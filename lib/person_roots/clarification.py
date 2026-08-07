"""Clarification helpers for Person Roots candidate names.

The ingestion layer should not build a growing approval backlog for ambiguous or
new person names. Instead, it can call these helpers and immediately pause the
agent with Hermes' clarify tool when a mention is not already a confirmed alias.

This module does not call tools directly and does not mutate person-root files.
It returns a serializable payload shaped for the agent/gateway layer to pass to
``clarify(question=..., choices=..., multi_select=False)``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository

_MAX_CLARIFY_CHOICES = 4


def build_name_clarification(
    candidate_name: str,
    observed_context: str | None = None,
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any]:
    """Return an immediate clarification payload for an observed name.

    Known aliases do not pause. Every unknown name pauses, whether it is a common
    first name, similar to an existing root, or a distinct new full-ish name.
    That keeps Person Roots from accumulating stale approval queues.
    """

    repo = PersonRootsRepository(root)
    classification = repo.classify_candidate_name(candidate_name)
    if classification['decision'] in {'ignore', 'known_person'}:
        return {
            'should_pause': False,
            'candidate_name': candidate_name,
            'classification': classification,
            'clarify_args': None,
            'reason': classification['reason'],
        }

    question = _question(candidate_name, classification, observed_context)
    choices = _choices(candidate_name, classification)
    return {
        'should_pause': True,
        'candidate_name': candidate_name,
        'classification': classification,
        'clarify_args': {
            'question': question,
            'choices': tuple(choices),
            'multi_select': False,
        },
        'reason': classification['reason'],
    }


def build_name_clarify_tool_args(
    candidate_name: str,
    observed_context: str | None = None,
    root: str | Path = DEFAULT_ROOT,
) -> dict[str, Any] | None:
    """Return arguments suitable for the Hermes ``clarify`` tool, if needed."""

    payload = build_name_clarification(candidate_name, observed_context, root)
    return payload['clarify_args'] if payload['should_pause'] else None


def _question(candidate_name: str, classification: dict[str, Any], observed_context: str | None) -> str:
    similar_people = classification.get('similar_people') or ()
    context_suffix = ''
    if observed_context:
        cleaned_context = ' '.join(observed_context.split())
        if cleaned_context:
            context_suffix = f" Context: {cleaned_context[:180]}"

    if similar_people:
        similar = ', '.join(
            f"{person['display_name']} ({person['person_id']}, matched {person['matched_alias']})"
            for person in similar_people[:2]
        )
        return (
            f"I saw the name '{candidate_name}', and it looks similar to existing Person Roots: "
            f"{similar}. What should I do?{context_suffix}"
        )
    return f"I saw a new person name, '{candidate_name}'. What should I do with it?{context_suffix}"


def _choices(candidate_name: str, classification: dict[str, Any]) -> list[str]:
    choices: list[str] = []
    for person in (classification.get('similar_people') or ())[:2]:
        choices.append(
            f"Treat '{candidate_name}' as {person['display_name']} ({person['person_id']}) / add alias"
        )
    choices.append(f"Create a new Person Root for '{candidate_name}'")
    choices.append(f"Ignore '{candidate_name}' this time")
    return choices[:_MAX_CLARIFY_CHOICES]
