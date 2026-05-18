#!/usr/bin/env python3
"""Janus HTTP Bridge v2 — uses FastMCP for proper StreamableHTTP.

Janus runs as an isolated stdio subprocess. The bridge proxies JSON-RPC
messages between FastMCP (HTTP) and Janus (stdio). FastMCP handles all
SSE/StreamableHTTP protocol details correctly, so no custom SSE code needed.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time

from mcp.server.fastmcp import FastMCP

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JANUS_CMD = os.path.expanduser("~/.hermes/hermes-agent/venv/bin/janus")
JANUS_PORT = int(os.environ.get("JANUS_BRIDGE_PORT", "8011"))
JANUS_HOST = os.environ.get("JANUS_BRIDGE_HOST", "127.0.0.1")
HEALTH_LOG = os.path.expanduser("~/.hermes/logs/janus-bridge-health.log")

LOG = logging.getLogger("janus-bridge")

# ---------------------------------------------------------------------------
# Janus subprocess manager (shared state)
# ---------------------------------------------------------------------------


class JanusProcess:
    """Manages Janus subprocess — one request at a time via lock."""

    def __init__(self):
        self._proc: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self.restart_count = 0
        self.last_restart = 0.0
        self._health_fails = 0
        self._ready = False

    async def start(self):
        async with self._lock:
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
            self._ready = False
            # Start stderr drainer
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
        """Send JSON-RPC, read one response. Lock ensures serial access."""
        async with self._lock:
            if not self._proc or self._proc.returncode is not None:
                LOG.warning("Janus not running, restarting...")
                await self._do_start_nolock()

            payload = json.dumps(request, ensure_ascii=False) + "\n"
            self._proc.stdin.write(payload.encode())
            await self._proc.stdin.drain()

            line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=60.0)
            if not line:
                raise ConnectionError("Janus closed stdout")
            return json.loads(line.decode())

    async def _do_start_nolock(self):
        """Start without acquiring lock (caller must hold it)."""
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
        self._ready = False
        asyncio.create_task(self._drain_stderr())
        LOG.info("Janus started (PID=%d, restart=%d)", self._proc.pid, self.restart_count)

    async def health(self) -> bool:
        """Check Janus is alive and responsive."""
        try:
            # Don't use call() here to avoid deadlock with _lock
            # Instead, use the process directly
            async with self._lock:
                if not self._proc or self._proc.returncode is not None:
                    return False
                payload = json.dumps({
                    "jsonrpc": "2.0", "id": "health",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "janus-bridge", "version": "2.0.0"},
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
                    self._ready = True
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
            "ready": self._ready,
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


# ---------------------------------------------------------------------------
# FastMCP server — proxies all tool calls to Janus
# ---------------------------------------------------------------------------

# Global Janus instance
_janus: JanusProcess | None = None


def _get_janus() -> JanusProcess:
    global _janus
    assert _janus is not None
    return _janus


def _init_mcp() -> FastMCP:
    """Create FastMCP server with dynamic tool handlers proxied to Janus."""
    mcp = FastMCP(
        "janus-mcp-bridge",
        instructions="Proxy server for Janus MCP aggregator.",
    )

    # We'll register tools dynamically after discovering them from Janus.
    # FastMCP doesn't support dynamic tool registration after startup in all
    # versions, so we use a catch-all approach: a single tool with a dynamic
    # name pattern using the MCP server's capabilities.

    # Actually, the simplest approach: register tools by proxying each call.
    # Since tools are discovered from Janus at startup, we register them
    # via FastMCP's tool decorator pattern but with generic handler.

    # Instead, we use FastMCP's low-level hooks. We override the
    # tool call handler to proxy to Janus.

    # The simplest correct approach: register a custom tool list handler
    # and tool call handler via the underlying Server object.
    server = mcp._mcp_server  # access the low-level Server

    original_request_handlers = server.request_handlers

    async def proxy_handler(request: dict) -> dict:
        """Handle any MCP request by proxying to Janus."""
        janus = _get_janus()
        method = request.get("method", "")

        # For tools/list, fetch from Janus
        if method == "tools/list":
            try:
                resp = await janus.call({
                    "jsonrpc": "2.0", "id": "janus-list",
                    "method": "tools/list",
                    "params": {},
                })
                if resp and "result" in resp:
                    return resp
            except Exception as e:
                LOG.error("Failed to list tools from Janus: %s", e)
                return {"tools": []}
            return {"tools": []}

        # For all other methods, proxy to Janus
        try:
            resp = await janus.call(request)
            if resp is not None:
                return resp
        except Exception as e:
            LOG.error("Proxy call failed: %s", e)
            return {"error": {"code": -32000, "message": str(e)}}

        return {"error": {"code": -32003, "message": "Empty response from Janus"}}

    # Remove old handler, set new one
    server.request_handler = proxy_handler

    return mcp


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    LOG.info("=" * 60)
    LOG.info("Janus MCP Bridge v2 starting...")
    LOG.info("Janus: %s", JANUS_CMD)
    LOG.info("Listen: %s:%s", JANUS_HOST, JANUS_PORT)
    LOG.info("=" * 60)

    global _janus

    async def _start():
        global _janus
        janus = JanusProcess()
        _janus = janus
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

        mcp = _init_mcp()
        starlette_app = mcp.streamable_http_app()

        import uvicorn

        # Graceful GET /mcp handler (same as Pantheon MCP server pattern)
        async def graceful_app(scope, receive, send):
            if scope["type"] == "http" and scope["method"] == "GET":
                path = scope.get("path", "")
                if path.rstrip("/") == "/mcp":
                    accept_hdr = b""
                    for k, v in scope.get("headers", []):
                        if k.lower() == b"accept":
                            accept_hdr = v
                            break
                    if b"text/event-stream" not in accept_hdr:
                        body = json.dumps({
                            "jsonrpc": "2.0", "id": "info",
                            "result": {
                                "server": "Janus MCP Bridge v2",
                                "transport": "streamable-http",
                                "message": "POST JSON-RPC or GET with Accept: text/event-stream",
                            },
                        }).encode()
                        await send({
                            "type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(body)).encode()),
                                (b"access-control-allow-origin", b"*"),
                            ],
                        })
                        await send({"type": "http.response.body", "body": body})
                        return
                    if path.rstrip("/") == "/health":
                        info_body = json.dumps(janus.info).encode()
                        await send({
                            "type": "http.response.start",
                            "status": 200,
                            "headers": [
                                (b"content-type", b"application/json"),
                                (b"content-length", str(len(info_body)).encode()),
                            ],
                        })
                        await send({"type": "http.response.body", "body": info_body})
                        return
            await starlette_app(scope, receive, send)

        config = uvicorn.Config(
            graceful_app,
            host=JANUS_HOST,
            port=JANUS_PORT,
            log_level="info",
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
