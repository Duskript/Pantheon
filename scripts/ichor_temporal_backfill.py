#!/usr/bin/env python3
"""Ichor Temporal Backfill — ichor_events temporal defaults + legacy supersession.

Two independent passes:

1. Hindsight Phase 1 backfill (CLI default): populates missing
   ``mentioned_at`` (defaults to ``created_at``) and missing/NULL/empty
   ``status`` (defaults to ``'active'``) on ``ichor_events`` rows.

2. T-Memory supersession backfill (kept for backward compatibility, exercised
   by ``tests/test_ichor_temporal_backfill.py``): scans duplicate pairs (same
   type + source + target for relationships; same type + name for entities)
   and sets ``valid_to`` / ``valid_until`` on the older rows via
   ``run_backfill()``.

Usage:
    python3 scripts/ichor_temporal_backfill.py --db-path ~/.hermes/ichor.db --dry-run
    python3 scripts/ichor_temporal_backfill.py --db-path ~/.hermes/ichor.db --apply
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("ichor_backfill")

DEFAULT_DB = Path.home() / ".hermes" / "ichor.db"


def _audit_event(
    conn: sqlite3.Connection,
    table: str,
    superseded_id: int,
    superseded_by_id: int,
    type_id: str,
    detail: str,
) -> None:
    """Write a backfill audit event to ichor_events."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            "INSERT INTO ichor_events "
            "(session_id, event_type, subject, predicate, object, confidence, "
            " source, raw_text, created_at, god_name, importance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"backfill_{now[:10]}",
                "correction",
                f"backfill:{table}:{superseded_id}",
                "supersedes",
                str(superseded_by_id),
                1.0,
                "backfill",
                detail,
                now,
                "subconscious",
                70.0,
            ),
        )
    except Exception as exc:
        logger.debug("Audit write failed (non-fatal): %s", exc)


def backfill_relationships(
    conn: sqlite3.Connection, dry_run: bool = True,
) -> Dict[str, Any]:
    """Find duplicate relationship groups and expire older rows.

    A "duplicate" is: same type_id + source_id + target_id, with > 1 row.
    The newest row (by id) is kept; all older rows get valid_to set.
    """
    groups = conn.execute(
        "SELECT type_id, source_id, target_id, COUNT(*) as cnt, "
        "       MAX(id) as newest_id "
        "FROM relationships "
        "GROUP BY type_id, source_id, target_id "
        "HAVING cnt > 1"
    ).fetchall()

    updated: List[int] = []
    for group in groups:
        newest_id = group["newest_id"]
        # Get all older rows in this group
        older = conn.execute(
            "SELECT id, created_at FROM relationships "
            "WHERE type_id = ? AND source_id = ? AND target_id = ? "
            "  AND id != ? AND valid_to IS NULL",
            (group["type_id"], group["source_id"], group["target_id"], newest_id),
        ).fetchall()

        for row in older:
            expiry = row["created_at"] or datetime.now(timezone.utc).isoformat()
            if not dry_run:
                conn.execute(
                    "UPDATE relationships SET valid_to = ? WHERE id = ?",
                    (expiry, row["id"]),
                )
                _audit_event(
                    conn, "relationships", row["id"], newest_id,
                    group["type_id"],
                    f"Backfill: superseded duplicate relationship "
                    f"{group['type_id']}({group['source_id']}→{group['target_id']}) "
                    f"by newer row {newest_id}",
                )
            updated.append(row["id"])

    if not dry_run and updated:
        conn.commit()
    return {"table": "relationships", "expired": len(updated), "groups": len(groups)}


def backfill_entities(
    conn: sqlite3.Connection, dry_run: bool = True,
) -> Dict[str, Any]:
    """Find duplicate entity groups and expire older rows.

    A "duplicate" is: same type_id + name, with > 1 row.
    The newest row (by id) is kept; all older rows get valid_until
    and superseded_by set.
    """
    groups = conn.execute(
        "SELECT type_id, name, COUNT(*) as cnt, MAX(id) as newest_id "
        "FROM entities "
        "GROUP BY type_id, name "
        "HAVING cnt > 1"
    ).fetchall()

    updated: List[int] = []
    for group in groups:
        newest_id = group["newest_id"]
        older = conn.execute(
            "SELECT id, created_at FROM entities "
            "WHERE type_id = ? AND name = ? AND id != ? "
            "  AND valid_until IS NULL",
            (group["type_id"], group["name"], newest_id),
        ).fetchall()

        for row in older:
            expiry = row["created_at"] or datetime.now(timezone.utc).isoformat()
            if not dry_run:
                conn.execute(
                    "UPDATE entities SET valid_until = ?, superseded_by = ? "
                    "WHERE id = ?",
                    (expiry, newest_id, row["id"]),
                )
                _audit_event(
                    conn, "entities", row["id"], newest_id,
                    group["type_id"],
                    f"Backfill: superseded duplicate entity "
                    f"{group['type_id']}/{group['name']} "
                    f"by newer row {newest_id}",
                )
            updated.append(row["id"])

    if not dry_run and updated:
        conn.commit()
    return {"table": "entities", "expired": len(updated), "groups": len(groups)}


def backfill_event_temporal(
    conn: sqlite3.Connection, dry_run: bool = True,
) -> Dict[str, Any]:
    """Backfill missing temporal/status fields on ichor_events (Hindsight Phase 1).

    - ``mentioned_at`` defaults to ``created_at`` when missing.
    - ``status`` defaults to ``'active'`` when missing, NULL, or empty.
    Idempotent: rows already populated are untouched. No writes in dry-run.
    """
    rows = conn.execute(
        "SELECT id, mentioned_at, status FROM ichor_events ORDER BY id"
    ).fetchall()
    mentioned_ids: List[int] = []
    status_ids: List[int] = []
    for row in rows:
        if not row["mentioned_at"]:
            mentioned_ids.append(int(row["id"]))
        if row["status"] is None or str(row["status"]).strip() == "":
            status_ids.append(int(row["id"]))

    if not dry_run:
        # Use set-based UPDATEs instead of a giant `id IN (?,...)` list.
        # The live Pantheon DB has hundreds of thousands of rows, which can
        # exceed SQLite's variable limit if each id is bound separately.
        if mentioned_ids:
            conn.execute(
                "UPDATE ichor_events "
                "SET mentioned_at = COALESCE(mentioned_at, created_at) "
                "WHERE mentioned_at IS NULL OR TRIM(CAST(mentioned_at AS TEXT)) = ''"
            )
        if status_ids:
            conn.execute(
                "UPDATE ichor_events SET status = 'active' "
                "WHERE status IS NULL OR TRIM(CAST(status AS TEXT)) = ''"
            )
        conn.commit()

    return {
        "table": "ichor_events",
        "rows_scanned": len(rows),
        "missing_mentioned_at": len(mentioned_ids),
        "missing_status": len(status_ids),
        "updated": len(mentioned_ids) + len(status_ids),
        "dry_run": bool(dry_run),
    }


def run_backfill(
    db_path: str | Path, dry_run: bool = True,
) -> Dict[str, Any]:
    """Run the full temporal backfill pass.

    Lock policy: this legacy T-Memory path opens its own connection instead of
    going through ``IchorDB``, so it must set the batch wait itself or it keeps
    sqlite3's 5s default and dies on a lock held by a sibling maintenance job
    (the 2026-09-21 09:51/10:07 `database is locked` failures). Same value the
    rest of the fleet's maintenance scripts use.
    """
    path = Path(db_path)
    if not path.exists():
        return {"error": "db not found", "path": str(path)}

    # Local import + path setup, matching main(): this module is executed as a
    # script from the repo root, so `lib` is not importable at module import
    # time. Keeping the constant single-sourced in lib/ichor_db.py is the point
    # — a re-typed 600000 here is the duplication this change exists to remove.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from lib.ichor_db import MAINTENANCE_BUSY_TIMEOUT_MS

    conn = sqlite3.connect(str(path))
    conn.execute(f"PRAGMA busy_timeout={MAINTENANCE_BUSY_TIMEOUT_MS};")
    conn.row_factory = sqlite3.Row

    results = {}
    try:
        results["relationships"] = backfill_relationships(conn, dry_run)
    except Exception as exc:
        results["relationships"] = {"error": str(exc)}

    try:
        results["entities"] = backfill_entities(conn, dry_run)
    except Exception as exc:
        results["entities"] = {"error": str(exc)}

    conn.close()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ichor temporal backfill - ichor_events mentioned_at/status defaults."
    )
    ap.add_argument("--db-path", default=str(DEFAULT_DB), help="Path to ichor.db")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report only (default unless --apply)")
    ap.add_argument("--apply", action="store_true",
                    help="Actually write the backfill updates")
    args = ap.parse_args()

    dry = args.dry_run or not args.apply

    # Ensure the schema (incl. mentioned_at/status columns) exists for the
    # target db before counting or updating.
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from lib.ichor_db import MAINTENANCE_BUSY_TIMEOUT_MS, IchorDB

    path = Path(args.db_path).expanduser()
    # Batch caller: wait out a lock held by a sibling maintenance job (WAL
    # truncate, retention prune, gateway checkpoint) instead of aborting after
    # sqlite3's 5s default. This is the call that raised
    # `sqlite3.OperationalError: database is locked` on 2026-09-21 at 09:51 and
    # 10:07 and alerted through ichor_hindsight_maintenance.py.
    db = IchorDB(db_path=str(path), busy_timeout_ms=MAINTENANCE_BUSY_TIMEOUT_MS)
    conn = db.connect()
    res = backfill_event_temporal(conn, dry_run=dry)

    mode = "APPLIED" if not dry else "DRY-RUN"
    print(f"=== Temporal Backfill {mode} ===")
    print(
        f"  ichor_events: scanned={res['rows_scanned']} "
        f"missing_mentioned_at={res['missing_mentioned_at']} "
        f"missing_status={res['missing_status']} "
        f"updated={res['updated']} dry_run={res['dry_run']}"
    )
    if dry:
        print("\nRun with --apply to execute.")


if __name__ == "__main__":
    main()
