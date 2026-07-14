#!/usr/bin/env python3
"""Inject active strategic goals into the system prompt preamble.

Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §A1.

This is a thin wrapper around `lib.ichor_goals.format_active_goals_preamble`.
It's called by session-start hooks (or directly by agents) to print the
markdown preamble that should be appended to the agent's system prompt.

Usage:
    python3 ~/pantheon/scripts/inject-goals.py              # default: max 5, min priority 3
    python3 ~/pantheon/scripts/inject-goals.py --max 3       # smaller
    python3 ~/pantheon/scripts/inject-goals.py --json        # JSON envelope (for MCP wrappers)

Exits with code 0 always — the absence of active goals is not an error;
the session-start hook can simply skip the injection block.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Ensure lib/ is on sys.path so we can import ichor_goals regardless of cwd
_THIS = Path(__file__).resolve()
_PANTHEON_ROOT = _THIS.parent.parent
sys.path.insert(0, str(_PANTHEON_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject active strategic goals into session-start preamble"
    )
    parser.add_argument("--max", type=int, default=5,
                        help="Max goals to inject (default 5)")
    parser.add_argument("--min-priority", type=int, default=3,
                        help="Min priority to include (default 3)")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON envelope instead of raw markdown")
    args = parser.parse_args()

    try:
        from lib.ichor_goals import format_active_goals_preamble
    except ImportError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": f"import failed: {exc}"}))
        else:
            print(f"# (goal injection unavailable: {exc})", file=sys.stderr)
        return 0  # never block session start

    md = format_active_goals_preamble(
        max_injected=args.max, min_priority=args.min_priority,
    )
    if args.json:
        print(json.dumps({
            "ok": True,
            "preamble": md,
            "injected": bool(md),
            "max_injected": args.max,
            "min_priority": args.min_priority,
        }, indent=2))
    else:
        if md:
            print(md, end="" if md.endswith("\n") else "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
