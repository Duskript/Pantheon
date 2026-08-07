"""Access-control evaluator for Pantheon Person Roots.

Spec references:
- ``plans/person-roots/PERSON_ROOTS_PRIVACY_ACL.md``
- ``plans/person-roots/PERSON_ROOTS_BUILD_GATES.md``

This module implements the alpha Wave 3 ACL contract. It is intentionally
rule-based rather than LLM-inferred so privacy behavior is predictable and easy
to test. The evaluator receives a normalized ``AccessRequest`` plus the target
``PersonRecord`` and returns an ``AccessDecision``. It does not read files,
write files, call Discord, call Ichor, or mutate profile roots.

Important invariants:

1. Owner is owner-admin, but admin override logging can still be requested.
2. Unknown users receive public/basic help only.
3. Direct users can access their own explicitly allowed self context.
4. Owner-perspective relationship notes are not shared with non-Owner accounts.
5. Denied domains beat actor-god presence; handoffs cannot broaden access.
6. Public-brand use of sensitive family/person context requires owner approval.
"""

from __future__ import annotations

from lib.person_roots.schema import (
    ALLOW,
    DENY,
    NEEDS_OWNER_APPROVAL,
    PRIVATE_FACT_TYPES,
    PUBLIC_FACT_TYPES,
    AccessDecision,
    AccessRequest,
    PersonRecord,
)

_PUBLIC_BRAND_PURPOSES = {'public_brand', 'public_brand_post', 'public_content', 'social_post'}
_PUBLIC_BRAND_GODS = {'kairos', 'rheta', 'iris'}
_OWNER_PRIVATE_DOMAINS = {'relationship_to_owner', 'owner_private_relationship_notes'}
_SELF_PROFILE_DOMAINS = {'own_profile', 'her_own_profile', 'self_profile', 'preferences', 'her_own_pantheon_usage'}


def evaluate_access(request: AccessRequest, target: PersonRecord) -> AccessDecision:
    """Return an allow/deny/approval decision for person-root context access."""

    requester = (request.requesting_person_id or '').casefold()
    domain = request.requested_context_domain
    fact_type = request.requested_fact_type
    purpose = request.purpose
    actor_god = (request.actor_god or '').casefold()

    if requester in {'owner', 'sample-owner'}:
        return AccessDecision(
            ALLOW,
            'Owner-admin access is allowed.',
            log_required=domain == 'admin_override',
        )

    if _public_brand_sensitive_use(purpose, actor_god, fact_type):
        return AccessDecision(
            NEEDS_OWNER_APPROVAL,
            'Public-brand use of sensitive person/family context requires owner approval.',
            redacted_domains=(domain,),
            log_required=True,
        )

    if not requester:
        if fact_type in PUBLIC_FACT_TYPES:
            return AccessDecision(ALLOW, 'Unknown requester may access public/basic context only.')
        return AccessDecision(
            DENY,
            'Unknown requester cannot access private person-root context.',
            redacted_domains=(domain,),
        )

    if domain in target.denied_context:
        return AccessDecision(
            DENY,
            f"Domain '{domain}' is explicitly denied for {target.person_id}.",
            redacted_domains=(domain,),
        )

    if domain in _OWNER_PRIVATE_DOMAINS and requester not in {'owner', 'sample-owner'}:
        return AccessDecision(
            DENY,
            'Owner-perspective private relationship notes are not shared by default.',
            redacted_domains=(domain,),
        )

    if requester == target.person_id and target.direct_user:
        if domain in target.allowed_context:
            return AccessDecision(
                ALLOW,
                f"{target.person_id} may access explicitly allowed self context '{domain}'.",
            )
        if domain in _SELF_PROFILE_DOMAINS and fact_type in {'basic', 'private'}:
            return AccessDecision(ALLOW, 'Direct user may access own profile/basic private context.')

    if domain in target.allowed_context and fact_type in PUBLIC_FACT_TYPES:
        return AccessDecision(ALLOW, f"Domain '{domain}' is public/basic and allowed for target policy.")

    if fact_type in PRIVATE_FACT_TYPES:
        return AccessDecision(
            NEEDS_OWNER_APPROVAL,
            'Private/sensitive cross-person context requires owner approval.',
            redacted_domains=(domain,),
            log_required=True,
        )

    return AccessDecision(DENY, 'No ACL rule allowed this person-root context.', redacted_domains=(domain,))


def _public_brand_sensitive_use(purpose: str, actor_god: str, fact_type: str) -> bool:
    return (purpose in _PUBLIC_BRAND_PURPOSES or actor_god in _PUBLIC_BRAND_GODS) and fact_type in PRIVATE_FACT_TYPES
