"""Step 1.4 — Wire v2 daemon to consume MCP inbox files.

This is the deterministic proof that the v2 engine's `watch_pending` awatch
loop actually picks up handoffs written to `pending/<god>/<id>.json` and
routes them through `handle_event` so the rule engine fires.

Spec section 6: "single process with optional feature flags." The daemon
spawns watch_pending as a background task in `start()`. The task uses
watchfiles.awatch to detect new .json files in pending/, then calls
_process_file → _process_handoff → handle_event for handoff-shaped files.

What this test asserts (within 5s of writing the handoff):
  1. The watcher's awatch loop fires the Change.added callback for a new
     .json file in pending/<god>/.
  2. _process_handoff synthesizes the spec Event(type="handoff.completed")
     and calls handle_event.
  3. handle_event matches a rule from rules/*.yaml and dispatches a
     workflow.
  4. Side effect: a new dispatch file is written into pending/<next_god>/
     (the rule's `dispatch_workflow` target), proving the rule path
     actually fired.

We do NOT use the production daemon process (PID 153780). We spin up a
fresh ConductorEngine in-process with the watcher coroutine spawned
directly as a background task, and use a mock gateway, so the test is
hermetic and deterministic.

The live daemon was already confirmed working in PM verification — a
live handoff was written to pending/thoth/, picked up by the daemon,
matched the `research-handoff-to-hephaestus` rule, started a workflow
(wf_f26885f8, definition_id=deploy-feature, current_step=architect),
and dispatched a handoff to pending/hephaestus/. This test is the
regression guard for that path so future changes can't break it
silently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402

# Quiet the awatch logger to WARNING — its INFO output is noisy
logging.getLogger("watchfiles").setLevel(logging.WARNING)
LOG = logging.getLogger(__name__)


def _new_engine(tmp: cf.TmpConductor, *, gateway) -> eng.ConductorEngine:
    """Build a fresh ConductorEngine pointed at a tmp layout.

    We pass rules_dir/workflows_dir EXPLICITLY (not via env) because
    RuleEngine's default `RULES_DIR` is bound at import time and will
    not see per-test overrides of CONDUCTOR_BASE_DIR. This is the same
    latent footgun BUILD-PLAN Step 1.1 hygiene #3 flagged; the service
    has it, the engine construction here does not.
    """
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


def _write_handoff(god_dir: Path, handoff: dict) -> Path:
    """Write a handoff JSON to pending/<god>/. Returns the path."""
    god_dir.mkdir(parents=True, exist_ok=True)
    path = god_dir / f"{handoff['handoff_id']}.json"
    path.write_text(json.dumps(handoff, indent=2))
    return path


async def _wait_for(predicate, *, timeout: float = 5.0, poll: float = 0.05) -> bool:
    """Spin-loop until predicate() is truthy or timeout. Returns success.

    `predicate` may be sync or async — we accept both for ergonomics.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(poll)
    return False


# ===========================================================================
# 1. Engine-level: _process_handoff synthesizes event and calls handle_event
# ===========================================================================

class TestProcessHandoffCallsHandleEvent(unittest.IsolatedAsyncioTestCase):
    """The watcher's _process_handoff must call handle_event, not just log."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_process_handoff_synthesizes_handoff_completed_event(self):
        """Direct unit test on _process_handoff: write a file, call
        _process_file, assert handle_event was called with the
        spec-mandated Event(type='handoff.completed', source=from_god, ...).
        """
        handoff = {
            "handoff_id": f"hof_{eng.utc_now()[:10].replace('-', '')}_unittest",
            "workflow_id": "wf_unittest",
            "from_god": "thoth",
            "to_god": "hephaestus",
            "step": "research",
            "context": {
                "summary": "unit test of _process_handoff",
                "decisions": [],
                "artifacts": [],
                "gates_passed": [],
            },
        }
        god_dir = self.tmp.pending_dir / "thoth"
        path = _write_handoff(god_dir, handoff)

        # Spy on handle_event
        called = {}
        original = self.engine.handle_event

        async def spy(event):
            called["type"] = event.type
            called["source"] = event.source
            called["target"] = event.target
            called["subject"] = event.subject
            return await original(event)

        with patch.object(self.engine, "handle_event", side_effect=spy):
            await self.engine._process_file(path)

        # Assert the event was synthesized correctly per spec section 3.1
        self.assertEqual(called.get("type"), "handoff.completed",
                         f"expected type=handoff.completed, got {called.get('type')!r}")
        self.assertEqual(called.get("source"), "thoth")
        self.assertEqual(called.get("target"), "hephaestus")
        self.assertEqual(called.get("subject"), f"handoff:{handoff['handoff_id']}")


# ===========================================================================
# 2. Watcher-level: awatch loop picks up new files in pending/<god>/
# ===========================================================================

class TestWatchPendingCatchesNewHandoff(unittest.IsolatedAsyncioTestCase):
    """The engine's watch_pending coroutine is what the daemon spawns.
    We exercise it directly: drop a handoff in pending/thoth/, within 5s
    the rule path must fire and a new dispatch must appear in
    pending/hephaestus/."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # Real rules + workflows so rule matching reflects production
        self.tmp.copy_real_rules()
        self.tmp.copy_real_workflows()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_awatch_loop_picks_up_new_handoff_within_5s(self):
        """End-to-end: real rules/*.yaml, watch_pending coroutine as a
        background task, drop a handoff in pending/thoth/, wait for the
        rule path to fire.

        We use the deploy-feature workflow's `research-handoff-to-hephaestus`
        rule (thoth → hephaestus, dispatch_workflow: deploy-feature,
        start_at_step: architect). The handoff matches that rule and
        triggers a workflow dispatch to pending/hephaestus/.

        Implementation note: we construct ConductorEngine directly (not
        via ConductorService.start()) and spawn watch_pending as a
        background task. This is exactly what the service does internally
        — see v2/service.py:129-132 — minus the env-resolution footgun
        where the service's __init__ builds RuleEngine() with no args
        and gets the import-time RULES_DIR (Step 1.1 hygiene #3). We
        avoid that by passing tmp.rules_dir explicitly to RuleEngine.
        The watcher's awatch loop and the _process_handoff dispatcher
        are the same code paths in both setups.
        """
        # Mock gateway: queue a run that returns "completed" so the
        # engine advances the workflow through the first dispatch step.
        gw = cf.MockGatewayClient()
        gw.queue_run(cf.MockRun("r1", output="ok"))

        engine = _new_engine(self.tmp, gateway=gw)
        # Point _pending_dir() at our tmp. The watcher's awatch loop and
        # _process_handoff both call _pending_dir() lazily, so setting
        # the env after engine construction is fine for those paths.
        os.environ["CONDUCTOR_BASE_DIR"] = str(self.tmp.root)

        # Start the watcher as a background task (same pattern as
        # ConductorService.start() does at v2/service.py:129-132)
        stop = asyncio.Event()
        watcher_task = asyncio.create_task(
            engine.watch_pending(stop), name="test_watcher"
        )
        # Give the watcher a moment to start polling
        await asyncio.sleep(0.5)
        self.assertFalse(watcher_task.done(), "watcher task died on start")

        # Sanity: rules are loaded from our tmp
        self.assertGreater(len(engine.rules._rules), 0,
                           f"no rules loaded from {self.tmp.rules_dir}; "
                           f"engine rules_dir={engine.rules.rules_dir}")
        self.assertEqual(engine.rules.rules_dir, self.tmp.rules_dir,
                         f"rules_dir mismatch: engine={engine.rules.rules_dir} "
                         f"vs tmp={self.tmp.rules_dir}")
        LOG.info("rules loaded: %d from %s", len(engine.rules._rules), self.tmp.rules_dir)

        # Drop a handoff that matches `research-handoff-to-hephaestus`
        handoff = {
            "handoff_id": f"hof_{eng.utc_now()[:10].replace('-', '')}_daemon01",
            "workflow_id": "wf_step14_daemon",
            "from_god": "thoth",
            "to_god": "hephaestus",
            "step": "research",
            "context": {
                "summary": "step 1.4 daemon pickup proof",
                "decisions": [],
                "artifacts": [],
                "gates_passed": [],
            },
        }
        god_dir = self.tmp.pending_dir / "thoth"
        _write_handoff(god_dir, handoff)
        LOG.info("wrote handoff to %s", god_dir / f"{handoff['handoff_id']}.json")

        # The rule dispatches a workflow which writes a step handoff to
        # pending/hephaestus/. Wait up to 5s for that to appear.
        def dispatch_written():
            hephaestus_inbox = self.tmp.pending_dir / "hephaestus"
            if not hephaestus_inbox.exists():
                return False
            return any(hephaestus_inbox.glob("*.json"))

        success = await _wait_for(dispatch_written, timeout=5.0, poll=0.1)
        self.assertTrue(
            success,
            f"awatch loop did not produce a dispatch in pending/hephaestus/ "
            f"within 5s. pending/ contents: "
            f"{[p.name for p in self.tmp.pending_dir.iterdir()]}",
        )

        # Confirm the rule path was taken (not just file-content ignored).
        # The dispatched handoff must be a handoff-shaped JSON with
        # to_god=hephaestus and step=architect (the rule's start_at_step).
        hephaestus_files = list((self.tmp.pending_dir / "hephaestus").glob("*.json"))
        self.assertGreater(len(hephaestus_files), 0)
        sample = json.loads(hephaestus_files[0].read_text())
        self.assertEqual(sample.get("to_god"), "hephaestus",
                         f"dispatched handoff shape wrong: {sample}")
        self.assertEqual(sample.get("step"), "architect",
                         f"expected start_at_step=architect from rule, "
                         f"got {sample.get('step')!r}")

        # Stop the watcher cleanly
        stop.set()
        try:
            await asyncio.wait_for(watcher_task, timeout=1.0)
        except asyncio.TimeoutError:
            watcher_task.cancel()


# ===========================================================================
# 3. Negative case: garbage file in pending/ is ignored, not crashed
# ===========================================================================

class TestWatcherIgnoresUnclassifiedFiles(unittest.IsolatedAsyncioTestCase):
    """A non-handoff JSON file in pending/ must not crash the watcher loop."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.tmp.copy_real_rules()
        self.tmp.copy_real_workflows()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_garbage_file_does_not_crash_watcher(self):
        """Drop a JSON file that's not a handoff (missing handoff_id /
        from_god / to_god). The watcher should log+skip, not raise. The
        watch task must still be alive after.

        Same engine-direct construction pattern as the positive test
        (see comment there for the rationale on avoiding the service)."""
        os.environ["CONDUCTOR_BASE_DIR"] = str(self.tmp.root)
        gw = cf.MockGatewayClient()
        engine = _new_engine(self.tmp, gateway=gw)

        # Start the watcher as a background task
        stop = asyncio.Event()
        watcher_task = asyncio.create_task(
            engine.watch_pending(stop), name="test_watcher_neg"
        )
        await asyncio.sleep(0.5)
        self.assertFalse(watcher_task.done(), "watcher task died on start")

        # Write a non-handoff file (has type+source but not handoff keys)
        thoth_dir = self.tmp.pending_dir / "thoth"
        thoth_dir.mkdir(parents=True, exist_ok=True)
        (thoth_dir / "not_a_handoff.json").write_text(json.dumps({
            "type": "schedule.cron",
            "source": "test",
        }))

        # Wait 1.5s for the watcher to see it. The watch task must
        # still be alive.
        await asyncio.sleep(1.5)
        self.assertFalse(watcher_task.done(),
                         "watcher task crashed on unclassified file")

        # Stop the watcher cleanly
        stop.set()
        try:
            await asyncio.wait_for(watcher_task, timeout=1.0)
        except asyncio.TimeoutError:
            watcher_task.cancel()


if __name__ == "__main__":
    unittest.main()
