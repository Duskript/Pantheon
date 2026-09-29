#!/usr/bin/env python3
"""Weight tuning harness — metric math, candidate generation, decision guards.

The harness exists so weight changes are judged by labeled recall instead of a
proxy. These tests pin the parts that decide whether a change is applied:

  * `composite()` ranks recall first, ranking quality second
  * `normalize()` keeps weights a distribution
  * `generate_candidates()` never proposes moving a lane that is offline
    (a dead embedder must not read as "this lane is useless")
  * the apply gate holds unless the gain clears `min_gain`
  * the latency guard rejects a faster-looking win that costs responsiveness
  * `rewrite_weights_literal()` touches only the literal and keeps it parseable

Hermetic: no DB, no live graph, no writes to lib/ichor_hybrid.py.

Run with the hermes venv (no pytest there):
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_weight_tuning.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PANTHEON = Path("/home/konan/pantheon")
if str(PANTHEON) not in sys.path:
    sys.path.insert(0, str(PANTHEON))

_spec = importlib.util.spec_from_file_location(
    "ichor_weight_tune", PANTHEON / "scripts/ichor_weight_tune.py"
)
tune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tune)

_espec = importlib.util.spec_from_file_location(
    "ichor_recall_eval", PANTHEON / "scripts/ichor_recall_eval.py"
)
ev = importlib.util.module_from_spec(_espec)
_espec.loader.exec_module(ev)

CURRENT = {"fts5": 0.40, "vector": 0.20, "graph": 0.15, "events": 0.15, "reference": 0.10}


class TestComposite(unittest.TestCase):
    def test_recall_dominates_ranking(self):
        better_recall = {"hit_at_5": 0.80, "mrr": 0.40}
        better_ranking = {"hit_at_5": 0.60, "mrr": 0.90}
        self.assertGreater(tune.composite(better_recall, 5), tune.composite(better_ranking, 5))

    def test_mrr_breaks_recall_ties(self):
        self.assertGreater(
            tune.composite({"hit_at_5": 0.5, "mrr": 0.9}, 5),
            tune.composite({"hit_at_5": 0.5, "mrr": 0.3}, 5),
        )

    def test_k_specific_key_is_used(self):
        report = {"hit_at_3": 0.9, "hit_at_5": 0.1, "mrr": 0.5}
        self.assertGreater(tune.composite(report, 3), tune.composite(report, 5))


class TestNormalize(unittest.TestCase):
    def test_sums_to_one(self):
        out = tune.normalize({"fts5": 2, "vector": 2, "graph": 1, "events": 1, "reference": 0})
        self.assertAlmostEqual(sum(out.values()), 1.0, places=2)

    def test_negatives_are_clamped(self):
        out = tune.normalize({**CURRENT, "fts5": -0.5})
        self.assertGreaterEqual(out["fts5"], 0.0)


class TestCandidateGeneration(unittest.TestCase):
    def test_offline_lanes_are_never_moved(self):
        cands = tune.generate_candidates(CURRENT, step=0.10, offline=["vector"])
        for c in cands:
            self.assertAlmostEqual(c["vector"], CURRENT["vector"], places=3,
                                   msg=f"candidate {c['_label']} moved an offline lane")

    def test_produces_lane_and_structural_candidates(self):
        labels = [c["_label"] for c in tune.generate_candidates(CURRENT, 0.05, [])]
        self.assertIn("fts5+0.05", labels)
        self.assertIn("graph-0.05", labels)
        self.assertIn("uniform", labels)
        self.assertIn("graph-heavy", labels)

    def test_candidates_are_normalized_and_unique(self):
        cands = tune.generate_candidates(CURRENT, 0.05, [])
        keys = [json.dumps({k: v for k, v in c.items() if k != "_label"}, sort_keys=True) for c in cands]
        self.assertEqual(len(keys), len(set(keys)), "duplicate candidate configs")
        for c in cands:
            self.assertAlmostEqual(sum(v for k, v in c.items() if k != "_label"), 1.0, places=2)


class TestDecisionGuards(unittest.TestCase):
    """`run()` is exercised with a stubbed evaluator so no graph is touched.

    The stub maps a candidate's weights to a report instead of popping a queue,
    so the assertions do not depend on how many candidates the generator emits.
    """

    @staticmethod
    def _report(hit5, mrr, lat, offline=None):
        return {
            "hit_at_1": hit5, "hit_at_3": hit5, "hit_at_5": hit5, "mrr": mrr,
            "latency_mean_ms": lat, "latency_p50_ms": lat, "weights": dict(CURRENT),
            "lane_results": {}, "lane_candidates": {}, "offline_lanes": offline or [],
            "queries": 1, "k": 5, "limit": 10, "misses": [],
        }

    def _run_with(self, baseline, scorer, **kw):
        def fake_evaluate(weights=None, **kwargs):
            if not weights or all(abs(weights.get(k, 0) - v) < 1e-9 for k, v in CURRENT.items()):
                return baseline
            return scorer(weights)

        with mock.patch.object(tune, "_load_eval") as loader:
            stub = mock.Mock()
            stub.load_golden.return_value = {"queries": [{"query": "q", "expect": ["X"]}]}
            stub.current_weights.return_value = dict(CURRENT)
            stub.evaluate.side_effect = fake_evaluate
            loader.return_value = stub
            with mock.patch.object(tune, "save_history"):
                return tune.run(step=0.05, k=5, limit=10,
                                min_gain=kw.get("min_gain", 0.02),
                                max_latency_factor=kw.get("max_latency_factor", 1.5),
                                apply=kw.get("apply", False))

    def test_holds_when_no_candidate_improves(self):
        base = self._report(0.50, 0.50, 100.0)
        res = self._run_with(base, lambda w: self._report(0.50, 0.50, 100.0), min_gain=0.02)
        self.assertEqual(res["decision"], "hold")
        self.assertLess(res["gain"], 0.02)

    def test_applies_when_gain_clears_threshold(self):
        base = self._report(0.50, 0.50, 100.0)

        def scorer(w):
            # a genuine recall win only for configs that raise the graph lane
            if w.get("graph", 0) >= 0.20:
                return self._report(0.90, 0.90, 100.0)
            return self._report(0.50, 0.50, 100.0)

        res = self._run_with(base, scorer, min_gain=0.02)
        self.assertEqual(res["decision"], "apply")
        self.assertGreaterEqual(res["gain"], 0.02)
        self.assertGreaterEqual(res["winner"]["weights"]["graph"], 0.20)

    def test_latency_guard_rejects_high_scoring_slow_candidate(self):
        base = self._report(0.50, 0.50, 100.0)

        def scorer(w):
            if w.get("graph", 0) >= 0.20:
                return self._report(0.99, 0.99, 400.0)   # 4x slower
            return self._report(0.50, 0.50, 100.0)

        res = self._run_with(base, scorer, min_gain=0.02, max_latency_factor=1.5)
        self.assertEqual(res["decision"], "hold", "a 4x slower config must not be applied")

    def test_offline_lanes_are_reported_in_the_reason(self):
        base = self._report(0.50, 0.50, 100.0, offline=["vector"])
        res = self._run_with(base, lambda w: self._report(0.50, 0.50, 100.0))
        self.assertIn("offline", res["reason"])
        self.assertIn("vector", res["reason"])
        for cand in res["candidates"]:
            self.assertAlmostEqual(cand["weights"]["vector"], CURRENT["vector"], places=3,
                                   msg="an offline lane was moved by a candidate")

    def test_apply_is_not_attempted_when_decision_is_hold(self):
        base = self._report(0.50, 0.50, 100.0)
        with mock.patch.object(tune, "apply_weights") as apply_mock:
            res = self._run_with(base, lambda w: self._report(0.50, 0.50, 100.0),
                                 min_gain=0.5, apply=True)
        apply_mock.assert_not_called()
        self.assertFalse(res["apply"]["applied"])


class TestRewriteWeightsLiteral(unittest.TestCase):
    SRC = '''WEIGHTS = {
    "fts5": 0.40,      # Phase 4 rebalance
    "vector": 0.20,
    "graph": 0.15,
    "events": 0.15,
    "reference": 0.10,
}
OTHER = {"fts5": 0.99}
'''

    def test_rewrites_only_the_weights_literal(self):
        res = tune.rewrite_weights_literal(self.SRC, {"fts5": 0.30, "vector": 0.30,
                                                      "graph": 0.15, "events": 0.15, "reference": 0.10})
        self.assertTrue(res["parsed"])
        self.assertEqual(res["changed"]["fts5"], {"from": 0.40, "to": 0.30})
        self.assertIn('"fts5": 0.30,      # Phase 4 rebalance', res["source"],
                      "inline comment was lost")
        self.assertIn('OTHER = {"fts5": 0.99}', res["source"],
                      "an unrelated literal was rewritten")

    def test_no_change_reports_empty_changed(self):
        res = tune.rewrite_weights_literal(self.SRC, dict(CURRENT))
        self.assertEqual(res["changed"], {})
        self.assertEqual(res["source"], self.SRC)

    def test_missing_block_is_reported_not_raised(self):
        res = tune.rewrite_weights_literal("x = 1\n", {"fts5": 0.5})
        self.assertIn("error", res)


class TestMetricMath(unittest.TestCase):
    def test_first_hit_rank_matches_names_in_title_snippet_or_id(self):
        results = [
            {"id": "fts5:1", "title": "unrelated", "snippet": "nothing here"},
            {"id": "graph:4450:knows", "title": "konan --knows--> Fia", "snippet": ""},
        ]
        self.assertEqual(ev._first_hit_rank(results, ["Fia"]), 2)
        self.assertIsNone(ev._first_hit_rank(results, ["Jahnavi"]))

    def test_rank_matching_is_case_insensitive_and_word_bounded(self):
        results = [{"id": "x", "title": "the TALLON handoff", "snippet": ""}]
        self.assertEqual(ev._first_hit_rank(results, ["tallon"]), 1)
        # a substring inside a longer token must not count
        results2 = [{"id": "x", "title": "tallonian", "snippet": ""}]
        self.assertIsNone(ev._first_hit_rank(results2, ["Tallon"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
