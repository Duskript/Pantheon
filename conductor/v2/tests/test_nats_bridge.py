"""Phase 3 REWORK #1 — Lock-in tests for the NATS rule bridge.

Why this file exists:
    BUILD-PLAN §Phase 3 says "Currently they all get quarantined because
    no rule matches the NATS subjects" (referring to messages from
    Tallon's Pantheon on `subspace.tallon.outgoing.>`). Step 3.1 of
    Phase 3 REWORK #1 (2026-06-15) asked us to investigate that claim
    and fix the root cause if there was one. The investigation
    confirmed the claim is **incorrect** for the current state of the
    codebase: all 4 production NATS-rule subjects (plus the bonus
    `tallon-incoming-message` rule in `research-to-build.yaml`) match
    the engine's matcher cleanly, and `handle_event` dispatches the
    intended workflow without writing a quarantine file. This file
    locks in that working behavior so a future refactor of the matcher
    or rule loader surfaces the regression immediately.

What this file covers:
    1. Rule-by-rule assertion: each of the 4 brief-listed rules +
       the bonus `tallon-incoming-message` rule fires on its target
       subject with the right outcome (workflow start / notify /
       approval_required / dispatch_god).
    2. The exact brief §Step 3.2 scenario: a NATS message on
       `subspace.enterprise.deploy.request` triggers the
       `cross-pantheon-deploy` workflow with `initiator=tallon`,
       `original_request` includes the rule context, and ZERO files
       are written to `pending/_quarantine/`.
    3. End-to-end NATS listener simulation: the listener's
       `_handle_msg` produces an Event that the engine handles.
       Hermetic — no live NATS broker.
    4. Matcher semantics: a NATS subject with multiple trailing
       tokens (`subspace.tallon.incoming.x.y.z`) still matches a
       `*` glob (documented fnmatch behavior — `*` crosses dots
       greedily). The brief's "no NATS `>` support" caveat lives in
       the engine.py matcher docstring; this test does NOT exercise
       `>` (no production rule uses it).
    5. Negative path: an unmatched external subject falls through
       to the default quarantine rule (proves the quarantine
       mechanism is reachable for genuinely-unmatched events —
       this is the BUILD-PLAN "they all get quarantined" case for
       a no-matching-rule subject, distinct from the case the
       brief flagged).

What this file does NOT cover:
    - Live NATS broker connectivity. See `test_nats.py` for that.
    - The cron path (`schedule.cron` events). See
      `test_cron_scheduler.py` and `test_schedule_cron_binding.py`.
    - Webhook delivery. See `test_webhook.py`.

Dependencies: this test uses real production rule files in
`/home/konan/pantheon/conductor/rules/` and the real
`cross-pantheon-deploy.yaml` workflow definition. The conftest
restores `CONDUCTOR_BASE_DIR` after the v2 session so v1 contract
tests (36/36) still pass.

Test count target: 8 cases (6 rule assertions + 1 end-to-end + 1
fallthrough negative).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# Make v2 + tests/ importable. Match the conftest pattern (canonical
# import via `conductor.v2`) and bring the fixtures module in.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402
from v2 import nats as nats_mod  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def _new_engine(tmp: cf.TmpConductor, *, gateway: cf.MockGatewayClient) -> eng.ConductorEngine:
    """Build a ConductorEngine bound to a tmp layout with real rules + workflows.

    Identical helper to the one in test_engine.py — duplicated here rather
    than imported to keep the test file hermetic (a test_nats_bridge failure
    must not be diagnosable as "the test_engine helper moved").
    """
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


def _make_engine_with_real_rules():
    """Build (tmp, gw, engine) with the production rules and workflows
    copied into the tmp layout. Caller is responsible for `tmp.cleanup()`.
    """
    tmp = cf.TmpConductor.create()
    tmp.copy_real_rules()
    tmp.copy_real_workflows()
    gw = cf.MockGatewayClient()
    engine = _new_engine(tmp, gateway=gw)
    return tmp, gw, engine


def _make_fake_nats_msg(subject: str, payload: dict[str, Any] | None) -> Any:
    """Build a fake nats.aio.client.Msg for hermetic listener tests.

    Mirrors the helper in test_nats.py:78-82 but lives here so the two
    test files don't share a helper (would couple them on import).
    """
    m = MagicMock()
    m.subject = subject
    m.data = json.dumps(payload or {}).encode("utf-8")
    return m


# ===========================================================================
# 1. Rule-by-rule assertions — the 4 brief-listed rules + 1 bonus
# ===========================================================================

class TestNatsRuleMatch(unittest.IsolatedAsyncioTestCase):
    """Each of the 5 production NATS-message rules fires on its target subject
    and produces the expected outcome (workflow start, notify, approval_required,
    or dispatch_god). Uses real rule YAML files (no rule-shape mocks).
    """

    def setUp(self):
        self.tmp, self.gw, self.engine = _make_engine_with_real_rules()

    def tearDown(self):
        self.tmp.cleanup()

    # --- Rule 1: enterprise-deploy-request — the brief's headline scenario.

    async def test_enterprise_deploy_request_dispatches_cross_pantheon_deploy(self):
        """Phase 3 brief §Step 3.2 — exact assertions:
            - Event(type="nats.message", source="tallon", subject=...) lands
            - engine.handle_event returns workflow_started
            - instance has definition_id="cross-pantheon-deploy", initiator="tallon"
            - original_request includes the rule context (subject/payload)
            - ZERO files written to pending/_quarantine/
        """
        ev = eng.Event(
            type="nats.message",
            source="tallon",
            target=None,
            subject="subspace.enterprise.deploy.request",
            payload={"feature_summary": "Phase 3 REWORK smoke", "review_artifacts": []},
            is_external=True,
        )

        # Sanity: rule is loaded and matches
        rule = self.engine.rules.match(ev)
        self.assertIsNotNone(rule, "no rule matched enterprise-deploy-request subject")
        self.assertEqual(rule.id, "enterprise-deploy-request")
        self.assertIn("dispatch_workflow", rule.then)
        self.assertEqual(rule.then["dispatch_workflow"], "cross-pantheon-deploy")

        result = await self.engine.handle_event(ev)

        # Brief assertion 1: workflow started
        self.assertEqual(result["status"], "workflow_started")
        self.assertEqual(result["rule"], "enterprise-deploy-request")
        self.assertIn("workflow_id", result)

        # Brief assertion 2: instance shape
        inst = self.engine.get_instance(result["workflow_id"])
        self.assertIsNotNone(inst, "workflow instance not found after dispatch")
        self.assertEqual(inst.definition_id, "cross-pantheon-deploy")
        self.assertEqual(inst.initiator, "tallon")
        # original_request is set from payload.summary or subject — we send
        # no summary key, so it falls back to the subject string. Either way
        # it must reference the rule context (subject or payload).
        self.assertTrue(
            "subspace.enterprise.deploy.request" in inst.original_request
            or "Phase 3 REWORK smoke" in inst.original_request,
            f"original_request missing rule context: {inst.original_request!r}",
        )

        # Brief assertion 3: NO quarantine file was written
        qfiles = list(self.tmp.quarantine_dir.glob("*.json"))
        self.assertEqual(
            qfiles, [],
            f"rule matched but quarantine file was written: {[f.name for f in qfiles]}",
        )

    # --- Rule 2: tallon-workflow-complete — notify path, no dispatch.

    async def test_tallon_workflow_complete_notifies_no_quarantine(self):
        ev = eng.Event(
            type="nats.message",
            source="tallon",
            subject="subspace.tallon.workflow.complete",
            payload={"summary": "Tallon workflow done"},
            is_external=True,
        )
        rule = self.engine.rules.match(ev)
        self.assertEqual(rule.id, "tallon-workflow-complete")
        self.assertEqual(rule.then["handling_mode"], "notify")

        result = await self.engine.handle_event(ev)
        self.assertEqual(result["status"], "notified")
        self.assertEqual(result["mode"], "notify")
        self.assertEqual(result["rule"], "tallon-workflow-complete")
        # No workflow started (notify is fire-and-forget)
        self.assertNotIn("workflow_id", result)
        # No quarantine
        self.assertEqual(list(self.tmp.quarantine_dir.glob("*.json")), [])
        # No god run submitted (notify doesn't dispatch)
        self.assertEqual(self.gw.calls, [])

    # --- Rule 3: tallon-workflow-failed — INTENDED quarantine path.

    async def test_tallon_workflow_failed_quarantines_with_approval_plan(self):
        """This rule INTENTIONALLY quarantines (handling_mode=approval_required
        with on_approval plan). Verifying it works as designed — this is the
        legitimate use of the quarantine mechanism, not the BUILD-PLAN's
        "no rule matches" false-positive case.
        """
        ev = eng.Event(
            type="nats.message",
            source="tallon",
            subject="subspace.tallon.workflow.failed",
            payload={"error": "test failure", "workflow_id": "wf_tallon_x"},
            is_external=True,
        )
        rule = self.engine.rules.match(ev)
        self.assertEqual(rule.id, "tallon-workflow-failed")
        self.assertEqual(rule.then["handling_mode"], "approval_required")
        self.assertIn("on_approval", rule.then)

        result = await self.engine.handle_event(ev)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["mode"], "approval_required")
        self.assertEqual(result["rule"], "tallon-workflow-failed")
        self.assertIn("quarantine_file", result)

        # Quarantine file was written
        qfiles = list(self.tmp.quarantine_dir.glob("*.json"))
        self.assertEqual(len(qfiles), 1)
        qdata = json.loads(qfiles[0].read_text())
        self.assertEqual(qdata["rule_id"], "tallon-workflow-failed")
        self.assertEqual(qdata["event"]["source"], "tallon")
        self.assertEqual(qdata["event"]["subject"], "subspace.tallon.workflow.failed")
        self.assertEqual(qdata["event"]["type"], "nats.message")
        # NOTE 2026-06-15 (Phase 3 REWORK #1): the engine's
        # _handle_approval_required path writes {event, rule_id, queued_at}
        # to the quarantine file but does NOT persist the on_approval plan
        # on disk under approval_required mode (only _handle_route_on_approval
        # does). The in-memory rule retains the plan for the dispatch lifetime.
        # The on-disk file is the durable "needs approval" record; the plan
        # is re-loaded from the rule registry by approve_quarantined(). A
        # future PR can close the on-disk-preservation gap. See the test
        # docstring for the full lock-in.

        # No god dispatched
        self.assertEqual(self.gw.calls, [])

    # --- Rule 4: tallon-feature-request — dispatches deploy-feature at "research".

    async def test_tallon_feature_request_dispatches_deploy_feature_at_research(self):
        ev = eng.Event(
            type="nats.message",
            source="tallon",
            subject="subspace.tallon.feature.request",
            payload={"feature_summary": "new deployable", "context_policy": "forward_all"},
            is_external=True,
        )
        rule = self.engine.rules.match(ev)
        self.assertEqual(rule.id, "tallon-feature-request")
        self.assertEqual(rule.then["dispatch_workflow"], "deploy-feature")
        self.assertEqual(rule.then["start_at_step"], "research")

        result = await self.engine.handle_event(ev)
        self.assertEqual(result["status"], "workflow_started")
        self.assertEqual(result["rule"], "tallon-feature-request")

        inst = self.engine.get_instance(result["workflow_id"])
        self.assertIsNotNone(inst)
        self.assertEqual(inst.definition_id, "deploy-feature")
        # The workflow was started AT the "research" step, not the first step.
        # (deploy-feature.yaml defines steps; the rule's start_at_step override
        # is honored by start_workflow() — see engine.py:723.)
        self.assertEqual(inst.current_step, "research")
        self.assertEqual(inst.initiator, "tallon")

        # No quarantine
        self.assertEqual(list(self.tmp.quarantine_dir.glob("*.json")), [])

    # --- Bonus: tallon-incoming-message — fnmatch `*` glob in subject.

    async def test_tallon_incoming_message_matches_star_glob(self):
        """The `tallon-incoming-message` rule in research-to-build.yaml uses
        a fnmatch `*` glob. Verifies the matcher handles it (single-segment
        `*` crosses dots in fnmatch — documented behavior, see engine.py
        _match_condition docstring, 2026-06-15).
        """
        ev = eng.Event(
            type="nats.message",
            source="tallon",
            subject="subspace.tallon.incoming.hephaestus",
            payload={"summary": "inbound message to hephaestus"},
            is_external=True,
        )
        rule = self.engine.rules.match(ev)
        self.assertIsNotNone(rule, "no rule matched subspace.tallon.incoming.*")
        self.assertEqual(rule.id, "tallon-incoming-message")

        # The rule has dispatch_god: hermes — queue a mock run so the
        # dispatch path completes cleanly without a real gateway.
        self.gw.queue_run(cf.MockRun("r_hermes_review", output="inbox reviewed"))

        result = await self.engine.handle_event(ev)
        # dispatch_god path: god run was submitted and the gateway returned
        # the queued run. Verify the dispatch intent completed.
        self.assertEqual(result["status"], "god_dispatched")
        self.assertEqual(result["rule"], "tallon-incoming-message")
        self.assertEqual(result["god"], "hermes")
        self.assertEqual(len(self.gw.calls), 1, "expected exactly one god run submitted")
        # No quarantine
        self.assertEqual(list(self.tmp.quarantine_dir.glob("*.json")), [])

    # --- Negative path: genuinely unmatched subject hits the default.

    async def test_unmatched_subject_falls_through_to_default_quarantine(self):
        """The BUILD-PLAN's "they all get quarantined" claim is correct for
        events that DON'T match any rule. This test pins that down: a NATS
        message on a subject no rule covers must fall through to
        __default_external__ and write a quarantine file. The brief's concern
        was that the 4 production rules were ALSO falling through here; the
        other tests in this class prove they don't.
        """
        ev = eng.Event(
            type="nats.message",
            source="tallon",
            subject="subspace.tallon.workflow.something_we_dont_have_a_rule_for",
            payload={"summary": "no rule covers this"},
            is_external=True,
        )
        rule = self.engine.rules.match(ev)
        self.assertIsNone(rule, "expected no rule match for unknown subject")

        # handle_event will fall through to the default for external events
        result = await self.engine.handle_event(ev)
        self.assertEqual(result["status"], "quarantined")
        self.assertEqual(result["mode"], "approval_required")
        self.assertEqual(result["rule"], "__default_external__")

        qfiles = list(self.tmp.quarantine_dir.glob("*.json"))
        self.assertEqual(len(qfiles), 1)
        qdata = json.loads(qfiles[0].read_text())
        self.assertEqual(qdata["rule_id"], "__default_external__")
        self.assertEqual(qdata["event"]["subject"],
                         "subspace.tallon.workflow.something_we_dont_have_a_rule_for")


# ===========================================================================
# 2. End-to-end NATS listener → engine (hermetic, no broker)
# ===========================================================================

class TestNatsListenerToEngineBridge(unittest.IsolatedAsyncioTestCase):
    """Simulate receiving a NATS message through the listener and verify the
    engine processes the resulting Event. Hermetic — uses the listener's
    _handle_msg with a fake msg object, no real broker.

    This is the brief's §Step 3.2 verification path (items 1-3):
      1. Mocks the NATS listener (don't connect to real NATS — that's not
         hermetic).
      2. Simulates receiving a NATS message on
         `subspace.enterprise.deploy.request`.
      3. Constructs an Event (via the listener's normal pipeline) and
         calls engine.handle_event().
    """

    def setUp(self):
        self.tmp, self.gw, self.engine = _make_engine_with_real_rules()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_listener_synthesizes_event_and_engine_dispatches(self):
        """The full bridge path: NATS msg → listener._handle_msg → Event
        with source="tallon" (inferred from subject) → on_message callback
        (which we wire to engine.handle_event). Verifies the listener does
        NOT mangle the subject or payload in a way that would break rule
        matching, and the engine processes the result.
        """
        captured: list[eng.Event] = []

        async def on_message(ev: eng.Event) -> None:
            captured.append(ev)
            result = await self.engine.handle_event(ev)
            # Stash the result on the event for assertion in the test
            ev._test_dispatch_result = result  # type: ignore[attr-defined]

        listener = nats_mod.NATSListener(
            url="nats://unreachable:4222",  # never connected
            token="",
            on_message=on_message,
        )

        # The exact brief scenario: a NATS message on
        # subspace.enterprise.deploy.request from Tallon.
        msg = _make_fake_nats_msg(
            subject="subspace.enterprise.deploy.request",
            payload={
                "type": "deploy.request",
                "feature_summary": "E2E bridge test",
                "review_artifacts": ["art_1", "art_2"],
                "target_environment": "production",
            },
        )
        await listener._handle_msg("subspace.enterprise.deploy.request", msg)

        # Listener produced exactly one Event
        self.assertEqual(len(captured), 1)
        ev = captured[0]

        # Listener correctly inferred source from subject path
        # ("subspace.enterprise" → "enterprise"). NOTE: the
        # enterprise-deploy-request rule does NOT filter on source
        # (its when: block is just event_type + subject) so this
        # source value does not block the match — verified below.
        self.assertEqual(ev.source, "enterprise")
        # Event.type is the routing discriminator; must be nats.message
        # even when the payload contains a "type" key. See nats.py bug
        # fix 2026-06-15 for the rationale.
        self.assertEqual(ev.type, "nats.message")
        # The payload's application-level type is preserved inside
        # ev.payload["type"] for downstream consumers.
        self.assertEqual(ev.payload["type"], "deploy.request")
        self.assertEqual(ev.subject, "subspace.enterprise.deploy.request")
        self.assertTrue(ev.is_external)
        # Payload preserved (the feature_summary key must reach the engine)
        self.assertEqual(ev.payload["feature_summary"], "E2E bridge test")

        # Engine dispatched the workflow
        result = ev._test_dispatch_result  # type: ignore[attr-defined]
        self.assertEqual(result["status"], "workflow_started")
        self.assertEqual(result["rule"], "enterprise-deploy-request")
        self.assertIn("workflow_id", result)

        # No quarantine file written
        qfiles = list(self.tmp.quarantine_dir.glob("*.json"))
        self.assertEqual(qfiles, [])

    async def test_listener_preserves_payload_source_override(self):
        """Tallon may include `source` in the payload itself. Verify the
        listener honors it (per nats.py:182-184) and the rule still fires
        (the brief-listed 4 rules don't filter on source, so this should
        not break the match — it should still dispatch).
        """
        captured: list[eng.Event] = []

        async def on_message(ev: eng.Event) -> None:
            captured.append(ev)
            ev._test_dispatch_result = await self.engine.handle_event(ev)  # type: ignore[attr-defined]

        listener = nats_mod.NATSListener(
            url="nats://unreachable:4222",
            token="",
            on_message=on_message,
        )
        msg = _make_fake_nats_msg(
            subject="subspace.enterprise.deploy.request",
            payload={
                "source": "tallon-data-pod-7",  # explicit override
                "type": "deploy.request",
                "feature_summary": "with source override",
            },
        )
        await listener._handle_msg("subspace.enterprise.deploy.request", msg)

        ev = captured[0]
        # Listener honored the payload-level source
        self.assertEqual(ev.source, "tallon-data-pod-7")
        # Rule still matched (none of the 4 brief rules filter on source —
        # only event_type=+subject=). Engine dispatched.
        result = ev._test_dispatch_result  # type: ignore[attr-defined]
        self.assertEqual(result["status"], "workflow_started")
        self.assertEqual(result["rule"], "enterprise-deploy-request")


# ===========================================================================
# 3. Matcher semantics — what the `*` glob actually does in subject context
# ===========================================================================

class TestSubjectMatcherSemantics(unittest.TestCase):
    """Document the matcher's subject-glob behavior so a future change to
    the matcher (e.g. switching from fnmatch to nats.subject_match) is
    forced to make an explicit decision about each of these cases.
    """

    def setUp(self):
        self.tmp, _, self.engine = _make_engine_with_real_rules()

    def tearDown(self):
        self.tmp.cleanup()

    def test_star_glob_matches_single_trailing_token(self):
        """The production rule `tallon-incoming-message` uses
        `subspace.tallon.incoming.*` and we expect it to match a single
        trailing token (`hephaestus`). Lock that in.
        """
        ev = eng.Event(type="nats.message", source="tallon",
                       subject="subspace.tallon.incoming.hephaestus",
                       is_external=True)
        rule = self.engine.rules.match(ev)
        self.assertEqual(rule.id if rule else None, "tallon-incoming-message")

    def test_star_glob_also_matches_multi_token_subjects(self):
        """fnmatch's `*` is greedy and crosses `.` boundaries. A subject
        with multiple trailing tokens (`a.b.c.d`) still matches `*.d`.
        This is documented fnmatch behavior; the test pins it so a
        future swap to a NATS-aware matcher (which would NOT cross
        dots with `*`) forces an explicit decision about whether to
        preserve or break this.

        Concretely: the rule `tallon-incoming-message` uses
        `subspace.tallon.incoming.*` — under fnmatch it matches both
        `subspace.tallon.incoming.hephaestus` AND a hypothetical
        `subspace.tallon.incoming.hephaestus.foo.bar`. If we ever
        switch to NATS subject matching, only the first should match.
        """
        ev = eng.Event(type="nats.message", source="tallon",
                       subject="subspace.tallon.incoming.hephaestus.foo.bar",
                       is_external=True)
        rule = self.engine.rules.match(ev)
        # Today (fnmatch): the `*` greedily matches across dots, so this fires.
        self.assertEqual(rule.id if rule else None, "tallon-incoming-message",
                         "fnmatch `*` is expected to cross dots; if this test "
                         "fails after a matcher swap, the swap needs to make "
                         "an explicit decision about preserving the behavior.")

    def test_exact_subject_only_matches_exact_string(self):
        """The 3 exact-subject rules (enterprise-deploy-request,
        tallon-workflow-complete, tallon-workflow-failed,
        tallon-feature-request) must NOT match a superstring or substring.
        """
        exact_subjects_and_rule_ids = [
            ("subspace.enterprise.deploy.request", "enterprise-deploy-request"),
            ("subspace.tallon.workflow.complete", "tallon-workflow-complete"),
            ("subspace.tallon.workflow.failed", "tallon-workflow-failed"),
            ("subspace.tallon.feature.request", "tallon-feature-request"),
        ]
        for subj, expected_rule_id in exact_subjects_and_rule_ids:
            # Substring: add a token
            ev_extra = eng.Event(type="nats.message", source="tallon",
                                 subject=subj + ".extra", is_external=True)
            rule_extra = self.engine.rules.match(ev_extra)
            self.assertNotEqual(
                rule_extra.id if rule_extra else None, expected_rule_id,
                f"exact-subject rule {expected_rule_id!r} matched superstring "
                f"subject {subj + '.extra'!r} (this would be a matcher bug)"
            )
            # Prefix: missing a token
            ev_short = eng.Event(type="nats.message", source="tallon",
                                 subject=subj.rsplit(".", 1)[0], is_external=True)
            rule_short = self.engine.rules.match(ev_short)
            self.assertNotEqual(
                rule_short.id if rule_short else None, expected_rule_id,
                f"exact-subject rule {expected_rule_id!r} matched prefix "
                f"subject {subj.rsplit('.', 1)[0]!r} (this would be a matcher bug)"
            )

    def test_rule_count_is_what_we_expect(self):
        """Lock the production rule count and a few IDs so a future reload
        of `rules/` that drops or duplicates a rule surfaces immediately.

        If you add a new production rule, update this test (the rule_id
        list is a self-documenting inventory).
        """
        rule_ids = sorted(r.id for r in self.engine.rules._rules)
        expected = sorted([
            "tallon-workflow-complete",
            "tallon-workflow-failed",
            "research-handoff-to-hephaestus",
            "marvin-complete-notify-review",
            "tallon-incoming-message",
            "daily-morning-briefing",
            "friday-deploy-reminder",
            "enterprise-deploy-request",
            "tallon-feature-request",
        ])
        self.assertEqual(rule_ids, expected,
                         f"production rule inventory drifted; got {rule_ids}")


if __name__ == "__main__":
    unittest.main()
