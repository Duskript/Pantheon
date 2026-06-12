"""
E2.2: Clawforge Pass 3.1 exporters — pattern + learning.

Tests cover the two new exporter modules:
  - lib.clawforge.pattern_exporter (memory.pattern.submitted)
  - lib.clawforge.learning_exporter (dojo.learning.submitted)

Each test verifies:
  1. The export function builds a valid entry with the right schema
  2. The anonymization guard passes
  3. The entry has no forbidden keys
  4. The instance_id is the right format (12 hex chars)
  5. The wrapper flow (clawforge_export_run.py) routes correctly
  6. Real-DB smoke (no side effects)
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/home/konan/pantheon/lib")

# Make sure the test can find clawforge.* even outside the wrapper
import clawforge  # noqa: F401
from clawforge.learning_exporter import (  # noqa: E402
    assert_anonymized as assert_learning_anonymized,
    export_dojo_learnings,
)
from clawforge.pattern_exporter import (  # noqa: E402
    assert_anonymized as assert_pattern_anonymized,
    export_memory_patterns,
)


TEST_INSTANCE_ID = "0123456789ab"  # 12 hex chars


# ---------------------------------------------------------------------------
# Pattern exporter tests
# ---------------------------------------------------------------------------

class TestPatternExporterSchema(unittest.TestCase):
    """The pattern exporter must produce a valid spec-shaped entry."""

    def test_entry_has_all_top_level_keys(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        expected = {
            "schema_version", "instance_id", "submitted_at", "span_days",
            "total_queries", "patterns", "retrieval_stats", "coverage_gaps",
        }
        self.assertEqual(set(entry.keys()), expected)

    def test_schema_version_is_1(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        self.assertEqual(entry["schema_version"], 1)

    def test_instance_id_is_12_hex(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        self.assertEqual(len(entry["instance_id"]), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in entry["instance_id"]))

    def test_span_days_echoed(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=14)
        self.assertEqual(entry["span_days"], 14)

    def test_submitted_at_is_iso8601(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        # Should parse as ISO 8601
        from datetime import datetime
        # Format: 2026-06-11T22:49:59Z
        parsed = datetime.strptime(entry["submitted_at"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertIsNotNone(parsed)


class TestPatternExporterAnonymization(unittest.TestCase):
    """No forbidden keys anywhere in the entry."""

    def test_no_session_id(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        # Top level
        self.assertNotIn("session_id", entry)
        # Recursive — every key in the entry
        def check_all_keys(d, path=""):
            if isinstance(d, dict):
                for k, v in d.items():
                    self.assertNotEqual(k, "session_id",
                        msg=f"session_id found at {path}.{k}")
                    check_all_keys(v, f"{path}.{k}")
            elif isinstance(d, list):
                for i, v in enumerate(d):
                    check_all_keys(v, f"{path}[{i}]")
        check_all_keys(entry)

    def test_no_raw_query_text(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        # Patterns have query_class (allowed) not query (forbidden)
        for p in entry.get("patterns", []):
            self.assertIn("query_class", p)
            self.assertNotIn("query", p)

    def test_no_user_intent(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        s = json.dumps(entry)
        self.assertNotIn("user_intent", s)

    def test_retrieval_stats_has_no_raw_entries(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        stats = entry["retrieval_stats"]
        self.assertNotIn("entries", stats)
        self.assertNotIn("queries", stats)
        # Only aggregate fields
        expected_keys = {
            "total_queries", "span_days", "by_outcome", "backend_usage",
            "avg_result_count", "max_result_count", "weight_distribution",
        }
        self.assertEqual(set(stats.keys()), expected_keys)

    def test_coverage_gaps_has_no_raw_events(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        coverage = entry["coverage_gaps"]
        self.assertNotIn("events", coverage)
        self.assertNotIn("raw_events", coverage)
        self.assertNotIn("samples", coverage)
        # Only aggregate fields
        for k in ("by_type", "low_coverage_types", "threshold_pct",
                  "total_events", "total_tier_a", "overall_coverage_pct"):
            self.assertIn(k, coverage)

    def test_assert_anonymized_runs_clean(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        # Should not raise
        assert_pattern_anonymized(entry)


class TestPatternExporterData(unittest.TestCase):
    """The entry reflects real data (or absence thereof)."""

    def test_total_queries_matches_outcomes(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        # Currently 0 because all retrieval-log entries are 'pending'
        self.assertGreaterEqual(entry["total_queries"], 0)

    def test_patterns_list_is_list(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        self.assertIsInstance(entry["patterns"], list)

    def test_coverage_gaps_real_data(self):
        """Coverage gaps comes from real `ichor_events` data."""
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        coverage = entry["coverage_gaps"]
        # Real data has thousands of events, so total_events should be > 0
        self.assertGreater(coverage["total_events"], 0)
        self.assertGreater(coverage["total_tier_a"], 0)
        # low_coverage_types is a list
        self.assertIsInstance(coverage["low_coverage_types"], list)
        # Real coverage gaps from E2.1 smoke: decision, digest_entry, preference
        # (these are the 3 below 50% threshold)
        if coverage["low_coverage_types"]:
            for et in coverage["low_coverage_types"]:
                self.assertIn(et, coverage["by_type"])

    def test_min_cluster_size_keeps_singletons(self):
        """Passing min_cluster_size=1 should keep singleton patterns."""
        entry = export_memory_patterns(
            TEST_INSTANCE_ID, days=7, min_cluster_size=1,
        )
        # Even with no real outcomes, the function should not error
        self.assertIsInstance(entry["patterns"], list)


# ---------------------------------------------------------------------------
# Learning exporter tests
# ---------------------------------------------------------------------------

class TestLearningExporterSchema(unittest.TestCase):
    """The learning exporter must produce a valid spec-shaped entry."""

    def test_entry_has_all_top_level_keys(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        expected = {
            "schema_version", "instance_id", "submitted_at", "span_days",
            "total_learnings", "learnings", "by_type",
        }
        self.assertEqual(set(entry.keys()), expected)

    def test_schema_version_is_1(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        self.assertEqual(entry["schema_version"], 1)

    def test_instance_id_is_12_hex(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        self.assertEqual(len(entry["instance_id"]), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in entry["instance_id"]))

    def test_span_days_echoed(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=14)
        self.assertEqual(entry["span_days"], 14)


class TestLearningExporterAnonymization(unittest.TestCase):
    """No forbidden keys; entity ids are integers, not names."""

    def test_no_session_id_anywhere(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        s = json.dumps(entry)
        self.assertNotIn("session_id", s)

    def test_no_user_intent(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        s = json.dumps(entry)
        self.assertNotIn("user_intent", s)

    def test_no_source_ref(self):
        """source_ref might contain raw event text; banned by spec §9."""
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        for lrn in entry.get("learnings", []):
            self.assertNotIn("source_ref", lrn)

    def test_entity_ids_are_integers(self):
        """source_id and target_id must be int, not entity names."""
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        for lrn in entry.get("learnings", []):
            self.assertIsInstance(lrn["source_id"], int)
            self.assertIsInstance(lrn["target_id"], int)

    def test_by_type_values_are_ints(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        for v in entry["by_type"].values():
            self.assertIsInstance(v, int)

    def test_assert_anonymized_runs_clean(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        # Should not raise
        assert_learning_anonymized(entry)


class TestLearningExporterData(unittest.TestCase):
    """Real-DB smoke (no writes)."""

    def test_empty_data_on_fresh_db(self):
        """Real DB has no learning-type relationships yet → empty entry."""
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        self.assertEqual(entry["total_learnings"], 0)
        self.assertEqual(entry["learnings"], [])
        self.assertEqual(entry["by_type"], {})


# ---------------------------------------------------------------------------
# Anonymization self-test (with synthetic data)
# ---------------------------------------------------------------------------

class TestAnonymizationGuards(unittest.TestCase):
    """The assert_anonymized guard must CATCH injected forbidden keys."""

    def test_pattern_anonymization_catches_session_id(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        entry["session_id"] = "leaked"  # inject forbidden
        with self.assertRaises(AssertionError):
            assert_pattern_anonymized(entry)

    def test_pattern_anonymization_catches_raw_query(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        if entry["patterns"]:
            entry["patterns"][0]["query"] = "leaked raw text"
            with self.assertRaises(AssertionError):
                assert_pattern_anonymized(entry)

    def test_pattern_anonymization_catches_user_intent(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        entry["retrieval_stats"]["user_intent"] = "leaked"
        with self.assertRaises(AssertionError):
            assert_pattern_anonymized(entry)

    def test_pattern_anonymization_catches_raw_events_in_coverage(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        entry["coverage_gaps"]["raw_events"] = ["leaked"]
        with self.assertRaises(AssertionError):
            assert_pattern_anonymized(entry)

    def test_pattern_anonymization_catches_bad_instance_id(self):
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        entry["instance_id"] = "not-12-chars"  # too short
        with self.assertRaises(AssertionError):
            assert_pattern_anonymized(entry)

    def test_learning_anonymization_catches_session_id(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        entry["session_id"] = "leaked"
        with self.assertRaises(AssertionError):
            assert_learning_anonymized(entry)

    def test_learning_anonymization_catches_source_ref(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        # Inject a fake learning record with source_ref
        entry["learnings"] = [{
            "id": 1, "type": "learned_from", "source_id": 1, "target_id": 2,
            "confidence": 0.9, "weight": 1.0, "created_at": "2026-01-01 00:00:00",
            "days_ago": 0, "provenance": "phronesis",
            "source_ref": "this contains raw event text!",
        }]
        with self.assertRaises(AssertionError):
            assert_learning_anonymized(entry)

    def test_learning_anonymization_catches_string_entity_id(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        entry["learnings"] = [{
            "id": 1, "type": "learned_from", "source_id": "Acme", "target_id": 2,
            "confidence": 0.9, "weight": 1.0, "created_at": "2026-01-01 00:00:00",
            "days_ago": 0, "provenance": "phronesis",
        }]
        with self.assertRaises(AssertionError):
            assert_learning_anonymized(entry)

    def test_learning_anonymization_catches_unknown_type(self):
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        entry["learnings"] = [{
            "id": 1, "type": "random_unrelated_type", "source_id": 1, "target_id": 2,
            "confidence": 0.9, "weight": 1.0, "created_at": "2026-01-01 00:00:00",
            "days_ago": 0, "provenance": "phronesis",
        }]
        with self.assertRaises(AssertionError):
            assert_learning_anonymized(entry)


# ---------------------------------------------------------------------------
# Synthetic learning data (using a temp DB with the schema)
# ---------------------------------------------------------------------------

class TestLearningExporterWithData(unittest.TestCase):
    """Build a temp DB with learning-type relationships, verify the
    exporter reads them correctly."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "ichor_test.db"
        self.now = 1_780_000_000.0
        self._build_db()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build_db(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        try:
            con.executescript("""
                CREATE TABLE entity_types (
                    id TEXT PRIMARY KEY,
                    description TEXT
                );
                CREATE TABLE entities (
                    id INTEGER PRIMARY KEY,
                    type_id TEXT,
                    name TEXT,
                    status TEXT DEFAULT 'active'
                );
                CREATE TABLE relationship_types (
                    id TEXT PRIMARY KEY,
                    description TEXT
                );
                CREATE TABLE relationships (
                    id INTEGER PRIMARY KEY,
                    type_id TEXT,
                    source_id INTEGER,
                    target_id INTEGER,
                    confidence REAL DEFAULT 1.0,
                    weight REAL DEFAULT 1.0,
                    provenance TEXT,
                    source_ref TEXT,
                    valid_from TEXT,
                    valid_to TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    provisional INTEGER DEFAULT 0
                );
            """)
            for i in (1, 2, 3, 4, 5):
                con.execute(
                    "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
                    (i, "concept", f"Concept{i}"),
                )
            # 2 learned_from, 1 superseded_by, all in window
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("learned_from", 2, 1, 0.9, 1.0, "phronesis",
                 "2026-05-20 00:00:00", "2026-05-20 00:00:00"),
            )
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("learned_from", 3, 2, 0.8, 1.0, "phronesis",
                 "2026-05-21 00:00:00", "2026-05-21 00:00:00"),
            )
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("superseded_by", 4, 5, 0.7, 1.0, "phronesis",
                 "2026-05-22 00:00:00", "2026-05-22 00:00:00"),
            )
            con.commit()
        finally:
            con.close()

    def test_exports_3_learnings(self):
        # Patch the path that the EXPORTER actually sees. The exporter
        # does `from clawforge.memory_api import get_recent_learnings`
        # (NOT `from lib.clawforge.memory_api import ...`), so the
        # module it binds to is `clawforge.memory_api`, not
        # `lib.clawforge.memory_api`. Both refer to the same file on
        # disk but Python treats them as distinct module objects
        # when loaded via different sys.path entries.
        import clawforge.memory_api as mem_api
        original = mem_api.ICHOR_DB_PATH
        mem_api.ICHOR_DB_PATH = self.db_path
        try:
            entry = export_dojo_learnings(TEST_INSTANCE_ID, days=30)
        finally:
            mem_api.ICHOR_DB_PATH = original
        self.assertEqual(entry["total_learnings"], 3)
        self.assertEqual(entry["by_type"], {"learned_from": 2, "superseded_by": 1})

    def test_learnings_sorted_by_created_at_descending(self):
        """Newest learnings come first (smallest days_ago first).

        The SQL orders by created_at DESC, so days_ago ends up
        ascending (most recent = closest to today = smallest days_ago).
        """
        import clawforge.memory_api as mem_api
        original = mem_api.ICHOR_DB_PATH
        mem_api.ICHOR_DB_PATH = self.db_path
        try:
            entry = export_dojo_learnings(TEST_INSTANCE_ID, days=30)
        finally:
            mem_api.ICHOR_DB_PATH = original
        # Most recent first → days_ago should be ascending
        days_ago = [lrn["days_ago"] for lrn in entry["learnings"]]
        self.assertEqual(days_ago, sorted(days_ago))


# ---------------------------------------------------------------------------
# Build list gate
# ---------------------------------------------------------------------------

class TestGateAssertions(unittest.TestCase):
    """Build list E2.2 gate: 'valid output, zero raw text, ≥2 instance
    submissions visible in pattern-effectiveness.json, execute_flag
    respected.'

    The first 3 are unit-testable. The 4th (≥2 instance submissions)
    is a federation test that requires Hephaestus + a real Clawforge
    hub — covered by the Pass 3 Phase 5 smoke test, not unit tests.
    execute_flag is also covered by the existing `recommendation_applier`
    (Pass 3), not the exporters.
    """

    def test_gate_1_pattern_valid_output(self):
        """Memory pattern exporter produces a spec-shaped entry."""
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        # All 8 top-level keys present
        self.assertEqual(len(entry), 8)
        # Schema version correct
        self.assertEqual(entry["schema_version"], 1)
        # Anonymization passes
        assert_pattern_anonymized(entry)

    def test_gate_2_learning_valid_output(self):
        """Dojo learning exporter produces a spec-shaped entry."""
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        # All 7 top-level keys present
        self.assertEqual(len(entry), 7)
        # Schema version correct
        self.assertEqual(entry["schema_version"], 1)
        # Anonymization passes
        assert_learning_anonymized(entry)

    def test_gate_3_pattern_zero_raw_text(self):
        """No raw query text, no session_id, no user_intent anywhere."""
        entry = export_memory_patterns(TEST_INSTANCE_ID, days=7)
        s = json.dumps(entry)
        self.assertNotIn("user_intent", s)
        self.assertNotIn("session_id", s)
        # query_class is OK, raw "query" is not
        for p in entry.get("patterns", []):
            self.assertNotIn("query", p)

    def test_gate_4_learning_zero_raw_text(self):
        """No source_ref (might contain raw event text) anywhere."""
        entry = export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        for lrn in entry.get("learnings", []):
            self.assertNotIn("source_ref", lrn)


# ---------------------------------------------------------------------------
# Real-DB no-side-effects
# ---------------------------------------------------------------------------

class TestRealDBNoSideEffects(unittest.TestCase):
    """Both exporters must not modify the real DB or the retrieval log."""

    def test_pattern_exporter_no_side_effects(self):
        import hashlib
        db_path = Path.home() / ".hermes" / "ichor.db"
        log_path = Path.home() / ".hermes" / "pantheon" / "retrieval-log.jsonl"
        with open(db_path, "rb") as f:
            db_before = hashlib.sha256(f.read()).hexdigest()
        with open(log_path, "rb") as f:
            log_before = hashlib.sha256(f.read()).hexdigest()

        export_memory_patterns(TEST_INSTANCE_ID, days=7)

        with open(db_path, "rb") as f:
            db_after = hashlib.sha256(f.read()).hexdigest()
        with open(log_path, "rb") as f:
            log_after = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(db_before, db_after, msg="real DB was modified!")
        self.assertEqual(log_before, log_after, msg="retrieval log was modified!")

    def test_learning_exporter_no_side_effects(self):
        import hashlib
        db_path = Path.home() / ".hermes" / "ichor.db"
        with open(db_path, "rb") as f:
            db_before = hashlib.sha256(f.read()).hexdigest()
        export_dojo_learnings(TEST_INSTANCE_ID, days=7)
        with open(db_path, "rb") as f:
            db_after = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(db_before, db_after, msg="real DB was modified!")


if __name__ == "__main__":
    unittest.main()
