"""
Ichor V2 schema migration — backfill temporal columns on `entities`.

Phase 0b of ichor-v2-build-blueprint.md §2. The schema columns were
added by `v2_temporal.py` (migration `ichor_v2_temporal_001`) but
the existing 13,452 entity rows were never backfilled — the columns
are 100% NULL. This migration:

  1. Backfills `valid_from = created_at` for all entities.
     The "orthogonal origin timestamp" per the spec.

  2. For entities with `status='merged'` and `merged_into IS NOT NULL`:
        - `valid_until = updated_at`  (when the merge happened)
        - `superseded_by = merged_into`  (FK to the survivor)
     This makes the existing merge data bitemporally queryable.

  3. Active entities (`status='active'`):
        - `valid_until = NULL`  (still valid)
        - `superseded_by = NULL`  (no successor)

Idempotent: re-running is a no-op because every row already has
`valid_from` set on the first run, and the UPDATE for merged rows
re-applies the same values.

Run from /home/konan/pantheon:

    python3 -c "
    import sys; sys.path.insert(0, '.')
    from lib.ichor.migrations.v2_temporal_backfill import run_migration
    run_migration()
    "

Returns a dict describing what was applied (counts of rows updated).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".hermes" / "ichor.db"
MIGRATION_KEY = "ichor_v2_temporal_backfill_002"


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return False
    return any(r[1] == column for r in rows)


def run_migration(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Backfill temporal columns on existing `entities` rows."""
    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        # Pre-flight: the column-add migration must have run first.
        for col in ("valid_from", "valid_until", "superseded_by"):
            if not _column_exists(conn, "entities", col):
                return {
                    "applied": False,
                    "migration": MIGRATION_KEY,
                    "error": (
                        f"entities.{col} does not exist — run "
                        f"lib.ichor.migrations.v2_temporal.run_migration() first"
                    ),
                }

        # Count what's currently null so we can report progress.
        null_vf = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE valid_from IS NULL"
        ).fetchone()[0]
        null_vu = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE valid_until IS NULL"
        ).fetchone()[0]
        merged_rows = conn.execute(
            "SELECT COUNT(*) FROM entities "
            "WHERE status='merged' AND merged_into IS NOT NULL"
        ).fetchone()[0]

        # ---- 1. Backfill valid_from = created_at for all rows that lack it.
        # Idempotent: only writes to rows where valid_from is still NULL.
        active_vf = conn.execute(
            "UPDATE entities SET valid_from = created_at "
            "WHERE valid_from IS NULL AND created_at IS NOT NULL"
        )
        active_vf_count = active_vf.rowcount

        # ---- 2. Backfill valid_until + superseded_by for merged entities.
        # These are the rows where status='merged' and merged_into is set.
        # valid_until = updated_at (the moment of merge), superseded_by = merged_into.
        merged_uv = conn.execute(
            "UPDATE entities "
            "SET valid_until = updated_at, superseded_by = merged_into "
            "WHERE status='merged' AND merged_into IS NOT NULL "
            "  AND (valid_until IS NULL OR superseded_by IS NULL)"
        )
        merged_uv_count = merged_uv.rowcount

        # ---- 3. Mark the migration as applied.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ichor_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        before = conn.execute(
            "SELECT value FROM ichor_settings WHERE key=?", (MIGRATION_KEY,)
        ).fetchone()
        if before is None:
            conn.execute(
                "INSERT INTO ichor_settings (key, value) VALUES (?, ?)",
                (MIGRATION_KEY, "applied"),
            )

        conn.commit()

        return {
            "applied": True,
            "migration": MIGRATION_KEY,
            "backfilled_valid_from": active_vf_count,
            "backfilled_merged_rows": merged_uv_count,
            "pre_state": {
                "entities_with_null_valid_from": null_vf,
                "entities_with_null_valid_until": null_vu,
                "merged_entities_total": merged_rows,
            },
            "previously_applied": before is not None,
        }
    finally:
        conn.close()


def status(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Return the migration's current state without applying anything."""
    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    try:
        applied = None
        try:
            row = conn.execute(
                "SELECT value FROM ichor_settings WHERE key=?",
                (MIGRATION_KEY,),
            ).fetchone()
            applied = row[0] if row else None
        except sqlite3.OperationalError:
            pass

        null_vf = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE valid_from IS NULL"
        ).fetchone()[0]
        merged_with_temporal = conn.execute(
            "SELECT COUNT(*) FROM entities "
            "WHERE status='merged' AND valid_until IS NOT NULL "
            "  AND superseded_by IS NOT NULL"
        ).fetchone()[0]
        merged_total = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE status='merged'"
        ).fetchone()[0]

        return {
            "migration": MIGRATION_KEY,
            "applied": applied,
            "entities_still_missing_valid_from": null_vf,
            "merged_entities_with_temporal_set": merged_with_temporal,
            "merged_entities_total": merged_total,
            "fully_populated": null_vf == 0 and merged_with_temporal == merged_total,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    import sys

    if "--status" in sys.argv:
        print(json.dumps(status(), indent=2))
    else:
        print(json.dumps(run_migration(), indent=2))
