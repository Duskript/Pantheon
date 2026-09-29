#!/usr/bin/env python3
"""Ichor relational recall — Fix C: nickname/alias resolution.

Problem
-------
Konan exists in ``~/.hermes/ichor.db`` as six or more separate active ``person``
rows, none merged.  ``entity_resolve.py`` consolidates on *token similarity*, so
``"Cybermage"`` vs ``"Konan"`` (zero shared tokens, similarity 0.0) can never
merge by construction.  ``entity_aliases`` — the table ``resolve()`` consults
**first** (``entity_resolve.py:463``) — has 0 rows despite 641 merges having run,
because the mergers wrote ``entities.aliases`` JSON instead of the index table.

This script:
  1. Picks one canonical person entity (the hub, by live-edge degree).
  2. Seeds ``entity_aliases`` with every known identity variant -> canonical id.
  3. Folds the fragment rows into the canonical node via
     ``entity_resolve._apply_merge`` (re-points edges + facts, unions aliases,
     marks the loser merged).  Explicit id list only — never fuzzy.
  4. Optionally seeds ``entity_aliases`` for every person_roots person so
     relationship names resolve to nodes (Fia, Tallon, Jahnavi, ...).

Idempotent: re-running changes nothing.  Dry-run by default.

Usage
-----
    python3 scripts/ichor_identity_alias_seed.py                 # dry run, Konan only
    python3 scripts/ichor_identity_alias_seed.py --person-roots  # dry run, + people
    python3 scripts/ichor_identity_alias_seed.py --apply --person-roots
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

PANTHEON_LIB = Path("/home/konan/pantheon")
if str(PANTHEON_LIB) not in sys.path:
    sys.path.insert(0, str(PANTHEON_LIB))

from lib.ichor.entities.entity_resolve import _apply_merge  # noqa: E402
from lib.ichor.entities.schema import migrate  # noqa: E402

DEFAULT_DB = Path("/home/konan/.hermes/ichor.db")
PERSON_ROOTS_ROOT = Path("/home/konan/athenaeum/Codex-User/relationships")

# ── Konan's canonical identity ──────────────────────────────────────────
# The hub row: 'konan', type_id='person', 944 live edges.  Verified 2026-09-17.
CANONICAL_ENTITY_ID = 614
CANONICAL_NAME = "konan"

# Every variant that must resolve to ONE person id.
IDENTITY_ALIASES: List[str] = [
    "konan",
    "Konan",
    "KONAN",
    "Konan Ross Rudolph I",
    "Konan Ross Rudolph",
    "Konan Rudolph",
    "Konan Rudolph I",
    "Cybermage",
    "cybermage",
    "The Cybermage",
    "thecybermage",
    "CyberMage",
    # Discord user id (Konan's own account)
    "180817012619083776",
    # registered emails
    "konan.rudolph@gmail.com",
    "konan.rudolph@proton.me",
    "konan@theoforgesolutions.co",
    "konan@olympus.ui",
]

# Rows folded into the canonical node.  person fragments first, then the
# stray cross-type rows that are extraction artifacts of the same identity.
MERGE_LOSERS: Dict[int, str] = {
    # --- person fragments (the direct cause of the reported symptom) ---
    785: "person 'Konan' (already merged_into 614 — re-asserted for alias union)",
    1286: "person 'Konan Ross Rudolph I'",
    7743: "person 'Konan Rudolph'",
    5750: "person 'The Cybermage' (aliases: thecybermage)",
    13627: "person 'Cybermage' (aliases: 180817012619083776)",
    2664: "person 'konan.rudolph@proton.me' (email mis-typed as person)",
    # --- cross-type identity strays ---
    1826: "tool 'Konan'",
    1839: "concept 'Konan'",
    1908: "project 'Konan'",
    9468: "organization 'Konan'",
    12710: "github_handle 'konan'",
    17372: "github_handle 'Cybermage'",
    5431: "concept 'Cybermage' (79 edges — these become Konan's)",
    16179: "project 'Cybermage'",
}

# Relation-phrase nodes that are NOT Konan and must not be merged into him.
# Recorded here so the report is explicit about what was deliberately skipped.
NOT_MERGED: Dict[int, str] = {
    4437: "person \"Konan's brother\" — a different person (person_roots: tallon)",
    4438: "person \"Konan's father\" — different person; relation phrase as node",
    4439: "person \"Konan's mother\" — different person; relation phrase as node",
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _live_edge_count(conn: sqlite3.Connection, entity_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM relationships r "
        "WHERE (r.source_id = ? OR r.target_id = ?) "
        "  AND r.provisional = 0 "
        "  AND (r.valid_to IS NULL OR r.valid_to > datetime('now'))",
        (entity_id, entity_id),
    ).fetchone()
    return int(row["n"]) if row else 0


def pick_canonical(conn: sqlite3.Connection) -> Optional[int]:
    """Return the canonical person id, preferring the configured hub id."""
    row = conn.execute(
        "SELECT id, name, type_id, status FROM entities WHERE id = ?",
        (CANONICAL_ENTITY_ID,),
    ).fetchone()
    if row is not None and row["type_id"] == "person" and row["status"] == "active":
        return int(row["id"])

    # Fallback: highest live-degree active person row whose name matches konan.
    cands = conn.execute(
        "SELECT id, name FROM entities WHERE type_id = 'person' AND status = 'active' "
        "AND LOWER(name) LIKE '%konan%' ORDER BY id",
    ).fetchall()
    best_id, best_deg = None, -1
    for c in cands:
        deg = _live_edge_count(conn, int(c["id"]))
        if deg > best_deg:
            best_id, best_deg = int(c["id"]), deg
    return best_id


def seed_aliases(
    conn: sqlite3.Connection, canonical_id: int, aliases: List[str]
) -> Dict[str, Any]:
    """INSERT OR IGNORE alias -> canonical.  Returns inserted/present split."""
    inserted: List[str] = []
    present: List[str] = []
    for alias in aliases:
        a = str(alias).strip()
        if not a:
            continue
        existing = conn.execute(
            "SELECT canonical_entity_id FROM entity_aliases WHERE alias = ? LIMIT 1",
            (a,),
        ).fetchone()
        if existing is not None:
            present.append(a)
            continue
        conn.execute(
            "INSERT OR IGNORE INTO entity_aliases (canonical_entity_id, alias) "
            "VALUES (?, ?)",
            (canonical_id, a),
        )
        inserted.append(a)
    return {"inserted": inserted, "already_present": present}


def merge_losers(
    conn: sqlite3.Connection, canonical_id: int, losers: Dict[int, str]
) -> List[Dict[str, Any]]:
    """Fold each loser into canonical via _apply_merge.  Idempotent."""
    out: List[Dict[str, Any]] = []
    for loser_id in sorted(losers):
        row = conn.execute(
            "SELECT id, name, type_id, status, merged_into, aliases FROM entities "
            "WHERE id = ?",
            (loser_id,),
        ).fetchone()
        if row is None:
            out.append({"id": loser_id, "action": "missing", "note": losers[loser_id]})
            continue
        if row["status"] == "merged" and row["merged_into"] == canonical_id:
            out.append({
                "id": loser_id,
                "name": row["name"],
                "type": row["type_id"],
                "action": "already_merged",
            })
            continue
        if int(row["id"]) == canonical_id:
            out.append({"id": loser_id, "action": "skipped_self"})
            continue
        edges_before = _live_edge_count(conn, loser_id)
        _apply_merge(conn, canonical_id, loser_id)
        out.append({
            "id": loser_id,
            "name": row["name"],
            "type": row["type_id"],
            "action": "merged",
            "edges_folded": edges_before,
        })
    return out


def _unpack_person_aliases(rec: Any) -> List[str]:
    names: List[str] = []
    display = getattr(rec, "display_name", "") or ""
    if display:
        names.append(display)
    for a in getattr(rec, "aliases", ()) or ():
        if isinstance(a, str) and a.strip() and a.strip() != "—":
            names.append(a.strip())
    return names


def seed_person_roots_aliases(
    conn: sqlite3.Connection, dry_run: bool
) -> Dict[str, Any]:
    """Seed entity_aliases for every person_roots person (Fia, Tallon, ...).

    Additive only: inserts alias rows pointing at the entity id that already
    exists for that person.  Never creates or merges entities.
    """
    from lib.person_roots.resolver import PersonRootsRepository  # noqa: E402

    repo = PersonRootsRepository(PERSON_ROOTS_ROOT)
    report: Dict[str, Any] = {"people": [], "alias_rows_planned": 0, "skipped": []}
    for person_id in repo.list_people():
        try:
            rec = repo.load_person(person_id)
        except Exception as exc:  # noqa: BLE001 — one bad folder must not abort
            report["skipped"].append({"person_id": person_id, "reason": str(exc)})
            continue

        names = _unpack_person_aliases(rec)
        # Resolve to an existing active entity id, exact-name only.
        target_id: Optional[int] = None
        hit_name = ""
        for nm in names:
            row = conn.execute(
                "SELECT id FROM entities WHERE LOWER(name) = LOWER(?) "
                "AND status = 'active' ORDER BY id LIMIT 1",
                (nm,),
            ).fetchone()
            if row is not None:
                target_id = int(row["id"])
                hit_name = nm
                break
        if target_id is None:
            report["skipped"].append({
                "person_id": person_id,
                "reason": "no matching active entity row",
                "names": names,
            })
            continue

        added = [n for n in names if n]
        report["people"].append({
            "person_id": person_id,
            "display_name": getattr(rec, "display_name", ""),
            "entity_id": target_id,
            "matched_on": hit_name,
            "aliases": added,
        })
        report["alias_rows_planned"] += len(added)
        if not dry_run:
            seed_aliases(conn, target_id, added)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to ichor.db")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    ap.add_argument(
        "--person-roots",
        action="store_true",
        help="also seed aliases for every person_roots person",
    )
    args = ap.parse_args()

    db_path = Path(args.db)
    dry_run = not args.apply
    report: Dict[str, Any] = {"db": str(db_path), "dry_run": dry_run}

    migrate(db_path)
    conn = _connect(db_path)
    try:
        canonical_id = pick_canonical(conn)
        report["canonical_entity_id"] = canonical_id
        if canonical_id is None:
            report["error"] = "no canonical person row found"
            print(json.dumps(report, indent=2))
            return 1

        row = conn.execute(
            "SELECT id, name, type_id, aliases FROM entities WHERE id = ?",
            (canonical_id,),
        ).fetchone()
        report["canonical"] = {
            "id": int(row["id"]),
            "name": row["name"],
            "type": row["type_id"],
            "live_edges": _live_edge_count(conn, canonical_id),
            "aliases_before": row["aliases"],
        }

        report["aliases_before_count"] = int(
            conn.execute("SELECT COUNT(*) AS n FROM entity_aliases").fetchone()["n"]
        )

        # sqlite3 opens an implicit transaction on the first INSERT, so a dry
        # run is simply rolled back at the end — no explicit BEGIN (which would
        # raise "cannot start a transaction within a transaction").
        seed = seed_aliases(conn, canonical_id, IDENTITY_ALIASES)
        merges = merge_losers(conn, canonical_id, MERGE_LOSERS)

        if args.person_roots:
            report["person_roots"] = seed_person_roots_aliases(conn, dry_run=dry_run)

        if dry_run:
            conn.rollback()
            report["planned_alias_rows"] = len(seed["inserted"])
        else:
            conn.commit()

        report["identity_aliases"] = {
            "inserted": seed["inserted"],
            "already_present": seed["already_present"],
        }
        report["merges"] = merges
        report["not_merged"] = NOT_MERGED

        if not dry_run:
            report["aliases_after_count"] = int(
                conn.execute("SELECT COUNT(*) AS n FROM entity_aliases").fetchone()["n"]
            )
            canon_after = conn.execute(
                "SELECT aliases FROM entities WHERE id = ?", (canonical_id,)
            ).fetchone()
            report["canonical"]["aliases_after"] = canon_after["aliases"]
    finally:
        conn.close()

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
