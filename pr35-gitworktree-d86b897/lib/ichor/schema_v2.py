"""
Ichor Schema v2 — 5-tier memory architecture (Sibyl-inspired).

Moved from `lib/ichor_schema_v2.py` into the ichor package on
2026-06-12 as part of the package refactor (Thoth answered Q1
with "inside the package, clean break"). Public surface unchanged:
SCHEMA_SQL, DB_PATH, migrate(), validate(), rollback(), status(),
plus the CLI entry point.

Tables:
  hot_state:        Per-session live working state (rewritten in place)
  warm_entities:    Single source of truth per (category, name) — Rule 43
  cold_events:      Append-only event log (replaces ichor_events)
  reference_knowledge:  Static curated knowledge (distilled concepts)
  archive_retired:  Pruned warm_entities kept for audit
  strategic_goals:  Long-lived strategic goals tracked across sessions (A1)

Usage:
    python3 -m lib.ichor.schema_v2 --migrate    # Create + backfill
    python3 -m lib.ichor.schema_v2 --validate   # Verify backfill
    python3 -m lib.ichor.schema_v2 --rollback   # Drop new tables
    python3 -m lib.ichor.schema_v2 --status     # Show current state
"""

import argparse
import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger("lib.ichor.schema_v2")  # was "ichor_schema_v2" pre-2026-06-12

DB_PATH = Path.home() / ".hermes" / "ichor.db"

SCHEMA_SQL = """
-- HOT: Live per-session working state
CREATE TABLE IF NOT EXISTS hot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    session_id TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- WARM: Single source of truth per (category, name) — Rule 43 enforced
CREATE TABLE IF NOT EXISTS warm_entities (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    importance REAL DEFAULT 50.0,
    trust REAL DEFAULT 50.0,
    maturity TEXT DEFAULT 'validated',
    last_access TEXT,
    related_to TEXT,
    brief TEXT DEFAULT '',
    outline TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE (category, name)
);

-- COLD: Append-only event log
CREATE TABLE IF NOT EXISTS cold_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT,
    category TEXT,
    name TEXT,
    confidence REAL DEFAULT 0.5,
    importance REAL DEFAULT 50.0,
    trust REAL DEFAULT 50.0,
    raw_text TEXT,
    brief TEXT DEFAULT '',
    outline TEXT DEFAULT '',
    speaker TEXT,
    session_id TEXT,
    god_name TEXT,
    direction TEXT DEFAULT 'unknown',
    peer_god TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now'))
);

-- REFERENCE: Static curated knowledge (distilled concepts)
CREATE TABLE IF NOT EXISTS reference_knowledge (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    title TEXT,
    body TEXT,
    brief TEXT DEFAULT '',
    outline TEXT DEFAULT '',
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- ARCHIVE: Retired warm_entities kept for audit
CREATE TABLE IF NOT EXISTS archive_retired (
    id INTEGER PRIMARY KEY,
    original_id INTEGER,
    category TEXT,
    name TEXT,
    value TEXT,
    importance REAL,
    trust REAL,
    retired_reason TEXT,
    retired_at TEXT DEFAULT (datetime('now'))
);

-- FTS5 over cold_events (regular non-external FTS5 — simpler, no triggers needed)
-- Includes brief + outline so the TieredRetriever (B2) can search tier-L0/L1
-- without scanning full raw_text. Drop+recreate when adding columns.
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content, category, name, event_type, brief, outline,
    tokenize='porter unicode61'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_warm_category ON warm_entities(category);
CREATE INDEX IF NOT EXISTS idx_warm_importance ON warm_entities(importance DESC);
CREATE INDEX IF NOT EXISTS idx_cold_god ON cold_events(god_name);
CREATE INDEX IF NOT EXISTS idx_cold_created ON cold_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cold_type ON cold_events(event_type);
CREATE INDEX IF NOT EXISTS idx_ref_slug ON reference_knowledge(slug);

-- STRATEGIC_GOALS: Long-lived goals (A1, 2026-06-11)
-- Distinct from hermes_cli/goals.py (per-turn judge) — this is the
-- memory-layer registry. cold_events.goal_id optionally links an event
-- to the goal it advances; see lib/ichor_goals.py for CRUD.
CREATE TABLE IF NOT EXISTS strategic_goals (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    category TEXT DEFAULT 'general',       -- 'theoforge', 'pantheon', 'skc'
    priority INTEGER DEFAULT 5,            -- 1-10
    status TEXT DEFAULT 'active',          -- active | paused | completed | abandoned
    progress REAL DEFAULT 0.0,             -- 0.0 to 1.0
    target_date TEXT DEFAULT '',
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_goals_status ON strategic_goals(status);
CREATE INDEX IF NOT EXISTS idx_goals_priority ON strategic_goals(priority DESC);
CREATE INDEX IF NOT EXISTS idx_goals_category ON strategic_goals(category);
"""


def get_conn() -> sqlite3.Connection:
    """Open a connection with WAL mode and Row factory."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def migrate() -> None:
    """Create 5-tier tables and backfill from ichor_events."""
    conn = get_conn()

    # Create tables (idempotent)
    conn.executescript(SCHEMA_SQL)
    logger.info("5-tier schema tables created")

    # A1 migration: add goal_id to cold_events (idempotent pragma check,
    # works on pre-existing tables that were created before A1 shipped)
    has_goal_id = conn.execute(
        "SELECT 1 FROM pragma_table_info('cold_events') WHERE name='goal_id' LIMIT 1"
    ).fetchone()
    if not has_goal_id:
        conn.execute("ALTER TABLE cold_events ADD COLUMN goal_id INTEGER REFERENCES strategic_goals(id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cold_goal ON cold_events(goal_id)")
        logger.info("A1 migration: added goal_id column to cold_events")

    # Backfill: ichor_events → cold_events
    existing = conn.execute("SELECT id FROM cold_events LIMIT 1").fetchone()
    if not existing:
        # Use the existing importance/trust columns that P0b's hooks populated
        conn.execute("""
            INSERT INTO cold_events (
                event_type, category, name, confidence, importance, trust,
                raw_text, speaker, session_id, god_name, direction, peer_god, created_at
            )
            SELECT
                event_type, 'event', subject, confidence, importance, trust,
                raw_text, NULL, session_id, god_name, direction, peer_god, created_at
            FROM ichor_events
        """)
        n = conn.execute("SELECT COUNT(*) AS cnt FROM cold_events").fetchone()["cnt"]
        logger.info("Backfilled ichor_events → cold_events (%d rows)", n)

    # Backfill: high-importance ichor_events → warm_entities
    existing = conn.execute("SELECT id FROM warm_entities LIMIT 1").fetchone()
    if not existing:
        conn.execute("""
            INSERT OR IGNORE INTO warm_entities
                (category, name, value, importance, trust, maturity, related_to, created_at)
            SELECT
                event_type,
                COALESCE(NULLIF(subject, ''), 'event_' || id),
                COALESCE(NULLIF(object, ''), raw_text),
                importance, trust, maturity,
                CASE WHEN direction != 'unknown'
                     THEN 'direction:' || direction || ',peer:' || COALESCE(peer_god, '')
                     ELSE NULL
                END,
                created_at
            FROM ichor_events
            WHERE importance >= 20
        """)
        n = conn.execute("SELECT COUNT(*) AS cnt FROM warm_entities").fetchone()["cnt"]
        logger.info("Backfilled ichor_events → warm_entities (%d rows, importance >= 20)", n)

    # Populate memory_fts from cold_events (idempotent)
    existing_fts = conn.execute(
        "SELECT COUNT(*) AS cnt FROM memory_fts"
    ).fetchone()["cnt"]
    if existing_fts == 0:
        conn.execute("""
            INSERT INTO memory_fts (rowid, content, category, name, event_type)
            SELECT id,
                   COALESCE(raw_text, ''),
                   COALESCE(category, ''),
                   COALESCE(name, ''),
                   COALESCE(event_type, '')
            FROM cold_events
        """)
        n = conn.execute("SELECT COUNT(*) AS cnt FROM memory_fts").fetchone()["cnt"]
        logger.info("Populated memory_fts from cold_events (%d rows)", n)
    else:
        logger.info("memory_fts already populated (%d rows)", existing_fts)

    conn.commit()
    conn.close()
    logger.info("Migration complete")


def validate() -> dict:
    """Verify backfill was successful. Returns counts per table."""
    conn = get_conn()
    counts = {}
    for table in ["hot_state", "warm_entities", "cold_events",
                  "reference_knowledge", "archive_retired", "memory_fts",
                  "strategic_goals"]:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
            counts[table] = row["cnt"] if row else 0
        except sqlite3.OperationalError as exc:
            counts[table] = f"MISSING ({exc})"

    # Source-of-truth count for comparison
    try:
        src = conn.execute("SELECT COUNT(*) AS cnt FROM ichor_events").fetchone()["cnt"]
        counts["_ichor_events (source)"] = src
    except sqlite3.OperationalError:
        counts["_ichor_events (source)"] = "table not found"

    conn.close()
    return counts


def rollback() -> None:
    """Drop new tables (for testing or reversal)."""
    conn = get_conn()
    for table in ["memory_fts", "hot_state", "warm_entities", "cold_events",
                  "reference_knowledge", "archive_retired",
                  "strategic_goals"]:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    # Triggers dropped automatically when their table is dropped
    conn.commit()
    conn.close()
    logger.info("Schema v2 tables dropped (rollback complete)")


def status() -> dict:
    """Show current state of all v2 tables."""
    return validate()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ichor Schema v2 — 5-tier memory")
    parser.add_argument("--migrate", action="store_true", help="Create tables + backfill")
    parser.add_argument("--validate", action="store_true", help="Verify backfill")
    parser.add_argument("--rollback", action="store_true", help="Drop new tables")
    parser.add_argument("--status", action="store_true", help="Show current state")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.migrate:
        migrate()
        print(json.dumps(validate(), indent=2))
    elif args.validate:
        print(json.dumps(validate(), indent=2))
    elif args.rollback:
        rollback()
        print(json.dumps(validate(), indent=2))
    elif args.status:
        print(json.dumps(validate(), indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
