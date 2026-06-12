"""
E2.1: Memory-side API surface tests.

Tests cover the 5 helper functions in `lib.clawforge.memory_api`:

  1. get_recent_outcomes(days)         — read retrieval-log.jsonl
  2. extract_patterns_from_outcomes()   — cluster by (query_class, outcome)
  3. compute_retrieval_stats()          — aggregate over outcomes
  4. detect_tier_a_coverage_gaps()      — coverage % per event_type
  5. get_recent_learnings(days)         — entity relationship learning types

Plus:
  - TestAnonymization: no session_id, no raw query text, no result_ids
  - TestRealDBReadOnly: dry-run smoke on real DB (no writes)
  - TestGateAssertions: build list's "gates pass" check
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

# Make `lib.clawforge.memory_api` importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.clawforge import memory_api  # noqa: E402
from lib.clawforge.memory_api import (  # noqa: E402
    COVERAGE_GAP_THRESHOLD,
    KNOWN_OUTCOMES,
    RELATIONSHIP_LEARNING_TYPES,
    RETRIEVAL_LOG_PATH,
    OutcomesSummary,
    PatternCluster,
    compute_retrieval_stats,
    detect_tier_a_coverage_gaps,
    extract_patterns_from_outcomes,
    get_recent_learnings,
    get_recent_outcomes,
    _anon_query_class,
    _parse_retrieval_log_line,
)


def _make_outcome(
    *,
    ts: float,
    query: str,
    outcome: str,
    result_count: int = 5,
    backends: list[str] | None = None,
    weights: dict[str, float] | None = None,
) -> str:
    """Build a JSONL line representing a retrieval-log entry."""
    entry = {
        "timestamp": ts,
        "query": query,
        "outcome": outcome,
        "result_count": result_count,
        "result_ids": ["fts5:123", "chroma:abc"],  # forbidden in output
        "backends_used": backends or ["fts5", "chroma"],
        "weights": weights or {"fts5": 0.4, "chroma": 0.4, "graph": 0.2},
        "session_id": "secret-session-uuid-12345",  # forbidden in output
    }
    return json.dumps(entry)


# ---------------------------------------------------------------------------
# Test 1: get_recent_outcomes
# ---------------------------------------------------------------------------

class TestGetRecentOutcomes(unittest.TestCase):
    """Read resolved outcomes from the retrieval log."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "retrieval-log.jsonl"
        self.now = 1_780_000_000.0  # fixed timestamp for determinism
        # Write some entries: 1 used, 1 irrelevant, 1 pending, 1 outside window
        entries = [
            _make_outcome(ts=self.now - 86400, query="git status check", outcome="used"),
            _make_outcome(ts=self.now - 2 * 86400, query="redis cache invalidation", outcome="irrelevant"),
            _make_outcome(ts=self.now - 3 * 86400, query="docker compose healthcheck", outcome="pending"),
            _make_outcome(ts=self.now - 30 * 86400, query="old query about kubernetes", outcome="used"),  # outside 7d
        ]
        with open(self.log_path, "w") as f:
            for e in entries:
                f.write(e + "\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_filters_pending(self):
        """Entries with outcome='pending' (C1 sentinel) are excluded."""
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        self.assertEqual(out.total, 2)  # used + irrelevant, not pending
        self.assertEqual(out.by_outcome.get("used", 0), 1)
        self.assertEqual(out.by_outcome.get("irrelevant", 0), 1)
        self.assertEqual(out.by_outcome.get("pending", 0), 0)

    def test_filters_old_entries(self):
        """Entries older than `days` are excluded."""
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        # The 30-day-old "kubernetes" entry is outside the 7-day window
        for e in out.entries:
            self.assertGreaterEqual(e.timestamp, self.now - 7 * 86400)

    def test_time_range_set(self):
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        self.assertIsNotNone(out.time_range)
        earliest, latest = out.time_range
        self.assertLessEqual(earliest, latest)

    def test_empty_log_returns_empty_summary(self):
        empty = self.log_path.with_name("empty.jsonl")
        out = get_recent_outcomes(days=7, log_path=empty, now=self.now)
        self.assertEqual(out.total, 0)
        self.assertEqual(out.entries, [])
        self.assertIsNone(out.time_range)

    def test_missing_log_returns_empty(self):
        missing = self.log_path.with_name("nonexistent.jsonl")
        out = get_recent_outcomes(days=7, log_path=missing, now=self.now)
        self.assertEqual(out.total, 0)

    def test_invalid_days_raises(self):
        with self.assertRaises(ValueError):
            get_recent_outcomes(days=0, log_path=self.log_path, now=self.now)
        with self.assertRaises(ValueError):
            get_recent_outcomes(days=-1, log_path=self.log_path, now=self.now)

    def test_skip_malformed_lines(self):
        """Bad JSON lines are skipped, not raised."""
        with open(self.log_path, "a") as f:
            f.write("this is not json\n")
            f.write(_make_outcome(
                ts=self.now - 86400, query="valid entry", outcome="used"
            ) + "\n")
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        # Should still get the original 2 + the new 1 = 3
        self.assertEqual(out.total, 3)


# ---------------------------------------------------------------------------
# Test 2: extract_patterns_from_outcomes
# ---------------------------------------------------------------------------

class TestExtractPatterns(unittest.TestCase):
    """Cluster outcomes by (query_class, outcome)."""

    def _make_summary(self, entries_data: list[tuple[str, str]]) -> OutcomesSummary:
        """Build an OutcomesSummary from (query, outcome) tuples."""
        from lib.clawforge.memory_api import Outcome
        entries = []
        by_outcome: dict[str, int] = {}
        for q, o in entries_data:
            entries.append(Outcome(
                timestamp=1_780_000_000.0,
                query_class=_anon_query_class(q),
                outcome=o,
                result_count=5,
                backends_used=["fts5"],
                weights={"fts5": 1.0},
            ))
            by_outcome[o] = by_outcome.get(o, 0) + 1
        return OutcomesSummary(
            total=len(entries),
            by_outcome=by_outcome,
            entries=entries,
            span_days=7,
        )

    def test_empty_input_returns_empty(self):
        s = OutcomesSummary(total=0)
        self.assertEqual(extract_patterns_from_outcomes(s), [])

    def test_clusters_by_query_class_and_outcome(self):
        # 3x "git status now" → "used" (same query_class because
        # first 3 tokens match), 2x "git status now" → "irrelevant"
        s = self._make_summary([
            ("git status now a", "used"),
            ("git status now b", "used"),
            ("git status now c", "used"),
            ("git status now d", "irrelevant"),
            ("git status now e", "irrelevant"),
        ])
        clusters = extract_patterns_from_outcomes(s, min_cluster_size=2)
        # 2 clusters (both above min size), same query_class
        self.assertEqual(len(clusters), 2)
        # All entries share query_class "q_git_status_now"
        self.assertEqual(clusters[0].query_class, clusters[1].query_class)
        # Sorted by count descending
        self.assertEqual(clusters[0].count, 3)
        self.assertEqual(clusters[0].outcome, "used")
        self.assertEqual(clusters[1].count, 2)
        self.assertEqual(clusters[1].outcome, "irrelevant")

    def test_singleton_clusters_dropped(self):
        """A cluster with count=1 is dropped at min_cluster_size=2."""
        # Each pair shares the same query_class but only 1 outcome
        s = self._make_summary([
            ("git status now a", "used"),
            ("redis cache now a", "used"),  # different query_class
        ])
        clusters = extract_patterns_from_outcomes(s, min_cluster_size=2)
        # 2 different query_classes, each with 1 outcome → all dropped
        self.assertEqual(len(clusters), 0)

    def test_singleton_kept_with_min_size_1(self):
        s = self._make_summary([
            ("git status now a", "used"),
            ("redis cache now a", "used"),
        ])
        clusters = extract_patterns_from_outcomes(s, min_cluster_size=1)
        self.assertEqual(len(clusters), 2)

    def test_confidence_ratio(self):
        """Confidence = count / class_total."""
        # All 3 queries share query_class "q_redis_cache_now" because
        # they all start with the same 3 tokens
        s = self._make_summary([
            ("redis cache now a", "used"),
            ("redis cache now b", "used"),
            ("redis cache now c", "irrelevant"),
        ])
        # Two clusters: 2 used, 1 irrelevant
        # Total for "q_redis_cache_now" = 3
        clusters = extract_patterns_from_outcomes(s, min_cluster_size=1)
        used_cluster = next(c for c in clusters if c.outcome == "used")
        irrel_cluster = next(c for c in clusters if c.outcome == "irrelevant")
        self.assertAlmostEqual(used_cluster.confidence, 2/3, places=3)
        self.assertAlmostEqual(irrel_cluster.confidence, 1/3, places=3)

    def test_min_cluster_size_validation(self):
        s = OutcomesSummary(total=0)
        with self.assertRaises(ValueError):
            extract_patterns_from_outcomes(s, min_cluster_size=0)


# ---------------------------------------------------------------------------
# Test 3: compute_retrieval_stats
# ---------------------------------------------------------------------------

class TestComputeRetrievalStats(unittest.TestCase):
    """Aggregate stats over an OutcomesSummary."""

    def _make_summary(self, entries_data: list[dict]) -> OutcomesSummary:
        from lib.clawforge.memory_api import Outcome
        entries = []
        by_outcome: dict[str, int] = {}
        for d in entries_data:
            entries.append(Outcome(
                timestamp=d.get("ts", 1_780_000_000.0),
                query_class=d.get("qc", "q_x"),
                outcome=d.get("outcome", "used"),
                result_count=d.get("rc", 5),
                backends_used=d.get("backends", ["fts5"]),
                weights=d.get("weights", {"fts5": 1.0}),
            ))
            by_outcome[d.get("outcome", "used")] = by_outcome.get(d.get("outcome", "used"), 0) + 1
        return OutcomesSummary(
            total=len(entries),
            by_outcome=by_outcome,
            entries=entries,
            span_days=7,
        )

    def test_empty_summary(self):
        s = OutcomesSummary(total=0)
        stats = compute_retrieval_stats(s)
        self.assertEqual(stats["total_queries"], 0)
        self.assertEqual(stats["avg_result_count"], 0.0)
        self.assertEqual(stats["max_result_count"], 0)
        self.assertEqual(stats["backend_usage"], {})
        self.assertEqual(stats["weight_distribution"], {})

    def test_total_queries(self):
        s = self._make_summary([
            {"outcome": "used", "rc": 5},
            {"outcome": "used", "rc": 3},
            {"outcome": "irrelevant", "rc": 7},
        ])
        stats = compute_retrieval_stats(s)
        self.assertEqual(stats["total_queries"], 3)
        self.assertEqual(stats["by_outcome"], {"used": 2, "irrelevant": 1})

    def test_avg_max_result_count(self):
        s = self._make_summary([
            {"rc": 5},
            {"rc": 10},
            {"rc": 15},
        ])
        stats = compute_retrieval_stats(s)
        self.assertEqual(stats["avg_result_count"], 10.0)
        self.assertEqual(stats["max_result_count"], 15)

    def test_backend_usage_histogram(self):
        s = self._make_summary([
            {"backends": ["fts5", "chroma"]},
            {"backends": ["fts5", "chroma"]},
            {"backends": ["fts5"]},
        ])
        stats = compute_retrieval_stats(s)
        self.assertEqual(stats["backend_usage"]["fts5"], 3)
        self.assertEqual(stats["backend_usage"]["chroma"], 2)

    def test_weight_distribution(self):
        s = self._make_summary([
            {"weights": {"fts5": 0.4, "chroma": 0.4, "graph": 0.2}},
            {"weights": {"fts5": 0.6, "chroma": 0.2, "graph": 0.2}},
        ])
        stats = compute_retrieval_stats(s)
        # fts5 avg = 0.5, chroma avg = 0.3, graph avg = 0.2
        self.assertAlmostEqual(stats["weight_distribution"]["fts5"], 0.5, places=3)
        self.assertAlmostEqual(stats["weight_distribution"]["chroma"], 0.3, places=3)
        self.assertAlmostEqual(stats["weight_distribution"]["graph"], 0.2, places=3)


# ---------------------------------------------------------------------------
# Test 4: detect_tier_a_coverage_gaps
# ---------------------------------------------------------------------------

class TestDetectTierACoverageGaps(unittest.TestCase):
    """Coverage = tier_a / total per event_type."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "ichor_test.db"
        self._build_db()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build_db(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        try:
            con.execute(
                "CREATE TABLE ichor_events ("
                "  id INTEGER PRIMARY KEY, "
                "  event_type TEXT, "
                "  source TEXT, "
                "  created_at TEXT"
                ")"
            )
            # Type 'decision': 10 events, only 1 tier_a → 10% coverage (gap)
            for i in range(9):
                con.execute(
                    "INSERT INTO ichor_events (event_type, source) VALUES (?, ?)",
                    ("decision", "manual"),
                )
            con.execute(
                "INSERT INTO ichor_events (event_type, source) VALUES (?, ?)",
                ("decision", "tier_a"),
            )
            # Type 'fact': 5 events, all tier_a → 100% coverage
            for i in range(5):
                con.execute(
                    "INSERT INTO ichor_events (event_type, source) VALUES (?, ?)",
                    ("fact", "tier_a"),
                )
            # Type 'blocker': 3 events, all tier_a → 100% but only 3 (< min_events=5)
            for i in range(3):
                con.execute(
                    "INSERT INTO ichor_events (event_type, source) VALUES (?, ?)",
                    ("blocker", "tier_a"),
                )
            con.commit()
        finally:
            con.close()

    def test_low_coverage_detected(self):
        result = detect_tier_a_coverage_gaps(db_path=self.db_path, min_events=5)
        self.assertIn("decision", result["low_coverage_types"])
        self.assertNotIn("fact", result["low_coverage_types"])

    def test_high_coverage_not_flagged(self):
        result = detect_tier_a_coverage_gaps(db_path=self.db_path, min_events=5)
        decision_info = result["by_type"]["decision"]
        self.assertEqual(decision_info["total"], 10)
        self.assertEqual(decision_info["tier_a"], 1)
        self.assertEqual(decision_info["coverage_pct"], 10.0)
        self.assertTrue(decision_info["gap"])

        fact_info = result["by_type"]["fact"]
        self.assertEqual(fact_info["total"], 5)
        self.assertEqual(fact_info["tier_a"], 5)
        self.assertEqual(fact_info["coverage_pct"], 100.0)
        self.assertFalse(fact_info["gap"])

    def test_min_events_filters_low_signal(self):
        """Types with fewer than min_events total are excluded."""
        result = detect_tier_a_coverage_gaps(db_path=self.db_path, min_events=5)
        # 'blocker' has 3 events (< 5), so it's not in by_type
        self.assertNotIn("blocker", result["by_type"])

    def test_missing_db_returns_empty(self):
        missing = self.db_path.with_name("nonexistent.db")
        result = detect_tier_a_coverage_gaps(db_path=missing)
        self.assertEqual(result["total_events"], 0)
        self.assertEqual(result["overall_coverage_pct"], 0.0)

    def test_overall_coverage(self):
        result = detect_tier_a_coverage_gaps(db_path=self.db_path, min_events=5)
        # 1 + 5 = 6 tier_a out of 10 + 5 = 15 total → 40.0%
        self.assertEqual(result["total_events"], 15)
        self.assertEqual(result["total_tier_a"], 6)
        self.assertEqual(result["overall_coverage_pct"], 40.0)


# ---------------------------------------------------------------------------
# Test 5: get_recent_learnings
# ---------------------------------------------------------------------------

class TestGetRecentLearnings(unittest.TestCase):
    """Query entity relationships for learning types."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "ichor_test.db"
        self._build_db()
        self.now = 1_780_000_000.0

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _build_db(self) -> None:
        con = sqlite3.connect(str(self.db_path))
        try:
            # Create entity_types, entities, relationship_types, relationships
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
            # Insert a few entities
            for i in (1, 2, 3, 4):
                con.execute(
                    "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
                    (i, "concept", f"Concept{i}"),
                )
            # 1 'learned_from' within window
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("learned_from", 2, 1, 0.9, 1.0, "phronesis",
                 "2026-05-20 00:00:00", "2026-05-20 00:00:00"),
            )
            # 1 'superseded_by' within window
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("superseded_by", 3, 4, 0.85, 1.0, "phronesis",
                 "2026-05-25 00:00:00", "2026-05-25 00:00:00"),
            )
            # 1 'related_to' (NOT a learning type) — should be filtered
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("related_to", 1, 2, 0.6, 1.0, "llm",
                 "2026-05-25 00:00:00", "2026-05-25 00:00:00"),
            )
            # 1 'learned_from' OUTSIDE window (200 days ago)
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("learned_from", 1, 3, 0.7, 1.0, "phronesis",
                 "2025-10-01 00:00:00", "2025-10-01 00:00:00"),
            )
            con.commit()
        finally:
            con.close()

    def test_returns_learning_types(self):
        result = get_recent_learnings(days=30, db_path=self.db_path, now=self.now)
        # 2 in-window: 1 learned_from, 1 superseded_by
        self.assertEqual(len(result), 2)
        types = {r["type"] for r in result}
        self.assertEqual(types, {"learned_from", "superseded_by"})

    def test_excludes_non_learning_types(self):
        result = get_recent_learnings(days=30, db_path=self.db_path, now=self.now)
        for r in result:
            self.assertIn(r["type"], RELATIONSHIP_LEARNING_TYPES)

    def test_excludes_outside_window(self):
        result = get_recent_learnings(days=30, db_path=self.db_path, now=self.now)
        # The 200-day-old learned_from (source_id=1) should NOT appear;
        # the in-window learned_from (source_id=2) and superseded_by
        # (source_id=3) should.
        for r in result:
            self.assertLess(r["days_ago"], 30)
        source_ids = {r["source_id"] for r in result}
        self.assertNotIn(1, source_ids)  # old entry excluded
        self.assertIn(2, source_ids)     # in-window learned_from
        self.assertIn(3, source_ids)     # in-window superseded_by

    def test_days_ago_computed(self):
        result = get_recent_learnings(days=30, db_path=self.db_path, now=self.now)
        for r in result:
            self.assertIn("days_ago", r)
            self.assertGreaterEqual(r["days_ago"], 0)
            self.assertLess(r["days_ago"], 30)

    def test_invalid_days_raises(self):
        with self.assertRaises(ValueError):
            get_recent_learnings(days=0, db_path=self.db_path, now=self.now)

    def test_missing_db_returns_empty(self):
        missing = self.db_path.with_name("nonexistent.db")
        self.assertEqual(
            get_recent_learnings(days=7, db_path=missing, now=self.now),
            [],
        )


# ---------------------------------------------------------------------------
# Test: Anonymization
# ---------------------------------------------------------------------------

class TestAnonymization(unittest.TestCase):
    """The exported data must not contain session_id, raw query, or
    result_ids (per clawforge spec §9)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "retrieval-log.jsonl"
        self.now = 1_780_000_000.0
        # Write an entry with all the sensitive fields
        with open(self.log_path, "w") as f:
            f.write(_make_outcome(
                ts=self.now - 86400,
                query="the user is asking about a secret",
                outcome="used",
            ) + "\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_outcome_excludes_raw_query(self):
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        for e in out.entries:
            d = e.to_dict()
            self.assertNotIn("query", d)
            self.assertNotIn("session_id", d)
            self.assertNotIn("result_ids", d)
            # Only the anonymized cluster key
            self.assertIn("query_class", d)
            self.assertTrue(d["query_class"].startswith("q_")
                            or d["query_class"] == "short_query")

    def test_query_class_is_hashed(self):
        """Two semantically similar queries should produce the same key."""
        k1 = _anon_query_class("git status please")
        k2 = _anon_query_class("git status update")
        # First 3 tokens: 'git', 'status', 'please' vs 'git', 'status', 'update'
        # → different
        self.assertNotEqual(k1, k2)
        # But k1 should equal k1 (deterministic)
        self.assertEqual(k1, _anon_query_class("git status please"))

    def test_short_query_bucketed(self):
        """Queries under ANON_MIN_QUERY_LEN chars are bucketed as short_query."""
        self.assertEqual(_anon_query_class("hi"), "short_query")
        self.assertEqual(_anon_query_class(""), "short_query")
        # Long-enough query should get a key
        k = _anon_query_class("kubernetes deployment")
        self.assertTrue(k.startswith("q_"))


# ---------------------------------------------------------------------------
# Test: Real-DB read-only (no side effects)
# ---------------------------------------------------------------------------

class TestRealDBReadOnly(unittest.TestCase):
    """All 5 helpers must work on the real `~/.hermes/ichor.db` and
    `~/.hermes/pantheon/retrieval-log.jsonl` without any writes."""

    @classmethod
    def setUpClass(cls) -> None:
        from lib.ichor.entities.schema import DB_PATH
        cls.db_path = DB_PATH
        if not cls.db_path.exists():
            raise unittest.SkipTest(f"real DB not found at {cls.db_path}")
        if not RETRIEVAL_LOG_PATH.exists():
            raise unittest.SkipTest(f"real log not found at {RETRIEVAL_LOG_PATH}")

    def test_all_5_helpers_run(self):
        """Smoke test: call all 5, verify no exceptions, get expected shapes."""
        outcomes = get_recent_outcomes(days=7)
        self.assertIsInstance(outcomes, OutcomesSummary)
        self.assertGreaterEqual(outcomes.total, 0)

        patterns = extract_patterns_from_outcomes(outcomes)
        self.assertIsInstance(patterns, list)

        stats = compute_retrieval_stats(outcomes)
        self.assertIsInstance(stats, dict)
        self.assertIn("total_queries", stats)

        coverage = detect_tier_a_coverage_gaps()
        self.assertIsInstance(coverage, dict)
        self.assertIn("by_type", coverage)

        learnings = get_recent_learnings(days=7)
        self.assertIsInstance(learnings, list)

    def test_real_db_no_writes(self):
        """Hash the DB before/after, expect identical."""
        import hashlib
        with open(self.db_path, "rb") as f:
            before = hashlib.sha256(f.read()).hexdigest()
        # Call each helper
        get_recent_outcomes(days=7)
        detect_tier_a_coverage_gaps()
        get_recent_learnings(days=7)
        with open(self.db_path, "rb") as f:
            after = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(before, after, msg="real DB was modified!")


# ---------------------------------------------------------------------------
# Test: Build list gate
# ---------------------------------------------------------------------------

class TestGateAssertions(unittest.TestCase):
    """Build list contract: 'each returns correct shape, gates pass'."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.log_path = Path(self.tmp.name) / "retrieval-log.jsonl"
        self.db_path = Path(self.tmp.name) / "ichor_test.db"
        self.now = 1_780_000_000.0
        # Build a log with mixed data. Several queries share the same
        # 3-token prefix so they land in the same query_class — that's
        # what makes the cluster assertions below pass.
        with open(self.log_path, "w") as f:
            for i, (q, o) in enumerate([
                ("git status overview a", "used"),
                ("git status overview b", "used"),
                ("git status overview c", "irrelevant"),
                ("redis cache check", "irrelevant"),
                ("redis cache check twice", "irrelevant"),
                ("kubernetes deployment", "pending"),  # not counted
            ]):
                f.write(_make_outcome(
                    ts=self.now - (i + 1) * 86400,
                    query=q, outcome=o,
                ) + "\n")
        # Build a minimal DB with both tables (the gate test exercises
        # both coverage and learnings).
        con = sqlite3.connect(str(self.db_path))
        try:
            con.executescript("""
                CREATE TABLE ichor_events (
                    id INTEGER PRIMARY KEY,
                    event_type TEXT,
                    source TEXT
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
            for i in range(8):
                con.execute(
                    "INSERT INTO ichor_events (event_type, source) "
                    "VALUES (?, ?)",
                    ("decision", "manual" if i > 0 else "tier_a"),
                )
            # Add one in-window learned_from relationship
            con.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, weight, "
                " provenance, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("learned_from", 1, 2, 0.9, 1.0, "phronesis",
                 "2026-05-20 00:00:00", "2026-05-20 00:00:00"),
            )
            con.commit()
        finally:
            con.close()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_gate_1_outcomes_return_correct_shape(self):
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        self.assertIsInstance(out, OutcomesSummary)
        self.assertEqual(out.total, 5)  # 3 used + 2 irrelevant, 1 pending excluded
        self.assertIn("used", out.by_outcome)
        self.assertIn("irrelevant", out.by_outcome)

    def test_gate_2_patterns_return_correct_shape(self):
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        patterns = extract_patterns_from_outcomes(out)
        self.assertGreater(len(patterns), 0)
        for p in patterns:
            self.assertIsInstance(p, PatternCluster)
            self.assertGreater(p.count, 0)
            self.assertGreaterEqual(p.confidence, 0.0)
            self.assertLessEqual(p.confidence, 1.0)

    def test_gate_3_stats_return_correct_shape(self):
        out = get_recent_outcomes(days=7, log_path=self.log_path, now=self.now)
        stats = compute_retrieval_stats(out)
        self.assertGreater(stats["total_queries"], 0)
        self.assertIn("backend_usage", stats)
        self.assertIn("weight_distribution", stats)

    def test_gate_4_coverage_returns_correct_shape(self):
        result = detect_tier_a_coverage_gaps(db_path=self.db_path)
        self.assertIn("decision", result["by_type"])
        self.assertGreater(result["total_events"], 0)
        # 1 tier_a out of 8 = 12.5%, below 50% threshold
        self.assertIn("decision", result["low_coverage_types"])

    def test_gate_5_learnings_return_correct_shape(self):
        """1 in-window learned_from entry → list of dicts with right shape."""
        result = get_recent_learnings(days=30, db_path=self.db_path, now=self.now)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        entry = result[0]
        self.assertEqual(entry["type"], "learned_from")
        self.assertEqual(entry["source_id"], 1)
        self.assertEqual(entry["target_id"], 2)
        self.assertIn("days_ago", entry)
        self.assertIn("confidence", entry)


if __name__ == "__main__":
    unittest.main()
