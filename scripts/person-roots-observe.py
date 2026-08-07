#!/usr/bin/env python3
"""Person Roots explicit-marker observer CLI.

Purpose
-------
This command is the safe bridge between human/god-authored source artifacts and
the already-live Person Roots background ingest watcher. It scans source files
for explicit marker lines such as::

    PERSON_ROOT: Demo Person | profile.known_context | Demo context marker.
    @person-fact Sample Work Contact | notes.work | Retiring in Dec 2026.

It does **not** run an LLM, scrape Discord, infer facts from free prose, write
person-root markdown files, create people, link accounts, or update Ichor. It
only emits structured CandidateFact JSONL into the incoming directory. The
existing background watcher then resolves/classifies/applies/queues those facts
under the privacy rules.

Default live output
-------------------
~/.pantheon/person-roots/relationships/_incoming/
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.person_roots.observer import observe_source_files

DEFAULT_ROOT = Path(os.environ.get('PERSON_ROOTS_ROOT', str(Path.home() / '.pantheon' / 'person-roots' / 'relationships')))
DEFAULT_INCOMING = DEFAULT_ROOT / '_incoming'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Extract explicit Person Roots candidate markers.')
    parser.add_argument('sources', nargs='+', help='Source files or directories to scan.')
    parser.add_argument('--incoming', default=str(DEFAULT_INCOMING), help='Incoming candidate directory.')
    parser.add_argument('--root', default=str(DEFAULT_ROOT), help='Relationship root; used to derive incoming when custom root is set.')
    parser.add_argument('--recursive', action='store_true', help='Recurse source directories.')
    parser.add_argument('--source-person-id', default='owner')
    parser.add_argument('--source-type', default='owner_account')
    parser.add_argument('--sensitivity', default='private')
    parser.add_argument('--json', action='store_true', dest='as_json')
    args = parser.parse_args(argv)

    incoming = Path(args.incoming).expanduser()
    if args.incoming == str(DEFAULT_INCOMING) and args.root != str(DEFAULT_ROOT):
        incoming = Path(args.root).expanduser() / '_incoming'

    result = observe_source_files(
        args.sources,
        incoming_dir=incoming,
        source_person_id=args.source_person_id,
        source_type=args.source_type,
        sensitivity=args.sensitivity,
        recursive=args.recursive,
    )

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if not result['errors'] else 1

    if result['candidates']:
        print(
            f"Person Roots observer: extracted {result['candidates']} candidate(s) "
            f"from {result['files_read']}/{result['files_seen']} file(s)."
        )
        print(f"Output: {result['output_path']}")
    else:
        print(
            f"Person Roots observer: no explicit candidate markers found "
            f"in {result['files_read']}/{result['files_seen']} file(s)."
        )
    if result['errors']:
        print('Errors:')
        for error in result['errors']:
            print(f'- {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
