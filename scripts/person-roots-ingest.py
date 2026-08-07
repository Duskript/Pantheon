#!/usr/bin/env python3
"""Deterministic CLI for Person Roots structured candidate ingestion.

Reads structured candidate facts (JSON list or JSONL) and emits a JSON result
with the ingest plan and, when requested, the guarded apply result. No LLM
extraction happens here: candidates must already be structured objects with
``candidate_name``, ``field``, ``value``, ``source_person_id`` and
``source_type`` (plus optional ``sensitivity``, ``observed_context`` and
``provenance``).

Examples:
    python3 scripts/person-roots-ingest.py --input candidates.jsonl --root /path/to/relationships --dry-run
    python3 scripts/person-roots-ingest.py --input candidates.jsonl --root /path/to/relationships --apply

Output JSON to stdout:
    {"plan": {...}, "apply_result": {... or null}}

``--dry-run`` produces a plan and a dry-run apply result (nothing mutated).
``--apply`` applies allow-classified updates only.
With neither flag, only the plan is produced.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make ``lib`` importable when the script is run directly from the repo
# (``python3 scripts/person-roots-ingest.py``) rather than via ``-m``.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.person_roots.apply import ingest_and_apply  # noqa: E402
from lib.person_roots.ingest import build_ingest_plan  # noqa: E402
from lib.person_roots.resolver import DEFAULT_ROOT  # noqa: E402


def _load_candidates(input_path: str) -> list[dict]:
    """Load a JSON list or JSONL file of candidate objects."""

    text = Path(input_path).read_text(encoding='utf-8')
    stripped = text.strip()
    if not stripped:
        return []

    if stripped.startswith('['):
        data = json.loads(stripped)
        if not isinstance(data, list):
            raise ValueError('JSON input must be a list of candidate objects')
        return data

    candidates: list[dict] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            candidates.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f'Invalid JSON on line {line_number}: {exc}') from exc
    return candidates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Plan and apply structured Person Roots candidate facts (no LLM extraction).'
    )
    parser.add_argument(
        '--input',
        required=True,
        help='Path to a JSON list or JSONL file of candidate fact objects.',
    )
    parser.add_argument(
        '--root',
        default=str(DEFAULT_ROOT),
        help='Path to the Person Roots relationships root.',
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        '--dry-run',
        action='store_true',
        help='Build the plan and report would-apply rows without writing anything.',
    )
    mode.add_argument(
        '--apply',
        action='store_true',
        help='Apply allow-classified updates to existing person roots.',
    )
    args = parser.parse_args(argv)

    try:
        candidates = _load_candidates(args.input)
    except (OSError, ValueError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1

    if args.apply:
        result = ingest_and_apply(candidates, root=args.root, dry_run=False)
    elif args.dry_run:
        result = ingest_and_apply(candidates, root=args.root, dry_run=True)
    else:
        result = {
            'plan': build_ingest_plan(candidates, root=args.root),
            'apply_result': None,
        }

    json.dump(result, sys.stdout, indent=2, default=str)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
