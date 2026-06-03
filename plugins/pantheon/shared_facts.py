"""Pantheon Shared Facts — consolidated into the pantheon plugin (2026-06-02).

Was previously a standalone plugin at plugins/pantheon-shared-facts/.
Hooks into on_pre_compress to extract decisions, facts, and preferences
from messages about to be compressed and writes them to
~/pantheon/shared/decisions/{user_id}/ as timestamped markdown files.

Also hooks into on_memory_write to capture explicit memory saves.

The decisions/ folder feeds into the budget-aware context injection
system so all gods see relevant shared context without tool calls.

Multi-user: paths are scoped by user_id (env HERMES_USER_ID, defaults to 'konan').
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger("pantheon.shared_facts")

# ── paths ──────────────────────────────────────────────────────────────

_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
_PANTHEON_SHARED = Path.home() / "pantheon" / "shared"


def _get_user_id() -> str:
    """Return the current user ID (default: konan for single-user)."""
    return os.environ.get("HERMES_USER_ID", "konan")


def _decisions_dir(user_id: str | None = None) -> Path:
    return _PANTHEON_SHARED / "decisions" / (user_id or _get_user_id())


def _context_file(user_id: str | None = None) -> Path:
    return _PANTHEON_SHARED / f"CONTEXT_{user_id or _get_user_id()}.md"


# ── priority patterns (regex, zero-cost) ──────────────────────────────

_HIGH_PRIORITY_PATTERNS: list[tuple[re.Pattern, int]] = [
    # Hard rules and architecture decisions
    (re.compile(r"\b(hard rule|never|always|must not|requirement)\b", re.I), 9),
    (re.compile(r"\b(decid(ed|ing)|decision|chose|chosen|settled on)\b", re.I), 8),
    (re.compile(r"\b(architectur|design decision|trade.?off)\b", re.I), 8),
    # Config and tool changes
    (re.compile(r"\b(switched|migrated|changed|updated|upgraded)\s+(to|from)\b", re.I), 7),
    (re.compile(r"\b(config|setting|configured|setup|installed)\b", re.I), 7),
    # Preferences
    (re.compile(r"\b(prefer|preference|i like|works better|feels right)\b", re.I), 6),
    (re.compile(r"\b(don't do|stop using|avoid|not working)\b", re.I), 6),
    # Facts worth remembering
    (re.compile(r"\b(remember that|keep in mind|note that|important)\b", re.I), 7),
    (re.compile(r"\b(fact:|project uses|depends on|requires)\b", re.I), 6),
    # Task / progress
    (re.compile(r"\b(todo|to do|next step|roadblock|blocked by)\b", re.I), 5),
]

_LOW_PRIORITY_DOMAINS = re.compile(
    r"\b(chat|hello|thanks|okay|sure|let me|let's|gonna|wanna)\b", re.I
)

# ── helpers ────────────────────────────────────────────────────────────


def _ensure_dirs(user_id: str | None = None) -> None:
    """Create decisions directory for a user if it doesn't exist."""
    _decisions_dir(user_id).mkdir(parents=True, exist_ok=True)


def _next_seq(user_id: str | None = None) -> str:
    """Return zero-padded sequence number for today's decisions."""
    today_prefix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = list(_decisions_dir(user_id).glob(f"{today_prefix}--*.md"))
    next_num = len(existing) + 1
    return f"{today_prefix}--{next_num:03d}"


def _score_priority(text: str) -> int:
    """Score a message's importance (1-10) based on keyword patterns.

    Uses regex scanning only — no LLM call. Returns 0 if the message
    appears to be low-value chitchat.
    """
    if not text or len(text.strip()) < 15:
        return 0
    if _LOW_PRIORITY_DOMAINS.search(text) and len(text.split()) < 8:
        return 0

    score = 3  # baseline — generic observation
    for pattern, value in _HIGH_PRIORITY_PATTERNS:
        if pattern.search(text):
            score = max(score, value)

    # Boost for message length (longer = more substantive)
    word_count = len(text.split())
    if word_count > 50:
        score = min(score + 1, 10)
    if word_count > 150:
        score = min(score + 1, 10)

    return score


def _guess_domain(text: str) -> str:
    """Guess the knowledge domain from message content."""
    domains = {
        "infrastructure": re.compile(
            r"\b(server|deploy|docker|container|vps|nginx|proxy|domain|ssh|tailscale|network)\b", re.I
        ),
        "development": re.compile(
            r"\b(code|python|js|typescript|react|api|endpoint|test|debug|git|pr|merge)\b", re.I
        ),
        "config": re.compile(
            r"\b(config|yaml|setting|env|\.env|flag|option|parameter)\b", re.I
        ),
        "music": re.compile(
            r"\b(song|track|beat|melody|lyric|mix|master|suno|audio|vocals|chord)\b", re.I
        ),
        "writing": re.compile(
            r"\b(write|draft|edit|rewrite|prose|chapter|story|character|scene)\b", re.I
        ),
        "design": re.compile(
            r"\b(ui|ux|design|layout|css|style|theme|color|font|icon)\b", re.I
        ),
    }
    for domain, pattern in domains.items():
        if pattern.search(text):
            return domain
    return "general"


def _save_decision(
    content: str,
    priority: int,
    domain: str,
    tags: list[str],
    source: str = "compression",
    user_id: str | None = None,
) -> Path | None:
    """Write a single decision/fact to the user's shared decisions folder."""
    uid = user_id or _get_user_id()
    decisions_path = _decisions_dir(uid)
    _ensure_dirs(uid)
    seq = _next_seq(uid)
    slug = _make_slug(content)
    filename = f"{seq}--{slug}.md"
    filepath = decisions_path / filename

    # Deduplicate: skip if content is very similar to an existing file
    if _is_duplicate(content, uid):
        return None

    header = content.split("\n")[0] if "\n" in content else content[:120]
    summary = header.strip().rstrip(".:")

    md = (
        f"---\n"
        f"date: {datetime.now(timezone.utc).isoformat()}\n"
        f"domain: {domain}\n"
        f"priority: {priority}\n"
        f"source: {source}\n"
        f"tags: [{', '.join(tags)}]\n"
        f'user_id: "{uid}"\n'
        f'summary: "{summary}"\n'
        f"---\n"
        f"\n"
        f"# {summary}\n"
        f"\n"
        f"{content}\n"
    )

    try:
        filepath.write_text(md)
        logger.info("Saved decision: %s (priority=%d, domain=%s, user=%s)", filename, priority, domain, uid)
        return filepath
    except OSError as e:
        logger.warning("Failed to save decision: %s", e)
        return None


def _make_slug(text: str, max_len: int = 48) -> str:
    """Turn a text fragment into a URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    slug = slug[:max_len].rstrip("-")
    return slug or "decision"


def _is_duplicate(new_text: str, user_id: str | None = None, threshold: float = 0.6) -> bool:
    """Simple overlap check against existing decisions.

    Uses word-set Jaccard similarity. Fast, no LLM needed.
    """
    new_words = set(re.findall(r"\b[a-z]{3,}\b", new_text.lower()))
    if not new_words:
        return False

    decisions_path = _decisions_dir(user_id)
    if not decisions_path.exists():
        return False

    for fpath in sorted(decisions_path.glob("*.md"), reverse=True)[:20]:
        try:
            existing = fpath.read_text()
            # Skip frontmatter
            if existing.startswith("---"):
                parts = existing.split("---", 2)
                if len(parts) >= 3:
                    existing = parts[2]
            existing_words = set(re.findall(r"\b[a-z]{3,}\b", existing.lower()))
            if not existing_words:
                continue
            overlap = len(new_words & existing_words) / len(new_words | existing_words)
            if overlap > threshold:
                return True
        except OSError:
            continue
    return False


# ── provider ──────────────────────────────────────────────────────────


class PantheonSharedFactsProvider(MemoryProvider):
    """Extracts decisions/facts during compression and saves them to shared context."""

    def __init__(self) -> None:
        _ensure_dirs()
        logger.info("PantheonSharedFactsProvider initialized (user=%s)", _get_user_id())

    @property
    def name(self) -> str:
        return "pantheon-shared-facts"

    def on_pre_compress(self, messages: List[Dict[str, Any]]) -> str:
        """Extract decisions from messages about to be compressed.

        Scans the discarded messages for high-signal content, saves
        decisions/facts to ~/pantheon/shared/decisions/{user_id}/, and returns
        an empty string (we don't modify the compression summary).
        """
        if not messages:
            return ""

        saved_count = 0
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if not isinstance(content, str) or not content.strip():
                continue

            # Only process user and assistant messages
            if role not in ("user", "assistant"):
                continue

            priority = _score_priority(content)
            if priority < 4:  # Skip low-value chitchat
                continue

            domain = _guess_domain(content)
            tags = [role, domain]

            # Extract key sentences for the decision record
            decision_text = self._extract_key_sentences(content, priority)
            if not decision_text:
                continue

            filepath = _save_decision(
                content=decision_text,
                priority=priority,
                domain=domain,
                tags=tags,
                source="compression",
            )
            if filepath:
                saved_count += 1

        if saved_count:
            logger.info(
                "PantheonSharedFacts: saved %d decisions from %d pre-compress messages",
                saved_count, len(messages),
            )

        return ""  # Don't modify compression summary

    def on_memory_write(
        self,
        action: str,
        target: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Capture explicit memory writes as shared decisions."""
        if not content or not content.strip():
            return

        priority = _score_priority(content)
        if priority < 5:  # Memory writes should be important
            return

        domain = _guess_domain(content)
        tags = ["memory", action, target, domain]

        _save_decision(
            content=content[:500],  # Cap at 500 chars for memory writes
            priority=priority,
            domain=domain,
            tags=tags,
            source="memory_write",
        )

    def _extract_key_sentences(self, text: str, priority: int) -> str:
        """Extract the most relevant sentences from a message.

        For high-priority items, keep more context.
        For medium-priority, extract decision-bearing sentences.
        """
        if priority >= 8:
            return text[:1000]  # Full context for critical decisions

        # Split into sentences
        sentences = re.split(r"(?<=[.!?])\s+", text)

        # Score each sentence
        scored = []
        for s in sentences:
            s = s.strip()
            if not s or len(s) < 10:
                continue
            s_priority = _score_priority(s)
            scored.append((s_priority, s))

        # Take top sentences by priority
        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:3]

        # Return the best sentences
        if top:
            return "\n".join(s for _, s in top if s)
        return ""

    def get_config_schema(self) -> List[Dict[str, Any]]:
        """No configuration needed — purely local filesystem-based."""
        return []

    def system_prompt_block(self) -> str:
        """Inject shared context decisions into the system prompt.

        Reads the user-scoped CONTEXT_{user_id}.md (regenerated every 15 min
        by the injection cron) and returns its content. Falls back to the old
        global CONTEXT.md if the user-specific file doesn't exist yet.

        The system prompt is cached at session start and rebuilt on compression
        events, so decisions are snapshotted fresh at both points.
        """
        ctx_path = _context_file()
        # Try user-scoped first, fall back to global for backwards compat
        if not ctx_path.exists():
            ctx_path = _PANTHEON_SHARED / "CONTEXT.md"
        if not ctx_path.exists():
            return ""
        try:
            content = ctx_path.read_text().strip()
            return content if content else ""
        except OSError:
            return ""

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """No additional tools needed — logs directly to filesystem."""
        return []

    def initialize(self) -> None:
        """Ensure decisions directory exists."""
        _ensure_dirs()

    def is_available(self) -> bool:
        """Always available — purely local filesystem writes."""
        return True


# ── plugin registration (called during discovery) ─────────────────────


def get_provider_instance() -> MemoryProvider:
    """Return a singleton provider instance for Hermes Agent discovery.

    Called by the plugin loader when this module is scanned.
    """
    return PantheonSharedFactsProvider()
