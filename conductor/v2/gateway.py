"""Conductor v2 gateway client — talks to Hermes api_server over HTTP.

Spec section 3.5 / Layer 3: Conductor dispatches god work by POSTing to
gateway's /v1/runs endpoint and polling /v1/runs/{run_id} for results.

Decoupling contract (locked decision, see DECISIONS.md 2026-06-14):
    ZERO imports from hermes-agent/. All interaction is HTTP.
    Conductor survives any Hermes Agent upstream refactor.

Endpoints used (verified live on Thoth's gateway, port 8642):
    POST /v1/runs                  start async run, returns 202 + run_id
    GET  /v1/runs/{run_id}         poll status, returns output when completed
    GET  /v1/runs/{run_id}/events  SSE stream of structured lifecycle events
    POST /v1/runs/{run_id}/stop    interrupt a running agent
    GET  /health                   health check (no auth)

Auth: Bearer token in Authorization header, sourced from ~/.hermes/.env
API_SERVER_KEY (or override via CONDUCTOR_GATEWAY_KEY env var).

Default gateway URL: http://127.0.0.1:8642 (Thoth profile is the dispatcher;
other profiles can be targeted per-call by passing url= param).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx

LOG = logging.getLogger("conductor.v2.gateway")

DEFAULT_BASE_URL = os.environ.get("CONDUCTOR_GATEWAY_URL", "http://127.0.0.1:8642")
DEFAULT_KEY_PATH = Path(os.environ.get("CONDUCTOR_GATEWAY_KEY_PATH", Path.home() / ".hermes" / ".env"))
DEFAULT_POLL_INTERVAL = float(os.environ.get("CONDUCTOR_POLL_INTERVAL", "2.0"))
DEFAULT_RUN_TIMEOUT = float(os.environ.get("CONDUCTOR_RUN_TIMEOUT", "1800"))  # 30m
DEFAULT_MODEL = os.environ.get("CONDUCTOR_MODEL", "thoth")  # Thoth is default dispatcher


def _load_key(path: Path = DEFAULT_KEY_PATH) -> str:
    """Load API_SERVER_KEY from a .env file."""
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("API_SERVER_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


@dataclass
class GatewayConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = field(default_factory=_load_key)
    poll_interval: float = DEFAULT_POLL_INTERVAL
    run_timeout: float = DEFAULT_RUN_TIMEOUT
    default_model: str = DEFAULT_MODEL
    timeout: float = 300.0  # per-request HTTP timeout

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h


@dataclass
class RunResult:
    run_id: str
    status: str  # started | queued | running | completed | failed | cancelled | requires_action
    output: str = ""
    model: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    error: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)
    elapsed: float = 0.0


class GatewayClient:
    """Async HTTP client for the Hermes api_server.

    Conductor calls this from the engine/DAG executor to spawn god sessions
    and collect their output. Stateless across calls — safe to share.
    """

    def __init__(self, config: Optional[GatewayConfig] = None):
        self.config = config or GatewayConfig()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GatewayClient":
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            headers=self.config.headers(),
            timeout=self.config.timeout,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GatewayClient must be used as async context manager")
        return self._client

    async def health(self) -> dict[str, Any]:
        """GET /health — no auth required."""
        r = await self.client.get("/health")
        r.raise_for_status()
        return r.json()

    async def capabilities(self) -> dict[str, Any]:
        """GET /v1/capabilities — server-side capability discovery."""
        r = await self.client.get("/v1/capabilities")
        r.raise_for_status()
        return r.json()

    async def submit_run(
        self,
        input_text: str,
        *,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        session_key: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> str:
        """POST /v1/runs — start an async run, return run_id.

        Args:
            input_text: The user-message / handoff text for the god.
            model: God profile to dispatch to. Default: thoth.
                   (Conductor uses different profiles by god name; this
                   default is for handoffs routed to thoth.)
            session_id: Optional X-Hermes-Session-Id header for continuity.
            session_key: Optional X-Hermes-Session-Key for memory scoping.
            extra: Additional fields merged into the request body.

        Returns:
            run_id (str) — poll with get_run() or stream_run_events().
        """
        body: dict[str, Any] = {
            "model": model or self.config.default_model,
            "input": input_text,
        }
        if extra:
            body.update(extra)

        headers: dict[str, str] = {}
        if session_id:
            headers["X-Hermes-Session-Id"] = session_id
        if session_key:
            headers["X-Hermes-Session-Key"] = session_key

        r = await self.client.post("/v1/runs", json=body, headers=headers)
        if r.status_code != 200 and r.status_code != 202:
            raise GatewayError(
                f"submit_run failed: {r.status_code} {r.text[:500]}", status=r.status_code
            )
        data = r.json()
        run_id = data.get("run_id") or data.get("id")
        if not run_id:
            raise GatewayError(f"submit_run returned no run_id: {data}")
        LOG.info(f"submit_run ok: run_id={run_id} model={body['model']}")
        return run_id

    async def get_run(self, run_id: str) -> RunResult:
        """GET /v1/runs/{run_id} — fetch current status (one-shot poll)."""
        r = await self.client.get(f"/v1/runs/{run_id}")
        if r.status_code == 404:
            raise GatewayError(f"run_id not found: {run_id}", status=404)
        r.raise_for_status()
        d = r.json()
        return _parse_run(d)

    async def wait_for_run(
        self, run_id: str, *, timeout: Optional[float] = None, poll_interval: Optional[float] = None
    ) -> RunResult:
        """Poll /v1/runs/{run_id} until terminal state or timeout.

        Returns RunResult with status in {completed, failed, cancelled,
        requires_action}. Raises asyncio.TimeoutError on timeout.
        """
        timeout = timeout or self.config.run_timeout
        poll = poll_interval or self.config.poll_interval
        start = time.monotonic()
        terminal = {"completed", "failed", "cancelled", "requires_action"}
        while True:
            result = await self.get_run(run_id)
            if result.status in terminal:
                result.elapsed = time.monotonic() - start
                LOG.info(
                    f"wait_for_run done: run_id={run_id} status={result.status} "
                    f"elapsed={result.elapsed:.1f}s output_len={len(result.output)}"
                )
                return result
            if time.monotonic() - start > timeout:
                raise asyncio.TimeoutError(
                    f"run {run_id} did not finish within {timeout}s "
                    f"(last status={result.status})"
                )
            await asyncio.sleep(poll)

    async def stream_run_events(
        self, run_id: str
    ) -> AsyncIterator[dict[str, Any]]:
        """GET /v1/runs/{run_id}/events — SSE event stream.

        Yields parsed event dicts. Caller is responsible for breaking out
        when status event arrives.
        """
        async with self.client.stream("GET", f"/v1/runs/{run_id}/events") as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    yield json.loads(payload)
                except json.JSONDecodeError:
                    LOG.warning(f"stream_run_events: bad JSON: {payload[:200]}")

    async def stop_run(self, run_id: str) -> dict[str, Any]:
        """POST /v1/runs/{run_id}/stop — interrupt a running agent."""
        r = await self.client.post(f"/v1/runs/{run_id}/stop")
        r.raise_for_status()
        return r.json()


class GatewayError(RuntimeError):
    """Raised on non-2xx gateway responses."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _parse_run(d: dict[str, Any]) -> RunResult:
    return RunResult(
        run_id=d.get("run_id") or d.get("id", ""),
        status=d.get("status", "unknown"),
        output=_extract_output(d),
        model=d.get("model", ""),
        usage=d.get("usage", {}) or {},
        session_id=d.get("session_id", ""),
        error=(d.get("error") or {}).get("message") if isinstance(d.get("error"), dict) else d.get("error"),
        raw=d,
    )


def _extract_output(d: dict[str, Any]) -> str:
    """Pull text output from a /v1/runs response in any of the shapes the
    server might return (Responses API style, Chat Completions style, or
    the simpler Conductor-friendly shape)."""
    if "output" in d and isinstance(d["output"], str):
        return d["output"]
    if "output" in d and isinstance(d["output"], list):
        parts = []
        for item in d["output"]:
            if isinstance(item, dict):
                if "text" in item:
                    parts.append(item["text"])
                elif "content" in item:
                    parts.append(str(item["content"]))
        return "".join(parts)
    if "choices" in d and isinstance(d["choices"], list) and d["choices"]:
        msg = d["choices"][0].get("message", {})
        return msg.get("content", "")
    return ""


# ---------------------------------------------------------------------------
# CLI smoke test: `python3 -m conductor.v2.gateway` → health + ping run
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _smoke() -> int:
        cfg = GatewayConfig()
        if not cfg.api_key:
            print(f"ERROR: no API_SERVER_KEY in {DEFAULT_KEY_PATH}", file=sys.stderr)
            return 2
        print(f"gateway={cfg.base_url} key=...{cfg.api_key[-6:]}")
        async with GatewayClient(cfg) as gw:
            h = await gw.health()
            print(f"health: {h}")
            run_id = await gw.submit_run("Reply with the single word: PONG")
            print(f"submitted: {run_id}")
            result = await gw.wait_for_run(run_id, timeout=60)
            print(f"status={result.status} output={result.output!r} elapsed={result.elapsed:.1f}s")
            return 0 if result.status == "completed" else 1

    sys.exit(asyncio.run(_smoke()))
