"""Ichor Tier A — Zero-LLM Regex Extraction Engine.

Fires on compaction events (configurable threshold, default 40%).
Extracts structured events from conversation text using compiled regex patterns.
Events are stored in the ichor_events table via IchorDB for instant FTS5 search.

Usage:
    extractor = TierAExtractor()
    count = extractor.extract_and_store(text, session_id, god_name="apollo")
"""

import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from lib.ichor_db import IchorDB, auto_generate_tiers
from lib.ichor_patterns import PATTERNS, EVENT_TYPE_META, ALL_TYPES

logger = logging.getLogger("ichor_tier_a")

# Events below this confidence are discarded
CONFIDENCE_FLOOR = 0.5

# Default path for the Ichor database
ICHOR_DB_PATH = os.path.expanduser("~/.hermes/ichor.db")

# Default importance (0-100) seeded at Tier A insert time, indexed by
# event_type. Higher = more retrieval-worthy on day-zero before any
# access/confirm/contradict signals have had a chance to move it.
# Defined here in Tier A (Q3 answer, msg_20260612_073307_marvin) rather
# than imported from lib.ichor_score to avoid a hard dep between Tier A
# and the unified score module, which is still a half-shipped refactor
# (see Codex-God-thoth/research/ichor-consolidation-spec/report.md §1a).
# When ichor_score.compute_score() becomes the canonical path, this
# dict gets folded into the unified TYPE_PRIORITY table there.
TYPE_IMPORTANCE: Dict[str, int] = {
    "blocker":     70,   # active obstacle — high retrieval weight
    "commitment":  60,   # followed-up items
    "decision":    55,   # rationale + outcomes
    "correction":  50,   # "I was wrong about X" — high trust signal
    "insight":     50,   # synthesized learnings
    "preference":  45,   # user prefs — moderate
    "follow_up":   45,   # open items
    "fact":        40,   # verified facts
    "reference":   35,   # links, citations
}

# Default trust (0-100) seeded at Tier A insert time. Tier A doesn't
# have access/confirm signals so trust starts at 50 (neutral); the
# daily maintenance + forge cycles move it based on user behavior.
DEFAULT_TRUST: int = 50


def _ensure_gods_path() -> None:
    """Add ~/pantheon/pantheon-core/ to sys.path so GraphClient is importable."""
    gods_path = str(Path.home() / "pantheon" / "pantheon-core")
    if gods_path not in sys.path:
        sys.path.insert(0, gods_path)


class TierAExtractor:
    """Zero-LLM regex extraction engine. Fires on compaction events.

    Extracts decisions, commitments, facts, preferences, corrections,
    insights, blockers, references, and follow-ups from conversation text.
    """

    def __init__(self, db: Optional[IchorDB] = None, db_path: str = ""):
        """Initialize with optional existing IchorDB connection.

        Args:
            db: Existing IchorDB instance. If None, creates one.
            db_path: Path to ichor.db. Defaults to ~/.hermes/ichor.db.
        """
        if db is not None:
            self.db = db
        else:
            path = db_path or ICHOR_DB_PATH
            self.db = IchorDB(db_path=path)
        self.db.connect()

    # ── Core extraction ──────────────────────────────────────────────────

    def extract_from_text(
        self,
        text: str,
        session_id: str,
        god_name: str = "",
        speaker: str = "",
    ) -> List[Dict]:
        """Extract events from a single text segment.

        Args:
            text: Raw conversation text to scan.
            session_id: Current session identifier.
            god_name: Name of the god processing this text.
            speaker: 'user' or 'assistant' — affects confidence baseline.

        Returns:
            List of event dicts with confidence >= CONFIDENCE_FLOOR.
        """
        if not text or not text.strip():
            return []

        results: List[Dict] = []
        seen: Dict[Tuple[str, str], Dict] = {}  # (event_type, subject) -> event

        # User messages get higher baseline confidence
        baseline = 0.9 if speaker.lower() in ("user", "human", "") else 0.6

        for event_type in ALL_TYPES:
            patterns = PATTERNS.get(event_type, [])
            meta = EVENT_TYPE_META.get(event_type, {})
            type_baseline = meta.get("baseline_confidence", 0.7)

            for pattern in patterns:
                for match in pattern.finditer(text):
                    self._process_match(
                        match=match,
                        event_type=event_type,
                        text=text,
                        baseline=baseline,
                        type_baseline=type_baseline,
                        speaker=speaker,
                        session_id=session_id,
                        god_name=god_name,
                        results=results,
                        seen=seen,
                    )

        return results

    def _process_match(
        self,
        match: re.Match,
        event_type: str,
        text: str,
        baseline: float,
        type_baseline: float,
        speaker: str,
        session_id: str,
        god_name: str,
        results: List[Dict],
        seen: Dict,
    ) -> None:
        """Process a single regex match into an event if it passes confidence."""
        matched_text = match.group(0).strip()

        # Calculate confidence
        confidence = (baseline + type_baseline) / 2

        # Bonus for user-originated exact-ish matches
        if speaker.lower() in ("user", "human", ""):
            confidence += 0.05

        # Penalty for very short matches (likely noise)
        if len(matched_text) < 6:
            confidence -= 0.15

        confidence = max(0.1, min(round(confidence, 2), 1.0))

        if confidence < CONFIDENCE_FLOOR:
            return

        # Extract surrounding context
        context = _extract_context(text, match.start(), match.end())

        # Extract subject noun phrase before the match
        subject = _extract_subject(text, match.start(), match.end())

        # Dedup: same (event_type, subject) gets merged with confidence boost
        dedup_key = (event_type, subject.lower() if subject else matched_text.lower())
        if dedup_key in seen:
            existing = seen[dedup_key]
            existing["confidence"] = min(existing["confidence"] + 0.05, 1.0)
            existing["occurrences"] = existing.get("occurrences", 1) + 1
            return

        event = {
            "event_type": event_type,
            "subject": subject or matched_text,
            "predicate": event_type,
            "object": matched_text,
            "confidence": confidence,
            "raw_text": context[:300],
            "speaker": speaker,
            "session_id": session_id,
            "god_name": god_name,
            "occurrences": 1,
        }
        seen[dedup_key] = event
        results.append(event)

    # ── Segment-level extraction ─────────────────────────────────────────

    def extract_from_segment(
        self,
        user_msg: str,
        assistant_msg: str,
        session_id: str,
        god_name: str = "",
    ) -> List[Dict]:
        """Extract from a user+assistant exchange pair.

        User messages get higher baseline confidence.
        """
        results: List[Dict] = []
        seen: Dict = {}

        # User messages
        for ev in self.extract_from_text(
            user_msg, session_id, god_name, speaker="user"
        ):
            key = (ev["event_type"], ev["subject"].lower())
            if key not in seen:
                seen[key] = ev
                results.append(ev)

        # Assistant messages
        for ev in self.extract_from_text(
            assistant_msg, session_id, god_name, speaker="assistant"
        ):
            key = (ev["event_type"], ev["subject"].lower())
            if key not in seen:
                seen[key] = ev
                results.append(ev)

        return results

    # ── Store extraction results ─────────────────────────────────────────

    def extract_and_store(
        self,
        text: str,
        session_id: str,
        god_name: str = "",
        speaker: str = "",
    ) -> int:
        """Extract from text + insert into ichor_events table.

        Args:
            text: Conversation text to scan.
            session_id: Current session identifier.
            god_name: Name of the god.
            speaker: 'user' or 'assistant'.

        Returns:
            Number of events stored.
        """
        events = self.extract_from_text(text, session_id, god_name, speaker)
        return self._store_events(events, session_id, god_name)

    def extract_and_store_segment(
        self,
        user_msg: str,
        assistant_msg: str,
        session_id: str,
        god_name: str = "",
    ) -> int:
        """Extract from user+assistant exchange + store in ichor_events.

        Returns:
            Number of events stored.
        """
        events = self.extract_from_segment(
            user_msg, assistant_msg, session_id, god_name
        )
        return self._store_events(events, session_id, god_name)

    def _store_events(
        self,
        events: List[Dict],
        session_id: str,
        god_name: str = "",
    ) -> int:
        """Store a list of extracted events in the database and upsert to WARM.

        P4b: writes to BOTH ichor_events (legacy, kept for back-compat) AND
        cold_events (new 5-tier schema, the canonical home going forward).
        """
        count = 0
        for ev in events:
            try:
                self.db.insert_event(
                    session_id=session_id,
                    event_type=ev["event_type"],
                    subject=ev["subject"],
                    predicate=ev.get("predicate", ev["event_type"]),
                    object=ev.get("object", ""),
                    confidence=ev["confidence"],
                    source="tier_a",
                    raw_text=ev.get("raw_text", ""),
                    god_name=god_name or ev.get("god_name", ""),
                )
                count += 1

                # P4b: also write to cold_events (the canonical v2 table)
                try:
                    conn = self.db.connect()
                    # B1: derive brief + outline from raw_text (heursitic, L0/L1)
                    _raw = ev.get("raw_text", "") or ""
                    _brief, _outline = auto_generate_tiers(_raw)
                    cur = conn.execute(
                        """INSERT INTO cold_events
                               (event_type, category, name, confidence, importance,
                                trust, raw_text, brief, outline, speaker, session_id, god_name,
                                direction, peer_god, created_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                        (
                            ev["event_type"],
                            ev["event_type"],  # category = event_type for now
                            ev.get("subject", ""),
                            ev.get("confidence", 0.5),
                            # Q3 (msg_20260612_073307_marvin): seed importance
                            # by event_type at insert time. Replaces the
                            # previous 50.0 default + "P0b's seed handles
                            # it later" TODO that was never wired.
                            float(TYPE_IMPORTANCE.get(ev["event_type"], 50)),
                            float(DEFAULT_TRUST),  # neutral; cycles move it
                            _raw,
                            _brief,
                            _outline,
                            ev.get("speaker", ""),
                            session_id,
                            god_name or ev.get("god_name", ""),
                            "unknown",
                            "",
                        ),
                    )
                    # P4b: also keep memory_fts in sync (no triggers on cold_events)
                    try:
                        conn.execute(
                            """INSERT INTO memory_fts (rowid, content, category, name, event_type)
                               VALUES (?, ?, ?, ?, ?)""",
                            (
                                cur.lastrowid,
                                ev.get("raw_text", ""),
                                ev["event_type"],
                                ev.get("subject", ""),
                                ev["event_type"],
                            ),
                        )
                    except Exception as fts_exc:
                        logger.debug("memory_fts insert failed (non-fatal): %s", fts_exc)
                except Exception as cold_exc:
                    logger.debug("cold_events insert failed (non-fatal): %s", cold_exc)

            except Exception as e:
                logger.warning("Failed to store event: %s", e)

        # Upsert extracted entities into warm_entities (P4b: replaces graph sync)
        try:
            warm_count = self._upsert_to_warm(events, session_id, god_name)
            if warm_count:
                logger.debug(
                    "WARM upsert: %d entities written for session %s",
                    warm_count, session_id[:8],
                )
        except Exception as e:
            logger.debug("WARM upsert failed (non-fatal): %s", e)

        return count

    # ── WARM upsert (replaces graph sync, P4b) ───────────────────────

    def _upsert_to_warm(
        self,
        events: List[Dict],
        session_id: str,
        god_name: str = "",
    ) -> int:
        """Upsert extracted entities into the warm_entities table.

        For each unique subject in the extracted events:
          1. INSERT into warm_entities with UNIQUE(category, name) — Rule 43
          2. ON CONFLICT, bump importance by +2 and update trust

        Returns the number of rows upserted.
        """
        try:
            conn = self.db.connect()
        except Exception:
            return 0

        count = 0
        seen: Set[str] = set()

        for ev in events:
            subject = (ev.get("subject") or "").strip()
            confidence = ev.get("confidence", 0.0)
            event_type = ev.get("event_type", "event")
            object_text = (ev.get("object") or "").strip()
            predicate = (ev.get("predicate") or "").strip()
            if not subject or confidence < CONFIDENCE_FLOOR:
                continue
            key = subject.lower()
            if key in seen:
                continue
            seen.add(key)

            related_to = None
            if session_id:
                related_to = f"session:{session_id[:20]}"
            if god_name:
                related_to = (related_to + "," if related_to else "") + f"god:{god_name}"

            value = (predicate + " " + object_text).strip() if object_text else subject

            try:
                # B1: brief = value (it IS the essence of the entity),
                # outline = value capped at 500 chars
                _b, _o = auto_generate_tiers(value)
                conn.execute(
                    """INSERT INTO warm_entities
                           (category, name, value, importance, trust, maturity,
                            related_to, brief, outline, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                       ON CONFLICT(category, name) DO UPDATE SET
                           value = CASE WHEN excluded.trust > warm_entities.trust
                                        THEN excluded.value
                                        ELSE warm_entities.value END,
                           importance = MIN(100, warm_entities.importance + 2),
                           trust = CASE WHEN excluded.trust > warm_entities.trust
                                        THEN MIN(100, warm_entities.trust + 2)
                                        ELSE MAX(0, warm_entities.trust - 1) END,
                           related_to = COALESCE(warm_entities.related_to, excluded.related_to),
                           brief = excluded.brief,
                           outline = excluded.outline,
                           updated_at = datetime('now')""",
                    (event_type, subject, value[:200], 50.0, confidence * 100,
                     "validated", related_to, _b, _o)
                )
                count += 1
            except Exception as exc:
                logger.debug("WARM upsert failed for '%s': %s", subject, exc)

        if count:
            try:
                conn.commit()
            except Exception:
                pass

        return count

    # ── Close ────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the database connection."""
        self.db.close()


# ── Helper functions ───────────────────────────────────────────────────


def _extract_context(text: str, match_start: int, match_end: int) -> str:
    """Extract surrounding context around a match."""
    start = max(0, match_start - 80)
    end = min(len(text), match_end + 80)
    context = text[start:end].strip()
    return context


def _extract_subject(text: str, match_start: int, match_end: int) -> str:
    """Extract the likely subject noun phrase before the match.

    Walks backward from the match to find the subject of the sentence.
    """
    before = text[:match_start].strip()
    if not before:
        return ""

    # Find last sentence boundary before the match
    sentence_breaks = [i for i, c in enumerate(before) if c in ".!?"]
    if sentence_breaks:
        before = before[sentence_breaks[-1] + 1 :].strip()

    # Take last 3-5 meaningful words as subject context
    words = before.split()
    if len(words) > 5:
        words = words[-5:]

    # Filter out stop words at the end
    stop_words = {
        "the", "a", "an", "to", "for", "of", "in", "on", "at",
        "is", "was", "are", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did",
        "will", "would", "could", "should", "may", "might",
        "and", "or", "but", "if", "so", "then", "that",
        "this", "it", "we", "i", "you", "they", "he", "she",
    }
    while words and words[-1].lower() in stop_words:
        words = words[:-1]

    if words:
        return " ".join(words)
    return ""


def create_extractor(db_path: str = "") -> TierAExtractor:
    """Convenience factory for creating a TierAExtractor."""
    return TierAExtractor(db_path=db_path)
