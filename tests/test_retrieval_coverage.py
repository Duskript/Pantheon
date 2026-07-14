"""
Unit tests for lib.ichor.retrieval_coverage — Phase 3 helper module.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 3 (Retrieval Coverage / `total_matching`)

Coverage:

  * CoverageStats dataclass
    - Auto-computes coverage_pct when both inputs valid
    - coverage_pct is None when total_matching is None or 0
    - Auto-corrects coverage_confidence to "unknown" when
      total_matching is None and caller forgot to set it
    - Rejects invalid coverage_confidence values

  * aggregate_coverage()
    - Empty by_backend → coverage_confidence="unknown"
    - All known backends → "known" + sum of totals
    - Some known + some unknown → "partial" + sum of knowns
    - All unknown → "unknown" + total_matching=None
    - coverage_pct math: returned / total_matching * 100

  * Per-backend count functions (against live DB)
    - FTS5: count > 0 for a real query, 0 for empty
    - Events: count > 0 for a real query
    - Graph: count >= 0 for a real query
    - Reference: count > 0 for a real query
    - All return None for empty/unsafe input

  * count_for_backend() dispatch
    - Returns None for unknown backend names
    - Routes to the correct count function for each known backend
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.retrieval_coverage import (  # noqa: E402
    CoverageStats,
    aggregate_coverage,
    count_candidates_events,
    count_candidates_fts5,
    count_candidates_graph,
    count_candidates_reference,
    count_for_backend,
)


# ─────────────────────────────────────────────────────────────────────
# CoverageStats — pure unit tests
# ─────────────────────────────────────────────────────────────────────

class TestCoverageStats(unittest.TestCase):
    """Pure-function tests for the CoverageStats dataclass."""

    def test_auto_computes_coverage_pct(self) -> None:
        s = CoverageStats(returned=5, total_matching=100)
        self.assertEqual(s.coverage_pct, 5.0)

    def test_coverage_pct_rounded_to_2_decimals(self) -> None:
        s = CoverageStats(returned=1, total_matching=3)
        self.assertEqual(s.coverage_pct, 33.33)

    def test_coverage_pct_none_when_total_is_none(self) -> None:
        s = CoverageStats(
            returned=0, total_matching=None, coverage_confidence="unknown",
        )
        self.assertIsNone(s.coverage_pct)

    def test_coverage_pct_none_when_total_is_zero(self) -> None:
        s = CoverageStats(returned=0, total_matching=0)
        self.assertIsNone(s.coverage_pct)

    def test_auto_corrects_confidence_when_total_is_none(self) -> None:
        # Caller forgot to set unknown; we auto-fix it.
        s = CoverageStats(returned=0, total_matching=None)
        self.assertEqual(s.coverage_confidence, "unknown")

    def test_rejects_invalid_confidence(self) -> None:
        with self.assertRaises(ValueError):
            CoverageStats(
                returned=0, total_matching=10, coverage_confidence="maybe",
            )

    def test_explicit_unknown_is_preserved(self) -> None:
        s = CoverageStats(
            returned=0, total_matching=None, coverage_confidence="unknown",
        )
        self.assertEqual(s.coverage_confidence, "unknown")

    def test_to_dict_is_json_safe(self) -> None:
        s = CoverageStats(returned=3, total_matching=10)
        d = s.to_dict()
        import json
        # Must round-trip through JSON without errors
        json.dumps(d)
        self.assertEqual(d["returned"], 3)
        self.assertEqual(d["total_matching"], 10)
        self.assertEqual(d["coverage_pct"], 30.0)
        self.assertEqual(d["coverage_confidence"], "known")


# ─────────────────────────────────────────────────────────────────────
# aggregate_coverage — pure unit tests
# ─────────────────────────────────────────────────────────────────────

class TestAggregateCoverage(unittest.TestCase):
    """Pure-function tests for aggregate_coverage()."""

    def test_empty_by_backend(self) -> None:
        agg = aggregate_coverage({})
        self.assertEqual(agg["returned"], 0)
        self.assertEqual(agg["total_matching"], 0)
        self.assertIsNone(agg["coverage_pct"])
        self.assertEqual(agg["coverage_confidence"], "unknown")
        self.assertEqual(agg["by_backend"], {})

    def test_all_known(self) -> None:
        agg = aggregate_coverage({
            "fts5":   CoverageStats(returned=5, total_matching=100),
            "events": CoverageStats(returned=3, total_matching=50),
        })
        self.assertEqual(agg["returned"], 8)
        self.assertEqual(agg["total_matching"], 150)
        self.assertEqual(agg["coverage_pct"], round(100.0 * 8 / 150, 2))
        self.assertEqual(agg["coverage_confidence"], "known")

    def test_partial_known_some_unknown(self) -> None:
        agg = aggregate_coverage({
            "fts5":   CoverageStats(returned=5, total_matching=100),
            "vector": CoverageStats(
                returned=0, total_matching=None, coverage_confidence="unknown",
            ),
        })
        # Aggregate total is sum of knowns only (vector excluded)
        self.assertEqual(agg["returned"], 5)
        self.assertEqual(agg["total_matching"], 100)
        self.assertEqual(agg["coverage_pct"], 5.0)
        self.assertEqual(agg["coverage_confidence"], "partial")
        # vector still appears in by_backend with total_matching=None
        self.assertIn("vector", agg["by_backend"])
        self.assertIsNone(agg["by_backend"]["vector"]["total_matching"])
        self.assertEqual(agg["by_backend"]["vector"]["coverage_confidence"], "unknown")

    def test_all_unknown(self) -> None:
        agg = aggregate_coverage({
            "v1": CoverageStats(
                returned=0, total_matching=None, coverage_confidence="unknown",
            ),
            "v2": CoverageStats(
                returned=0, total_matching=None, coverage_confidence="unknown",
            ),
        })
        self.assertIsNone(agg["total_matching"])
        self.assertIsNone(agg["coverage_pct"])
        self.assertEqual(agg["coverage_confidence"], "unknown")

    def test_zero_total_matching_no_coverage_pct(self) -> None:
        agg = aggregate_coverage({
            "fts5": CoverageStats(returned=0, total_matching=0),
        })
        self.assertEqual(agg["total_matching"], 0)
        self.assertIsNone(agg["coverage_pct"])
        # Confidence is "known" because we successfully counted (got 0)
        self.assertEqual(agg["coverage_confidence"], "known")


# ─────────────────────────────────────────────────────────────────────
# Per-backend count functions — live DB tests
# ─────────────────────────────────────────────────────────────────────

class TestCountCandidatesFTS5(unittest.TestCase):
    """FTS5 count against the live ichor.db."""

    def test_real_query_returns_positive_count(self) -> None:
        n = count_candidates_fts5("conductor")
        self.assertIsNotNone(n)
        self.assertGreater(n, 0, "'conductor' should match many FTS5 rows")

    def test_gibberish_returns_zero(self) -> None:
        n = count_candidates_fts5("xyzzyx_unlikely_term_zzz")
        # Either 0 (no match) or None (sanitization dropped everything).
        # Either is acceptable — neither is a positive count.
        self.assertTrue(n is None or n == 0)

    def test_empty_string_returns_none(self) -> None:
        self.assertIsNone(count_candidates_fts5(""))

    def test_fts_special_chars_are_sanitized(self) -> None:
        # FTS5 operators should be stripped, not crash.
        # The exact count is unimportant — we just want no exception.
        n = count_candidates_fts5('"*:()')
        self.assertIsNone(n)  # all chars stripped → empty query


class TestCountCandidatesEvents(unittest.TestCase):
    """Events count against the live ichor.db."""

    def test_real_query_returns_positive_count(self) -> None:
        n = count_candidates_events("conductor")
        self.assertIsNotNone(n)
        self.assertGreater(n, 0)

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(count_candidates_events(""))


class TestCountCandidatesGraph(unittest.TestCase):
    """Graph count against the live graph.db."""

    def test_real_query_returns_count(self) -> None:
        n = count_candidates_graph("conductor")
        # Should be ≥ 0 (could be 0 if no graph nodes match).
        self.assertIsNotNone(n)
        self.assertGreaterEqual(n, 0)

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(count_candidates_graph(""))


class TestCountCandidatesReference(unittest.TestCase):
    """L2 reference count against the live ichor.db."""

    def test_real_query_returns_positive_count(self) -> None:
        n = count_candidates_reference("conductor")
        self.assertIsNotNone(n)
        self.assertGreater(n, 0, "warm_entities should have 'conductor' hits")

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(count_candidates_reference(""))


# ─────────────────────────────────────────────────────────────────────
# count_for_backend dispatch
# ─────────────────────────────────────────────────────────────────────

class TestCountForBackendDispatch(unittest.TestCase):
    """count_for_backend() routes to the right count function."""

    def test_unknown_backend_returns_none(self) -> None:
        self.assertIsNone(count_for_backend("not_a_backend", "conductor"))

    def test_dispatches_fts5(self) -> None:
        a = count_for_backend("fts5", "conductor")
        b = count_candidates_fts5("conductor")
        self.assertEqual(a, b)

    def test_dispatches_events(self) -> None:
        a = count_for_backend("events", "conductor")
        b = count_candidates_events("conductor")
        self.assertEqual(a, b)

    def test_dispatches_graph(self) -> None:
        a = count_for_backend("graph", "conductor")
        b = count_candidates_graph("conductor")
        self.assertEqual(a, b)

    def test_dispatches_reference(self) -> None:
        a = count_for_backend("reference", "conductor")
        b = count_candidates_reference("conductor")
        self.assertEqual(a, b)

    def test_vector_returns_int_or_none(self) -> None:
        """Vector is optional — could be int if embeddings exist, None if not."""
        n = count_for_backend("vector", "conductor")
        self.assertTrue(n is None or isinstance(n, int))
