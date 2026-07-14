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
2. The next `migrate()` call will insert it.

## Idempotency

`seed_relationship_types()` is safe to call multiple times. Existing
types are left untouched; only missing ones are inserted.

## Full Taxonomy

Seeded from ichor-entity-model-design.md §Relationship Type Taxonomy
(~60 types across 10 families), plus TheoForge-specific additions for
the meeting-brief / GBrain use case (2026-06-12).
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
# - family: loose grouping for analytics ("affiliation" / "reference" / etc.)
#
# Organized by family per the design document.
CANONICAL_TYPES: list[dict[str, Any]] = [
    # ── 1. Affiliation (who connects to what) ────────────────────────
    {
        "id": "works_at",
        "description": "Person is employed by or works at an organization",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "founded",
        "description": "Person founded an organization",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "leads",
        "description": "Person leads an organization, group, or project",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "member_of",
        "description": "Person is a member of a group",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "reports_to",
        "description": "Person reports to another person (org chart)",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "partnered_with",
        "description": "Organization has a partnership with another organization",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": False,
    },
    {
        "id": "competes_with",
        "description": "Organization competes with another organization",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": False,
    },
    {
        "id": "acquired",
        "description": "Organization acquired another entity",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "clients",
        "description": "Organization serves another organization as a client",
        "family": "affiliation",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 2. Participation (who did what) ──────────────────────────────
    {
        "id": "attended",
        "description": "Person attended an event or meeting",
        "family": "participation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "organized",
        "description": "Person organized an event or meeting",
        "family": "participation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "participated_in",
        "description": "Person participated in a session, project, or meeting",
        "family": "participation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "contributes_to",
        "description": "Entity contributes to a project",
        "family": "participation",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "assigned_to",
        "description": "Task or action item is assigned to a person",
        "family": "participation",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 3. Authorship & Creation (who made what) ─────────────────────
    {
        "id": "authored",
        "description": "Person authored an artifact, document, decision, or creative work",
        "family": "authorship",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "created",
        "description": "Person created an artifact, project, or product",
        "family": "authorship",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "implements",
        "description": "Artifact implements a concept or decision",
        "family": "authorship",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 4. Reference & Citation (what points to what) ───────────────
    {
        "id": "cites",
        "description": "Artifact cites another artifact (academic or technical reference)",
        "family": "reference",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "references",
        "description": "Artifact references a concept or external source",
        "family": "reference",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "discusses",
        "description": "An artifact, session, or interaction discusses a concept",
        "family": "reference",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "mentions",
        "description": "An artifact or interaction mentions an entity",
        "family": "reference",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "related_to",
        "description": "Generic symmetric association between two entities",
        "family": "reference",
        "is_temporal": True,
        "is_directional": False,
    },

    # ── 5. Temporal & Lifecycle (what happened when) ─────────────────
    {
        "id": "superseded_by",
        "description": "Source entity was replaced or invalidated by target entity",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "deprecated_by",
        "description": "Source entity was deprecated by target entity",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "replaces",
        "description": "Source replaces target (non-deprecating replacement)",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "precedes",
        "description": "Source precedes target in time or sequence",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "follows",
        "description": "Source follows target in time or sequence (inverse of precedes)",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "contradicts",
        "description": "One entity contradicts another in fact or implication",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": False,
    },
    {
        "id": "depends_on",
        "description": "Entity depends on another (task, project, or system dependency)",
        "family": "lifecycle",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 6. Categorization (what belongs where) ──────────────────────
    {
        "id": "type_of",
        "description": "Entity is a type of a concept (is-a hierarchy)",
        "family": "categorization",
        "is_temporal": False,
        "is_directional": True,
    },
    {
        "id": "part_of",
        "description": "Entity is part of another entity (part-whole)",
        "family": "categorization",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "contains",
        "description": "Entity contains another entity (inverse of part_of)",
        "family": "categorization",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "instance_of",
        "description": "Entity is a concrete instance of a concept",
        "family": "categorization",
        "is_temporal": False,
        "is_directional": True,
    },
    {
        "id": "tagged_with",
        "description": "Entity is tagged or labeled with a concept",
        "family": "categorization",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 7. Communication (what was said where) ──────────────────────
    {
        "id": "discussed_in",
        "description": "A concept, project, or decision was discussed in a session or meeting",
        "family": "communication",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "sent_to",
        "description": "Message, proposal, or communication was sent to a person or entity",
        "family": "communication",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "replied_to",
        "description": "A message is a reply to another message",
        "family": "communication",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 8. Financial & Deal (business-specific) ─────────────────────
    {
        "id": "funded_by",
        "description": "Project or organization is funded by an entity",
        "family": "financial",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "budgeted_for",
        "description": "A dollar amount is budgeted for a project",
        "family": "financial",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "pricing_for",
        "description": "A pricing vertical or rate card applies to a project or product",
        "family": "financial",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "proposed_to",
        "description": "A pricing proposal or contract was sent to an organization or person",
        "family": "financial",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 9. Workflow & Process ───────────────────────────────────────
    {
        "id": "blocked_by",
        "description": "Task or project is blocked by a blocker or dependency",
        "family": "workflow",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "resolves",
        "description": "Action, decision, or PR resolves a blocker or issue",
        "family": "workflow",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "triggers",
        "description": "Event or condition triggers a workflow or action",
        "family": "workflow",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "produces",
        "description": "Workflow or process produces an artifact",
        "family": "workflow",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── 10. Decision & Strategy (TheoForge-specific) ─────────────────
    {
        "id": "decided_on",
        "description": "A decision was made about a project, product, or entity",
        "family": "strategy",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "involves",
        "description": "Project or work involves an organization, person, or system",
        "family": "strategy",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "enables",
        "description": "One entity enables or unlocks another",
        "family": "strategy",
        "is_temporal": True,
        "is_directional": True,
    },
    {
        "id": "requires",
        "description": "Entity requires another entity to function or proceed",
        "family": "strategy",
        "is_temporal": True,
        "is_directional": True,
    },

    # ── Learning (knowledge transfer) ───────────────────────────────
    {
        "id": "learned_from",
        "description": "Source skill/pattern/learning was derived from or informed by target entity",
        "family": "learning",
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
