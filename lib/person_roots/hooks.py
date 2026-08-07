"""Safe integration hook points for future Person Roots runtime wiring.

This module is Wave 6 alpha. It does not register hooks with Hermes, Discord,
Conductor, or any god profile. Instead, it exposes a serializable helper that a
future runtime integration can call after it has already identified the
requester, target name, purpose, fact type, and actor god.

The helper performs the required privacy sequence:

1. Resolve the requested target name/alias through ``PersonRootsRepository``.
2. Refuse unknown targets without guessing.
3. Load the target ``PersonRecord``.
4. Evaluate access through the ACL module.
5. Return only an allow/deny/approval decision plus file paths when allowed.

No file mutation, no account linking, and no background work happens here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.person_roots.acl import evaluate_access
from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository
from lib.person_roots.schema import DENY, AccessDecision, AccessRequest

_DEFAULT_ALLOWED_FILES = {
    'profile': ('PROFILE.md',),
    'basic_identity_context_if_owner_authorized': ('PROFILE.md',),
    'relationship_to_owner': ('RELATIONSHIP_TO_OWNER.md',),
    'private_family_context_if_explicitly_allowed': ('RELATIONSHIP_TO_OWNER.md', 'NOTES.md'),
    'permissions': ('PERMISSIONS.md',),
    'memory_policy': ('MEMORY_POLICY.md',),
    'own_profile': ('PROFILE.md', 'ROOT.md', 'PREFERENCES.md'),
    'her_own_profile': ('PROFILE.md', 'ROOT.md', 'PREFERENCES.md'),
    'her_own_pantheon_usage': ('ROOT.md', 'PREFERENCES.md'),
    'submitted_code': ('ROOT.md', 'PROJECTS/code-review.md'),
    'project_history': ('PROJECTS/code-review.md',),
    'general_programming_guidance': ('PROJECTS/code-review.md',),
    'mentor_review_mode': ('PROJECTS/code-review.md',),
}


def build_context_decision(
    requesting_person_id: str | None,
    target_name: str,
    requested_context_domain: str,
    requested_fact_type: str,
    purpose: str,
    source_platform: str | None = None,
    channel_id: str | None = None,
    actor_god: str | None = None,
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Build a serializable context decision for a future god/runtime hook."""

    repo = PersonRootsRepository(root)
    target_person_id = repo.resolve_name(target_name)
    if target_person_id is None:
        return _serialize(
            target_person_id=None,
            target_display_name=None,
            decision=AccessDecision(DENY, f"Unknown person target: {target_name}"),
        )

    target = repo.load_person(target_person_id)
    request = AccessRequest(
        requesting_person_id=requesting_person_id,
        target_person_id=target_person_id,
        requested_context_domain=requested_context_domain,
        requested_fact_type=requested_fact_type,
        purpose=purpose,
        source_platform=source_platform,
        channel_id=channel_id,
        actor_god=actor_god,
    )
    decision = evaluate_access(request, target)
    allowed_files = _allowed_files(repo, target_person_id, requested_context_domain, decision)
    return _serialize(target_person_id, target.display_name, decision, allowed_files)


def _allowed_files(
    repo: PersonRootsRepository,
    person_id: str,
    domain: str,
    decision: AccessDecision,
) -> tuple[str, ...]:
    if decision.decision != 'allow':
        return ()
    relative_files = _DEFAULT_ALLOWED_FILES.get(domain, ('PROFILE.md',))
    paths = []
    for relative in relative_files:
        path = repo.path_for(person_id, relative)
        if path.exists():
            paths.append(str(path))
    return tuple(paths)


def _serialize(
    target_person_id: str | None,
    target_display_name: str | None,
    decision: AccessDecision,
    allowed_files: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        'target_person_id': target_person_id,
        'target_display_name': target_display_name,
        'decision': decision.decision,
        'reason': decision.reason,
        'allowed_files': allowed_files,
        'redacted_domains': decision.redacted_domains,
        'log_required': decision.log_required,
    }
