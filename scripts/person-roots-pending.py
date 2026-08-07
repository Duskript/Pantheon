#!/usr/bin/env python3
"""List or resolve Person Roots pending proposal records."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.person_roots.pending_resolver import list_pending, resolve_pending_records

DEFAULT_ROOT = Path(os.environ.get('PERSON_ROOTS_ROOT', str(Path.home() / '.pantheon' / 'person-roots' / 'relationships')))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    list_parser = sub.add_parser('list', help='List pending records.')
    list_parser.add_argument('--root', default=str(DEFAULT_ROOT))
    list_parser.add_argument('--limit', type=int, default=None)
    list_parser.add_argument('--json', action='store_true', dest='as_json')

    resolve_parser = sub.add_parser('resolve', help='Resolve selected records.')
    resolve_parser.add_argument('--root', default=str(DEFAULT_ROOT))
    resolve_parser.add_argument('--actions', required=True, help='JSON list of {index, action, note?}.')
    resolve_parser.add_argument('--dry-run', action='store_true')
    resolve_parser.add_argument('--json', action='store_true', dest='as_json')

    args = parser.parse_args(argv)

    if args.command == 'list':
        records = list_pending(root=args.root, limit=args.limit)
        if args.as_json:
            print(json.dumps(records, indent=2, sort_keys=True, default=str))
        else:
            _print_pending(records)
        return 0

    actions = _load_actions(args.actions)
    result = resolve_pending_records(actions, root=args.root, dry_run=args.dry_run)
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        _print_resolution(result)
    return 0 if result['failed_count'] == 0 else 1


def _load_actions(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(f'Invalid --actions JSON: {exc}') from exc
    if not isinstance(data, list) or not all(isinstance(item, dict) for item in data):
        raise SystemExit('--actions must be a JSON list of objects')
    return data


def _print_pending(records: list[dict[str, Any]]) -> None:
    if not records:
        print('No pending Person Roots proposals.')
        return
    print(f'Pending Person Roots proposals: {len(records)}')
    for record in records:
        item = record.get('item') or {}
        who = item.get('display_name') or item.get('person_id') or item.get('candidate_name') or 'unknown'
        field = item.get('field', '-')
        reason = record.get('queue_reason', 'pending')
        value = ' '.join(str(item.get('value', '')).split())
        if len(value) > 80:
            value = value[:77] + '...'
        print(f"[{record['index']}] {reason}: {who} :: {field} :: {value}")


def _print_resolution(result: dict[str, Any]) -> None:
    mode = 'DRY RUN ' if result['dry_run'] else ''
    print(
        f"{mode}Person Roots pending resolver: "
        f"resolved={result['resolved_count']} applied={result['applied_count']} "
        f"failed={result['failed_count']} remaining={result['records_after']}"
    )
    if result.get('backup_path'):
        print(f"Backup: {result['backup_path']}")
    if result.get('resolved_path'):
        print(f"Resolved log: {result['resolved_path']}")
    for failure in result.get('failed') or []:
        print(f"FAILED [{failure.get('index')}]: {failure.get('reason')}")


if __name__ == '__main__':
    raise SystemExit(main())
