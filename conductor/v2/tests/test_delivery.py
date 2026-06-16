"""Unit tests for conductor.v2.delivery — DeliveryRouter.

The router writes notification files to:
  - pending/telegram_outbox/ for Telegram (soft-delivery to gateway)
  - pending/nats_outbox/ for Subspace replies
  - pending/<god>/ for Pantheon inboxes

No real HTTP — we just verify the files appear in the right places
with the right shape.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import delivery as d  # noqa: E402


class TestDeliveryFormatting(unittest.TestCase):
    """format_step_summary and format_quarantine_alert produce the
    human-readable text that goes to Telegram."""

    def test_step_summary_completed_includes_check(self):
        text = d.format_step_summary(
            workflow_id="wf_123", definition_id="morning-briefing",
            step_id="dawn-patrol", god="thoth",
            output="5 hot signals", status="completed",
        )
        self.assertIn("✅", text)
        self.assertIn("wf_123", text)
        self.assertIn("morning-briefing", text)
        self.assertIn("dawn-patrol", text)
        self.assertIn("thoth", text)
        self.assertIn("5 hot signals", text)

    def test_step_summary_failed_includes_cross(self):
        text = d.format_step_summary(
            workflow_id="wf_x", definition_id="d", step_id="s",
            god="g", output="", status="failed",
        )
        self.assertIn("❌", text)
        self.assertIn("failed", text)

    def test_step_summary_truncates_long_output(self):
        long = "x" * 2000
        text = d.format_step_summary(
            "w", "d", "s", "g", long, max_len=500,
        )
        # Should be truncated with ellipsis
        self.assertIn("…", text)
        # No 2000-character run should remain
        self.assertLess(len(text), 1500)

    def test_quarantine_alert_has_action_instructions(self):
        text = d.format_quarantine_alert(
            event_summary="unrecognized webhook from stripe",
            source="stripe",
            subject="/webhook/stripe",
            rule_id="stripe_default",
            quarantine_path="/path/to/q.json",
        )
        self.assertIn("Approval Required", text)
        self.assertIn("stripe", text)
        self.assertIn("stripe_default", text)
        self.assertIn("approve", text)
        self.assertIn("dismiss", text)


class TestDeliveryTargetBuilders(unittest.TestCase):
    """build_default_targets honors the env var for Telegram."""

    def test_default_targets_always_include_inbox(self):
        targets = d.build_default_targets()
        kinds = [t.kind for t in targets]
        self.assertIn("inbox", kinds)
        # Hermes is the canonical inbox god
        hermes = next(t for t in targets if t.kind == "inbox")
        self.assertEqual(hermes.inbox_god, "hermes")

    def test_default_targets_omit_telegram_when_no_chat_id(self):
        # If CONDUCTOR_TELEGRAM_CHAT_ID is not set, no telegram target
        targets = d.build_default_targets()
        if not d.DEFAULT_TELEGRAM_CHAT_ID:
            kinds = [t.kind for t in targets]
            self.assertNotIn("telegram", kinds)


class TestDeliveryInboxWriting(unittest.TestCase):
    """_write_inbox produces a real file in pending/<god>/."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_inbox_creates_file_in_god_dir(self):
        path = self.tmp.pending_dir / "hermes" / "test_inbox.json"
        result = d.DeliveryRouter._write_inbox(
            self=self,  # not used
        ) if False else None
        # Use a fresh router instance
        router = d.DeliveryRouter.__new__(d.DeliveryRouter)
        router.targets = []
        r = router._write_inbox("hermes", "hello from conductor")
        self.assertEqual(r["status"], "queued")
        # Find the file
        files = list((self.tmp.pending_dir / "hermes").glob("conductor_msg_*.json"))
        self.assertEqual(len(files), 1)
        env = json.loads(files[0].read_text())
        self.assertEqual(env["from"], "conductor")
        self.assertEqual(env["to"], "hermes")
        self.assertEqual(env["text"], "hello from conductor")


class TestDeliveryRouterAsync(unittest.IsolatedAsyncioTestCase):
    """End-to-end: build a router, deliver a step completion, verify
    the right files appear in the right directories."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_deliver_step_completion_writes_inbox(self):
        # No telegram target → only inbox
        router = d.DeliveryRouter(
            gateway_base_url="http://unreachable:1",
            gateway_api_key="",
            targets=[d.DeliveryTarget(name="hermes-inbox", kind="inbox", inbox_god="hermes")],
        )
        async with router:
            results = await router.deliver_step_completion(
                workflow_id="wf_t1", definition_id="morning-briefing",
                step_id="step-1", god="thoth",
                output="Today's digest is ready.", status="completed",
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], "queued")
        # File in pending/hermes/
        files = list((self.tmp.pending_dir / "hermes").glob("conductor_msg_*.json"))
        self.assertEqual(len(files), 1)
        body = json.loads(files[0].read_text())
        self.assertIn("Today's digest is ready.", body["text"])

    async def test_deliver_telegram_writes_to_outbox(self):
        router = d.DeliveryRouter(
            gateway_base_url="http://unreachable:1",
            gateway_api_key="",
            targets=[d.DeliveryTarget(
                name="tg-konan", kind="telegram", chat_id="12345",
            )],
        )
        async with router:
            results = await router.deliver("hello from conductor")
        self.assertEqual(results[0]["status"], "queued")
        # File in pending/telegram_outbox/
        outbox = self.tmp.pending_dir / "telegram_outbox"
        files = list(outbox.glob("*.json"))
        self.assertEqual(len(files), 1)
        body = json.loads(files[0].read_text())
        self.assertEqual(body["chat_id"], "12345")
        self.assertEqual(body["text"], "hello from conductor")

    async def test_deliver_subspace_writes_to_outbox(self):
        router = d.DeliveryRouter(
            gateway_base_url="http://unreachable:1",
            gateway_api_key="",
            targets=[d.DeliveryTarget(
                name="tallon", kind="subspace",
                subject="subspace.konan.outgoing.tallon",
            )],
        )
        async with router:
            results = await router.deliver("hello tallon")
        self.assertEqual(results[0]["status"], "queued")
        outbox = self.tmp.pending_dir / "nats_outbox"
        files = list(outbox.glob("*.json"))
        self.assertEqual(len(files), 1)
        body = json.loads(files[0].read_text())
        self.assertEqual(body["subject"], "subspace.konan.outgoing.tallon")
        self.assertEqual(body["payload"]["text"], "hello tallon")

    async def test_deliver_unknown_kind_returns_error(self):
        router = d.DeliveryRouter(
            gateway_base_url="http://x", gateway_api_key="",
            targets=[d.DeliveryTarget(name="weird", kind="carrier_pigeon")],
        )
        async with router:
            results = await router.deliver("hi")
        self.assertEqual(results[0]["status"], "unknown_kind")

    async def test_deliver_quarantine_alert_uses_event_summary(self):
        from v2.engine import Event
        ev = Event(
            type="webhook", source="stripe", subject="/webhook/stripe",
            payload={"summary": "unrecognized charge"}, is_external=True,
        )
        router = d.DeliveryRouter(
            gateway_base_url="http://x", gateway_api_key="",
            targets=[d.DeliveryTarget(name="h", kind="inbox", inbox_god="hermes")],
        )
        async with router:
            results = await router.deliver_quarantine_alert(
                event=ev, rule_id="stripe_default",
                quarantine_path="/tmp/q.json",
            )
        self.assertEqual(results[0]["status"], "queued")
        files = list((self.tmp.pending_dir / "hermes").glob("conductor_msg_*.json"))
        self.assertEqual(len(files), 1)
        body = json.loads(files[0].read_text())
        self.assertIn("Approval Required", body["text"])
        self.assertIn("stripe", body["text"])
        self.assertIn("stripe_default", body["text"])


if __name__ == "__main__":
    unittest.main()
