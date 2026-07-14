#!/usr/bin/env python3
"""Ichor Temporal Backfill — populate valid_to on superseded relationships and entities.

One-shot, idempotent. Scans for duplicate pairs (same type + source + target for
relationships; same type + name for entities) and sets ``valid_to`` / ``valid_until``
on the older rows, keeping the newest one as current.

This is the backfill for Phase 1 (T-Memory). Run once, then the write-time
supersession code in ``lib/ichor/entities/extraction.py`` handles new rows.

Usage:
    python3 scripts/ichor_temporal_backfill.py              # dry-run
    python3 scripts/ichor_temporal_backfill.py --apply      # apply
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
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


def run_backfill(
    db_path: str | Path, dry_run: bool = True,
) -> Dict[str, Any]:
    """Run the full temporal backfill pass."""
    path = Path(db_path)
    if not path.exists():
        return {"error": "db not found", "path": str(path)}

    conn = sqlite3.connect(str(path))
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
    ap = argparse.ArgumentParser(description="Ichor Temporal Backfill")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to ichor.db")
    ap.add_argument("--apply", action="store_true", help="Actually apply (default: dry-run)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    dry = not args.apply
    results = run_backfill(args.db, dry_run=dry)

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"=== Temporal Backfill {mode} ===")
    for table, r in results.items():
        if isinstance(r, dict) and "error" in r:
            print(f"  {table}: ERROR — {r['error']}")
        else:
            groups = r.get("groups", 0)
            expired = r.get("expired", 0)
            print(f"  {table}: {expired} rows expired across {groups} duplicate groups")

    if dry:
        print("\nRun with --apply to execute.")


if __name__ == "__main__":
    main()
