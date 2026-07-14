"""Ichor Subconscious Engine — Periodic Background Awareness for Gods.

The Subconscious Engine runs as a cron job and gives each god proactive
awareness of pending items, open decisions, blockers, and fresh insights
from the Ichor event database.

Architecture:
    Cron (every N min) → ichor_subconscious.tick()
        → Query ichor_events for actionable items per god
        → Phase 3: cluster events by topic similarity
        → Phase 3: optionally summarize clusters via LLM
        → Build situation report (clustered or legacy)
        → Deliver to god's filesystem inbox (primary)
        → Phase 3: also deliver through Conductor handoff system
        → Update overlap guard

Overlap guard:
    Prevents duplicate deliveries by tracking which events have been
    reported per god. A counter file stores the last-reported event ID
    per god — only events with higher IDs are included.
"""

from __future__ import annotations

import json
import logging
import os
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

# Topic clustering defaults. These can be overridden by env vars so the
# background job can be tuned without a code change.
DEFAULT_CLUSTER_WINDOW_MINUTES = 30
DEFAULT_CLUSTER_SIMILARITY_THRESHOLD = 0.82
DEFAULT_CLUSTER_MIN_SIZE = 2
DEFAULT_CLUSTER_MAX_SIZE = 20


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


def _sanitize_preview(text: str) -> str:
    """Sanitize preview text for subconscious reports."""
    if not text:
        return ""

    lines: List[str] = []
    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(sig in lowered for sig in (
            '{"result":', '{"output":', '{"messages":', '"untrusted_tool_result"',
            '</untrusted_tool_result>', '<untrusted_tool_result>', '<tool_result>',
            '</tool_result>', 'only the user', 'outside this block',
            'treat as data', 'do not follow', 'cannot be issuing instructions',
        )):
            continue
        if lowered.startswith(("you are", "you must", "treat as", "only the user")):
            continue
        if "\\u" in line:
            return ""
        lines.append(line)

    if not lines:
        return ""

    collapsed = " ".join(lines)
    for sep in (". ", "! ", "? "):
        idx = collapsed.find(sep)
        if idx != -1:
            return collapsed[: idx + 1].strip()

    if len(collapsed) <= 240:
        return collapsed

    return collapsed[:237].rstrip() + "..."


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
            raw_preview = _sanitize_preview(str(raw))

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
# Topic clustering
# ---------------------------------------------------------------------------


# (replaced by Phase 3 YAML-aware version below)


def _event_text(ev: Dict[str, Any]) -> str:
    subject = str(ev.get("subject", ""))
    raw_text = str(ev.get("raw_text", ""))
    return f"{subject} {raw_text}".strip().lower()


def _token_counts(text: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    token = []
    for ch in text.lower():
        if ch.isalnum():
            token.append(ch)
            continue
        if token:
            piece = "".join(token)
            if len(piece) > 2:
                counts[piece] = counts.get(piece, 0) + 1
            token = []
    if token:
        piece = "".join(token)
        if len(piece) > 2:
            counts[piece] = counts.get(piece, 0) + 1
    return counts


def _cosine_similarity(text_a: str, text_b: str) -> float:
    """Cosine similarity over simple token counts.

    This is deterministic and cheap enough for the background tick while still
    giving us a stable clustering signal for similar event text.
    """
    counts_a = _token_counts(text_a)
    counts_b = _token_counts(text_b)
    if not counts_a or not counts_b:
        return 0.0

    dot = sum(counts_a[t] * counts_b.get(t, 0) for t in counts_a)
    if dot <= 0:
        return 0.0
    mag_a = sum(v * v for v in counts_a.values()) ** 0.5
    mag_b = sum(v * v for v in counts_b.values()) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _cluster_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster events into topic groups using deterministic similarity.

    Returns a list of cluster dicts sorted by recency, each containing the
    member events and a derived summary.
    """
    settings = _cluster_runtime_settings()
    if len(events) < settings["min_size"]:
        return []

    if not events:
        return []

    # Keep only events within the configured window, using the newest event as
    # the anchor for the tick batch.
    newest_created_at = max(ev.get("created_at", "") for ev in events)
    newest_dt: datetime | None = None
    try:
        newest_dt = datetime.fromisoformat(str(newest_created_at))
    except (ValueError, TypeError):
        newest_dt = None

    eligible: List[Dict[str, Any]] = []
    for ev in events:
        created_at = ev.get("created_at", "")
        try:
            event_dt = datetime.fromisoformat(str(created_at))
        except (ValueError, TypeError):
            continue
        if newest_dt is not None:
            delta_minutes = abs((newest_dt - event_dt).total_seconds()) / 60.0
            if delta_minutes > settings["window_minutes"]:
                continue
        eligible.append(ev)

    if len(eligible) < settings["min_size"]:
        return []

    ordered = sorted(
        eligible,
        key=lambda ev: (str(ev.get("created_at", "")), int(ev.get("id", 0))),
        reverse=True,
    )

    clusters: List[Dict[str, Any]] = []
    for ev in ordered:
        text = _event_text(ev)
        placed = False
        for cluster in clusters:
            if len(cluster["members"]) >= settings["max_size"]:
                continue
            similarity = _cosine_similarity(text, cluster["anchor_text"])
            if similarity >= settings["similarity_threshold"]:
                cluster["members"].append(ev)
                cluster["anchor_texts"].append(text)
                placed = True
                break
        if not placed:
            clusters.append({
                "anchor_text": text,
                "anchor_texts": [text],
                "members": [ev],
            })

    clusters = [cluster for cluster in clusters if len(cluster["members"]) >= settings["min_size"]]
    for cluster in clusters:
        members = sorted(
            cluster["members"],
            key=lambda ev: (str(ev.get("created_at", "")), int(ev.get("id", 0))),
            reverse=True,
        )
        cluster["members"] = members
        cluster["count"] = len(members)
        cluster["event_type"] = max(
            {ev.get("event_type", "") for ev in members},
            key=lambda t: _ACTIONABLE_TYPES.index(t) if t in _ACTIONABLE_TYPES else len(_ACTIONABLE_TYPES),
            default="follow_up",
        )
        cluster["representative"] = members[0]
        cluster["summary"] = _build_cluster_summary(members)
        cluster["source_gods"] = sorted({str(ev.get("god_name", "")) for ev in members if ev.get("god_name")})
        cluster["member_ids"] = [ev.get("id") for ev in members]

    return clusters


def _build_cluster_summary(members: List[Dict[str, Any]]) -> str:
    """Create a one-line summary for a cluster."""
    settings = _cluster_runtime_settings()
    if settings.get("llm_summary_enabled"):
        llm_summary = _summarize_cluster_with_llm(members)
        if llm_summary:
            return llm_summary
    # Fallback: deterministic summary from representative event
    representative = members[0]
    subject = str(representative.get("subject", "topic"))
    raw = str(representative.get("raw_text", "")).strip()
    if raw:
        raw = raw.replace("\n", " ")
        raw = raw[:160] + ("..." if len(raw) > 160 else "")
        return f"{subject}: {raw}"
    return subject


# ── Phase 3: LLM summarization ──────────────────────────────────────

def _summarize_cluster_with_llm(members: List[Dict[str, Any]]) -> str:
    """Generate a one-line topic summary using a cheap LLM call.

    Builds a tiny prompt from the cluster's member subjects and first
    sentences, calls the configured LLM provider, and returns a single
    sentence summary. Falls back to empty string on any failure — the
    caller uses the deterministic fallback.
    """
    if len(members) < 2:
        return ""

    # Build a compact prompt: subjects + first ~80 chars of raw_text
    lines: List[str] = []
    for i, ev in enumerate(members[:5], start=1):
        subject = str(ev.get("subject", ""))[:80]
        raw = str(ev.get("raw_text", ""))[:120].replace("\n", " ")
        lines.append(f"{i}. {subject}: {raw}")

    prompt = (
        "You are a memory summarizer. Given these related events from the same "
        "topic cluster, write ONE sentence (max 120 chars) summarizing what they "
        "are collectively about. Be specific, not generic. Return ONLY the "
        f"sentence, nothing else.\n\nEvents:\n" + "\n".join(lines)
    )

    try:
        # Use the same LLM plumbing as extract_llm_rich, but call directly
        from lib.ichor.llm import _call_llm, _resolve_llm_provider
        provider = _resolve_llm_provider("subconscious")
        if not provider:
            return ""
        raw = _call_llm(prompt, provider)
        if not raw:
            return ""
        # Strip any quotes, markdown formatting, or extra whitespace
        summary = raw.strip().strip('"').strip("'").strip()
        # If the LLM returned multi-line, take just the first line
        summary = summary.split("\n")[0].strip()
        if len(summary) > 200:
            summary = summary[:197] + "..."
        return summary
    except Exception:
        return ""


# ── Phase 3: YAML config integration ─────────────────────────────────

def _load_cluster_config_from_yaml() -> Dict[str, Any]:
    """Read cluster settings from ``~/.hermes/config.yaml`` under
    ``ichor.subconscious.*``. Returns empty dict if not configured.
    """
    config_path = Path.home() / ".hermes" / "config.yaml"
    if not config_path.exists():
        return {}
    try:
        import yaml  # type: ignore[import-untyped]
        with open(config_path) as fh:
            cfg = yaml.safe_load(fh) or {}
        return (cfg.get("ichor") or {}).get("subconscious") or {}
    except Exception:
        return {}


def _cluster_runtime_settings() -> Dict[str, Any]:
    """Load clustering settings: YAML config first, env vars as override.

    Returns a dict with keys:
        window_minutes, similarity_threshold, min_size, max_size,
        llm_summary_enabled
    """
    yaml_cfg = _load_cluster_config_from_yaml()

    def _resolve(key: str, default: Any, coerce: type = str) -> Any:
        env_key = f"ICHOR_SUBCONSCIOUS_{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None and str(env_val).strip() != "":
            try:
                return coerce(env_val)
            except (ValueError, TypeError):
                pass
        yaml_val = yaml_cfg.get(key)
        if yaml_val is not None:
            try:
                return coerce(yaml_val)
            except (ValueError, TypeError):
                pass
        return default

    return {
        "window_minutes": _resolve("cluster_window_minutes", DEFAULT_CLUSTER_WINDOW_MINUTES, int),
        "similarity_threshold": _resolve("cluster_similarity_threshold", DEFAULT_CLUSTER_SIMILARITY_THRESHOLD, float),
        "min_size": _resolve("cluster_min_size", DEFAULT_CLUSTER_MIN_SIZE, int),
        "max_size": _resolve("cluster_max_size", DEFAULT_CLUSTER_MAX_SIZE, int),
        "llm_summary_enabled": _resolve("cluster_llm_summary_enabled", False, lambda v: str(v).lower() in ("true", "1", "yes")),
    }


def _build_clustered_situation_report(clusters: List[Dict[str, Any]]) -> str:
    """Render clustered topics into a markdown situation report."""
    if not clusters:
        return ""

    lines: List[str] = []
    lines.append("## 🧠 Subconscious Situation Report")
    lines.append(f"_Auto-generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_\n")

    for idx, cluster in enumerate(clusters, start=1):
        representative = cluster["representative"]
        count = cluster["count"]
        subject = representative.get("subject", "?")
        freshness = _freshness_label(_hours_ago(representative.get("created_at", "")))
        conf = _format_confidence(float(representative.get("confidence", 0.5)))
        source_gods = ", ".join(cluster["source_gods"]) if cluster["source_gods"] else "unknown"
        lines.append(f"### 🧭 Topic {idx} ({count} events)")
        lines.append("")
        lines.append(f"- **Representative:** {subject} {conf} {freshness}")
        lines.append(f"- **Source gods:** {source_gods}")
        lines.append(f"- **Summary:** {cluster['summary']}")
        lines.append(f"- **Member event ids:** {', '.join(str(mid) for mid in cluster['member_ids'])}")
        lines.append("- **Members:**")
        for ev in cluster["members"]:
            ev_subject = ev.get("subject", "?")
            ev_conf = _format_confidence(float(ev.get("confidence", 0.5)))
            ev_preview = str(ev.get("raw_text", "")).replace("\n", " ")
            if len(ev_preview) > 160:
                ev_preview = ev_preview[:160] + "..."
            lines.append(f"  - {ev_subject} {ev_conf}: {ev_preview}")
        lines.append("")

    lines.append("---")
    lines.append(f"_Total topics: {len(clusters)}_")
    return "\n".join(lines)


def _build_report_for_events(events: List[Dict[str, Any]]) -> str:
    """Pick clustered or legacy formatting for the current tick batch."""
    clusters = _cluster_events(events)
    if clusters:
        return _build_clustered_situation_report(clusters)
    return build_situation_report(events)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


def _deliver_to_conductor(
    god_name: str,
    report: str,
    cluster_count: int = 0,
) -> bool:
    """Deliver a clustered situation report through the Conductor handoff
    system so the god's inbox in the Conductor UI picks it up.

    Writes a handoff-compatible JSON file to the shared handoffs dir.
    Falls back silently on any error — the filesystem inbox is the
    primary delivery channel.
    """
    try:
        handoffs_dir = Path(os.environ.get(
            "CONDUCTOR_HANDOFFS_DIR",
            str(Path.home() / "pantheon" / "shared" / "handoffs"),
        ))
        target_dir = handoffs_dir / god_name
        target_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    now = datetime.now(timezone.utc)
    msg_id = f"subconscious_{now.strftime('%Y%m%d_%H%M%S')}"

    handoff = {
        "id": msg_id,
        "from": "subconscious",
        "to": god_name,
        "type": "handoff",
        "subject": f"🧠 Subconscious Digest — {cluster_count} topic(s)",
        "body": report,
        "priority": "normal",
        "timestamp": now.isoformat(),
        "read": False,
        "payload": {
            "source": "ichor_subconscious",
            "type": "clustered_situation_report",
            "cluster_count": cluster_count,
        },
        "routing": {
            "workflow_definition": "subconscious-digest",
        },
    }

    msg_path = target_dir / f"{msg_id}.json"
    try:
        msg_path.write_text(json.dumps(handoff, indent=2) + "\n", encoding="utf-8")
        logger.info(
            "Delivered subconscious conductor handoff to '%s' (%d bytes, %s)",
            god_name, len(report), msg_id,
        )
        return True
    except Exception as exc:
        logger.debug("Conductor handoff write failed for '%s': %s", god_name, exc)
        return False


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

            report = _build_report_for_events(events)
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

            # Phase 3: also deliver through Conductor handoff system
            cluster_count = 0
            try:
                clusters = _cluster_events(events)
                cluster_count = len(clusters)
            except Exception:
                pass
            _deliver_to_conductor(gname_lower, report, cluster_count=cluster_count)

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
