"""Relationship type seed registry.

Defines the canonical relationship types that should exist in the
`relationship_types` table, with idempotent insert logic. New types can
be added to `CANONICAL_TYPES` and the migration will create them on the
next `migrate()` call.

## Why a separate module?

The L2 extractor (`l2_llm.py`) uses `_ensure_relationship_type()` to
insert types that the LLM discovers on the fly. This module ensures the
**canonical** types are always present, even before any LLM extraction
has run — so a fresh DB has the right types and the federation-stats
daemon can join against them.

## Adding a new canonical type

1. Add the type dict to `CANONICAL_TYPES` below.
2. Bump `_SCHEMA_VERSION` (optional — only needed if a backfill depends
   on the new type).
3. The next `migrate()` call will insert it.

## Idempotency

`seed_relationship_types()` is safe to call multiple times. Existing
types are left untouched; only missing ones are inserted.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


# Canonical relationship types. Order matters for stable test assertions.
# Each entry: {id, description, family, is_temporal, is_directional}.
#
# - is_temporal: does this relationship have valid time bounds? (most do)
# - is_directional: false for symmetric (similar_to, related_to).
# - family: loose grouping for analytics ("learning" / "lifecycle" / etc.)
CANONICAL_TYPES: list[dict[str, Any]] = [
    {
        "id": "related_to",
        "description": "Generic symmetric association between two entities",
        "family": "reference",
        "is_temporal": True,
        "is_directional": False,
    },
    {
        "id": "learned_from",
        "description": "Source entity (skill/pattern/learning) was derived from or informed by target entity (event/source/skill)",
        "family": "learning",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "superseded_by",
        "description": "Source entity (skill/decision) was replaced or invalidated by target entity",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "derived_from",
        "description": "Source was derived from target (e.g., a skill derived from a pattern)",
        "family": "learning",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "replaces",
        "description": "Source replaced target (similar to superseded_by but for non-deprecated replacements)",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
]


def seed_relationship_types(
    conn: sqlite3.Connection,
    types: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Ensure each canonical relationship_type row exists. Idempotent.

    Returns a status dict: {"inserted": N, "already_present": M}.
    """
    if types is None:
        types = CANONICAL_TYPES

    inserted = 0
    already = 0
    for rt in types:
        rid = rt["id"]
        existing = conn.execute(
            "SELECT 1 FROM relationship_types WHERE id = ?", (rid,)
        ).fetchone()
        if existing:
            already += 1
            continue
        conn.execute(
            """INSERT INTO relationship_types
               (id, description, source_type, target_type,
                is_temporal, is_directional, family, created_at)
               VALUES (?, ?, NULL, NULL, ?, ?, ?, datetime('now'))""",
            (
                rid,
                rt.get("description", ""),
                1 if rt.get("is_temporal", True) else 0,
                1 if rt.get("is_directional", True) else 0,
                rt.get("family"),
            ),
        )
        inserted += 1
        logger.info("inserted canonical relationship_type: %s", rid)
    return {"inserted": inserted, "already_present": already}


def seed_all(db_path_or_conn) -> dict[str, int]:
    """Convenience wrapper: open conn from path, seed, close.

    Accepts a Path/str (open + close) OR an open sqlite3.Connection
    (caller manages lifecycle).
    """
    owns_conn = not hasattr(db_path_or_conn, "execute")
    if owns_conn:
        conn = sqlite3.connect(str(db_path_or_conn))
    else:
        conn = db_path_or_conn
    try:
        result = seed_relationship_types(conn)
        conn.commit()
        return result
    finally:
        if owns_conn:
            conn.close()
