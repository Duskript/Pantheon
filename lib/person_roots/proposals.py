"""Safe proposal classification for Person Roots updates.

This module does not write to profile files. It turns an observed possible fact
into a ``ProposedUpdate`` with one of three outcomes: allow, deny, or
needs_owner_approval. The rules intentionally favor approval/denial over silent
canon mutation so direct users, public sources, and gods cannot overwrite
Owner's private relationship view.
"""

from __future__ import annotations

from typing import Any, Optional

from lib.person_roots.schema import (
    ALLOW,
    DENY,
    NEEDS_OWNER_APPROVAL,
    SOURCE_TYPES,
    ProposedUpdate,
)

_LOW_RISK_SENSITIVITIES = {'public', 'basic', 'private'}
_HIGH_RISK_SENSITIVITIES = {'sensitive', 'secret'}
_RELATIONSHIP_FIELDS = ('relationship_to_owner', 'relationship.', 'relationships.')
_SELF_FIELDS = ('preferences.', 'profile.', 'projects.', 'root.')


def classify_source_authority(source_type: str) -> str:
    """Return a compact source-authority category for docs/tests."""

    if source_type == 'owner_account':
        return 'authoritative_owner'
    if source_type == 'direct_user_account':
        return 'authoritative_self_only'
    if source_type in {'trusted_contact_account', 'god_subagent'}:
        return 'suggestion_only'
    if source_type == 'public_web_social':
        return 'not_authoritative_private'
    return 'unknown'


def propose_update(
    person_id: str,
    field: str,
    value: Any,
    source_person_id: Optional[str],
    source_type: str,
    sensitivity: str = 'private',
) -> ProposedUpdate:
    """Classify a possible person-root update without mutating storage."""

    if source_type not in SOURCE_TYPES:
        return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, DENY, 'Unknown source type.')

    if source_type == 'public_web_social':
        if sensitivity in {'private', 'sensitive', 'secret'}:
            return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, DENY, 'Public web/social is never authoritative for private person facts.')
        return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, NEEDS_OWNER_APPROVAL, 'Public source requires review before canonization.')

    if source_type == 'owner_account':
        if sensitivity in _HIGH_RISK_SENSITIVITIES:
            return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, NEEDS_OWNER_APPROVAL, 'Sensitive cross-person facts require explicit approval even from Owner-authored capture.')
        return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, ALLOW, 'Owner-authored low-risk fact may update Owner canon.')

    if source_type == 'direct_user_account':
        if source_person_id == person_id and field.startswith(_SELF_FIELDS) and sensitivity in _LOW_RISK_SENSITIVITIES:
            return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, ALLOW, 'Direct user may update own low-risk self-profile/preferences.')
        if field.startswith(_RELATIONSHIP_FIELDS):
            return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, NEEDS_OWNER_APPROVAL, 'Direct user cannot overwrite Owner relationship canon.')
        return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, NEEDS_OWNER_APPROVAL, 'Direct user update requires review outside self-profile scope.')

    if source_type in {'trusted_contact_account', 'god_subagent'}:
        return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, NEEDS_OWNER_APPROVAL, 'Trusted contacts and gods may suggest only; Owner approval required.')

    return _proposal(person_id, field, value, source_person_id, source_type, sensitivity, DENY, 'Unhandled source authority.')


def _proposal(
    person_id: str,
    field: str,
    value: Any,
    source_person_id: Optional[str],
    source_type: str,
    sensitivity: str,
    decision: str,
    reason: str,
) -> ProposedUpdate:
    return ProposedUpdate(
        person_id=person_id,
        field=field,
        value=value,
        source_person_id=source_person_id,
        source_type=source_type,
        sensitivity=sensitivity,
        decision=decision,
        reason=reason,
    )
