"""Ichor Subconscious Engine — Periodic Background Awareness for Gods.

The Subconscious Engine runs as a cron job and gives each god proactive
awareness of pending items, open decisions, blockers, and fresh insights
from the Ichor event database.

Architecture:
    Cron (every N min) → ichor_subconscious.tick()
        → Query ichor_events for actionable items per god
        → Build situation report (zero-LLM, structured data)
        → Deliver to god's filesystem inbox
        → Update overlap guard

Overlap guard:
    Prevents duplicate deliveries by tracking which events have been
    reported per god. A counter file stores the last-reported event ID
    per god — only events with higher IDs are included.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("ichor_subconscious")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HOME = Path.home()
_PANTHEON_LIB = _HOME / "pantheon" / "lib"
_ICHOR_DB_PATH = _HOME / ".hermes" / "ichor.db"
_COUNTER_DIR = _HOME / ".hermes" / "ichor_subconscious"
_MESSAGES_DIR = _HOME / "pantheon" / "gods" / "messages"

# Actionable event types in priority order
_ACTIONABLE_TYPES = [
    "blocker",
    "commitment",
    "follow_up",
    "decision",
    "insight",
]

# Freshness windows (in hours)
_FRESH_HOT = 24       # "hot" — top priority
_FRESH_WARM = 72      # "warm" — still relevant
_FRESH_COLD = 168     # "cold" — surface only if high confidence (7 days)

MAX_EVENTS_PER_GOD = 15      # Max total events in a single report
MAX_EVENTS_PER_TYPE = 5      # Max per event type per report


def _ensure_imports() -> None:
    """Ensure ~/pantheon/ is on sys.path for importing from lib."""
    pantheon_root = str(_HOME / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


def _get_db() -> Any:
    """Get IchorDB instance. Lazy import to avoid circular deps."""
    _ensure_imports()
    from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
    db = IchorDB(db_path=str(_ICHOR_DB_PATH))
    db.connect()
    return db


def _get_last_reported_id(god_name: str) -> int:
    """Read the last-reported event ID for a god (overlap guard)."""
    counter_file = _COUNTER_DIR / f"{god_name}.txt"
    if counter_file.exists():
        try:
            return int(counter_file.read_text().strip())
        except (ValueError, IOError):
            return 0
    return 0


def _set_last_reported_id(god_name: str, event_id: int) -> None:
    """Write the last-reported event ID for a god."""
    _COUNTER_DIR.mkdir(parents=True, exist_ok=True)
    counter_file = _COUNTER_DIR / f"{god_name}.txt"
    counter_file.write_text(str(event_id))


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


def _query_actionable_events(
    db: Any,
    god_name: str = "",
    since_id: int = 0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Query ichor_events for actionable items.

    Args:
        db: IchorDB instance.
        god_name: If provided, filter to this god only.
        since_id: Only return events with ID greater than this (overlap guard).
        limit: Max events to return.

    Returns:
        List of event dicts, ordered by created_at DESC.
    """
    types_placeholders = ",".join("?" for _ in _ACTIONABLE_TYPES)
    params: List[Any] = [*_ACTIONABLE_TYPES]

    if god_name:
        params.append(since_id)
        params.append(god_name)
        params.append(limit)
        sql = f"""
            SELECT * FROM ichor_events
            WHERE event_type IN ({types_placeholders})
              AND id > ?
              AND god_name = ?
            ORDER BY
                CASE event_type
                    WHEN 'blocker' THEN 1
                    WHEN 'commitment' THEN 2
                    WHEN 'follow_up' THEN 3
                    WHEN 'decision' THEN 4
                    WHEN 'insight' THEN 5
                END,
                confidence DESC,
                created_at DESC
            LIMIT ?
        """
    else:
        params.append(since_id)
        params.append(limit)
        sql = f"""
            SELECT * FROM ichor_events
            WHERE event_type IN ({types_placeholders})
              AND id > ?
            ORDER BY
                CASE event_type
                    WHEN 'blocker' THEN 1
                    WHEN 'commitment' THEN 2
                    WHEN 'follow_up' THEN 3
                    WHEN 'decision' THEN 4
                    WHEN 'insight' THEN 5
                END,
                confidence DESC,
                created_at DESC
            LIMIT ?
        """

    conn = db._conn
    cursor = conn.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Situation Report Builder
# ---------------------------------------------------------------------------


def _hours_ago(created_at: str) -> float:
    """Calculate hours between now and an ISO datetime string."""
    try:
        dt = datetime.fromisoformat(created_at)
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = now - dt
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 999  # Unknown → treat as very old


def _freshness_label(hours: float) -> str:
    """Label for recency."""
    if hours <= _FRESH_HOT:
        return "🔥 hot"
    elif hours <= _FRESH_WARM:
        return "⚡ warm"
    elif hours <= _FRESH_COLD:
        return "❄️ cold"
    return "🧊 ancient"


def _format_confidence(confidence: float) -> str:
    """Short confidence badge."""
    if confidence >= 0.9:
        return "🟢"
    elif confidence >= 0.7:
        return "🟡"
    return "🟠"


def build_situation_report(
    events: List[Dict[str, Any]],
) -> str:
    """Build a structured situation report from events.

    Groups events by type, sorts by priority, and formats as markdown.

    Args:
        events: List of event dicts from _query_actionable_events().

    Returns:
        Markdown-formatted situation report. Empty string if no events.
    """
    if not events:
        return ""

    # Group by type
    grouped: Dict[str, List[Dict]] = {}
    for ev in events:
        t = ev["event_type"]
        if t not in grouped:
            grouped[t] = []
        grouped[t].append(ev)

    # Cap per type
    for t in grouped:
        grouped[t] = grouped[t][:MAX_EVENTS_PER_TYPE]

    # Cap total
    total = sum(len(v) for v in grouped.values())
    if total > MAX_EVENTS_PER_GOD:
        # Trim from lowest-priority types
        for t in reversed(_ACTIONABLE_TYPES):
            if total <= MAX_EVENTS_PER_GOD:
                break
            if t in grouped:
                excess = total - MAX_EVENTS_PER_GOD
                trimmed = grouped[t][:-excess] if excess < len(grouped[t]) else []
                total -= len(grouped[t]) - len(trimmed)
                if trimmed:
                    grouped[t] = trimmed
                else:
                    del grouped[t]

    lines: List[str] = []
    lines.append("## 🧠 Subconscious Situation Report")
    lines.append(f"_Auto-generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")

    type_labels = {
        "blocker": "🚧 Blockers",
        "commitment": "📋 Commitments",
        "follow_up": "🔁 Follow-ups",
        "decision": "🎯 Decisions",
        "insight": "💡 Insights",
    }

    type_icons = {
        "blocker": "🚧",
        "commitment": "📋",
        "follow_up": "🔁",
        "decision": "🎯",
        "insight": "💡",
    }

    for event_type in _ACTIONABLE_TYPES:
        if event_type not in grouped:
            continue

        events_of_type = grouped[event_type]
        label = type_labels.get(event_type, event_type)
        icon = type_icons.get(event_type, "•")
        lines.append(f"### {icon} {label} ({len(events_of_type)})")
        lines.append("")

        for ev in events_of_type:
            hours = _hours_ago(ev.get("created_at", ""))
            freshness = _freshness_label(hours)
            conf = _format_confidence(ev.get("confidence", 0.5))
            subject = ev.get("subject", "?")
            raw = ev.get("raw_text", "")
            raw_preview = raw[:200] + "..." if len(raw) > 200 else raw

            lines.append(f"- **{subject}** {conf} {freshness}")
            if raw_preview:
                lines.append(f"  > {raw_preview}")
            lines.append("")

    # Summary line
    type_counts = ", ".join(
        f"{type_labels.get(t, t)}: {len(grouped[t])}"
        for t in _ACTIONABLE_TYPES
        if t in grouped
    )
    lines.append(f"---")
    lines.append(f"_Total: {total} items — {type_counts}_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _deliver_to_inbox(
    god_name: str,
    report: str,
) -> bool:
    """Write a situation report to a god's filesystem inbox.

    Args:
        god_name: Recipient god name (lowercase).
        report: Markdown-formatted situation report.

    Returns:
        True if delivered successfully.
    """
    inbox_dir = _MESSAGES_DIR / god_name
    try:
        inbox_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("Cannot create inbox for '%s': %s", god_name, exc)
        return False

    now = datetime.now(timezone.utc)
    msg_id = f"subconscious_{now.strftime('%Y%m%d_%H%M%S')}"

    message = {
        "id": msg_id,
        "from": "subconscious",
        "to": god_name,
        "type": "report",
        "subject": "🧠 Subconscious Situation Report",
        "body": report,
        "priority": "normal",
        "timestamp": now.isoformat(),
        "read": False,
        "payload": {"source": "ichor_subconscious", "type": "situation_report"},
        "thread_id": None,
    }

    msg_path = inbox_dir / f"{msg_id}.json"
    try:
        msg_path.write_text(json.dumps(message, indent=2) + "\n", encoding="utf-8")
        logger.info(
            "Delivered subconscious report to '%s' (%d bytes, %s)",
            god_name, len(report), msg_id,
        )
        return True
    except Exception as exc:
        logger.warning("Failed to write message for '%s': %s", god_name, exc)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def tick(
    god_name: str = "",
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run one Subconscious Engine tick.

    Queries the ichor DB for actionable events since the last tick,
    builds a situation report, and delivers it to the god's inbox.

    Args:
        god_name: If set, only tick for this specific god.
        dry_run: If True, log what would happen but don't deliver.

    Returns:
        Dict with tick results: {god: {events_found, delivered, report_length}}
    """
    db = _get_db()
    results: Dict[str, Any] = {}

    # Determine which gods to tick
    gods_to_tick: List[str] = []
    if god_name:
        gods_to_tick = [god_name]
    else:
        gods_to_tick = _discover_active_gods()

    if not gods_to_tick:
        logger.info("Subconscious tick: no gods to tick")
        return {"status": "skipped", "reason": "no gods"}

    for gname in gods_to_tick:
        try:
            gname_lower = gname.lower()
            since_id = _get_last_reported_id(gname_lower)
            events = _query_actionable_events(
                db, god_name=gname_lower, since_id=since_id, limit=MAX_EVENTS_PER_GOD
            )

            if not events:
                logger.debug("Subconscious tick for '%s': no new events", gname_lower)
                results[gname_lower] = {
                    "events_found": 0,
                    "delivered": False,
                    "reason": "no_new_events",
                }
                continue

            report = build_situation_report(events)
            if not report:
                results[gname_lower] = {
                    "events_found": len(events),
                    "delivered": False,
                    "reason": "report_empty",
                }
                continue

            if dry_run:
                logger.info(
                    "Subconscious DRY-RUN for '%s': %d events, %d chars",
                    gname_lower, len(events), len(report),
                )
                results[gname_lower] = {
                    "events_found": len(events),
                    "delivered": False,
                    "report_preview": report[:200],
                    "reason": "dry_run",
                }
                continue

            delivered = _deliver_to_inbox(gname_lower, report)

            if delivered:
                # Update overlap guard with max event ID seen
                max_id = max(ev["id"] for ev in events)
                _set_last_reported_id(gname_lower, max_id)

            results[gname_lower] = {
                "events_found": len(events),
                "delivered": delivered,
                "report_length": len(report),
                "max_event_id": max(ev["id"] for ev in events) if events else 0,
            }

        except Exception as exc:
            logger.warning(
                "Subconscious tick failed for '%s': %s", gname, exc, exc_info=True
            )
            results[gname_lower if 'gname_lower' in dir() else gname] = {
                "events_found": 0,
                "delivered": False,
                "error": str(exc),
            }

    db.close()

    summary = {
        "status": "ok",
        "gods_ticked": len(gods_to_tick),
        "results": results,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    total_events = sum(
        r.get("events_found", 0) for r in results.values()
    )
    total_delivered = sum(
        1 for r in results.values() if r.get("delivered")
    )
    logger.info(
        "Subconscious tick complete: %d gods, %d events found, %d reports delivered",
        len(gods_to_tick), total_events, total_delivered,
    )

    return summary


def _discover_active_gods() -> List[str]:
    """Discover active gods from the ichor_events database.

    Returns distinct god_name values from events that have actionable types.
    Falls back to filesystem inbox directories if the DB is empty.
    """
    db = _get_db()
    try:
        types_placeholders = ",".join("?" for _ in _ACTIONABLE_TYPES)
        cursor = db._conn.execute(
            f"""
            SELECT DISTINCT god_name FROM ichor_events
            WHERE event_type IN ({types_placeholders})
              AND god_name IS NOT NULL
              AND god_name != ''
            ORDER BY god_name
            """,
            _ACTIONABLE_TYPES,
        )
        gods = [row["god_name"] for row in cursor.fetchall()]
        if gods:
            db.close()
            return gods
    except Exception:
        pass

    # Fallback: scan inbox directories
    db.close()
    if _MESSAGES_DIR.is_dir():
        return sorted(
            d.name for d in _MESSAGES_DIR.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    return []


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """CLI entry point for the Subconscious Engine.

    Usage:
        python3 ~/pantheon/lib/ichor_subconscious.py [--god NAME] [--dry-run]
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Ichor Subconscious Engine — periodic god awareness tick"
    )
    parser.add_argument(
        "--god", "-g", default="",
        help="Only tick for a specific god (default: all active gods)",
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Log what would happen but don't deliver",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    result = tick(god_name=args.god, dry_run=args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
