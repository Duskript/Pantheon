#!/usr/bin/env python3
"""Ichor Auto-Eviction — move stale events to cold storage.

Events with importance below CUTOFF_IMPORTANCE AND age > CUTOFF_DAYS
are moved from ``ichor_events`` to ``ichor_cold_storage``. The cold
table mirrors the event schema plus an ``archived_at`` column.

Schedule: daily at 02:45, after decay at 02:30.

Usage:
    python3 lib/ichor_eviction.py                       # dry-run
    python3 lib/ichor_eviction.py --apply               # apply to live DB
    python3 lib/ichor_eviction.py --db /tmp/test.db --apply
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("ichor_eviction")

DEFAULT_DB = Path.home() / ".hermes" / "ichor.db"
COLD_TABLE = "ichor_cold_storage"
CUTOFF_IMPORTANCE: float = 0.1
CUTOFF_DAYS: int = 90

# Cold storage schema mirrors ichor_events plus archived_at.
COLD_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {COLD_TABLE} (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    event_type TEXT,
    subject TEXT,
    predicate TEXT,
    object TEXT,
    confidence REAL,
    source TEXT,
    raw_text TEXT,
    created_at TEXT,
    god_name TEXT,
    importance REAL,
    trust REAL,
    maturity TEXT,
    last_access TEXT,
    direction TEXT,
    peer_god TEXT,
    archived_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""


def ensure_cold_table(conn: sqlite3.Connection) -> None:
    conn.execute(COLD_TABLE_DDL)


def run_eviction(
    db_path: str | Path,
    *,
    dry_run: bool = True,
    reference_now: datetime | None = None,
) -> Dict[str, Any]:
    """Move stale events to cold storage.

    Args:
        db_path: Path to ichor.db.
        dry_run: If True, report candidates but don't move.
        reference_now: Override "now" for deterministic testing.

    Returns:
        Dict with `archived` (count moved), `candidates` (list of ids).
    """
    path = Path(db_path)
    if not path.exists():
        return {"archived": 0, "candidates": [], "error": "db not found"}

    now = reference_now or datetime.now(timezone.utc)
    cutoff_dt = (now - timedelta(days=CUTOFF_DAYS)).isoformat()

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    try:
        ensure_cold_table(conn)

        cursor = conn.execute(
            f"SELECT * FROM ichor_events "
            f"WHERE importance < ? AND created_at < ?",
            (CUTOFF_IMPORTANCE, cutoff_dt),
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        return {"archived": 0, "candidates": [], "error": str(exc)}

    if not rows:
        conn.close()
        return {"archived": 0, "candidates": []}

    candidate_ids = [row["id"] for row in rows]

    if dry_run:
        conn.close()
        logger.info(
            "Eviction DRY-RUN: %d candidates (not moved)", len(rows)
        )
        return {"archived": 0, "candidates": candidate_ids}

    # Insert into cold storage
    col_names = list(rows[0].keys())
    col_names = [c for c in col_names if c != "archived_at"]  # exclude if present
    placeholders = ", ".join("?" for _ in col_names)
    col_list = ", ".join(col_names)

    now_iso = now.isoformat()
    conn.executemany(
        f"INSERT OR IGNORE INTO {COLD_TABLE} ({col_list}, archived_at) "
        f"VALUES ({placeholders}, ?)",
        [tuple(row[col] for col in col_names) + (now_iso,) for row in rows],
    )

    # Delete from main table
    conn.executemany(
        "DELETE FROM ichor_events WHERE id = ?",
        [(rid,) for rid in candidate_ids],
    )
    conn.commit()

    logger.info("Eviction: %d events archived to %s", len(rows), COLD_TABLE)
    conn.close()
    return {"archived": len(rows), "candidates": candidate_ids}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ichor Auto-Eviction")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to ichor.db")
    ap.add_argument("--apply", action="store_true", help="Actually apply (default: dry-run)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    result = run_eviction(args.db, dry_run=not args.apply)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        return

    mode = "ARCHIVED" if args.apply else "DRY-RUN"
    print(
        f"{mode}: {result['archived']} events, "
        f"{len(result.get('candidates', []))} candidates"
    )
    if not args.apply and result.get("candidates"):
        print(f"  Candidate IDs: {result['candidates'][:10]}...")


if __name__ == "__main__":
    main()
