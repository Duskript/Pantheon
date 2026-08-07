"""Deterministic candidate planning for Person Roots auto-ingestion.

This is the first deterministic autopopulation layer for Person Roots: it
accepts structured candidate facts (from future Discord/Hermes/Ichor scanners —
no LLM extraction here), resolves candidate names through the existing alias
resolver, pauses for clarification on unknown/common/similar names, and
classifies every known-person fact through the existing source-authority
proposal rules (``lib.person_roots.proposals``).

This module is side-effect free by design: it never writes files, never creates
person roots, never links accounts, and never canonizes anything by itself. It
returns a serializable plan; the guarded writer in
``lib.person_roots.apply`` decides what may actually be applied.

Planning rules (mirroring the fusion spec contract):

1. Use ``build_name_clarification(candidate_name, observed_context, root)``
   first.
2. If ``should_pause`` is true, put the item in ``clarifications``; do not
   propose/apply it.
3. If known, use the resolved ``person_id`` and ``propose_update(...)``.
4. ``allow`` -> ``applies``.
5. ``needs_owner_approval`` -> ``approvals``.
6. ``deny`` -> ``denied``.
7. Preserve ``provenance`` in every emitted item.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib.person_roots.clarification import build_name_clarification
from lib.person_roots.proposals import propose_update
from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository
from lib.person_roots.schema import ALLOW, DENY, NEEDS_OWNER_APPROVAL

_REQUIRED_FIELDS = (
    'candidate_name',
    'field',
    'value',
    'source_person_id',
    'source_type',
)


@dataclass(frozen=True)
class CandidateFact:
    """A structured, already-extracted candidate fact about a person name.

    Scanners (Discord/Hermes/Ichor) emit these; nothing here performs LLM
    extraction. ``candidate_name`` may be a person ID, display name, or alias;
    it is resolved through the existing Person Roots alias resolver.
    """

    candidate_name: str
    field: str
    value: Any
    source_person_id: str | None
    source_type: str
    sensitivity: str = 'private'
    observed_context: str = ''
    provenance: dict[str, Any] = dataclasses.field(default_factory=dict)


def candidate_from_mapping(data: Mapping[str, Any]) -> CandidateFact:
    """Parse/validate a dict into CandidateFact.

    Raises ValueError for missing required fields (``candidate_name``,
    ``field``, ``value``, ``source_person_id``, ``source_type``) or for blank
    required string fields. Optional fields default to ``sensitivity='private'``,
    ``observed_context=''`` and ``provenance={}``.
    """

    for key in _REQUIRED_FIELDS:
        if key not in data:
            raise ValueError(f"Missing required field: {key!r}")

    candidate_name = str(data['candidate_name']).strip()
    if not candidate_name:
        raise ValueError('candidate_name must be a non-empty string')

    field_name = str(data['field']).strip()
    if not field_name:
        raise ValueError('field must be a non-empty string')

    source_type = str(data['source_type']).strip()
    if not source_type:
        raise ValueError('source_type must be a non-empty string')

    provenance = data.get('provenance')
    if provenance is None:
        provenance = {}
    elif not isinstance(provenance, Mapping):
        raise ValueError('provenance must be a mapping')

    source_person_id = data['source_person_id']
    if source_person_id is not None:
        source_person_id = str(source_person_id)

    return CandidateFact(
        candidate_name=candidate_name,
        field=field_name,
        value=data['value'],
        source_person_id=source_person_id,
        source_type=source_type,
        sensitivity=str(data.get('sensitivity', 'private')),
        observed_context=str(data.get('observed_context', '')),
        provenance=dict(provenance),
    )


def build_ingest_plan(
    candidates: Iterable[CandidateFact | Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Return a serializable plan without mutating files.

    Emitted buckets: ``applies``, ``clarifications``, ``approvals``, ``denied``
    plus a ``summary`` of counts. Every emitted item preserves the candidate's
    ``provenance``.
    """

    repo = PersonRootsRepository(root)
    applies: list[dict[str, Any]] = []
    clarifications: list[dict[str, Any]] = []
    approvals: list[dict[str, Any]] = []
    denied: list[dict[str, Any]] = []

    for candidate in candidates:
        fact = candidate if isinstance(candidate, CandidateFact) else candidate_from_mapping(candidate)

        clarification = build_name_clarification(fact.candidate_name, fact.observed_context, root)
        if clarification['should_pause']:
            clarifications.append({
                'candidate_name': fact.candidate_name,
                'clarify_args': clarification['clarify_args'],
                'reason': clarification['reason'],
                'provenance': dict(fact.provenance),
            })
            continue

        person_id = clarification['classification']['person_id']
        if person_id is None:
            # Defensive: only reachable for a directly-constructed CandidateFact
            # with an empty/ignorable name; never propose without a target.
            clarifications.append({
                'candidate_name': fact.candidate_name,
                'clarify_args': None,
                'reason': clarification['reason'],
                'provenance': dict(fact.provenance),
            })
            continue

        proposal = propose_update(
            person_id,
            fact.field,
            fact.value,
            fact.source_person_id,
            fact.source_type,
            fact.sensitivity,
        )
        item = {
            'person_id': person_id,
            'display_name': repo.load_person(person_id).display_name,
            'field': fact.field,
            'value': fact.value,
            'source_person_id': fact.source_person_id,
            'source_type': fact.source_type,
            'sensitivity': fact.sensitivity,
            'decision': proposal.decision,
            'reason': proposal.reason,
            'provenance': dict(fact.provenance),
        }
        if proposal.decision == ALLOW:
            applies.append(item)
        elif proposal.decision == NEEDS_OWNER_APPROVAL:
            approvals.append(item)
        else:
            denied.append(item)

    return {
        'applies': applies,
        'clarifications': clarifications,
        'approvals': approvals,
        'denied': denied,
        'summary': {
            'total': len(applies) + len(clarifications) + len(approvals) + len(denied),
            'apply': len(applies),
            'clarify': len(clarifications),
            'approval': len(approvals),
            'deny': len(denied),
        },
    }
