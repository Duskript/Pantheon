"""Unified Ichor Score — single scoring formula for all memory events.

Replaces 7 separate scoring formulas (ichor_brief, ichor_memory_score,
shared_facts.score_priority, Tier A confidence, HybridScorer backend
weighting, Ichor Forge, gates cap) with one composite per-event score.

Formula:
    ichor_score = (importance/100)*0.30*100
                + (trust/100)*0.25*100
                + freshness*0.20*100
                + type_priority*0.15*100
                + confidence*0.10*100

Where:
    importance     (0-100) — boosted on access/update, decays daily
                              (lifecycle owned by ichor_memory_score)
    trust          (0-100) — boosted on confirm, penalized on contradict
                              (lifecycle owned by ichor_memory_score)
    freshness      (0-1)   — linear decay 1.0 -> 0.0 over 7 days
    type_priority  (0-1)   — category weight (blocker=1.0, fact=0.50)
    confidence     (0-1)   — Tier A extraction confidence + speaker bonus

Range: 0.0 - 100.0 (single float). Higher = more retrieval-worthy.

Spec: ~/athenaeum/Codex-God-thoth/research/ichor-consolidation-spec/report.md
Author: Thoth (spec), Marvin (implementation)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

# ─── Weights (sum to 1.0) ────────────────────────────────────────
W_IMPORTANCE = 0.30
W_TRUST = 0.25
W_FRESHNESS = 0.20
W_TYPE_PRIORITY = 0.15
W_CONFIDENCE = 0.10

# ─── Type priority: importance-rank by event category ─────────────
# Higher = more retrieval-worthy.
TYPE_PRIORITY = {
    "blocker": 1.00, "commitment": 0.85, "decision": 0.75,
    "follow_up": 0.70, "correction": 0.65, "insight": 0.60,
    "preference": 0.55, "fact": 0.50, "reference": 0.45,
}

# ─── Default importance by event type (seeding) ──────────────────
# Used when an event is first inserted and we want to give it a
# reasonable starting importance rather than the schema default 50.0.
TYPE_IMPORTANCE = {
    "blocker": 70, "commitment": 60, "decision": 55,
    "correction": 50, "insight": 50, "preference": 45,
    "follow_up": 45, "fact": 40, "reference": 35,
}

# ─── Freshness window ────────────────────────────────────────────
# Linear decay from 1.0 (now) to 0.0 (FRESHNESS_DAYS old).
FRESHNESS_DAYS = 7


def _freshness_score(created_at: str, now: Optional[datetime] = None) -> float:
    """Linear freshness: 1.0 at now, 0.0 at FRESHNESS_DAYS old.

    Accepts ISO-8601-ish strings (with or without 'Z' suffix, with or
    without timezone). Falls back to 0.5 for unparseable timestamps
    (which is the "neutral" middle — neither fresh nor stale).
    """
    if not created_at:
        return 0.5
    if now is None:
        now = datetime.now(timezone.utc)
    s = created_at.strip()
    # Python's fromisoformat handles most ISO-8601 in 3.11+; older
    # versions need the trailing 'Z' replaced with '+00:00'.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        ts = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return 0.5
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age_seconds = (now - ts).total_seconds()
    if age_seconds < 0:
        return 1.0
    age_days = age_seconds / 86400.0
    if age_days >= FRESHNESS_DAYS:
        return 0.0
    return 1.0 - (age_days / FRESHNESS_DAYS)


def _row_value(row, key: str, default=None):
    """Get a value from either a sqlite3.Row or a dict."""
    if row is None:
        return default
    try:
        v = row[key]
    except (KeyError, IndexError):
        return default
    return default if v is None else v


def compute_score(event, now: Optional[datetime] = None) -> float:
    """Compute unified ichor_score for a single event.

    Accepts either a dict or a sqlite3.Row. Required fields:
    - importance (0-100)
    - trust (0-100)
    - created_at (ISO-8601 string or datetime)
    - event_type (str; one of TYPE_PRIORITY keys or unknown)
    - confidence (0-1)

    Returns: float in 0.0..100.0, rounded to 1 decimal.
    """
    importance = _row_value(event, "importance", 50.0)
    trust = _row_value(event, "trust", 50.0)
    created_at = _row_value(event, "created_at", "")
    event_type = _row_value(event, "event_type", "") or ""
    confidence = _row_value(event, "confidence", 0.5)

    # Normalize importance and trust to 0-1 (they are stored 0-100)
    imp_norm = max(0.0, min(1.0, float(importance) / 100.0))
    trust_norm = max(0.0, min(1.0, float(trust) / 100.0))
    confidence_norm = max(0.0, min(1.0, float(confidence)))
    type_priority = TYPE_PRIORITY.get(event_type, 0.50)
    freshness = _freshness_score(created_at, now=now)

    score = (
        imp_norm * W_IMPORTANCE * 100
        + trust_norm * W_TRUST * 100
        + freshness * W_FRESHNESS * 100
        + type_priority * W_TYPE_PRIORITY * 100
        + confidence_norm * W_CONFIDENCE * 100
    )
    return round(score, 1)


# ─── Optional: convenience for the HybridScorer fusion path ──────
# Used by ichor_hybrid.py to add the score as a post-fusion boost.

# Default score for raw documents that aren't ichor_events (e.g. distilled
# docs from ChromaDB that have no importance/trust metadata). The 0.50
# puts them at the midpoint, so they neither dominate nor disappear.
DEFAULT_NON_EVENT_SCORE = 50.0

# HybridScorer's ichor_score blend weight (0.30 = 30% boost in fusion).
HYBRID_BOOST_WEIGHT = 0.30
HYBRID_BACKEND_WEIGHT = 0.70


# ─── Priority → Importance override (for compression path) ─────────
# Used by on_pre_compress: when a message scores priority ≥ 4, the events
# Tier A just stored from that message get their importance overridden
# to match the message priority (not the default TYPE_IMPORTANCE seed).

def priority_to_importance(priority: int) -> int:
    """Map a shared-facts priority score (1-10) to an importance value (0-100).

    Linear mapping clamped to [20, 80]:
      1 → 25,  5 → 50,  10 → 75
    """
    if priority is None:
        return 50
    try:
        p = int(priority)
    except (TypeError, ValueError):
        return 50
    # Linear: 5 → 50, so importance = priority * 10
    val = p * 10
    return max(20, min(80, val))


def importance_boost_for_priority(priority: int) -> float:
    """Return an additive importance boost given a priority score.

    Used as a one-shot override (not stacked with TYPE_IMPORTANCE).
    Returns 0.0 if priority < 4 (caller should skip).
    """
    if priority is None or priority < 4:
        return 0.0
    return float(priority_to_importance(priority))
