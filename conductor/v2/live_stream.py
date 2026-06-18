"""Conductor v2 `LiveStreamServer` — WebSocket live-observability stream.

Companion to engine.py + cli_tool.py. Implements Thoth's spec §3
(athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md):

  > The Conductor GUI's Run view ... connects to this WebSocket when an
  > instance is open. The user sees the agent's actions in real time,
  > including file edits and command runs.

Scope implemented in this module (A.2, 2026-06-16):
  - `StreamEvent` dataclass with 8 event types per spec §3 (lines 281-290)
  - `LiveStreamServer` — aiohttp WebSocket server on port 7700
  - Auth via `?api_key=<key>` query param (per spec §9 Q5)
  - Per-(workflow_id, step_id) fan-out via `broadcast(event)`
  - Async lifecycle: `start()` / `stop()` with clean shutdown
  - Reconnection: stateless — clients reconnect with the same URL

Design notes:
  - Each (workflow_id, step_id) tuple maps to a set of WebSocket
    subscribers in `connections`. `broadcast()` fans an event to all
    subscribers of that exact tuple. Events for other tuples are NOT
    delivered (per spec §3 "the user sees the agent's actions in real
    time" — narrow scope = no cross-step leakage).
  - The server is a thin transport: it does NOT enforce any schema on
    the `data` payload (the engine + cli_tool decide what each event
    contains). Validation lives at the producer.
  - Multi-subscriber fan-out is implemented as concurrent `asyncio`
    `send_str()` calls inside a single broadcast. We use
    `asyncio.gather(*tasks, return_exceptions=True)` so one slow /
    failing client does NOT stall the others.
  - The `host` defaults to "0.0.0.0" (all interfaces) so the GUI can
    connect from a different container/host on the same network. The
    `api_key` defaults to an empty string — callers MUST set a real
    key in production (the engine reads CONDUCTOR_WS_API_KEY from
    env if not set explicitly).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from aiohttp import WSMsgType, web

# Shared auth helpers from auth.py. The check_query_key function
# encapsulates the same logic the FastAPI bearer dependency uses, but
# in a shape suitable for aiohttp handlers (returns True/False rather
# than raising HTTPException). The browser WebSocket cannot send a
# custom Authorization header on the upgrade request, so the WS path
# keeps the `?api_key=` query string (spec §6, Q5).
from .auth import check_query_key, resolve_api_key

LOG = logging.getLogger("conductor.v2.live_stream")

# Event types per spec §3 table. Keep in sync with the stream-json
# parsers in cli_tool._run_subprocess_stream().
EVENT_TYPES: frozenset[str] = frozenset({
    "thinking",
    "tool_call",
    "file_edit",
    "file_create",
    "command_run",
    "output",
    "error",
    "done",
})

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7700

# Internal "lifecycle" event types emitted by the engine, NOT from the
# spec §3 table. They flow through the same WebSocket channel but use
# a different `event` field to distinguish (e.g. "step.started" vs
# "step.completed"). The GUI can choose to render or ignore them.
ENGINE_EVENT_PREFIX = "step."  # step.started, step.completed, step.failed
WORKFLOW_EVENT_PREFIX = "workflow."  # workflow.started, workflow.completed


# ---------------------------------------------------------------------------
# StreamEvent
# ---------------------------------------------------------------------------

@dataclass
class StreamEvent:
    """A single event in the live-observability stream.

    Per spec §3 (lines 281-290), the 8 event types are:
      - thinking, tool_call, file_edit, file_create, command_run,
        output, error, done

    The engine also emits lifecycle events (step.started, etc.) that
    follow the same wire shape but are NOT in the spec table — they
    are part of A.2's engine integration (Task 2a).
    """
    ts: str
    workflow_id: str
    step_id: str
    event: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize to a single JSON line (NDJSON-style)."""
        return json.dumps({
            "ts": self.ts,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "event": self.event,
            "data": self.data,
        }, default=str)

    @classmethod
    def now(
        cls,
        workflow_id: str,
        step_id: str,
        event: str,
        data: Optional[dict[str, Any]] = None,
    ) -> "StreamEvent":
        """Build a StreamEvent with the current UTC timestamp."""
        return cls(
            ts=datetime.now(timezone.utc).isoformat(),
            workflow_id=workflow_id,
            step_id=step_id,
            event=event,
            data=dict(data or {}),
        )


# ---------------------------------------------------------------------------
# LiveStreamServer
# ---------------------------------------------------------------------------

class LiveStreamServer:
    """WebSocket server that broadcasts StreamEvents to subscribers.

    The server listens on `ws://{host}:{port}/clitool/{workflow_id}/{step_id}`
    (the `clitool` path prefix matches the Conductor GUI's expected URL
    shape per Iris's mock at http://100.68.106.59:8889/).

    Subscribers connect to a SPECIFIC (workflow_id, step_id) tuple and
    receive only events for that tuple. They authenticate via the
    `?api_key=<key>` query param (spec §9 Q5: API key in query param for
    v1 — browsers cannot send custom headers on WebSocket connect).

    Lifecycle:
        server = LiveStreamServer(port=7700, api_key="secret")
        await server.start()
        # ... server.broadcast(event) from anywhere ...
        await server.stop()

    The server is safe to use as an `asyncio.create_task(...)` target —
    `start()` returns once the listening socket is bound (it does NOT
    block). `stop()` cleanly closes all open connections.
    """

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        api_key: Optional[str] = None,
    ):
        # Resolve api_key via the shared helper. The helper honors
        # CONDUCTOR_API_KEY (canonical) and CONDUCTOR_WS_API_KEY
        # (legacy alias) so operator config keeps working without
        # renaming the env var. An explicit arg wins (tests pass
        # a known key).
        self.api_key = resolve_api_key(api_key)

        self.host = host
        self.port = port
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._connections: dict[tuple[str, str], set[web.WebSocketResponse]] = {}
        self._connection_lock = threading.Lock()
        # Workflow-level subscribers: workflow_id -> list of asyncio.Queue
        # instances. The api_server's SSE handler registers a queue
        # per client so the same workflow event can fan out to N
        # SSE streams without each having to know about the others.
        # The set is empty unless a consumer explicitly subscribes —
        # this is opt-in so the WebSocket-only path is unchanged.
        self._workflow_listeners: dict[str, list[asyncio.Queue]] = {}
        self._listener_lock = threading.Lock()
        self._started = False

    @property
    def is_running(self) -> bool:
        return self._started and self._site is not None

    @property
    def connection_count(self) -> int:
        """Total number of open WebSocket connections (across all subs)."""
        return sum(len(s) for s in self._connections.values())

    # ----- Lifecycle -----

    async def start(self) -> None:
        """Bind the listening socket and start accepting connections.

        Returns once the socket is bound. The actual accept loop runs
        in a background task owned by the aiohttp runner. Idempotent:
        calling start() on a running server is a no-op (logged as info).
        """
        if self._started:
            LOG.info(f"LiveStreamServer already running on {self.host}:{self.port}")
            return

        self._app = web.Application()
        self._app.router.add_get(
            "/clitool/{workflow_id}/{step_id}", self._handle_clitool
        )
        # Health endpoint — useful for `curl http://host:port/health`
        # from a load balancer or an operator.
        self._app.router.add_get("/health", self._handle_health)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()
        self._started = True
        LOG.info(
            f"LiveStreamServer listening on ws://{self.host}:{self.port} "
            f"(auth: {'required' if self.api_key else 'DISABLED — set api_key'})"
        )

    async def stop(self) -> None:
        """Close all open connections and shut down the listening socket.

        Clean shutdown: sends a close frame to every open client,
        waits for the close to complete, then tears down the runner.
        Safe to call even if start() was never called (no-op).
        """
        if not self._started:
            return

        # Close all open WebSockets. We do this BEFORE tearing down the
        # runner so clients see a clean close frame, not a TCP reset.
        with self._connection_lock:
            all_ws = []
            for conns in self._connections.values():
                all_ws.extend(list(conns))
            self._connections.clear()

        for ws in all_ws:
            try:
                if not ws.closed:
                    await ws.close(code=1001, message=b"server shutting down")
            except Exception as e:  # pragma: no cover — best-effort close
                LOG.debug(f"error closing ws during shutdown: {e}")

        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

        self._app = None
        self._started = False
        LOG.info(f"LiveStreamServer stopped (closed {len(all_ws)} connections)")

    # ----- HTTP routes -----

    async def _handle_health(self, _request: web.Request) -> web.Response:
        return web.json_response({
            "status": "ok",
            "connections": self.connection_count,
            "host": self.host,
            "port": self.port,
        })

    async def _handle_clitool(self, request: web.Request) -> web.WebSocketResponse:
        """WebSocket route: /clitool/{workflow_id}/{step_id}.

        Auth is enforced BEFORE the WebSocket handshake completes: we
        return HTTP 403 if the api_key query param is missing/wrong.
        This is the spec §9 Q5 contract for v1.
        """
        workflow_id = request.match_info["workflow_id"]
        step_id = request.match_info["step_id"]
        provided_key = request.query.get("api_key", "")

        if not self._auth_check(provided_key):
            LOG.warning(
                f"rejected ws connect to /clitool/{workflow_id}/{step_id}: "
                f"bad api_key (provided len={len(provided_key)})"
            )
            return web.Response(status=403, text="invalid api_key")

        ws = web.WebSocketResponse(heartbeat=30.0)
        await ws.prepare(request)
        LOG.info(
            f"ws connected: /clitool/{workflow_id}/{step_id} "
            f"(connections now: {self.connection_count + 1})"
        )

        key = (workflow_id, step_id)
        with self._connection_lock:
            self._connections.setdefault(key, set()).add(ws)

        try:
            # We don't expect clients to send anything meaningful —
            # the server is a one-way push channel. But we still drain
            # incoming messages so the WebSocket stays healthy (and
            # so a misbehaving client doesn't accumulate buffer).
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    LOG.warning(f"ws connection error: {ws.exception()}")
                    break
                # PING/PONG is handled by aiohttp heartbeat. Any
                # inbound text/binary is logged and ignored.
                if msg.type in (WSMsgType.TEXT, WSMsgType.BINARY):
                    LOG.debug(
                        f"ignoring inbound ws message on "
                        f"/clitool/{workflow_id}/{step_id} (server is push-only)"
                    )
        finally:
            with self._connection_lock:
                conns = self._connections.get(key)
                if conns is not None:
                    conns.discard(ws)
                    if not conns:
                        # Clean up empty buckets so the dict doesn't grow.
                        del self._connections[key]
            try:
                if not ws.closed:
                    await ws.close()
            except Exception:  # pragma: no cover
                pass
            LOG.info(
                f"ws disconnected: /clitool/{workflow_id}/{step_id} "
                f"(connections now: {self.connection_count})"
            )
        return ws

    def _auth_check(self, provided_key: str) -> bool:
        """Validate the api_key. Empty configured key = auth disabled.

        Per spec §9 Q5: API key in query param for v1. An empty
        CONDUCTOR_API_KEY means "no auth" — this is a footgun for
        production but useful for local dev / tests. The constructor
        logs a warning when started without a key.

        Delegates to the shared `check_query_key` helper so the WS
        and JSON API surfaces enforce auth with the same logic.
        """
        return check_query_key(provided_key, self.api_key)

    # ----- Broadcasting -----

    async def subscribe_workflow(self, workflow_id: str) -> asyncio.Queue:
        """Register a queue to receive ALL events for a workflow.

        The queue receives one element per broadcast event for ANY
        step in the given workflow_id — the fan-out key is widened
        from (workflow_id, step_id) to workflow_id so a single SSE
        consumer can render the whole workflow's progress without
        subscribing to every step_id individually.

        The caller is responsible for calling ``unsubscribe_workflow``
        when done; otherwise the queue will keep receiving events
        for the lifetime of the process (memory leak).
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=1024)
        with self._listener_lock:
            self._workflow_listeners.setdefault(workflow_id, []).append(q)
        LOG.debug(
            f"subscribe_workflow({workflow_id}): now "
            f"{len(self._workflow_listeners[workflow_id])} listener(s)"
        )
        return q

    async def unsubscribe_workflow(self, workflow_id: str, queue: asyncio.Queue) -> None:
        """Remove a queue from the workflow listener set.

        Idempotent — calling twice with the same queue is a no-op.
        Empty listener lists are cleaned up so the dict doesn't grow
        indefinitely for one-off workflow ids.
        """
        with self._listener_lock:
            listeners = self._workflow_listeners.get(workflow_id)
            if not listeners:
                return
            try:
                listeners.remove(queue)
            except ValueError:
                return  # already removed — idempotent
            if not listeners:
                del self._workflow_listeners[workflow_id]
        LOG.debug(f"unsubscribe_workflow({workflow_id}): listener removed")

    @property
    def workflow_listener_count(self) -> int:
        """Total number of workflow listeners across all workflow ids.

        Useful for tests and operator visibility (``/health`` returns
        it alongside ``connection_count``).
        """
        return sum(len(qs) for qs in self._workflow_listeners.values())

    async def broadcast(self, event: StreamEvent) -> int:
        """Fan `event` out to all subscribers of its (workflow_id, step_id)
        AND to all workflow-level subscribers of its workflow_id.

        Returns the number of WebSocket clients that received the event.
        Workflow-level queue listeners are NOT counted in the return
        value (they have a different delivery shape — async queue
        push, not a socket send). Clients with a closed/congested
        socket are silently skipped (the error is logged at debug
        level). One slow client does NOT block the others — each
        send is an independent task in an asyncio.gather.
        """
        key = (event.workflow_id, event.step_id)
        with self._connection_lock:
            conns = list(self._connections.get(key, ()))

        # Workflow-level listeners (api_server SSE consumers) receive
        # every event for the workflow regardless of step_id. We do
        # this BEFORE the WebSocket fan-out so a slow listener doesn't
        # block the WebSocket path (and vice versa) — they're
        # independent delivery shapes.
        with self._listener_lock:
            listeners = list(self._workflow_listeners.get(event.workflow_id, ()))
        if listeners:
            payload = event.to_json()
            for q in listeners:
                # put_nowait so a full queue doesn't stall the engine.
                # The caller chose the maxsize; if they hit it, they
                # need a bigger queue (or a slower consumer). We log
                # and drop the event for that listener — the alternative
                # (blocking) would wedge the engine.
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    LOG.warning(
                        f"workflow listener queue full for "
                        f"workflow_id={event.workflow_id} — "
                        f"event {event.event!r} dropped for this listener"
                    )

        if not conns:
            return 0

        payload = event.to_json()
        tasks = [asyncio.create_task(ws.send_str(payload)) for ws in conns]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Count successful sends. Log (but don't raise) on per-client
        # failure — broadcast is best-effort.
        delivered = 0
        for ws, result in zip(conns, results):
            if isinstance(result, Exception):
                LOG.debug(
                    f"broadcast send failed for /clitool/{event.workflow_id}"
                    f"/{event.step_id}: {result}"
                )
            else:
                delivered += 1
        return delivered

    def broadcast_sync(self, event: StreamEvent) -> asyncio.Future:
        """Synchronous-style broadcast: schedules `broadcast(event)` on
        the running event loop and returns a Future.

        Useful from synchronous code paths (e.g. cli_tool.run_cli_tool
        called via run_in_executor) that want to push events without
        awaiting. If there's no running loop, the event is dropped
        (logged at warning level) — broadcast is best-effort by design.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            LOG.warning(
                f"broadcast_sync called with no running event loop — "
                f"dropping event {event.event!r} for "
                f"/clitool/{event.workflow_id}/{event.step_id}"
            )
            # Return a completed future so callers can `await` it
            # uniformly without raising.
            return _completed_future(0)
        return asyncio.ensure_future(self.broadcast(event))


def _completed_future(value: int) -> asyncio.Future:
    """Build an already-resolved future with the given value.

    Used by broadcast_sync when there's no running event loop — the
    caller can still `await` the returned future and get a sensible
    value (0 = nothing delivered).
    """
    fut: asyncio.Future = asyncio.Future()
    fut.set_result(value)
    return fut


# ---------------------------------------------------------------------------
# Convenience helpers (used by engine + cli_tool)
# ---------------------------------------------------------------------------

def stream_url(host: str, port: int, workflow_id: str, step_id: str) -> str:
    """Build the canonical WebSocket URL for a (workflow_id, step_id).

    Used by cli_tool.py to populate `result["stream_url"]` so the GUI
    knows where to subscribe. The URL has no api_key — the client
    appends it from its own config.
    """
    # The Conductor GUI uses ws:// (or wss:// in TLS-terminated setups);
    # the host is the bare IP/hostname (no scheme prefix on the input).
    return f"ws://{host}:{port}/clitool/{workflow_id}/{step_id}"
