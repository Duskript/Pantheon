"""Guarded writer for Person Roots ingest plans.

Only ``plan['applies']`` entries — facts already classified ``allow`` by the
source-authority proposal rules — may be written. This module never creates
person roots, never links accounts, and never canonizes clarification- or
approval-required facts.

Writer behavior:

- Only apply items already in ``plan['applies']``; everything else is skipped.
- Re-check that the target person folder still exists through
  ``PersonRootsRepository.path_for``; a missing folder is an error, never an
  implicit creation.
- Append facts as markdown bullets with provenance, preserving frontmatter.
- Append one interaction-log row per applied fact.
- Supported field routes:
  - ``profile.*``                  -> ``## Known context`` in ``PROFILE.md``
  - ``relationship_to_owner.*``    -> ``## What Owner has said`` in ``RELATIONSHIP_TO_OWNER.md``
  - ``notes.*`` or ``notes``       -> ``## Auto-applied facts`` in ``NOTES.md``
- Unknown routes are never written; they produce error entries.
- Exact duplicate bullets (same value + provenance line) are skipped.
- ``dry_run=True`` mutates nothing but still reports targets and would-apply
  rows.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from lib.person_roots.ingest import build_ingest_plan
from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository

_PROFILE_SECTION = '## Known context'
_RELATIONSHIP_SECTION = '## Owner notes'
_NOTES_SECTION = '## Auto-applied facts'

_LOG_HEADINGS = ('# Interaction Log', '## Interaction Log')
_LOG_TABLE_HEADER = '| Date | Source | Summary | Notes |'
_LOG_TABLE_SEPARATOR = '|---|---|---|---|'
_MAX_VALUE_PREVIEW = 60


def apply_ingest_plan(
    plan: Mapping[str, Any],
    root: str | Path = DEFAULT_ROOT,
    dry_run: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Apply only allowed planned updates. Return serializable results."""

    repo = PersonRootsRepository(root)
    day = today or date.today().isoformat()

    applied: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    # Anything outside plan['applies'] is never written.
    for bucket in ('clarifications', 'approvals', 'denied'):
        for item in plan.get(bucket) or []:
            entry: dict[str, Any] = {'reason': 'not in applies'}
            for key in ('candidate_name', 'person_id', 'field'):
                if key in item:
                    entry[key] = item[key]
            skipped.append(entry)

    for item in plan.get('applies') or []:
        person_id = item.get('person_id')
        field = item.get('field')
        value = item.get('value')

        # Guard: a hand-crafted plan must not smuggle non-allow facts through
        # the applies bucket. Only facts explicitly classified ``allow`` may be
        # written; a missing decision is just as unsafe as a non-allow one.
        if item.get('decision') != 'allow':
            skipped.append({
                'person_id': person_id,
                'field': field,
                'reason': 'decision is not allow',
            })
            continue

        route = _route_for(field) if isinstance(field, str) else None
        if route is None:
            errors.append({
                'person_id': person_id,
                'field': field,
                'reason': 'unknown field route',
            })
            continue

        relative_file, section = route
        try:
            target = repo.path_for(person_id, relative_file)
        except KeyError:
            errors.append({
                'person_id': person_id,
                'field': field,
                'reason': 'person folder no longer exists',
            })
            continue
        except (TypeError, ValueError):
            errors.append({
                'person_id': person_id,
                'field': field,
                'reason': 'invalid person_id or target path',
            })
            continue

        if not target.exists():
            errors.append({
                'person_id': person_id,
                'field': field,
                'reason': 'target file missing',
            })
            continue

        bullet = _build_bullet(value, item)
        if _bullet_exists(target, section, bullet):
            skipped.append({
                'person_id': person_id,
                'field': field,
                'value': value,
                'reason': 'duplicate bullet',
            })
            continue

        applied.append({
            'person_id': person_id,
            'field': field,
            'target_file': str(target),
            'value': value,
            'dry_run': bool(dry_run),
        })
        if dry_run:
            continue

        _append_bullet(target, section, bullet)
        try:
            log_path = repo.path_for(person_id, 'INTERACTION_LOG.md')
        except (KeyError, TypeError, ValueError):
            log_path = None
        if log_path is not None and log_path.exists():
            _append_log_row(log_path, _build_log_row(day, field, value, item))

    return {
        'applied': applied,
        'skipped': skipped,
        'errors': errors,
        'summary': {
            'applied': len(applied),
            'skipped': len(skipped),
            'errors': len(errors),
            'dry_run': bool(dry_run),
        },
    }


def ingest_and_apply(
    candidates: Any,
    root: str | Path = DEFAULT_ROOT,
    dry_run: bool = False,
    today: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: build the plan, then apply allowed updates."""

    plan = build_ingest_plan(candidates, root)
    apply_result = apply_ingest_plan(plan, root, dry_run=dry_run, today=today)
    return {'plan': plan, 'apply_result': apply_result}


# ---------------------------------------------------------------------------
# Field routing
# ---------------------------------------------------------------------------

def _route_for(field: str) -> tuple[str, str] | None:
    """Map a planned field to ``(relative filename, markdown section heading)``."""

    if field == 'notes' or field.startswith('notes.'):
        return ('NOTES.md', _NOTES_SECTION)
    if field.startswith('profile.'):
        return ('PROFILE.md', _PROFILE_SECTION)
    if field.startswith('relationship_to_owner.'):
        return ('RELATIONSHIP_TO_OWNER.md', _RELATIONSHIP_SECTION)
    return None


# ---------------------------------------------------------------------------
# Bullet construction and appending
# ---------------------------------------------------------------------------

def _build_bullet(value: Any, item: Mapping[str, Any]) -> str:
    """Build the exact ``- value (provenance...)`` bullet line for a fact."""

    text = ' '.join(str(value).split())
    return f'- {text}{_provenance_suffix(item)}'


def _provenance_suffix(item: Mapping[str, Any]) -> str:
    """Compact, deterministic provenance suffix attached to every written bullet."""

    bits: list[str] = [f'source={item.get("source_type") or "unknown"}']
    source_person_id = item.get('source_person_id')
    if source_person_id:
        bits.append(f'source_person={source_person_id}')
    provenance = item.get('provenance') or {}
    for key in sorted(provenance):
        raw = provenance[key]
        if isinstance(raw, (dict, list, tuple)):
            raw = json.dumps(raw, sort_keys=True, default=str)
        bits.append(f'{key}={raw}')
    return ' (' + ', '.join(bits) + ')'


def _find_section_start(lines: list[str], section: str) -> int | None:
    for index, line in enumerate(lines):
        if line.strip() == section:
            return index
    return None


def _section_lines(lines: list[str], start: int) -> list[str]:
    return [
        line
        for line in lines[start + 1:]
        if not line.lstrip().startswith('#')
    ]


def _bullet_exists(path: Path, section: str, bullet: str) -> bool:
    lines = path.read_text(encoding='utf-8').splitlines()
    start = _find_section_start(lines, section)
    if start is None:
        return False
    needle = bullet.strip()
    return any(line.strip() == needle for line in _section_lines(lines, start))


def _append_bullet(path: Path, section: str, bullet: str) -> None:
    lines = path.read_text(encoding='utf-8').splitlines()
    start = _find_section_start(lines, section)
    if start is None:
        body = '\n'.join(lines).rstrip()
        path.write_text(f'{body}\n\n{section}\n\n{bullet}\n', encoding='utf-8')
        return
    end = start + 1
    while end < len(lines) and not lines[end].lstrip().startswith('#'):
        end += 1
    lines.insert(end, bullet)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


# ---------------------------------------------------------------------------
# Interaction log rows
# ---------------------------------------------------------------------------

def _build_log_row(day: str, field: str, value: Any, item: Mapping[str, Any]) -> str:
    preview = ' '.join(str(value).split())
    if len(preview) > _MAX_VALUE_PREVIEW:
        preview = preview[:_MAX_VALUE_PREVIEW - 3] + '...'
    source = str(item.get('source_type') or 'unknown')
    return f'| {day} | {source} | Ingested {field}. | {preview} |'


def _is_log_heading(line: str) -> bool:
    return line.strip() in _LOG_HEADINGS


def _append_log_row(path: Path, row: str) -> None:
    text = path.read_text(encoding='utf-8').rstrip('\n')
    lines = text.splitlines()
    pipe_indices = [i for i, line in enumerate(lines) if line.lstrip().startswith('|')]
    if pipe_indices:
        lines.insert(pipe_indices[-1] + 1, row)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        return
    heading_index = next((i for i, line in enumerate(lines) if _is_log_heading(line)), None)
    table = f'{_LOG_TABLE_HEADER}\n{_LOG_TABLE_SEPARATOR}\n{row}'
    if heading_index is None:
        path.write_text(f'{text}\n\n# Interaction Log\n\n{table}\n', encoding='utf-8')
    else:
        lines.insert(heading_index + 1, '')
        lines.insert(heading_index + 2, table)
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
