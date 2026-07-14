"""Entity type seed registry.

Defines the canonical entity types that should exist in the
`entity_types` table, with idempotent insert logic. New types can
be added to `CANONICAL_TYPES` and the migration will create them on
the next `migrate()` call.

## Adding a new canonical type

1. Add the type dict to `CANONICAL_TYPES` below.
2. The next `migrate()` call will insert it.

## Idempotency

`seed_entity_types()` is safe to call multiple times. Existing
types are left untouched; only missing ones are inserted.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


# Canonical entity types. Order matters for stable test assertions.
# Each entry: {id, description, parent_type, extractable, icon}.
#
# - parent_type: optional hierarchy — 'lead' inherits from 'organization'
# - extractable: should L0/L1 regex try to extract this type?
# - icon: emoji for display
#
# Follows the taxonomy from ichor-entity-model-design.md §Base Entity Types,
# prioritized for TheoForge's operational needs (person, org, project, pricing,
# decisions, lyrics).
CANONICAL_TYPES: list[dict[str, Any]] = [
    # ── Core (universal) ──────────────────────────────────────────────
    {
        "id": "person",
        "description": "Natural person — client, prospect, partner, team member, contact",
        "parent_type": None,
        "extractable": True,
        "icon": "👤",
    },
    {
        "id": "organization",
        "description": "Company, institution, firm, agency, or group",
        "parent_type": None,
        "extractable": True,
        "icon": "🏢",
    },
    {
        "id": "concept",
        "description": "Abstract idea, topic, theme, pattern, or architectural concept",
        "parent_type": None,
        "extractable": True,
        "icon": "💡",
    },
    {
        "id": "artifact",
        "description": "Document, code, design, spec, or any created work",
        "parent_type": None,
        "extractable": True,
        "icon": "📄",
    },

    # ── Business (TheoForge operations) ──────────────────────────────
    {
        "id": "project",
        "description": "Goal-directed endeavor with timeline — client engagement or internal build",
        "parent_type": None,
        "extractable": True,
        "icon": "📋",
    },
    {
        "id": "product_idea",
        "description": "Product concept, feature idea, or strategic product direction",
        "parent_type": None,
        "extractable": True,
        "icon": "✨",
    },
    {
        "id": "decision",
        "description": "Recorded decision with rationale — business or architectural",
        "parent_type": None,
        "extractable": True,
        "icon": "🎯",
    },
    {
        "id": "pricing_vertical",
        "description": "Rate card, pricing model, package, or pricing vertical",
        "parent_type": None,
        "extractable": True,
        "icon": "💰",
    },
    {
        "id": "interaction",
        "description": "Meeting, call, conversation, or any significant exchange",
        "parent_type": None,
        "extractable": True,
        "icon": "💬",
    },
    {
        "id": "contract",
        "description": "SOW, proposal, service agreement, or legal document",
        "parent_type": None,
        "extractable": True,
        "icon": "📝",
    },

    # ── Creative (Codex-SKC) ──────────────────────────────────────────
    {
        "id": "lyrics",
        "description": "Song lyrics, poetry, or creative text",
        "parent_type": None,
        "extractable": True,
        "icon": "🎵",
    },

    # ── Pantheon-specific ────────────────────────────────────────────
    {
        "id": "god",
        "description": "Registered Pantheon deity (Hermes, Thoth, Marvin, etc.)",
        "parent_type": None,
        "extractable": True,
        "icon": "⚡",
    },
    {
        "id": "session",
        "description": "Conversation between user and a Pantheon god",
        "parent_type": None,
        "extractable": False,
        "icon": "📜",
    },
    {
        "id": "goal",
        "description": "Strategic objective or directional target",
        "parent_type": None,
        "extractable": True,
        "icon": "🎯",
    },
    {
        "id": "commitment",
        "description": "Promised action or deliverable",
        "parent_type": None,
        "extractable": True,
        "icon": "🤝",
    },
]


def seed_entity_types(
    conn: sqlite3.Connection,
    types: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Ensure each canonical entity_type row exists. Idempotent.

    Returns a status dict: {"inserted": N, "already_present": M}.
    """
    if types is None:
        types = CANONICAL_TYPES

    inserted = 0
    already = 0
    for et in types:
        eid = et["id"]
        existing = conn.execute(
            "SELECT 1 FROM entity_types WHERE id = ?", (eid,)
        ).fetchone()
        if existing:
            already += 1
            continue

        conn.execute(
            """INSERT INTO entity_types (id, description, parent_type, extractable, icon)
               VALUES (?, ?, ?, ?, ?)""",
            (
                eid,
                et["description"],
                et.get("parent_type"),
                et.get("extractable", True),
                et.get("icon", "📄"),
            ),
        )
        inserted += 1

    conn.commit()
    logger.info("entity_types seeded: %d inserted, %d already present", inserted, already)
    return {"inserted": inserted, "already_present": already}
