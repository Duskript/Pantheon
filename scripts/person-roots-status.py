#!/usr/bin/env python3
"""Print the read-only Pantheon Person Roots admin dashboard.

This local operator helper does not start a web server, open a socket, mutate
Athenaeum files, resolve pending account links, or call any messaging platform.
It serializes ``lib.person_roots.admin_status`` as JSON or compact text for a
human/operator or a future dashboard process.
"""

from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path

PANTHEON_ROOT = Path(__file__).resolve().parents[1]
if str(PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(PANTHEON_ROOT))

from lib.person_roots.admin_status import build_status, render_status_text  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Print Person Roots admin status.')
    parser.add_argument(
        '--root',
        default=os.environ.get('PERSON_ROOTS_ROOT', str(Path.home() / '.pantheon' / 'person-roots' / 'relationships')),
        help='Path to the Person Roots relationship tree.',
    )
    parser.add_argument('--format', choices=['json', 'text'], default='json')
    parser.add_argument('--pending-limit', type=int, default=20)
    args = parser.parse_args(argv)
    status = build_status(args.root, pending_limit=args.pending_limit)
    if args.format == 'json':
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(render_status_text(status))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
