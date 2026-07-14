"""
Ichor-Retrieval Phase 3 contract tests.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 3 (retrieval coverage / total_matching)

This file replaced the original Phase 0 baseline + Phase 3 xfail
placeholder tests once Phase 3 shipped. The old baseline tests
documented the OLD broken response shape (no `returned`, no
`total_matching`, no coverage block). They've been converted into
positive tests that prove the NEW shape is in effect.

What this file proves:

  * `returned` and `total_matching` are distinct fields in the response
    (no longer one overloaded `total` field).
  * `coverage_pct` and `coverage_confidence` are present and
    structured.
  * `by_backend` is present and contains per-backend returned /
    total_matching / coverage_pct / coverage_confidence.
  * `total_matching: null` is paired with `coverage_confidence:
    "unknown"` — never silently treated as 100%.
  * For a real query (e.g. "conductor") where many candidates exist,
    `returned` is provably smaller than `total_matching` — that's the
    smoking-gun acceptance criterion from the spec ("total no longer
    masquerades as total matching evidence").

No service restart required: tests use the read-only retrieve path
against the live DB. Tests do not write to the DB.
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any, Dict, List

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor_hybrid import MemoryTrait  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _retrieve(
    query: str = "conductor",
    limit: int = 5,
    backends: List[str] | None = None,
) -> Dict[str, Any]:
    """Run a real MemoryTrait.retrieve() against the live DB.

    The call is read-only. No service restart is required because
    the path is in-process — `MemoryTrait` is a Python class, not a
    long-running daemon. The retrieve call itself does not mutate
    any tables (it appends to a JSONL log file in
    `~/.hermes/pantheon/retrieval-log.jsonl`, which is non-fatal and
    outside the DB).
    """
    trait = MemoryTrait()
    kwargs: Dict[str, Any] = dict(
        query=query, limit=limit, output_format="json", active_god=None,
    )
    if backends is not None:
        kwargs["backends"] = backends
    return trait.retrieve(**kwargs)


# ─────────────────────────────────────────────────────────────────────
# Phase 3 contract — response shape
# ─────────────────────────────────────────────────────────────────────

class TestContract(unittest.TestCase):
    """Phase 3 deliverables — coverage and total_matching."""

    def test_response_has_returned_and_total_matching(self) -> None:
        """Spec AC: returned and total_matching are distinct fields."""
        result = _retrieve("conductor", limit=5)
        self.assertIn("returned", result, "Phase 3 must expose 'returned'")
        self.assertIn(
            "total_matching", result,
            "Phase 3 must expose 'total_matching' separate from 'returned'",
        )
        self.assertIsInstance(result["returned"], int)
        self.assertTrue(
            result["total_matching"] is None
            or isinstance(result["total_matching"], int),
            "total_matching must be int or null (unknown)",
        )

    def test_response_has_coverage_block(self) -> None:
        """Spec AC: coverage_pct + coverage_confidence in response."""
        result = _retrieve("conductor", limit=5)
        self.assertIn("coverage_pct", result)
        self.assertIn("coverage_confidence", result)
        self.assertIn(result["coverage_confidence"], ("known", "partial", "unknown"))

    def test_response_has_per_backend_breakdown(self) -> None:
        """Spec AC: per-backend coverage appears in response."""
        result = _retrieve("conductor", limit=5)
        self.assertIn("by_backend", result)
        by_backend = result["by_backend"]
        self.assertIsInstance(by_backend, dict)
        self.assertGreater(
            len(by_backend), 0,
            "by_backend must list every attempted backend",
        )
        for backend_name, stats in by_backend.items():
            self.assertIn("returned", stats, f"{backend_name} missing 'returned'")
            self.assertIn(
                "total_matching", stats,
                f"{backend_name} missing 'total_matching'",
            )
            self.assertIn(
                "coverage_pct", stats,
                f"{backend_name} missing 'coverage_pct'",
            )
            self.assertIn(
                "coverage_confidence", stats,
                f"{backend_name} missing 'coverage_confidence'",
            )

    def test_unknown_coverage_is_explicit(self) -> None:
        """Spec AC: When a backend can't count, mark it unknown.

        Spec §Phase 3:
          > If a backend cannot cheaply count:
          >     {"total_matching": null, "coverage_confidence": "unknown"}
          > Do not fabricate counts.
        """
        result = _retrieve("conductor", limit=5)
        by_backend = result.get("by_backend", {})
        for backend_name, stats in by_backend.items():
            if stats.get("total_matching") is None:
                self.assertEqual(
                    stats.get("coverage_confidence"), "unknown",
                    f"{backend_name} has total_matching=None but "
                    f"coverage_confidence={stats.get('coverage_confidence')!r}; "
                    f"spec requires 'unknown' when count is unavailable",
                )

    def test_total_no_longer_masquerades_as_total_matching(self) -> None:
        """Spec AC: `total` no longer masquerades as total matching evidence.

        The smoking-gun test. With Phase 3, "conductor" matches tens of
        thousands of candidates across all backends but only a handful
        are returned. The legacy `total` field would say 5; the new
        `total_matching` says many thousands. Proving they're
        DIFFERENT is the contract.
        """
        result = _retrieve("conductor", limit=5)

        # Both fields exist
        self.assertIn("total", result)
        self.assertIn("total_matching", result)

        total = result["total"]
        tm = result["total_matching"]

        # total_matching must be either int or None — never the same
        # as `total`. None is allowed for unknown (e.g. all backends
        # couldn't count), but the test query "conductor" matches
        # plenty, so None here would be a regression.
        self.assertIsNotNone(
            tm,
            "total_matching should not be None for a query that "
            "matches plenty — at least one backend should count",
        )
        self.assertIsInstance(tm, int)

        # The smoking gun: for "conductor" the candidate count is
        # orders of magnitude larger than the returned count.
        self.assertGreater(
            tm, total,
            f"total_matching ({tm}) must be > total ({total}) — "
            f"if they're equal, Phase 3 has regressed and `total` "
            f"is once again masquerading as total matching evidence",
        )

    def test_returned_equals_total_legacy_alias(self) -> None:
        """Legacy `total` field preserved as alias for `returned`.

        Spec: keep backward compat. The legacy `total` field equals
        `returned` (post-dedup, post-cap) — it's NOT total_matching.
        """
        result = _retrieve("conductor", limit=5)
        self.assertEqual(
            result["total"], result["returned"],
            "Legacy `total` field must equal `returned` (alias), "
            "NOT `total_matching`",
        )

    def test_empty_query_path_returns_coverage(self) -> None:
        """Even with zero results, coverage metadata is present."""
        # Use fts5-only to force the empty-result branch
        result = _retrieve(
            "xyzzyx_unlikely_to_match_anything_zzz",
            limit=5,
            backends=["fts5"],
        )
        self.assertEqual(result["returned"], 0)
        # by_backend still has fts5 entry with returned=0
        self.assertIn("fts5", result["by_backend"])
        fts5_stats = result["by_backend"]["fts5"]
        self.assertEqual(fts5_stats["returned"], 0)


# ─────────────────────────────────────────────────────────────────────
# Per-result metadata — coverage stays at response level, not per result
# ─────────────────────────────────────────────────────────────────────

class TestPerResultMetadata(unittest.TestCase):
    """Coverage stays at the RESPONSE level (by_backend block), not on
    each individual result row.

    Rationale: putting coverage on every result would duplicate the
    same numbers N times. The response-level breakdown is the single
    source of truth; per-result rows carry rank_reasons, score, and
    hydration metadata (added in Phase 4).
    """

    def test_results_do_not_carry_backend_count_metadata(self) -> None:
        result = _retrieve("conductor", limit=5)
        results = result.get("results", [])
        if results:
            sample = results[0]
            self.assertNotIn("backend_total_matching", sample)
            self.assertNotIn("backend_returned", sample)
            self.assertNotIn("coverage_pct", sample)
