"""Bridge tests — conductor.conductor_server.start_workflow (Phase 1 Step 1.1).

These tests target the SYNC BRIDGE between MCP/theoforge and the v2 engine.
The existing test_engine.py covers `engine.start_workflow` directly, but the
bridge has its own logic:

  - Reject empty/None workflow_id with ValueError
  - Reject unknown workflow_id with ValueError
  - Delegate instance minting + state save to engine.start_workflow_sync()
  - Translate the engine's "in_progress" status → spec's "running" in the
    response shape (the on-disk state file keeps "in_progress")
  - Write a state file at state_dir / "<wf_*.json>"

If the bridge is broken — e.g. it falls back to inline mint+save logic
instead of calling the engine, or it never creates a state file — these
tests catch it. They also assert the engine is being called (no duplication)
by inspecting the call site for the new method.

Run: /home/konan/.hermes/hermes-agent/venv/bin/python3 -m pytest \
        conductor/v2/tests/test_conductor_bridge.py -x -q
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import unittest
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

# Marvin hygiene #2, Step 1.7 polish: canonical import path
# (matches fixtures.py's conductor.v2 import shape; works in every
# pytest invocation regardless of cwd/sys.path setup).
from conductor.v2.tests import fixtures as cf  # noqa: E402

# Import the bridge — the module-level start_workflow + the class method.
import conductor.conductor_server as bridge  # noqa: E402


def _seed_workflow(workflow_id: str, workflows_dir: Path) -> Path:
    """Write a minimal test workflow YAML into the engine's resolved
    workflows dir.

    The caller MUST pass the same `workflows_dir` that the engine will
    read from. The bridge's `_v2_engine()` builds a fresh
    `ConductorEngine()` with no `workflows=` arg, so the engine's
    `WorkflowRegistry` resolves `WORKFLOWS_DIR` at construction time via
    `_workflows_dir()` — which honours the `CONDUCTOR_BASE_DIR` env var
    (see v2/engine.py lines 81-87). `TmpConductor.create()` sets that env
    var to a per-test tmp dir, so the engine reads from the tmp dir.
    The seed has to match.

    Returns the path of the written file so callers can unlink() in tearDown.
    """
    import yaml
    workflows_dir.mkdir(parents=True, exist_ok=True)
    target = workflows_dir / f"{workflow_id}.yaml"
    target.write_text(yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": f"Bridge test {workflow_id}",
            "version": "1.0.0",
            "context": {"required": [], "optional": []},
            "steps": [
                {"id": "step1", "god": "thoth",
                 "output": "test result", "timeout": "5m"},
            ],
        }
    }))
    return target


def _build_conductor(tmp: cf.TmpConductor) -> bridge.Conductor:
    """Build a Conductor instance bound to an existing tmp layout.

    `tmp` is created by the caller (in setUp) BEFORE the workflow YAML
    is seeded, so the engine's WorkflowRegistry will read from the same
    dir the seed wrote to. The state_file ends up at
    `tmp_root/state/wf_*.json` so we don't pollute the production state dir.
    """
    c = bridge.Conductor(base_dir=tmp.root)
    bridge._default = c
    # Stash the tmp on the instance so tearDown can find it
    c._test_tmp = tmp  # type: ignore[attr-defined]
    return c


def _setup_test_layout(workflow_id: str) -> tuple[Path, cf.TmpConductor, bridge.Conductor]:
    """One-shot setUp helper: create the tmp dir (which sets the
    CONDUCTOR_BASE_DIR env var the engine honours), seed a workflow YAML
    into BOTH the engine's resolved workflows dir AND the per-test tmp
    workflows dir, and build a Conductor bound to the same tmp. Returns
    (wf_path, tmp, conductor) for the caller to stash.

    Why seed TWO locations: the Step 1.6 lazy fix made
    `WorkflowRegistry.__init__` resolve `workflows_dir` at construction
    time via the lazy `_workflows_dir()` function (which honours
    `CONDUCTOR_BASE_DIR`). The bridge's `_v2_engine()` builds a fresh
    `ConductorEngine()` which builds a fresh `WorkflowRegistry()` which
    reads from the lazy env-resolved path — that's the per-test tmp
    workflows dir (`tmp.workflows_dir`).

    The session-level `eng.WORKFLOWS_DIR` is the frozen module-level
    constant bound at first-import time. The bridge does not read from
    it (the lazy fix made that path obsolete). But `test_engine.py` and
    other v2-direct-path tests do read from `eng.WORKFLOWS_DIR`. We
    seed both for safety: the per-test tmp is what THIS test's bridge
    path reads from, and `eng.WORKFLOWS_DIR` is what other tests'
    direct-engine paths read from.

    Returns (wf_path, tmp, conductor) for the caller to stash. The
    returned wf_path is the per-test tmp copy; callers should unlink
    it in tearDown. We deliberately do NOT unlink the eng.WORKFLOWS_DIR
    copy from this helper — that's the session-level shared dir and
    other tests may rely on files there.
    """
    from conductor.v2 import engine as eng  # noqa: E402  # canonical
    # Per-test tmp for state/pending (also sets CONDUCTOR_BASE_DIR).
    tmp = cf.TmpConductor.create()
    # Seed into the bridge's lazy-resolved workflows dir (per-test
    # tmp). This is what the bridge path will read from after the
    # Step 1.6 lazy fix.
    wf_path = _seed_workflow(workflow_id, tmp.workflows_dir)
    # Also seed into the session-level eng.WORKFLOWS_DIR so other
    # v2-direct tests in the same pytest run that read from
    # `eng.WORKFLOWS_DIR` (the frozen constant) can find the workflow.
    # This is harmless — the test uses a uuid-suffixed workflow_id so
    # collision is impossible.
    _seed_workflow(workflow_id, eng.WORKFLOWS_DIR)
    conductor = _build_conductor(tmp)
    return wf_path, tmp, conductor


# ===========================================================================
# 1. Happy path
# ===========================================================================

class TestBridgeStartsKnownWorkflow(unittest.TestCase):
    """`start_workflow(<a known wf>)` returns the spec'd shape."""

    def setUp(self):
        # Use a unique workflow id per test method so we never collide
        # with other tests' seeded files in the shared tmp.
        self.wf_id = f"bridge-test-{uuid.uuid4().hex[:8]}"
        self.wf_path, _, self.conductor = _setup_test_layout(self.wf_id)

    def tearDown(self):
        if self.wf_path.exists():
            self.wf_path.unlink()
        # Clean up any wf_*.json the test wrote
        if hasattr(self.conductor, "_test_tmp"):
            tmp = self.conductor._test_tmp  # type: ignore[attr-defined]
            for f in tmp.state_dir.glob("wf_*.json"):
                f.unlink()
            tmp.cleanup()

    def test_bridge_starts_known_workflow(self):
        result = self.conductor.start_workflow(self.wf_id)

        # All spec-required fields present
        for key in ("workflow_id", "definition_id", "status",
                    "current_step", "state_file", "started_at"):
            self.assertIn(key, result, f"missing spec field: {key}")

        # wf_ prefix and unique id
        self.assertTrue(result["workflow_id"].startswith("wf_"),
                        f"workflow_id should start with wf_: {result['workflow_id']}")
        self.assertEqual(result["definition_id"], self.wf_id)

        # status is the spec-facing alias "running", not the engine's "in_progress"
        self.assertEqual(result["status"], "running",
                         "bridge must translate in_progress → running in response")

        # current_step must point at the first step of the workflow
        self.assertEqual(result["current_step"], "step1")

        # state_file is a Path-like string under our tmp dir
        self.assertTrue(result["state_file"].endswith(
            f"{result['workflow_id']}.json"))
        tmp = self.conductor._test_tmp  # type: ignore[attr-defined]
        self.assertIn(str(tmp.state_dir), result["state_file"])


# ===========================================================================
# 2. Error paths
# ===========================================================================

class TestBridgeRejectsBadInput(unittest.TestCase):
    """Empty / None / unknown workflow_id all raise ValueError."""

    def setUp(self):
        self.wf_id = f"bridge-test-{uuid.uuid4().hex[:8]}"
        # The error-path and delegation tests don't strictly need a
        # seeded workflow (they pass bogus/empty/None ids or never call
        # start_workflow), but the bridge's _v2_engine() still constructs
        # an engine and reads the workflows dir, so we go through the
        # same setup shape. This also ensures tearDown has a tmp to clean.
        self.wf_path, _, self.conductor = _setup_test_layout(self.wf_id)

    def tearDown(self):
        if self.wf_path.exists():
            self.wf_path.unlink()
        if hasattr(self.conductor, "_test_tmp"):
            self.conductor._test_tmp.cleanup()  # type: ignore[attr-defined]

    def test_bridge_rejects_empty_workflow_id(self):
        with self.assertRaises(ValueError) as cm:
            self.conductor.start_workflow("")
        self.assertIn("workflow_id", str(cm.exception).lower())

    def test_bridge_rejects_none_workflow_id(self):
        with self.assertRaises(ValueError) as cm:
            self.conductor.start_workflow(None)  # type: ignore[arg-type]
        self.assertIn("workflow_id", str(cm.exception).lower())

    def test_bridge_rejects_unknown_workflow(self):
        bogus = f"definitely-not-a-real-workflow-{uuid.uuid4().hex[:6]}"
        with self.assertRaises(ValueError) as cm:
            self.conductor.start_workflow(bogus)
        self.assertIn("unknown workflow", str(cm.exception).lower())


# ===========================================================================
# 3. State file side-effect
# ===========================================================================

class TestBridgeStateFileIsWritten(unittest.TestCase):
    """After a successful start, a wf_*.json exists at the state_file path."""

    def setUp(self):
        self.wf_id = f"bridge-test-{uuid.uuid4().hex[:8]}"
        # The error-path and delegation tests don't strictly need a
        # seeded workflow (they pass bogus/empty/None ids or never call
        # start_workflow), but the bridge's _v2_engine() still constructs
        # an engine and reads the workflows dir, so we go through the
        # same setup shape. This also ensures tearDown has a tmp to clean.
        self.wf_path, _, self.conductor = _setup_test_layout(self.wf_id)

    def tearDown(self):
        if self.wf_path.exists():
            self.wf_path.unlink()
        if hasattr(self.conductor, "_test_tmp"):
            tmp = self.conductor._test_tmp  # type: ignore[attr-defined]
            for f in tmp.state_dir.glob("wf_*.json"):
                f.unlink()
            tmp.cleanup()

    def test_bridge_state_file_is_written(self):
        result = self.conductor.start_workflow(self.wf_id)
        state_path = Path(result["state_file"])
        self.assertTrue(state_path.exists(),
                        f"state file not written: {state_path}")
        # On-disk file is valid JSON and matches the response workflow_id
        on_disk = json.loads(state_path.read_text())
        self.assertEqual(on_disk["workflow_id"], result["workflow_id"])
        self.assertEqual(on_disk["definition_id"], self.wf_id)
        # Status on disk is the engine's "in_progress", not the alias
        self.assertEqual(on_disk["status"], "in_progress",
                         "on-disk status must remain the engine's invariant; "
                         "the bridge only translates in the response shape")


# ===========================================================================
# 4. No duplication — bridge calls the new engine method
# ===========================================================================

class TestBridgeDelegatesToEngine(unittest.TestCase):
    """The bridge must call engine.start_workflow_sync, not re-implement it.
    This test guards against the BLOCKER 1 regression: if someone reverts
    the refactor and puts the inline mint+save back in the bridge, this
    test fails."""

    def setUp(self):
        self.wf_id = f"bridge-test-{uuid.uuid4().hex[:8]}"
        # The error-path and delegation tests don't strictly need a
        # seeded workflow (they pass bogus/empty/None ids or never call
        # start_workflow), but the bridge's _v2_engine() still constructs
        # an engine and reads the workflows dir, so we go through the
        # same setup shape. This also ensures tearDown has a tmp to clean.
        self.wf_path, _, self.conductor = _setup_test_layout(self.wf_id)

    def tearDown(self):
        if self.wf_path.exists():
            self.wf_path.unlink()
        if hasattr(self.conductor, "_test_tmp"):
            self.conductor._test_tmp.cleanup()  # type: ignore[attr-defined]

    def test_bridge_engine_not_duplicated(self):
        """The bridge source must not contain the inline mint+save logic
        that BLOCKER 1 wanted us to remove. It must delegate to the new
        engine method start_workflow_sync."""
        # 1. The engine method exists
        from conductor.v2 import engine as eng  # noqa: F401
        self.assertTrue(hasattr(eng.ConductorEngine, "start_workflow_sync"),
                        "v2/engine.py must expose start_workflow_sync")

        # 2. The bridge method's source contains a call to start_workflow_sync
        src = inspect.getsource(self.conductor.start_workflow)
        self.assertIn("start_workflow_sync", src,
                      "bridge start_workflow must call engine.start_workflow_sync")
        # 3. The bridge source does NOT contain the inline mint+save markers
        #    (the BLOCKER 1 anti-pattern). These strings only existed in the
        #    duplicated copy of the engine logic; if they reappear here, the
        #    refactor has been undone.
        anti_patterns = [
            "from conductor.v2.engine import WorkflowInstance",
            "wf_{_uuid.uuid4().hex[:8]}",
        ]
        for anti in anti_patterns:
            self.assertNotIn(anti, src,
                             f"bridge re-implements engine logic (found '{anti}')")

    def test_bridge_module_level_wrapper_uses_engine(self):
        """The module-level start_workflow() must delegate to the class method,
        which delegates to the engine. Verify the module-level wrapper's
        source delegates correctly."""
        src = inspect.getsource(bridge.start_workflow)
        self.assertIn("_default.start_workflow", src,
                      "module-level start_workflow must call _default.start_workflow")

    def test_engine_sync_variant_skips_asyncio_create_task(self):
        """The sync variant must NOT schedule async step execution. We verify
        this by calling it directly with a real workflow and confirming the
        instance is registered in _instances (sync write) and the function
        returns synchronously without requiring a running event loop."""
        from conductor.v2 import engine as eng  # noqa: F401
        eng_instance = eng.ConductorEngine(
            gateway_client=None,
            rules=eng.RuleEngine(),
            workflows=eng.WorkflowRegistry(),  # reads from WORKFLOWS_DIR
            pending_dir=self.conductor._test_tmp.pending_dir,  # type: ignore[attr-defined]
            state_dir=self.conductor._test_tmp.state_dir,  # type: ignore[attr-defined]
        )
        inst = eng_instance.start_workflow_sync(self.wf_id)
        self.assertTrue(inst.workflow_id.startswith("wf_"))
        self.assertEqual(inst.definition_id, self.wf_id)
        # The instance was added to the engine's in-memory dict
        self.assertIn(inst.workflow_id, eng_instance._instances)
        # The on-disk state file exists
        on_disk = eng_instance.state_dir / f"{inst.workflow_id}.json"
        self.assertTrue(on_disk.exists())


if __name__ == "__main__":
    unittest.main()
