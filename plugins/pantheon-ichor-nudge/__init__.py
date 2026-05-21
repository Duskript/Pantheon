"""Pantheon Ichor Nudge Plugin.

Hooks into the Hermes Agent memory nudge to extract structured Ichor events
(decisions, commitments, insights, blockers, references, follow-ups, preferences)
from the SAME LLM call that already runs for memory/skill review — zero extra LLM calls.

Also fires Tier A regex extraction as fallback on 30 minutes of session inactivity
(background timer thread). No on_session_end hook needed — the nudge and timer
cover both active and idle sessions.

Architecture:
  run_agent.py :: _spawn_background_review()
      │
      ├── [original] forked AIAgent runs patched prompt
      │   ├── Saves memory entries (existing)
      │   ├── Saves skill entries (existing)
      │   └── Outputs Ichor events as JSON block ← appended via prompt patch
      │
      └── [patched] _summarize_background_review_actions
          └── Scans assistant response for Ichor_EVENTS block
              └── Stores via IchorDB (SQLite FTS5)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pantheon_ichor_nudge")

# ---------------------------------------------------------------------------
# Lazy IchorDB singleton
# ---------------------------------------------------------------------------
_ichor_db = None


def _ensure_pantheon_path() -> None:
    pantheon_root = str(Path.home() / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


def _get_ichor_db():
    global _ichor_db
    if _ichor_db is None:
        _ensure_pantheon_path()
        from lib.ichor_db import IchorDB

        _ichor_db = IchorDB(
            db_path=os.path.expanduser("~/.hermes/ichor.db")
        )
    return _ichor_db


# ---------------------------------------------------------------------------
# Prompt append — tells the LLM to also extract Ichor events in the SAME call
# ---------------------------------------------------------------------------

ICHOR_PROMPT_ADDITION = """

### Extract Ichor Events

Also scan the conversation for structured Ichor events and output them as a 
JSON block at the END of your response like this:

ICHOR_EVENTS
[{"type": "decision", "content": "...", "confidence": 0.9}]

Event types: **decision**, **commitment**, **insight**, **blocker**,
**reference**, **follow_up**, **preference**, **fact**, **correction**.

Rules:
- Only extract events you are confident about (confidence 0.0-1.0).
- "decision" = choices made, paths selected, agreements reached.
- "commitment" = promises, deadlines, action items assigned.
- "insight" = realizations, breakthroughs, aha moments.
- "blocker" = stuck points, errors, unresolved issues.
- "reference" = resources, tools, links mentioned.
- "follow_up" = things to revisit later.
- "preference" = user preferences, style choices, work habits.
- "fact" = factual statements about the user, system, or domain.
- "correction" = user corrections, feedback, course corrections.

If no events found, output:
ICHOR_EVENTS
[]
"""


# ---------------------------------------------------------------------------
# Monkey-patch helpers
# ---------------------------------------------------------------------------

_original_summarize = None


def _store_ichor_events(content: str, session_id: str = "", god_name: str = "") -> int:
    """Parse ICHOR_EVENTS JSON block from LLM response content and store via IchorDB."""
    if "ICHOR_EVENTS" not in content:
        return 0

    try:
        # Extract JSON block after ICHOR_EVENTS marker
        marker = "ICHOR_EVENTS"
        idx = content.index(marker)
        json_text = content[idx + len(marker):].strip()

        # Find the JSON array (first [ to last ])
        start = json_text.find("[")
        end = json_text.rfind("]")
        if start == -1 or end == -1:
            return 0

        json_text = json_text[start:end + 1]
        events = json.loads(json_text)

        if not isinstance(events, list) or not events:
            return 0

        db = _get_ichor_db()
        count = 0
        for event in events:
            etype = event.get("type", "fact")
            content_text = event.get("content", "")
            confidence = event.get("confidence", 0.5)

            if not content_text or confidence < 0.5:
                continue

            db.insert_event(
                session_id=session_id,
                event_type=etype,
                subject=content_text,
                confidence=confidence,
                source="nudge",
                god_name=god_name,
            )
            count += 1

        if count:
            logger.info(
                "Ichor nudge: stored %d events from LLM review (session=%s god=%s)",
                count, session_id or "(none)", god_name or "(none)",
            )
        return count

    except Exception:
        logger.debug("Ichor nudge: failed to parse LLM events (non-fatal)", exc_info=True)
        return 0


def _patched_summarize(review_messages: List[Dict], prior_snapshot: List[Dict]) -> List[str]:
    """Wraps the original _summarize_background_review_actions to also extract Ichor events."""
    global _original_summarize

    actions = _original_summarize(review_messages, prior_snapshot) if _original_summarize else []

    # Scan for Ichor events in the last assistant response
    for msg in reversed(review_messages or []):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant":
            content = msg.get("content", "") or ""
            if "ICHOR_EVENTS" in content:
                # Extract session_id and god_name from messages if available
                session_id = ""
                god_name = ""
                for m in review_messages or []:
                    if isinstance(m, dict):
                        sid = m.get("session_id", "")
                        if sid:
                            session_id = sid
                        gn = m.get("god_name", "")
                        if gn:
                            god_name = gn

                _store_ichor_events(content, session_id=session_id, god_name=god_name)
                break

    return actions


def _patch_prompts() -> None:
    """Append Ichor extraction instructions to the memory review prompts."""
    try:
        from run_agent import AIAgent

        # Only patch if not already patched (check for our marker)
        if "ICHOR_EVENTS" not in AIAgent._MEMORY_REVIEW_PROMPT:
            AIAgent._MEMORY_REVIEW_PROMPT += ICHOR_PROMPT_ADDITION
            logger.info("Patched _MEMORY_REVIEW_PROMPT with Ichor extraction")

        if "ICHOR_EVENTS" not in AIAgent._COMBINED_REVIEW_PROMPT:
            AIAgent._COMBINED_REVIEW_PROMPT += ICHOR_PROMPT_ADDITION
            logger.info("Patched _COMBINED_REVIEW_PROMPT with Ichor extraction")

    except Exception:
        logger.warning("Failed to patch memory review prompts (non-fatal)", exc_info=True)


def _patch_summarize() -> None:
    """Replace _summarize_background_review_actions to capture Ichor events."""
    global _original_summarize
    try:
        from run_agent import AIAgent

        _original_summarize = AIAgent._summarize_background_review_actions
        AIAgent._summarize_background_review_actions = staticmethod(_patched_summarize)
        logger.info("Patched _summarize_background_review_actions for Ichor extraction")

    except Exception:
        logger.warning("Failed to patch _summarize_background_review_actions (non-fatal)", exc_info=True)


# ---------------------------------------------------------------------------
# 30-minute inactivity monitor
# ---------------------------------------------------------------------------

_inactivity_timer_started = False


def _check_inactive_sessions() -> None:
    """Check for sessions idle >30 min and fire Tier A regex extraction."""
    try:
        _ensure_pantheon_path()
        # Read session timestamps from the Hermes session DB
        session_db_path = os.path.expanduser("~/.hermes/state.db")
        if not os.path.isfile(session_db_path):
            return

        import sqlite3

        conn = sqlite3.connect(session_db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Find sessions with no activity in 30+ minutes
            cutoff = time.time() - 1800  # 30 minutes ago
            cursor = conn.execute(
                "SELECT id, last_active FROM sessions "
                "WHERE last_active IS NOT NULL "
                "AND last_active < ? "
                "AND last_active > ? "
                "ORDER BY last_active ASC",
                (cutoff, cutoff - 86400),  # Within last 24h
            )
            stale = cursor.fetchall()
        finally:
            conn.close()

        if not stale:
            return

        # Fire Tier A regex on stale sessions
        _ensure_pantheon_path()
        from lib.ichor_tier_a import TierAExtractor

        extractor = TierAExtractor()
        for row in stale:
            session_id = row["id"] if isinstance(row, sqlite3.Row) else row[0]
            try:
                # Get session messages
                messages = _load_session_messages(session_id)
                if messages:
                    # Build text from messages
                    text_parts = []
                    for m in messages:
                        content = m.get("content", "") or ""
                        role = m.get("role", "")
                        if content.strip():
                            text_parts.append(f"[role: {role}] {content}")

                    raw_text = "\n\n".join(text_parts)
                    if raw_text.strip():
                        count = extractor.extract_and_store(raw_text, session_id=session_id)
                        if count:
                            logger.info(
                                "Ichor inactivity: extracted %d events from stale session %s",
                                count, session_id,
                            )
            except Exception:
                logger.debug("Ichor inactivity: failed on session %s", session_id, exc_info=True)

    except Exception:
        logger.debug("Ichor inactivity check failed (non-fatal)", exc_info=True)


def _load_session_messages(session_id: str) -> List[Dict]:
    """Load messages for a given session from the Hermes session store."""
    try:
        from hermes_state import SessionDB

        db = SessionDB()
        session = db.get_session(session_id)
        if session:
            messages_raw = session.get("messages", "[]")
            if isinstance(messages_raw, str):
                return json.loads(messages_raw)
            return messages_raw if isinstance(messages_raw, list) else []
    except Exception:
        pass
    return []


def _inactivity_loop() -> None:
    """Background thread: check every 5 minutes for stale sessions."""
    while True:
        time.sleep(300)  # 5 min
        _check_inactive_sessions()


def _start_inactivity_monitor() -> None:
    global _inactivity_timer_started
    if _inactivity_timer_started:
        return
    _inactivity_timer_started = True
    t = threading.Thread(target=_inactivity_loop, daemon=True, name="ichor-inactivity")
    t.start()
    logger.info("Started 30-min inactivity Ichor monitor")


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------


def register(ctx) -> None:
    """Plugin entry point — called by Hermes Agent plugin loader.

    Patches the memory nudge prompts to include Ichor extraction, wraps
    the background review summarizer to capture Ichor events, and starts
    the inactivity monitor.

    Two extraction paths, zero extra LLM calls:
      1. LLM-enhanced extraction — piggybacks on the memory nudge's
         existing LLM call (every 5 turns via nudge_interval config)
      2. Tier A regex fallback — fires on sessions idle for 30+ min
         (background timer thread, polls every 5 min)
    """
    logger.info("Pantheon Ichor Nudge plugin loading...")

    # 1. Patch prompts to add Ichor extraction to the memory nudge LLM call
    _patch_prompts()

    # 2. Patch summarizer to capture Ichor events from LLM response
    _patch_summarize()

    # 3. Start inactivity monitor (Tier A regex fallback for stale sessions)
    _start_inactivity_monitor()

    logger.info("Pantheon Ichor Nudge plugin loaded successfully")
