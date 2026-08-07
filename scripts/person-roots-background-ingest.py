#!/usr/bin/env python3
"""Cron-safe unattended ingest processor for Person Roots candidate files.

Reads JSON/JSONL candidate fact files dropped into ``--incoming``, builds an
ingest plan, auto-applies only safe ``allow`` facts, queues
clarifications/approvals/denials/apply-errors to ``<root>/_pending/PROPOSALS.jsonl``,
and archives processed inputs to ``<root>/_processed/``.

Cron-safe output rules:

- No work (or safe-only applies without ``--report-applies``) and no
  ``--json``: prints nothing, exit 0.
- Pending decisions or errors exist: prints a compact digest suitable for
  no-agent cron delivery ("Person Roots needs decisions: ...").
- ``--json``: prints the full serializable result.

Example:
    python3 scripts/person-roots-background-ingest.py \\
        --incoming ~/.pantheon/person-roots/relationships/_incoming \\
        --root ~/.pantheon/person-roots/relationships
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make ``lib`` importable when the script is run directly from the repo
# (``python3 scripts/person-roots-background-ingest.py``) rather than via ``-m``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.person_roots.resolver import DEFAULT_ROOT  # noqa: E402
from lib.person_roots.runtime import unattended_ingest_files  # noqa: E402


def _digest(result: dict[str, Any]) -> str:
    """Compact human-readable digest for pending decisions/errors."""

    breakdown = result.get('pending_breakdown') or {}
    pending_bits = ', '.join(
        f'{label}: {breakdown[label]}'
        for label in ('clarification', 'approval', 'denied', 'error')
        if breakdown.get(label, 0) > 0
    ) or 'none'
    error_count = int(result.get('apply_errors') or 0) + int(result.get('files_failed') or 0)
    lines = [
        f"Person Roots needs decisions: {result.get('pending_count', 0)} pending "
        f'({pending_bits}), {error_count} errors.',
        f"Pending queue: {result.get('pending_path')}",
    ]
    if result.get('files_processed'):
        lines.append(
            f"Processed {result['files_processed']} file(s), applied "
            f"{result.get('applied_count', 0)} fact(s), archived "
            f"{len(result.get('archived_paths') or [])} file(s)."
        )
    return '\n'.join(lines)


def _applied_digest(result: dict[str, Any]) -> str:
    """Compact digest for explicitly-reported safe-only applies."""

    return (
        f"Person Roots applied {result.get('applied_count', 0)} safe fact(s) from "
        f"{result.get('files_processed', 0)} file(s); archived "
        f"{len(result.get('archived_paths') or [])} file(s)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Cron-safe unattended Person Roots ingest processor (no LLM extraction).'
    )
    parser.add_argument(
        '--incoming',
        required=True,
        help='Directory containing JSON/JSONL candidate fact files.',
    )
    parser.add_argument(
        '--root',
        default=str(DEFAULT_ROOT),
        help='Path to the Person Roots relationships root.',
    )
    parser.add_argument(
        '--archive-dir',
        default=None,
        help='Archive directory (default: <root>/_processed).',
    )
    parser.add_argument(
        '--report-applies',
        action='store_true',
        help='Report safe-only applies; absent means safe-only applies are silent.',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Print the full JSON result even when there is no pending work.',
    )
    args = parser.parse_args(argv)

    result = unattended_ingest_files(
        args.incoming,
        root=args.root,
        archive_dir=args.archive_dir,
        report_applies=args.report_applies,
    )

    if args.json:
        json.dump(result, sys.stdout, indent=2, default=str)
        sys.stdout.write('\n')
        return 0

    has_pending = int(result.get('pending_count') or 0) > 0
    has_errors = bool(result.get('errors')) or int(result.get('apply_errors') or 0) > 0
    has_failed = int(result.get('files_failed') or 0) > 0

    if has_pending or has_errors or has_failed:
        print(_digest(result))
        return 0

    if int(result.get('applied_count') or 0) > 0 and args.report_applies:
        print(_applied_digest(result))
        return 0

    return 0


if __name__ == '__main__':
    sys.exit(main())
