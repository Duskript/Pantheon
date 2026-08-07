"""Read-only admin/status surface for Pantheon Person Roots.

This module gathers the local state a future dashboard should render, without
starting a web server or mutating relationship files:

1. Person IDs/count and direct-user roots.
2. Trust tiers and verified/pending account-link counts.
3. Pending proposal queue, incoming candidate files, and processed archives.
4. Structural validator health.
5. Compact blockers and next actions for the operator.

The function is safe to call from scripts, tests, or a dashboard endpoint because
it performs no writes, resolves no placeholder account IDs, opens no network
sockets, and does not mutate Hermes/Pantheon configuration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.person_roots.accounts import AccountLink, parse_account_links
from lib.person_roots.pending import pending_path, read_pending_items
from lib.person_roots.resolver import DEFAULT_ROOT, PersonRootsRepository


def build_status(root: str | Path = DEFAULT_ROOT, pending_limit: int = 20) -> dict[str, Any]:
    """Return a serializable read-only dashboard summary for Person Roots."""

    resolved_root = Path(root).expanduser().resolve()
    repo = PersonRootsRepository(resolved_root)
    people = repo.list_people()
    records = [repo.load_person(person_id) for person_id in people]
    account_links = parse_account_links(resolved_root)
    validation = _validate_root(resolved_root)
    queues = _queue_status(resolved_root, pending_limit=pending_limit)
    pending_accounts = [link for link in account_links if link.status == 'pending']
    verified_accounts = [link for link in account_links if link.status == 'verified']
    blockers = _blockers(validation, queues, pending_accounts)
    return {
        'root': str(resolved_root),
        'person_count': len(people),
        'people': people,
        'direct_users': sorted(record.person_id for record in records if record.direct_user),
        'trust_tiers': {record.person_id: record.trust_tier for record in records},
        'account_links': [_link_to_dict(link) for link in account_links],
        'pending_account_links': len(pending_accounts),
        'verified_account_links': len(verified_accounts),
        'queues': queues,
        'pending_proposals': queues['pending_preview'],
        'validator_passed': validation['passed'],
        'warnings': validation['warnings'],
        'errors': validation['errors'],
        'blockers': blockers,
        'next_actions': _next_actions(blockers, pending_accounts),
    }


def render_status_text(status: dict[str, Any]) -> str:
    """Render ``build_status`` output as a compact operator dashboard."""

    queues = status.get('queues') or {}
    lines = [
        'Person Roots Admin Dashboard',
        '=' * 28,
        f"Root: {status.get('root')}",
        f"People: {status.get('person_count')} ({', '.join(status.get('direct_users') or [])} direct users)",
        f"Account links: {status.get('verified_account_links')} verified / {status.get('pending_account_links')} pending",
        f"Queues: {queues.get('pending_count', 0)} pending proposal(s), "
        f"{queues.get('incoming_count', 0)} incoming file(s), "
        f"{queues.get('processed_count', 0)} processed file(s)",
        f"Validator: {'PASS' if status.get('validator_passed') else 'FAIL'}",
        '',
        'Blockers:',
    ]
    blockers = status.get('blockers') or []
    if blockers:
        lines.extend(f"- {item}" for item in blockers)
    else:
        lines.append('- none')
    lines.append('')
    lines.append('Next actions:')
    actions = status.get('next_actions') or []
    if actions:
        lines.extend(f"- {item}" for item in actions)
    else:
        lines.append('- none')
    return '\n'.join(lines)


def _link_to_dict(link: AccountLink) -> dict[str, str]:
    return {
        'platform': link.platform,
        'account_id': link.account_id,
        'person_id': link.person_id,
        'status': link.status,
        'verified_by': link.verified_by,
        'notes': link.notes,
    }


def _queue_status(root: Path, *, pending_limit: int) -> dict[str, Any]:
    incoming_dir = root / '_incoming'
    processed_dir = root / '_processed'
    pending_file = pending_path(root)
    resolved_file = root / '_pending' / 'RESOLVED.jsonl'
    pending_error: str | None = None
    try:
        pending_records = read_pending_items(root, limit=max(1, int(pending_limit)))
        pending_count = _jsonl_count(pending_file)
    except ValueError as exc:
        pending_records = []
        pending_count = 0
        pending_error = str(exc)
    return {
        'incoming_dir': str(incoming_dir),
        'incoming_count': len(_files(incoming_dir)),
        'incoming_files': _files(incoming_dir)[:20],
        'processed_dir': str(processed_dir),
        'processed_count': len(_files(processed_dir)),
        'pending_path': str(pending_file),
        'pending_count': pending_count,
        'pending_preview': [_pending_preview(record, index) for index, record in enumerate(pending_records)],
        'pending_error': pending_error,
        'resolved_path': str(resolved_file),
        'resolved_count': _jsonl_count(resolved_file),
    }


def _files(path: Path) -> list[str]:
    if not path.exists() or not path.is_dir():
        return []
    return sorted(child.name for child in path.iterdir() if child.is_file())


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with open(path, 'r', encoding='utf-8') as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _pending_preview(record: dict[str, Any], index: int) -> dict[str, Any]:
    item = record.get('item') if isinstance(record, dict) else {}
    if not isinstance(item, dict):
        item = {}
    value = ' '.join(str(item.get('value') or '').split())
    if len(value) > 140:
        value = value[:137] + '...'
    return {
        'index': index,
        'queue_reason': record.get('queue_reason'),
        'source_file': record.get('source_file'),
        'person_id': item.get('person_id'),
        'candidate_name': item.get('candidate_name'),
        'field': item.get('field'),
        'value': value,
    }


def _blockers(validation: dict[str, Any], queues: dict[str, Any], pending_accounts: list[AccountLink]) -> list[str]:
    blockers: list[str] = []
    if not validation['passed']:
        blockers.append(f"validator failing: {len(validation['errors'])} error(s)")
    if queues.get('pending_error'):
        blockers.append(f"pending queue unreadable: {queues['pending_error']}")
    if queues.get('pending_count', 0):
        blockers.append(f"{queues['pending_count']} pending proposal(s) need approve/ignore")
    if queues.get('incoming_count', 0):
        blockers.append(f"{queues['incoming_count']} incoming candidate file(s) awaiting watcher")
    for link in pending_accounts:
        blockers.append(f"{link.person_id} has pending {link.platform} account link")
    return blockers


def _next_actions(blockers: list[str], pending_accounts: list[AccountLink]) -> list[str]:
    actions: list[str] = []
    if any('pending proposal' in blocker for blocker in blockers):
        actions.append('Run scripts/person-roots-pending.py list --json, then approve or ignore rows.')
    if any('incoming candidate' in blocker for blocker in blockers):
        actions.append('Let cron watcher 8674b16a15dd process _incoming/ or run the wrapper manually.')
    for link in pending_accounts:
        actions.append(f'Provide and verify {link.person_id} {link.platform} account ID.')
    if any('validator failing' in blocker for blocker in blockers):
        actions.append('Fix validator errors before exposing dashboard data.')
    return actions


def _validate_root(root: Path) -> dict[str, Any]:
    import importlib.util

    validator_path = Path('<repo-root>/scripts/validate-person-roots.py')
    spec = importlib.util.spec_from_file_location('validate_person_roots_runtime', validator_path)
    if spec is None or spec.loader is None:
        return {'passed': False, 'warnings': [], 'errors': [f'Cannot load validator: {validator_path}']}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors, warnings, _stats = module.validate(str(root))
    return {'passed': not errors, 'warnings': warnings, 'errors': errors}
