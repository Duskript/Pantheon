"""Schema constants and dataclasses for Pantheon Person Roots.

The Person Roots layer models people as permissioned identity roots. This module
contains only immutable constants and dataclasses so the rest of the library has
one vocabulary for decision values, sensitivities, trust tiers, and source types.
The values mirror the spec pack under:

- plans/person-roots/PERSON_ROOTS_SCHEMA.md
- plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md

No code in this module performs I/O. That keeps imports safe for tests, future
god runtime hooks, and dashboard/admin surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

ALLOW = "allow"
DENY = "deny"
NEEDS_OWNER_APPROVAL = "needs_owner_approval"

DECISIONS = frozenset({ALLOW, DENY, NEEDS_OWNER_APPROVAL})
DOCUMENT_TYPES = frozenset({
    "index",
    "profile",
    "relationship_to_owner",
    "aliases",
    "permissions",
    "memory_policy",
    "interaction_log",
    "notes",
    "root",
    "preferences",
    "relationship",
    "project",
})
SENSITIVITIES = frozenset({"public", "basic", "private", "sensitive", "secret"})
TRUST_TIERS = frozenset({
    "tier_0_unknown",
    "tier_1_recognized",
    "tier_2_collaborator",
    "tier_3_family_close",
    "tier_4_owner_admin",
})
SOURCE_TYPES = frozenset({
    "owner_account",
    "direct_user_account",
    "trusted_contact_account",
    "god_subagent",
    "public_web_social",
})

PRIVATE_FACT_TYPES = frozenset({"private", "sensitive", "secret"})
PUBLIC_FACT_TYPES = frozenset({"public", "basic"})


@dataclass(frozen=True)
class PersonRecord:
    """Loaded person-root summary used by resolver and ACL code.

    ``profile_frontmatter`` and ``permissions_frontmatter`` preserve raw file
    metadata for later integrations, while ``allowed_context`` and
    ``denied_context`` expose the immediate policy lists used by the ACL.
    """

    person_id: str
    display_name: str
    aliases: tuple[str, ...] = ()
    direct_user: bool = False
    trust_tier: str = "tier_1_recognized"
    folder: Path = Path()
    notes: str = ""
    profile_frontmatter: dict[str, Any] = field(default_factory=dict)
    permissions_frontmatter: dict[str, Any] = field(default_factory=dict)
    allowed_context: tuple[str, ...] = ()
    denied_context: tuple[str, ...] = ()


@dataclass(frozen=True)
class AccessRequest:
    """Request facts used by the ACL evaluator."""

    requesting_person_id: Optional[str]
    target_person_id: str
    requested_context_domain: str
    requested_fact_type: str
    purpose: str
    source_platform: Optional[str] = None
    channel_id: Optional[str] = None
    actor_god: Optional[str] = None


@dataclass(frozen=True)
class AccessDecision:
    """ACL result for a person-root retrieval attempt."""

    decision: str
    reason: str
    allowed_files: tuple[str, ...] = ()
    redacted_domains: tuple[str, ...] = ()
    log_required: bool = False


@dataclass(frozen=True)
class ProposedUpdate:
    """A non-mutating classification of a possible profile update."""

    person_id: str
    field: str
    value: Any
    source_person_id: Optional[str]
    source_type: str
    sensitivity: str
    decision: str
    reason: str
