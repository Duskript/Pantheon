"""Daily maintenance: decay, prune, report.

Run via cron: 0 3 * * * python3 -m lib.ichor_daily_maintenance --execute
"""

import argparse
import logging
import os
from pathlib import Path

import lib.ichor_memory_score as score

logger = logging.getLogger("ichor_daily_maintenance")

# Resolve real home — $HOME may be profile-scoped in Hermes
_REAL_HOME = Path(os.environ.get("REAL_HOME", os.environ.get("HOME", "/home/konan")))
DB_PATH = _REAL_HOME / ".hermes" / "ichor.db"


def run(dry_run: bool = True) -> dict:
    """Run daily maintenance cycle."""
    conn = score.get_db_connection(str(DB_PATH))
    score.ensure_schema(conn)

    decayed = score.apply_decay(conn)
    score.update_maturity(conn)
    prunable = score.prune_execute(conn, dry_run=dry_run)

    report = {
        "events_decayed": decayed,
        "events_pruned": prunable,
        "dry_run": dry_run,
    }
    logger.info("Daily maintenance: %d decayed, %d pruned (dry_run=%s)", decayed, prunable, dry_run)
    conn.close()
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete, not dry-run")
    args = parser.parse_args()
    run(dry_run=not args.execute)
