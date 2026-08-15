#!/usr/bin/env python3
"""Validate all workflows in a directory against the sovereign-outbound contract.

Usage:
    python3 scripts/validate-workflows.py [workflows_dir]

Default workflows_dir: ~/pantheon/conductor/workflows

Exit codes:
    0 = all workflows valid
    1 = at least one workflow has violations (printed to stderr)
    2 = invalid usage / fatal error (missing dir)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the conductor package is importable from the project root.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from conductor.v2.workflow_validator import validate_workflow_dir


def main() -> int:
    workflows_dir = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else Path.home() / "pantheon" / "conductor" / "workflows"
    )
    if not workflows_dir.is_dir():
        print(f"ERROR: {workflows_dir} is not a directory", file=sys.stderr)
        return 2

    results = validate_workflow_dir(workflows_dir)
    if not results:
        print(
            f"OK: all workflows in {workflows_dir} pass sovereign-outbound validation"
        )
        return 0

    print(
        f"FAIL: {len(results)} workflow(s) have violations:", file=sys.stderr
    )
    for path, violations in results.items():
        print(f"\n  {path}:", file=sys.stderr)
        for v in violations:
            print(f"    - {v}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
