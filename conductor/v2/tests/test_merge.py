"""Tests for the Step 4.7 `merge` step type (Brief 1, 2026-06-16).

Covers the 4 non-LLM merge strategies in `pantheon.conductor.v2.merge`:
  - `concat` — concatenate inputs in declared order, separated by headers
  - `first`  — first non-None input wins (in `inputs` order)
  - `diff`   — structured diff between inputs (≥2 inputs)
  - `vote`   — majority result; ties broken by `inputs` order

The 2 LLM-merge strategies (`llm_summarize`, `llm_pick_best`) live in
`engine._exec_merge` because they reuse the engine's `llm_call` path;
they are NOT tested here (they require an LLM subprocess). The
dispatcher's strategy validation IS tested (bad/missing strategy,
length mismatch, missing `llm_fn` for LLM strategies).

Pattern: tests directly call `merge_mod.run_merge(strategy, inputs,
values, strategy_config)`. The engine's wiring of merge into a
workflow step is verified by `test_merge.py::TestMergeInWorkflow` at
the bottom — the unit tests are the focus.

Mirrors the test_parallel.py structure (per the brief):
  - Uses `from v2.tests import fixtures as cf` for tmp + mock
  - The pure-function unit tests at the top
  - End-to-end workflow tests at the bottom
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402
from v2 import merge as merge_mod  # noqa: E402


# -----------------------------------------------------------------------------
# concat
# -----------------------------------------------------------------------------

class TestConcatStrategy(unittest.TestCase):
    """`concat`: join non-None inputs in declared order with headers."""

    def test_concat_two_strings_joins_with_headers(self):
        """Two string inputs → header for each + the value, joined
        by a blank line. The headers let downstream readers identify
        which step produced which chunk."""
        result = merge_mod.run_merge(
            "concat",
            inputs=["a", "b"],
            values=["alpha", "beta"],
        )
        self.assertEqual(result["strategy"], "concat")
        self.assertEqual(result["sources"], ["a", "b"])
        self.assertEqual(
            result["merged_value"],
            "=== a ===\nalpha\n\n=== b ===\nbeta",
        )

    def test_concat_three_strings_preserves_order(self):
        """Three inputs → order must match the declared `inputs` order
        (concat is order-sensitive; vote/first are order-sensitive
        for tiebreak, but concat preserves order strictly)."""
        result = merge_mod.run_merge(
            "concat",
            inputs=["x", "y", "z"],
            values=["first", "second", "third"],
        )
        self.assertEqual(
            result["merged_value"],
            "=== x ===\nfirst\n\n=== y ===\nsecond\n\n=== z ===\nthird",
        )
        # sources list is also in declared order
        self.assertEqual(result["sources"], ["x", "y", "z"])

    def test_concat_skips_none_values(self):
        """A None value (failed/unresolved input) is skipped, not
        rendered as the literal string "None". The sources list
        records which inputs actually contributed."""
        result = merge_mod.run_merge(
            "concat",
            inputs=["good", "bad", "good2"],
            values=["ok", None, "ok2"],
        )
        self.assertEqual(result["sources"], ["good", "good2"])
        # No `=== bad ===` header in the output
        self.assertNotIn("=== bad ===", result["merged_value"])
        self.assertIn("=== good ===", result["merged_value"])
        self.assertIn("=== good2 ===", result["merged_value"])


# -----------------------------------------------------------------------------
# first
# -----------------------------------------------------------------------------

class TestFirstStrategy(unittest.TestCase):
    """`first`: first non-None input (in declared order) wins."""

    def test_first_returns_first_successful(self):
        """Both inputs succeed → returns inputs[0]'s value, sources=[a]."""
        result = merge_mod.run_merge(
            "first",
            inputs=["a", "b"],
            values=["alpha", "beta"],
        )
        self.assertEqual(result["strategy"], "first")
        self.assertEqual(result["merged_value"], "alpha")
        self.assertEqual(result["sources"], ["a"])

    def test_first_skips_failed_inputs(self):
        """First input is None (failed) → return inputs[1]'s value,
        sources=[b] (the one that contributed)."""
        result = merge_mod.run_merge(
            "first",
            inputs=["a", "b"],
            values=[None, "beta"],
        )
        self.assertEqual(result["merged_value"], "beta")
        self.assertEqual(result["sources"], ["b"])

    def test_first_all_failed_returns_none(self):
        """All inputs None → merged_value is None, sources is [].
        The engine treats this as a failed merge (no winner)."""
        result = merge_mod.run_merge(
            "first",
            inputs=["a", "b", "c"],
            values=[None, None, None],
        )
        self.assertIsNone(result["merged_value"])
        self.assertEqual(result["sources"], [])


# -----------------------------------------------------------------------------
# diff
# -----------------------------------------------------------------------------

class TestDiffStrategy(unittest.TestCase):
    """`diff`: structured diff between inputs (≥2 non-None)."""

    def test_diff_two_dicts_shows_structured_diff(self):
        """Two dicts → key-by-key diff: added, removed, changed keys."""
        a = {"x": 1, "y": 2, "shared": "old"}
        b = {"y": 2, "shared": "new", "z": 3}
        result = merge_mod.run_merge(
            "diff",
            inputs=["snap1", "snap2"],
            values=[a, b],
        )
        self.assertEqual(result["strategy"], "diff")
        self.assertEqual(result["sources"], ["snap1", "snap2"])
        diffs = result["merged_value"]
        self.assertIn("snap1__vs__snap2", diffs)
        change = diffs["snap1__vs__snap2"]
        self.assertEqual(change["type"], "dict")
        changes = change["changes"]
        # 'x' is in a but not b → removed
        self.assertIn("x", changes["removed"])
        # 'z' is in b but not a → added
        self.assertIn("z", changes["added"])
        # 'y' is identical in both → not in any list
        self.assertNotIn("y", changes["changed"])
        # 'shared' changed value → in changed
        self.assertIn("shared", changes["changed"])

    def test_diff_two_strings_returns_unified_diff(self):
        """Two strings → unified diff text in the merged_value."""
        result = merge_mod.run_merge(
            "diff",
            inputs=["old", "new"],
            values=["line1\nline2\n", "line1\nline2-changed\n"],
        )
        self.assertEqual(result["strategy"], "diff")
        diffs = result["merged_value"]
        self.assertIn("old__vs__new", diffs)
        change = diffs["old__vs__new"]
        self.assertEqual(change["type"], "text")
        # The unified diff should mention both filenames
        self.assertIn("old", change["diff"])
        self.assertIn("new", change["diff"])
        # And show the actual change marker
        self.assertIn("-line2", change["diff"])
        self.assertIn("+line2-changed", change["diff"])


# -----------------------------------------------------------------------------
# vote
# -----------------------------------------------------------------------------

class TestVoteStrategy(unittest.TestCase):
    """`vote`: majority on structured data; ties broken by `inputs` order."""

    def test_vote_majority_winner(self):
        """3 inputs, 2 same + 1 different → the 2-of-3 majority wins.
        sources = the step ids that contributed to the majority."""
        result = merge_mod.run_merge(
            "vote",
            inputs=["a", "b", "c"],
            values=["yes", "yes", "no"],
        )
        self.assertEqual(result["strategy"], "vote")
        self.assertEqual(result["merged_value"], "yes")
        # a and b both voted "yes"; c voted "no". Majority = a+b.
        self.assertEqual(set(result["sources"]), {"a", "b"})

    def test_vote_tie_broken_by_order(self):
        """4 inputs: a=x, b=x, c=y, d=y → 2-2 tie. By the spec
        (and the implementation), ties are broken by EARLIEST
        position in `inputs`. So a (index 0) wins over c (index 2),
        because the first occurrence of the tied value is the
        tiebreaker."""
        result = merge_mod.run_merge(
            "vote",
            inputs=["a", "b", "c", "d"],
            values=["x", "x", "y", "y"],
        )
        self.assertEqual(result["merged_value"], "x")
        # sources = [a, b] (both voted x, the tiebreak winner)
        self.assertEqual(set(result["sources"]), {"a", "b"})

    def test_vote_unanimous(self):
        """All 4 inputs agree → unanimous winner, all in sources."""
        result = merge_mod.run_merge(
            "vote",
            inputs=["a", "b", "c", "d"],
            values=["agree", "agree", "agree", "agree"],
        )
        self.assertEqual(result["merged_value"], "agree")
        self.assertEqual(set(result["sources"], ), {"a", "b", "c", "d"})
        self.assertEqual(set(result["sources"]), {"a", "b", "c", "d"})

    def test_vote_dict_values_group_by_canonical_form(self):
        """Dicts with the same content (different object identity)
        should be counted as the same vote. The implementation
        uses `json.dumps(val, sort_keys=True)` as the canonical
        form for unhashable types."""
        result = merge_mod.run_merge(
            "vote",
            inputs=["snap_a", "snap_b", "snap_c"],
            values=[
                {"k": "v1", "n": 1},
                {"n": 1, "k": "v1"},   # same as a (reordered)
                {"k": "v2", "n": 1},   # different
            ],
        )
        # snap_a and snap_b both contain {"k": "v1", "n": 1} → 2 votes
        # snap_c contains {"k": "v2", "n": 1} → 1 vote
        # Majority is the v1 dict.
        self.assertEqual(result["merged_value"], {"k": "v1", "n": 1})
        self.assertEqual(set(result["sources"]), {"snap_a", "snap_b"})


# -----------------------------------------------------------------------------
# Dispatcher / validation
# -----------------------------------------------------------------------------

class TestMergeDispatcher(unittest.TestCase):
    """The run_merge dispatcher: strategy validation, length checks,
    LLM strategy stub."""

    def test_unknown_strategy_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            merge_mod.run_merge("bogus_strategy", ["a"], ["x"])
        self.assertIn("unknown merge strategy", str(ctx.exception))
        self.assertIn("bogus_strategy", str(ctx.exception))

    def test_input_value_length_mismatch_raises(self):
        """inputs has 3 ids, values has 2 → must raise (otherwise
        downstream strategies would silently index-out-of-range)."""
        with self.assertRaises(ValueError) as ctx:
            merge_mod.run_merge("concat", ["a", "b", "c"], ["x", "y"])
        self.assertIn("length mismatch", str(ctx.exception))

    def test_empty_inputs_raises(self):
        """At least one input is required."""
        with self.assertRaises(ValueError) as ctx:
            merge_mod.run_merge("concat", [], [])
        self.assertIn("at least one input", str(ctx.exception))

    def test_llm_strategy_without_llm_fn_raises(self):
        """llm_summarize and llm_pick_best require an llm_fn. If
        omitted, the dispatcher raises a clear error (the engine
        is responsible for passing the LLM-calling function in)."""
        for strategy in ("llm_summarize", "llm_pick_best"):
            with self.assertRaises(ValueError) as ctx:
                merge_mod.run_merge(
                    strategy, ["a"], ["x"],
                    strategy_config={"judge_prompt_template": "t"},
                )
            self.assertIn("requires an llm_fn", str(ctx.exception))

    def test_llm_strategy_with_llm_fn_delegates(self):
        """If an llm_fn is provided, the dispatcher delegates to it
        instead of running a non-LLM strategy. The llm_fn returns
        its own dict (the LLM caller's contract)."""
        def fake_llm(inputs, values, cfg):
            return {
                "strategy": "llm_pick_best",
                "merged_value": values[0],
                "sources": [inputs[0]],
                "chosen_source": inputs[0],
                "judge_output": "picked the first one",
            }
        result = merge_mod.run_merge(
            "llm_pick_best",
            inputs=["a", "b"],
            values=["alpha", "beta"],
            strategy_config={"judge_prompt_template": "t"},
            llm_fn=fake_llm,
        )
        self.assertEqual(result["merged_value"], "alpha")
        self.assertEqual(result["chosen_source"], "a")
        self.assertEqual(result["judge_output"], "picked the first one")


# -----------------------------------------------------------------------------
# Engine integration: merge step in a workflow (mirrors test_parallel.py bottom)
# -----------------------------------------------------------------------------

def _new_engine(tmp, *, gateway):
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


class TestMergeInWorkflow(unittest.IsolatedAsyncioTestCase):
    """End-to-end: a workflow with a `merge` step executes and
    produces the merged output in `context_bag[merge_step.output]`.

    Mirrors `TestParallelExecution` in test_parallel.py — uses the
    mock gateway + queue_run pattern. Three parallel god branches
    feed a merge step that combines them via `vote`."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_workflow(self, yml: dict) -> Path:
        path = self.tmp.workflows_dir / "test.yaml"
        path.write_text(json.dumps(yml))
        self.engine.workflows.reload()
        return path

    async def test_merge_vote_step_in_workflow_writes_context_bag(self):
        """A merge step with strategy=vote picks the majority
        output and writes the result to context_bag under the
        step's `output:` key."""
        yml = {"workflow": {
            "id": "merge-vote", "name": "merge-vote", "version": "1.0.0",
            "context": {"required": [], "optional": []},
            "steps": [
                {
                    "id": "par", "type": "parallel",
                    "branches": [
                        {"id": "a", "god": "thoth",
                         "input": "x", "output": "a_out"},
                        {"id": "b", "god": "marvin",
                         "input": "y", "output": "b_out"},
                        {"id": "c", "god": "hephaestus",
                         "input": "z", "output": "c_out"},
                    ],
                },
                {
                    "id": "merge", "type": "merge",
                    "inputs": ["a_out", "b_out", "c_out"],
                    "strategy": "vote",
                    "output": "winner",
                },
            ],
        }}
        self._write_workflow(yml)
        # 2 of 3 vote for "alpha", 1 votes "beta" → majority = alpha
        for n, val in [("a", "alpha"), ("b", "alpha"), ("c", "beta")]:
            self.gw.queue_run(cf.MockRun(f"r_{n}", output=val))
        inst = self.engine.start_workflow("merge-vote")
        for _ in range(100):
            await asyncio.sleep(0.02)
            cur = self.engine.get_instance(inst.workflow_id)
            if cur.status in ("completed", "failed", "aborted"):
                break
        # Per-branch outputs in context_bag
        self.assertEqual(cur.context_bag.get("a_out"), "alpha")
        self.assertEqual(cur.context_bag.get("b_out"), "alpha")
        self.assertEqual(cur.context_bag.get("c_out"), "beta")
        # Merge output in context_bag
        self.assertIn("winner", cur.context_bag)
        merged = cur.context_bag["winner"]
        self.assertEqual(merged["strategy"], "vote")
        self.assertEqual(merged["merged_value"], "alpha")
        # Sources are the step ids whose values participated in
        # the majority bucket. With a,b both being "alpha", the
        # majority sources are a_out and b_out.
        self.assertEqual(set(merged["sources"]), {"a_out", "b_out"})


if __name__ == "__main__":
    unittest.main()
