"""
ER-P4: Dream cycle — consolidation, dedup, contradiction detection, decay.

Spec: ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md
     (lines 195, 215, 278, 299, 640, 687)

The dream cycle has FOUR sub-cycles that the cron runs at different cadences:

  DEDUP (daily)
    Find entities with the same `(type_id, lower(name))` that aren't
    already merged. Merge them into a single survivor (lowest id;
    deterministic), redirect all relationships and facts to the
    survivor, mark losers `status='merged'`, set `merged_into`.

  CONTRADICTION (daily)
    Find pairs of relationships on the same (source, target, type)
    where one has `valid_to` and the other doesn't but the
    `valid_from` ranges overlap. These can't both be true at the
    same time. Flag and return — does NOT auto-resolve (the source
    data is ambiguous, and a human-or-LLM review is the spec's
    intended path).

  DECAY (weekly)
    For each non-archived relationship with `weight > 0`, look at
    `COALESCE(last_accessed, updated_at)`. If it's older than
    `half_life_days` (default 7), apply exponential decay:
        weight *= exp(-Δt * ln(2) / half_life_days)
    Archive (status='archived', weight=0) any that drop below
    `archive_threshold` (default 0.1).

    `last_accessed` is set explicitly by callers via `touch_entity()`.
    Until P3 traversal starts updating it, the cycle falls back to
    `updated_at` (the last time the entity was modified). This is
    conservative: an entity you extracted last month but never
    looked at again still decays, which is the right default.

  ENTITY_DECAY (weekly, runs AFTER decay)
    Entity confidence decay + fact decay. For each active entity,
    apply the same exponential decay to `confidence` using the
    entity's `last_accessed` (or `updated_at` as fallback).
    Entities below `archive_threshold` get `status='archived'`
    and their relationships are archived too.
    Also decays `entity_facts.confidence` using the parent
    entity's last_accessed as a proxy.

The 4 sub-cycles share one DB connection. They are run in this
order: dedup first (so contradictions fire on the merged graph),
contradiction next (lightweight read-only), decay next (touches
relationship weights), entity_decay last (touches entity confidence
and cascades to relationships).

Usage:
    python3 -m lib.ichor.entities.dream --cycle=dedup --execute
    python3 -m lib.ichor.entities.dream --cycle=dedup,contradiction --execute
    python3 -m lib.ichor.entities.dream --cycle=all --execute
    python3 -m lib.ichor.entities.dream --cycle=decay --half-life-days=7 --execute
    python3 -m lib.ichor.entities.dream --cycle=entity_decay --execute

    from lib.ichor.entities import run_dream_cycle
    report = run_dream_cycle(cycles=("dedup", "contradiction"), dry_run=False)

Cron integration (per build list):
    ichor-dream.service + .timer           daily 03:30 UTC  (dedup, contradiction)
    ichor-dream-decay.service + .timer     weekly Sun 04:00 UTC  (decay, entity_decay)
    Both 30 minutes after ichor-tick at 03:00, so they run in
    sequence and the decay is off-peak.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.ichor.entities.schema import DB_PATH

logger = logging.getLogger("ichor.entities.dream")

DREAM_VERSION = "1.0.0"

# Decay defaults. Spec says "weight *= 0.9 per week of no access" which
# corresponds to half_life_days = 7 / log2(1/0.9) ≈ 66 days. But that's
# very slow decay. Build list says "<0.1 archive" which implies much
# faster decay. Use 7 days half-life (matches the spec's "per week"
# cadence) so an untouched relationship halves in a week, and reaches
# the 0.1 archive threshold in ~3.3 weeks (7 * log2(10) ≈ 23 days).
DEFAULT_HALF_LIFE_DAYS = 7
DEFAULT_ARCHIVE_THRESHOLD = 0.1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection to the entity DB.

    Defaults to the live ~/.hermes/ichor.db. Tests pass a temp path.
    Foreign keys are enforced so the relationship-table references
    (entities.id) actually redirect on merge.
    """
    path = Path(db_path) if db_path else DB_PATH
    if not path.exists():
        raise FileNotFoundError(f"Ichor DB not found at {path}")
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _now_iso() -> str:
    """Current UTC time as ISO 8601 string. Matches SQLite's
    `datetime('now')` format so we can compare strings directly."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _parse_db_datetime(iso_str: str) -> datetime | None:
    """Parse a SQLite datetime('now') string. Defensive: returns None
    on failure rather than raising, so decay can skip junk data."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    # SQLite's datetime('now') is 'YYYY-MM-DD HH:MM:SS' in UTC. Strip
    # any trailing ' UTC' marker that some callers might add.
    s = iso_str.strip()
    if s.endswith(" UTC"):
        s = s[:-4]
    # Drop subseconds if any ('YYYY-MM-DD HH:MM:SS.fff' -> first 19 chars)
    if len(s) > 19 and s[19] in (".", ","):
        s = s[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _days_between(iso_later: str, iso_earlier: str) -> float:
    """Days between two SQLite datetime strings. Defensive: if either
    string is unparseable, return 0 (treat as 'now' to avoid spurious
    decay on junk data)."""
    later = _parse_db_datetime(iso_later)
    earlier = _parse_db_datetime(iso_earlier)
    if later is None or earlier is None:
        return 0.0
    delta = later - earlier
    return delta.total_seconds() / 86400.0


def touch_entity(con: sqlite3.Connection, entity_id: int) -> None:
    """Update `entities.last_accessed` to now.

    Callers (P3 traversal, search, etc.) invoke this whenever an
    entity is observed. Until they wire it up, the dream cycle
    falls back to `updated_at` for decay — so absence of touch
    calls just makes decay slightly more aggressive, not broken.
    """
    con.execute(
        "UPDATE entities SET last_accessed = datetime('now') "
        "WHERE id = ? AND status = 'active'",
        (entity_id,),
    )


# ---------------------------------------------------------------------------
# Sub-cycle 1: dedup
# ---------------------------------------------------------------------------

def _find_dedup_groups(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Find groups of active entities that share (type_id, lower(name)).

    Groups must have >= 2 members to be candidates. The lowest id
    in each group is the survivor (deterministic — no LLM needed
    to pick a winner).
    """
    rows = con.execute(
        "SELECT type_id, LOWER(name) AS lname, COUNT(*) AS n, "
        "       MIN(id) AS survivor_id "
        "FROM entities "
        "WHERE status = 'active' AND name IS NOT NULL AND name != '' "
        "GROUP BY type_id, LOWER(name) "
        "HAVING COUNT(*) > 1"
    ).fetchall()
    return [dict(r) for r in rows]


def _members_of_group(con: sqlite3.Connection, type_id: str, lname: str) -> list[int]:
    """All active entity ids in a (type_id, lower(name)) group, ordered ascending."""
    rows = con.execute(
        "SELECT id FROM entities "
        "WHERE type_id = ? AND LOWER(name) = ? AND status = 'active' "
        "ORDER BY id ASC",
        (type_id, lname),
    ).fetchall()
    return [r["id"] for r in rows]


def _redirect_relationships(con: sqlite3.Connection, loser_id: int, survivor_id: int) -> int:
    """Redirect relationships pointing at the loser to the survivor.

    The schema has UNIQUE(type_id, source_id, target_id, valid_from)
    so naive UPDATE could collide. We DELETE the loser's relationships
    (the survivor is the canonical owner) and re-insert them pointing
    at the survivor, but ONLY if the survivor doesn't already have
    the same edge.

    Returns: number of relationships redirected.
    """
    if loser_id == survivor_id:
        return 0, 0
    redirected = 0
    duplicates_deleted = 0
    # Pull all edges that touch the loser
    edges = con.execute(
        "SELECT id, type_id, source_id, target_id, confidence, weight, "
        "       provenance, source_ref, valid_from, valid_to "
        "FROM relationships "
        "WHERE source_id = ? OR target_id = ?",
        (loser_id, loser_id),
    ).fetchall()
    for e in edges:
        new_source = survivor_id if e["source_id"] == loser_id else e["source_id"]
        new_target = survivor_id if e["target_id"] == loser_id else e["target_id"]
        # If redirecting the edge to itself, skip (was self-loop on loser)
        if new_source == new_target:
            con.execute("DELETE FROM relationships WHERE id = ?", (e["id"],))
            continue
        # Check if the survivor already has the same edge
        existing = con.execute(
            "SELECT id FROM relationships "
            "WHERE type_id = ? AND source_id = ? AND target_id = ? "
            "  AND (valid_from IS ? OR valid_from = ?) "
            "  AND (valid_to IS ? OR valid_to = ?)",
            (e["type_id"], new_source, new_target,
             e["valid_from"], e["valid_from"],
             e["valid_to"], e["valid_to"]),
        ).fetchone()
        if existing:
            # Survivor already has this edge — drop the duplicate
            con.execute("DELETE FROM relationships WHERE id = ?", (e["id"],))
        else:
            con.execute(
                "UPDATE relationships "
                "SET source_id = ?, target_id = ?, "
                "    provenance = CASE WHEN provenance = 'dream_cycle_merge' "
                "                      THEN provenance "
                "                      ELSE 'dream_cycle_merge' END "
                "WHERE id = ?",
                (new_source, new_target, e["id"]),
            )
            redirected += 1
    return redirected, duplicates_deleted


def _redirect_facts(con: sqlite3.Connection, loser_id: int, survivor_id: int) -> int:
    """Redirect facts from the loser to the survivor, deduping by (key, value).

    The schema doesn't UNIQUE facts — multiple facts per (entity, key)
    are allowed (think: mrr over time). We only redirect facts the
    survivor doesn't already have. Returns: number of facts redirected.
    """
    redirected = 0
    duplicates_deleted = 0
    facts = con.execute(
        "SELECT key, value, type, confidence, valid_from, valid_to "
        "FROM entity_facts WHERE entity_id = ?",
        (loser_id,),
    ).fetchall()
    for f in facts:
        existing = con.execute(
            "SELECT 1 FROM entity_facts "
            "WHERE entity_id = ? AND key = ? AND value = ? LIMIT 1",
            (survivor_id, f["key"], f["value"]),
        ).fetchone()
        if existing:
            # Drop duplicate
            con.execute(
                "DELETE FROM entity_facts WHERE entity_id = ? "
                "AND key = ? AND value = ?",
                (loser_id, f["key"], f["value"]),
            )
            duplicates_deleted += 1
        else:
            con.execute(
                "UPDATE entity_facts SET entity_id = ? WHERE entity_id = ? "
                "AND key = ? AND value = ?",
                (survivor_id, loser_id, f["key"], f["value"]),
            )
            redirected += 1
    return redirected, duplicates_deleted


def dedup(con: sqlite3.Connection, *, dry_run: bool = False) -> dict[str, Any]:
    """Merge duplicate entities within the same type.

    Returns:
        {
            "groups_found": int,      # distinct (type, name) duplicates
            "merges_applied": int,    # entities that got merged
            "relationships_redirected": int,
            "facts_redirected": int,
            "dry_run": bool,
        }
    """
    groups = _find_dedup_groups(con)
    merges_applied = 0
    rels_redirected = 0
    rels_duplicates_deleted = 0
    facts_redirected = 0
    facts_duplicates_deleted = 0
    details: list[dict[str, Any]] = []

    for g in groups:
        members = _members_of_group(con, g["type_id"], g["lname"])
        survivor = min(members)
        losers = [m for m in members if m != survivor]
        for loser in losers:
            details.append({
                "type_id": g["type_id"],
                "name": g["lname"],
                "survivor_id": survivor,
                "loser_id": loser,
            })
            if not dry_run:
                rr, dd = _redirect_relationships(con, loser, survivor)
                rels_redirected += rr
                rels_duplicates_deleted += dd
                fr, fd = _redirect_facts(con, loser, survivor)
                facts_redirected += fr
                facts_duplicates_deleted += fd
                con.execute(
                    "UPDATE entities "
                    "SET status = 'merged', merged_into = ?, "
                    "    updated_at = datetime('now') "
                    "WHERE id = ?",
                    (survivor, loser),
                )
                # Log the merge in extraction_log (provenance)
                con.execute(
                    "INSERT INTO extraction_log "
                    "  (entity_id, method, source_text, confidence) "
                    "VALUES (?, 'dream_cycle', ?, 1.0)",
                    (loser, json.dumps({
                        "action": "merge",
                        "merged_into": survivor,
                        "reason": "dream_dedup",
                    })),
                )
                merges_applied += 1
    if not dry_run:
        con.commit()
    return {
        "groups_found": len(groups),
        "merges_applied": merges_applied,
        "relationships_redirected": rels_redirected,
        "relationships_duplicates_deleted": rels_duplicates_deleted,
        "facts_redirected": facts_redirected,
        "facts_duplicates_deleted": facts_duplicates_deleted,
        "details": details,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Sub-cycle 2: contradiction detection
# ---------------------------------------------------------------------------

def _find_overlapping_windows(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Find pairs of relationships with the same (type, source, target)
    whose valid_from ranges overlap. Two such relationships cannot
    both be true simultaneously (in the temporal sense).

    "Overlap" definition: r1.valid_from <= r2.valid_to (or r2 has
    no valid_to, meaning still-true) AND r2.valid_from <= r1.valid_to
    (or r1 has no valid_to).

    Returns: list of {r1_id, r2_id, type_id, source_id, target_id,
                      r1_valid_from, r1_valid_to, r2_valid_from,
                      r2_valid_to, reason}
    """
    rows = con.execute(
        "SELECT a.id AS a_id, b.id AS b_id, a.type_id, "
        "       a.source_id, a.target_id, "
        "       a.valid_from AS a_vf, a.valid_to AS a_vt, "
        "       b.valid_from AS b_vf, b.valid_to AS b_vt "
        "FROM relationships a "
        "JOIN relationships b ON a.type_id = b.type_id "
        "  AND a.source_id = b.source_id AND a.target_id = b.target_id "
        "  AND a.id < b.id "
        "WHERE a.valid_from IS NOT NULL "
        "  AND (a.valid_to IS NULL OR b.valid_from IS NULL OR b.valid_from <= a.valid_to) "
        "  AND (b.valid_to IS NULL OR a.valid_from IS NULL OR a.valid_from <= b.valid_to)"
    ).fetchall()
    return [dict(r) for r in rows]


def _find_value_conflicts(con: sqlite3.Connection) -> list[dict[str, Any]]:
    """Find entities with conflicting facts on the same key.

    Example: entity 'Acme' has two facts with key='valuation' and
    different values where neither has a valid_to (both still-true).
    """
    rows = con.execute(
        "SELECT a.entity_id, a.key, a.value AS a_value, a.valid_to AS a_vt, "
        "       b.id AS b_id, b.value AS b_value, b.valid_to AS b_vt "
        "FROM entity_facts a "
        "JOIN entity_facts b ON a.entity_id = b.entity_id AND a.key = b.key "
        "  AND a.id < b.id AND a.value != b.value "
        "WHERE a.valid_to IS NULL AND b.valid_to IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def detect_contradictions(
    con: sqlite3.Connection, *, dry_run: bool = False
) -> dict[str, Any]:
    """Scan for contradictions in the entity graph.

    Two flavors:
      1. Two relationships of the same (type, source, target) with
         overlapping valid_from ranges (temporal conflict).
      2. Two facts of the same (entity, key) with different values
         both still valid (value conflict).

    Returns: {
        "relationship_conflicts": [list],
        "fact_conflicts": [list],
        "total": int,
        "dry_run": bool,
    }
    """
    rel_conflicts = _find_overlapping_windows(con)
    fact_conflicts = _find_value_conflicts(con)
    return {
        "relationship_conflicts": rel_conflicts,
        "fact_conflicts": fact_conflicts,
        "relationship_conflicts_count": len(rel_conflicts),
        "fact_conflicts_count": len(fact_conflicts),
        "total": len(rel_conflicts) + len(fact_conflicts),
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Sub-cycle 3: relationship decay
# ---------------------------------------------------------------------------

def _relationships_to_decay(
    con: sqlite3.Connection, *, half_life_days: float
) -> list[dict[str, Any]]:
    """List active relationships that are old enough to start decaying.

    "Old enough" = the entity (or the relationship's `updated_at`
    as fallback) hasn't been touched in `half_life_days` days. We
    use a generous threshold: only the relationships whose
    source-or-target entity is older than half_life_days are
    candidates. This prevents freshly-extracted relationships from
    being immediately decayed by the next tick.
    """
    cutoff = _now_iso()  # We just need entities with NULL last_accessed
    # Pull all active relationships
    rows = con.execute(
        "SELECT r.id, r.weight, r.updated_at, r.source_id, r.target_id, "
        "       se.last_accessed AS src_la, se.updated_at AS src_ua, "
        "       se.confidence AS src_conf, "
        "       te.last_accessed AS tgt_la, te.updated_at AS tgt_ua, "
        "       te.confidence AS tgt_conf "
        "FROM relationships r "
        "JOIN entities se ON r.source_id = se.id "
        "JOIN entities te ON r.target_id = te.id "
        "WHERE r.weight > 0"
    ).fetchall()
    return [dict(r) for r in rows]


def decay(
    con: sqlite3.Connection,
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    archive_threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply exponential decay to untouched relationships.

    For each non-archived relationship with weight > 0:
      - effective_last_access = max(source.last_accessed, target.last_accessed)
        (a relationship is "used" if either endpoint was recently touched)
        Fall back to source.updated_at if no last_accessed.
      - dt = days since effective_last_access
      - if dt > half_life_days: new_weight = weight * exp(-dt * ln(2) / half_life_days)
      - if new_weight < archive_threshold: weight = 0, mark archived

    Returns: {
        "considered": int,   # total relationships evaluated
        "decayed": int,      # had their weight reduced
        "archived": int,     # dropped below threshold
        "skipped_fresh": int,  # too fresh to decay
        "dry_run": bool,
    }
    """
    if half_life_days <= 0:
        raise ValueError("half_life_days must be > 0")
    if not 0 < archive_threshold < 1:
        raise ValueError("archive_threshold must be in (0, 1)")

    rows = _relationships_to_decay(con, half_life_days=half_life_days)
    considered = len(rows)
    decayed = 0
    archived = 0
    skipped_fresh = 0

    # Half-life constant
    k = math.log(2) / half_life_days

    for r in rows:
        # Effective last-access: max of source and target's last_accessed
        # (or their updated_at as fallback)
        src_la = r["src_la"] or r["src_ua"]
        tgt_la = r["tgt_la"] or r["tgt_ua"]
        # Use the MORE RECENT of the two — if either endpoint was
        # touched recently, the relationship is still "in use"
        effective_la = max(src_la or "", tgt_la or "")
        if not effective_la:
            skipped_fresh += 1
            continue
        delta_days = _days_between(_now_iso(), effective_la)
        if delta_days < half_life_days:
            skipped_fresh += 1
            continue
        new_weight = r["weight"] * math.exp(-k * delta_days)
        if new_weight < archive_threshold:
            new_weight = 0.0
            archived += 1
        decayed += 1
        if not dry_run and abs(new_weight - r["weight"]) > 1e-9:
            if new_weight == 0.0:
                # Archive: zero weight and mark entities as archived
                con.execute(
                    "UPDATE relationships SET weight = 0, "
                    "  provenance = 'dream_decay_archived' WHERE id = ?",
                    (r["id"],),
                )
            else:
                con.execute(
                    "UPDATE relationships SET weight = ? WHERE id = ?",
                    (new_weight, r["id"]),
                )
    if not dry_run:
        con.commit()
    return {
        "considered": considered,
        "decayed": decayed,
        "archived": archived,
        "skipped_fresh": skipped_fresh,
        "half_life_days": half_life_days,
        "archive_threshold": archive_threshold,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Sub-cycle 4: entity + fact confidence decay
# ---------------------------------------------------------------------------

def _entities_to_decay(
    con: sqlite3.Connection, *, half_life_days: float
) -> list[dict[str, Any]]:
    """List active entities that haven't been touched recently."""
    rows = con.execute(
        "SELECT id, name, type_id, confidence, "
        "       last_accessed, updated_at "
        "FROM entities "
        "WHERE status = 'active'"
    ).fetchall()
    return [dict(r) for r in rows]


def _entity_facts_to_decay(
    con: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """List active facts whose parent entity hasn't been touched."""
    rows = con.execute(
        "SELECT f.id, f.entity_id, f.key, f.value, f.confidence, "
        "       f.valid_to, "
        "       e.last_accessed AS e_la, e.updated_at AS e_ua "
        "FROM entity_facts f "
        "JOIN entities e ON f.entity_id = e.id "
        "WHERE f.valid_to IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def entity_decay(
    con: sqlite3.Connection,
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    archive_threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply exponential decay to entity confidence and archive stale ones.

    Also cascades to entity_facts (decay confidence) and relationships
    (archived when their entity is archived).

    Returns: {
        "entities_considered": int,
        "entities_decayed": int,
        "entities_archived": int,
        "facts_considered": int,
        "facts_decayed": int,
        "facts_archived": int,
        "relationships_archived": int,
        "dry_run": bool,
    }
    """
    k = math.log(2) / half_life_days
    now = _now_iso()

    # -- Entity decay --
    e_rows = _entities_to_decay(con, half_life_days=half_life_days)
    e_considered = len(e_rows)
    e_decayed = 0
    e_archived = 0
    rels_archived = 0

    for r in e_rows:
        effective_la = r["last_accessed"] or r["updated_at"]
        if not effective_la:
            continue
        delta_days = _days_between(now, effective_la)
        if delta_days < half_life_days:
            continue
        new_conf = r["confidence"] * math.exp(-k * delta_days)
        if new_conf < archive_threshold:
            e_archived += 1
            if not dry_run:
                con.execute(
                    "UPDATE entities SET status = 'archived', "
                    "  confidence = 0.0, updated_at = ? "
                    "WHERE id = ?",
                    (now, r["id"]),
                )
                con.execute(
                    "UPDATE relationships SET weight = 0, "
                    "  provenance = 'dream_entity_archived' "
                    "WHERE (source_id = ? OR target_id = ?) "
                    "  AND weight > 0",
                    (r["id"], r["id"]),
                )
        else:
            e_decayed += 1
            if not dry_run:
                con.execute(
                    "UPDATE entities SET confidence = ?, updated_at = ? "
                    "WHERE id = ?",
                    (round(new_conf, 4), now, r["id"]),
                )

    if not dry_run:
        rels_archived = con.execute(
            "SELECT changes()"
        ).fetchone()[0]

    # -- Fact decay --
    f_rows = _entity_facts_to_decay(con)
    f_considered = len(f_rows)
    f_decayed = 0
    f_archived = 0

    for f in f_rows:
        effective_la = f["e_la"] or f["e_ua"]
        if not effective_la:
            continue
        delta_days = _days_between(now, effective_la)
        if delta_days < half_life_days:
            continue
        new_conf = f["confidence"] * math.exp(-k * delta_days)
        if new_conf < archive_threshold:
            f_archived += 1
            if not dry_run:
                con.execute(
                    "UPDATE entity_facts SET valid_to = ?, "
                    "  confidence = 0.0 "
                    "WHERE id = ?",
                    (now, f["id"]),
                )
        else:
            f_decayed += 1
            if not dry_run:
                con.execute(
                    "UPDATE entity_facts SET confidence = ? WHERE id = ?",
                    (round(new_conf, 4), f["id"]),
                )

    if not dry_run:
        con.commit()

    return {
        "entities_considered": e_considered,
        "entities_decayed": e_decayed,
        "entities_archived": e_archived,
        "facts_considered": f_considered,
        "facts_decayed": f_decayed,
        "facts_archived": f_archived,
        "relationships_archived": rels_archived,
        "dry_run": dry_run,
    }


# ---------------------------------------------------------------------------
# Cycle orchestrator
# ---------------------------------------------------------------------------

def run_dream_cycle(
    cycles: tuple[str, ...] = ("dedup", "contradiction"),
    *,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    archive_threshold: float = DEFAULT_ARCHIVE_THRESHOLD,
    dry_run: bool = False,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run the requested sub-cycles in order.

    Args:
        cycles: any combination of "dedup", "contradiction", "decay", "entity_decay".
            Default: ("dedup", "contradiction") — the daily sub-cycles.
            Use ("decay", "entity_decay") for the weekly decay run.
        half_life_days: for the decay cycles. Default 7 (per spec).
        archive_threshold: for the decay cycles. Default 0.1 (per spec).
        dry_run: if True, no writes happen, only reports.

    Returns:
        {
            "version": str,
            "started_at": ISO 8601 UTC,
            "duration_seconds": float,
            "cycles": {cycle_name: cycle_output, ...},
            "dry_run": bool,
        }
    """
    import time

    valid = {"dedup", "contradiction", "decay", "entity_decay"}
    unknown = set(cycles) - valid
    if unknown:
        raise ValueError(
            f"Unknown cycles: {unknown}. Valid: {sorted(valid)}"
        )

    t0 = time.perf_counter()
    started_at = _now_iso()
    out: dict[str, Any] = {
        "version": DREAM_VERSION,
        "started_at": started_at,
        "duration_seconds": 0.0,
        "cycles": {},
        "dry_run": dry_run,
    }

    con = _connect(db_path)
    try:
        if "dedup" in cycles:
            out["cycles"]["dedup"] = dedup(con, dry_run=dry_run)
        if "contradiction" in cycles:
            out["cycles"]["contradiction"] = detect_contradictions(
                con, dry_run=dry_run
            )
        if "decay" in cycles:
            out["cycles"]["decay"] = decay(
                con,
                half_life_days=half_life_days,
                archive_threshold=archive_threshold,
                dry_run=dry_run,
            )
        if "entity_decay" in cycles:
            out["cycles"]["entity_decay"] = entity_decay(
                con,
                half_life_days=half_life_days,
                archive_threshold=archive_threshold,
                dry_run=dry_run,
            )
    finally:
        con.close()

    out["duration_seconds"] = round(time.perf_counter() - t0, 3)
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    """CLI: `python3 -m lib.ichor.entities.dream [--cycle=...] [--execute]`

    Examples:
        # Dry-run dedup + contradiction (default)
        python3 -m lib.ichor.entities.dream

        # Apply dedup + contradiction to the live DB
        python3 -m lib.ichor.entities.dream --execute

        # Apply all four (dedup, contradiction, decay, entity_decay)
        python3 -m lib.ichor.entities.dream --cycle=all --execute

        # Just the weekly decay + entity_decay
        python3 -m lib.ichor.entities.dream --cycle=decay,entity_decay \
            --half-life-days=14 --execute
    """
    parser = argparse.ArgumentParser(
        description="Ichor ER Graph dream cycle (dedup / contradiction / decay / entity_decay).",
    )
    parser.add_argument(
        "--cycle",
        default="dedup,contradiction",
        help=(
            "Comma-separated sub-cycles to run. "
            "Valid: dedup, contradiction, decay, entity_decay, all. "
            "Default: dedup,contradiction (the daily pair)."
        ),
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Apply changes (default: dry-run, no writes).",
    )
    parser.add_argument(
        "--half-life-days", type=float, default=DEFAULT_HALF_LIFE_DAYS,
        help=f"Decay half-life in days. Default: {DEFAULT_HALF_LIFE_DAYS}.",
    )
    parser.add_argument(
        "--archive-threshold", type=float, default=DEFAULT_ARCHIVE_THRESHOLD,
        help=f"Archive below this weight. Default: {DEFAULT_ARCHIVE_THRESHOLD}.",
    )
    args = parser.parse_args()

    if args.cycle == "all":
        cycles = ("dedup", "contradiction", "decay", "entity_decay")
    else:
        cycles = tuple(c.strip() for c in args.cycle.split(",") if c.strip())

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    result = run_dream_cycle(
        cycles=cycles,
        half_life_days=args.half_life_days,
        archive_threshold=args.archive_threshold,
        dry_run=not args.execute,
    )
    # Print summary
    mode = "DRY-RUN" if result["dry_run"] else "EXECUTED"
    print(f"Ichor Dream v{result['version']} — {mode}")
    print(f"Duration: {result['duration_seconds']:.2f}s")
    print(f"Cycles:   {', '.join(result['cycles'].keys())}")
    for name, out in result["cycles"].items():
        if name == "dedup":
            print(
                f"  dedup:        groups={out['groups_found']} "
                f"merges={out['merges_applied']} "
                f"rels_redirected={out['relationships_redirected']} "
                f"facts_redirected={out['facts_redirected']}"
            )
        elif name == "contradiction":
            print(
                f"  contradiction: rels={out['relationship_conflicts_count']} "
                f"facts={out['fact_conflicts_count']} "
                f"total={out['total']}"
            )
        elif name == "decay":
            print(
                f"  decay:        considered={out['considered']} "
                f"decayed={out['decayed']} "
                f"archived={out['archived']} "
                f"skipped_fresh={out['skipped_fresh']}"
            )
        elif name == "entity_decay":
            print(
                f"  entity_decay: entities_considered={out['entities_considered']} "
                f"entities_decayed={out['entities_decayed']} "
                f"entities_archived={out['entities_archived']} "
                f"facts_considered={out['facts_considered']} "
                f"facts_decayed={out['facts_decayed']} "
                f"facts_archived={out['facts_archived']} "
                f"rels_archived_cascade={out['relationships_archived']}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
