#!/usr/bin/env python3
"""Janus HTTP Bridge v3 — Starlette + sse-starlette for proper SSE.

Janus runs as an isolated stdio subprocess. The bridge proxies JSON-RPC
messages between HTTP (StreamableHTTP) and Janus (stdio). Uses Starlette
for clean HTTP routing and sse-starlette for spec-compliant SSE.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from sse_starlette.sse import EventSourceResponse

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JANUS_CMD = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/janus")
JANUS_PORT = int(os.environ.get("JANUS_BRIDGE_PORT", "8011"))
JANUS_HOST = os.environ.get("JANUS_BRIDGE_HOST", "127.0.0.1")
HEALTH_LOG = os.path.expanduser("~/.hermes/logs/janus-bridge-health.log")

LOG = logging.getLogger("janus-bridge")

# ---------------------------------------------------------------------------
# Janus subprocess manager
# ---------------------------------------------------------------------------


class JanusProcess:
    """Manages Janus subprocess — one request at a time via lock."""

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.restart_count = 0
        self.last_restart = 0.0
        self._health_fails = 0

    async def start(self):
        async with self._lock:
            await self._start_nolock()

    async def _start_nolock(self):
        if self._proc and self._proc.returncode is None:
            return
        LOG.info("Starting Janus subprocess...")
        self._proc = await asyncio.create_subprocess_exec(
            JANUS_CMD, "serve",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.restart_count += 1
        self.last_restart = time.time()
        self._health_fails = 0
        asyncio.create_task(self._drain_stderr())
        LOG.info("Janus started (PID=%d, restart=%d)", self._proc.pid, self.restart_count)

    async def _drain_stderr(self):
        try:
            while self._proc and self._proc.returncode is None:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text:
                    LOG.info("[janus] %s", text)
        except Exception:
            pass

    async def call(self, request: dict) -> dict | None:
        """Send JSON-RPC, read one response. Serialized via _lock."""
        async with self._lock:
            if not self._proc or self._proc.returncode is not None:
                LOG.warning("Janus not running, restarting...")
                await self._start_nolock()
            payload = json.dumps(request, ensure_ascii=False) + "\n"
            self._proc.stdin.write(payload.encode())
            await self._proc.stdin.drain()
            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=60.0)
            if not line:
                raise ConnectionError("Janus closed stdout")
            return json.loads(line.decode())

    async def health(self) -> bool:
        """Check Janus is alive."""
        try:
            async with self._lock:
                if not self._proc or self._proc.returncode is not None:
                    return False
                payload = json.dumps({
                    "jsonrpc": "2.0", "id": "health",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "janus-bridge", "version": "3.0.0"},
                    },
                }) + "\n"
                self._proc.stdin.write(payload.encode())
                await self._proc.stdin.drain()
                line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=10.0)
                if not line:
                    return False
                resp = json.loads(line.decode())
                ok = resp.get("result", {}).get("serverInfo", {}).get("name") == "janus-mcp"
                if ok:
                    self._health_fails = 0
                return bool(ok)
        except Exception as e:
            self._health_fails += 1
            LOG.debug("Health check failed: %s", e)
            return False

    @property
    def info(self) -> dict:
        return {
            "pid": self._proc.pid if self._proc and self._proc.returncode is None else None,
            "restart_count": self.restart_count,
            "uptime_seconds": int(time.time() - self.last_restart) if self.last_restart else 0,
            "health_failures": self._health_fails,
            "alive": self._proc is not None and self._proc.returncode is None,
            "service": "janus-mcp-bridge",
        }

    async def shutdown(self):
        if self._proc and self._proc.returncode is None:
            LOG.info("Terminating Janus (PID=%d)...", self._proc.pid)
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()

    async def cleanup_children(self):
        """Kill any stray npm/node children left by Janus."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pkill", "-f", "npm exec", signal=sig
                )
                await proc.wait()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_janus: JanusProcess | None = None


async def get_janus() -> JanusProcess:
    global _janus
    assert _janus is not None
    return _janus


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


async def handle_health(request: Request) -> JSONResponse:
    """GET /health — monitoring endpoint."""
    janus = await get_janus()
    ok = await janus.health()
    info = janus.info
    info["healthy"] = ok

    # Log health
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(HEALTH_LOG, "a") as f:
        f.write(f"{ts} status={200 if ok else 503} pid={info['pid']} "
                f"restarts={info['restart_count']} uptime={info['uptime_seconds']}s "
                f"failures={info['health_failures']}\n")

    status_code = 200 if ok else 503
    return JSONResponse(info, status_code=status_code)


async def handle_mcp(request: Request) -> Response:
    """POST /mcp — forward JSON-RPC to Janus.
    GET /mcp — SSE stream for server-initiated messages (keep-alive).
    """
    janus = await get_janus()

    if request.method == "POST":
        return await handle_post(janus, request)
    elif request.method == "GET":
        return await handle_get(janus, request)
    return JSONResponse({"error": "Method not allowed"}, status_code=405)


async def handle_post(janus: JanusProcess, request: Request) -> Response:
    """Handle POST /mcp — forward JSON-RPC to Janus."""
    try:
        body = await request.body()
        req_data = json.loads(body)
    except json.JSONDecodeError:
        return JSONResponse(
            {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
            status_code=400,
        )

    is_request = req_data.get("id") is not None
    is_initialize = req_data.get("method") == "initialize"

    # Notifications: 202 Accepted
    if not is_request:
        try:
            await janus.call(req_data)
        except Exception:
            pass
        return Response(status_code=202)

    # Requests: forward to Janus
    try:
        resp_data = await janus.call(req_data)
    except asyncio.TimeoutError:
        resp_data = {
            "jsonrpc": "2.0", "id": req_data.get("id"),
            "error": {"code": -32000, "message": "Janus call timed out"},
        }
    except ConnectionError as e:
        asyncio.create_task(restart_janus(janus))
        resp_data = {
            "jsonrpc": "2.0", "id": req_data.get("id"),
            "error": {"code": -32000, "message": f"Janus connection lost: {e}"},
        }
    except Exception as e:
        LOG.error("Janus call failed: %s", e, exc_info=True)
        resp_data = {
            "jsonrpc": "2.0", "id": req_data.get("id"),
            "error": {"code": -32000, "message": f"Janus error: {e}"},
        }

    if resp_data is None:
        resp_data = {
            "jsonrpc": "2.0", "id": req_data.get("id"),
            "error": {"code": -32003, "message": "Empty response from Janus"},
        }

    headers = {}
    if is_initialize and resp_data.get("result"):
        headers["mcp-session-id"] = str(uuid.uuid4())
        headers["mcp-protocol-version"] = "2024-11-05"

    return JSONResponse(resp_data, headers=headers)


async def handle_get(janus: JanusProcess, request: Request) -> Response:
    """Handle GET /mcp — SSE keepalive stream for MCP client."""
    accept = request.headers.get("accept", "")
    session_id = request.headers.get("mcp-session-id", "")

    if "text/event-stream" not in accept:
        return JSONResponse({
            "jsonrpc": "2.0", "id": "info",
            "result": {
                "server": "Janus MCP Bridge v3",
                "transport": "streamable-http",
                "version": "3.0.0",
            },
        })

    # Proper SSE stream with sse-starlette
    priming_id = str(uuid.uuid4())

    async def event_generator():
        # Priming event
        yield {"id": priming_id, "event": "message", "data": ""}
        # First keepalive quickly
        await asyncio.sleep(1)
        while True:
            yield {"event": "keepalive", "data": ""}
            await asyncio.sleep(10)

    headers = {}
    if session_id:
        headers["mcp-session-id"] = session_id

    return EventSourceResponse(event_generator(), headers=headers)


async def restart_janus(janus: JanusProcess):
    """Fire-and-forget Janus restart."""
    await asyncio.sleep(2)
    try:
        await janus.start()
    except Exception as e:
        LOG.error("Failed to restart Janus: %s", e)


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

def create_app(janus: JanusProcess) -> Starlette:
    global _janus
    _janus = janus
    routes = [
        Route("/health", endpoint=handle_health),
        Route("/mcp", endpoint=handle_mcp, methods=["GET", "POST"]),
    ]
    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    LOG.info("=" * 60)
    LOG.info("Janus MCP Bridge v3 starting...")
    LOG.info("Janus: %s", JANUS_CMD)
    LOG.info("Listen: %s:%s", JANUS_HOST, JANUS_PORT)
    LOG.info("=" * 60)

    janus = JanusProcess()

    async def _start():
        await janus.start()

        # Verify Janus is alive
        for attempt in range(5):
            if await janus.health():
                LOG.info("Janus healthy (attempt %d/5)", attempt + 1)
                break
            LOG.warning("Waiting for Janus (attempt %d/5)...", attempt + 1)
            await asyncio.sleep(1)
        else:
            LOG.warning("Janus not healthy yet — bridge will still start")

        app = create_app(janus)

        import uvicorn
        config = uvicorn.Config(
            app,
            host=JANUS_HOST,
            port=JANUS_PORT,
            log_level="info",
            lifespan="on",
        )
        server = uvicorn.Server(config)

        # Signal handling
        loop = asyncio.get_running_loop()
        shutdown_event = asyncio.Event()

        def _sig():
            if not shutdown_event.is_set():
                LOG.info("Shutting down...")
                shutdown_event.set()
                server.should_exit = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _sig)
            except NotImplementedError:
                pass

        await server.serve()
        await janus.shutdown()
        LOG.info("Bridge stopped.")

    try:
        asyncio.run(_start())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
