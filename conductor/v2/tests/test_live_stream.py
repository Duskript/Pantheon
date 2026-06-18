"""Tests for A.2 (2026-06-16) — WebSocket live-observability stream.

Covers conductor/v2/live_stream.py + the engine integration +
the streaming path in cli_tool.py. 10 tests:

  1.  test_server_lifecycle_start_stop
  2.  test_client_connect_with_valid_api_key_receives_events
  3.  test_client_connect_rejected_with_invalid_api_key
  4.  test_broadcast_to_single_subscriber
  5.  test_broadcast_to_multiple_subscribers
  6.  test_per_step_routing_isolates_subscribers
  7.  test_engine_emits_step_lifecycle_events
  8.  test_stream_json_ndjson_parsing_via_claude_format
  9.  test_clean_disconnect_removes_subscription
  10. test_server_shutdown_during_active_connections_closes_all

Run with:
    PYTHONPATH=/home/konan/pantheon \\
    ~/.hermes/hermes-agent/venv/bin/pytest \\
    conductor/v2/tests/test_live_stream.py -q
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import unittest
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

# v2 imports
from v2 import engine as eng  # noqa: E402
from v2 import cli_tool as ct  # noqa: E402
from v2 import live_stream as ls  # noqa: E402
from v2.tests import fixtures as cf  # noqa: E402

import aiohttp  # noqa: E402
from aiohttp import WSServerHandshakeError  # noqa: E402


def _free_port() -> int:
    """Bind to port 0 to discover a free port, then release it.

    There's an unavoidable race condition (another process could grab
    the port between close() and our start()), but for the test
    isolation we get (each test gets a fresh port), it's good enough.
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ---------------------------------------------------------------------------
# Shared async runner: each async test is wrapped in `asyncio.run`
# ---------------------------------------------------------------------------

def _run(coro):
    """Helper: run a coroutine in a fresh loop and return its result.

    Used because the test methods are synchronous (unittest.TestCase
    pattern) but the WebSocket / streaming logic is async. We avoid
    `unittest.IsolatedAsyncioTestCase` to keep style consistent with
    the rest of the v2 test suite, which uses sync test methods
    calling async helpers via asyncio.run.
    """
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Server lifecycle
# ---------------------------------------------------------------------------

class TestServerLifecycle(unittest.TestCase):
    """The server can be started and stopped cleanly. No errors, no
    leaked connections. Idempotent start (calling start twice = no-op).
    """

    def test_server_lifecycle_start_stop(self):
        async def go():
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="k1")
            self.assertFalse(server.is_running)
            self.assertEqual(server.connection_count, 0)
            await server.start()
            self.assertTrue(server.is_running)
            # Idempotent: second start is a no-op (no exception)
            await server.start()
            self.assertTrue(server.is_running)
            await server.stop()
            self.assertFalse(server.is_running)
            # Stop is also idempotent (safe to call twice)
            await server.stop()
            self.assertFalse(server.is_running)
        _run(go())


# ---------------------------------------------------------------------------
# 2-3. Client connect: valid + invalid api_key
# ---------------------------------------------------------------------------

class TestClientConnect(unittest.TestCase):
    """api_key query param: valid → handshake succeeds, invalid → 403."""

    def test_client_connect_with_valid_api_key_receives_events(self):
        async def go():
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="secret")
            await server.start()
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        f"http://127.0.0.1:{port}/clitool/wf_a/step_a?api_key=secret"
                    ) as ws:
                        # Give the server a moment to register the connection
                        await asyncio.sleep(0.05)
                        self.assertEqual(server.connection_count, 1)

                        # Broadcast an event
                        evt = ls.StreamEvent.now("wf_a", "step_a", "thinking", {"text": "hello"})
                        delivered = await server.broadcast(evt)
                        self.assertEqual(delivered, 1)

                        # Client receives it
                        msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                        self.assertEqual(msg.type, aiohttp.WSMsgType.TEXT)
                        payload = json.loads(msg.data)
                        self.assertEqual(payload["event"], "thinking")
                        self.assertEqual(payload["data"]["text"], "hello")
                        self.assertEqual(payload["workflow_id"], "wf_a")
                        self.assertEqual(payload["step_id"], "step_a")
            finally:
                await server.stop()
        _run(go())

    def test_client_connect_rejected_with_invalid_api_key(self):
        async def go():
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="secret")
            await server.start()
            try:
                async with aiohttp.ClientSession() as session:
                    # Wrong key → 403
                    with self.assertRaises(WSServerHandshakeError) as ctx:
                        async with session.ws_connect(
                            f"http://127.0.0.1:{port}/clitool/wf_a/step_a?api_key=WRONG"
                        ):
                            pass
                    self.assertEqual(ctx.exception.status, 403)
                    # Missing key → 403 (empty string != "secret")
                    with self.assertRaises(WSServerHandshakeError) as ctx2:
                        async with session.ws_connect(
                            f"http://127.0.0.1:{port}/clitool/wf_a/step_a"
                        ):
                            pass
                    self.assertEqual(ctx2.exception.status, 403)
                    # Connection count stays at 0
                    self.assertEqual(server.connection_count, 0)
            finally:
                await server.stop()
        _run(go())


# ---------------------------------------------------------------------------
# 4-6. Broadcasting: single, multiple, per-step routing
# ---------------------------------------------------------------------------

class TestBroadcast(unittest.TestCase):
    """broadcast() fans out to subscribers of the matching
    (workflow_id, step_id). Other subscribers don't see the event.
    """

    async def _setup_server_with_subs(self, n_subs: int, wf: str, step: str):
        port = _free_port()
        server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="k")
        await server.start()
        url = f"http://127.0.0.1:{port}/clitool/{wf}/{step}?api_key=k"
        session = aiohttp.ClientSession()
        subs = []
        for _ in range(n_subs):
            ws = await session.ws_connect(url)
            subs.append(ws)
        # Wait for server to register all
        await asyncio.sleep(0.05)
        return server, session, subs

    def test_broadcast_to_single_subscriber(self):
        async def go():
            server, session, subs = await self._setup_server_with_subs(1, "wf1", "s1")
            try:
                self.assertEqual(server.connection_count, 1)
                evt = ls.StreamEvent.now("wf1", "s1", "tool_call", {"tool_name": "Bash"})
                delivered = await server.broadcast(evt)
                self.assertEqual(delivered, 1)
                msg = await asyncio.wait_for(subs[0].receive(), timeout=2.0)
                payload = json.loads(msg.data)
                self.assertEqual(payload["event"], "tool_call")
            finally:
                for ws in subs:
                    await ws.close()
                await session.close()
                await server.stop()
        _run(go())

    def test_broadcast_to_multiple_subscribers(self):
        async def go():
            server, session, subs = await self._setup_server_with_subs(3, "wf1", "s1")
            try:
                self.assertEqual(server.connection_count, 3)
                evt = ls.StreamEvent.now("wf1", "s1", "output", {"text": "fanned out"})
                delivered = await server.broadcast(evt)
                self.assertEqual(delivered, 3)
                # All 3 clients should receive
                for i, ws in enumerate(subs):
                    msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                    payload = json.loads(msg.data)
                    self.assertEqual(payload["event"], "output")
                    self.assertEqual(payload["data"]["text"], "fanned out")
            finally:
                for ws in subs:
                    await ws.close()
                await session.close()
                await server.stop()
        _run(go())

    def test_per_step_routing_isolates_subscribers(self):
        async def go():
            # Two subscriptions on different (wf, step) tuples.
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="k")
            await server.start()
            try:
                session = aiohttp.ClientSession()
                # wf1/s1
                ws_a = await session.ws_connect(
                    f"http://127.0.0.1:{port}/clitool/wf1/s1?api_key=k"
                )
                # wf1/s2 (different step on same workflow)
                ws_b = await session.ws_connect(
                    f"http://127.0.0.1:{port}/clitool/wf1/s2?api_key=k"
                )
                # wf2/s1 (different workflow, same step id)
                ws_c = await session.ws_connect(
                    f"http://127.0.0.1:{port}/clitool/wf2/s1?api_key=k"
                )
                await asyncio.sleep(0.05)
                self.assertEqual(server.connection_count, 3)

                # Broadcast to wf1/s1 — only ws_a should receive
                evt = ls.StreamEvent.now("wf1", "s1", "done", {"status": "success"})
                delivered = await server.broadcast(evt)
                self.assertEqual(delivered, 1)

                msg = await asyncio.wait_for(ws_a.receive(), timeout=2.0)
                self.assertEqual(json.loads(msg.data)["event"], "done")
                # The other two should have NOTHING in their buffer.
                # (We use a short wait_for to verify non-delivery — if
                # they had received the event, receive() would resolve
                # immediately with a message.)
                for ws in (ws_b, ws_c):
                    with self.assertRaises(asyncio.TimeoutError):
                        await asyncio.wait_for(ws.receive(), timeout=0.2)
            finally:
                for ws in (ws_a, ws_b, ws_c):
                    await ws.close()
                await session.close()
                await server.stop()
        _run(go())


# ---------------------------------------------------------------------------
# 7. Engine integration: step.started → tool events → step.completed
# ---------------------------------------------------------------------------

class TestEngineEmitsEvents(unittest.TestCase):
    """When a live_stream is passed to ConductorEngine, the engine
    emits step.started/completed/failed and workflow.started/completed
    events. Verified end-to-end by:
      1. Construct engine with a live_stream (port=0 trick to get free)
      2. Connect a websocket subscriber
      3. Run a workflow containing a cli_tool step with stream=True
      4. Verify the event sequence over the websocket
    """

    def test_engine_emits_step_lifecycle_events(self):
        async def go():
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="k")
            await server.start()
            try:
                # Build a minimal workflow with a single cli_tool step
                wf_dict = {
                    "workflow": {
                        "id": "lifecycle_test",
                        "name": "lifecycle_test",
                        "version": "1.0.0",
                        "steps": [{
                            "id": "s1",
                            "type": "cli_tool",
                            "tool": "_mock_echo",
                            "tool_input": {"prompt": "from-lifecycle-test", "stream": True},
                            "on_error": {"retry": {"max_attempts": 1}},
                            "timeout": "10s",
                            "output": "out1",
                        }],
                    }
                }
                tmp = cf.TmpConductor.create()
                try:
                    # Write YAML to disk so WorkflowRegistry picks it up
                    wf_path = tmp.workflows_dir / "lifecycle_test.yaml"
                    wf_path.write_text(json.dumps(wf_dict))
                    # Build the engine with our live_stream
                    engine_obj = eng.ConductorEngine(
                        workflows_dir=tmp.workflows_dir,
                        live_stream=server,
                    )

                    # Subscribe a client to the step's URL
                    session = aiohttp.ClientSession()
                    inst = engine_obj.start_workflow_sync("lifecycle_test")
                    sub_url = f"http://127.0.0.1:{port}/clitool/{inst.workflow_id}/s1?api_key=k"
                    ws = await session.ws_connect(sub_url)
                    await asyncio.sleep(0.05)

                    # Now run the step (async) — this is what
                    # start_workflow would do, but sync doesn't
                    # schedule. We call _execute_step directly.
                    # Look up the workflow from engine registry (not from_dict — it's on disk now)
                    wf = engine_obj.workflows.get("lifecycle_test")
                    await engine_obj._execute_step(inst, wf, "s1")

                    # Drain events. Expected order:
                    #   1. workflow.started (emitted at start_workflow)
                    #      — we missed it because we subscribed AFTER
                    #      start_workflow_sync. So our first event
                    #      should be step.started.
                    #   2. step.started
                    #   3. (tool events from the streaming path)
                    #   4. step.completed
                    events = []
                    try:
                        while True:
                            msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                events.append(json.loads(msg.data))
                            elif msg.type == aiohttp.WSMsgType.CLOSE:
                                break
                    except asyncio.TimeoutError:
                        pass  # no more events

                    # We expect at least step.started + step.completed
                    ev_types = [e["event"] for e in events]
                    self.assertIn("step.started", ev_types, f"missing step.started in {ev_types}")
                    self.assertIn("step.completed", ev_types, f"missing step.completed in {ev_types}")

                    # The step.started payload should include step_type=cli_tool
                    started = next(e for e in events if e["event"] == "step.started")
                    self.assertEqual(started["data"]["step_type"], "cli_tool")
                    self.assertEqual(started["data"]["tool"], "_mock_echo")

                    # The step.completed payload should include status=completed
                    completed = next(e for e in events if e["event"] == "step.completed")
                    self.assertEqual(completed["data"]["step_type"], "cli_tool")
                    self.assertIn(completed["data"]["status"], ("completed", "refused"))

                    await ws.close()
                    await session.close()
                finally:
                    tmp.cleanup()
            finally:
                await server.stop()
        _run(go())


# ---------------------------------------------------------------------------
# 8. NDJSON parsing (claude-stream-json format)
# ---------------------------------------------------------------------------

class TestNdjsonParsing(unittest.TestCase):
    """The _ndjson_from_claude parser maps NDJSON lines to spec §3
    event types. We verify a few representative lines (no subprocess
    needed — pure unit test of the parser).
    """

    def test_stream_json_ndjson_parsing_via_claude_format(self):
        # content_block_delta with text_delta → "output"
        ev, data = ct._ndjson_from_claude({
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "hello world"},
        })
        self.assertEqual(ev, "output")
        self.assertEqual(data["text"], "hello world")
        self.assertFalse(data["is_final"])

        # tool_use → "tool_call"
        ev, data = ct._ndjson_from_claude({
            "type": "tool_use",
            "name": "Bash",
            "input": {"command": "ls -la"},
        })
        self.assertEqual(ev, "tool_call")
        self.assertEqual(data["tool_name"], "Bash")
        self.assertEqual(data["args"], {"command": "ls -la"})

        # message_stop → "done"
        ev, data = ct._ndjson_from_claude({
            "type": "message_stop",
            "message": {"stop_reason": "end_turn"},
        })
        self.assertEqual(ev, "done")
        self.assertEqual(data["status"], "success")

        # error → "error"
        ev, data = ct._ndjson_from_claude({
            "type": "error",
            "error": {"message": "rate limit"},
        })
        self.assertEqual(ev, "error")
        self.assertEqual(data["message"], "rate limit")
        self.assertFalse(data["recoverable"])

        # unknown type → "thinking" (default)
        ev, data = ct._ndjson_from_claude({
            "type": "message_start",
            "message": {"id": "msg_01"},
        })
        self.assertEqual(ev, "thinking")

        # Non-dict input → passthrough
        ev, data = ct._ndjson_from_claude("not a dict")
        self.assertEqual(ev, "output")

        # _ndjson_to_event: builds a StreamEvent with the right routing.
        # workflow_id and step_id start empty (the caller fills them).
        reg = ct.ToolRegistration(
            name="_test_claude",
            command="/bin/echo",
            args_template=["{prompt}"],
            output_format="stream-json",
            timeout_default="5s",
            stream_format="claude-stream-json",
        )
        evt = ct._ndjson_to_event(reg, {
            "type": "content_block_delta",
            "delta": {"type": "text_delta", "text": "from-ndjson"},
        })
        self.assertIsInstance(evt, ls.StreamEvent)
        self.assertEqual(evt.event, "output")
        self.assertEqual(evt.data["text"], "from-ndjson")
        self.assertEqual(evt.workflow_id, "")  # filled by caller
        self.assertEqual(evt.step_id, "")      # filled by caller


# ---------------------------------------------------------------------------
# 9. Clean disconnect
# ---------------------------------------------------------------------------

class TestCleanDisconnect(unittest.TestCase):
    """When a client disconnects mid-stream, the server removes it
    from the connections dict (no leak). A subsequent broadcast
    doesn't try to send to the dead client.
    """

    def test_clean_disconnect_removes_subscription(self):
        async def go():
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="k")
            await server.start()
            try:
                session = aiohttp.ClientSession()
                ws = await session.ws_connect(
                    f"http://127.0.0.1:{port}/clitool/wf_d/s_d?api_key=k"
                )
                await asyncio.sleep(0.05)
                self.assertEqual(server.connection_count, 1)

                # Disconnect
                await ws.close()
                # Give the server's finally block time to run
                await asyncio.sleep(0.1)
                self.assertEqual(server.connection_count, 0)

                # A broadcast now should deliver to 0 (not raise)
                evt = ls.StreamEvent.now("wf_d", "s_d", "done", {"status": "success"})
                delivered = await server.broadcast(evt)
                self.assertEqual(delivered, 0)

                await session.close()
            finally:
                await server.stop()
        _run(go())


# ---------------------------------------------------------------------------
# 10. Server shutdown during active connections
# ---------------------------------------------------------------------------

class TestServerShutdown(unittest.TestCase):
    """stop() during active connections closes all sockets cleanly.
    No hangs, no orphaned tasks.
    """

    def test_server_shutdown_during_active_connections_closes_all(self):
        async def go():
            port = _free_port()
            server = ls.LiveStreamServer(host="127.0.0.1", port=port, api_key="k")
            await server.start()
            session = aiohttp.ClientSession()
            subs = []
            for i in range(2):
                ws = await session.ws_connect(
                    f"http://127.0.0.1:{port}/clitool/wf_shut/s_{i}?api_key=k"
                )
                subs.append(ws)
            await asyncio.sleep(0.05)
            self.assertEqual(server.connection_count, 2)

            # Shutdown with active connections
            await server.stop()
            self.assertFalse(server.is_running)
            self.assertEqual(server.connection_count, 0)

            # The client sockets should have received a close frame
            for ws in subs:
                msg = await asyncio.wait_for(ws.receive(), timeout=2.0)
                self.assertEqual(msg.type, aiohttp.WSMsgType.CLOSE)
            await session.close()
        _run(go())


if __name__ == "__main__":
    unittest.main()
