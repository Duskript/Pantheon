"""Step 2.3 E2E — full ConductorService + cron scheduler fires a real workflow.

This is the slow test. It spins up the real ConductorService (with
NATS + webhook disabled so we don't need those services), starts the
CronScheduler with a 0.5s tick and a `* * * * *` rule pointing at a
minimal test workflow, and waits long enough for the cron boundary to
be crossed. Then asserts the workflow instance was created and the
test step executed.

Mark: @pytest.mark.slow
Run: PYTHONPATH=/home/konan/pantheon PANTHEON_ROOT=/home/konan/pantheon \\
     pytest conductor/v2/tests/test_cron_e2e.py -v --runslow
Skip: included by default — `pytest conductor/v2/tests/` does NOT run this.

The test is conservative on timeouts: it waits UP TO 70s (capped) for
the next cron boundary, then asserts. If we miss the boundary by more
than 0.5s, the scheduler will still fire on the next tick after the
boundary (the per-rule next_fire is anchored to the just-fired time,
not wall-clock). So 70s is overkill in practice — typical run is
< 65s.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

# Phase 2 PM-fix: `os` and `shutil` were used by the original
# asyncSetUp to mutate CONDUCTOR_BASE_DIR. The new approach uses
# pytest's tmp_path fixture + explicit constructor args to the
# RuleEngine / WorkflowRegistry / ConductorService, so direct
# os.environ / shutil.rmtree calls are no longer the primary
# mechanism. We still keep `os` and `shutil` available in case
# the teardown path needs them for cleanup.
import pytest

# Match the v2 test pattern.
sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import engine as eng  # noqa: E402
from v2.cron_scheduler import CronScheduler  # noqa: E402

LOG = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _write_workflow(workflows_dir: Path, workflow_id: str) -> Path:
    """Minimal 1-step test workflow. The step is a god call so the
    gateway mock gets exercised end-to-end. We pre-queue a mock run
    below so the gateway doesn't hang."""
    body = {
        "workflow": {
            "id": workflow_id,
            "name": f"E2E test {workflow_id}",
            "version": "1.0.0",
            "context": {"required": [], "optional": []},
            "steps": [{
                "id": "test-step",
                "god": "marvin",
                "skill": "noop",
                "action": "test",
                "output": "test_result",
                "timeout": "5s",
            }],
        }
    }
    path = workflows_dir / f"{workflow_id}.yaml"
    path.write_text(json.dumps(body, indent=2))
    return path


def _write_rule(rules_dir: Path, rule_id: str, workflow_id: str) -> Path:
    body = {"rules": [{
        "id": rule_id,
        "when": {
            "event_type": "schedule.cron",
            "expression": "* * * * *",  # every minute
        },
        "then": {
            "dispatch_workflow": workflow_id,
        },
    }]}
    path = rules_dir / f"{rule_id}.yaml"
    path.write_text(json.dumps(body, indent=2))
    return path


# ----------------------------------------------------------------------
# E2E
# ----------------------------------------------------------------------

@pytest.mark.slow
class TestCronE2E(unittest.IsolatedAsyncioTestCase):
    """End-to-end: ConductorService + CronScheduler + workflow dispatch.

    Uses unittest.IsolatedAsyncioTestCase because the daemon holds
    open asyncio tasks and an event loop; this isolates the loop from
    the test runner's loop and prevents teardown races.
    """

    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        # These are set in asyncSetUp; declared here for type-checkers
        # and so the class signature is self-documenting.
        self.test_root: Path
        self.rules_dir: Path
        self.workflows_dir: Path
        self.pending_dir: Path
        self.state_dir: Path
        self.test_rules: "eng.RuleEngine"
        self.test_workflows: "eng.WorkflowRegistry"
        self.workflow_id: str
        self.rule_id: str
        self._saved_pantheon_root: Optional[str]
        self._saved_base_dir: Optional[str]
        # Pytest's tmp_path is set via the `_pytest_fixtures` autouse
        # fixture below (defined as a generator-style fixture so it
        # can clean up after itself). It's a per-test fresh dir that
        # the conftest's env-guard is already aware of.
        self._pytest_tmp_path: Path

    @pytest.fixture(autouse=True)
    def _pytest_fixtures(self, tmp_path):
        """
        Pytest fixture bridge for unittest.IsolatedAsyncioTestCase.

        unittest's IsolatedAsyncioTestCase doesn't natively support
        pytest fixtures via `def test_foo(self, tmp_path):`, but a
        generator-style `@pytest.fixture(autouse=True)` method on
        the class DOES get called by pytest before each test method.
        We stash the injected `tmp_path` on `self` so asyncSetUp
        can pick it up. The yield + return acts as a no-op
        teardown — pytest's tmp_path lifecycle handles cleanup.
        """
        self._pytest_tmp_path = tmp_path
        yield

    async def asyncSetUp(self):
        """
        Phase 2 PM-fix: don't fight the conftest's env-guard.

        The original asyncSetUp set CONDUCTOR_BASE_DIR to a fresh tmp
        dir, but the conftest's pytest_runtest_setup env-guard had
        already pinned the env var to a DIFFERENT per-test tmp dir
        (the conftest-managed one). When ConductorService() ran, it
        read CONDUCTOR_BASE_DIR and got the conftest's tmp, not ours,
        so it found zero rules and the test failed at the "rule
        not loaded" assertion.

        The fix: don't rely on the env var at all. Use pytest's
        tmp_path fixture (which the env-guard already routes
        correctly), write the rule + workflow there, and pass the
        rules_dir / workflows_dir EXPLICITLY to RuleEngine /
        WorkflowRegistry. Then inject those pre-built instances into
        ConductorService via the new `rules` / `workflows` kwargs
        (Phase 2 PM-fix on the service signature). The service
        never touches CONDUCTOR_BASE_DIR for the registries — it
        uses the injected ones. Conftest env-guard is no longer
        fighting the test.
        """
        import os
        import shutil
        from conductor.v2.engine import RuleEngine, WorkflowRegistry

        # Use pytest's tmp_path fixture (passed in via DI in test_*)
        # — the conftest env-guard is already aware of it.
        # We create our own sub-tree for the test inside tmp_path.
        self.test_root = self._pytest_tmp_path / "cron_e2e"
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.rules_dir = self.test_root / "rules"
        self.workflows_dir = self.test_root / "workflows"
        self.pending_dir = self.test_root / "pending"
        self.state_dir = self.test_root / "state"
        for d in (self.rules_dir, self.workflows_dir,
                  self.pending_dir, self.state_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Pin PANTHEON_ROOT / CONDUCTOR_BASE_DIR for the engine's
        # lazy path resolvers (which still read from env in some
        # code paths even when the registries are injected). This
        # is best-effort; the injected registries are the
        # authoritative source.
        self._saved_pantheon_root = os.environ.get("PANTHEON_ROOT")
        self._saved_base_dir = os.environ.get("CONDUCTOR_BASE_DIR")
        os.environ["PANTHEON_ROOT"] = str(self.test_root.parent.parent)
        os.environ["CONDUCTOR_BASE_DIR"] = str(self.test_root)

        # Write the test rule + workflow into OUR dir.
        self.workflow_id = "e2e-cron-fire"
        self.rule_id = "e2e-cron-rule"
        _write_workflow(self.workflows_dir, self.workflow_id)
        _write_rule(self.rules_dir, self.rule_id, self.workflow_id)

        # Build the registries with EXPLICIT paths pointing at our
        # test dirs. The conftest's env-guard can't touch these —
        # the constructors only use the path we pass.
        self.test_rules = RuleEngine(rules_dir=self.rules_dir)
        self.test_workflows = WorkflowRegistry(workflows_dir=self.workflows_dir)

    async def asyncTearDown(self):
        """Restore the env vars we mutated. The injected registries
        and tmp dirs are GC'd when the test instance goes away."""
        import os
        import shutil
        if self._saved_pantheon_root is None:
            os.environ.pop("PANTHEON_ROOT", None)
        else:
            os.environ["PANTHEON_ROOT"] = self._saved_pantheon_root
        if self._saved_base_dir is None:
            os.environ.pop("CONDUCTOR_BASE_DIR", None)
        else:
            os.environ["CONDUCTOR_BASE_DIR"] = self._saved_base_dir
        if self.test_root.exists():
            shutil.rmtree(self.test_root, ignore_errors=True)

    async def test_conductor_service_with_cron_scheduler_fires_workflow(self):
        # Patch GatewayClient inside the service module so the
        # service's start() doesn't try to reach the real Hermes
        # api_server. We use a stable in-process replacement.
        with patch("conductor.v2.service.GatewayClient") as mock_gw_cls, \
             patch("conductor.v2.nats.NATSListener"), \
             patch("conductor.v2.webhook.WebhookServer"):
            # Build a mock gateway that returns programmable runs
            # (the test workflow's only step is a god call).
            from v2 import gateway as gw_mod
            from v2.tests.fixtures import MockRun
            mock_gw = cf.MockGatewayClient()
            mock_gw.queue_run(MockRun("e2e_run_1", output="e2e test passed"))
            mock_gw_cls.return_value = mock_gw

            # Construct the service with a 0.5s cron tick and
            # NATS/webhook disabled. The 0.5s tick is fast enough to
            # never miss a 60s boundary in practice.
            #
            # Phase 2 PM-fix: pass the pre-built registries via the
            # new `rules` / `workflows` kwargs so the service uses
            # them directly instead of reading CONDUCTOR_BASE_DIR.
            # This is the whole point of the refactor — we never
            # depend on env-var state.
            from conductor.v2.service import ConductorService
            svc = ConductorService(
                enable_nats=False,
                enable_webhook=False,
                cron_tick_interval=0.5,
                rules=self.test_rules,
                workflows=self.test_workflows,
            )
            # Sanity: the rule + workflow are in the injected set.
            # The service uses them as-is, no env-var lookup.
            self.assertTrue(
                any(r.id == self.rule_id for r in svc.rules._rules),
                f"rule {self.rule_id} not in loaded rules: "
                f"{[r.id for r in svc.rules._rules]}",
            )
            self.assertIsNotNone(
                svc.workflows.get(self.workflow_id),
                f"workflow {self.workflow_id} not loaded",
            )

            # Start the service — this creates the engine, gateway,
            # and the cron scheduler task.
            await svc.start()
            try:
                self.assertIsNotNone(svc.cron, "service.cron was not created")
                self.assertIsNotNone(svc.cron._task, "cron task was not started")
                # The engine should also be running.
                self.assertIsNotNone(svc.engine)

                # Compute the next cron boundary, then wait past it.
                # Cap the wait at 70s so the test can't hang forever.
                from croniter import croniter
                now = datetime.now(timezone.utc)
                nxt = croniter("* * * * *", now).get_next(datetime)
                wait = min((nxt - now).total_seconds() + 2.0, 70.0)
                LOG.info(
                    f"E2E cron: now={now.isoformat()}, next={nxt.isoformat()}, "
                    f"waiting {wait:.2f}s for the scheduler to fire"
                )
                await asyncio.sleep(wait)

                # Assertions:
                # 1. The cron scheduler emitted at least one event.
                self.assertGreaterEqual(
                    svc.cron.fired_count, 1,
                    f"expected at least one cron fire, got {svc.cron.fired_count}",
                )
                # 2. The event shape is right.
                ev = svc.cron.last_event
                self.assertIsNotNone(ev)
                self.assertEqual(ev.type, "schedule.cron")
                self.assertEqual(ev.source, "cron")
                self.assertEqual(ev.subject, self.rule_id)
                self.assertEqual(ev.payload["rule_id"], self.rule_id)
                # 3. A workflow instance was created. It may have
                # already completed (the 1-step workflow finished
                # during our wait) — check both list_active and
                # list_all.
                active = svc.engine.list_active()
                all_insts = svc.engine.list_all()
                matching_active = [
                    i for i in active if i.definition_id == self.workflow_id
                ]
                matching_all = [
                    i for i in all_insts if i.definition_id == self.workflow_id
                ]
                self.assertGreaterEqual(
                    len(matching_all), 1,
                    f"no workflow instance for {self.workflow_id} "
                    f"in list_all() — handle_event() did NOT dispatch",
                )
                # The instance is either still active (in_progress)
                # or completed (we waited long enough for the 1-step
                # workflow to finish). Both are fine.
                inst = matching_all[0]
                self.assertEqual(inst.definition_id, self.workflow_id)
                self.assertEqual(inst.definition_version, "1.0.0")
                self.assertEqual(inst.initiator, "cron")
                # And the event payload was plumbed into the context.
                self.assertIn("event_payload", inst.context_bag)
                self.assertEqual(
                    inst.context_bag["event_payload"]["rule_id"],
                    self.rule_id,
                )
                # 4. The gateway was called (the workflow's first
                # step is a god call). At least one submit_run()
                # should have been recorded by the mock.
                self.assertGreaterEqual(
                    len(mock_gw.calls), 1,
                    f"no gateway calls recorded — workflow step didn't run: "
                    f"{mock_gw.calls}",
                )
                # The call's model should be the step's god (marvin).
                self.assertEqual(mock_gw.calls[0]["model"], "marvin")
            finally:
                # Stop the service — this should cancel the cron
                # scheduler and all other background tasks.
                await svc.stop()
                # The cron task should be cancelled.
                self.assertTrue(
                    svc.cron._task is None or svc.cron._task.done(),
                    "cron task was not stopped",
                )
