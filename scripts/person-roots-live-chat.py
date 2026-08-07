#!/usr/bin/env python3
"""Run the Person Roots active-chat wrapper on a structured candidate file.

This CLI is a local smoke/operator helper for the live-turn wrapper. It accepts a
JSON list or JSONL stream of CandidateFact objects, then reports whether Hermes
should call clarify, whether safe facts were applied, or whether review-class
items were intentionally not queued in the active chat path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PANTHEON_ROOT = Path(__file__).resolve().parents[1]
if str(PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(PANTHEON_ROOT))

from lib.person_roots.live_chat import (  # noqa: E402
    handle_live_chat_candidates,
    load_candidate_stream,
    render_live_chat_result,
)
from lib.person_roots.resolver import DEFAULT_ROOT  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Run Person Roots live-chat candidate wrapper.')
    parser.add_argument('candidate_file', help='JSON list or JSONL CandidateFact stream')
    parser.add_argument('--root', default=str(DEFAULT_ROOT))
    parser.add_argument('--no-apply-safe', action='store_true')
    parser.add_argument('--today', default=None)
    parser.add_argument('--json', action='store_true', dest='as_json')
    args = parser.parse_args(argv)

    candidates = load_candidate_stream(args.candidate_file)
    result = handle_live_chat_candidates(
        candidates,
        root=args.root,
        apply_safe=not args.no_apply_safe,
        today=args.today,
    )
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
    else:
        print(render_live_chat_result(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
