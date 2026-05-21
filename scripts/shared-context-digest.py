#!/usr/bin/env python3
"""Build a compact digest of recent Pantheon shared context.

Ran by cron every 2h. Writes ~/pantheon/shared/DIGEST.md.
Hermes Agent: check this file before starting significant builds.

Multi-user: iterates all user subdirs under decisions/{user_id}/ and
labels each decision with the originating user.

TODO: Disable this cron job when the auto-inject plugin is ready.
"""

import os
import re
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta

SHARED = Path.home() / "pantheon" / "shared"
DECISIONS_ROOT = SHARED / "decisions"
DIGEST_PATH = SHARED / "DIGEST.md"
CUTOFF_HOURS = 48  # Only include decisions/events from last 48h


def format_timestamp(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def heading(text: str, level: int = 2) -> str:
    return f"\n{'#' * level} {text}\n"


def collect_decisions_for_user(user_id: str) -> list[dict]:
    """Read decision files for a specific user from the last 48h."""
    cutoff = time.time() - CUTOFF_HOURS * 3600
    decisions = []
    dirpath = DECISIONS_ROOT / user_id
    if not dirpath.exists():
        return decisions
    for f in sorted(dirpath.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        mtime = f.stat().st_mtime
        if mtime < cutoff:
            continue
        content = f.read_text().strip()
        # Extract title (first # line or filename-based title)
        title_match = re.search(r"^#{1,3} (.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else f.name.replace(".md", "").replace("-", " ").title()
        # Extract first paragraph as summary
        paras = [p.strip() for p in content.split("\n\n") if p.strip()]
        summary = paras[1] if len(paras) > 1 else "(no detail captured)"
        decisions.append({
            "file": f.name,
            "title": title,
            "summary": summary[:300],
            "age": format_timestamp(mtime),
            "user": user_id,
        })
    return decisions


def collect_decisions() -> list[dict]:
    """Collect recent decisions across all users."""
    if not DECISIONS_ROOT.exists():
        return []
    all_decisions = []
    for child in sorted(DECISIONS_ROOT.iterdir()):
        if child.is_dir() and not child.name.startswith("."):
            all_decisions.extend(collect_decisions_for_user(child.name))
    return all_decisions


def collect_active() -> list[dict]:
    """Read active task files."""
    active = []
    dirpath = SHARED / "active"
    if not dirpath.exists():
        return active
    for f in sorted(dirpath.glob("*.md")):
        if f.name == "INDEX.md":
            continue
        content = f.read_text().strip()
        title_match = re.search(r"^# (.+)$", content, re.MULTILINE)
        title = title_match.group(1) if title_match else f.name.replace(".md", "")
        first_paras = content[:200].replace("\n", " ")[:200]
        active.append({
            "file": f.name,
            "title": title,
            "preview": first_paras,
        })
    return active


def read_athenaeum_writes() -> str | None:
    """Read the athenaeum-writes.md scratchpad."""
    path = SHARED / "athenaeum-writes.md"
    if path.exists():
        content = path.read_text().strip()
        return content[:500]
    return None


def build_digest() -> str:
    lines = []
    lines.append("# Pantheon Shared Context — Digest")
    lines.append(f"_Auto-generated {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    lines.append(f"_Shows decisions and tasks from the last {CUTOFF_HOURS}h_")
    lines.append("")

    # Decisions (grouped by user)
    decisions = collect_decisions()
    if decisions:
        lines.append(heading("Recent Decisions", 2))
        # Group by user
        from collections import OrderedDict
        by_user = OrderedDict()
        for d in decisions:
            uid = d.get("user", "unknown")
            if uid not in by_user:
                by_user[uid] = []
            by_user[uid].append(d)
        for user_id, user_decisions in by_user.items():
            lines.append(f"### 👤 User: {user_id}")
            for d in user_decisions:
                lines.append(f"- **{d['title']}** (`decisions/{user_id}/{d['file']}`)")
                lines.append(f"  - Age: {d['age']}")
                lines.append(f"  - Summary: {d['summary']}")
                lines.append("")
    else:
        lines.append(heading("Recent Decisions", 2))
        lines.append("_No decisions from the last 48h._")
        lines.append("")

    # Active tasks
    active = collect_active()
    if active:
        lines.append(heading("Active Tasks", 2))
        for a in active:
            lines.append(f"- **{a['title']}** (`active/{a['file']}`)")
            lines.append(f"  _{a['preview']}_")
            lines.append("")

    # Athenaeum writes
    writes = read_athenaeum_writes()
    if writes:
        lines.append(heading("Athenaeum Writes Scratchpad", 2))
        lines.append(f"_{writes}_")
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("_This digest auto-updates every 2h via cron. Disable digest cron when `context_dirs` plugin is active._")

    return "\n".join(lines)


if __name__ == "__main__":
    digest = build_digest()
    DIGEST_PATH.write_text(digest)
    print(f"Wrote digest → {DIGEST_PATH}")
