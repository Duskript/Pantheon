"""Pantheon Person Roots library package.

This package is the Wave 3-7 implementation surface for the Person Roots plan:

- Wave 3: access-control decisions for person-root retrieval.
- Wave 4: resolver/account parsing for relationship folders.
- Wave 5: proposal classification for safe profile updates.
- Wave 6: deterministic ingest planning + guarded apply writer.
- Wave 7: explicit-marker observer, pending queue, and operator resolver.

The package is intentionally side-effect free. Importing it must not write files,
load Discord, touch Ichor, edit Hermes configuration, or mutate Athenaeum roots.
Live god integration is a later wave; this library only exposes primitives that
future runtime hooks can call after they have identified the requester, target,
purpose, and context domain.
"""

from lib.person_roots.schema import (
    ALLOW,
    DENY,
    NEEDS_OWNER_APPROVAL,
    AccessDecision,
    AccessRequest,
    PersonRecord,
    ProposedUpdate,
)
from lib.person_roots.ingest import (
    CandidateFact,
    build_ingest_plan,
    candidate_from_mapping,
)
from lib.person_roots.account_verification import (
    AccountVerificationPlan,
    apply_account_verification_plan,
    build_account_verification_plan,
    verify_account_link,
)
from lib.person_roots.apply import apply_ingest_plan, ingest_and_apply
from lib.person_roots.live_chat import (
    handle_live_chat_candidates,
    load_candidate_stream,
    render_live_chat_result,
)
from lib.person_roots.observer import extract_candidates_from_text, observe_source_files
from lib.person_roots.pending import append_pending_items, pending_path, read_pending_items
from lib.person_roots.pending_resolver import list_pending, resolve_pending_records
from lib.person_roots.runtime import active_ingest_step, unattended_ingest_files

__all__ = [
    "ALLOW",
    "DENY",
    "NEEDS_OWNER_APPROVAL",
    "AccessDecision",
    "AccessRequest",
    "PersonRecord",
    "ProposedUpdate",
    "CandidateFact",
    "build_ingest_plan",
    "candidate_from_mapping",
    "apply_ingest_plan",
    "ingest_and_apply",
    "active_ingest_step",
    "unattended_ingest_files",
    "append_pending_items",
    "pending_path",
    "read_pending_items",
    "list_pending",
    "resolve_pending_records",
    "extract_candidates_from_text",
    "observe_source_files",
    "AccountVerificationPlan",
    "build_account_verification_plan",
    "apply_account_verification_plan",
    "verify_account_link",
    "handle_live_chat_candidates",
    "load_candidate_stream",
    "render_live_chat_result",
]
