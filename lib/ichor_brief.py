"""Ichor Brief — Query-less Recall Engine for Pantheon Gods.

The Ichor Brief gives every god instant context: "what should I know right now?"
No search query needed — the engine scores every stored event by a weighted
formula of priority, freshness, confidence, and repetition, then returns the
top-ranked items as a structured, scannable brief.

Scoring formula:
    score = confidence × 0.35 + freshness × 0.30 + type_priority × 0.25 + repetition × 0.10

Where:
    - confidence  (0.0-1.0) — Tier A extraction confidence
    - freshness   (0.0-1.0) — decays linearly from 1.0 (now) to 0.0 (7+ days old)
    - priority    (0.0-1.0) — blocker(1.0) > commitment(0.85) > decision(0.75) > ...
    - repetition  (0.0-1.0) — mentioned multiple times in conversation (signal)

Usage:
    from lib.ichor_brief import build_brief
    brief = build_brief(god_name="hermes", limit=10)

CLI:
    python3 ~/pantheon/lib/ichor_brief.py --god hermes [--limit 10] [--min-score 0.3] [--json]
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("ichor_brief")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_HOME = Path.home()
_PANTHEON_LIB = _HOME / "pantheon" / "lib"
_ICHOR_DB_PATH = _HOME / ".hermes" / "ichor.db"

# Priority score per event type (higher = more important to surface)
TYPE_PRIORITY: Dict[str, float] = {
    "blocker": 1.00,
    "commitment": 0.85,
    "decision": 0.75,
    "follow_up": 0.70,
    "correction": 0.65,
    "insight": 0.60,
    "fact": 0.50,
    "preference": 0.45,
    "reference": 0.40,
}

# Display labels and icons
TYPE_META: Dict[str, Dict[str, str]] = {
    "blocker": {"icon": "🚧", "label": "Blocker"},
    "commitment": {"icon": "📋", "label": "Commitment"},
    "decision": {"icon": "🎯", "label": "Decision"},
    "follow_up": {"icon": "🔁", "label": "Follow-up"},
    "correction": {"icon": "🔧", "label": "Correction"},
    "insight": {"icon": "💡", "label": "Insight"},
    "fact": {"icon": "📌", "label": "Fact"},
    "preference": {"icon": "❤️", "label": "Preference"},
    "reference": {"icon": "📎", "label": "Reference"},
}

# Scoring weights
W_CONFIDENCE = 0.35
W_FRESHNESS = 0.30
W_PRIORITY = 0.25
W_REPETITION = 0.10

# Defaults
DEFAULT_LIMIT = 10
DEFAULT_MIN_SCORE = 0.20
MAX_AGE_HOURS = 168  # 7 days — older than this gets freshness = 0
BRIEF_MIN_EVENTS = 3  # Don't return a brief if fewer than this many events


def _ensure_imports() -> None:
    """Ensure ~/pantheon/ is on sys.path for importing from lib."""
    pantheon_root = str(_HOME / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


def _get_db() -> Any:
    """Get IchorDB instance. Lazy import."""
    _ensure_imports()
    from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
    db = IchorDB(db_path=str(_ICHOR_DB_PATH))
    db.connect()
    return db


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _hours_ago(created_at: str) -> float:
    """Calculate hours between now and a datetime string."""
    try:
        dt = datetime.fromisoformat(created_at)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return (now - dt).total_seconds() / 3600
    except (ValueError, TypeError):
        return MAX_AGE_HOURS + 1


def _freshness_score(hours: float) -> float:
    """Freshness decays linearly from 1.0 (now) to 0.0 (MAX_AGE_HOURS)."""
    if hours <= 0:
        return 1.0
    if hours >= MAX_AGE_HOURS:
        return 0.0
    return round(1.0 - (hours / MAX_AGE_HOURS), 3)


def score_event(ev: Dict[str, Any]) -> float:
    """Compute a composite relevance score for an event.

    Phase 1 (Ichor consolidation): delegates the actual scoring to
    lib.ichor_score.compute_score() (unified 5-factor formula). Adds
    a small repetition boost (0.0-0.05) on top, since query-less recall
    is repetition-sensitive in a way that the unified formula is not.

    Args:
        ev: Event dict from ichor_events (must have event_type, confidence,
            created_at, importance, trust, and optionally occurrences).

    Returns:
        Float score 0.0-1.0 where higher = more relevant.
    """
    from lib.ichor_score import compute_score as _compute
    unified = _compute(ev)  # 0.0..100.0
    base = unified / 100.0  # 0.0..1.0
    repetition = min(ev.get("occurrences", 1), 5) / 5.0
    # Repetition is a 0-5% boost on the unified score. Capped because
    # the unified formula already accounts for access-boosted importance
    # which correlates with retrieval count over time.
    repetition_boost = repetition * 0.05
    return round(min(1.0, base + repetition_boost), 3)


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def query_all_events(
    god_name: str = "",
    since_hours: float = MAX_AGE_HOURS,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    """Query all events within the age window, optionally filtered by god.

    Args:
        god_name: If set, only return events for this god.
        since_hours: Only return events newer than this many hours.
        limit: Max events to consider.

    Returns:
        List of event dicts.
    """
    db = _get_db()
    conn = db._conn

    if god_name:
        cursor = conn.execute(
            """
            SELECT * FROM ichor_events
            WHERE god_name = ?
              AND created_at >= datetime('now', ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (god_name, f"-{int(since_hours)} hours", limit),
        )
    else:
        cursor = conn.execute(
            """
            SELECT * FROM ichor_events
            WHERE created_at >= datetime('now', ?)
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (f"-{int(since_hours)} hours", limit),
        )

    results = [dict(row) for row in cursor.fetchall()]
    db.close()
    return results


# ---------------------------------------------------------------------------
# Brief Builder
# ---------------------------------------------------------------------------


def _freshness_label(hours: float) -> str:
    """Label for recency."""
    if hours <= 1:
        return "now"
    elif hours <= 24:
        return f"{int(hours)}h ago"
    elif hours <= 72:
        return f"{int(hours / 24)}d ago"
    return f"{int(hours / 24)}d ago"


def _confidence_badge(confidence: float) -> str:
    """Short confidence badge."""
    if confidence >= 0.9:
        return "🟢"
    elif confidence >= 0.7:
        return "🟡"
    return "🟠"


def build_brief(
    god_name: str = "",
    limit: int = DEFAULT_LIMIT,
    min_score: float = DEFAULT_MIN_SCORE,
    include_all_gods: bool = False,
    output_format: str = "markdown",
) -> Any:
    """Build a ranked context brief for a god.

    Queries all recent events, scores them, filters by threshold, ranks
    descending, and returns the top-N as formatted output.

    Args:
        god_name: Filter events for this god.
        limit: Max items to return.
        min_score: Minimum score threshold (0.0-1.0).
        include_all_gods: If True, include events from ALL gods
            (gives cross-god awareness).
        output_format: 'markdown' or 'json'.

    Returns:
        If output_format='markdown': a formatted markdown string.
        If output_format='json': a dict with ranked events and metadata.
    """
    events = query_all_events(
        god_name=god_name if not include_all_gods else "",
        limit=200,
    )

    if not events:
        empty_msg = (
            f"🧘 No ichor events yet for **{god_name}**.\n\n"
            "Events are extracted during context compression — have a conversation "
            "and decisions/commitments will appear here automatically."
            if god_name
            else "🧘 No ichor events found yet."
        )
        if output_format == "json":
            return {"status": "empty", "god_name": god_name, "events": []}
        return empty_msg

    # Score and rank
    scored = []
    for ev in events:
        s = score_event(ev)
        if s >= min_score:
            scored.append((s, ev))

    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:limit]

    if not scored:
        empty_msg = (
            f"🧘 No notable events for **{god_name}** above score {min_score}."
            if god_name
            else "🧘 No notable events above score threshold."
        )
        if output_format == "json":
            return {"status": "below_threshold", "god_name": god_name, "min_score": min_score, "events": []}
        return empty_msg

    if output_format == "json":
        return {
            "status": "ok",
            "god_name": god_name,
            "total_scored": len(scored),
            "events": [
                {
                    "rank": i + 1,
                    "score": s,
                    "event_type": ev["event_type"],
                    "subject": ev["subject"],
                    "confidence": ev["confidence"],
                    "freshness": _freshness_score(_hours_ago(ev.get("created_at", ""))),
                    "created_at": ev.get("created_at", ""),
                    "raw_text": ev.get("raw_text", "")[:300],
                    "session_id": ev.get("session_id", ""),
                }
                for i, (s, ev) in enumerate(scored)
            ],
        }

    # ── Markdown output ──────────────────────────────────────────────
    lines: List[str] = []
    title = f"for **{god_name}**" if god_name else "(all gods)"
    lines.append(f"## 🧠 Ichor Brief {title}")
    lines.append(f"_Ranked context · {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")

    for i, (score, ev) in enumerate(scored):
        hours = _hours_ago(ev.get("created_at", ""))
        freshness_label = _freshness_label(hours)
        conf_badge = _confidence_badge(ev.get("confidence", 0.5))
        meta = TYPE_META.get(ev.get("event_type", ""), {})
        icon = meta.get("icon", "•")
        type_label = meta.get("label", ev.get("event_type", ""))

        subject = ev.get("subject", "?")
        raw = ev.get("raw_text", "") or ""
        raw_preview = raw[:200] + ("..." if len(raw) > 200 else "")

        lines.append(
            f"{i+1}. **{subject}** {conf_badge} {icon} {type_label} · "
            f"score: {score:.2f} · {freshness_label}"
        )
        if raw_preview:
            lines.append(f"   > {raw_preview}")

    lines.append("")
    lines.append(f"---")
    total = len(scored)
    type_counts = ", ".join(
        f"{TYPE_META.get(t, {}).get('icon', '•')} {sum(1 for _, e in scored if e['event_type'] == t)}"
        for t in ["blocker", "commitment", "decision", "follow_up", "insight"]
        if sum(1 for _, e in scored if e['event_type'] == t) > 0
    )
    lines.append(f"_{total} items · {type_counts}_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point.

    Usage:
        python3 ~/pantheon/lib/ichor_brief.py [--god NAME] [--limit N] [--min-score M] [--json] [--all-gods]
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Ichor Brief — query-less recall for Pantheon gods"
    )
    parser.add_argument(
        "--god", "-g", default="",
        help="Filter events for this god (default: all gods)",
    )
    parser.add_argument(
        "--limit", "-l", type=int, default=DEFAULT_LIMIT,
        help=f"Max items to return (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--min-score", "-m", type=float, default=DEFAULT_MIN_SCORE,
        help=f"Minimum score threshold (default: {DEFAULT_MIN_SCORE})",
    )
    parser.add_argument(
        "--json", "-j", action="store_true",
        help="Output JSON instead of markdown",
    )
    parser.add_argument(
        "--all-gods", "-a", action="store_true",
        help="Include events from all gods (cross-god awareness)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    result = build_brief(
        god_name=args.god,
        limit=args.limit,
        min_score=args.min_score,
        include_all_gods=args.all_gods,
        output_format="json" if args.json else "markdown",
    )

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result)


if __name__ == "__main__":
    main()
