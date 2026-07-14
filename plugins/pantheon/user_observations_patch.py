"""
User observations extraction — piggybacks on the Ichor Nudge LLM call.

Adds USER_OBSERVATIONS extraction alongside the existing ICHOR_EVENTS block.
Same LLM call, same context window, same response — just one more JSON block
to parse and store in PostgreSQL.

Was previously at plugins/pantheon-ichor-nudge/user_observations_patch.py,
consolidated into the pantheon plugin (2026-06-02).
"""
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("pantheon.ichor_nudge.user_observations")

# ---------------------------------------------------------------------------
# Prompt addition (appended to AIAgent._MEMORY_REVIEW_PROMPT)
# ---------------------------------------------------------------------------

USER_OBSERVATIONS_PROMPT_ADDITION = """
### User Observations

Also scan the conversation for new things you learned about the user(s) and
output them as structured observations. These observations will be stored in
Pantheon's user memory system so ALL gods can understand this user better in
future interactions.

Output as a JSON block at the END of your response (after ICHOR_EVENTS):

USER_OBSERVATIONS
[
  {
    "subject": "konan",
    "category": "preference",
    "content": "Prefers plan-first execution with no clarification loops on Telegram",
    "confidence": 0.9,
    "evidence": ["msg-3", "msg-7"]
  }
]

CATEGORIES: fact, preference, commitment, project, relationship,
           environment, emotional, contradiction, gap

RULES:
- Only NEW observations (check existing list below)
- Self-contained, with absolute dates, confidence >= 0.5
- Evidence references where possible
- Corrections are HIGH PRIORITY (category: preference)
- Empty array if nothing new: []
"""


# ---------------------------------------------------------------------------
# Store function — parses USER_OBSERVATIONS block from LLM response
# ---------------------------------------------------------------------------

def _store_user_observations(content: str, session_id: str = "", god_name: str = "") -> int:
    """Parse USER_OBSERVATIONS JSON block from LLM response and store in PostgreSQL."""
    if "USER_OBSERVATIONS" not in content:
        return 0

    try:
        marker = "USER_OBSERVATIONS"
        idx = content.index(marker)
        json_text = content[idx + len(marker):].strip()

        start = json_text.find("[")
        end = json_text.rfind("]")
        if start == -1 or end == -1:
            return 0

        json_text = json_text[start:end + 1]
        observations = json.loads(json_text)

        if not isinstance(observations, list) or not observations:
            return 0

        # Import our storage backend
        pantheon_root = str(Path.home() / "pantheon")
        if pantheon_root not in sys.path:
            sys.path.insert(0, pantheon_root)
        from lib.user_observations import store_observations, resolve_user_alias

        count = 0
        for obs in observations:
            subject = obs.get("subject", "").lower().strip()
            if not subject:
                continue

            # Try alias resolution; fall back to raw subject
            canonical = resolve_user_alias("telegram", subject) or subject

            stored = store_observations(
                observations=[obs],
                subject_id=canonical,
                observer_id=god_name or "hermes",
                session_id=session_id,
            )
            count += stored

        if count:
            logger.info(
                "User observations: stored %d observations (session=%s god=%s)",
                count, session_id or "(none)", god_name or "(none)",
            )

        return count

    except Exception:
        logger.debug("Failed to parse user observations (non-fatal)", exc_info=True)
        return 0
