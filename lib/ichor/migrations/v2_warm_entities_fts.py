"""
Ichor V2 schema migration — warm_entities full-text index (2026-09-20).

## Why

`warm_entities` is the "single source of truth per (category, name)" table
(Rule 43) and the per-turn provider's docstrings have claimed since the ChromaDB
removal that semantic search was "replaced by FTS5 + WARM entity lookup" — but
that lookup was never written (`_query_chroma` still returns `[]`, and
`warm_entities` is referenced nowhere in the provider). The table therefore has
**no retrieval path at all**, and no index to build one on: 188,762 rows with
only `idx_warm_category` and `idx_warm_importance`.

A `LIKE '%term%'` scan over 188k rows is exactly the fault the keyword lanes were
fixed for (~2.5 s per query, measured on `ichor_events`). This migration adds the
indexed path: an FTS5 table over `(name, value, brief, outline, category)`,
external-content against `warm_entities` so nothing is duplicated, kept in sync
by triggers, rebuilt once so existing rows are searchable immediately.

## Content quality (why the lookup also gates)

97.4% of rows (183,921) carry a `value` that is just the category echoed in front
of a raw text fragment — `blocker crash`, `commitment TODO`, `fact db is`,
`follow_up v2`. That is the naive extractor's signature, not knowledge. Only
3,981 rows (2.1%) are entity-shaped (name starts alphanumeric, 3-60 chars, no
JSON/markdown punctuation, <=5 words, real brief/outline text), and those are the
curated ones: `OAuth — An authentication protocol…`, `ChromaDB — A vector
database that is not coming back…`.

So the index covers every row, and `WarmEntitiesBackend` applies the quality gate
at query time. Gating in the query keeps the decision auditable and reversible —
indexing a filtered subset would silently hide rows from every future consumer.

## Usage

    from lib.ichor.migrations.v2_warm_entities_fts import run_migration, status
    run_migration()        # idempotent; every DDL is IF NOT EXISTS
    status()               # inspect without applying
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("/home/konan/.hermes/ichor.db")

DDL = """
-- FTS5 over warm_entities. External content (content='warm_entities') so the
-- index stores only the inverted index, never a second copy of the text; the
-- triggers keep it in sync with every INSERT/UPDATE/DELETE on the base table.
CREATE VIRTUAL TABLE IF NOT EXISTS warm_entities_fts USING fts5(
    name, value, brief, outline, category,
    content='warm_entities',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS warm_entities_fts_ai AFTER INSERT ON warm_entities BEGIN
    INSERT INTO warm_entities_fts(rowid, name, value, brief, outline, category)
    VALUES (new.id, new.name, new.value, coalesce(new.brief, ''), coalesce(new.outline, ''), new.category);
END;

CREATE TRIGGER IF NOT EXISTS warm_entities_fts_ad AFTER DELETE ON warm_entities BEGIN
    INSERT INTO warm_entities_fts(warm_entities_fts, rowid, name, value, brief, outline, category)
    VALUES ('delete', old.id, old.name, old.value, coalesce(old.brief, ''), coalesce(old.outline, ''), old.category);
END;

CREATE TRIGGER IF NOT EXISTS warm_entities_fts_au AFTER UPDATE ON warm_entities BEGIN
    INSERT INTO warm_entities_fts(warm_entities_fts, rowid, name, value, brief, outline, category)
    VALUES ('delete', old.id, old.name, old.value, coalesce(old.brief, ''), coalesce(old.outline, ''), old.category);
    INSERT INTO warm_entities_fts(rowid, name, value, brief, outline, category)
    VALUES (new.id, new.name, new.value, coalesce(new.brief, ''), coalesce(new.outline, ''), new.category);
END;
"""


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='warm_entities_fts'"
    ).fetchone()
    return bool(row)


def _indexed_count(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute("SELECT count(*) FROM warm_entities_fts").fetchone()[0])
    except sqlite3.Error:
        return 0


def run_migration(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Create the warm_entities FTS index + triggers, then rebuild it once.

    Idempotent: the DDL is `IF NOT EXISTS` and the rebuild is a full reindex from
    the content table, so re-running is safe and always leaves the index
    consistent with `warm_entities`.
    """
    conn = _connect(db_path)
    try:
        base_rows = int(conn.execute("SELECT count(*) FROM warm_entities").fetchone()[0])
        conn.executescript(DDL)
        conn.execute("INSERT INTO warm_entities_fts(warm_entities_fts) VALUES('rebuild')")
        conn.commit()
        indexed = _indexed_count(conn)
        return {
            "db": str(db_path),
            "warm_entities_rows": base_rows,
            "fts_rows": indexed,
            "created": True,
            "in_sync": indexed == base_rows,
        }
    finally:
        conn.close()


def status(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Report index presence and row counts without changing anything."""
    conn = _connect(db_path)
    try:
        base_rows = int(conn.execute("SELECT count(*) FROM warm_entities").fetchone()[0])
        present = _has_fts(conn)
        indexed = _indexed_count(conn) if present else 0
        triggers = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' "
                "AND name LIKE 'warm_entities_fts_%' ORDER BY name"
            )
        ]
        return {
            "db": str(db_path),
            "fts_present": present,
            "warm_entities_rows": base_rows,
            "fts_rows": indexed,
            "triggers": triggers,
            "in_sync": present and indexed == base_rows,
        }
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    """`--status` inspects; an optional positional path overrides the DB.

    Flags are filtered out before positional parsing: `argv[0]` used to be taken
    as the DB path, so `--status` opened a database literally named "--status".
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    flags = {a for a in argv if a.startswith("-")}
    positional = [a for a in argv if not a.startswith("-")]
    db = Path(positional[0]) if positional else DEFAULT_DB_PATH
    if "--status" in flags:
        print(json.dumps(status(db), indent=2))
        return 0
    print(json.dumps(run_migration(db), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
