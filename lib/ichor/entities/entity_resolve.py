"""Ichor Phase 2D — Entity Resolution (dedup pass).

Closes the "Tallon as 3 entities" problem: entities extracted by the
L0/L1/L2 extractors accumulate near-duplicates ("Tallon", "K. Tallon",
"konan tallon") with no merge path.  This module adds a deterministic
alias-normalization + similarity merge pass, so a single canonical
entity gets all its claims.

Spec: ~/athenaeum/Codex-God-thoth/research/ichor-mnemos-upgrade-plan/SPEC.md §2D
      (ported from the mnelo entity_resolve.py pattern)

Algorithm (three stages):

  1. Alias normalization — `normalize(name)`:
       lowercase → strip punctuation → split into a token set
       (sorted, joined by spaces).  Single-character tokens (initials
       like "K.") are *kept* so that "A. Smith" vs "B. Smith" stay
       distinct.

  2. Similarity — `similarity(a, b)`:
       Primary signal is `difflib.SequenceMatcher.ratio()` over the
       normalized names (per spec).  Two deterministic guards on top:

         * Generational suffixes (jr/sr/ii/iii/...) present on one side
           only → hard-capped at 0.5.  "John Smith" and "John Smith Jr"
           are *different people*; the suffix must never be absorbed.
         * Token containment — when the smaller token set is fully
           contained in the larger (e.g. "Tallon" ⊂ "konan tallon"),
           the score lifts to 1.0.  This is what lets a fuller-name
           variant merge into the short canonical form.
         * Differing single-letter initials ("A. Smith" vs "B. Smith")
           cap the score at 0.8 so initial-only differences do not merge.

  3. Merge — `run()`:
       Entities are grouped by type_id (we never merge across types),
       pairs with similarity >= threshold (default 0.85) are unioned
       (connected components; canonical = lowest entity id), and each
       loser is folded into the canonical:
         * alias rows inserted into entity_aliases (every cluster name
           variant resolves to the canonical),
         * loser relationships re-pointed to the canonical (UNIQUE-safe),
         * loser entity_facts re-pointed to the canonical (deduped),
         * loser marked status='merged' with merged_into=canonical —
           the Phase 3B trigger `expire_relations_on_entity_supersede`
           fires, but by then the loser's edges are already re-pointed,
           so it is a no-op (relationships stay valid on the canonical),
         * provenance logged in extraction_log.

       Dry-run mode (`dry_run=True`) reports candidates/merges without
       changing anything.  Cross-type similar pairs are reported as
       "collisions" (refused merges).

Interfaces:
    run(dry_run=True, threshold=0.85, db_path=None) -> dict
    normalize(name) -> str
    similarity(a, b) -> float
    resolve(alias, db_path=None) -> int | None

Cron hook: lib/ichor_daily_maintenance.run() runs a dry-run pre-pass
before decay.  On-demand apply: MCP tool `ichor_entity_resolve(apply)`.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

from lib.ichor.entities.schema import DB_PATH, get_conn, migrate

logger = logging.getLogger("ichor.entities.entity_resolve")

DEFAULT_THRESHOLD = 0.85

# Generational suffixes mark a DIFFERENT person (father vs son, Jr vs Sr).
# A fuzzy containment merge must never absorb them.
_SUFFIX_TOKENS = {
    "jr", "sr", "jnr", "snr", "ii", "iii", "iv", "v", "vi",
    "junior", "senior", "md", "phd", "esq",
}

_PUNCT_RE = re.compile(r"[^a-z0-9]+")


# ---------------------------------------------------------------------------
# Stage 1 + 2: normalization and similarity
# ---------------------------------------------------------------------------

def normalize(name: str) -> str:
    """Canonical form: lowercase → strip punctuation → sorted token set.

    Single-character tokens (initials) are kept so that "A. Smith" and
    "B. Smith" remain distinguishable.
    """
    if not name:
        return ""
    s = str(name).lower()
    s = _PUNCT_RE.sub(" ", s)
    tokens = sorted(set(s.split()))
    return " ".join(tokens)


def similarity(a: str, b: str) -> float:
    """Similarity in [0, 1] between two entity names.

    Primary: difflib.SequenceMatcher ratio on normalized names (spec).
    Guards (deterministic, documented in the module docstring):
      * generational suffix on one side only → 0.5 (never merge Jr/Sr)
      * full token containment of the smaller set → 1.0
      * differing single-letter initials → cap at 0.8
    """
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())

    # Generational suffix mismatch: different person, hard cap.
    if (_SUFFIX_TOKENS & ta) != (_SUFFIX_TOKENS & tb):
        return 0.5

    # Token containment: smaller set fully explained by the larger one
    # (e.g. "Tallon" ⊂ "konan tallon", "Tallon" ⊂ "K. Tallon").
    overlap = len(ta & tb)
    smaller = min(len(ta), len(tb))
    if smaller and overlap == smaller:
        return 1.0

    r = difflib.SequenceMatcher(None, na, nb).ratio()

    # Differing single-letter initials: "A. Smith" vs "B. Smith" are
    # most likely different people — keep below the default threshold.
    diff = (ta - tb) | (tb - ta)
    if any(len(t) == 1 for t in diff):
        return min(r, 0.8)
    return r


# ---------------------------------------------------------------------------
# Stage 3: merge application
# ---------------------------------------------------------------------------

def _apply_merge(conn: sqlite3.Connection, canonical_id: int, loser_id: int) -> None:
    """Fold `loser_id` into `canonical_id` (relationships, facts, aliases).

    ORDER MATTERS: relationships/facts are re-pointed BEFORE the loser is
    marked merged (status='merged', merged_into=...).  The Phase 3B
    trigger `expire_relations_on_entity_supersede` fires on the
    merged_into update, but by then the loser owns no open edges, so the
    trigger is a no-op and the (re-pointed) edges stay valid on the
    canonical.
    """
    if canonical_id == loser_id:
        return

    # ---- relationships: re-point to canonical, UNIQUE-safe ---------------
    edges = conn.execute(
        "SELECT id, type_id, source_id, target_id, valid_from, valid_to "
        "FROM relationships WHERE source_id = ? OR target_id = ?",
        (loser_id, loser_id),
    ).fetchall()
    for e in edges:
        new_source = canonical_id if e["source_id"] == loser_id else e["source_id"]
        new_target = canonical_id if e["target_id"] == loser_id else e["target_id"]
        if new_source == new_target:
            # Self-loop on the loser collapses to nothing.
            conn.execute("DELETE FROM relationships WHERE id = ?", (e["id"],))
            continue
        dup = conn.execute(
            "SELECT id FROM relationships "
            "WHERE type_id = ? AND source_id = ? AND target_id = ? "
            "  AND (valid_from IS ? OR valid_from = ?) "
            "  AND (valid_to IS ? OR valid_to = ?)",
            (
                e["type_id"], new_source, new_target,
                e["valid_from"], e["valid_from"],
                e["valid_to"], e["valid_to"],
            ),
        ).fetchone()
        if dup is not None:
            conn.execute("DELETE FROM relationships WHERE id = ?", (e["id"],))
        else:
            conn.execute(
                "UPDATE relationships SET source_id = ?, target_id = ?, "
                "provenance = CASE WHEN provenance = 'entity_resolve_merge' "
                "                   THEN provenance "
                "                   ELSE 'entity_resolve_merge' END "
                "WHERE id = ?",
                (new_source, new_target, e["id"]),
            )

    # ---- entity_facts: re-point to canonical, dedup by (key, value) -------
    facts = conn.execute(
        "SELECT key, value, type, confidence, valid_from, valid_to "
        "FROM entity_facts WHERE entity_id = ?",
        (loser_id,),
    ).fetchall()
    for f in facts:
        dup = conn.execute(
            "SELECT 1 FROM entity_facts WHERE entity_id = ? AND key = ? AND value = ? LIMIT 1",
            (canonical_id, f["key"], f["value"]),
        ).fetchone()
        if dup is not None:
            conn.execute(
                "DELETE FROM entity_facts WHERE entity_id = ? AND key = ? AND value = ?",
                (loser_id, f["key"], f["value"]),
            )
        else:
            conn.execute(
                "UPDATE entity_facts SET entity_id = ? "
                "WHERE entity_id = ? AND key = ? AND value = ?",
                (canonical_id, loser_id, f["key"], f["value"]),
            )

    # ---- aliases: every cluster name variant → canonical -----------------
    loser_row = conn.execute(
        "SELECT name, aliases FROM entities WHERE id = ?", (loser_id,)
    ).fetchone()
    canon_row = conn.execute(
        "SELECT name, aliases FROM entities WHERE id = ?", (canonical_id,)
    ).fetchone()
    alias_set: set[str] = set()
    for raw in (canon_row["name"], loser_row["name"]):
        if raw and str(raw).strip():
            alias_set.add(str(raw).strip())
    for raw in (canon_row["aliases"], loser_row["aliases"]):
        try:
            for a in json.loads(raw or "[]"):
                if isinstance(a, str) and a.strip():
                    alias_set.add(a.strip())
        except Exception as exc:  # noqa: BLE001 — junk JSON must not abort merge
            logger.debug("unparseable aliases JSON: %s", exc)
    for alias in sorted(alias_set):
        conn.execute(
            "INSERT OR IGNORE INTO entity_aliases (canonical_entity_id, alias) VALUES (?, ?)",
            (canonical_id, alias),
        )
    conn.execute(
        "UPDATE entities SET aliases = ? WHERE id = ?",
        (json.dumps(sorted(alias_set)), canonical_id),
    )

    # ---- provenance --------------------------------------------------------
    conn.execute(
        "INSERT INTO extraction_log (entity_id, method, source_text, confidence) "
        "VALUES (?, 'entity_resolve', ?, 1.0)",
        (
            loser_id,
            json.dumps({
                "action": "merge",
                "merged_into": canonical_id,
                "reason": "fuzzy_similarity",
            }),
        ),
    )

    # ---- mark loser merged (fires the 3B trigger; edges already gone) -----
    conn.execute(
        "UPDATE entities SET status = 'merged', merged_into = ?, "
        "updated_at = datetime('now') WHERE id = ?",
        (canonical_id, loser_id),
    )


# ---------------------------------------------------------------------------
# Stage 3: run (candidate discovery + union-find + merge)
# ---------------------------------------------------------------------------

def _run(conn: sqlite3.Connection, *, dry_run: bool, threshold: float) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT id, type_id, name FROM entities WHERE status = 'active' "
        "AND name IS NOT NULL AND name != '' ORDER BY id"
    ).fetchall()

    by_type: dict[str, list[sqlite3.Row]] = {}
    for r in rows:
        by_type.setdefault(r["type_id"], []).append(r)

    candidates: list[dict[str, Any]] = []
    collisions: list[dict[str, Any]] = []
    merges: list[dict[str, Any]] = []

    # Token pre-filter: two names whose normalized token sets are disjoint
    # cannot reach the similarity threshold (SequenceMatcher ratio on disjoint
    # token sets is ~0). Index entities by token so we only run the expensive
    # difflib comparison on pairs that share at least one token. This turns
    # the O(n^2) scan over the real corpus (13k+ entities) into a near-linear
    # pass — identical results, no false negatives (containment merges like
    # "Tallon" C "konan tallon" share tokens; Jr/Sr caps still apply).
    def _shared_token_pairs(rows_a: list[sqlite3.Row], rows_b: list[sqlite3.Row]) -> list[tuple[sqlite3.Row, sqlite3.Row]]:
        token_map: dict[str, list[sqlite3.Row]] = {}
        for r in rows_b:
            for tok in normalize(r["name"]).split():
                token_map.setdefault(tok, []).append(r)
        out: list[tuple[sqlite3.Row, sqlite3.Row]] = []
        seen: set[tuple[int, int]] = set()
        for ra in rows_a:
            ta = normalize(ra["name"]).split()
            if not ta:
                continue
            for tok in ta:
                for rb in token_map.get(tok, ()):
                    key = (ra["id"], rb["id"])
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((ra, rb))
        return out

    # Cross-type similar pairs (refused merges) are reported as collisions.
    type_names = list(by_type.keys())
    for i in range(len(type_names)):
        for j in range(i + 1, len(type_names)):
            for ea, eb in _shared_token_pairs(by_type[type_names[i]], by_type[type_names[j]]):
                sim = similarity(ea["name"], eb["name"])
                if sim >= threshold:
                    collisions.append({
                        "name_a": ea["name"],
                        "name_b": eb["name"],
                        "ratio": round(sim, 4),
                        "type_a": ea["type_id"],
                        "type_b": eb["type_id"],
                    })

    for _type_id, group in by_type.items():
        # Candidate pairs within the type (token-pre-filtered).
        pairs: list[tuple[sqlite3.Row, sqlite3.Row, float]] = []
        for a, b in _shared_token_pairs(group, group):
            if a["id"] == b["id"]:
                continue
            sim = similarity(a["name"], b["name"])
            if sim >= threshold:
                pairs.append((a, b, sim))
                candidates.append({
                    "name_a": a["name"],
                    "name_b": b["name"],
                    "ratio": round(sim, 4),
                    "type_id": _type_id,
                })

        if not pairs:
            continue

        # Union-find over the candidate graph; canonical = lowest id.
        parent = {e["id"]: e["id"] for e in group}

        def _find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(x: int, y: int) -> None:
            rx, ry = _find(x), _find(y)
            if rx != ry:
                parent[max(rx, ry)] = min(rx, ry)

        for a, b, _sim in pairs:
            _union(a["id"], b["id"])

        clusters: dict[int, list[int]] = {}
        for e in group:
            clusters.setdefault(_find(e["id"]), []).append(e["id"])

        for root, members in clusters.items():
            if len(members) < 2:
                continue
            canonical = root
            losers = sorted(m for m in members if m != canonical)
            for loser in losers:
                loser_name = next((e["name"] for e in group if e["id"] == loser), str(loser))
                canon_name = next((e["name"] for e in group if e["id"] == canonical), str(canonical))
                best_ratio = max(
                    (sim for a, b, sim in pairs
                     if {a["id"], b["id"]} == {canonical, loser}),
                    default=0.0,
                )
                merges.append({
                    "canonical_id": canonical,
                    "canonical_name": canon_name,
                    "loser_id": loser,
                    "loser_name": loser_name,
                    "ratio": round(best_ratio, 4),
                })
                if not dry_run:
                    _apply_merge(conn, canonical, loser)

    if not dry_run:
        conn.commit()

    return {
        "candidates": len(candidates),
        "merges": len(merges),
        "collisions": collisions,
        "threshold": threshold,
        "dry_run": dry_run,
        "details": merges,
    }


def _default_db_path() -> Path:
    """Resolve the default DB path at CALL time.

    entities.schema.DB_PATH is computed once at import time, which is
    wrong in test processes that patch HOME after import. Resolving here
    (Path.home() honors the HOME env var) keeps run()/resolve() pointed
    at the live DB in production and at the isolated temp DB in tests.
    """
    return Path.home() / ".hermes" / "ichor.db"


def run(dry_run: bool = True, threshold: float = DEFAULT_THRESHOLD, db_path=None) -> dict:
    """Run the entity-resolution dedup pass.

    Args:
        dry_run: report only, change nothing (default True).
        threshold: minimum similarity for a merge (default 0.85).
        db_path: override DB path (tests). Defaults to ~/.hermes/ichor.db.

    Returns:
        {"candidates": N, "merges": N,
         "collisions": [{name_a, name_b, ratio}],
         "threshold": float, "dry_run": bool, "details": [...]}
    """
    path = Path(db_path) if db_path is not None else _default_db_path()
    # Idempotent: guarantees the entity tables, entity_aliases and the
    # Phase 3B supersede trigger exist before any merge is applied.
    migrate(path)
    conn = get_conn(path)
    try:
        return _run(conn, dry_run=dry_run, threshold=float(threshold))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Alias → canonical resolution
# ---------------------------------------------------------------------------

def resolve(alias: str, db_path=None) -> int | None:
    """Resolve any alias/name variant to the canonical entity id.

    Lookup order:
      1. entity_aliases exact match
      2. entity_aliases case-insensitive match
      3. entities.name exact (case-insensitive), active first
      4. entities.aliases JSON containment
      5. merged entity name → merged_into (survivor)

    Returns the canonical entity id, or None when nothing matches.
    """
    a = str(alias or "").strip()
    if not a:
        return None
    path = Path(db_path) if db_path is not None else _default_db_path()
    migrate(path)
    conn = get_conn(path)
    try:
        row = conn.execute(
            "SELECT canonical_entity_id FROM entity_aliases WHERE alias = ? LIMIT 1",
            (a,),
        ).fetchone()
        if row is not None:
            return int(row["canonical_entity_id"])

        row = conn.execute(
            "SELECT canonical_entity_id FROM entity_aliases "
            "WHERE LOWER(alias) = LOWER(?) LIMIT 1",
            (a,),
        ).fetchone()
        if row is not None:
            return int(row["canonical_entity_id"])

        row = conn.execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(?) "
            "AND status = 'active' ORDER BY id LIMIT 1",
            (a,),
        ).fetchone()
        if row is not None:
            return int(row["id"])

        for r in conn.execute(
            "SELECT id, aliases FROM entities WHERE status = 'active'"
        ).fetchall():
            try:
                aliases = json.loads(r["aliases"] or "[]")
            except Exception:  # noqa: BLE001
                aliases = []
            lowered = {str(x).lower() for x in aliases if isinstance(x, str)}
            if a.lower() in lowered:
                return int(r["id"])

        row = conn.execute(
            "SELECT merged_into FROM entities WHERE LOWER(name) = LOWER(?) "
            "AND status = 'merged' AND merged_into IS NOT NULL LIMIT 1",
            (a,),
        ).fetchone()
        if row is not None:
            return int(row["merged_into"])
        return None
    finally:
        conn.close()


if __name__ == "__main__":
    import argparse
    import json as _json

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Ichor entity resolution (Phase 2D)")
    parser.add_argument("--execute", action="store_true", help="Apply merges (default: dry-run)")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Similarity threshold")
    args = parser.parse_args()
    print(_json.dumps(run(dry_run=not args.execute, threshold=args.threshold), indent=2))
