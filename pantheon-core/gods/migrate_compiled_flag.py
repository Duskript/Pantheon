#!/usr/bin/env python3
"""Migration script: mark all existing sessions as compiled=0.

Phase 1 of the session compilation pipeline.  Ensures the `compiled` and
`compiled_at` columns exist on the sessions table, then sets compiled=0 for
every session that doesn't already have the flag set (NULL or missing).

Safe to re-run — idempotent.
"""

import logging
import sys
import time
from pathlib import Path

# Ensure hermes-agent is importable
_HERMES_AGENT = Path.home() / ".hermes" / "hermes-agent" / "venv" / "lib" / "python3.14" / "site-packages"
if str(_HERMES_AGENT) not in sys.path:
    sys.path.insert(0, str(_HERMES_AGENT))

from hermes_state import SessionDB

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("migrate_compiled")


def main():
    state_db_path = Path.home() / ".hermes" / "state.db"
    if not state_db_path.exists():
        logger.error("state.db not found at %s", state_db_path)
        sys.exit(1)

    db = SessionDB(db_path=state_db_path)
    logger.info("Connected to state.db at %s (size: %.1f MB)",
                state_db_path, state_db_path.stat().st_size / (1024 * 1024))

    # The SessionDB._init_schema() already calls _reconcile_columns() which
    # auto-adds the compiled/compiled_at columns from SCHEMA_SQL.  The
    # instantiation above triggers that.  Verify by checking a session row.
    test = db.get_uncompiled_sessions(limit=1)
    logger.info("Schema reconciled — compiled columns are present.")

    # Count sessions that need the flag
    with db._lock:
        total = db._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        null_count = db._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE compiled IS NULL"
        ).fetchone()[0]

    logger.info("Total sessions: %d", total)
    logger.info("Sessions with NULL compiled: %d", null_count)

    if null_count == 0:
        logger.info("All sessions already have compiled set. Nothing to do.")
        return

    # Set compiled=0 for all NULL entries
    def _do(conn):
        cur = conn.execute("UPDATE sessions SET compiled = 0 WHERE compiled IS NULL")
        return cur.rowcount

    updated = db._execute_write(_do)
    logger.info("Marked %d sessions as compiled=0", updated)

    # Verify
    with db._lock:
        remaining = db._conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE compiled IS NULL"
        ).fetchone()[0]
    logger.info("Remaining NULL compiled: %d (expected 0)", remaining)

    total_uncompiled = db.count_uncompiled()
    logger.info("Total un-compiled sessions: %d", total_uncompiled)

    logger.info("Migration complete.")


if __name__ == "__main__":
    main()
