"""
Ichor V2 schema migration — temporal columns + orthogonal indexes.

Phase 0 of ichor-v2-build-blueprint.md §2. Adds:

  1. Temporal columns on graph nodes (`entities`):
        - valid_from     TEXT NULL  — when this entity became known
        - valid_until    TEXT NULL  — when this entity stopped being valid
        - superseded_by  INTEGER    — FK to entities(id) of the survivor

     Note: `relationships` and `entity_facts` already had valid_from/valid_to
     since the ER-P0 schema landed; this migration brings `entities` to parity.

  2. Orthogonal search indexes on the canonical cold-events store
     (`cold_events`):
        - idx_cold_god_type_date  compound (god_name, event_type, created_at)
        - idx_cold_type_date      compound (event_type, created_at)
        - idx_cold_freshness      partial — created_at DESC WHERE importance > 0.1

     And on the legacy single-tier table (`ichor_events`) for back-compat:
        - idx_ichor_events_god_type_date  compound (god_name, event_type, created_at)

  3. Migration tracking table `ichor_settings` (key/value) with a row
     recording this migration as applied.

Idempotent: every DDL uses IF NOT EXISTS or is gated on a pragma_table_info
check, so re-running on an already-migrated DB is a no-op.

Run from /home/konan/pantheon:

    python3 -c "
    import sys; sys.path.insert(0, '.')
    from lib.ichor.migrations.v2_temporal import run_migration
    run_migration()
    "

Or via the re-export:

    from lib.ichor import run_migration
    run_migration('/home/konan/.hermes/ichor.db')

Returns a dict describing what was applied (or skipped if already applied).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".hermes" / "ichor.db"
MIGRATION_KEY = "ichor_v2_temporal_001"


def _existing_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the set of column names on `table` (empty set if missing)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.OperationalError:
        return set()
    return {row[1] for row in rows}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    ddl_fragment: str,
) -> bool:
    """Add `column` to `table` if it isn't there yet. Returns True if added."""
    if column in _existing_columns(conn, table):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_fragment}")
    return True


def run_migration(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Apply the v2_temporal migration to the Ichor database.

    Idempotent. Safe to re-run. Returns a dict summarizing what was done.
    """
    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        added_columns: list[str] = []
        added_indexes: list[str] = []

        # ---- 1. Temporal columns on graph nodes (entities) ----
        # `relationships` and `entity_facts` already have valid_from/valid_to
        # from ER-P0 — we only need to add them to `entities` to complete
        # the graph layer's temporal coverage.
        if _existing_columns(conn, "entities"):
            if _add_column_if_missing(
                conn, "entities", "valid_from", "TEXT DEFAULT NULL"
            ):
                added_columns.append("entities.valid_from")
            if _add_column_if_missing(
                conn, "entities", "valid_until", "TEXT DEFAULT NULL"
            ):
                added_columns.append("entities.valid_until")
            # superseded_by is distinct from merged_into:
            #   merged_into      — explicit merge operation (status='merged')
            #   superseded_by    — temporal lineage (this fact was replaced by)
            if _add_column_if_missing(
                conn,
                "entities",
                "superseded_by",
                "INTEGER DEFAULT NULL REFERENCES entities(id)",
            ):
                added_columns.append("entities.superseded_by")
        else:
            # The graph layer hasn't landed yet. Skip silently — the blueprint
            # is forward-looking; this migration is a no-op until entities
            # exists. The migration marker is still set so subsequent runs
            # don't retry on a DB that hasn't reached ER-P0.
            pass

        # ---- 2. Temporal indexes on entities ----
        temporal_idx_sql = [
            (
                "idx_entities_temporal",
                "CREATE INDEX IF NOT EXISTS idx_entities_temporal "
                "ON entities(valid_from, valid_until)",
            ),
            (
                "idx_entities_valid_until",
                "CREATE INDEX IF NOT EXISTS idx_entities_valid_until "
                "ON entities(valid_until) WHERE valid_until IS NOT NULL",
            ),
        ]
        for name, ddl in temporal_idx_sql:
            before = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            conn.execute(ddl)
            if before is None:
                added_indexes.append(name)

        # ---- 3. Orthogonal indexes on the canonical cold-events store ----
        cold_idx_sql = [
            (
                "idx_cold_god_type_date",
                "CREATE INDEX IF NOT EXISTS idx_cold_god_type_date "
                "ON cold_events(god_name, event_type, created_at)",
            ),
            (
                "idx_cold_type_date",
                "CREATE INDEX IF NOT EXISTS idx_cold_type_date "
                "ON cold_events(event_type, created_at)",
            ),
            (
                "idx_cold_freshness",
                "CREATE INDEX IF NOT EXISTS idx_cold_freshness "
                "ON cold_events(created_at DESC) WHERE importance > 0.1",
            ),
        ]
        for name, ddl in cold_idx_sql:
            before = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            conn.execute(ddl)
            if before is None:
                added_indexes.append(name)

        # ---- 4. Orthogonal indexes on legacy ichor_events (back-compat) ----
        legacy_idx_sql = [
            (
                "idx_ichor_events_god_type_date",
                "CREATE INDEX IF NOT EXISTS idx_ichor_events_god_type_date "
                "ON ichor_events(god_name, event_type, created_at)",
            ),
        ]
        for name, ddl in legacy_idx_sql:
            if not _existing_columns(conn, "ichor_events"):
                # Legacy table may have been dropped entirely; skip silently.
                continue
            before = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            conn.execute(ddl)
            if before is None:
                added_indexes.append(name)

        # ---- 5. Migration tracking table + marker row ----
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ichor_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        # Idempotent insert: only writes if the key doesn't already exist.
        # This makes re-running the migration a no-op (no overwrite, no
        # updated_at churn).
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
            "added_columns": added_columns,
            "added_indexes": added_indexes,
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

        ents_cols = _existing_columns(conn, "entities")
        cold_cols = _existing_columns(conn, "cold_events")

        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
        ).fetchall()
        idx_names = {r[0] for r in idx_rows}

        return {
            "migration": MIGRATION_KEY,
            "applied": applied,
            "entities_has_valid_from": "valid_from" in ents_cols,
            "entities_has_valid_until": "valid_until" in ents_cols,
            "entities_has_superseded_by": "superseded_by" in ents_cols,
            "cold_events_exists": bool(cold_cols),
            "indexes_present": {
                "idx_entities_temporal": "idx_entities_temporal" in idx_names,
                "idx_entities_valid_until": "idx_entities_valid_until" in idx_names,
                "idx_cold_god_type_date": "idx_cold_god_type_date" in idx_names,
                "idx_cold_type_date": "idx_cold_type_date" in idx_names,
                "idx_cold_freshness": "idx_cold_freshness" in idx_names,
                "idx_ichor_events_god_type_date": (
                    "idx_ichor_events_god_type_date" in idx_names
                ),
            },
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
