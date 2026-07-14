"""Unit tests for conductor.v2.nats — NATSListener.

We don't need a live NATS broker — the daemon must survive NATS being
down (spec 6). Tests cover:

  - Token loading from env
  - Connection failure: returns clean status dict, doesn't raise
  - Subject parsing: source inferred from subject path
  - Payload parsing: JSON body, raw text, dict
  - on_message callback: invoked with synthesized Event

If nats-py is unavailable, all tests still pass (listener reports
disabled). If nats-py is available but no broker is reachable, all
tests still pass (listener reports unreachable).
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import nats as nats_mod  # noqa: E402


class TestNatsTokenLoading(unittest.TestCase):
    """_load_token parses NATS_TOKEN= from a .env file."""

    def test_load_token_from_env_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write("# comment\n")
            f.write("NATS_TOKEN=secret123\n")
            f.write("OTHER=foo\n")
            path = Path(f.name)
        try:
            tok = nats_mod._load_token(path)
            self.assertEqual(tok, "secret123")
        finally:
            path.unlink()

    def test_load_token_missing_file_returns_empty(self):
        tok = nats_mod._load_token(Path("/tmp/does_not_exist_xyz.env"))
        self.assertEqual(tok, "")

    def test_load_token_strips_quotes(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as f:
            f.write('NATS_TOKEN="quoted-secret"\n')
            path = Path(f.name)
        try:
            tok = nats_mod._load_token(path)
            self.assertEqual(tok, "quoted-secret")
        finally:
            path.unlink()


class TestNatsMessageParsing(unittest.IsolatedAsyncioTestCase):
    """The _handle_msg method synthesizes an Event from a raw NATS
    message. We don't need a real connection — call _handle_msg with a
    fake msg object and verify the Event it passes to on_message."""

    def _make_listener(self, on_message=None) -> nats_mod.NATSListener:
        return nats_mod.NATSListener(
            url="nats://unreachable:4222",
            token="",
            on_message=on_message,
        )

    def _fake_msg(self, subject: str, data: bytes) -> Any:
        """Build a fake msg that mimics nats.aio.client.Msg."""
        m = MagicMock()
        m.subject = subject
        m.data = data
        return m

    async def test_handle_msg_json_payload(self):
        captured: list[Any] = []
        async def cb(ev):
            captured.append(ev)
        listener = self._make_listener(on_message=cb)
        msg = self._fake_msg(
            "subspace.tallon.outgoing.hephaestus",
            json.dumps({"type": "ping", "hello": "world"}).encode(),
        )
        await listener._handle_msg("subspace.tallon.outgoing.hephaestus", msg)
        self.assertEqual(len(captured), 1)
        ev = captured[0]
        # Source inferred from subject path (subspace.tallon → tallon)
        self.assertEqual(ev.source, "tallon")
        # Event.type is the routing discriminator — it must stay
        # "nats.message" regardless of what the payload says. The
        # payload's `type` ("ping" here) is application metadata and
        # is preserved inside ev.payload["type"] for downstream
        # consumers that want to branch on it. See nats.py:_handle_msg
        # for the 2026-06-15 bug-fix rationale.
        self.assertEqual(ev.type, "nats.message")
        self.assertEqual(ev.payload["type"], "ping")
        self.assertEqual(ev.payload["hello"], "world")
        # All NATS messages are external
        self.assertTrue(ev.is_external)

    async def test_handle_msg_raw_text_fallback(self):
        captured: list[Any] = []
        async def cb(ev):
            captured.append(ev)
        listener = self._make_listener(on_message=cb)
        msg = self._fake_msg("subspace.broadcast", b"not json at all")
        await listener._handle_msg("subspace.broadcast", msg)
        ev = captured[0]
        # source = "broadcast" for that subject
        self.assertEqual(ev.source, "broadcast")
        self.assertIn("_raw", ev.payload)
        self.assertEqual(ev.payload["_raw"], "not json at all")
        # No type in payload → defaults to "nats.message"
        self.assertEqual(ev.type, "nats.message")

    async def test_handle_msg_payload_source_overrides_subject(self):
        captured: list[Any] = []
        async def cb(ev):
            captured.append(ev)
        listener = self._make_listener(on_message=cb)
        # Tallon may include source in the payload itself
        msg = self._fake_msg(
            "subspace.pantheon.incoming.x",
            json.dumps({"source": "tallon-explicit", "type": "t"}).encode(),
        )
        await listener._handle_msg("subspace.pantheon.incoming.x", msg)
        ev = captured[0]
        self.assertEqual(ev.source, "tallon-explicit")
        # target inferred if present
        self.assertIsNone(ev.target)

    async def test_handle_msg_no_callback_silently_drops(self):
        listener = self._make_listener(on_message=None)
        msg = self._fake_msg("subspace.broadcast", b"{}")
        # Should not raise
        await listener._handle_msg("subspace.broadcast", msg)

    async def test_handle_msg_uses_subject_when_no_payload_source(self):
        captured: list[Any] = []
        async def cb(ev):
            captured.append(ev)
        listener = self._make_listener(on_message=cb)
        msg = self._fake_msg(
            "subspace.pantheon.incoming.misc",
            json.dumps({"type": "x"}).encode(),
        )
        await listener._handle_msg("subspace.pantheon.incoming.misc", msg)
        ev = captured[0]
        # subject path: subspace.pantheon → source = "pantheon"
        self.assertEqual(ev.source, "pantheon")


class TestNatsConnectionFailure(unittest.IsolatedAsyncioTestCase):
    """When NATS is unreachable, the listener must return a clean
    status dict and NOT raise. The daemon must keep running."""

    async def test_start_returns_unreachable_when_no_broker(self):
        # 127.0.0.1:1 is guaranteed to be closed → connect fails fast
        listener = nats_mod.NATSListener(url="nats://127.0.0.1:1", token="")
        result = await listener.start()
        # Either "unreachable" (connect timeout/refused) or "disabled"
        # (nats-py not installed) — both are valid clean-fail outcomes
        self.assertIn(result["status"], ("unreachable", "disabled"))
        # If unreachable, must include url so the daemon can log it
        if result["status"] == "unreachable":
            self.assertEqual(result["url"], "nats://127.0.0.1:1")
        # is_connected must be False after failed start
        self.assertFalse(listener.is_connected)

    async def test_publish_when_not_connected_returns_status(self):
        listener = nats_mod.NATSListener(url="nats://127.0.0.1:1", token="")
        result = await listener.publish("test.subject", {"hello": "world"})
        self.assertEqual(result["status"], "not_connected")


if __name__ == "__main__":
    unittest.main()
