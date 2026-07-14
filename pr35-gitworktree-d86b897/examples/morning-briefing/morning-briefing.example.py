#!/usr/bin/env python3
"""
Pantheon Morning Briefing — EXAMPLE script.
=============================================
Collects structured data for the Hermes cron agent to compose into
a morning briefing.  This is a *template* — copy it to
~/.hermes/scripts/morning-briefing.py and customize by setting env vars.

Environment variables (all optional, with sensible defaults):
  PANTHEON_DIR          — root of your Pantheon checkout   ($HOME/pantheon)
  ATHENAEUM_DIR         — root of your Athenaeum           ($HOME/athenaeum)
  HERMES_HOME           — Hermes config root               ($HOME/.hermes)
  PROJECT_IDEAS_FILE    — path to project-ideas.md         (PANTHEON_DIR/project-ideas.md)

Add/remove data collectors below by editing the COLLECTORS dict.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone, timedelta, date

# ── Configuration ───────────────────────────────────────────────────────────
PANTHEON_DIR = os.environ.get("PANTHEON_DIR", os.path.expanduser("~/pantheon"))
ATHENAEUM_DIR = os.environ.get("ATHENAEUM_DIR", os.path.expanduser("~/athenaeum"))
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
PROJECT_IDEAS = os.environ.get("PROJECT_IDEAS_FILE",
                               os.path.join(PANTHEON_DIR, "project-ideas.md"))


# ── Helpers ─────────────────────────────────────────────────────────────────

def _sh(cmd: str, timeout: int = 15) -> str:
    """Run a shell command and return stdout, or an error message."""
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=timeout)
        out = r.stdout.strip()
        return out if out else (f"[exit {r.returncode}]" if r.returncode else "")
    except FileNotFoundError:
        return "[command not found]"
    except subprocess.TimeoutExpired:
        return "[timed out]"


def _read(path: str) -> str:
    """Read a file if it exists, else return empty."""
    try:
        with open(path) as f:
            return f.read().strip()
    except (FileNotFoundError, PermissionError, IsADirectoryError):
        return ""


# ── Data Collectors ─────────────────────────────────────────────────────────
# Each entry is (section_header, callable) — the callable returns text.
# Order determines output order.  Add or remove entries to customize.

COLLECTORS: list[tuple[str, str]] = [
    ("TIMESTAMP", "collect_timestamp"),
    ("HADES_REPORT", "collect_hades"),
    ("ATHENAEUM_TRIAGE", "collect_triage"),
    ("PROJECT_IDEAS", "collect_project_ideas"),
    ("HERMES_UPDATE", "collect_update_check"),
    ("GIT_STATUS", "collect_git_status"),
]


def collect_timestamp() -> str:
    now = datetime.now(timezone.utc)
    local = now + timedelta(hours=_local_utc_offset())
    lines = [
        f"UTC:  {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"Local: {local.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Unix: {int(now.timestamp())}",
    ]
    return "\n".join(lines)


def _local_utc_offset() -> int:
    """Guess UTC offset (dumb heuristic: prefer America/Denver)."""
    import time
    return -1 * time.timezone // 3600 if time.timezone else -6


def collect_hades() -> str:
    today = date.today().isoformat()
    report = os.path.join(
        ATHENAEUM_DIR, "Codex-Pantheon", "reports", f"hades-{today}.md"
    )
    content = _read(report)
    if not content:
        return "[No Hades report for today yet — nightly consolidation may not have run]"
    # Condense: return first 50 lines or key sections
    lines = content.splitlines()
    key_lines = [l for l in lines if any(
        tag in l for tag in ("❌", "⚠️", "✅", "## ", "Sessions compiled",
                             "Articles created", "Distilled files",
                             "STATUS", "Codex-")
    )]
    return "\n".join(key_lines[:40]) if key_lines else lines[0]


def collect_triage() -> str:
    script = os.path.join(ATHENAEUM_DIR, "scripts", "athenaeum-triage.py")
    if not os.path.exists(script):
        return "[athenaeum-triage.py not found — skipping]"
    return _sh(f"python3 {script}", timeout=30)


def collect_project_ideas() -> str:
    content = _read(PROJECT_IDEAS)
    if not content:
        return "[No project ideas file — skipping]"
    return content


def collect_update_check() -> str:
    current = _sh("hermes --version 2>/dev/null || echo 'unknown'")
    return f"Hermes version: {current}"


def collect_git_status() -> str:
    repos = [PANTHEON_DIR, ATHENAEUM_DIR]
    results = []
    for repo in repos:
        if os.path.isdir(os.path.join(repo, ".git")):
            status = _sh(f"cd {repo} && git status --short")
            if status:
                branch = _sh(f"cd {repo} && git branch --show-current")
                results.append(f"[{os.path.basename(repo)}] ({branch}):\n{status}")
            else:
                results.append(f"[{os.path.basename(repo)}] ✓ clean")
    return "\n".join(results) if results else "[No git repos found]"


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> None:
    for header, func_name in COLLECTORS:
        func = globals().get(func_name)
        if func is None:
            print(f"=== {header} ===\n[collector '{func_name}' not found]")
            continue
        try:
            result = func()
        except Exception as e:
            result = f"[collector error: {e}]"
        print(f"=== {header} ===")
        if result:
            print(result)
        print()


if __name__ == "__main__":
    main()
