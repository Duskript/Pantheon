"""Step 1.6 — v2 submit_handoff spec cases.

Phase 1 Step 1.6 wired the v2 `submit_handoff` path into
`Conductor.submit_handoff` as the primary routing path when
`routing.workflow_definition` is a workflow the v2 engine knows
(v2_definition_known=True). When the definition is unknown or
`routing` is missing entirely, the v1 dispatch path is the
fallback.

This file pins the four spec cases for the v2 routing wiring:

  1. Known workflow definition → v2 path runs. v2_definition_known
     and v2_dispatched are both True. The v2-shape dispatch file
     lands in pending/<first_god>/<v2_wf_id>_<first_step_id>.json.
     The on-disk state file (state/wf_<v2_wf_id>.json) has a
     step_history entry with v2_dispatched=True.

  2. Unknown workflow definition → v1 path is the fallback. The
     response shape has v2_definition_known=False. v2_dispatched
     is False (the v2 path never ran). The dispatch lands in the
     v1-shape location (pending/<handoff.to_god>/<handoff_id>.json).

  3. No `routing` key at all → v1 path is the fallback. Same shape
     as the unknown case: v2_definition_known=False, v2_dispatched
     unset (or False).

  4. v2_dispatched: bool persisted in state['step_history'] when
     the v2 path runs. Specifically: the state file's step_history
     has at least one entry whose `v2_dispatched` field is True (the
     audit-trail flag Thoth's design note requires for the v2 path).

The four cases are isolated in separate TestCase classes so the
state of one doesn't leak into the next. Each setUp uses a fresh
TmpConductor + workflow seed.

Run: cd /home/konan && PANTHEON_ROOT=/home/konan/pantheon \\
     PYTHONPATH=/home/konan/pantheon \\
     pytest conductor/v2/tests/test_submit_handoff_v2.py -v
"""

from __future__ import annotations

import json
import sys
import unittest
import uuid
from pathlib import Path

# Path setup: parent of conductor/ (i.e., pantheon checkout root) so that
# `from v2.tests import fixtures` and `import conductor.conductor_server`
# both resolve. Same convention as the other v2 test files.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402

import conductor.conductor_server as bridge  # noqa: E402
from v2 import engine as eng  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# handoff_id must match the validator regex ^hof_\d{8}_[a-z0-9]{6,8}$
# (see /home/konan/pantheon/shared/handoffs/schema.json:32). 6-char
# suffix keeps the test output deterministic.
_HANDOFF_ID = "hof_20260615_sub010"  # 6-char suffix to match regex


def _make_handoff(
    *,
    workflow_id: str = "wf_test",
    from_god: str = "konan",
    to_god: str = "thoth",
    step: str = "active-goals",
    routing: dict | None = None,
    include_routing: bool = True,
    handoff_id: str = _HANDOFF_ID,
) -> dict:
    """Build a minimal valid handoff dict per the handoff schema.

    Required fields per schema (handoffs/schema.json:90-97):
        handoff_id, workflow_id, from_god, to_god, step, context
    `routing` is optional (per the schema, additionalProperties: false
    only applies to the handoff object itself; `routing` is an
    optional property of the handoff).
    """
    handoff: dict = {
        "handoff_id": handoff_id,
        "workflow_id": workflow_id,
        "from_god": from_god,
        "to_god": to_god,
        "step": step,
        "context": {
            "summary": "v2 routing test handoff",
            "decisions": [],
            "artifacts": [],
        },
    }
    if include_routing and routing is not None:
        handoff["routing"] = routing
    return handoff


def _build_conductor_with_workflow(
    tmp: cf.TmpConductor,
    workflow_id: str,
    *,
    first_god: str = "thoth",
    first_step_id: str = "active-goals",
    seed_in_engine_globally: bool = True,
) -> bridge.Conductor:
    """Create a Conductor bound to the tmp layout, with a workflow
    YAML seeded into the bridge's lazy-resolved workflows dir (and
    optionally the session-level eng.WORKFLOWS_DIR for v2-direct
    readers in other tests).

    Why seed TWO locations: the Step 1.6 lazy fix made
    `WorkflowRegistry.__init__` resolve `workflows_dir` at
    construction time via the lazy `_workflows_dir()` (which honours
    `CONDUCTOR_BASE_DIR`). The bridge's `_v2_engine()` builds a fresh
    `ConductorEngine()` whose `WorkflowRegistry` reads from the
    per-test tmp workflows dir (`tmp.workflows_dir`). The
    session-level `eng.WORKFLOWS_DIR` is what v2-direct tests in
    `test_engine.py` read from — harmless to seed for them but not
    required for the bridge path this test exercises.
    """
    import shutil
    import yaml

    # Per-test tmp seed (the path the bridge will read from).
    tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp.workflows_dir / f"{workflow_id}.yaml"
    tmp_path.write_text(yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": f"v2 routing test {workflow_id}",
            "version": "1.0.0",
            "context": {"required": [], "optional": []},
            "steps": [
                {
                    "id": first_step_id,
                    "god": first_god,
                    "action": "research",
                    "output": f"{first_step_id}_output",
                    "timeout": "30m",
                },
            ],
        }
    }))

    # Session-level seed (so v2-direct tests in the same pytest run
    # can find this workflow; harmless for the bridge path).
    if seed_in_engine_globally:
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        eng_path = eng.WORKFLOWS_DIR / f"{workflow_id}.yaml"
        if not eng_path.exists():
            shutil.copy(tmp_path, eng_path)

    return bridge.Conductor(base_dir=tmp.root)


# ===========================================================================
# 1. Known workflow definition → v2 path runs (the primary spec case)
# ===========================================================================

class TestV2DispatchForKnownDefinition(unittest.TestCase):
    """routing.workflow_definition points at a real v2 workflow → the
    v2 path runs. v2_definition_known=True, v2_dispatched=True, and
    the v2-shape dispatch file lands in pending/<first_god>/.
    """

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # Per-test uuid-suffixed workflow id so the v2 engine's
        # WorkflowRegistry (which lives in a session-shared dir) can
        # never collide with production-shipped workflows.
        self.workflow_id = f"v2-submit-{uuid.uuid4().hex[:8]}"
        self.first_god = "thoth"
        self.first_step_id = "active-goals"
        self.conductor = _build_conductor_with_workflow(
            self.tmp,
            self.workflow_id,
            first_god=self.first_god,
            first_step_id=self.first_step_id,
        )

    def tearDown(self):
        self.tmp.cleanup()
        # Wipe the session-level engine seed if we wrote one (best
        # effort; the session dir is shared with other tests).
        eng_path = eng.WORKFLOWS_DIR / f"{self.workflow_id}.yaml"
        if eng_path.exists():
            try:
                eng_path.unlink()
            except OSError:
                pass

    def test_v2_dispatch_for_known_definition(self):
        # Build a handoff whose routing.workflow_definition points at
        # our seeded workflow. The v2 path's
        # `self._v2_engine().workflows.get(wf_def_id)` returns the
        # workflow, so v2_definition_known=True and the v2 path runs.
        handoff = _make_handoff(
            workflow_id=f"wf_{uuid.uuid4().hex[:8]}",  # v2 mints a fresh wf_<uuid8>
            from_god="konan",
            to_god=self.first_god,
            step=self.first_step_id,
            routing={"workflow_definition": self.workflow_id},
        )

        result = self.conductor.submit_handoff(handoff)

        # --- v2 markers: v2_definition_known AND v2_dispatched ---
        self.assertTrue(
            result.get("v2_definition_known"),
            f"v2 path should set v2_definition_known=True for a known "
            f"workflow definition; got {result!r}",
        )
        self.assertIs(
            result.get("v2_dispatched"),
            True,
            f"v2 path should set v2_dispatched=True for a known "
            f"workflow definition; got {result!r}",
        )
        # --- Response shape: dispatched, target_god = current step's god ---
        self.assertEqual(
            result.get("status"), "dispatched",
            f"v2 path should return status=dispatched; got {result!r}",
        )
        self.assertEqual(
            result.get("target_god"), self.first_god,
            f"v2 path should set target_god=current step's god "
            f"({self.first_god!r}); got {result.get('target_god')!r}",
        )
        self.assertEqual(
            result.get("target_step"), self.first_step_id,
            f"v2 path should set target_step=current step's id "
            f"({self.first_step_id!r}); got {result.get('target_step')!r}",
        )
        # --- v2 path mints a fresh wf_<uuid8> workflow instance ---
        v2_wf_id = result.get("workflow_id")
        self.assertIsNotNone(
            v2_wf_id,
            f"v2 path should return a workflow_id; got {result!r}",
        )
        self.assertTrue(
            isinstance(v2_wf_id, str) and v2_wf_id.startswith("wf_"),
            f"v2 path should mint a wf_<uuid8> workflow_id; "
            f"got {v2_wf_id!r}",
        )
        assert isinstance(v2_wf_id, str)  # type narrowing
        # --- v2 dispatch file lands in pending/<first_god>/ ---
        v2_dispatch = (
            self.tmp.pending_dir
            / self.first_god
            / f"{v2_wf_id}_{self.first_step_id}.json"
        )
        self.assertTrue(
            v2_dispatch.exists(),
            f"v2 dispatch should land in {v2_dispatch}; "
            f"pending/{self.first_god}/ contents: "
            f"{list((self.tmp.pending_dir / self.first_god).iterdir())}",
        )
        # --- on-disk state file at state/wf_<v2_wf_id>.json ---
        v2_state_file = self.tmp.state_dir / f"{v2_wf_id}.json"
        self.assertTrue(
            v2_state_file.exists(),
            f"v2 path should write state file at {v2_state_file}; "
            f"state_dir contents: "
            f"{list(self.tmp.state_dir.glob('wf_*.json'))}",
        )
        # --- v1 bookkeeping pass: handoff file in handoffs_dir ---
        v1_handoff_file = (
            self.conductor.handoffs_dir
            / handoff["workflow_id"]
            / f"{self.first_step_id}.json"
        )
        self.assertTrue(
            v1_handoff_file.exists(),
            f"bridge should write the v1-shape handoff file at "
            f"{v1_handoff_file} (v1 bookkeeping pass for v2-routed "
            f"handoffs)",
        )


# ===========================================================================
# 2. Unknown workflow definition → v1 fallback (v2_dispatched=False)
# ===========================================================================

class TestV1FallbackForUnknownDefinition(unittest.TestCase):
    """routing.workflow_definition is a bogus id → the v1 path is the
    fallback. v2_definition_known=False, v2_dispatched=False (the v2
    path never ran). The dispatch lands in the v1-shape location.
    """

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # No workflow YAML is seeded for this test — the whole point
        # is to exercise the v1 fallback when the definition is
        # unknown to the v2 engine.
        self.conductor = bridge.Conductor(base_dir=self.tmp.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_v1_fallback_for_unknown_definition(self):
        bogus_def = f"no-such-workflow-{uuid.uuid4().hex[:8]}"
        handoff = _make_handoff(
            workflow_id=f"wf_{uuid.uuid4().hex[:8]}",
            from_god="konan",
            to_god="hephaestus",
            step="step1",
            routing={"workflow_definition": bogus_def},
        )

        result = self.conductor.submit_handoff(handoff)

        # --- v2 markers: v2_definition_known is False ---
        self.assertIs(
            result.get("v2_definition_known"),
            False,
            f"v2 path should NOT run for unknown definition "
            f"{bogus_def!r}; got v2_definition_known={result.get('v2_definition_known')!r} "
            f"in {result!r}",
        )
        # The v1 path returns its own response shape (which does
        # not include v2_dispatched). When v2_definition_known is
        # False, the v1 path runs and v2_dispatched is either absent
        # or False (never True).
        self.assertNotEqual(
            result.get("v2_dispatched"),
            True,
            f"v2_dispatched must NOT be True when v2_definition_known "
            f"is False (the v2 path never ran); got {result!r}",
        )
        # --- v1 dispatch path still ran (the fallback) ---
        # The v1 path's status is "dispatched" when the dispatch
        # file is written. We assert that the dispatch landed in
        # the v1-shape location: pending/<handoff.to_god>/<handoff_id>.json.
        v1_dispatch = (
            self.tmp.pending_dir
            / handoff["to_god"]
            / f"{handoff['handoff_id']}.json"
        )
        self.assertTrue(
            v1_dispatch.exists(),
            f"v1 fallback should write the dispatch to {v1_dispatch}; "
            f"pending/{handoff['to_god']}/ contents: "
            f"{list((self.tmp.pending_dir / handoff['to_god']).iterdir())}",
        )


# ===========================================================================
# 3. No routing key at all → v1 fallback
# ===========================================================================

class TestV1FallbackWhenRoutingMissing(unittest.TestCase):
    """No `routing` key at all → the v1 path is the fallback. Same
    shape as the unknown-definition case (v2_definition_known=False).
    """

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.conductor = bridge.Conductor(base_dir=self.tmp.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_v1_fallback_when_routing_missing(self):
        handoff = _make_handoff(
            workflow_id=f"wf_{uuid.uuid4().hex[:8]}",
            from_god="konan",
            to_god="hephaestus",
            step="step1",
            include_routing=False,
        )
        # Sanity: confirm the test really omitted the routing key.
        self.assertNotIn(
            "routing", handoff,
            "test setup should omit the routing key for this case",
        )

        result = self.conductor.submit_handoff(handoff)

        # --- v2 markers: v2_definition_known is False ---
        self.assertIs(
            result.get("v2_definition_known"),
            False,
            f"v2 path should NOT run when routing is missing; "
            f"got {result!r}",
        )
        self.assertNotEqual(
            result.get("v2_dispatched"),
            True,
            f"v2_dispatched must NOT be True when routing is missing; "
            f"got {result!r}",
        )
        # --- v1 fallback still ran ---
        v1_dispatch = (
            self.tmp.pending_dir
            / handoff["to_god"]
            / f"{handoff['handoff_id']}.json"
        )
        self.assertTrue(
            v1_dispatch.exists(),
            f"v1 fallback should write the dispatch to {v1_dispatch}; "
            f"pending/{handoff['to_god']}/ contents: "
            f"{list((self.tmp.pending_dir / handoff['to_god']).iterdir())}",
        )


# ===========================================================================
# 4. v2_dispatched: bool persisted in state['step_history'] (audit trail)
# ===========================================================================

class TestV2DispatchedPersistedInStepHistory(unittest.TestCase):
    """The v2 path appends a step_history entry with
    `v2_dispatched: True` to the on-disk state file. This is the
    audit-trail flag Thoth's design note requires for the v2 path.
    """

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.workflow_id = f"v2-audit-{uuid.uuid4().hex[:8]}"
        self.first_god = "thoth"
        self.first_step_id = "active-goals"
        self.conductor = _build_conductor_with_workflow(
            self.tmp,
            self.workflow_id,
            first_god=self.first_god,
            first_step_id=self.first_step_id,
        )

    def tearDown(self):
        self.tmp.cleanup()
        eng_path = eng.WORKFLOWS_DIR / f"{self.workflow_id}.yaml"
        if eng_path.exists():
            try:
                eng_path.unlink()
            except OSError:
                pass

    def test_v2_dispatched_persisted_in_step_history(self):
        handoff = _make_handoff(
            workflow_id=f"wf_{uuid.uuid4().hex[:8]}",
            from_god="konan",
            to_god=self.first_god,
            step=self.first_step_id,
            routing={"workflow_definition": self.workflow_id},
            handoff_id="hof_20260615_audt010",  # 7-char suffix to match regex
        )

        result = self.conductor.submit_handoff(handoff)

        # Sanity: the v2 path actually ran (v2_dispatched=True).
        self.assertIs(
            result.get("v2_dispatched"),
            True,
            f"v2 path should have run for known definition; got {result!r}",
        )

        v2_wf_id = result.get("workflow_id")
        self.assertTrue(
            isinstance(v2_wf_id, str) and v2_wf_id.startswith("wf_"),
            f"v2 path should mint a wf_<uuid8>; got {v2_wf_id!r}",
        )
        assert isinstance(v2_wf_id, str)  # type narrowing

        # The on-disk state file has the v2-dispatched entry in
        # step_history. This is the audit-trail flag — post-hoc
        # inspection of the state file shows which path was used.
        v2_state_file = self.tmp.state_dir / f"{v2_wf_id}.json"
        self.assertTrue(
            v2_state_file.exists(),
            f"v2 path should have written {v2_state_file}",
        )
        state = json.loads(v2_state_file.read_text())
        step_history = state.get("step_history", [])
        self.assertGreaterEqual(
            len(step_history),
            1,
            f"v2 path should append at least 1 step_history entry; "
            f"got {len(step_history)}: {step_history!r}",
        )

        # Find the entry with v2_dispatched=True.
        v2_entries = [e for e in step_history if e.get("v2_dispatched") is True]
        self.assertGreaterEqual(
            len(v2_entries),
            1,
            f"at least 1 step_history entry must have v2_dispatched=True "
            f"(Step 1.6 audit trail); got {len(v2_entries)} of "
            f"{len(step_history)}: {step_history!r}",
        )

        # The v2-dispatched entry should be for the right step, with
        # the spec-conformant shape (started timestamp, in_progress
        # status, handoff_id recorded).
        e0 = v2_entries[0]
        self.assertEqual(
            e0.get("step_id"),
            self.first_step_id,
            f"v2 step_history entry should be for the first step "
            f"{self.first_step_id!r}; got {e0!r}",
        )
        self.assertEqual(
            e0.get("god"),
            self.first_god,
            f"v2 step_history entry should record the god "
            f"{self.first_god!r}; got {e0!r}",
        )
        self.assertEqual(
            e0.get("status"),
            "in_progress",
            f"v2 step_history entry should be status=in_progress "
            f"until acked; got {e0!r}",
        )
        self.assertIn(
            "started",
            e0,
            f"v2 step_history entry must have a 'started' timestamp; "
            f"got {e0!r}",
        )
        self.assertEqual(
            e0.get("handoff_id"),
            handoff["handoff_id"],
            f"v2 step_history entry should record the handoff_id "
            f"({handoff['handoff_id']!r}); got {e0!r}",
        )


if __name__ == "__main__":
    unittest.main()
