#!/usr/bin/env python3
"""Ichor relational recall — alias index mirror (completes Fix C).

Why
---
`entity_resolve.resolve()` consults `entity_aliases` first (exact, then
case-insensitive) and only then falls back to step 4: a full scan of every
active entity's `aliases` JSON — the measured ~85 ms miss path. 2,738 active
entities carry aliases JSON, but the index table held only 39 rows (Konan's
identity set from the Fix C seed), so every other nickname paid the scan.

What this does
--------------
Mirrors `entities.aliases` into `entity_aliases`, additively and idempotently:

  * one row per (canonical_entity_id, alias)
  * an alias already mapped to a DIFFERENT entity is skipped and reported —
    aliases are never stolen (an incumbent mapping is authoritative)
  * the entity's own name is not registered as its own alias (resolve() step 3
    already matches exact names case-insensitively)
  * **shadow guard**: an alias is not indexed when it is the literal NAME of
    another active entity that is strictly denser (more live edges) than the
    alias target. Loose aliases are noisy — "Pantheon MCP" lists `pantheon`,
    "thoth profile" lists `thoth` — and indexing those made `resolve('pantheon')`
    return a 1-edge stub instead of the 1,494-edge hub. The guard keeps
    genuinely useful aliases (`Cybermage` -> Konan, `Tallon` -> the person hub)
    while refusing to let a weaker facet capture a name that belongs to a
    stronger one.

`--prune-shadowing` removes rows that already violate the shadow rule (dry-run
by default; every deletion is listed for audit).

Dry-run by default. No entity is created, merged, or modified.

Usage
-----
    ~/.hermes/hermes-agent/.venv/bin/python3 scripts/ichor_alias_index_mirror.py
    ... --apply
    ... --prune-shadowing --apply      # clean up rows inserted before the guard
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_DB = Path("/home/konan/.hermes/ichor.db")

_JUNK = {"", "—", "-", "n/a", "none", "null"}

_DEGREE_SQL = (
    "SELECT (SELECT COUNT(*) FROM relationships WHERE source_id = ? AND valid_to IS NULL) "
    "     + (SELECT COUNT(*) FROM relationships WHERE target_id = ? AND valid_to IS NULL)"
)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _live_degree(conn: sqlite3.Connection, entity_id: int) -> int:
    return int(conn.execute(_DEGREE_SQL, (entity_id, entity_id)).fetchone()[0])


def _candidate_aliases(name: str, raw_aliases: str) -> List[str]:
    """Aliases worth indexing for one entity: deduped, junk-free, not the name."""
    try:
        parsed = json.loads(raw_aliases or "[]")
    except Exception:  # noqa: BLE001 — one malformed cell must not abort the pass
        return []
    if not isinstance(parsed, list):
        return []
    name_l = (name or "").strip().lower()
    seen: set[str] = set()
    out: List[str] = []
    for a in parsed:
        if not isinstance(a, str):
            continue
        a = a.strip()
        if not a or a.lower() in _JUNK or a.lower() == name_l:
            continue
        key = a.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(a)
    return out


def _shadowed_by(conn: sqlite3.Connection, alias: str, target_id: int) -> int | None:
    """Return the id of a strictly denser active entity literally named `alias`.

    None when the alias is safe to index for `target_id`.
    """
    named = [
        int(r["id"])
        for r in conn.execute(
            "SELECT id FROM entities WHERE LOWER(name) = LOWER(?) AND status = 'active'",
            (alias,),
        )
        if int(r["id"]) != target_id
    ]
    if not named:
        return None
    target_deg = _live_degree(conn, target_id)
    best_id, best_deg = None, target_deg
    for nid in named:
        deg = _live_degree(conn, nid)
        if deg > best_deg:
            best_id, best_deg = nid, deg
    return best_id


def mirror(conn: sqlite3.Connection, *, limit: int | None, apply: bool) -> Dict[str, Any]:
    started = time.monotonic()
    before = int(conn.execute("SELECT COUNT(*) AS n FROM entity_aliases").fetchone()["n"])

    sql = (
        "SELECT id, name, aliases FROM entities "
        "WHERE status = 'active' AND aliases IS NOT NULL AND TRIM(aliases) NOT IN ('', '[]') "
        "ORDER BY id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()

    report: Dict[str, Any] = {
        "entities_scanned": len(rows),
        "aliases_considered": 0,
        "inserted": 0,
        "already_present": 0,
        "conflicts_skipped": 0,
        "shadow_skipped": 0,
        "shadow_samples": [],
        "conflict_samples": [],
        "dry_run": not apply,
    }

    for r in rows:
        eid = int(r["id"])
        for alias in _candidate_aliases(r["name"], r["aliases"]):
            report["aliases_considered"] += 1
            existing = conn.execute(
                "SELECT canonical_entity_id FROM entity_aliases WHERE LOWER(alias) = LOWER(?) LIMIT 1",
                (alias,),
            ).fetchone()
            if existing is not None:
                if int(existing["canonical_entity_id"]) == eid:
                    report["already_present"] += 1
                else:
                    report["conflicts_skipped"] += 1
                    if len(report["conflict_samples"]) < 10:
                        report["conflict_samples"].append(
                            {"alias": alias, "held_by": int(existing["canonical_entity_id"]), "entity_id": eid}
                        )
                continue
            shadow = _shadowed_by(conn, alias, eid)
            if shadow is not None:
                report["shadow_skipped"] += 1
                if len(report["shadow_samples"]) < 10:
                    report["shadow_samples"].append(
                        {"alias": alias, "entity_id": eid, "denser_named_entity": shadow}
                    )
                continue
            conn.execute(
                "INSERT OR IGNORE INTO entity_aliases (canonical_entity_id, alias) VALUES (?, ?)",
                (eid, alias),
            )
            report["inserted"] += 1

    if apply:
        conn.commit()
    else:
        conn.rollback()

    after = int(conn.execute("SELECT COUNT(*) AS n FROM entity_aliases").fetchone()["n"])
    report["aliases_before"] = before
    report["aliases_after"] = after if apply else before
    report["elapsed_s"] = round(time.monotonic() - started, 2)
    return report


def prune_shadowing(
    conn: sqlite3.Connection, *, apply: bool, audit: Path | None = None
) -> Dict[str, Any]:
    """Delete alias rows that violate the shadow rule (inserted before the guard).

    Every removed row is written to `audit` (JSONL) when applying, so the prune
    is reversible: re-inserting those rows restores the prior state.
    """
    rows = conn.execute(
        "SELECT id, canonical_entity_id, alias FROM entity_aliases ORDER BY id"
    ).fetchall()
    removed: List[Dict[str, Any]] = []
    for r in rows:
        shadow = _shadowed_by(conn, r["alias"], int(r["canonical_entity_id"]))
        if shadow is None:
            continue
        removed.append(
            {
                "alias_row": int(r["id"]),
                "alias": r["alias"],
                "canonical_entity_id": int(r["canonical_entity_id"]),
                "denser_named_entity": shadow,
            }
        )
        if apply:
            conn.execute("DELETE FROM entity_aliases WHERE id = ?", (int(r["id"]),))
    if apply:
        conn.commit()
        if audit is not None:
            audit.parent.mkdir(parents=True, exist_ok=True)
            with open(audit, "a") as fh:
                for item in removed:
                    fh.write(json.dumps({"action": "delete", **item}) + "\n")
    else:
        conn.rollback()
    return {
        "scanned": len(rows),
        "removed": len(removed),
        "audit_path": str(audit) if (apply and audit) else None,
        "removed_samples": removed[:15],
        "dry_run": not apply,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument("--limit", type=int, default=None, help="scan at most N entities")
    ap.add_argument(
        "--prune-shadowing",
        action="store_true",
        help="delete alias rows that point at a strictly weaker facet than the name owner",
    )
    ap.add_argument(
        "--audit",
        default="/home/konan/pantheon/shared/handoffs/ichor-relational-recall-fix/alias-shadow-prune.jsonl",
        help="JSONL path recording every pruned alias row (rollback source)",
    )
    args = ap.parse_args()

    conn = _connect(Path(args.db))
    try:
        if args.prune_shadowing:
            report = {"prune": prune_shadowing(conn, apply=args.apply, audit=Path(args.audit))}
        else:
            report = mirror(conn, limit=args.limit, apply=args.apply)
    finally:
        conn.close()

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
