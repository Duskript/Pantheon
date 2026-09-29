-- Ichor Memory Engine — Events Schema
-- Phase 0 Foundation: Events table + FTS5 full-text search + indexes
-- Part of the Pantheon system

-- Events table: extracted facts from god sessions
CREATE TABLE IF NOT EXISTS ichor_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    predicate TEXT,
    object TEXT,
    confidence REAL DEFAULT 0.8,
    source TEXT,  -- 'tier_a' | 'tier_b' | 'manual'
    raw_text TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    god_name TEXT
);

-- FTS5 virtual table for full-text search on events
CREATE VIRTUAL TABLE IF NOT EXISTS ichor_events_fts USING fts5(
    subject, predicate, object, raw_text,
    content='ichor_events',
    content_rowid='id',
    tokenize='porter unicode61'
);

-- Trigger: keep FTS in sync on INSERT
CREATE TRIGGER IF NOT EXISTS ichor_events_ai AFTER INSERT ON ichor_events BEGIN
    INSERT INTO ichor_events_fts(rowid, subject, predicate, object, raw_text)
    VALUES (new.id, new.subject, new.predicate, new.object, new.raw_text);
END;

-- Trigger: keep FTS in sync on DELETE
CREATE TRIGGER IF NOT EXISTS ichor_events_ad AFTER DELETE ON ichor_events BEGIN
    INSERT INTO ichor_events_fts(ichor_events_fts, rowid, subject, predicate, object, raw_text)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.raw_text);
END;

-- Trigger: keep FTS in sync on UPDATE
CREATE TRIGGER IF NOT EXISTS ichor_events_au AFTER UPDATE ON ichor_events BEGIN
    INSERT INTO ichor_events_fts(ichor_events_fts, rowid, subject, predicate, object, raw_text)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.raw_text);
    INSERT INTO ichor_events_fts(rowid, subject, predicate, object, raw_text)
    VALUES (new.id, new.subject, new.predicate, new.object, new.raw_text);
END;

-- Indexes for fast lookup
CREATE INDEX IF NOT EXISTS idx_ichor_events_session_type ON ichor_events(session_id, event_type);
CREATE INDEX IF NOT EXISTS idx_ichor_events_created_at ON ichor_events(created_at);
CREATE INDEX IF NOT EXISTS idx_ichor_events_god_name ON ichor_events(god_name);

-- ===========================================================================
-- Hindsight-Inspired Memory Upgrades (additive, migration-safe)
-- Spec: plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md
-- Event temporal columns are added via Python migration helpers in
-- lib/ichor_db.py (_run_schema_migrations) — SQLite cannot reliably do
-- ALTER TABLE ADD COLUMN IF NOT EXISTS, so the ALTERs live in Python.
-- ===========================================================================

-- Event temporal columns and their indexes are added by the Python migration
-- helper in lib/ichor_db.py (_run_schema_migrations) — the columns do not
-- exist yet when this schema executescripts, so SQLite would reject any
-- CREATE INDEX referencing them here.

-- Event tags: join table so strict matching stays queryable
CREATE TABLE IF NOT EXISTS ichor_event_tags (
    event_id INTEGER NOT NULL REFERENCES ichor_events(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(event_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_ichor_event_tags_tag ON ichor_event_tags(tag);
CREATE INDEX IF NOT EXISTS idx_ichor_event_tags_event ON ichor_event_tags(event_id);

-- Observations: consolidated, evidence-grounded beliefs
CREATE TABLE IF NOT EXISTS ichor_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT,
    object TEXT,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.8,
    proof_count INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT,
    last_seen TEXT,
    evidence_span_days REAL DEFAULT 0,
    trend TEXT DEFAULT 'new',
    status TEXT DEFAULT 'active',
    superseded_by INTEGER REFERENCES ichor_observations(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(subject, predicate, category, content)
);

CREATE TABLE IF NOT EXISTS ichor_observation_sources (
    observation_id INTEGER NOT NULL REFERENCES ichor_observations(id) ON DELETE CASCADE,
    event_id INTEGER REFERENCES ichor_events(id) ON DELETE SET NULL,
    conclusion_id INTEGER,
    quote TEXT NOT NULL,
    relevance TEXT,
    source_session_id TEXT,
    source_god_name TEXT,
    source_timestamp TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(observation_id, event_id, conclusion_id)
);

CREATE TABLE IF NOT EXISTS ichor_observation_tags (
    observation_id INTEGER NOT NULL REFERENCES ichor_observations(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(observation_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_ichor_observations_subject ON ichor_observations(subject);
CREATE INDEX IF NOT EXISTS idx_ichor_observations_category ON ichor_observations(category);
CREATE INDEX IF NOT EXISTS idx_ichor_observations_status ON ichor_observations(status);
CREATE INDEX IF NOT EXISTS idx_ichor_observations_last_seen ON ichor_observations(last_seen);
CREATE INDEX IF NOT EXISTS idx_ichor_observation_tags_tag ON ichor_observation_tags(tag);

-- Observation FTS (content-synced via triggers)
CREATE VIRTUAL TABLE IF NOT EXISTS ichor_observations_fts USING fts5(
    subject, predicate, object, content,
    content='ichor_observations',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS ichor_observations_ai AFTER INSERT ON ichor_observations BEGIN
    INSERT INTO ichor_observations_fts(rowid, subject, predicate, object, content)
    VALUES (new.id, new.subject, new.predicate, new.object, new.content);
END;

CREATE TRIGGER IF NOT EXISTS ichor_observations_ad AFTER DELETE ON ichor_observations BEGIN
    INSERT INTO ichor_observations_fts(ichor_observations_fts, rowid, subject, predicate, object, content)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.content);
END;

CREATE TRIGGER IF NOT EXISTS ichor_observations_au AFTER UPDATE ON ichor_observations BEGIN
    INSERT INTO ichor_observations_fts(ichor_observations_fts, rowid, subject, predicate, object, content)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.content);
    INSERT INTO ichor_observations_fts(rowid, subject, predicate, object, content)
    VALUES (new.id, new.subject, new.predicate, new.object, new.content);
END;

-- Knowledge pages: rebuildable projections from observations (NOT source of truth)
CREATE TABLE IF NOT EXISTS ichor_knowledge_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    question TEXT NOT NULL,
    scope_tags_json TEXT NOT NULL DEFAULT '[]',
    content_md TEXT NOT NULL,
    source_observation_ids_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    refresh_status TEXT NOT NULL DEFAULT 'fresh',
    stale_after TEXT,
    last_refreshed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ichor_knowledge_page_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES ichor_knowledge_pages(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content_md TEXT NOT NULL,
    source_observation_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(page_id, version)
);

CREATE INDEX IF NOT EXISTS idx_ichor_knowledge_pages_key ON ichor_knowledge_pages(key);
CREATE INDEX IF NOT EXISTS idx_ichor_knowledge_pages_refresh ON ichor_knowledge_pages(refresh_status, stale_after);
