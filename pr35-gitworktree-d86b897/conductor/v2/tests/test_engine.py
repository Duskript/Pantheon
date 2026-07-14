"""Engine tests — every spec scenario in sections 3.4, 3.5, 8.1, 8.2, 8.4, 8.5.

These tests load the REAL rules/*.yaml and workflows/*.yaml files from
the production layout, copy them into a tmp test dir, and verify the
engine behaves correctly against them. They are not synthetic.

Coverage:
  - Rule loading from real files
  - Workflow loading from real files
  - Rule matching: exact, list, wildcard subject, contains operator
  - Spec 8.1: all 5 handling modes produce correct artifacts
  - Spec 8.2: internal events auto-dispatch unless gated
  - Spec 8.4: workflow version lock on in-flight instances
  - Spec 8.5: handoff routing (Conductor routes, not gods)
  - Spec 3.4: single timeout threshold
  - Layer 3a: abort manifest + .aborted marker files
  - Handoff → workflow step chaining via real workflow files
  - End-to-end: drop handoff in pending/<god>/ → engine matches rule →
    starts workflow → executes steps → produces handoffs

Run: python3 -m v2.tests.test_engine
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402

LOG = logging.getLogger(__name__)


def _new_engine(tmp: cf.TmpConductor, *, gateway: cf.MockGatewayClient):
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


# ===========================================================================
# 1. Real production file loading
# ===========================================================================

class TestRealRulesLoad(unittest.TestCase):
    """All production rules/*.yaml must load cleanly and have valid shape."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = cf.TmpConductor.create()
        cls.tmp.copy_real_rules()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_rule_files_load(self):
        rules = eng.RuleEngine(self.tmp.rules_dir)
        self.assertGreater(len(rules._rules), 0,
                           "no rules loaded from real rules/ — broken?")

    def test_no_rule_file_loads_zero_rules_silently(self):
        """If rules/ is empty, the engine must not pretend to have rules."""
        empty = cf.TmpConductor.create()
        try:
            rules = eng.RuleEngine(empty.rules_dir)
            self.assertEqual(len(rules._rules), 0)
            # An event with no matching rule and no default should return None
            e = eng.Event(type="x", source="y", is_external=True)
            self.assertIsNone(rules.match(e))
        finally:
            empty.cleanup()

    def test_broken_rule_file_is_reported_not_silently_dropped(self):
        """A rule file with invalid YAML must log a load error."""
        bad = cf.TmpConductor.create()
        try:
            (bad.rules_dir / "broken.yaml").write_text("this is: not: valid: yaml: [")
            # Force a capture of the log
            import io
            buf = io.StringIO()
            handler = logging.StreamHandler(buf)
            handler.setLevel(logging.ERROR)
            eng.LOG.addHandler(handler)
            try:
                rules = eng.RuleEngine(bad.rules_dir)
            finally:
                eng.LOG.removeHandler(handler)
            self.assertEqual(len(rules._rules), 0)
            self.assertIn("failed to load rule file", buf.getvalue())
        finally:
            bad.cleanup()

    def test_each_rule_has_required_fields(self):
        rules = eng.RuleEngine(self.tmp.rules_dir)
        for r in rules._rules:
            self.assertTrue(r.id, f"rule missing id in {r.source_path}")
            self.assertIsInstance(r.when, dict, f"rule {r.id} when not a dict")
            self.assertIsInstance(r.then, dict, f"rule {r.id} then not a dict")


class TestRealWorkflowsLoad(unittest.TestCase):
    """All production workflows/*.yaml must load cleanly and have valid shape."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = cf.TmpConductor.create()
        cls.tmp.copy_real_workflows()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_all_workflow_files_load(self):
        wf = eng.WorkflowRegistry(self.tmp.workflows_dir)
        self.assertGreater(len(wf._workflows), 0)

    def test_morning_briefing_has_expected_steps(self):
        wf = eng.WorkflowRegistry(self.tmp.workflows_dir)
        mb = wf.get("morning-briefing")
        self.assertIsNotNone(mb)
        # v1.1.0 — added active-goals + last30days-research steps before dawn-patrol
        self.assertEqual(mb.version, "1.1.0")
        self.assertGreaterEqual(len(mb.steps), 4)
        # First god step is thoth
        first_god_step = next(s for s in mb.steps if s.type == "god")
        self.assertEqual(first_god_step.god, "thoth")
        # Last step is a nats_publish (per spec workflow definition)
        self.assertEqual(mb.steps[-1].type, "nats_publish")

    def test_deploy_feature_has_review_loop(self):
        wf = eng.WorkflowRegistry(self.tmp.workflows_dir)
        df = wf.get("deploy-feature")
        self.assertIsNotNone(df)
        # The review step has a loop: block (spec 3.5 RALPH loop)
        review_step = df.step_by_id("review")
        self.assertIsNotNone(review_step)
        self.assertIsNotNone(review_step.loop, "review step missing loop config")
        self.assertEqual(review_step.loop["max_retries"], 3)
        self.assertEqual(review_step.loop["gate"], "logic_gate")

    def test_cross_pantheon_deploy_requires_context(self):
        wf = eng.WorkflowRegistry(self.tmp.workflows_dir)
        cpd = wf.get("cross-pantheon-deploy")
        self.assertIsNotNone(cpd)
        # Spec 3.2: required context fields
        self.assertIn("feature_summary", cpd.context_required)
        self.assertIn("review_artifacts", cpd.context_required)

    def test_bug_fix_workflow_has_full_pipeline(self):
        wf = eng.WorkflowRegistry(self.tmp.workflows_dir)
        bf = wf.get("bug-fix")
        self.assertIsNotNone(bf)
        self.assertGreaterEqual(len(bf.steps), 4)  # triage → fix → review → deploy
        # Required context from spec section 3.2
        self.assertIn("bug_report", bf.context_required)
        self.assertIn("reproduction_steps", bf.context_required)

    def test_workflow_id_and_version_enforced(self):
        wf = eng.WorkflowRegistry(self.tmp.workflows_dir)
        for w in wf.all():
            self.assertTrue(w.id, f"workflow missing id in {w.source_path}")
            self.assertTrue(w.version, f"workflow {w.id} missing version")
            # Version must be string with dots (per spec 8.4)
            self.assertRegex(w.version, r"^\d+\.\d+\.\d+$",
                             f"workflow {w.id} version not semver: {w.version}")


# ===========================================================================
# 2. Rule matching (spec section 3.5)
# ===========================================================================

class TestRuleMatching(unittest.TestCase):
    """Spec section 3.5: when→then conditions with exact, list, wildcard,
    and contains operators."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()

    def test_exact_match(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"event_type": "handoff.completed", "source": "thoth"},
             "then": {"dispatch_god": "hephaestus"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        e = eng.Event(type="handoff.completed", source="thoth")
        self.assertIsNotNone(rules.match(e))
        # Wrong source
        self.assertIsNone(rules.match(eng.Event(type="handoff.completed", source="marvin")))

    def test_list_any_of_match(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": ["thoth", "marvin"]},
             "then": {"dispatch_god": "hephaestus"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        self.assertIsNotNone(rules.match(eng.Event(type="x", source="thoth")))
        self.assertIsNotNone(rules.match(eng.Event(type="x", source="marvin")))
        self.assertIsNone(rules.match(eng.Event(type="x", source="hermes")))

    def test_wildcard_subject_match(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"subject": "subspace.tallon.incoming.*"},
             "then": {"dispatch_god": "hermes"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        e1 = eng.Event(type="nats.message", source="tallon",
                       subject="subspace.tallon.incoming.hephaestus")
        e2 = eng.Event(type="nats.message", source="tallon",
                       subject="subspace.tallon.incoming.marvin.deploy")
        e3 = eng.Event(type="nats.message", source="tallon",
                       subject="subspace.tallon.deploy.request")
        self.assertIsNotNone(rules.match(e1))
        self.assertIsNotNone(rules.match(e2))  # * matches anything including dots
        self.assertIsNone(rules.match(e3))  # different subject path

    def test_list_of_wildcard_subjects(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"subject": ["a.*", "b.*"]},
             "then": {"dispatch_god": "x"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        self.assertIsNotNone(rules.match(eng.Event(type="x", source="test", subject="a.foo")))
        self.assertIsNotNone(rules.match(eng.Event(type="x", source="test", subject="b.bar")))
        self.assertIsNone(rules.match(eng.Event(type="x", source="test", subject="c.baz")))

    def test_contains_operator_on_list(self):
        """Spec example: 'context.gates_passed contains "logic_gate"'."""
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"context.gates_passed contains \"logic_gate\"": True},
             "then": {"dispatch_god": "hephaestus"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        # Should match: list contains needle
        e1 = eng.Event(type="x", source="marvin", payload={"context": {"gates_passed": ["logic_gate", "state_gate"]}})
        self.assertIsNotNone(rules.match(e1))
        # Should NOT match: list missing needle
        e2 = eng.Event(type="x", source="marvin", payload={"context": {"gates_passed": ["state_gate"]}})
        self.assertIsNone(rules.match(e2))
        # Should NOT match: no context
        e3 = eng.Event(type="x", source="marvin", payload={})
        self.assertIsNone(rules.match(e3))

    def test_contains_operator_on_string(self):
        """Spec 3.5: contains also works on string (substring match)."""
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"subject": "contains tallon"},
             "then": {"dispatch_god": "hermes"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        self.assertIsNotNone(rules.match(eng.Event(type="x", source="test", subject="hello tallon deploy")))
        self.assertIsNone(rules.match(eng.Event(type="x", source="test", subject="marvin deploy")))

    def test_nested_context_dict_form(self):
        """When the rule uses nested context: form, evaluate correctly."""
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"context": {"gates_passed_contains": "logic_gate"}},
             "then": {"dispatch_god": "hephaestus"}}
        ]}))
        rules = eng.RuleEngine(self.tmp.rules_dir)
        e = eng.Event(type="x", source="marvin", payload={"context": {"gates_passed_contains": "logic_gate"}})
        self.assertIsNotNone(rules.match(e))


# ===========================================================================
# 3. Spec 8.1 — All 5 handling modes
# ===========================================================================

class TestHandlingModes(unittest.IsolatedAsyncioTestCase):
    """Spec section 8.1. Each of 5 modes produces a distinct, testable
    artifact (or no artifact for log_only)."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_log_only_writes_to_journal(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "reddit"}, "then": {"handling_mode": "log_only"}}
        ]}))
        self.engine.rules.reload()
        e = eng.Event(type="webhook", source="reddit", subject="post",
                      payload={"summary": "test"}, is_external=True)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "logged")
        self.assertEqual(result["mode"], "log_only")
        # File in _journal/
        self.assertTrue(self.tmp.journal_dir.exists())
        files = list(self.tmp.journal_dir.glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text())
        self.assertEqual(data["source"], "reddit")
        # Should NOT have written to inbox
        self.assertFalse(self.tmp.inbox_dir.exists() and any(self.tmp.inbox_dir.iterdir()))

    async def test_notify_writes_to_journal_and_inbox(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "youtube"}, "then": {"handling_mode": "notify"}}
        ]}))
        self.engine.rules.reload()
        e = eng.Event(type="webhook", source="youtube", subject="video",
                      payload={"summary": "new video"}, is_external=True)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "notified")
        self.assertEqual(result["mode"], "notify")
        # Both files written
        self.assertEqual(len(list(self.tmp.journal_dir.glob("*.json"))), 1)
        self.assertEqual(len(list(self.tmp.inbox_dir.glob("*.json"))), 1)
        notif = json.loads(list(self.tmp.inbox_dir.glob("*.json"))[0].read_text())
        self.assertEqual(notif["from"], "youtube")
        self.assertEqual(notif["action"], "fyi")

    async def test_notify_and_log_marks_no_action_needed(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "monitoring"}, "then": {"handling_mode": "notify_and_log"}}
        ]}))
        self.engine.rules.reload()
        e = eng.Event(type="webhook", source="monitoring", subject="health",
                      payload={"summary": "all green"}, is_external=True)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "notified_and_logged")
        notif = json.loads(list(self.tmp.inbox_dir.glob("*.json"))[0].read_text())
        self.assertEqual(notif["action"], "no_action_needed")

    async def test_approval_required_quarantines_and_does_not_execute(self):
        """Spec 8.1: default for unmatched external. CRITICAL — must never
        auto-execute an external event without explicit approval."""
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "tallon"}, "then": {"handling_mode": "approval_required"}}
        ]}))
        self.engine.rules.reload()
        e = eng.Event(type="nats.message", source="tallon",
                      subject="subspace.tallon.deploy.request",
                      payload={"summary": "deploy feature X"}, is_external=True)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["mode"], "approval_required")
        # File quarantined
        qfiles = list(self.tmp.quarantine_dir.glob("*.json"))
        self.assertEqual(len(qfiles), 1)
        # CRITICAL: no god was dispatched
        self.assertEqual(len(self.gw.calls), 0)

    async def test_route_on_approval_quarantines_with_plan(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "tallon", "subject": "subspace.tallon.deploy.request"},
             "then": {
                 "handling_mode": "route_on_approval",
                 "on_approval": {"dispatch_workflow": "cross-pantheon-deploy"},
             }}
        ]}))
        self.engine.rules.reload()
        # Need the workflow to be registered for on_approval to be usable
        (self.tmp.workflows_dir / "cross-pantheon-deploy.yaml").write_text(json.dumps({
            "workflow": {"id": "cross-pantheon-deploy", "name": "test", "version": "1.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "package", "god": "marvin", "skill": "x", "output": "pkg", "timeout": "5m"}]}
        }))
        self.engine.workflows.reload()
        e = eng.Event(type="nats.message", source="tallon",
                      subject="subspace.tallon.deploy.request",
                      payload={"summary": "deploy"}, is_external=True)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "awaiting_approval")
        self.assertEqual(result["mode"], "route_on_approval")
        self.assertEqual(result["on_approval"]["dispatch_workflow"], "cross-pantheon-deploy")
        # Quarantine file has the plan attached
        qfile = json.loads(list(self.tmp.quarantine_dir.glob("*.json"))[0].read_text())
        self.assertEqual(qfile["on_approval"]["dispatch_workflow"], "cross-pantheon-deploy")
        # Not yet executed
        self.assertEqual(len(self.gw.calls), 0)


class TestDefaultHandlingMode(unittest.IsolatedAsyncioTestCase):
    """Spec 8.1: unmatched external events default to approval_required."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_unmatched_external_defaults_to_approval_required(self):
        # No rules loaded
        e = eng.Event(type="nats.message", source="unknown_pantheon",
                      subject="x.y.z", is_external=True, payload={"x": 1})
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["rule"], "__default_external__")
        # Must not have executed
        self.assertEqual(len(self.gw.calls), 0)

    async def test_unmatched_internal_drops_silently(self):
        """Internal events with no matching rule are dropped, not quarantined."""
        e = eng.Event(type="internal.thing", source="hermes", is_external=False, payload={})
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "no_rule")
        self.assertEqual(result["action"], "dropped")


# ===========================================================================
# 4. Spec 8.2 — Internal events may auto-dispatch
# ===========================================================================

class TestInternalDispatch(unittest.IsolatedAsyncioTestCase):
    """Spec 8.2: internal events (handoffs, cron, internal NATS) auto-execute."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_dispatch_workflow_rule_starts_workflow(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "thoth", "target": "hephaestus"},
             "then": {"dispatch_workflow": "morning-briefing", "start_at_step": "summarize"}}
        ]}))
        self.engine.rules.reload()
        # Use the REAL morning-briefing workflow
        src = cf.REAL_WORKFLOWS_DIR / "morning-briefing.yaml"
        if not src.exists():
            self.skipTest("morning-briefing.yaml not present")
        shutil.copy(src, self.tmp.workflows_dir / "morning-briefing.yaml")
        self.engine.workflows.reload()
        # Queue runs for the 2 god steps we will reach (summarize, digest-format).
        # deliver is nats_publish, no run needed.
        self.gw.queue_run(cf.MockRun("r1", output="briefing summary"))
        self.gw.queue_run(cf.MockRun("r2", output="formatted digest"))

        e = eng.Event(type="handoff.completed", source="thoth", target="hephaestus",
                      subject="thoth done", payload={"summary": "intel"}, is_external=False)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "workflow_started")
        self.assertIn("workflow_id", result)
        # Wait for the workflow to complete (or abort)
        inst_id = result["workflow_id"]
        for _ in range(60):
            await asyncio.sleep(0.05)
            current = self.engine.get_instance(inst_id)
            if current and current.status in ("completed", "aborted", "failed"):
                break
        # The instance started at summarize and completed normally
        self.assertIsNotNone(current)
        self.assertEqual(current.status, "completed",
                          f"unexpected status: {current.status}, history: {current.step_history}")
        # The first god run was submitted (summarize step)
        self.assertGreaterEqual(len(self.gw.calls), 1)
        # State file exists
        state_files = [f for f in self.tmp.state_dir.glob("wf_*.json")
                       if not f.name.endswith(".aborted.json")]
        self.assertEqual(len(state_files), 1)
        inst_data = json.loads(state_files[0].read_text())
        # completed workflows have current_step=None; what matters is the
        # step history shows summarize as the first step that ran
        step_ids = [h["step_id"] for h in inst_data["step_history"]]
        self.assertIn("summarize", step_ids)

    async def test_dispatch_god_submits_run(self):
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "marvin"},
             "then": {"dispatch_god": "hephaestus", "skill": "code-review"}}
        ]}))
        self.engine.rules.reload()
        self.gw.queue_run(cf.MockRun("run_1", output="review done"))
        e = eng.Event(type="handoff.completed", source="marvin", target="conductor",
                      subject="marvin done", payload={"summary": "code done"}, is_external=False)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "god_dispatched")
        self.assertEqual(result["god"], "hephaestus")
        # Mock was called
        self.assertEqual(len(self.gw.calls), 1)
        self.assertEqual(self.gw.calls[0]["model"], "hephaestus")


# ===========================================================================
# 5. Spec 8.4 — Version lock on in-flight workflow instances
# ===========================================================================

class TestVersionLock(unittest.IsolatedAsyncioTestCase):
    """Spec 8.4: in-flight instances complete on their original version,
    even if the workflow YAML changes mid-execution."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_workflow_instance_locks_version_on_start(self):
        (self.tmp.workflows_dir / "test-wf.yaml").write_text(json.dumps({
            "workflow": {"id": "test-wf", "name": "test", "version": "1.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "a", "god": "thoth", "output": "r1", "timeout": "5m"}]}
        }))
        self.engine.workflows.reload()
        inst = self.engine.start_workflow("test-wf")
        # Mutate the workflow on disk to a new version
        (self.tmp.workflows_dir / "test-wf.yaml").write_text(json.dumps({
            "workflow": {"id": "test-wf", "name": "test", "version": "2.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "a", "god": "hephaestus", "output": "r1", "timeout": "5m"},
                                   {"id": "b", "god": "marvin", "output": "r2", "timeout": "5m"}]}
        }))
        self.engine.workflows.reload()
        # The in-flight instance should still have v1.0.0
        inst_after = self.engine.get_instance(inst.workflow_id)
        self.assertEqual(inst_after.definition_version, "1.0.0")
        # And still be using the v1.0.0 workflow (1 step, thoth)
        wf = self.engine.workflows.get("test-wf")  # now loads v2.0.0
        self.assertEqual(wf.version, "2.0.0")
        self.assertEqual(len(wf.steps), 2)
        # The instance's original workflow version is preserved in state
        state_data = json.loads((self.tmp.state_dir / f"{inst.workflow_id}.json").read_text())
        self.assertEqual(state_data["definition_version"], "1.0.0")


# ===========================================================================
# 6. Layer 3a — Abort handling
# ===========================================================================

class TestAbortHandling(unittest.IsolatedAsyncioTestCase):
    """Layer 3a: on failure, write abort manifest + .aborted marker files."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_gateway_failure_marks_workflow_aborted(self):
        (self.tmp.workflows_dir / "wf.yaml").write_text(json.dumps({
            "workflow": {"id": "wf", "name": "wf", "version": "1.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "a", "god": "thoth", "output": "r1", "timeout": "5m"}]}
        }))
        self.engine.workflows.reload()
        self.gw.fail_submit = RuntimeError("gateway down")
        inst = self.engine.start_workflow("wf")
        # Wait for abort
        for _ in range(20):
            await asyncio.sleep(0.05)
            inst = self.engine.get_instance(inst.workflow_id)
            if inst.status in ("aborted", "completed"):
                break
        self.assertEqual(inst.status, "aborted")
        # Abort manifest exists
        manifest_path = self.tmp.state_dir / f"{inst.workflow_id}.aborted.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["status"], "aborted")
        self.assertIn("failed_step", manifest)
        self.assertTrue(manifest["requires_manual_review"])
        # State file reflects abort
        state_data = json.loads((self.tmp.state_dir / f"{inst.workflow_id}.json").read_text())
        self.assertEqual(state_data["status"], "aborted")

    async def test_abort_marks_existing_handoff_artifacts(self):
        """Layer 3a: existing handoff files get .aborted marker beside them."""
        # Pre-create a completed step's handoff file
        god_dir = self.tmp.pending_dir / "thoth"
        god_dir.mkdir(parents=True, exist_ok=True)
        handoff_path = god_dir / "wf_test_step1.json"
        handoff_path.write_text('{"ok": true}')
        inst = eng.WorkflowInstance(
            workflow_id="wf_test", definition_id="t1", definition_version="1.0.0",
            current_step="step1",
            step_history=[{"step_id": "step1", "god": "thoth", "status": "completed",
                           "started": eng.utc_now()}],
        )
        self.engine._save_instance(inst)
        # Trigger abort
        self.engine._abort_workflow(inst, "test failure reason")
        # Manifest written
        manifest = json.loads((self.tmp.state_dir / "wf_test.aborted.json").read_text())
        self.assertEqual(manifest["failed_step"], "step1")
        # Marker file beside the handoff artifact
        marker = handoff_path.with_suffix(handoff_path.suffix + ".aborted")
        self.assertTrue(marker.exists())
        # The original handoff is still there (spec: manifest + breadcrumbs)
        self.assertTrue(handoff_path.exists())


# ===========================================================================
# 7. Spec 3.4 — Single timeout threshold
# ===========================================================================

class TestSingleTimeoutThreshold(unittest.IsolatedAsyncioTestCase):
    """Spec 3.4: 'Single threshold, no ladder'. The step timeout is the
    ONLY timeout; no 3-tier retry ladder."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_duration_supported_units(self):
        self.assertEqual(eng._parse_duration("30s"), 30.0)
        self.assertEqual(eng._parse_duration("5m"), 300.0)
        self.assertEqual(eng._parse_duration("2h"), 7200.0)
        self.assertEqual(eng._parse_duration("1d"), 86400.0)
        # Default unit is seconds
        self.assertEqual(eng._parse_duration("45"), 45.0)
        # Bogus input falls back to 30m default (no crash)
        self.assertEqual(eng._parse_duration("????"), 1800.0)
        # Numeric passthrough
        self.assertEqual(eng._parse_duration(60), 60.0)

    async def test_run_timeout_aborts_workflow(self):
        """If god run times out past step timeout, the step is recorded
        as failed and the workflow aborts (per spec 3.4)."""
        (self.tmp.workflows_dir / "wf.yaml").write_text(json.dumps({
            "workflow": {"id": "wf", "name": "wf", "version": "1.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "a", "god": "thoth", "output": "r1", "timeout": "1s"}]}
        }))
        self.engine.workflows.reload()
        # Queue a run that "takes too long" — make wait_for_run raise TimeoutError
        # by having the engine submit but the run never returning.
        # Simplest: make the mock fail with TimeoutError.
        import asyncio as _asyncio
        original = self.gw.wait_for_run
        async def slow_wait(*a, **kw):
            raise _asyncio.TimeoutError("simulated")
        self.gw.wait_for_run = slow_wait
        inst = self.engine.start_workflow("wf")
        for _ in range(40):
            await asyncio.sleep(0.05)
            inst = self.engine.get_instance(inst.workflow_id)
            if inst.status in ("aborted", "failed", "completed"):
                break
        # Either aborted (if the engine's _execute_step caught the error)
        # or failed. Both are spec-compliant outcomes.
        self.assertIn(inst.status, ("aborted", "failed"),
                      f"expected aborted/failed, got {inst.status}")
        # No .aborted manifest is required for timeout-fail (only for "abort on fail")
        # but state should reflect the failure
        state = json.loads((self.tmp.state_dir / f"{inst.workflow_id}.json").read_text())
        self.assertIn(state["status"], ("aborted", "failed"))


# ===========================================================================
# 8. Spec 8.5 — Conductor routes, gods don't
# ===========================================================================

class TestHandoffRouting(unittest.IsolatedAsyncioTestCase):
    """A handoff in pending/<god>/ should be picked up by the file watcher
    and routed to the next step via the rules engine, NOT by the god."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_handoff_in_pending_folder_becomes_event(self):
        # A marvin handoff with logic_gate passed → should match
        # the marvin-complete-notify-review rule from research-to-build.yaml
        # Use a real rule shape that the matcher understands: `source: marvin`
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "marvin-complete", "when": {"source": "marvin"},
             "then": {"dispatch_god": "hephaestus"}}
        ]}))
        # Reload rules — engine was constructed with an empty rules dir,
        # so it has no rules in memory until we re-read the file.
        self.engine.rules.reload()
        # Queue a fake run that resolves when hephaestus is dispatched
        self.gw.queue_run(cf.MockRun("run_x", output="review complete"))
        handoff = cf.make_handoff(
            from_god="marvin", to_god="conductor",
            gates_passed=["logic_gate", "state_gate"],
        )
        cf.write_handoff_to_pending(self.tmp, handoff, god="marvin")
        # Use the file processor directly (don't need the watcher)
        await self.engine._process_file(
            self.tmp.pending_dir / "marvin" / f"{handoff['handoff_id']}.json"
        )
        # The dispatch happened — the gateway recorded the hephaestus call
        self.assertGreaterEqual(len(self.gw.calls), 1,
            f"expected gateway to record ≥1 call, got {len(self.gw.calls)}")
        # The last call was for hephaestus (per the rule's then.dispatch_god)
        self.assertEqual(self.gw.calls[-1]["model"], "hephaestus")


# ===========================================================================
# 9. End-to-end with real workflow files
# ===========================================================================

class TestRealWorkflowExecution(unittest.IsolatedAsyncioTestCase):
    """Drop a real handoff in pending/<god>/ → engine routes → workflow
    executes → handoffs produced for next god."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.tmp.copy_real_rules()
        self.tmp.copy_real_workflows()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_morning_briefing_runs_through_all_steps(self):
        """The real morning-briefing workflow (v1.1.0+) has 5 god steps + 1 nats_publish:
        active-goals, last30days-research, dawn-patrol, summarize, digest-format.
        We queue 5 mock runs (one per god step) and verify the engine walks
        all 6 steps including the nats_publish terminal step."""
        self.gw.queue_run(cf.MockRun("r1", output="goals_preamble: 5 active"))
        self.gw.queue_run(cf.MockRun("r2", output="l30: 12 X signals on multi-agent AI"))
        self.gw.queue_run(cf.MockRun("r3", output="daily intel: 5 hot signals"))
        self.gw.queue_run(cf.MockRun("r4", output="summary: all systems green"))
        self.gw.queue_run(cf.MockRun("r5", output="formatted digest text"))
        inst = self.engine.start_workflow("morning-briefing",
                                          context={"date": "2026-06-14"})
        # Wait for the workflow to complete
        for _ in range(100):
            await asyncio.sleep(0.05)
            current = self.engine.get_instance(inst.workflow_id)
            if current.status in ("completed", "failed", "aborted"):
                break
        self.assertEqual(current.status, "completed", f"history: {current.step_history}")
        # All 5 god runs were submitted (6th step is nats_publish)
        self.assertEqual(len(self.gw.calls), 5,
                          f"expected 5 god calls, got {len(self.gw.calls)}: {self.gw.calls}")
        # Step history has 6 entries (5 god + 1 nats_publish)
        self.assertEqual(len(current.step_history), 6)
        # Context bag has the step outputs
        self.assertIn("goals_preamble", current.context_bag)
        self.assertIn("l30_signals", current.context_bag)
        self.assertIn("daily_intel", current.context_bag)
        self.assertIn("briefing_summary", current.context_bag)
        # Final nats_publish step recorded in context
        self.assertIn("nats_publishes", current.context_bag)

    async def test_deploy_feature_runs_research_through_review(self):
        """deploy-feature is 7 steps. Run the first 3 (research→architect→implement)
        with a failing run to trigger abort handling."""
        self.gw.queue_run(cf.MockRun("r1", output="research done"))
        self.gw.queue_run(cf.MockRun("r2", output="arch spec done"))
        self.gw.queue_run(cf.MockRun("r3", output="", status="failed", error="test failure"))
        inst = self.engine.start_workflow("deploy-feature",
                                          context={"spec_summary": "x", "artifacts": [], "decisions": []},
                                          start_at_step="research")
        for _ in range(100):
            await asyncio.sleep(0.05)
            current = self.engine.get_instance(inst.workflow_id)
            if current.status in ("completed", "failed", "aborted"):
                break
        # With abort_on_fail=True (default), the workflow aborts on first failure
        self.assertIn(current.status, ("aborted", "failed"),
                       f"expected abort on failure, got {current.status}")
        # Abort manifest exists
        abort_files = list(self.tmp.state_dir.glob("*.aborted.json"))
        self.assertEqual(len(abort_files), 1)


# ===========================================================================
# 10. Approval workflow
# ===========================================================================

class TestApproveQuarantined(unittest.IsolatedAsyncioTestCase):
    """Konan can approve a quarantined event to dispatch its on_approval plan."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine(self.tmp, gateway=self.gw)

    def tearDown(self):
        self.tmp.cleanup()

    async def test_approve_dispatches_workflow(self):
        # Setup: rule with route_on_approval + workflow registered
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "tallon"}, "then": {
                "handling_mode": "route_on_approval",
                "on_approval": {"dispatch_workflow": "deploy-feature"},
            }}
        ]}))
        (self.tmp.workflows_dir / "deploy-feature.yaml").write_text(json.dumps({
            "workflow": {"id": "deploy-feature", "name": "df", "version": "1.0.0",
                         "context": {"required": ["spec_summary", "artifacts", "decisions"], "optional": []},
                         "steps": [{"id": "research", "god": "thoth", "input": "x", "output": "rf", "timeout": "5m"}]}
        }))
        self.engine.rules.reload()
        self.engine.workflows.reload()
        # Trigger quarantine
        e = eng.Event(type="nats.message", source="tallon", subject="deploy",
                      payload={"summary": "deploy x"}, is_external=True)
        result = await self.engine.handle_event(e)
        self.assertEqual(result["status"], "awaiting_approval")
        qfile = result["quarantine_file"]
        qname = Path(qfile).name
        # Approve
        self.gw.queue_run(cf.MockRun("r1", output="research done"))
        approval_result = await self.engine.approve_quarantined_async(qname, approver="konan")
        self.assertEqual(approval_result["status"], "approved")
        # A workflow was started
        self.assertIn("workflow_id", approval_result["dispatch_result"])
        # Wait for it
        await asyncio.sleep(0.2)
        # The quarantine file is now marked approved
        qdata = json.loads((self.tmp.quarantine_dir / qname).read_text())
        self.assertTrue(qdata.get("approved"))
        self.assertEqual(qdata.get("approver"), "konan")

    async def test_dismiss_removes_quarantine(self):
        # Quarantine an event
        (self.tmp.rules_dir / "test.yaml").write_text(json.dumps({"rules": [
            {"id": "r1", "when": {"source": "tallon"}, "then": {"handling_mode": "approval_required"}}
        ]}))
        self.engine.rules.reload()
        e = eng.Event(type="nats.message", source="tallon", subject="x",
                      payload={"summary": "x"}, is_external=True)
        result = await self.engine.handle_event(e)
        qname = Path(result["quarantine_file"]).name
        # Dismiss
        d_result = await self.engine.approve_quarantined_async(qname, action="dismiss")
        self.assertEqual(d_result["status"], "dismissed")
        self.assertFalse((self.tmp.quarantine_dir / qname).exists())


# ===========================================================================
# 11. State persistence
# ===========================================================================

class TestStatePersistence(unittest.IsolatedAsyncioTestCase):
    """Workflow state must persist to disk and reload on engine restart."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_instance_state_file_is_written(self):
        gw = cf.MockGatewayClient()
        engine = _new_engine(self.tmp, gateway=gw)
        (self.tmp.workflows_dir / "wf.yaml").write_text(json.dumps({
            "workflow": {"id": "wf", "name": "wf", "version": "1.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "a", "god": "thoth", "output": "r1", "timeout": "5m"}]}
        }))
        engine.workflows.reload()
        gw.queue_run(cf.MockRun("r1", output="done"))
        inst = engine.start_workflow("wf")
        # State file exists immediately
        state_path = self.tmp.state_dir / f"{inst.workflow_id}.json"
        self.assertTrue(state_path.exists())
        # Wait for completion
        for _ in range(40):
            await asyncio.sleep(0.05)
            current = engine.get_instance(inst.workflow_id)
            if current.status == "completed":
                break
        # State file has the final status
        state = json.loads(state_path.read_text())
        self.assertEqual(state["status"], "completed")
        # Step history is recorded
        self.assertEqual(len(state["step_history"]), 1)
        self.assertEqual(state["step_history"][0]["status"], "completed")

    async def test_new_engine_loads_existing_in_flight_instances(self):
        # First engine starts a workflow
        gw1 = cf.MockGatewayClient()
        engine1 = _new_engine(self.tmp, gateway=gw1)
        (self.tmp.workflows_dir / "wf.yaml").write_text(json.dumps({
            "workflow": {"id": "wf", "name": "wf", "version": "1.0.0",
                         "context": {"required": [], "optional": []},
                         "steps": [{"id": "a", "god": "thoth", "output": "r1", "timeout": "5m"}]}
        }))
        engine1.workflows.reload()
        # Block the run so it stays in_progress
        import asyncio as _asyncio
        async def block_wait(*a, **kw):
            await _asyncio.sleep(60)
        gw1.wait_for_run = block_wait
        inst = engine1.start_workflow("wf")
        # Give it a moment to write state
        await asyncio.sleep(0.1)
        # Spin up a fresh engine pointing at the same state dir
        gw2 = cf.MockGatewayClient()
        engine2 = _new_engine(self.tmp, gateway=gw2)
        # New engine should see the in-flight instance
        self.assertIn(inst.workflow_id, engine2._instances)
        loaded = engine2.get_instance(inst.workflow_id)
        self.assertIsNotNone(loaded)
        self.assertIn(loaded.status, ("in_progress", "waiting_for_ack"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    unittest.main(verbosity=2)
