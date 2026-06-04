#!/usr/bin/env python3
"""consolidate.py — backwards-compat shim for the Hades Nightly cron.

The Hades Nightly cron at 9am (job `cfb065b056ac`) has its prompt
hardcoded to call `python3 consolidate.py`. The original
consolidate.py was removed in some earlier cleanup; this file is a
replacement that delegates to the modern `scripts/hades` shim so
tonight's 9am run doesn't fail at step 1.

Brittleness fix #1 (2026-06-03): the cron prompt references a
non-existent file (`consolidate.py` was deleted, the live entry point
is `scripts/hades` via the package refactor). This shim gives the
cron something to call without forcing a cron-prompt rewrite.

If you're editing the cron prompt, you can replace the
`python3 consolidate.py` line with `python3 scripts/hades` and
delete this file. Until then, this shim keeps the existing prompt
working.

For modern callers, prefer the explicit flags:
    python3 scripts/hades --health
    python3 scripts/hades --distill
    python3 scripts/hades --archive
    python3 scripts/hades                  # full sweep
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Resolve scripts/hades relative to this file
HERE = Path(__file__).resolve().parent
SHIM = HERE / "scripts" / "hades"


def _venv_python() -> str:
    """Path to the hermes-agent venv python (has chromadb installed).

    The nightly Hades cron calls `python3 consolidate.py` from the
    cron subshell, which resolves `python3` to /usr/bin/python3
    (system Python, no third-party packages). The embed phase then
    fails silently with `ModuleNotFoundError: No module named
    'chromadb'`, the orchestrator catches the exception, and the
    9:15am notif rubber-stamps success. Self-heal by re-execing
    under the venv interpreter that has chromadb available.
    """
    venv = Path("/home/konan/.hermes/hermes-agent/venv/bin/python3")
    if venv.is_file():
        return str(venv)
    return sys.executable


def _has_chromadb() -> bool:
    """Best-effort check that the current interpreter can import chromadb.

    Returns True if importable, False otherwise. Used to decide
    whether to re-exec under the venv python.
    """
    try:
        import chromadb  # noqa: F401
        return True
    except Exception:
        return False


def main() -> int:
    if not SHIM.exists():
        print(f"ERROR: {SHIM} not found — was the package refactored?", file=sys.stderr)
        return 1

    # Self-heal: if the current interpreter can't import chromadb,
    # re-exec under the hermes-agent venv python. The nightly cron
    # resolves bare `python3` to /usr/bin/python3, which lacks
    # chromadb. The venv at ~/.hermes/hermes-agent/venv has it.
    interpreter = sys.executable
    if not _has_chromadb():
        venv_py = _venv_python()
        if venv_py != sys.executable and Path(venv_py).is_file():
            print(
                f"[consolidate.py] chromadb not importable in "
                f"{sys.executable}; re-execing under {venv_py}",
                file=sys.stderr,
            )
            cmd = [venv_py, str(Path(__file__).resolve())] + sys.argv[1:]
            return subprocess.run(cmd).returncode

    # Default behavior: full sweep. If the cron ever needs
    # granular control, pass flags through.
    cmd = [interpreter, str(SHIM)]

    # Pass through any flags the caller provided
    cmd.extend(sys.argv[1:])

    # Default a 25-minute hard timeout. Cron jobs shouldn't take
    # longer than that; if they do, we want to know.
    env = os.environ.copy()
    if "--timeout" not in sys.argv:
        cmd.extend(["--timeout", "1500"])

    # Delegation log goes to stderr so --json consumers can pipe stdout
    print(f"[consolidate.py] Delegating to: {' '.join(cmd)}", file=sys.stderr)
    result = subprocess.run(cmd, env=env)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
