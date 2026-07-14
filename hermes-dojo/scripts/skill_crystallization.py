#!/usr/bin/env python3
"""Skill Crystallization — find candidates for skill creation from Ichor events.

Scans ``ichor_events`` for high-importance insights, completed tasks, and
complex multi-step workflows from the last 24 hours. Outputs candidate
lines that the hourly agent cron reads and decides which to crystallize
into reusable skills.

Run by the Hermes Dojo hourly cron. Output goes to stdout for the agent.

Usage:
    python3 hermes-dojo/scripts/skill_crystallization.py
    python3 hermes-dojo/scripts/skill_crystallization.py --days 3
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

HERMES_HOME = Path.home() / ".hermes"
ICHOR_DB = HERMES_HOME / "ichor.db"
DOJO_DIR = Path.home() / "pantheon" / "hermes-dojo"
CRYSTALLIZATION_LOG = DOJO_DIR / "logs" / "crystallizations.jsonl"

# Event types that signal a completed task worth crystallizing.
TASK_COMPLETION_TYPES = ("insight", "decision", "commitment", "follow_up")

# Subject prefixes that indicate test data injected by the test suite.
# These entries pollute the production ichor.db and must be excluded
# from crystallization candidates. Source: pr35-gitworktree
# tests/test_ichor_c1_outcome_and_contradiction.py
EXCLUDED_SUBJECT_PREFIXES = ("test_", "c1_test_")

# Minimum importance for a candidate event.
MIN_IMPORTANCE: float = 40.0

# How many candidates to surface per run.
MAX_CANDIDATES: int = 10


def find_candidates(
    db_path: str | None = None,
    days: int = 1,
    reference_now: datetime | None = None,
) -> List[Dict[str, Any]]:
    """Find high-signal events suitable for skill crystallization.

    Args:
        db_path: Path to ichor.db (default: ~/.hermes/ichor.db).
        days: Look-back window in days.
        reference_now: Override "now" for deterministic testing.

    Returns:
        List of candidate dicts with keys: id, subject, god_name,
        event_type, importance, raw_text, created_at.
    """
    path = Path(db_path or ICHOR_DB)
    if not path.exists():
        return []

    now = reference_now or datetime.now(timezone.utc)
    # DB stores created_at as 'YYYY-MM-DD HH:MM:SS' with space separator (no timezone).
    # isoformat() produces 'YYYY-MM-DDTHH:MM:SS+tz' which breaks SQLite string comparison
    # because 'T' (ASCII 84) > ' ' (ASCII 32). Match the DB format exactly.
    cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    type_placeholders = ", ".join("?" for _ in TASK_COMPLETION_TYPES)
    rows = conn.execute(
        f"SELECT id, subject, raw_text, god_name, event_type, importance, created_at "
        f"FROM ichor_events "
        f"WHERE event_type IN ({type_placeholders}) "
        f"  AND importance >= ? "
        f"  AND created_at >= ? "
        f"  AND NOT (god_name = 'default' AND ("
        f"       subject LIKE 'test_%' "
        f"    OR subject LIKE 'c1_test_%'"
        f"  )) "
        f"ORDER BY importance DESC, created_at DESC "
        f"LIMIT ?",
        (*TASK_COMPLETION_TYPES, MIN_IMPORTANCE, cutoff, MAX_CANDIDATES * 3),
    ).fetchall()
    conn.close()

    candidates: List[Dict[str, Any]] = []
    for row in rows:
        raw = (row["raw_text"] or "")[:300].replace("\n", " ")
        candidates.append({
            "id": row["id"],
            "subject": row["subject"] or "",
            "god_name": row["god_name"] or "unknown",
            "event_type": row["event_type"],
            "importance": round(row["importance"] or 0, 1),
            "raw_text": raw,
            "created_at": row["created_at"] or "",
        })

    # Deduplicate by subject prefix to avoid near-duplicates
    seen_subjects: set = set()
    unique: List[Dict[str, Any]] = []
    for c in candidates:
        prefix = c["subject"][:60].lower().strip()
        if prefix and prefix not in seen_subjects:
            seen_subjects.add(prefix)
            unique.append(c)
            if len(unique) >= MAX_CANDIDATES:
                break

    return unique


def log_crystallization(
    candidate_id: int,
    skill_name: str,
    skill_path: str,
    god_name: str = "",
) -> None:
    """Append a crystallization event to the log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "candidate_id": candidate_id,
        "god_name": god_name,
        "skill_name": skill_name,
        "skill_path": skill_path,
    }
    CRYSTALLIZATION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(CRYSTALLIZATION_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Skill Crystallization Candidate Finder")
    ap.add_argument("--days", type=int, default=1, help="Look-back window (default: 1)")
    ap.add_argument("--db", default=str(ICHOR_DB), help="Path to ichor.db")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = ap.parse_args()

    candidates = find_candidates(db_path=args.db, days=args.days)

    if args.json:
        print(json.dumps(candidates, indent=2, default=str))
        return

    if not candidates:
        print("No crystallization candidates found.")
        return

    print(f"Found {len(candidates)} crystallization candidate(s):\n")
    for c in candidates:
        print(
            f"CANDIDATE id={c['id']} | {c['god_name']} | "
            f"{c['event_type']} (imp={c['importance']}) | "
            f"{c['subject'][:60]}"
        )
        if c["raw_text"]:
            print(f"  → {c['raw_text'][:120]}")
        print()


if __name__ == "__main__":
    main()
