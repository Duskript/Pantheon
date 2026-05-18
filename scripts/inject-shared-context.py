#!/usr/bin/env python3
"""Shared context injection — regenerates CONTEXT_{user_id}.md per user.

Runs every 15 minutes via cron. For each user who has a decisions/
subdirectory under ~/pantheon/shared/decisions/{user_id}/, picks recent
high-priority decisions and generates a budget-aware summary for
injection into that user's agent system prompts.

Multi-user ready: iterates all user subdirs in decisions/.
Single-user today (user=konan) — just works.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SHARED_DIR = Path.home() / "pantheon" / "shared"
DECISIONS_ROOT = SHARED_DIR / "decisions"

MODEL_WINDOWS = {
    "deepseek": 1_000_000, "gemini": 2_000_000,
    "claude": 200_000, "llama": 128_000, "qwen": 128_000,
    "mistral": 128_000, "phi": 16_000, "tinyllama": 16_000,
}

DEFAULT_WINDOW = 128_000
BUDGET_FRACTION = 0.03
SMALL_BUDGET_FRACTION = 0.01


def load_decisions(decisions_dir: Path):
    decisions = []
    for fpath in sorted(decisions_dir.glob("*.md"), reverse=True)[:100]:
        try:
            text = fpath.read_text()
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            fm = {}
            for line in parts[1].strip().split("\n"):
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip().strip('"')
                if k == "priority":
                    try:
                        fm["priority"] = int(v)
                    except ValueError:
                        fm["priority"] = 3
                elif k in ("domain", "summary", "date", "user_id"):
                    fm[k] = v
            fm.setdefault("priority", 3)
            fm.setdefault("domain", "general")
            fm.setdefault("summary", "")
            fm.setdefault("date", "")
            decisions.append(fm)
        except OSError:
            continue
    return decisions


def estimate_window(model=""):
    ml = model.lower()
    for key in sorted(MODEL_WINDOWS, key=len, reverse=True):
        if key in ml:
            return MODEL_WINDOWS[key]
    return DEFAULT_WINDOW


def generate_for_user(user_id: str) -> int:
    """Generate CONTEXT_{user_id}.md for a single user. Returns number of decisions injected."""
    decisions_dir = DECISIONS_ROOT / user_id
    output_path = SHARED_DIR / f"CONTEXT_{user_id}.md"

    if not decisions_dir.exists():
        print(f"  [skip] No decisions dir for user '{user_id}': {decisions_dir}")
        return 0

    decisions = load_decisions(decisions_dir)
    if not decisions:
        print(f"  [skip] No decisions for user '{user_id}'")
        return 0

    ctx = estimate_window(os.environ.get("HERMES_MODEL", ""))
    budget = int(ctx * BUDGET_FRACTION)

    # Sort by priority desc, then date desc
    decisions.sort(key=lambda d: (-d.get("priority", 0), d.get("date", "")))

    lines = []
    used = 80  # header overhead
    if budget < 200:
        # Compressed summary for tiny-budget models
        top = [d.get("summary", "") for d in decisions[:3] if d.get("summary")]
        combined = " | ".join(top)
        max_chars = max(budget * 4 - 20, 20)
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "..."
        lines = [
            "## Recent Decisions\n",
            f"_Budget summary (ctx: {ctx:,}t)_\n",
            combined + "\n",
        ]
    else:
        lines.append("## Recent Decisions\n")
        for d in decisions:
            s = d.get("summary", "")
            if not s:
                continue
            est = len(s) // 4 + 30
            if used + est > budget:
                break
            icon = {9: "🔴", 7: "🟠", 5: "🟡"}.get(d.get("priority", 0), "⚪")
            dt = d.get("date", "")[:10]
            lines.append(f"- {icon} **{s}**" + (f" — _{dt}_" if dt else "") + "\n")
            used += est

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines))
    count = sum(1 for l in lines if l.startswith("- "))
    print(f"  ✓ Wrote {count} decisions → {output_path.name} ({ctx:,} ctx, {budget:,}t budget)")
    return count


def generate() -> int:
    if not DECISIONS_ROOT.exists():
        print(f"No decisions root: {DECISIONS_ROOT}")
        return 0

    # Discover all user subdirectories
    user_dirs = sorted(
        d.name for d in DECISIONS_ROOT.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )

    if not user_dirs:
        print(f"No user directories found under {DECISIONS_ROOT}")
        return 0

    print(f"Generating per-user CONTEXT for: {', '.join(user_dirs)}")
    total = 0
    for uid in user_dirs:
        total += generate_for_user(uid)

    return total


if __name__ == "__main__":
    sys.exit(0 if generate() else 1)
