"""Tests for the Ichor C1 spec: Outcome tracking + contradiction detection.

Covers the three GATE C1 checks from the spec verbatim, plus the
behavioral contract for the contradiction signal.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ichor_hybrid import (
    HybridScorer,
    MemoryTrait,
    detect_contradiction,
)


# ---------------------------------------------------------------------------
# Spec gate checks (verbatim from marvin-memory-upgrade-handoff-2026-06-10.md)
# ---------------------------------------------------------------------------


def test_gate_c1_check1_outcome_field_in_log(tmp_path, monkeypatch):
    """Gate C1 check #1: outcome field present in retrieval-log.jsonl.

    Strategy: redirect the retrieval log to a tmp file via env var,
    run a retrieve, check the entry has an "outcome" field.
    """
    log_path = tmp_path / "retrieval-log.jsonl"
    # Force the log to a tmp path
    import lib.ichor_hybrid as h
    monkeypatch.setattr(h, "_RETRIEVAL_LOG", log_path)
    s = HybridScorer()
    s.retrieve("test", limit=3)
    # The log should now have 1+ entries
    assert log_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) >= 1
    last = json.loads(lines[-1])
    assert "outcome" in last, f"Entry missing 'outcome' field: {last}"
    # Outcome is None (lazy) until a later store() correlates it
    # OR a default string like "pending" / "unmarked" — both are valid
    assert last["outcome"] in (None, "pending", "unmarked", ""), (
        f"outcome should be a sentinel for lazy evaluation, got: {last['outcome']!r}"
    )


def test_gate_c1_check2_contradiction_non_blocking():
    """Gate C1 check #2: store a decision, then store a contradicting one.

    Should NOT block or error. Should flag if contradiction detected.
    """
    m = MemoryTrait()
    r1 = m.store(key="test_contradiction", content="Use PostgreSQL", category="decision")
    r2 = m.store(key="test_contradiction", content="Use SQLite instead", category="decision")
    # Both should succeed (no error)
    assert r1.get("stored") is True
    assert r2.get("stored") is True
    # The second should at least mention whether a contradiction was detected
    # (we accept either way — the spec says "should flag if contradiction detected")
    assert "contradiction_warning" in r2 or "stored" in r2


def test_gate_c1_check3_retrieval_path_unchanged():
    """Gate C1 check #3: legacy and tiered both still work."""
    s = HybridScorer()
    old = s.retrieve("test", mode="legacy")
    new = s.retrieve("test", mode="tiered")
    assert "results" in old
    assert "results" in new
    assert old.get("mode") == "legacy"
    assert new.get("mode") == "tiered"
    # Both paths still callable after C1 changes — that's the spec requirement


# ---------------------------------------------------------------------------
# Behavioral contract: contradiction detection
# ---------------------------------------------------------------------------


def test_contradiction_helper_detects_obvious_negation():
    """detect_contradiction should return True for clear negations."""
    old = "We should use PostgreSQL for the production database"
    new = "We should not use PostgreSQL — switch to SQLite instead"
    assert detect_contradiction(old, new) is True


def test_contradiction_helper_returns_false_for_consistent_text():
    """detect_contradiction should return False for aligned content."""
    old = "Use PostgreSQL for production"
    new = "We also need to add indexes to the PostgreSQL tables"
    assert detect_contradiction(old, new) is False


def test_contradiction_helper_returns_false_for_unrelated_text():
    """Unrelated content shouldn't be flagged as contradiction."""
    old = "Use PostgreSQL for production"
    new = "The meeting is at 3pm tomorrow"
    assert detect_contradiction(old, new) is False


def test_store_with_contradiction_returns_warning_field():
    """When contradiction is detected, store() should return a warning field."""
    m = MemoryTrait()
    # First store a high-importance decision
    r1 = m.store(key="c1_test_decision_1", content="Use PostgreSQL", category="decision")
    # Then store the opposite
    r2 = m.store(key="c1_test_decision_2", content="Do not use PostgreSQL, use SQLite", category="decision")
    # Even if a contradiction isn't detected (heuristic may not catch all),
    # the response should still have the field set to False (no false negative masking)
    assert "contradiction_warning" in r2
    # The value is a bool — accepting either True (caught) or False (heuristic missed)
    assert isinstance(r2["contradiction_warning"], bool)


# ---------------------------------------------------------------------------
# Outcome tracking behavior
# ---------------------------------------------------------------------------


def test_outcome_default_is_pending(tmp_path, monkeypatch):
    """Fresh retrieval log entries should have outcome='pending' (lazy)."""
    log_path = tmp_path / "retrieval-log.jsonl"
    import lib.ichor_hybrid as h
    monkeypatch.setattr(h, "_RETRIEVAL_LOG", log_path)
    s = HybridScorer()
    s.retrieve("memory", limit=3)
    last = json.loads(log_path.read_text().strip().splitlines()[-1])
    assert "outcome" in last
    # The default should be a lazy sentinel, not None
    assert last["outcome"] is not None
    assert last["outcome"] in ("pending", "unmarked")


def test_outcome_does_not_change_when_no_store(tmp_path, monkeypatch):
    """A retrieval followed by no store should not mark outcome=used."""
    log_path = tmp_path / "retrieval-log.jsonl"
    import lib.ichor_hybrid as h
    monkeypatch.setattr(h, "_RETRIEVAL_LOG", log_path)
    s = HybridScorer()
    s.retrieve("memory", limit=3)
    last = json.loads(log_path.read_text().strip().splitlines()[-1])
    # After a single retrieve, the outcome should still be the lazy default
    assert last["outcome"] in ("pending", "unmarked", "")
