#!/usr/bin/env python3
"""Janus HTTP Bridge — MCP StreamableHTTP proxy to stdio Janus process.

Runs Janus as an isolated subprocess and exposes it via HTTP/StreamableHTTP
so the Hermes gateway doesn't share process space with Janus's native modules.
If Janus heap-corrupts, it crashes alone — the gateway keeps running.

Health-check endpoint at GET /health for monitoring.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JANUS_CMD = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/janus")
JANUS_PORT = int(os.environ.get("JANUS_BRIDGE_PORT", "8011"))
JANUS_HOST = os.environ.get("JANUS_BRIDGE_HOST", "127.0.0.1")
HEALTH_LOG = os.path.expanduser("~/.hermes/logs/janus-bridge-health.log")
KEEPALIVE_INTERVAL = 10  # seconds between SSE keepalive pings
FIRST_KEEPALIVE_DELAY = 1  # seconds before first keepalive
JANUS_RESTART_DELAY = 2  # seconds to wait before restarting Janus

LOG = logging.getLogger("janus-bridge")

# ---------------------------------------------------------------------------
# Janus subprocess manager
# ---------------------------------------------------------------------------


class JanusProcess:
    """Manages Janus subprocess lifecycle with auto-restart + stderr logging."""

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.restart_count = 0
        self.last_restart = 0.0
        self._health_fails = 0
        self._stderr_buffer = asyncio.Queue(maxsize=100)

    async def start(self):
        async with self._lock:
            await self._do_start()

    async def _do_start(self):
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

        # Background reader for stderr
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        LOG.info("Janus started (PID=%d, restart_count=%d)", self._proc.pid, self.restart_count)

    async def _drain_stderr(self):
        """Read and log stderr continuously so the pipe doesn't block."""
        try:
            while self._proc and self._proc.returncode is None:
                line = await self._proc.stderr.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip()
                if text:
                    LOG.info("[janus stderr] %s", text)
                    try:
                        self._stderr_buffer.put_nowait(text)
                    except asyncio.QueueFull:
                        pass  # drop if full
        except Exception:
            pass

    async def call(self, request: dict) -> dict | None:
        """Send JSON-RPC request, read one response line from stdout.

        Thread-safe via _lock — only one coroutine talks to Janus at a time.
        """
        async with self._lock:
            if not self._proc or self._proc.returncode is not None:
                LOG.warning("Janus not running, restarting...")
                await self._do_start()

            payload = json.dumps(request, ensure_ascii=False) + "\n"
            self._proc.stdin.write(payload.encode())
            await self._proc.stdin.drain()

            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=60.0)
            if not line:
                raise ConnectionError("Janus closed stdout")
            return json.loads(line.decode())

    async def health(self) -> bool:
        """Ping Janus with an initialize request. Returns True if responsive."""
        try:
            resp = await self.call({
                "jsonrpc": "2.0", "id": "health",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "janus-bridge", "version": "1.0.0"},
                },
            })
            ok = bool(resp and resp.get("result", {}).get("serverInfo", {}).get("name") == "janus-mcp")
            if ok:
                self._health_fails = 0
            return ok
        except Exception as e:
            self._health_fails += 1
            LOG.warning("Health check failed (%d consecutive): %s", self._health_fails, e)
            return False

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc and self._proc.returncode is None else None

    @property
    def process_info(self) -> dict:
        return {
            "pid": self.pid,
            "restart_count": self.restart_count,
            "uptime_seconds": int(time.time() - self.last_restart) if self.last_restart else 0,
            "health_failures": self._health_fails,
            "alive": self._proc is not None and self._proc.returncode is None,
        }

    async def shutdown(self):
        if self._stderr_task:
            self._stderr_task.cancel()
        if self._proc and self._proc.returncode is None:
            LOG.info("Terminating Janus (PID=%d)...", self._proc.pid)
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                LOG.warning("Janus didn't terminate, killing...")
                self._proc.kill()
                await self._proc.wait()


# ---------------------------------------------------------------------------
# StreamableHTTP ASGI app
# ---------------------------------------------------------------------------


class JanusBridgeApp:
    """ASGI app: MCP StreamableHTTP proxy + health endpoint."""

    def __init__(self, janus: JanusProcess):
        self.janus = janus
        # Track SSE GET streams so we can push session updates if needed
        self._sse_clients: set[asyncio.Event] = set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return

        method = scope["method"]
        path = scope.get("path", "").rstrip("/")
        headers = dict(scope.get("headers", []))

        if path == "/health":
            await self._handle_health(send)
            return
        if path != "/mcp":
            await self._send_json(send, 404, {"error": "Not found"})
            return

        if method == "GET":
            await self._handle_get(headers, send)
        elif method == "POST":
            body = await self._read_body(receive)
            await self._handle_post(headers, body, send)
        else:
            await self._send_json(send, 405, {"error": "Method not allowed"})

    # -- helpers -----------------------------------------------------------

    @staticmethod
    async def _read_body(receive) -> bytes:
        chunks = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            else:
                break
        return b"".join(chunks)

    @staticmethod
    async def _send_raw(send, status: int, body: bytes,
                        extra_headers: dict[str, str] | None = None,
                        content_type: str = "application/json",
                        more_body: bool = False):
        h = [
            (b"content-type", content_type.encode()),
            (b"access-control-allow-origin", b"*"),
            (b"cache-control", b"no-store"),
        ]
        if not more_body and content_type == "application/json":
            h.append((b"content-length", str(len(body)).encode()))
        if extra_headers:
            for k, v in extra_headers.items():
                h.append((k.encode() if isinstance(k, str) else k,
                          v.encode() if isinstance(v, str) else v))
        await send({"type": "http.response.start", "status": status, "headers": h})
        await send({"type": "http.response.body", "body": body, "more_body": more_body})

    async def _send_json(self, send, status: int, data: dict,
                         extra_headers: dict[str, str] | None = None):
        body = json.dumps(data, ensure_ascii=False).encode()
        await self._send_raw(send, status, body, extra_headers)

    # -- GET /mcp ----------------------------------------------------------

    async def _handle_get(self, headers: dict, send):
        """GET /mcp — SSE stream for server-initiated messages."""
        accept = headers.get(b"accept", b"").decode()
        session_id = headers.get(b"mcp-session-id", b"").decode()

        if "text/event-stream" not in accept:
            # Plain GET for discovery / info
            await self._send_json(send, 200, {
                "jsonrpc": "2.0", "id": "info",
                "result": {
                    "server": "Janus MCP Bridge",
                    "transport": "streamable-http",
                    "version": "1.0.0",
                },
            })
            return

        # SSE stream — Janus doesn't push events, so we keep-alive
        priming_id = str(uuid.uuid4())
        priming_data = f"id: {priming_id}\nevent: message\ndata: \n\n".encode()

        h_list = [
            (b"content-type", b"text/event-stream"),
            (b"cache-control", b"no-cache"),
            (b"connection", b"keep-alive"),
            (b"access-control-allow-origin", b"*"),
        ]
        if session_id:
            h_list.insert(0, (b"mcp-session-id", session_id.encode()))

        await send({
            "type": "http.response.start",
            "status": 200,
            "headers": h_list,
        })

        # Send priming event as first body chunk
        await send({
            "type": "http.response.body",
            "body": priming_data,
            "more_body": True,
        })

        # Keep-alive: first ping quickly to confirm stream is alive
        try:
            await asyncio.sleep(FIRST_KEEPALIVE_DELAY)
            await send({
                "type": "http.response.body",
                "body": ": keepalive\n\n".encode(),
                "more_body": True,
            })
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                await send({
                    "type": "http.response.body",
                    "body": ": keepalive\n\n".encode(),
                    "more_body": True,
                })
        except asyncio.CancelledError:
            pass

    # -- POST /mcp ---------------------------------------------------------

    async def _handle_post(self, headers: dict, body: bytes, send):
        """POST /mcp — forward JSON-RPC to Janus, return response."""
        # Parse request
        try:
            request = json.loads(body.decode())
        except json.JSONDecodeError:
            await self._send_json(send, 400, {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": "Parse error"},
            })
            return

        is_request = request.get("id") is not None
        is_initialize = request.get("method") == "initialize"

        # Notifications: fire-and-forget (202 Accepted)
        if not is_request:
            try:
                await self.janus.call(request)
            except Exception:
                pass  # notifications are best-effort
            await self._send_raw(send, 202, b"")
            return

        # Forward to Janus
        try:
            response_data = await self.janus.call(request)
        except asyncio.TimeoutError:
            LOG.error("Janus call timed out")
            response_data = {
                "jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32000, "message": "Janus call timed out"},
            }
        except json.JSONDecodeError as e:
            LOG.error("Janus returned invalid JSON: %s", e)
            response_data = {
                "jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32000, "message": f"Invalid JSON from Janus: {e}"},
            }
        except ConnectionError as e:
            LOG.error("Janus connection lost: %s", e)
            # Restart Janus
            asyncio.create_task(self._restart_janus())
            response_data = {
                "jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32000, "message": "Janus process died"},
            }
        except Exception as e:
            LOG.error("Janus call failed: %s", type(e).__name__, exc_info=True)
            response_data = {
                "jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32000, "message": f"Janus error: {e}"},
            }

        if response_data is None:
            response_data = {
                "jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32003, "message": "Janus returned empty response"},
            }

        # Build response headers
        extra_headers: dict[str, str] = {}

        # Session management for initialize
        if is_initialize and response_data.get("result"):
            session_id = str(uuid.uuid4())
            extra_headers["mcp-session-id"] = session_id
            extra_headers["mcp-protocol-version"] = "2024-11-05"

        await self._send_json(send, 200, response_data, extra_headers)

    async def _restart_janus(self):
        """Restart Janus after a brief delay (fire-and-forget)."""
        await asyncio.sleep(JANUS_RESTART_DELAY)
        try:
            await self.janus.start()
        except Exception as e:
            LOG.error("Failed to restart Janus: %s", e)

    # -- GET /health -------------------------------------------------------

    async def _handle_health(self, send):
        """Health check endpoint for monitoring."""
        ok = await self.janus.health()
        info = self.janus.process_info
        info["healthy"] = ok
        info["service"] = "janus-mcp-bridge"
        status = 200 if ok else 503

        # Log health outcome
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(HEALTH_LOG, "a") as f:
            f.write(f"{ts} status={status} pid={info['pid']} restarts={info['restart_count']} "
                    f"uptime={info['uptime_seconds']}s failures={info['health_failures']}\n")

        await self._send_json(send, status, info)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    LOG.info("=" * 60)
    LOG.info("Janus MCP Bridge starting...")
    LOG.info("Janus command: %s", JANUS_CMD)
    LOG.info("Listen: %s:%s", JANUS_HOST, JANUS_PORT)
    LOG.info("Health log: %s", HEALTH_LOG)
    LOG.info("=" * 60)

    janus = JanusProcess()
    await janus.start()

    app = JanusBridgeApp(janus)

    # Wake up Janus quickly to verify it's alive
    for attempt in range(5):
        if await janus.health():
            LOG.info("Janus responded to health check on attempt %d", attempt + 1)
            break
        LOG.warning("Waiting for Janus to start (attempt %d/5)...", attempt + 1)
        await asyncio.sleep(1)
    else:
        LOG.error("Janus failed to respond after 5 attempts — bridge will still start")

    import uvicorn
    config = uvicorn.Config(
        app,
        host=JANUS_HOST,
        port=JANUS_PORT,
        log_level="info",
        lifespan="off",
    )
    server = uvicorn.Server(config)

    # Signal handling for clean shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler():
        if not shutdown_event.is_set():
            LOG.info("Signal received, shutting down...")
            shutdown_event.set()
            server.should_exit = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows doesn't support add_signal_handler

    await server.serve()

    # Cleanup
    LOG.info("Bridge shutting down...")
    await janus.shutdown()
    LOG.info("Bridge stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
