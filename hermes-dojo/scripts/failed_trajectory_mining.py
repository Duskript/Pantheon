#!/usr/bin/env python3
"""Failed Trajectory Mining — find the most common failure modes each week."""

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

FAILURE_EVENT_TYPES = ("blocker", "correction")
FAILURE_KEYWORDS = (
    "error:", "traceback", "failed", "timeout", "retry",
    "exception", "moduleNotFoundError", "importError",
    "operation timed out", "connection refused",
    "permission denied", "no such file",
    "could not", "unable to", "cannot",
)

MIN_OCCURRENCES: int = 2
MAX_PATTERNS: int = 5


def _failure_signature(subject: str, raw_text: str) -> str:
    text = f"{subject} {raw_text}".lower()
    for kw in FAILURE_KEYWORDS:
        if kw in text:
            return kw
    words = [w for w in subject.lower().split() if len(w) > 2]
    return words[0] if words else "unknown"


def find_failure_patterns(
    db_path: str | None = None,
    days: int = 7,
    reference_now: datetime | None = None,
) -> Dict[str, Any]:
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

    text_matches: List[Dict[str, Any]] = []
    for row in rows:
        raw = (row["raw_text"] or "").lower()
        if any(kw in raw for kw in FAILURE_KEYWORDS):
            text_matches.append(dict(row))

    if not text_matches:
        return {"patterns": [], "total_events_scanned": len(rows)}

    by_sig: Dict[str, List[Dict]] = defaultdict(list)
    for ev in text_matches:
        sig = _failure_signature(
            ev.get("subject", ""),
            ev.get("raw_text", ""),
        )
        by_sig[sig].append(ev)

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
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "signature": pattern.get("signature", ""),
        "occurrences": pattern.get("occurrences", 0),
    }
    FAILURE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(FAILURE_LOG, "a") as fh:
        fh.write(json.dumps(entry) + "\n")


def create_prevention_skill(
    pattern: Dict[str, Any],
    action: str = "logged",
) -> None:
    """Create a prevention skill based on a failure pattern."""
    signature = pattern["signature"]
    occurrences = pattern["occurrences"]
    god_dist = pattern["god_distribution"]
    event_types = pattern["event_types"]
    
    # Analyze what caused the recurrence
    recurrence_reason = ""
    guard_condition = ""
    resolution_step = ""
    
    # Check each event_type to find common prevention issues
    for et in event_types:
        for god_name, count in god_dist.items():
            # If default god failed often, check if there's a general config issue
            # If specific god failed, check that god's specific code
            if count >= occurrences / len(event_types) and et == "blocker":
                recurrence_reason = f"Default god ({god_name}) failed {occurrences} times"
                if "timeout" in et:
                    guard_condition = "Subprocess timeout handling - check process timeout limits"
                    resolution_step = "Increase subprocess timeout or add signal handler for SIGTERM"
                elif "permission" in et:
                    guard_condition = "File/permission check - ensure proper access rights"
                    resolution_step = "Fix file permissions or use os.chmod() for directory access"
                else:
                    guard_condition = "Resource access - verify file/directory existence before operations"
                    resolution_step = "Check file permissions and use exist() before open() or read()"
            elif et in ["timeout", "connection refused"]:
                recurrence_reason = f"{god_name} failed {count} times - likely resource exhaustion"
                guard_condition = "Connection/resource check - verify timeout settings before long operations"
                resolution_step = "Reduce timeout values or add connection retry logic with exponential backoff"
    
    # Build skill description
    trigger = f"Pattern signature '{signature}' failed {occurrences} times across event type(s): {', '.join(event_types)}"
    
    skill = {
        "trigger_condition": trigger,
        "guard_condition": guard_condition,
        "resolution_step": resolution_step,
        "prevention_strategy": "implement_guard"
    }
    
    # Log the skill
    log_pattern(skill, "created")
    
    # Save to file
    skill_file = DOJO_DIR / f"skills_{signature}.py"
    with open(skill_file, "w") as fh:
        fh.write(json.dumps(skill, indent=2))
    
    # Print summary
    print(f"\nPrevention skill created:")
    print(f"  Signature: {signature}")
    print(f"  Occurrences: {occurrences}")
    print(f"  Trigger: {trigger}")
    print(f"  Guard: {guard_condition}")
    print(f"  Resolution: {resolution_step}")
    print(f"  File: {skill_file}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Failed Trajectory Mining")
    ap.add_argument("--days", type=int, default=7, help="Look-back window (default: 7)")
    ap.add_argument("--db", default=str(ICHOR_DB), help="Path to ichor.db")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of text")
    ap.add_argument("--create-skill", action="store_true", help="Create prevention skills for patterns")
    args = ap.parse_args()

    result = find_failure_patterns(db_path=args.db, days=args.days)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
        # Extract PATTERN_DICT for use by log_pattern
        PATTERN_DICT = {
            p["signature"]: {"occurrences": p["occurrences"], "god_distribution": p["god_distribution"], "event_types": p["event_types"]}
            for p in result["patterns"]
        }
        return
    else:
        scanned = result.get("total_events_scanned", 0)
        print(f"Scanned {scanned} events, found {len(result.get('patterns', []))} failure pattern(s):")
        for p in result.get("patterns", []):
            print(f"PATTERN: {p['signature']} ({p['occurrences']} occurrences)")
            print(f"  Gods: {p['god_distribution']}")
            print(f"  Types: {p['event_types']}")
            print(f"  Sample: {p['sample_raw'][:150]}")
            print()


if __name__ == "__main__":
    main()
