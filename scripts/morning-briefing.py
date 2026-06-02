#!/usr/bin/env python3
"""
Pantheon Morning Briefing — portable data collector.

Collects system state for the Hermes cron agent to compose into a
daily briefing.  Uses environment variables for all paths so it works
on any machine without modification.

Environment variables (all optional):
  PANTHEON_DIR       — root of Pantheon checkout       (default: $HOME/pantheon)
  ATHENAEUM_DIR      — root of Athenaeum               (default: $HOME/athenaeum)
  HERMES_HOME        — Hermes config root               (default: $HOME/.hermes)
  PROJECT_IDEAS_FILE — path to project-ideas.md         (default: PANTHEON_DIR/project-ideas.md)
  UTC_OFFSET         — hours from UTC for local time    (default: -6 / America/Denver)

See examples/morning-briefing/ for setup docs.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path

# ── Config ───────────────────────────────────────────────────────────
PANTHEON_DIR = os.environ.get("PANTHEON_DIR", os.path.expanduser("~/pantheon"))
ATHENAEUM_DIR = os.environ.get("ATHENAEUM_DIR", os.path.expanduser("~/athenaeum"))
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
PROJECT_IDEAS = os.environ.get(
    "PROJECT_IDEAS_FILE",
    os.path.join(PANTHEON_DIR, "project-ideas.md"),
)
UTC_OFFSET = int(os.environ.get("UTC_OFFSET", "-6"))


def _sh(cmd: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip()
        return out if out else (f"[exit {r.returncode}]" if r.returncode else "")
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"[{e.__class__.__name__}]"


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return ""


# ── Collectors ───────────────────────────────────────────────────────

def collect_timestamp() -> str:
    now = datetime.now(timezone.utc)
    local = now + timedelta(hours=UTC_OFFSET)
    return (
        f"UTC:   {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
        f"Local: {local.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Unix:  {int(now.timestamp())}"
    )


def collect_hades() -> str:
    today = date.today().isoformat()
    report = os.path.join(ATHENAEUM_DIR, "Codex-Pantheon", "reports", f"hades-{today}.md")
    content = _read(report)
    if not content:
        return "[No Hades report for today — nightly consolidation may not have run]"
    lines = content.splitlines()
    key = [l for l in lines if any(
        t in l for t in ("❌", "⚠️", "✅", "## ", "Sessions compiled",
                         "Articles created", "Distilled", "STATUS", "Codex-")
    )]
    return "\n".join(key[:40]) if key else content[:2000]


def collect_triage() -> str:
    script = os.path.join(ATHENAEUM_DIR, "scripts", "athenaeum-triage.py")
    if not os.path.exists(script):
        return "[athenaeum-triage.py not found — skipping]"
    return _sh(f"python3 {script}", timeout=30)


def collect_dawn_patrol() -> str:
    """Read the most recent Thoth dawn patrol briefing."""
    patrol_dir = Path(ATHENAEUM_DIR) / "reports" / "dawn-patrol"
    if not patrol_dir.exists():
        return "[No dawn patrol directory — intelligence scan not yet set up]"
    files = sorted(patrol_dir.glob("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].md"), reverse=True)
    if not files:
        return "[No dawn patrol briefings found yet — first scan runs at midnight]"
    latest = files[0]
    content = latest.read_text().strip()
    if not content:
        return f"[Dawn patrol report {latest.name} is empty]"
    lines = content.splitlines()
    # Extract the key sections with headings — limit to ~3000 chars
    key_lines = [l for l in lines if l.startswith("## ") or l.startswith("### ") or 
                 any(t in l for t in ("HIGH", "MEDIUM", "LOW", "⚠️", "❌", "✅", "🔴"))]
    preview = "\n".join(key_lines[:30])
    if len(content) > 3000:
        preview += f"\n\n[... full report at {latest.name} — {len(content)} chars]"
    return preview or content[:3000]


def collect_project_ideas() -> str:
    c = _read(PROJECT_IDEAS)
    return c or "[No project ideas file — skipping]"


def collect_update_check() -> str:
    return f"Hermes: {_sh('hermes --version 2>/dev/null || echo unknown')}"


def collect_git_status() -> str:
    results = []
    for repo in [PANTHEON_DIR, ATHENAEUM_DIR]:
        git_dir = os.path.join(repo, ".git")
        if os.path.isdir(git_dir):
            status = _sh(f"cd {repo} && git status --short")
            branch = _sh(f"cd {repo} && git branch --show-current")
            label = os.path.basename(repo)
            if status:
                results.append(f"[{label}] ({branch}):\n{status}")
            else:
                results.append(f"[{label}] ✓ clean")
    return "\n".join(results) or "[No git repos found]"


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    collectors = [
        ("TIMESTAMP", collect_timestamp),
        ("HADES_REPORT", collect_hades),
        ("DAWN_PATROL", collect_dawn_patrol),
        ("ATHENAEUM_TRIAGE", collect_triage),
        ("PROJECT_IDEAS", collect_project_ideas),
        ("HERMES_UPDATE", collect_update_check),
        ("GIT_STATUS", collect_git_status),
    ]
    for header, fn in collectors:
        print(f"=== {header} ===")
        try:
            out = fn()
            if out:
                print(out)
        except Exception as e:
            print(f"[collector error: {e}]")
        print()


if __name__ == "__main__":
    main()
