"""
Ichor V2 schema migration — L2 Scenarios table (P5d, 2026-06-21).

Phase 0d of ichor-v2-build-blueprint.md §1 — the L2 "Scenario" layer
that the v2 architecture diagram calls out as the cross-session pattern
store between L1 atomic events and L3 persona views.

The Overnight Forge (cron c7c93416a2dc) was already emitting cross-
session patterns as `digest_entry` events back to L1. This migration
adds a structured L2 table that the Forge will write to instead. The
table is a strict superset of what the digest_entry events encoded —
each scenario row has the same metadata + a unique slug + a confidence
score + provenance_refs to the cold_events that fed it.

Idempotent: re-running is a no-op because every DDL is `IF NOT EXISTS`
and the migration marker is only inserted when missing.

Run from /home/konan/pantheon:

    python3 -c "
    import sys; sys.path.insert(0, '.')
    from lib.ichor.migrations.v2_l2_scenarios import run_migration
    run_migration()
    "

Or via the re-export:

    from lib.ichor import run_l2_scenarios_migration
    run_l2_scenarios_migration()

Returns a dict describing what was applied.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path.home() / ".hermes" / "ichor.db"
MIGRATION_KEY = "ichor_v2_l2_scenarios_003"


def run_migration(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Create the l2_scenarios table and supporting indexes."""
    db_path = str(db_path)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        created_objects: list[str] = []

        # ---- 1. l2_scenarios table ----
        table_before = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='l2_scenarios'"
        ).fetchone()
        if table_before is None:
            conn.executescript("""
                CREATE TABLE l2_scenarios (
                    id INTEGER PRIMARY KEY,
                    slug TEXT UNIQUE NOT NULL,
                    pattern_type TEXT DEFAULT 'cross_session',
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source_events TEXT DEFAULT '[]',
                    source_sessions TEXT DEFAULT '[]',
                    source_gods TEXT DEFAULT '[]',
                    confidence REAL DEFAULT 0.5,
                    provenance_refs TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'active',
                    event_count INTEGER DEFAULT 0,
                    session_count INTEGER DEFAULT 0,
                    first_seen TEXT,
                    last_seen TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );
            """)
            created_objects.append("table:l2_scenarios")

        # ---- 2. Indexes (idempotent) ----
        idx_sql = [
            ("idx_l2_scenarios_status",
             "CREATE INDEX IF NOT EXISTS idx_l2_scenarios_status "
             "ON l2_scenarios(status)"),
            ("idx_l2_scenarios_pattern",
             "CREATE INDEX IF NOT EXISTS idx_l2_scenarios_pattern "
             "ON l2_scenarios(pattern_type)"),
            ("idx_l2_scenarios_confidence",
             "CREATE INDEX IF NOT EXISTS idx_l2_scenarios_confidence "
             "ON l2_scenarios(confidence DESC)"),
            ("idx_l2_scenarios_last_seen",
             "CREATE INDEX IF NOT EXISTS idx_l2_scenarios_last_seen "
             "ON l2_scenarios(last_seen DESC)"),
        ]
        for name, ddl in idx_sql:
            before = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
                (name,),
            ).fetchone()
            conn.execute(ddl)
            if before is None:
                created_objects.append(f"index:{name}")

        # ---- 3. Migration marker ----
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

        # Quick row count for visibility
        try:
            count = conn.execute("SELECT COUNT(*) FROM l2_scenarios").fetchone()[0]
        except Exception:
            count = 0

        return {
            "applied": True,
            "migration": MIGRATION_KEY,
            "created_objects": created_objects,
            "l2_scenarios_row_count": count,
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

        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='l2_scenarios'"
        ).fetchone() is not None

        idx_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_l2_%'"
        ).fetchall()
        idx_names = [r[0] for r in idx_rows]

        try:
            count = conn.execute("SELECT COUNT(*) FROM l2_scenarios").fetchone()[0]
        except Exception:
            count = "table-missing"

        return {
            "migration": MIGRATION_KEY,
            "applied": applied,
            "l2_scenarios_table_exists": table_exists,
            "l2_scenarios_index_count": len(idx_names),
            "l2_scenarios_index_names": idx_names,
            "l2_scenarios_row_count": count,
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
