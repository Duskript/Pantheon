#!/usr/bin/env python3
"""Ichor Phase 4 — Overnight Forge Orchestrator.

Runs the full overnight maintenance pipeline:
  1. Ebbinghaus decay (02:30)
  2. Cold-storage eviction (02:45)
  3. Cross-session pattern scan (03:00)

Usage:
    python3 scripts/ichor_overnight_phase4.py              # dry-run all
    python3 scripts/ichor_overnight_phase4.py --apply      # apply all
    python3 scripts/ichor_overnight_phase4.py --decay-only
    python3 scripts/ichor_overnight_phase4.py --evict-only
    python3 scripts/ichor_overnight_phase4.py --forge-only
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("ichor_phase4")

PANTHEON_HOME = Path.home() / "pantheon"
DEFAULT_DB = Path.home() / ".hermes" / "ichor.db"

# Cross-session pattern scan — look for topics appearing in multiple
# sessions within the last FORGE_WINDOW_DAYS.
FORGE_WINDOW_DAYS: int = 1
FORGE_MIN_SESSIONS: int = 2  # topic must appear in ≥ N sessions
FORGE_MAX_PATTERNS: int = 5


def run_decay_step(db_path: str, dry_run: bool) -> Dict[str, Any]:
    from lib.ichor_decay import run_decay
    return run_decay(db_path, dry_run=dry_run)


def run_eviction_step(db_path: str, dry_run: bool) -> Dict[str, Any]:
    from lib.ichor_eviction import run_eviction
    return run_eviction(db_path, dry_run=dry_run)


def _normalize_topic(subject: str) -> str:
    """Normalize a subject into a topic key for grouping."""
    s = subject.lower().strip()
    # Drop common prefixes that vary but don't change the topic
    for prefix in ("hermes:", "hephaestus:", "thoth:", "marvin:", "iris:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    # Drop trailing numbers / timestamps
    while s and (s[-1].isdigit() or s[-1] in "-_"):
        s = s[:-1]
    return s.strip()[:80]


def run_forge_step(
    db_path: str, dry_run: bool = True, reference_now: datetime | None = None,
) -> Dict[str, Any]:
    """Cross-session pattern scan.

    Finds subject strings that appear in multiple distinct sessions
    within the forge window, groups them into patterns, and returns
    a digest of findings. In non-dry-run mode, writes digest_entry
    events for each pattern found.
    """
    path = Path(db_path)
    if not path.exists():
        return {"patterns_found": 0, "error": "db not found"}

    now = reference_now or datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=FORGE_WINDOW_DAYS)).isoformat()

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT subject, session_id, god_name, event_type, id "
            "FROM ichor_events "
            "WHERE created_at >= ? AND subject IS NOT NULL AND subject != '' "
            "ORDER BY created_at DESC",
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        return {"patterns_found": 0, "error": str(exc)}

    if not rows:
        conn.close()
        return {"patterns_found": 0, "reason": "no events in window"}

    # Group by normalized topic
    topic_sessions: Dict[str, set] = {}
    topic_events: Dict[str, List[Dict]] = {}
    for row in rows:
        topic = _normalize_topic(row["subject"])
        if not topic or len(topic) < 3:
            continue
        if topic not in topic_sessions:
            topic_sessions[topic] = set()
            topic_events[topic] = []
        topic_sessions[topic].add(row["session_id"] or "")
        if len(topic_events[topic]) < 20:
            topic_events[topic].append(dict(row))

    # Find topics appearing in multiple sessions
    patterns: List[Dict[str, Any]] = []
    for topic, sessions in topic_sessions.items():
        sessions.discard("")
        if len(sessions) < FORGE_MIN_SESSIONS:
            continue
        events = topic_events[topic]
        god_counts = Counter(e.get("god_name", "") for e in events)
        patterns.append({
            "topic": topic,
            "session_count": len(sessions),
            "event_count": len(events),
            "gods": dict(god_counts.most_common(5)),
            "representative_id": events[0]["id"] if events else None,
        })

    patterns.sort(key=lambda p: p["session_count"], reverse=True)
    patterns = patterns[:FORGE_MAX_PATTERNS]

    if dry_run:
        conn.close()
        return {"patterns_found": len(patterns), "patterns": patterns}

    # Write digest_entry for each pattern
    written = 0
    today = now.strftime("%Y%m%d")
    for i, pat in enumerate(patterns):
        god_list = ", ".join(
            f"{g} ({c})" for g, c in pat["gods"].items()
        )
        content = (
            f"Overnight Forge found cross-session pattern: **{pat['topic']}**. "
            f"Appeared in {pat['session_count']} sessions with "
            f"{pat['event_count']} events. Gods involved: {god_list}."
        )
        try:
            conn.execute(
                "INSERT INTO ichor_events "
                "(session_id, event_type, subject, predicate, object, confidence, "
                " source, raw_text, created_at, god_name, importance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"forge_{today}_{i}",
                    "digest_entry",
                    f"forge:{today}:{pat['topic'][:60]}",
                    "reports",
                    content[:500],
                    0.85,
                    "forge",
                    content,
                    now.isoformat(),
                    "subconscious",
                    50.0,
                ),
            )
            written += 1
        except Exception as exc:
            logger.warning("Forge write failed for topic %s: %s", pat["topic"], exc)

    if written:
        conn.commit()
    conn.close()
    return {"patterns_found": len(patterns), "patterns": patterns, "digests_written": written}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ichor Phase 4 Overnight Forge")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to ichor.db")
    ap.add_argument("--apply", action="store_true", help="Actually apply (default: dry-run)")
    ap.add_argument("--decay-only", action="store_true")
    ap.add_argument("--evict-only", action="store_true")
    ap.add_argument("--forge-only", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    dry_run = not args.apply
    run_all = not (args.decay_only or args.evict_only or args.forge_only)

    results: Dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat()}

    if run_all or args.decay_only:
        print("── Decay ──")
        r = run_decay_step(args.db, dry_run)
        results["decay"] = r
        print(f"  {r['decayed']} decayed, {r['skipped']} skipped")

    if run_all or args.evict_only:
        print("── Eviction ──")
        r = run_eviction_step(args.db, dry_run)
        results["eviction"] = r
        n = r.get("archived", 0)
        cand = len(r.get("candidates", []))
        print(f"  {n} archived, {cand} candidates")

    if run_all or args.forge_only:
        print("── Forge (cross-session patterns) ──")
        r = run_forge_step(args.db, dry_run)
        results["forge"] = r
        n = r.get("patterns_found", 0)
        print(f"  {n} patterns found")
        for p in r.get("patterns", [])[:3]:
            print(f"    • {p['topic'][:60]} — {p['session_count']} sessions, {p['event_count']} events")

    mode = "DRY-RUN" if dry_run else "APPLIED"
    print(f"\nPhase 4 {mode} complete.")
    results["dry_run"] = dry_run

    # Write result JSON for cron capture
    log_path = Path.home() / ".hermes" / "cron" / "output" / "ichor_phase4.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(results, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
