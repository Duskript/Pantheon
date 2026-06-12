"""Ichor entities — schema (ER-P0).

Adds 6 new tables to ~/.hermes/ichor.db for the entity-relationship
graph layer. Additive: does not touch any existing table.

Tables:
    entity_types        — extensible registry of entity types (person, organization, ...)
    entities            — nodes (the "things" in the graph)
    relationship_types  — extensible registry of relationship types (works_at, cites, ...)
    relationships       — edges (typed, bitemporal valid_from/valid_to)
    entity_facts        — typed properties on entities (mrr, valuation, arxiv_id, ...)
    extraction_log      — provenance for every extraction (regex/llm/manual/dream_cycle)

The design is in ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md

Usage:
    python3 -m lib.ichor.entities.schema --migrate    # Create tables + indexes
    python3 -m lib.ichor.entities.schema --validate   # Verify tables exist
    python3 -m lib.ichor.entities.schema --rollback   # Drop entity tables
    python3 -m lib.ichor.entities.schema --status     # Show counts per table

    from lib.ichor.entities import migrate, validate
    migrate()
    print(validate())
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

# B1 (Pass 3.1) — seed canonical relationship types. Imported here
# so that calling `migrate()` from anywhere in the ichor.entities
# package also seeds `learned_from`, `superseded_by`, and the rest
# of the canonical type set (idempotent, safe on existing DBs).
from lib.ichor.entities.relationship_type_seeds import (
    seed_relationship_types as _seed_relationship_types,
)

logger = logging.getLogger("ichor.entities.schema")

# Same path as the rest of the Ichor stack — we extend, not fork.
DB_PATH = Path.home() / ".hermes" / "ichor.db"

# Tables owned by this module. Order matters for DROP (children first).
# relationships and entity_facts reference entities; extraction_log
# references all three. We drop in reverse-creation order.
SCHEMA_TABLES: list[str] = [
    "extraction_log",
    "entity_facts",
    "relationships",
    "relationship_types",
    "entities",
    "entity_types",
]

# All 6 CREATE TABLE statements + their supporting indexes.
# Idempotent: every statement uses IF NOT EXISTS, every index too.
SCHEMA_SQL = """
-- ---------------------------------------------------------------------------
-- Entity types registry (extensible). 25+ types per design §Base Entity Types.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_types (
    id TEXT PRIMARY KEY,                                       -- 'person', 'organization', 'concept', ...
    description TEXT,                                          -- human-readable
    parent_type TEXT REFERENCES entity_types(id),              -- hierarchy: 'lead' inherits from 'organization'
    extractable BOOLEAN DEFAULT true,                          -- should L0/L1 regex try to extract this type?
    icon TEXT DEFAULT '📄',                                    -- for display
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entity_types_parent ON entity_types(parent_type);

-- ---------------------------------------------------------------------------
-- Entities (nodes). 25+ entity types per design §Base Entity Types.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    type_id TEXT NOT NULL REFERENCES entity_types(id),         -- FK to entity_types
    name TEXT NOT NULL,                                         -- display name
    aliases TEXT DEFAULT '[]',                                  -- JSON array of alternate names
    summary TEXT DEFAULT '',                                    -- L1 tier: ~500 char overview
    confidence REAL DEFAULT 1.0,                                -- 0.0 to 1.0 (from Hindsight)
    status TEXT DEFAULT 'active',                               -- active | archived | merged
    merged_into INTEGER REFERENCES entities(id),               -- when status='merged', points to survivor
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    last_accessed TEXT                                          -- for L4 decay calculation
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type_id);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_status ON entities(status);
CREATE INDEX IF NOT EXISTS idx_entities_last_accessed ON entities(last_accessed);

-- ---------------------------------------------------------------------------
-- Relationship types registry. 67+ types in 10 families per design §Relationship Type Taxonomy.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationship_types (
    id TEXT PRIMARY KEY,                                        -- 'works_at', 'cites', 'superseded_by', ...
    description TEXT,
    source_type TEXT REFERENCES entity_types(id),               -- valid source entity type
    target_type TEXT REFERENCES entity_types(id),               -- valid target entity type
    is_temporal BOOLEAN DEFAULT true,                           -- does this relationship have valid time bounds?
    is_directional BOOLEAN DEFAULT true,                        -- false for symmetric relations (similar_to, related_to)
    family TEXT,                                                -- 'affiliation', 'reference', 'lifecycle', ...
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_relationship_types_family ON relationship_types(family);

-- ---------------------------------------------------------------------------
-- Relationships (edges). Bitemporal: valid_from/valid_to (Zep pattern).
-- UNIQUE(type_id, source_id, target_id, valid_from) prevents duplicate
-- "factually true at time T" entries; allows re-recording the same
-- relationship at a different time.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY,
    type_id TEXT NOT NULL REFERENCES relationship_types(id),
    source_id INTEGER NOT NULL REFERENCES entities(id),
    target_id INTEGER NOT NULL REFERENCES entities(id),
    confidence REAL DEFAULT 1.0,                                -- 0.0 to 1.0
    weight REAL DEFAULT 1.0,                                    -- for ranking; decays over time
    provenance TEXT DEFAULT '',                                 -- 'regex', 'llm', 'manual', 'dream_cycle'
    source_ref TEXT DEFAULT '',                                 -- link to original text/message
    valid_from TEXT,                                            -- when this fact became true
    valid_to TEXT,                                              -- when this fact stopped being true (NULL = still true)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(type_id, source_id, target_id, valid_from)
);
CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(type_id);
CREATE INDEX IF NOT EXISTS idx_relationships_valid_to ON relationships(valid_to);
CREATE INDEX IF NOT EXISTS idx_relationships_provenance ON relationships(provenance);

-- ---------------------------------------------------------------------------
-- Entity facts (typed properties on entities — from GBrain's typed facts).
-- Multiple facts per entity (mrr, valuation, arxiv_id, severity, ...).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entity_facts (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id),
    key TEXT NOT NULL,                                          -- 'mrr', 'valuation', 'arxiv_id', 'severity'
    value TEXT NOT NULL,                                        -- '50000', '15000000', '2402.04253', 'p0'
    type TEXT DEFAULT 'string',                                 -- 'string', 'number', 'date', 'url'
    confidence REAL DEFAULT 1.0,
    valid_from TEXT,
    valid_to TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_entity_facts_entity ON entity_facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_facts_entity_key ON entity_facts(entity_id, key);

-- ---------------------------------------------------------------------------
-- Provenance log. Every extraction (regex, LLM, manual, dream_cycle) is logged.
-- One extraction may produce multiple entities + relationships + facts;
-- extraction_log tracks which came from where.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS extraction_log (
    id INTEGER PRIMARY KEY,
    entity_id INTEGER REFERENCES entities(id),
    relationship_id INTEGER REFERENCES relationships(id),
    fact_id INTEGER REFERENCES entity_facts(id),
    method TEXT NOT NULL,                                       -- 'regex', 'llm', 'manual', 'dream_cycle'
    source_text TEXT,                                           -- the text that triggered extraction
    source_session_id TEXT,                                     -- session where it was found
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_extraction_log_entity ON extraction_log(entity_id);
CREATE INDEX IF NOT EXISTS idx_extraction_log_relationship ON extraction_log(relationship_id);
CREATE INDEX IF NOT EXISTS idx_extraction_log_method ON extraction_log(method);
CREATE INDEX IF NOT EXISTS idx_extraction_log_session ON extraction_log(source_session_id);
"""


def get_conn(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection with WAL mode and Row factory.

    db_path defaults to the canonical ichor.db location. Override is
    provided for tests that want to use a temp DB.
    """
    path = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(db_path: Path | str | None = None) -> dict:
    """Create the 6 entity-graph tables + indexes, then apply incremental
    column-level migrations. Idempotent.

    Returns a small status dict with what was done. Safe to call
    multiple times.

    Column-level migrations live in `_MIGRATIONS` (a list of
    {table, column, ddl} dicts). Each runs only if the column doesn't
    already exist on the target table.
    """
    conn = get_conn(db_path)
    try:
        # Snapshot pre-state
        pre = {t: _table_exists(conn, t) for t in SCHEMA_TABLES}

        conn.executescript(SCHEMA_SQL)

        # Snapshot post-state
        post = {t: _table_exists(conn, t) for t in SCHEMA_TABLES}

        created = [t for t in SCHEMA_TABLES if not pre[t] and post[t]]
        already = [t for t in SCHEMA_TABLES if pre[t] and post[t]]

        # Sanity check
        missing = [t for t in SCHEMA_TABLES if not post[t]]
        if missing:
            raise RuntimeError(
                f"migration failed: tables still missing after executescript: {missing}"
            )

        # Apply column-level migrations (idempotent: skip if column exists)
        migrations_applied = _apply_column_migrations(conn)

        # B1 (Pass 3.1) — seed canonical relationship types
        # (learned_from, superseded_by, derived_from, replaces).
        # Idempotent: existing types are left untouched. Called after
        # column migrations so a fresh DB has the full type registry
        # ready before any L2 extraction runs. Failure here is logged
        # but does not fail the migration (seed is non-essential).
        try:
            seed_result = _seed_relationship_types(conn)
        except Exception as exc:  # noqa: BLE001
            logger.warning("relationship_type seed failed (non-fatal): %s", exc)
            seed_result = {"inserted": 0, "already_present": 0, "error": str(exc)}

        conn.commit()
        result = {
            "created": created,
            "already_present": already,
            "tables_total": len(SCHEMA_TABLES),
            "migrations_applied": migrations_applied,
            "seed_result": seed_result,
        }
        if created:
            logger.info("Created entity-graph tables: %s", created)
        else:
            logger.info("All 6 entity-graph tables already present (idempotent)")
        if migrations_applied:
            logger.info("Applied column migrations: %s", migrations_applied)
        if seed_result.get("inserted"):
            logger.info(
                "Seeded %d canonical relationship types: %s",
                seed_result["inserted"],
                seed_result,
            )
        return result
    finally:
        conn.close()


# Column-level migrations. Each entry: {table, column, ddl}.
# `ddl` is the full ALTER TABLE statement. Applied only if `column`
# doesn't already exist on `table` (idempotent).
#
# ER-P2 added:
#   - entities.provisional     (1 = inserted by incremental L2 pass, may be revised at finalize)
#   - relationships.provisional (same semantics for edges)
_MIGRATIONS: list[dict] = [
    {
        "table": "entities",
        "column": "provisional",
        "ddl": "ALTER TABLE entities ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0",
    },
    {
        "table": "relationships",
        "column": "provisional",
        "ddl": "ALTER TABLE relationships ADD COLUMN provisional INTEGER NOT NULL DEFAULT 0",
    },
]


def _apply_column_migrations(conn: sqlite3.Connection) -> list[str]:
    """Run each migration in _MIGRATIONS if the column doesn't exist.

    Returns a list of descriptions of what was actually applied.
    """
    applied: list[str] = []
    for m in _MIGRATIONS:
        table = m["table"]
        col = m["column"]
        # PRAGMA table_info returns one row per column; check if our col is there
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        existing_cols = {row[1] for row in rows}
        if col in existing_cols:
            continue
        conn.execute(m["ddl"])
        applied.append(f"{table}.{col}")
    return applied


def validate(db_path: Path | str | None = None) -> dict:
    """Verify all 6 entity tables exist and have no schema corruption.

    Returns a status dict. Each table is one of:
      "OK"                — exists, queryable, no NULL primary keys
      "MISSING"           — table doesn't exist
      "CORRUPT: <reason>" — query failed
    """
    conn = get_conn(db_path)
    try:
        result: dict[str, Any] = {}
        for table in SCHEMA_TABLES:
            if not _table_exists(conn, table):
                result[table] = "MISSING"
                continue
            try:
                row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                # Check for NULL primary keys (should be impossible but
                # verify anyway — surfaces data corruption early)
                pk = _primary_key_column(conn, table)
                if pk:
                    null_pk = conn.execute(
                        f"SELECT COUNT(*) AS cnt FROM {table} WHERE {pk} IS NULL"
                    ).fetchone()["cnt"]
                    if null_pk > 0:
                        result[table] = f"CORRUPT: {null_pk} NULL primary keys"
                        continue
                result[table] = {"rows": row["cnt"] if row else 0, "status": "OK"}
            except sqlite3.OperationalError as exc:
                result[table] = f"CORRUPT: {exc}"

        # Check that all expected indexes exist
        result["_indexes"] = _check_indexes(conn)

        return result
    finally:
        conn.close()


def status(db_path: Path | str | None = None) -> dict:
    """Show current state of entity-graph tables (alias for validate)."""
    return validate(db_path)


def rollback(db_path: Path | str | None = None) -> dict:
    """Drop the 6 entity-graph tables. Reversible: re-run migrate().

    Drops in reverse-dependency order (extraction_log first, entity_types
    last) to avoid FK constraint errors. The DB's foreign_keys=ON
    pragma is honored, so the order matters.

    Returns a list of dropped table names.
    """
    conn = get_conn(db_path)
    try:
        dropped: list[str] = []
        for table in SCHEMA_TABLES:  # already in reverse-dependency order
            if _table_exists(conn, table):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
                dropped.append(table)
        conn.commit()
        logger.info("Dropped entity-graph tables: %s", dropped)
        return {"dropped": dropped}
    finally:
        conn.close()


# ----- Private helpers -------------------------------------------------------

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _primary_key_column(conn: sqlite3.Connection, table: str) -> str | None:
    """Return the name of the table's PRIMARY KEY column, or None."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for r in rows:
        if r["pk"] > 0:
            return r["name"]
    return None


# Indexes we expect to find after a successful migrate().
# Defined here as a single source of truth for _check_indexes().
_EXPECTED_INDEXES: dict[str, list[str]] = {
    "entity_types": ["idx_entity_types_parent"],
    "entities": [
        "idx_entities_type",
        "idx_entities_name",
        "idx_entities_status",
        "idx_entities_last_accessed",
    ],
    "relationship_types": ["idx_relationship_types_family"],
    "relationships": [
        "idx_relationships_source",
        "idx_relationships_target",
        "idx_relationships_type",
        "idx_relationships_valid_to",
        "idx_relationships_provenance",
    ],
    "entity_facts": ["idx_entity_facts_entity", "idx_entity_facts_entity_key"],
    "extraction_log": [
        "idx_extraction_log_entity",
        "idx_extraction_log_relationship",
        "idx_extraction_log_method",
        "idx_extraction_log_session",
    ],
}


def _check_indexes(conn: sqlite3.Connection) -> dict:
    """Return a per-table dict of {expected: 'present' | 'MISSING'}.

    Verifies the design-spec indexes (see _check_indexes docstring)
    are all present after migrate().
    """
    result: dict[str, dict[str, str]] = {}
    for table, expected in _EXPECTED_INDEXES.items():
        if not _table_exists(conn, table):
            result[table] = {ix: "TABLE_MISSING" for ix in expected}
            continue
        rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
        present = {r["name"] for r in rows}
        result[table] = {ix: ("present" if ix in present else "MISSING") for ix in expected}
    return result


# ----- CLI -------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Ichor entities — schema (ER-P0)",
    )
    parser.add_argument("--migrate", action="store_true", help="Create tables + indexes")
    parser.add_argument("--validate", action="store_true", help="Verify tables exist")
    parser.add_argument("--rollback", action="store_true", help="Drop entity tables")
    parser.add_argument("--status", action="store_true", help="Show counts per table")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Override DB path (for tests). Default: ~/.hermes/ichor.db",
    )
    args = parser.parse_args()

    if args.migrate:
        print(json.dumps(migrate(args.db_path), indent=2))
    elif args.rollback:
        print(json.dumps(rollback(args.db_path), indent=2))
    elif args.validate or args.status:
        print(json.dumps(validate(args.db_path), indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
