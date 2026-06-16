"""Tests for the sovereign-outbound nats_publish guard (2026-06-15).

Root cause: wf_8a0b5f28 and wf_f26885f8 fired unapproved NATS publishes
to subspace.konan.outgoing.tallon even though all prior steps in the
workflow had been refused. The state file was marked `status=completed`
for a workflow whose outputs were entirely refusals + 1 unauthorized
publish. This module pins the engine-side fix:

  - `_is_sovereign_outbound` identifies cross-Pantheon publish subjects
  - `_exec_nats_publish` blocks sovereign outbound unless (a) every
    prior step is `status=completed`, (b) the workflow is still
    in_progress, and (c) the operator has issued a single-use
    `operator_approval_token` in context_bag
  - `_record_step_completion` flips a gateway-`completed` run to
    `refused` when the output contains a refusal marker, so the
    sovereign-outbound guard sees the truthful refusal

These tests are the load-bearing pin: if the regex or the guard
drift, the next dual-NATS breach happens silently. The
deploy-feature workflow is used as the real-world fixture because
it is the workflow that fired the 2026-06-15 breach.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

# Import the engine + fixtures the way the existing v2 tests do (see
# test_engine.py:35-39). The conftest's sys.path manipulation makes
# `v2.engine` and `v2.tests.fixtures` resolvable, and matching the
# existing import style means the engine singleton / module path is
# consistent with the rest of the test suite.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402


def _new_engine(tmp: cf.TmpConductor, *, gateway: cf.MockGatewayClient):
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


# ===========================================================================
# 1. Unit tests for the sovereign-outbound regex
# ===========================================================================

class TestIsSovereignOutbound(unittest.TestCase):
    """Pin the SOVEREIGN_OUTBOUND_RE regex against the 2026-06-15
    breach subject + the close-but-not-equal cases that must NOT be
    gated (morning-briefing inbox, test inbox)."""

    def test_tallon_breach_subject_matches(self):
        # The exact subject from wf_8a0b5f28 + wf_f26885f8
        self.assertTrue(eng._is_sovereign_outbound(
            "subspace.konan.outgoing.tallon"))

    def test_general_outgoing_pattern_matches(self):
        self.assertTrue(eng._is_sovereign_outbound(
            "subspace.foo.outgoing.bar"))
        self.assertTrue(eng._is_sovereign_outbound(
            "subspace.konan.outgoing.tallon.deploy"))

    def test_morning_briefing_inbox_does_not_match(self):
        # The morning-briefing workflow's nats_publish step — this
        # MUST stay un-gated, or we'll break the existing test.
        self.assertFalse(eng._is_sovereign_outbound(
            "subspace.konan.inbox"))

    def test_incoming_does_not_match(self):
        # Tallon's inbox is `subspace.tallon.incoming.*` — local
        # routing, not sovereign outbound.
        self.assertFalse(eng._is_sovereign_outbound(
            "subspace.tallon.incoming.notify"))
        self.assertFalse(eng._is_sovereign_outbound(
            "subspace.konan.inbox"))

    def test_test_inbox_does_not_match(self):
        # The cron-binding test's subject
        self.assertFalse(eng._is_sovereign_outbound(
            "subspace.test.inbox"))

    def test_empty_and_none_do_not_match(self):
        self.assertFalse(eng._is_sovereign_outbound(""))
        self.assertFalse(eng._is_sovereign_outbound(None))  # type: ignore[arg-type]

    def test_non_subspace_subjects_do_not_match(self):
        self.assertFalse(eng._is_sovereign_outbound("foo.bar.baz"))
        self.assertFalse(eng._is_sovereign_outbound("subspace.konan"))


# ===========================================================================
# 2. notify-enterprise breach-blocked scenarios (the real-world test)
# ===========================================================================

def _write_deploy_feature_with_sovereign_notify(tmp: cf.TmpConductor) -> Path:
    """Write a copy of the real deploy-feature workflow into the tmp
    workflows dir. We use the production file as the fixture so this
    test catches drift if deploy-feature.yaml is edited."""
    src = Path("/home/konan/pantheon/conductor/workflows/deploy-feature.yaml")
    dst = tmp.workflows_dir / "deploy-feature.yaml"
    dst.write_text(src.read_text())
    return dst


class TestSovereignOutboundBlocks(unittest.IsolatedAsyncioTestCase):
    """End-to-end: run deploy-feature with refusals + a sovereign
    nats_publish step, expect the publish to be blocked and the
    workflow to abort. This is the exact failure mode of the
    2026-06-15 breach, now pinned as a regression test."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)
        _write_deploy_feature_with_sovereign_notify(self.tmp)
        self.engine.workflows.reload()

    def tearDown(self):
        self.tmp.cleanup()

    async def _wait_terminal(self, wf_id: str, max_polls: int = 100) -> eng.WorkflowInstance:
        for _ in range(max_polls):
            await asyncio.sleep(0.05)
            inst = self.engine.get_instance(wf_id)
            if inst and inst.status in ("completed", "failed", "aborted"):
                return inst
        raise AssertionError(f"workflow {wf_id} did not reach terminal state in {max_polls} polls")

    async def test_breach_blocked_when_no_operator_approval(self):
        """The 2026-06-15 failure mode: every prior step is refused
        (god-level refusal text), the workflow reaches notify-enterprise
        anyway, and the publish must be blocked."""
        # Queue god-run outputs that mimic the 2026-06-15 refusals.
        # deploy-feature has 5 god steps (research, architect, implement,
        # review, project-manager); notify-enterprise is a nats_publish
        # with no god run. Each god run is a real refusal the regex
        # will catch.
        self.gw.queue_run(cf.MockRun("r1", output=(
            "Refused `wf_test` research dispatch — wrong god, no real "
            "work to do, this is a smoke test."
        )))
        self.gw.queue_run(cf.MockRun("r2", output=(
            "Refused `wf_test` architect dispatch — HELD the dispatch. "
            "Wrong god. No architecture work to do."
        )))
        self.gw.queue_run(cf.MockRun("r3", output=(
            "Refused `wf_test` implement dispatch — wrong god. No "
            "implementation to do. Same failure mode."
        )))
        self.gw.queue_run(cf.MockRun("r4", output=(
            "Refused `wf_test` review dispatch — no real "
            "implementation to review."
        )))
        self.gw.queue_run(cf.MockRun("r5", output=(
            "Done. HELD the dispatch — would have fabricated a sprint "
            "record on top of fabricated work. No operator_approval_token."
        )))
        inst = self.engine.start_workflow(
            "deploy-feature",
            context={"spec_summary": "smoke test", "artifacts": [],
                     "decisions": []},
            original_request="handoff:hof_smoke_breach_repro",
        )
        final = await self._wait_terminal(inst.workflow_id)
        # The publish must have been blocked. The workflow must be aborted.
        self.assertEqual(final.status, "aborted",
                         f"expected aborted, got {final.status} "
                         f"with history: {[(h['step_id'], h.get('status')) for h in final.step_history]}")
        # No nats_publishes in context_bag — the block must have stopped
        # the publish, not just recorded the intent.
        self.assertNotIn("nats_publishes", final.context_bag,
                         f"nats_publishes must NOT be recorded when blocked; "
                         f"context_bag keys: {list(final.context_bag.keys())}")
        # The notify-enterprise step must have a terminal breach_blocked
        # entry. There may also be an in_progress entry (the engine
        # recorded start before the guard ran) — the test pins that
        # AT LEAST ONE entry is breach_blocked.
        notify_entries = [h for h in final.step_history
                          if h["step_id"] == "notify-enterprise"]
        self.assertGreaterEqual(len(notify_entries), 1)
        breach_entries = [h for h in notify_entries
                          if h.get("status") == "breach_blocked"]
        self.assertEqual(len(breach_entries), 1,
                         f"expected exactly 1 breach_blocked entry, "
                         f"got {len(breach_entries)}: {breach_entries}")
        self.assertIn("block_reason", breach_entries[0])
        # The block reason must mention the missing approval.
        self.assertIn("operator_approval_token", breach_entries[0]["block_reason"])
        # The block reason must mention that prior steps were not clean.
        self.assertIn("prior step", breach_entries[0]["block_reason"])
        # An abort manifest must exist (operator visibility).
        manifests = list(self.tmp.state_dir.glob("*.aborted.json"))
        self.assertEqual(len(manifests), 1)
        manifest = json.loads(manifests[0].read_text())
        self.assertIn("sovereign outbound blocked", manifest["failure_reason"])

    async def test_breach_blocked_when_all_prior_refused(self):
        """Same scenario but with operator approval present — still
        blocked because the prior step refused. The approval alone
        is not enough; the prior history must also be clean."""
        self.gw.queue_run(cf.MockRun("r1", output=(
            "Refused `wf_test` research dispatch — wrong god, no work."
        )))
        self.gw.queue_run(cf.MockRun("r2", output=(
            "Refused `wf_test` architect dispatch — HELD the dispatch."
        )))
        self.gw.queue_run(cf.MockRun("r3", output=(
            "Refused `wf_test` implement dispatch — wrong god. No work."
        )))
        self.gw.queue_run(cf.MockRun("r4", output=(
            "Refused `wf_test` review dispatch — no implementation."
        )))
        self.gw.queue_run(cf.MockRun("r5", output=(
            "Done. HELD the dispatch — refused. No update_sprint."
        )))
        inst = self.engine.start_workflow(
            "deploy-feature",
            context={
                "spec_summary": "test",
                "artifacts": [],
                "decisions": [],
                # The approval token is present — but the prior
                # history is dirty, so the guard must still block.
                # The workflow_id is wrong on purpose: tests the
                # workflow_id-binding check too.
                "operator_approval_token": {
                    "workflow_id": "wf_some_other_workflow_9999",
                    "approved_by": "konan",
                    "approved_at": "2026-06-15T13:00:00Z",
                },
            },
        )
        final = await self._wait_terminal(inst.workflow_id)
        # The block should fire EITHER because prior steps are
        # refused OR because the approval token's workflow_id doesn't
        # match. Both are valid blocks; what MUST happen is the block.
        self.assertEqual(final.status, "aborted")
        breach_entries = [
            h for h in final.step_history
            if h["step_id"] == "notify-enterprise"
            and h.get("status") == "breach_blocked"
        ]
        self.assertEqual(len(breach_entries), 1)

    async def test_publish_allowed_with_valid_approval_token(self):
        """Happy path: every prior step is genuinely completed AND
        the operator has issued a valid approval token. The publish
        goes through and the workflow completes."""
        self.gw.queue_run(cf.MockRun("r1", output="research done"))
        self.gw.queue_run(cf.MockRun("r2", output="architecture spec ready"))
        self.gw.queue_run(cf.MockRun("r3", output="implementation done"))
        self.gw.queue_run(cf.MockRun("r4", output="review LGTM"))
        # project-manager (real completion, not a refusal)
        self.gw.queue_run(cf.MockRun("r5", output="sprint updated"))
        inst = self.engine.start_workflow(
            "deploy-feature",
            context={
                "spec_summary": "real feature",
                "artifacts": [],
                "decisions": [],
            },
        )
        # Issue the operator approval token. Real operator flow would
        # inspect the workflow, draft the message, and write the token
        # into context_bag via a Hermes surface.
        inst_obj = self.engine.get_instance(inst.workflow_id)
        self.assertIsNotNone(inst_obj, "instance should be loaded right after start")
        inst_obj.context_bag["operator_approval_token"] = {
            "workflow_id": inst.workflow_id,
            "approved_by": "konan",
            "approved_at": "2026-06-15T13:00:00Z",
        }
        self.engine._save_instance(inst_obj)
        final = await self._wait_terminal(inst.workflow_id)
        # The publish must have happened and the workflow completed.
        self.assertEqual(final.status, "completed",
                         f"expected completed, got {final.status} "
                         f"history: {[(h['step_id'], h.get('status')) for h in final.step_history]}")
        self.assertIn("nats_publishes", final.context_bag)
        # The approval token must be consumed (single-use).
        token = final.context_bag.get("operator_approval_token", {})
        self.assertTrue(token.get("consumed"),
                        f"approval token must be consumed after use; got: {token}")

    async def test_approval_token_workflow_id_mismatch_blocks(self):
        """An approval token issued for a DIFFERENT workflow must NOT
        authorize a sovereign outbound. Tokens are workflow_id-bound."""
        self.gw.queue_run(cf.MockRun("r1", output="research done"))
        self.gw.queue_run(cf.MockRun("r2", output="architecture spec ready"))
        self.gw.queue_run(cf.MockRun("r3", output="implementation done"))
        self.gw.queue_run(cf.MockRun("r4", output="review LGTM"))
        self.gw.queue_run(cf.MockRun("r5", output="sprint updated"))
        inst = self.engine.start_workflow(
            "deploy-feature",
            context={"spec_summary": "test", "artifacts": [], "decisions": []},
        )
        inst_obj = self.engine.get_instance(inst.workflow_id)
        self.assertIsNotNone(inst_obj)
        # Token with WRONG workflow_id
        inst_obj.context_bag["operator_approval_token"] = {
            "workflow_id": "wf_some_other_workflow_9999",
            "approved_by": "konan",
            "approved_at": "2026-06-15T13:00:00Z",
        }
        self.engine._save_instance(inst_obj)
        final = await self._wait_terminal(inst.workflow_id)
        # Must be blocked because the token doesn't bind to this wf.
        self.assertEqual(final.status, "aborted",
                         f"expected aborted (mismatched token), got {final.status}")
        breach_entries = [
            h for h in final.step_history
            if h["step_id"] == "notify-enterprise"
            and h.get("status") == "breach_blocked"
        ]
        self.assertEqual(len(breach_entries), 1)


# ===========================================================================
# 3. Non-sovereign nats_publish is un-gated (regression for morning-briefing
#    + cron-binding tests)
# ===========================================================================

class TestNonSovereignPublishUnGated(unittest.IsolatedAsyncioTestCase):
    """Pin that the new guard does NOT break existing nats_publish
    steps with non-sovereign subjects (morning-briefing's
    `subspace.konan.inbox`, cron-binding's `subspace.test.inbox`)."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)
        # Copy the real deploy-feature so tests that need it can
        # use start_workflow_sync against it (the refusal-detection
        # test class below calls _record_step_completion directly
        # against the engine's known workflow definitions).
        src = Path("/home/konan/pantheon/conductor/workflows/deploy-feature.yaml")
        if src.exists():
            (self.tmp.workflows_dir / "deploy-feature.yaml").write_text(src.read_text())
        self.engine.workflows.reload()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_morning_briefing_still_publishes_to_inbox(self):
        """The morning-briefing workflow publishes to subspace.konan.inbox.
        That must remain un-gated — it's local routing, not sovereign
        outbound. This is a regression test for the real workflow."""
        # Copy the real morning-briefing workflow
        src = Path("/home/konan/pantheon/conductor/workflows/morning-briefing.yaml")
        if not src.exists():
            self.skipTest("morning-briefing.yaml not present in production workflows dir")
        (self.tmp.workflows_dir / "morning-briefing.yaml").write_text(src.read_text())
        self.engine.workflows.reload()
        # Queue 5 successful god runs (the morning briefing has 5 god steps)
        for i in range(5):
            self.gw.queue_run(cf.MockRun(f"r{i}", output=f"step {i} done"))
        inst = self.engine.start_workflow("morning-briefing",
                                          context={"date": "2026-06-15"})
        for _ in range(100):
            await asyncio.sleep(0.05)
            current = self.engine.get_instance(inst.workflow_id)
            if current.status in ("completed", "failed", "aborted"):
                break
        self.assertEqual(current.status, "completed",
                         f"morning-briefing should still complete; got {current.status} "
                         f"history: {[(h['step_id'], h.get('status')) for h in current.step_history]}")
        # The nats_publish to subspace.konan.inbox must have happened.
        self.assertIn("nats_publishes", current.context_bag)
        # And the subject must be the inbox (non-sovereign).
        self.assertEqual(
            current.context_bag["nats_publishes"][-1]["subject"],
            "subspace.konan.inbox",
        )

    async def test_single_step_test_workflow_with_test_inbox_unaffected(self):
        """The cron-binding test workflow (1-step nats_publish to
        subspace.test.inbox) must still fire — pre-existing test
        regression.

        Notes: the workflow file is written in-test (not in setUp)
        because the setUp's workflow copy is for the refusal-detection
        test class which is defined further down. The engine's
        `WorkflowRegistry` is constructed in setUp pointing at the
        tmp dir, so a `reload()` here picks up the new test-fire
        workflow definition before the engine tries to start it."""
        (self.tmp.workflows_dir / "test-fire.yaml").write_text(json.dumps({
            "workflow": {
                "id": "test-fire",
                "name": "Test Fire",
                "version": "1.0.0",
                "context": {"required": [], "optional": []},
                "steps": [{
                    "id": "deliver",
                    "type": "nats_publish",
                    "subject": "subspace.test.inbox",
                    "message": "test fire",
                }],
            }
        }))
        self.engine.workflows.reload()
        inst = self.engine.start_workflow("test-fire")
        for _ in range(100):
            await asyncio.sleep(0.05)
            current = self.engine.get_instance(inst.workflow_id)
            if current.status in ("completed", "failed", "aborted"):
                break
        self.assertEqual(current.status, "completed")
        self.assertIn("nats_publishes", current.context_bag)
        self.assertEqual(
            current.context_bag["nats_publishes"][-1]["subject"],
            "subspace.test.inbox",
        )


# ===========================================================================
# 4. _record_step_completion refusal detection (the prerequisite for #2)
# ===========================================================================

class TestRecordStepCompletionRefusalDetection(unittest.IsolatedAsyncioTestCase):
    """If `_record_step_completion` fails to detect a refusal, the
    sovereign-outbound guard sees `status=completed` for a prior step
    that actually refused, and the publish is wrongly authorized.
    Pin the refusal-detection behavior here."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)
        # Need the deploy-feature workflow definition in the tmp dir
        # so start_workflow_sync can resolve it.
        src = Path("/home/konan/pantheon/conductor/workflows/deploy-feature.yaml")
        (self.tmp.workflows_dir / "deploy-feature.yaml").write_text(src.read_text())
        self.engine.workflows.reload()

    def tearDown(self):
        self.tmp.cleanup()

    def test_refused_output_is_recorded_as_refused(self):
        """A god run whose output starts with the canonical refusal
        phrase must be recorded with `status=refused`, not `completed`."""
        from conductor.v2 import gateway as gw_mod
        inst = self.engine.start_workflow_sync("deploy-feature",
            context={"spec_summary": "x", "artifacts": [], "decisions": []},
        )
        step = self.engine.workflows.get("deploy-feature").step_by_id("architect")
        result = gw_mod.RunResult(
            run_id="r_test",
            status="completed",  # gateway said "completed"
            output=(
                "Refused `wf_test` architect dispatch — wrong god, "
                "no real architecture work to do, this is a smoke test."
            ),
            error=None,
        )
        self.engine._record_step_completion(inst, step, result)
        architect_entry = next(
            h for h in inst.step_history if h["step_id"] == "architect"
        )
        self.assertEqual(architect_entry["status"], "refused",
                         f"refusal must flip status from completed to refused; "
                         f"got {architect_entry['status']}")
        self.assertIn("refusal_reason", architect_entry)
        # The refusal_reason should be a short phrase, not the full prose.
        self.assertLessEqual(len(architect_entry["refusal_reason"]), 200)

    def test_held_output_is_recorded_as_refused(self):
        """'HELD the dispatch' is the second-most-common refusal phrase
        from the 2026-06-15 misroute session."""
        from conductor.v2 import gateway as gw_mod
        inst = self.engine.start_workflow_sync("deploy-feature",
            context={"spec_summary": "x", "artifacts": [], "decisions": []},
        )
        step = self.engine.workflows.get("deploy-feature").step_by_id("architect")
        result = gw_mod.RunResult(
            run_id="r_test",
            status="completed",
            output=(
                "HELD the dispatch. Three problems compounded: "
                "wrong god, no real work, bad path. Won't roleplay."
            ),
            error=None,
        )
        self.engine._record_step_completion(inst, step, result)
        architect_entry = next(
            h for h in inst.step_history if h["step_id"] == "architect"
        )
        self.assertEqual(architect_entry["status"], "refused")

    def test_genuine_completion_still_recorded_as_completed(self):
        """Regression: a non-refusal run must still be `completed`."""
        from conductor.v2 import gateway as gw_mod
        inst = self.engine.start_workflow_sync("deploy-feature",
            context={"spec_summary": "x", "artifacts": [], "decisions": []},
        )
        step = self.engine.workflows.get("deploy-feature").step_by_id("architect")
        result = gw_mod.RunResult(
            run_id="r_test",
            status="completed",
            output=(
                "Architecture spec for the deploy-feature workflow is "
                "complete. Component breakdown: 3 modules, 2 interfaces, "
                "1 config file. Ready for implementation review."
            ),
            error=None,
        )
        self.engine._record_step_completion(inst, step, result)
        architect_entry = next(
            h for h in inst.step_history if h["step_id"] == "architect"
        )
        self.assertEqual(architect_entry["status"], "completed")
        self.assertNotIn("refusal_reason", architect_entry)

    def test_failed_gateway_run_still_recorded_as_failed(self):
        """A genuinely-failed gateway run (status=failed) must NOT be
        flipped to refused — the failure came from the gateway, not
        from the god's prose. The refusal flip only applies when the
        gateway said 'completed' but the god's output is a refusal."""
        from conductor.v2 import gateway as gw_mod
        inst = self.engine.start_workflow_sync("deploy-feature",
            context={"spec_summary": "x", "artifacts": [], "decisions": []},
        )
        step = self.engine.workflows.get("deploy-feature").step_by_id("architect")
        result = gw_mod.RunResult(
            run_id="r_test",
            status="failed",  # gateway-level failure
            output="",  # no output to scan
            error="HTTP 500 from gateway",
        )
        self.engine._record_step_completion(inst, step, result)
        architect_entry = next(
            h for h in inst.step_history if h["step_id"] == "architect"
        )
        self.assertEqual(architect_entry["status"], "failed")


if __name__ == "__main__":
    unittest.main()
