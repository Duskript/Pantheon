#!/usr/bin/env python3
"""Failed Trajectory Mining — find the most common failure modes each week.

Scans ``ichor_events`` for tool-call failures, timeouts, retries, and
error events from the last 7 days. Groups by failure signature and
surfaces the top patterns for the weekly agent cron to analyze.

Run weekly (Sunday 04:00). Output goes to stdout for the agent.

Usage:
    python3 hermes-dojo/scripts/failed_trajectory_mining.py
    python3 hermes-dojo/scripts/failed_trajectory_mining.py --days 7
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERMES_HOME = Path.home() / ".hermes"
ICHOR_DB = HERMES_HOME / "ichor.db"
DOJO_DIR = Path.home() / "pantheon" / "hermes-dojo"
FAILURE_LOG = DOJO_DIR / "logs" / "failure_patterns.jsonl"

# Event types that indicate failures or degraded outcomes.
FAILURE_EVENT_TYPES = ("blocker", "correction")

# Text patterns that signal a failure mode in raw_text.
FAILURE_KEYWORDS = (
    "error:", "traceback", "failed", "timeout", "retry",
    "exception", "moduleNotFoundError", "importError",
    "operation timed out", "connection refused",
    "permission denied", "no such file",
    "could not", "unable to", "cannot",
)

MIN_OCCURRENCES: int = 2  # minimum occurrences to surface as a pattern
MAX_PATTERNS: int = 5


def _failure_signature(subject: str, raw_text: str) -> str:
    """Extract a normalized failure signature from subject + raw_text."""
    text = f"{subject} {raw_text}".lower()
    for kw in FAILURE_KEYWORDS:
        if kw in text:
            return kw
    # Fallback: first meaningful word from subject
    words = [w for w in subject.lower().split() if len(w) > 2]
    return words[0] if words else "unknown"


def find_failure_patterns(
    db_path: str | None = None,
    days: int = 7,
    reference_now: datetime | None = None,
) -> Dict[str, Any]:
    """Scan ichor_events for recurring failure patterns.

    Args:
        db_path: Path to ichor.db (default: ~/.hermes/ichor.db).
        days: Look-back window in days.
        reference_now: Override "now" for deterministic testing.

    Returns:
        Dict with keys: patterns (list of pattern dicts), total_events_scanned.
    """
    path = Path(db_path or ICHOR_DB)
    if not path.exists():
        return {"patterns": [], "total_events_scanned": 0, "error": "db not found"}

    now = reference_now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    type_ph = ", ".join("?" for _ in FAILURE_EVENT_TYPES)
    rows = conn.execute(
        f"SELECT id, subject, raw_text, god_name, event_type, importance, created_at "
        f"FROM ichor_events "
        f"WHERE event_type IN ({type_ph}) "
        f"  AND created_at >= ? "
        f"ORDER BY created_at DESC "
        f"LIMIT 500",
        (*FAILURE_EVENT_TYPES, cutoff),
    ).fetchall()
    conn.close()

    # Also check for any events whose raw_text contains failure keywords
    text_matches: List[Dict[str, Any]] = []
    for row in rows:
        raw = (row["raw_text"] or "").lower()
        if any(kw in raw for kw in FAILURE_KEYWORDS):
            text_matches.append(dict(row))

    if not text_matches:
        return {"patterns": [], "total_events_scanned": len(rows)}

    # Group by failure signature
    by_sig: Dict[str, List[Dict]] = defaultdict(list)
    for ev in text_matches:
        sig = _failure_signature(
            ev.get("subject", ""),
            ev.get("raw_text", ""),
        )
        by_sig[sig].append(ev)

    # Build pattern summaries
    patterns: List[Dict[str, Any]] = []
    for sig, events in sorted(by_sig.items(), key=lambda x: -len(x[1])):
        if len(events) < MIN_OCCURRENCES:
            continue
        gods = Counter(e.get("god_name", "") for e in events)
        sample_raw = (events[0].get("raw_text") or "")[:200].replace("\n", " ")
        patterns.append({
            "signature": sig,
            "occurrences": len(events),
            "god_distribution": dict(gods.most_common(3)),
            "sample_id": events[0]["id"],
            "sample_raw": sample_raw,
            "event_types": list({e.get("event_type", "") for e in events}),
        })
        if len(patterns) >= MAX_PATTERNS:
            break

    return {"patterns": patterns, "total_events_scanned": len(rows)}


def log_pattern(pattern: Dict[str, Any], action: str = "analyzed") -> None:
    """Append to the failure pattern log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "signature": pattern.get("signature", ""),
        "occurrences": pattern.get("occurrences", 0),
    }
    FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FAILURE_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Failed Trajectory Mining")
    ap.add_argument("--days", type=int, default=7, help="Look-back window (default: 7)")
    ap.add_argument("--db", default=str(ICHOR_DB), help="Path to ichor.db")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = ap.parse_args()

    result = find_failure_patterns(db_path=args.db, days=args.days)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return

    patterns = result.get("patterns", [])
    scanned = result.get("total_events_scanned", 0)
    print(f"Scanned {scanned} events, found {len(patterns)} failure pattern(s):\n")

    if not patterns:
        print("No recurring failure patterns detected.")
        return

    for p in patterns:
        print(
            f"PATTERN: {p['signature']} ({p['occurrences']} occurrences)"
        )
        print(f"  Gods: {p['god_distribution']}")
        print(f"  Types: {p['event_types']}")
        print(f"  Sample: {p['sample_raw'][:150]}")
        print()


if __name__ == "__main__":
    main()
