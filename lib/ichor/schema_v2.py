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

-- VECTOR: sqlite-vec embeddings of cold_events.raw_text
-- Added 2026-06-20 (P5a — semantic search recovery). One 384-dim vector
-- per event. Populated by scripts/backfill-embeddings.py for the
-- existing corpus and by lib/ichor_db.py on every ichor_store() write.
-- See lib/ichor/embedder.py for the embedder and lib/ichor/vector_backend.py
-- for the search interface.
CREATE VIRTUAL TABLE IF NOT EXISTS event_embeddings USING vec0(
    event_id INTEGER PRIMARY KEY,
    embedding float[384]
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

-- L2_SCENARIOS: Cross-session pattern layer (P5d, 2026-06-21)
-- The ichor-v2-build-blueprint.md §1 calls this the L2 "Scenario" layer.
-- The Overnight Forge collects L1 events, finds cross-session patterns,
-- and writes them here as structured rows. Each row has a deterministic
-- slug, a pattern_type, the source events that fed it, the sessions
-- involved, and a confidence score. The L2 Reference Backend (P5c) reads
-- from this table (alongside warm_entities + reference_knowledge) so
-- the patterns surface in ichor_retrieve.
--
-- Design notes:
-- - slug is UNIQUE so re-runs of the forge are idempotent (the same
--   pattern gets the same row, not a duplicate).
-- - source_events + source_sessions are JSON arrays stored as TEXT.
--   SQLite doesn't have native JSON columns; we use TEXT + json.loads()
--   at read time. This matches the rest of Ichor's convention.
-- - confidence is 0.0-1.0, set by the forge agent based on the
--   evidence density (more sources + more sessions = higher confidence).
-- - status is 'active' | 'superseded' | 'retired'. We do not delete
--   scenarios; the decay/eviction scripts treat them like warm_entities.
CREATE TABLE IF NOT EXISTS l2_scenarios (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    pattern_type TEXT DEFAULT 'cross_session',  -- 'cross_session' | 'recurring_blocker' | 'open_commitment' | 'stale_decision'
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source_events TEXT DEFAULT '[]',   -- JSON array of event ids
    source_sessions TEXT DEFAULT '[]', -- JSON array of session ids
    source_gods TEXT DEFAULT '[]',     -- JSON array of god names
    confidence REAL DEFAULT 0.5,       -- 0.0-1.0
    provenance_refs TEXT DEFAULT '[]',  -- JSON array of cold_event names cited
    status TEXT DEFAULT 'active',       -- 'active' | 'superseded' | 'retired'
    event_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0,
    first_seen TEXT,                   -- earliest source event timestamp
    last_seen TEXT,                    -- latest source event timestamp
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_l2_scenarios_status ON l2_scenarios(status);
CREATE INDEX IF NOT EXISTS idx_l2_scenarios_pattern ON l2_scenarios(pattern_type);
CREATE INDEX IF NOT EXISTS idx_l2_scenarios_confidence ON l2_scenarios(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_l2_scenarios_last_seen ON l2_scenarios(last_seen DESC);

-- CLAIMS: Crystallized facts with source evidence and entity links (Phase 0A)
CREATE TABLE IF NOT EXISTS ichor_claims (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'fact',
    status TEXT NOT NULL DEFAULT 'hypothesis',
    zone TEXT,
    tension_score REAL,
    confidence REAL NOT NULL DEFAULT 0.5,
    trust_score REAL,
    valid_from TEXT DEFAULT (datetime('now')),
    valid_to TEXT,
    extracted_by TEXT NOT NULL DEFAULT 'manual',
    source_session_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_claims_status ON ichor_claims(status);
CREATE INDEX IF NOT EXISTS idx_claims_type ON ichor_claims(type);
CREATE INDEX IF NOT EXISTS idx_claims_session ON ichor_claims(source_session_id);

CREATE TABLE IF NOT EXISTS ichor_claim_evidence (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES ichor_claims(id) ON DELETE CASCADE,
    source_event_id INTEGER,
    source_session_id TEXT,
    excerpt TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (claim_id, source_event_id, source_session_id)
);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim ON ichor_claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_event ON ichor_claim_evidence(source_event_id);

CREATE TABLE IF NOT EXISTS ichor_claim_entities (
    id INTEGER PRIMARY KEY,
    claim_id INTEGER NOT NULL REFERENCES ichor_claims(id) ON DELETE CASCADE,
    entity_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'subject',
    embedding TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE (claim_id, entity_name, role)
);
CREATE INDEX IF NOT EXISTS idx_claim_entities_claim ON ichor_claim_entities(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_entities_name ON ichor_claim_entities(entity_name);
"""


def get_conn() -> sqlite3.Connection:
    """Open a connection with WAL mode and Row factory.

    Loads sqlite-vec extension if available (P5a, 2026-06-20). If the
    extension is missing, logs a warning but returns the connection
    anyway — the FTS5/cold_events tables will still be created, but the
    vec0 table creation in SCHEMA_SQL will fail and the migration will
    surface the error. Failure mode stays loud, no silent breakage.

    The sqlite-vec load is wrapped in try/except because:
    1. Not all environments have sqlite-vec installed (older deployments).
    2. The vec0 virtual table is optional — without it the system still
       works via FTS5 + Graph + Events, just without semantic search.
    3. A noisy error is preferable to a silent skip: operators should
       know if their semantic-search feature isn't actually running.
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Load sqlite-vec (P5a). Best-effort: log and continue if unavailable.
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        logger.debug("sqlite-vec extension loaded")
    except Exception as exc:
        logger.warning("sqlite-vec not loadable: %s", exc)
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
                  "strategic_goals", "ichor_claims", "ichor_claim_evidence",
                  "ichor_claim_entities"]:
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
    for table in ["ichor_claim_entities", "ichor_claim_evidence", "ichor_claims",
                  "memory_fts", "hot_state", "warm_entities", "cold_events",
                  "reference_knowledge", "archive_retired", "strategic_goals"]:
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
