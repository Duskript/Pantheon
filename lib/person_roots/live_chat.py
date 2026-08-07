"""Active-chat wrapper for Person Roots ingestion.

This is the live-turn integration surface above ``active_ingest_step``. It takes
structured candidate facts that were already extracted from an explicit operator
message and returns one of three safe outcomes:

- ``clarify``: pass ``clarify_args`` directly to Hermes' ``clarify`` tool and do
  not mutate files.
- ``applied``: safe ``allow`` facts were applied through the guarded writer.
- ``planned_review``: approval/deny-class facts were observed, but the live-turn
  path refused to queue or write them.

The wrapper never creates roots, never links accounts, never appends to
``_pending/PROPOSALS.jsonl``, and performs no free-form/LLM extraction.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib.person_roots.ingest import CandidateFact
from lib.person_roots.resolver import DEFAULT_ROOT
from lib.person_roots.runtime import active_ingest_step


def handle_live_chat_candidates(
    candidates: Iterable[CandidateFact | Mapping[str, Any]],
    *,
    root: str | Path = DEFAULT_ROOT,
    apply_safe: bool = True,
    today: str | None = None,
) -> dict[str, Any]:
    """Handle one active-chat candidate batch without durable review queues."""

    candidate_list = list(candidates)
    if not candidate_list:
        return {
            'action': 'no_candidates',
            'clarify_args': None,
            'tool_call': None,
            'plan': {'applies': [], 'clarifications': [], 'approvals': [], 'denied': [], 'summary': _empty_summary()},
            'apply_result': None,
            'summary': _empty_summary() | {'applied': 0, 'queued': 0},
            'message': 'No structured Person Roots candidates were supplied.',
        }

    result = active_ingest_step(candidate_list, root=root, apply_safe=apply_safe, today=today)
    plan = result['plan']
    if result['action'] == 'clarify':
        return {
            **result,
            'tool_call': {'name': 'clarify', 'arguments': result['clarify_args']},
            'message': 'Clarification required before Person Roots can ingest this live-chat fact.',
        }

    review_count = len(plan.get('approvals') or []) + len(plan.get('denied') or [])
    if review_count:
        return {
            'action': 'planned_review',
            'clarify_args': None,
            'tool_call': None,
            'plan': plan,
            'apply_result': result.get('apply_result'),
            'summary': {**result['summary'], 'review': review_count, 'queued': 0},
            'message': 'Live-chat path refused to queue approval/deny items; use unattended or pending resolver workflow.',
        }

    return {
        **result,
        'tool_call': None,
        'summary': {**result['summary'], 'review': 0, 'queued': 0},
        'message': 'Live-chat Person Roots candidates handled safely.',
    }


def render_live_chat_result(result: Mapping[str, Any]) -> str:
    """Render a compact human-readable live-chat wrapper result."""

    action = result.get('action')
    summary = result.get('summary') or {}
    if action == 'clarify':
        args = result.get('clarify_args') or {}
        return f"Person Roots needs clarification: {args.get('question', 'no question provided')}"
    if action == 'planned_review':
        return (
            'Person Roots live-chat review needed: '
            f"{summary.get('review', 0)} approval/deny item(s) were not queued or applied."
        )
    if action == 'applied':
        return f"Person Roots applied {summary.get('applied', 0)} safe live-chat fact(s)."
    if action == 'planned':
        return f"Person Roots planned {summary.get('total', 0)} live-chat fact(s) without mutation."
    return str(result.get('message') or 'No Person Roots live-chat action.')


def load_candidate_stream(path: str | Path) -> list[dict[str, Any]]:
    """Load JSON list or JSONL candidate stream for CLI smoke/testing."""

    source = Path(path).expanduser()
    text = source.read_text(encoding='utf-8').strip()
    if not text:
        return []
    if text.startswith('['):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError('JSON candidate stream must be a list')
        return list(data)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f'invalid JSON on line {line_number}: {exc}') from exc
        if not isinstance(row, dict):
            raise ValueError(f'candidate on line {line_number} must be an object')
        rows.append(row)
    return rows


def _empty_summary() -> dict[str, int]:
    return {'total': 0, 'apply': 0, 'clarify': 0, 'approval': 0, 'deny': 0}
