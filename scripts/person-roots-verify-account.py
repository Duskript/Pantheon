#!/usr/bin/env python3
"""Verify and apply one Person Roots platform account link.

The command expects the operator to provide live platform proof separately. For
Discord, use Hermes' `discord_admin member_info` tool and pass the returned JSON
through `--proof-json` or `--proof-file`; this script validates that the proof's
`user_id` matches the requested account ID and that the account is not a bot.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.person_roots.account_verification import verify_account_link
from lib.person_roots.resolver import DEFAULT_ROOT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Verify one Person Roots account link.')
    parser.add_argument('--root', default=str(DEFAULT_ROOT))
    parser.add_argument('--person-id', required=True)
    parser.add_argument('--platform', required=True, choices=['discord', 'telegram'])
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--verified-by', default='owner')
    parser.add_argument('--proof-json', default='')
    parser.add_argument('--proof-file', default='')
    parser.add_argument('--today', default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--json', action='store_true', dest='as_json')
    args = parser.parse_args(argv)

    proof = _load_proof(args.proof_json, args.proof_file)
    result = verify_account_link(
        person_id=args.person_id,
        platform=args.platform,
        account_id=args.account_id,
        verified_by=args.verified_by,
        root=args.root,
        proof=proof,
        today=args.today,
        dry_run=args.dry_run,
    )
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        mode = 'DRY RUN ' if result['dry_run'] else ''
        print(
            f"{mode}Person Roots account verification: {result['platform']}:{result['account_id']} "
            f"→ {result['person_id']} changed={result['would_change']}"
        )
        for path in result['changed_files']:
            print(f'- {path}')
    return 0


def _load_proof(raw_json: str, proof_file: str) -> dict | None:
    if raw_json and proof_file:
        raise SystemExit('Use either --proof-json or --proof-file, not both')
    if proof_file:
        return json.loads(Path(proof_file).expanduser().read_text(encoding='utf-8'))
    if raw_json:
        return json.loads(raw_json)
    return None


if __name__ == '__main__':
    raise SystemExit(main())
