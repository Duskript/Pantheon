#!/usr/bin/env python3
"""Ichor event tag backfill — infer safe god/session tags onto existing rows.

One-shot, idempotent. Scans ``ichor_events`` and plans ``god:<god_name>`` and
``session:<session_id>`` tags for every row, plus ``scope:pantheon`` when
``--pantheon-scope`` is passed. Never infers ``user:<id>`` tags — those require
an explicit caller-provided map (see the Hindsight spec default policy).

Usage:
    python3 scripts/ichor_backfill_tags.py --db-path ~/.hermes/ichor.db --dry-run
    python3 scripts/ichor_backfill_tags.py --db-path ~/.hermes/ichor.db --apply --pantheon-scope
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Batch lock-wait policy for this script ─────────────────────────────
# Mechanism: this backfill scans ichor_events and writes tag rows. It reaches
# the database through IchorDB, which by default leaves sqlite3's 5s busy
# timeout in place, so any lock held by a sibling maintenance job at the wrong
# moment aborts the pass.
# Symptom: on 2026-09-21 the parent job (ichor_hindsight_maintenance.py) exited
# non-zero twice — 09:51 and 10:07 — on `database is locked` while another job
# checkpointed a 12 GiB WAL. Every script in this path is now a batch caller
# that opts in to the longer wait, matching the fleet convention already used by
# ichor-retention-prune.py / ichor-dedupe.py / ichor-reconcile.py.
# Reproduce by hand: hold a write lock, then run the backfill —
#     python3 -c "import sqlite3,time; c=sqlite3.connect('/home/konan/.hermes/ichor.db'); c.execute('BEGIN IMMEDIATE'); time.sleep(30)"
#     python3 scripts/ichor_backfill_tags.py --db-path ~/.hermes/ichor.db --dry-run --pantheon-scope
from lib.ichor_db import MAINTENANCE_BUSY_TIMEOUT_MS, IchorDB  # noqa: E402

DEFAULT_DB = "/home/konan/.hermes/ichor.db"


def plan_tags(db_path: str, pantheon_scope: bool = False) -> tuple[int, list[tuple[int, str]]]:
    """Return ``(rows_scanned, planned (event_id, tag) pairs)``.

    Uses ``IchorDB`` so the target db's schema is guaranteed to exist before
    the scan. Only god/session (and optional scope) tags are planned — user
    tags are never inferred.

    Lock policy: the connection is opened as a BATCH caller
    (``busy_timeout_ms=MAINTENANCE_BUSY_TIMEOUT_MS``), so a lock held by a
    sibling maintenance job is waited out rather than aborting this pass after
    sqlite3's 5s default. See the policy block above the import.
    """
    db = IchorDB(db_path=db_path, busy_timeout_ms=MAINTENANCE_BUSY_TIMEOUT_MS)
    conn = db.connect()
    rows = conn.execute(
        "SELECT id, god_name, session_id FROM ichor_events ORDER BY id"
    ).fetchall()
    planned: list[tuple[int, str]] = []
    for row in rows:
        event_id = int(row["id"])
        god = row["god_name"]
        session = row["session_id"]
        if god:
            planned.append((event_id, f"god:{god}"))
        if session:
            planned.append((event_id, f"session:{session}"))
        if pantheon_scope:
            planned.append((event_id, "scope:pantheon"))
    return len(rows), planned


def apply_tags(db_path: str, planned: list[tuple[int, str]]) -> int:
    """Insert planned tags with INSERT OR IGNORE — idempotent. Returns count inserted.

    Lock policy: batch caller, same as ``plan_tags`` — the write pass waits for a
    sibling job's lock instead of raising ``database is locked`` after 5s.
    """
    db = IchorDB(db_path=db_path, busy_timeout_ms=MAINTENANCE_BUSY_TIMEOUT_MS)
    conn = db.connect()
    inserted = 0
    for event_id, tag in planned:
        cur = conn.execute(
            "INSERT OR IGNORE INTO ichor_event_tags (event_id, tag) VALUES (?, ?)",
            (event_id, tag),
        )
        inserted += max(0, cur.rowcount)
    conn.commit()
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Backfill safe god/session tags onto ichor_events rows."
    )
    ap.add_argument("--db-path", default=DEFAULT_DB, help="Path to the Ichor SQLite db")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report planned tags without writing (default unless --apply)")
    ap.add_argument("--apply", action="store_true", help="Write planned tags")
    ap.add_argument("--pantheon-scope", action="store_true",
                    help="Also plan scope:pantheon for every scanned row")
    args = ap.parse_args()

    # Dry-run is the default; --apply (without --dry-run) is the only write path.
    dry_run = args.dry_run or not args.apply

    scanned, planned = plan_tags(args.db_path, pantheon_scope=args.pantheon_scope)
    inserted = 0
    if not dry_run and planned:
        inserted = apply_tags(args.db_path, planned)

    print(f"tag backfill {'APPLIED' if not dry_run else 'DRY-RUN'}")
    print(f"  scanned={scanned} planned={len(planned)} inserted={inserted} dry_run={dry_run}")


if __name__ == "__main__":
    main()
