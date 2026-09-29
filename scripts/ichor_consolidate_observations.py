#!/usr/bin/env python3
"""Ichor observation consolidation CLI — collapse repeated events into observations.

One-shot, idempotent. Uses ``ObservationConsolidator.consolidate_events`` to
cluster active events by normalized subject/predicate/object and write (or
report) consolidated observations with evidence rows. Dry-run reports candidate
clusters without writing anything.

Usage:
    python3 scripts/ichor_consolidate_observations.py --db-path ~/.hermes/ichor.db --dry-run
    python3 scripts/ichor_consolidate_observations.py --db-path ~/.hermes/ichor.db --limit 1000
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.ichor_db import MAINTENANCE_BUSY_TIMEOUT_MS, IchorDB  # noqa: E402
from lib.ichor_observations import ConsolidationResult, ObservationConsolidator  # noqa: E402

DEFAULT_DB = "/home/konan/.hermes/ichor.db"


def _count_observations(db_path: str) -> int:
    """Count observation rows, waiting out a lock instead of aborting.

    Mechanism: this helper opens its OWN sqlite3 connection rather than going
    through ``IchorDB``, so it does not inherit the batch lock-wait policy set
    there and would fall back to sqlite3's 5s default. It runs at the start of
    every consolidation pass, so a lock held by a sibling job at that moment
    kills the whole pass before it starts.

    Symptom: on 2026-09-21 the hindsight job alerted twice (09:51 and 10:07)
    with ``sqlite3.OperationalError: database is locked`` while a 12 GiB WAL
    was being checkpointed by another job; the count is one of the first
    statements any consolidation pass executes.

    Reproduce by hand: hold a write lock, then run the consolidation —
        python3 -c "import sqlite3,time; c=sqlite3.connect('/home/konan/.hermes/ichor.db'); c.execute('BEGIN IMMEDIATE'); time.sleep(30)"
        python3 scripts/ichor_consolidate_observations.py --db-path ~/.hermes/ichor.db --dry-run
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(f"PRAGMA busy_timeout={MAINTENANCE_BUSY_TIMEOUT_MS};")
        row = conn.execute("SELECT COUNT(*) FROM ichor_observations").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Consolidate repeated Ichor events into observations."
    )
    ap.add_argument("--db-path", default=DEFAULT_DB, help="Path to the Ichor SQLite db")
    ap.add_argument("--limit", type=int, default=1000,
                    help="Max events to consider per pass (default: 1000)")
    ap.add_argument("--after-id", type=int, default=None,
                    help="Only consider events with id greater than this cursor")
    ap.add_argument("--only-unsourced", action="store_true",
                    help="Skip events already attached to observation source rows")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report candidate clusters without writing")
    args = ap.parse_args()

    # Ensure the schema exists for the target db before counting/consolidating.
    # Batch caller: MAINTENANCE_BUSY_TIMEOUT_MS is threaded through so this
    # connection — and the consolidator's, which builds its own IchorDB — wait
    # out a sibling job's lock rather than raising `database is locked` after
    # sqlite3's 5s default (the 2026-09-21 09:51/10:07 hindsight failures).
    IchorDB(
        db_path=args.db_path, busy_timeout_ms=MAINTENANCE_BUSY_TIMEOUT_MS
    ).connect()
    before = _count_observations(args.db_path)

    # Batch lock-wait policy reaches the consolidator too: it builds its own
    # IchorDB inside `_connect()`, so passing the timeout here is what makes the
    # consolidation WRITES wait for a sibling job's lock instead of raising
    # `database is locked` after 5s (the 2026-09-21 09:51/10:07 hindsight runs).
    consolidator = ObservationConsolidator(
        db_path=args.db_path, busy_timeout_ms=MAINTENANCE_BUSY_TIMEOUT_MS
    )
    result = consolidator.consolidate_events(
        limit=args.limit,
        after_id=args.after_id,
        only_unsourced=args.only_unsourced,
        dry_run=args.dry_run,
    )

    after = _count_observations(args.db_path)

    fields = result.to_dict() if isinstance(result, ConsolidationResult) else dict(result)
    print(f"observation consolidation {'DRY-RUN' if args.dry_run else 'APPLIED'}")
    print(f"  dry_run={args.dry_run} before={before} after={after}")
    print(
        f"  events_processed={fields.get('events_processed')} "
        f"clusters_found={fields.get('clusters_found')} "
        f"observations_created={fields.get('observations_created')} "
        f"observations_updated={fields.get('observations_updated')} "
        f"sources_written={fields.get('sources_written')} "
        f"tags_attached={fields.get('tags_attached')} "
        f"contradictions_skipped={fields.get('contradictions_skipped')} "
        f"min_event_id_processed={fields.get('min_event_id_processed')} "
        f"max_event_id_processed={fields.get('max_event_id_processed')} "
        f"written={fields.get('written')}"
    )


if __name__ == "__main__":
    main()
