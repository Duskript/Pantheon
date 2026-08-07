"""Runtime orchestration for Person Roots ingest/apply.

Two safe surfaces around the deterministic core (``lib.person_roots.ingest`` +
``lib.person_roots.apply``):

- ``active_ingest_step`` — for a live Hermes turn: plan candidates; if any
  clarification is needed, stop and hand back the first ``clarify_args``
  payload; otherwise optionally apply only safe ``allow`` facts. Never creates
  person roots or account links.
- ``unattended_ingest_files`` — cron-safe processor for JSON/JSONL candidate
  files dropped into an incoming directory: plans, auto-applies safe facts,
  queues clarifications/approvals/denials/apply-errors in
  ``<root>/_pending/PROPOSALS.jsonl``, and archives processed inputs to
  ``<root>/_processed/`` (never overwriting). Quiet when there is no work;
  the library never prints — callers decide how to render the digest.

No LLM extraction, no live Discord/Ichor scans, no person-root creation, no
account linking. Importable and side-effect free at import time.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib.person_roots.apply import apply_ingest_plan
from lib.person_roots.ingest import CandidateFact, build_ingest_plan
from lib.person_roots.pending import append_pending_items, pending_path
from lib.person_roots.resolver import DEFAULT_ROOT

_PENDING_BUCKETS = (
    ('clarifications', 'clarification'),
    ('approvals', 'approval'),
    ('denied', 'denied'),
)

_NO_WORK_SUMMARY = {
    'files_seen': 0,
    'files_processed': 0,
    'files_failed': 0,
    'applied_count': 0,
    'apply_errors': 0,
    'pending_count': 0,
    'pending_breakdown': {'clarification': 0, 'approval': 0, 'denied': 0, 'error': 0},
    'pending_path': None,
    'archived_paths': [],
    'errors': [],
}


def active_ingest_step(
    candidates: Iterable[CandidateFact | Mapping[str, Any]],
    root: str | Path = DEFAULT_ROOT,
    apply_safe: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Plan active-chat ingestion.

    If clarification is needed, return ``action='clarify'`` and do not apply.
    Otherwise optionally apply safe facts (``action='applied'``) or plan
    without mutation (``action='planned'``).
    """

    plan = build_ingest_plan(candidates, root)
    clarifications = plan.get('clarifications') or []

    if clarifications:
        return {
            'action': 'clarify',
            'plan': plan,
            'clarify_args': clarifications[0].get('clarify_args'),
            'apply_result': None,
            'summary': _active_summary(plan, None),
        }

    if apply_safe:
        apply_result = apply_ingest_plan(plan, root=root, today=today)
        return {
            'action': 'applied',
            'plan': plan,
            'clarify_args': None,
            'apply_result': apply_result,
            'summary': _active_summary(plan, apply_result),
        }

    return {
        'action': 'planned',
        'plan': plan,
        'clarify_args': None,
        'apply_result': None,
        'summary': _active_summary(plan, None),
    }


def unattended_ingest_files(
    incoming_dir: str | Path,
    root: str | Path = DEFAULT_ROOT,
    archive_dir: str | Path | None = None,
    pending_file_reason: str = 'unattended_ingest',
    report_applies: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Cron-safe processor for JSON/JSONL candidate files.

    Behavior:

    - Missing incoming dir (or no ``.json``/``.jsonl`` files) returns a
      no-work summary with ``files_seen=0`` and no errors.
    - Each input file is planned, safe ``allow`` facts are applied, and all
      clarifications/approvals/denials plus apply errors are appended to the
      pending queue with source-file provenance.
    - Inputs are archived to ``<root>/_processed/`` (or ``archive_dir``) with
      a unique filename, never overwriting; a file is only moved after
      successful processing.
    - ``report_applies`` is an output-policy hint for callers (the library
      itself never prints); ``pending_file_reason`` is the fallback
      ``queue_reason`` when a bucket-specific reason is not available.
    """

    incoming = Path(incoming_dir).expanduser()
    root_path = Path(root).expanduser()
    day = today or date.today().isoformat()

    if not incoming.is_dir():
        return dict(_NO_WORK_SUMMARY)

    input_files = sorted(
        path
        for path in incoming.iterdir()
        if path.is_file() and path.suffix.lower() in {'.json', '.jsonl'}
    )
    if not input_files:
        return dict(_NO_WORK_SUMMARY)

    archive = Path(archive_dir).expanduser() if archive_dir is not None else root_path / '_processed'

    pending_breakdown = {'clarification': 0, 'approval': 0, 'denied': 0, 'error': 0}
    archived_paths: list[str] = []
    errors: list[str] = []
    files_processed = 0
    applied_count = 0
    apply_error_count = 0

    for path in input_files:
        try:
            candidates = _load_candidate_file(path)
            plan = build_ingest_plan(candidates, root=root_path)
            apply_result = apply_ingest_plan(plan, root=root_path, today=day)

            applied_count += apply_result['summary']['applied']

            for bucket, reason in _PENDING_BUCKETS:
                _append_bucket(
                    plan.get(bucket) or [],
                    reason=reason,
                    fallback_reason=pending_file_reason,
                    root=root_path,
                    source_file=str(path),
                    today=day,
                    counts=pending_breakdown,
                )

            apply_errors = apply_result.get('errors') or []
            apply_error_count += len(apply_errors)
            _append_bucket(
                apply_errors,
                reason='error',
                fallback_reason=pending_file_reason,
                root=root_path,
                source_file=str(path),
                today=day,
                counts=pending_breakdown,
            )

            archived = _archive_file(path, archive)
            archived_paths.append(str(archived))
            files_processed += 1
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f'{path.name}: {exc}')

    return {
        'files_seen': len(input_files),
        'files_processed': files_processed,
        'files_failed': len(input_files) - files_processed,
        'applied_count': applied_count,
        'apply_errors': apply_error_count,
        'pending_count': sum(pending_breakdown.values()),
        'pending_breakdown': pending_breakdown,
        'pending_path': str(pending_path(root_path)) if sum(pending_breakdown.values()) else None,
        'archived_paths': archived_paths,
        'errors': errors,
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _active_summary(plan: Mapping[str, Any], apply_result: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compact counts for ``active_ingest_step`` including pending buckets."""

    summary = dict(plan.get('summary') or {})
    summary['applied'] = int(apply_result['summary']['applied']) if apply_result else 0
    return summary


def _load_candidate_file(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list or JSONL file of candidate objects."""

    text = path.read_text(encoding='utf-8')
    stripped = text.strip()
    if not stripped:
        return []

    if stripped.startswith('['):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError(f'{path.name}: JSON input must be a list of candidate objects')
        return list(data)

    candidates: list[dict[str, Any]] = []
    for line_number, line in enumerate(stripped.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path.name}: invalid JSON on line {line_number}: {exc}') from exc
    return candidates


def _append_bucket(
    items: list[Mapping[str, Any]],
    *,
    reason: str,
    fallback_reason: str,
    root: Path,
    source_file: str,
    today: str,
    counts: dict[str, int],
) -> None:
    """Append one pending bucket, tracking counts by queue reason."""

    if not items:
        return
    result = append_pending_items(
        items,
        root=root,
        reason=reason or fallback_reason,
        source_file=source_file,
        today=today,
    )
    counts[reason] += result['count']


def _archive_file(source: Path, archive_dir: Path) -> Path:
    """Move ``source`` into ``archive_dir`` under a unique name.

    Never overwrites: existing targets get a numeric suffix. Uses
    ``Path.replace`` (an atomic same-volume move); the input is only removed
    when the move succeeds.
    """

    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / source.name
    if target.exists():
        stem = source.stem
        suffix = source.suffix
        counter = 1
        while target.exists():
            target = archive_dir / f'{stem}-{counter}{suffix}'
            counter += 1
    source.replace(target)
    return target
