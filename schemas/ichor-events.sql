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
