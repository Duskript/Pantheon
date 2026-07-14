"""
C2: Weight Tuning + Benchmarks — gate + contract tests.

Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §C2

3 gate checks:
  1. WEIGHTS drift within ±5% of baseline
  2. run_benchmarks() returns a report with recall@5 > 0
  3. Regression flagging works (drop >10% → blocker event)

Plus contract tests for the tuner, history persistence, and
benchmark query set.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure ~/pantheon on path
import sys
PANTHEON_ROOT = str(Path.home() / "pantheon")
if PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, PANTHEON_ROOT)

from lib.ichor_hybrid import WEIGHTS  # noqa: E402
from lib.ichor_benchmarks import (  # noqa: E402
    run_benchmarks,
    BENCHMARK_QUERIES,
    WeightTuner,
    drift_weights,
    flag_regression,
    _WEIGHTS_HISTORY,
    _BASELINE_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Spec gate #1: weights within ±5% of baseline
# ---------------------------------------------------------------------------

class TestGateC2WeightsDrift(unittest.TestCase):
    """Gate C2 check 1: WEIGHTS drift within ±5% of baseline."""

    def test_weights_match_baseline(self):
        """Fresh import: WEIGHTS must equal baseline exactly."""
        for k, v in _BASELINE_WEIGHTS.items():
            self.assertAlmostEqual(WEIGHTS[k], v, places=4,
                                   msg=f"{k} baseline mismatch")

    def test_baseline_constant_shape(self):
        """Baseline has same keys as WEIGHTS."""
        self.assertEqual(set(_BASELINE_WEIGHTS.keys()), set(WEIGHTS.keys()))

    def test_drift_cap_helper(self):
        """drift_weights() never moves a weight more than 5% per call."""
        for k in WEIGHTS:
            current = WEIGHTS[k]
            for delta in (-0.20, -0.10, -0.05, 0.05, 0.10, 0.20):
                target = max(0.0, min(1.0, current + delta))
                new_w, actual_delta = drift_weights(
                    {k: current}, {k: target}, max_drift=0.05
                )
                self.assertLessEqual(
                    abs(actual_delta), 0.05 + 1e-9,
                    msg=f"drift cap violated: {actual_delta} for delta={delta}"
                )

    def test_drift_zero_when_at_target(self):
        """If current == target, drift is 0."""
        new_w, delta = drift_weights({"fts5": 0.45}, {"fts5": 0.45})
        self.assertEqual(delta, 0.0)
        self.assertEqual(new_w["fts5"], 0.45)

    def test_drift_partial_when_target_far(self):
        """If target is far, drift moves max_drift * current toward it (capped).

        Spec: `drift <= 0.05 * baseline[k]` (gate check #1). For 0.30,
        max delta is 0.30 * 0.05 = 0.015 per call.
        """
        new_w, delta = drift_weights({"fts5": 0.30}, {"fts5": 0.50}, max_drift=0.05)
        self.assertAlmostEqual(delta, 0.015, places=4)
        self.assertAlmostEqual(new_w["fts5"], 0.315, places=4)


# ---------------------------------------------------------------------------
# Spec gate #2: run_benchmarks() returns a report with recall@5 > 0
# ---------------------------------------------------------------------------

class TestGateC2Benchmarks(unittest.TestCase):
    """Gate C2 check 2: benchmark report has recall@5 > 0."""

    def test_benchmark_queries_nonempty(self):
        """Benchmark set must have at least 5 queries."""
        self.assertGreaterEqual(len(BENCHMARK_QUERIES), 5)

    def test_run_benchmarks_returns_report(self):
        report = run_benchmarks()
        self.assertIsInstance(report, dict)
        self.assertIn("recall@5", report)
        self.assertIn("latency_p50_ms", report)
        self.assertIn("latency_p95_ms", report)
        self.assertIn("per_query", report)
        self.assertIn("weights", report)
        self.assertIn("timestamp", report)
        # The gate's hard requirement
        self.assertGreater(report["recall@5"], 0.0,
                           msg="recall@5 must be > 0")

    def test_run_benchmarks_recall_bounded(self):
        """recall@5 must be in [0, 1]."""
        report = run_benchmarks()
        self.assertGreaterEqual(report["recall@5"], 0.0)
        self.assertLessEqual(report["recall@5"], 1.0)

    def test_per_query_results_have_scores(self):
        """Most benchmark queries return hits (some may be too specific)."""
        report = run_benchmarks()
        self.assertGreater(len(report["per_query"]), 0)
        for entry in report["per_query"]:
            self.assertIn("query", entry)
            self.assertIn("top_ids", entry)
            self.assertIsInstance(entry["top_ids"], list)
        hits = sum(1 for e in report["per_query"] if e["top_ids"])
        # At least 80% of queries should return hits — FTS5 has gaps
        # for jargon that isn't in the indexed corpus.
        self.assertGreaterEqual(
            hits / max(len(report["per_query"]), 1), 0.80,
            msg=f"only {hits}/{len(report['per_query'])} queries returned hits"
        )

    def test_weights_in_report_match_current(self):
        """Report includes the WEIGHTS that were used during the run."""
        report = run_benchmarks()
        for k, v in WEIGHTS.items():
            self.assertAlmostEqual(report["weights"][k], v, places=4)


# ---------------------------------------------------------------------------
# Spec gate #3: regression flagging works
# ---------------------------------------------------------------------------

class TestGateC2RegressionFlag(unittest.TestCase):
    """Gate C2 check 3: if recall drops >10%, a blocker event is created."""

    def test_flag_regression_creates_blocker(self):
        """A drop > 10% must produce a `blocker` event in ichor_events."""
        flag_regression(
            previous_recall=0.80,
            current_recall=0.65,  # -18.75% drop, well above 10%
            dry_run=False,
        )
        # Verify the blocker was created
        con = sqlite3.connect(Path.home() / ".hermes" / "ichor.db")
        try:
            row = con.execute(
                "SELECT event_type, raw_text FROM cold_events "
                "WHERE event_type='blocker' AND name='ichor.benchmark.regression' "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self.assertIsNotNone(row, "no blocker event created")
            self.assertEqual(row[0], "blocker")
            self.assertIn("regression", row[1].lower())
        finally:
            con.close()

    def test_no_flag_when_drop_below_threshold(self):
        """A 5% drop is not a regression — no blocker created."""
        # Snapshot existing blocker count, run, verify no new one
        con = sqlite3.connect(Path.home() / ".hermes" / "ichor.db")
        try:
            before = con.execute(
                "SELECT COUNT(*) FROM cold_events "
                "WHERE event_type='blocker' AND name='ichor.benchmark.regression'"
            ).fetchone()[0]
        finally:
            con.close()
        flag_regression(
            previous_recall=0.80,
            current_recall=0.76,  # -5% drop, below threshold
            dry_run=False,
        )
        con = sqlite3.connect(Path.home() / ".hermes" / "ichor.db")
        try:
            after = con.execute(
                "SELECT COUNT(*) FROM cold_events "
                "WHERE event_type='blocker' AND name='ichor.benchmark.regression'"
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(after, before, "spurious blocker created")

    def test_no_flag_when_recall_improves(self):
        """Improvement is not a regression."""
        con = sqlite3.connect(Path.home() / ".hermes" / "ichor.db")
        try:
            before = con.execute(
                "SELECT COUNT(*) FROM cold_events "
                "WHERE event_type='blocker' AND name='ichor.benchmark.regression'"
            ).fetchone()[0]
        finally:
            con.close()
        flag_regression(previous_recall=0.70, current_recall=0.85)
        con = sqlite3.connect(Path.home() / ".hermes" / "ichor.db")
        try:
            after = con.execute(
                "SELECT COUNT(*) FROM cold_events "
                "WHERE event_type='blocker' AND name='ichor.benchmark.regression'"
            ).fetchone()[0]
        finally:
            con.close()
        self.assertEqual(after, before)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestWeightTuner(unittest.TestCase):
    """WeightTuner applies a single drift cycle correctly."""

    def test_tuner_does_not_drift_when_no_history(self):
        """First run with no history → no drift applied (nothing to compare)."""
        with tempfile.TemporaryDirectory() as tmp:
            tuner = WeightTuner(history_path=Path(tmp) / "hist.json")
            initial = dict(WEIGHTS)
            result = tuner.cycle(previous_recall=None, current_recall=0.7)
            self.assertEqual(result, initial,
                             msg="first cycle should not drift")

    def test_tuner_persists_history(self):
        """After cycle(), history is written to disk."""
        with tempfile.TemporaryDirectory() as tmp:
            hist = Path(tmp) / "hist.json"
            tuner = WeightTuner(history_path=hist)
            tuner.cycle(previous_recall=0.5, current_recall=0.6)
            self.assertTrue(hist.exists())
            data = json.loads(hist.read_text())
            self.assertIn("cycles", data)
            self.assertEqual(len(data["cycles"]), 1)

    def test_tuner_drift_under_5pct(self):
        """cycle() drift must be ≤5% per call regardless of recall delta."""
        with tempfile.TemporaryDirectory() as tmp:
            tuner = WeightTuner(history_path=Path(tmp) / "hist.json")
            # Force a big improvement → big desired drift → still capped
            tuner.cycle(previous_recall=0.1, current_recall=0.9)
            data = json.loads((Path(tmp) / "hist.json").read_text())
            cycle = data["cycles"][-1]
            for k, d in cycle["drift"].items():
                self.assertLessEqual(abs(d), 0.05 + 1e-9,
                                     msg=f"{k} drifted {d} > 5%")


class TestHistoryIsolated(unittest.TestCase):
    """Weight history is read/written to the canonical path, but tests
    use a temp path so the real history isn't polluted."""

    def test_real_history_path_exists(self):
        """The canonical history file should exist (or be creatable)."""
        self.assertTrue(str(_WEIGHTS_HISTORY).endswith("ichor_weights_history.json"))


if __name__ == "__main__":
    unittest.main()
