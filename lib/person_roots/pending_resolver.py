"""Resolution helpers for the Person Roots pending proposal queue.

The unattended watcher stores questionable or approval-required items in
``<root>/_pending/PROPOSALS.jsonl``. This module lets an operator resolve those
records without hand-editing JSONL. It only supports two safe actions in this
slice: ``approve`` and ``ignore``. Alias merges, root creation, and account
linking are explicitly reported as unsupported.

Safety boundary
---------------
``approve`` does not bypass the guarded writer. It builds a one-item ingest plan
and calls ``apply_ingest_plan``. The only extra authority it provides is setting
``decision='allow'`` on a complete pending item, because the operator resolution
itself is the explicit approval. The writer still refuses unknown routes,
missing files, missing person roots, and account-link/root-creation attempts.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from lib.person_roots.apply import apply_ingest_plan
from lib.person_roots.pending import pending_path, read_pending_items
from lib.person_roots.resolver import DEFAULT_ROOT

_SUPPORTED_ACTIONS = {'approve', 'ignore'}
_UNSUPPORTED_ACTIONS = {'alias', 'create_root', 'link_account'}
_REQUIRED_APPROVAL_FIELDS = ('person_id', 'field', 'value', 'source_person_id', 'source_type')


def list_pending(root: str | Path = DEFAULT_ROOT, limit: int | None = None) -> list[dict[str, Any]]:
    """Return pending records with stable zero-based ``index`` values."""

    records = read_pending_items(root=root, limit=limit)
    return [dict(record, index=index) for index, record in enumerate(records)]


def resolve_pending_records(
    actions: Iterable[Mapping[str, Any]],
    *,
    root: str | Path = DEFAULT_ROOT,
    today: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Resolve selected pending records by index.

    ``approve`` applies one known-person item through ``apply_ingest_plan`` with
    an explicit ``decision='allow'`` because the operator action is the approval.
    ``ignore`` moves the record to ``RESOLVED.jsonl`` without mutation.
    Unsupported actions are reported and left unresolved.
    """

    root_path = Path(root).expanduser()
    queue_path = pending_path(root_path)
    records = read_pending_items(root_path)
    day = today or date.today().isoformat()
    action_map = _normalize_actions(actions)

    resolved: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    applied: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []

    for index, record in enumerate(records):
        action = action_map.get(index)
        if action is None:
            retained.append(record)
            continue

        action_name = str(action.get('action', '')).strip().lower()
        note = str(action.get('note', '')).strip()

        if action_name in _UNSUPPORTED_ACTIONS:
            failed.append({'index': index, 'action': action_name, 'reason': 'unsupported action in this slice'})
            retained.append(record)
            continue
        if action_name not in _SUPPORTED_ACTIONS:
            failed.append({'index': index, 'action': action_name, 'reason': 'unknown action'})
            retained.append(record)
            continue

        if action_name == 'ignore':
            resolved.append(_resolved_record(record, index, action_name, day, note, None))
            if dry_run:
                retained.append(record)
            continue

        approval_item = _approval_item(record)
        if approval_item is None:
            failed.append({'index': index, 'action': action_name, 'reason': 'record is not approvable'})
            retained.append(record)
            continue

        apply_result = apply_ingest_plan(
            {'applies': [approval_item], 'clarifications': [], 'approvals': [], 'denied': []},
            root=root_path,
            dry_run=dry_run,
            today=day,
        )
        if apply_result.get('errors'):
            failed.append({
                'index': index,
                'action': action_name,
                'reason': 'apply failed',
                'apply_result': apply_result,
            })
            retained.append(record)
            continue

        applied.append({'index': index, 'apply_result': apply_result})
        resolved.append(_resolved_record(record, index, action_name, day, note, apply_result))
        if dry_run:
            retained.append(record)

    missing = sorted(set(action_map) - set(range(len(records))))
    for index in missing:
        failed.append({'index': index, 'action': action_map[index].get('action'), 'reason': 'index out of range'})

    backup_path: str | None = None
    resolved_path: str | None = None
    if not dry_run and (resolved or len(retained) != len(records)):
        backup_path = _backup_queue(queue_path)
        _write_jsonl(queue_path, retained)
        if resolved:
            resolved_path = str(_append_resolved(root_path, resolved))

    return {
        'dry_run': bool(dry_run),
        'queue_path': str(queue_path),
        'backup_path': backup_path,
        'resolved_path': resolved_path,
        'records_before': len(records),
        'records_after': len(retained),
        'resolved_count': len(resolved),
        'failed_count': len(failed),
        'applied_count': len(applied),
        'resolved': resolved,
        'failed': failed,
        'applied': applied,
    }


def _normalize_actions(actions: Iterable[Mapping[str, Any]]) -> dict[int, dict[str, Any]]:
    normalized: dict[int, dict[str, Any]] = {}
    for raw in actions:
        if 'index' not in raw:
            raise ValueError('Each action requires an index')
        try:
            index = int(raw['index'])
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Invalid action index: {raw.get("index")!r}') from exc
        if index < 0:
            raise ValueError('Action index must be non-negative')
        if index in normalized:
            raise ValueError(f'Duplicate action index: {index}')
        normalized[index] = dict(raw)
    return normalized


def _approval_item(record: Mapping[str, Any]) -> dict[str, Any] | None:
    item = record.get('item')
    if not isinstance(item, Mapping):
        return None
    if not all(field in item for field in _REQUIRED_APPROVAL_FIELDS):
        return None

    queue_reason = str(record.get('queue_reason') or '')
    decision = item.get('decision')
    if decision != 'allow' and queue_reason != 'approval':
        return None

    approved = dict(item)
    approved['decision'] = 'allow'
    approved['reason'] = f'Explicit operator approval; previous reason: {item.get("reason", "")}'
    return approved


def _resolved_record(
    record: Mapping[str, Any],
    index: int,
    action: str,
    day: str,
    note: str,
    apply_result: Mapping[str, Any] | None,
) -> dict[str, Any]:
    resolved = dict(record)
    resolved['resolved'] = day
    resolved['resolved_index'] = index
    resolved['resolution_action'] = action
    if note:
        resolved['resolution_note'] = note
    if apply_result is not None:
        resolved['apply_result'] = dict(apply_result)
    return resolved


def _backup_queue(path: Path) -> str | None:
    if not path.exists():
        return None
    stamp = datetime.now().strftime('%Y%m%d%H%M%S')
    backup = path.with_name(f'{path.name}.bak-{stamp}')
    counter = 1
    while backup.exists():
        backup = path.with_name(f'{path.name}.bak-{stamp}-{counter}')
        counter += 1
    shutil.copy2(path, backup)
    return str(backup)


def _write_jsonl(path: Path, records: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    materialized = list(records)
    if not materialized:
        path.write_text('', encoding='utf-8')
        return
    with open(path, 'w', encoding='utf-8') as handle:
        for record in materialized:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')


def _append_resolved(root: Path, records: Iterable[Mapping[str, Any]]) -> Path:
    path = root / '_pending' / 'RESOLVED.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
    return path
