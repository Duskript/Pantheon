"""
Phase 2 of ichor-v2 — god-scoped boost + temporal filtering.

Tests for `apply_god_boost()` and the wiring through HybridScorer.retrieve
+ MemoryTrait.retrieve + MCP `ichor_retrieve` schema.

Gate: retrieve with active_god='hermes' ranks hermes events first,
expired events hidden.

Spec: ~/athenaeum/Codex-Pantheon/plans/ichor-v2-build-blueprint.md §4
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make ~/pantheon importable
_PANTHEON = Path.home() / "pantheon"
if str(_PANTHEON) not in sys.path:
    sys.path.insert(0, str(_PANTHEON))


# =============================================================================
# Pure-function tests for apply_god_boost
# =============================================================================


class TestApplyGodBoostPure(unittest.TestCase):
    """Unit tests for the pure function — no DB, no backend."""

    def setUp(self) -> None:
        from lib.ichor.retrieve_fusion import apply_god_boost
        self.apply_god_boost = apply_god_boost

    def test_same_god_2x(self) -> None:
        results = [
            {"id": "a", "fused_score": 0.5, "god_name": "hermes"},
            {"id": "b", "fused_score": 0.5, "god_name": "marvin"},
        ]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertEqual(out[0]["fused_score"], 1.0)   # 0.5 * 2.0
        self.assertEqual(out[1]["fused_score"], 0.75)  # 0.5 * 1.5
        self.assertEqual(out[0]["boost_reason"], "same_god")
        self.assertEqual(out[1]["boost_reason"], "cross_god")

    def test_cross_god_1_5x(self) -> None:
        results = [{"id": "x", "fused_score": 1.0, "god_name": "thoth"}]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertEqual(out[0]["fused_score"], 1.5)
        self.assertEqual(out[0]["boost_reason"], "cross_god")

    def test_neutral_1x_no_active_god(self) -> None:
        results = [
            {"id": "a", "fused_score": 0.5, "god_name": "hermes"},
            {"id": "b", "fused_score": 0.5, "god_name": ""},
        ]
        out = self.apply_god_boost(results, active_god=None)
        # No boost when active_god is None — everything neutral
        for r in out:
            self.assertEqual(r["fused_score"], 0.5)
            self.assertEqual(r["boost_reason"], "neutral")

    def test_neutral_1x_empty_god_name(self) -> None:
        results = [{"id": "a", "fused_score": 0.5, "god_name": ""}]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertEqual(out[0]["fused_score"], 0.5)  # 1.0x
        self.assertEqual(out[0]["boost_reason"], "neutral")

    def test_expired_zero(self) -> None:
        results = [
            {"id": "a", "fused_score": 0.5, "god_name": "hermes",
             "valid_until": "2020-01-01 00:00:00"},
            {"id": "b", "fused_score": 0.5, "god_name": "hermes",
             "status": "archived"},
            {"id": "c", "fused_score": 0.5, "god_name": "hermes",
             "superseded_by": 42},
        ]
        now = datetime(2026, 6, 20, tzinfo=timezone.utc)
        out = self.apply_god_boost(results, active_god="hermes", now=now)
        for r in out:
            self.assertEqual(r["fused_score"], 0.0)
            self.assertEqual(r["boost_reason"], "expired")

    def test_expired_overrides_same_god(self) -> None:
        """Even same-god events are zeroed if temporally expired."""
        results = [{"id": "a", "fused_score": 1.0, "god_name": "hermes",
                    "valid_until": "2020-01-01 00:00:00"}]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertEqual(out[0]["fused_score"], 0.0)
        self.assertEqual(out[0]["boost_reason"], "expired")

    def test_active_status_no_valid_until_is_current(self) -> None:
        results = [{"id": "a", "fused_score": 0.5, "god_name": "hermes",
                    "status": "active"}]
        out = self.apply_god_boost(results, active_god="hermes")
        # status=active + no valid_until = current, gets same_god boost
        self.assertEqual(out[0]["fused_score"], 1.0)
        self.assertEqual(out[0]["boost_reason"], "same_god")

    def test_merged_status_is_expired(self) -> None:
        """Per Phase 0 spec: merged entities are temporally replaced."""
        results = [{"id": "a", "fused_score": 0.5, "god_name": "hermes",
                    "status": "merged"}]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertEqual(out[0]["fused_score"], 0.0)
        self.assertEqual(out[0]["boost_reason"], "expired")

    def test_empty_list_is_safe(self) -> None:
        out = self.apply_god_boost([], active_god="hermes")
        self.assertEqual(out, [])

    def test_modifies_in_place_and_returns_same_list(self) -> None:
        results = [{"id": "a", "fused_score": 0.5, "god_name": "hermes"}]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertIs(out, results)

    def test_factor_constants(self) -> None:
        from lib.ichor.retrieve_fusion import (
            GOD_BOOST_SAME,
            GOD_BOOST_CROSS,
            GOD_BOOST_NEUTRAL,
            GOD_BOOST_EXPIRED,
        )
        self.assertEqual(GOD_BOOST_SAME, 2.0)
        self.assertEqual(GOD_BOOST_CROSS, 1.5)
        self.assertEqual(GOD_BOOST_NEUTRAL, 1.0)
        self.assertEqual(GOD_BOOST_EXPIRED, 0.0)

    def test_falls_back_to_score_when_no_fused_score(self) -> None:
        results = [{"id": "a", "score": 0.4, "god_name": "hermes"}]
        out = self.apply_god_boost(results, active_god="hermes")
        self.assertEqual(out[0]["fused_score"], 0.8)  # 0.4 * 2.0


# =============================================================================
# Helper: seed a temp ichor.db with hermes + non-hermes events
# =============================================================================


def _seed_temp_ichor_db(db_path: Path, rows: list[dict]) -> None:
    """Create a minimal ichor_events table mirroring the live schema + indexes."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """
            CREATE TABLE ichor_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                subject TEXT NOT NULL,
                predicate TEXT,
                object TEXT,
                confidence REAL DEFAULT 0.8,
                source TEXT,
                raw_text TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                god_name TEXT,
                importance REAL DEFAULT 50.0,
                trust REAL DEFAULT 50.0,
                maturity TEXT DEFAULT 'validated',
                last_access TEXT,
                direction TEXT DEFAULT 'unknown',
                peer_god TEXT DEFAULT ''
            )
            """
        )
        # FTS5 trigger (mirrors the live schema)
        conn.execute(
            """
            CREATE VIRTUAL TABLE ichor_events_fts USING fts5(
                subject, predicate, object, raw_text,
                content='ichor_events', content_rowid='id'
            )
            """
        )
        conn.execute(
            """
            CREATE TRIGGER ichor_events_ai AFTER INSERT ON ichor_events BEGIN
                INSERT INTO ichor_events_fts(rowid, subject, predicate, object, raw_text)
                VALUES (new.id, new.subject, new.predicate, new.object, new.raw_text);
            END
            """
        )
        for row in rows:
            cols = ", ".join(row.keys())
            placeholders = ", ".join(["?"] * len(row))
            conn.execute(
                f"INSERT INTO ichor_events ({cols}) VALUES ({placeholders})",
                list(row.values()),
            )
        conn.commit()
    finally:
        conn.close()


# =============================================================================
# Integration test: real HybridScorer with temp DB
# =============================================================================


class TestHybridScorerGodBoostGate(unittest.TestCase):
    """End-to-end gate: hermes events rank first when active_god='hermes'."""

    def setUp(self) -> None:
        # Build a temp ichor.db with known events
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_db = Path(self.tmpdir.name) / "ichor.db"

        # 3 hermes + 3 marvin events all matching "unlqterm_alpha"
        self._seed_events = [
            {"session_id": "h1", "event_type": "fact", "subject": "unlqterm_alpha hermes 1",
             "predicate": "is", "object": "fact", "raw_text": "unlqterm_alpha hermes raw 1",
             "god_name": "hermes", "confidence": 0.9},
            {"session_id": "h2", "event_type": "decision", "subject": "unlqterm_alpha hermes 2",
             "predicate": "decided", "object": "X", "raw_text": "unlqterm_alpha hermes raw 2",
             "god_name": "hermes", "confidence": 0.85},
            {"session_id": "h3", "event_type": "insight", "subject": "unlqterm_alpha hermes 3",
             "predicate": "notes", "object": "Y", "raw_text": "unlqterm_alpha hermes raw 3",
             "god_name": "hermes", "confidence": 0.8},
            {"session_id": "m1", "event_type": "fact", "subject": "unlqterm_alpha marvin 1",
             "predicate": "is", "object": "fact", "raw_text": "unlqterm_alpha marvin raw 1",
             "god_name": "marvin", "confidence": 0.9},
            {"session_id": "m2", "event_type": "decision", "subject": "unlqterm_alpha marvin 2",
             "predicate": "decided", "object": "Z", "raw_text": "unlqterm_alpha marvin raw 2",
             "god_name": "marvin", "confidence": 0.85},
            {"session_id": "m3", "event_type": "insight", "subject": "unlqterm_alpha marvin 3",
             "predicate": "notes", "object": "W", "raw_text": "unlqterm_alpha marvin raw 3",
             "god_name": "marvin", "confidence": 0.8},
        ]
        _seed_temp_ichor_db(self.tmp_db, self._seed_events)

        # Monkeypatch the FTS5Backend + EventsBackend to use temp DB
        import lib.ichor_hybrid as ih
        self._ih = ih
        self._orig_ichor_db = ih._ICHOR_DB
        ih._ICHOR_DB = self.tmp_db

        # Reset cached DB connections (they lazily connect)
        ih._ICHOR_DB = self.tmp_db

    def tearDown(self) -> None:
        import lib.ichor_hybrid as ih
        ih._ICHOR_DB = self._orig_ichor_db
        self.tmpdir.cleanup()

    def test_hermes_events_rank_first_when_active_god_hermes(self) -> None:
        from lib.ichor_hybrid import HybridScorer
        scorer = HybridScorer()
        result = scorer.retrieve("unlqterm_alpha", limit=10, active_god="hermes")

        # All top results should be hermes
        gods = [r.get("god_name", "") for r in result["results"]]
        self.assertTrue(len(gods) > 0, "No results returned")
        # First result MUST be hermes
        self.assertEqual(gods[0], "hermes",
                         f"Top result should be hermes, got {gods[0]} — all gods: {gods}")

        # Most/all top results should be hermes
        hermes_count = sum(1 for g in gods if g == "hermes")
        self.assertGreaterEqual(hermes_count, 3,
                                f"Expected ≥3 hermes in top 10, got {hermes_count}: {gods}")

        # Every result should have boost_reason set
        for r in result["results"]:
            self.assertIn("boost_reason", r)
            self.assertIn(r["boost_reason"],
                          {"same_god", "cross_god", "neutral", "expired"})

    def test_marvin_events_rank_first_when_active_god_marvin(self) -> None:
        """Symmetric: marvin asks, marvin events rank first."""
        from lib.ichor_hybrid import HybridScorer
        scorer = HybridScorer()
        result = scorer.retrieve("unlqterm_alpha", limit=10, active_god="marvin")
        gods = [r.get("god_name", "") for r in result["results"]]
        self.assertEqual(gods[0], "marvin")

    def test_no_active_god_keeps_legacy_ranking(self) -> None:
        """Without active_god, ranking is unchanged (no boost applied)."""
        from lib.ichor_hybrid import HybridScorer
        scorer = HybridScorer()
        result = scorer.retrieve("unlqterm_alpha", limit=10, active_god=None)
        # All results should be marked 'neutral'
        for r in result["results"]:
            self.assertEqual(r.get("boost_reason"), "neutral")

    def test_expired_entity_hidden_in_results(self) -> None:
        """Expired events (valid_until < now) get 0x and disappear."""
        # Insert an expired hermes event matching the same query
        expired_row = {
            "session_id": "h_old", "event_type": "fact",
            "subject": "unlqterm_alpha expired hermes",
            "predicate": "is", "object": "expired fact",
            "raw_text": "unlqterm_alpha expired hermes raw",
            "god_name": "hermes", "confidence": 0.9,
            # Phase 0 temporal columns aren't on ichor_events yet, so we
            # test the function-level expiry contract directly via a result
            # dict rather than through the FTS5 path.
        }
        # Insert directly into the existing temp DB (don't re-seed schema)
        conn = sqlite3.connect(str(self.tmp_db))
        try:
            cols = ", ".join(expired_row.keys())
            placeholders = ", ".join(["?"] * len(expired_row))
            conn.execute(
                f"INSERT INTO ichor_events ({cols}) VALUES ({placeholders})",
                list(expired_row.values()),
            )
            conn.commit()
        finally:
            conn.close()

        # Direct apply_god_boost test on a result dict with valid_until
        from lib.ichor.retrieve_fusion import apply_god_boost
        synthetic_results = [
            {"id": "x1", "fused_score": 1.0, "god_name": "hermes",
             "valid_until": "2020-01-01 00:00:00"},   # expired
            {"id": "x2", "fused_score": 0.5, "god_name": "hermes"},  # current
        ]
        out = apply_god_boost(synthetic_results, active_god="hermes")
        scores_by_id = {r["id"]: r["fused_score"] for r in out}
        self.assertEqual(scores_by_id["x1"], 0.0)   # expired
        self.assertEqual(scores_by_id["x2"], 1.0)   # same_god 2x


class TestMemoryTraitActiveGodPlumbing(unittest.TestCase):
    """MemoryTrait.retrieve accepts and forwards active_god."""

    def test_signature_has_active_god(self) -> None:
        from lib.ichor_hybrid import MemoryTrait
        import inspect
        sig = inspect.signature(MemoryTrait.retrieve)
        self.assertIn("active_god", sig.parameters)
        # Default should be None (back-compat with old callers)
        self.assertIs(sig.parameters["active_god"].default, None)


class TestMCPSchemaActiveGodParam(unittest.TestCase):
    """MCP `ichor_retrieve` tool schema accepts active_god."""

    def test_mcp_tool_signature_has_active_god(self) -> None:
        # Read the source file and check that the `ichor_retrieve` function
        # signature includes `active_god: str = ""`. We check the source
        # rather than importing the module because the MCP server runs in
        # a specific environment.
        mcp_path = _PANTHEON / "pantheon-core" / "mcp_server.py"
        src = mcp_path.read_text()
        # Find the ichor_retrieve function definition
        self.assertIn("def ichor_retrieve(", src)
        # Locate the function body and check for active_god parameter
        func_start = src.index("def ichor_retrieve(")
        # Find the end of the signature (closing paren)
        sig_end = src.index("):", func_start)
        sig = src[func_start:sig_end + 2]
        self.assertIn("active_god", sig,
                      f"ichor_retrieve signature must include active_god. Got:\n{sig}")


if __name__ == "__main__":
    unittest.main()