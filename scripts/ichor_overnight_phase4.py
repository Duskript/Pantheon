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

    # Apply exactly one step, leaving the others report-only:
    python3 scripts/ichor_overnight_phase4.py --apply-step evict

WHY `--apply-step` EXISTS
    The cron job schema has a `script` field and NO args field, so this script
    is invoked with an empty argv by its wrapper -- and `dry_run = not
    args.apply` then made every archived run a dry run, forever. The wrapper
    ~/.hermes/scripts/ichor-phase4-evict-apply.py now passes
    `--apply-step evict`, which applies eviction while decay and forge keep
    reporting. Applying decay is deliberately NOT wired: it rewrites importance
    in place for ~39.8k rows with no backup column, which is not recoverable the
    way archive-then-delete is.
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

# The orchestrator is launched from ~/.hermes/scripts/ wrappers that set
# PYTHONPATH to the repo root; make a bare `python3 scripts/...` invocation work
# too, so the manual dry-run path and the cron path resolve identically.
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.ichor_temporal import normalize_timestamp  # noqa: E402

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
    # Both sides normalised: `created_at` holds four shapes and the raw column
    # only compares correctly to a same-shaped literal down to the DAY (see
    # lib/ichor_temporal.CREATED_AT_SHAPES). With a raw comparison, every
    # space-shaped event written after the boundary on the boundary day was
    # invisible to this window.
    cutoff = normalize_timestamp(now - timedelta(days=FORGE_WINDOW_DAYS))

    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT subject, session_id, god_name, event_type, id "
            "FROM ichor_events "
            "WHERE datetime(created_at) >= datetime(?) "
            "AND subject IS NOT NULL AND subject != '' "
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
    ap.add_argument("--apply-step", action="append", default=[], metavar="STEP",
                    choices=("decay", "evict", "forge"),
                    help="Apply ONLY this step (decay|evict|forge); repeatable. "
                         "Steps not named stay gated as dry-runs -- this is how "
                         "the nightly cron applies eviction while decay and forge "
                         "remain report-only.")
    ap.add_argument("--decay-only", action="store_true")
    ap.add_argument("--evict-only", action="store_true")
    ap.add_argument("--forge-only", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--result-json", default=str(
        Path.home() / ".hermes" / "cron" / "output" / "ichor_phase4.json"),
        help="Where to write the machine-readable run result (the cron capture "
             "file). Tests point this at a temp path so they never clobber the "
             "live artifact.")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
    )

    run_all = not (args.decay_only or args.evict_only or args.forge_only)

    # Per-step gating. `--apply` applies every step that runs; `--apply-step X`
    # applies exactly X and leaves the rest reporting. Keeping the mode per step
    # (rather than one global flag) is what lets the nightly job apply the
    # recoverable half -- eviction copies to cold storage before deleting --
    # while the irreversible half (decay rewrites importance in place) stays off.
    applied = set(args.apply_step or [])
    if args.apply:
        applied.update(("decay", "evict", "forge"))

    def step_dry_run(step: str) -> bool:
        return step not in applied

    def label(step: str) -> str:
        return "APPLIED" if step in applied else "dry-run"

    results: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": {},
    }

    if run_all or args.decay_only:
        print("── Decay ──")
        dry = step_dry_run("decay")
        r = run_decay_step(args.db, dry)
        results["decay"] = r
        results["steps"]["decay"] = label("decay")
        print(f"  {r['decayed']} decayed, {r['skipped']} skipped [{label('decay')}]")

    if run_all or args.evict_only:
        print("── Eviction ──")
        dry = step_dry_run("evict")
        r = run_eviction_step(args.db, dry)
        results["eviction"] = r
        results["steps"]["eviction"] = label("evict")
        n = r.get("archived", 0)
        cand = len(r.get("candidates", []))
        print(f"  {n} archived, {cand} candidates [{label('evict')}]")
        if not dry:
            print(f"  {r.get('tags_removed', 0)} tag rows deleted, "
                  f"{r.get('evidence_unlinked', 0)} evidence rows unlinked")

    if run_all or args.forge_only:
        print("── Forge (cross-session patterns) ──")
        dry = step_dry_run("forge")
        r = run_forge_step(args.db, dry)
        results["forge"] = r
        results["steps"]["forge"] = label("forge")
        n = r.get("patterns_found", 0)
        print(f"  {n} patterns found [{label('forge')}]")
        for p in r.get("patterns", [])[:3]:
            print(f"    • {p['topic'][:60]} — {p['session_count']} sessions, {p['event_count']} events")

    # The overall word stays first so the artifact is still greppable, and the
    # per-step modes follow: a run that applied eviction must not read as a
    # dry-run, and a run that applied nothing must not read as APPLIED.
    overall = "APPLIED" if applied else "DRY-RUN"
    modes = " ".join(
        f"{step}={'APPLIED' if mode == 'APPLIED' else 'dry-run'}"
        for step, mode in results["steps"].items()
    )
    print(f"\nPhase 4 {overall} complete — {modes}")
    results["dry_run"] = not applied
    results["applied_steps"] = sorted(applied)

    # Write result JSON for cron capture
    log_path = Path(args.result_json)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(results, indent=2, default=str) + "\n")


if __name__ == "__main__":
    main()
