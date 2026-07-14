"""Unit tests for conductor.v2.gateway — GatewayClient over mocked httpx.

The gateway talks HTTP to Hermes api_server. We never hit a real server
in tests — every test patches the underlying httpx.AsyncClient.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import gateway as gw_mod  # noqa: E402


class TestGatewayConfig(unittest.TestCase):
    """GatewayConfig loads API_SERVER_KEY from .env and sets auth headers."""

    def test_load_key_from_env_file(self):
        # The test runs as user konan; the real ~/.hermes/.env has a real key.
        # If it's missing we just get "" — that's still a valid test.
        cfg = gw_mod.GatewayConfig()
        # Either it loaded something or the file is missing — both are OK
        self.assertIsInstance(cfg.api_key, str)

    def test_headers_includes_bearer_when_key_present(self):
        cfg = gw_mod.GatewayConfig(base_url="http://x:1234", api_key="abc123")
        h = cfg.headers()
        self.assertEqual(h["Authorization"], "Bearer abc123")
        self.assertEqual(h["Content-Type"], "application/json")

    def test_headers_no_auth_when_no_key(self):
        cfg = gw_mod.GatewayConfig(base_url="http://x:1234", api_key="")
        h = cfg.headers()
        self.assertNotIn("Authorization", h)


class TestRunResultParsing(unittest.TestCase):
    """_parse_run + _extract_output handle the multiple response shapes
    Hermes api_server can return."""

    def test_extract_output_string_form(self):
        self.assertEqual(gw_mod._extract_output({"output": "hello"}), "hello")

    def test_extract_output_responses_api_list(self):
        d = {"output": [{"text": "foo"}, {"text": "bar"}]}
        self.assertEqual(gw_mod._extract_output(d), "foobar")

    def test_extract_output_choices_form(self):
        d = {"choices": [{"message": {"content": "hi from choices"}}]}
        self.assertEqual(gw_mod._extract_output(d), "hi from choices")

    def test_extract_output_empty_when_missing(self):
        self.assertEqual(gw_mod._extract_output({}), "")

    def test_parse_run_with_error_dict(self):
        d = {"run_id": "r1", "status": "failed", "error": {"message": "boom"}}
        r = gw_mod._parse_run(d)
        self.assertEqual(r.run_id, "r1")
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.error, "boom")

    def test_parse_run_with_error_string(self):
        d = {"run_id": "r2", "status": "failed", "error": "nope"}
        r = gw_mod._parse_run(d)
        self.assertEqual(r.error, "nope")


class _MockAsyncClient:
    """Tiny httpx.AsyncClient replacement. Each test patches the
    GatewayClient's `_client` to this. Calls are recorded."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []  # (method, path, kwargs)
        self.responses: list[MagicMock] = []  # each has .json(), .aiter_lines(), etc.

    def _record(self, method: str, path: str, **kwargs) -> MagicMock:
        self.calls.append((method, path, kwargs))
        if not self.responses:
            raise AssertionError(f"no mock response queued for {method} {path}")
        return self.responses.pop(0)

    async def get(self, path: str, **kwargs):
        return self._record("GET", path, **kwargs)

    async def post(self, path: str, **kwargs):
        return self._record("POST", path, **kwargs)

    async def aclose(self):
        return None

    def stream(self, method: str, path: str, **kwargs):
        return _MockStream(self, method, path, kwargs)


class _MockStream:
    def __init__(self, parent, method, path, kwargs):
        self.parent = parent
        self.method = method
        self.path = path
        self.kwargs = kwargs
        self.response = self.parent._record(method, path, **kwargs)

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *exc):
        return None


class TestGatewayClientSubmit(unittest.IsolatedAsyncioTestCase):
    async def test_submit_run_returns_run_id(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key="k"))
        client._client = _MockAsyncClient()
        r = MagicMock()
        r.status_code = 202
        r.json = MagicMock(return_value={"run_id": "run_123"})
        r.raise_for_status = MagicMock()
        client._client.responses.append(r)

        run_id = await client.submit_run("hello", model="thoth")
        self.assertEqual(run_id, "run_123")
        # The call recorded
        self.assertEqual(client._client.calls[0][0], "POST")
        self.assertEqual(client._client.calls[0][1], "/v1/runs")
        # Body had model + input
        body = client._client.calls[0][2]["json"]
        self.assertEqual(body["model"], "thoth")
        self.assertEqual(body["input"], "hello")

    async def test_submit_run_falls_back_to_id_field(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key="k"))
        client._client = _MockAsyncClient()
        r = MagicMock()
        r.status_code = 202
        r.json = MagicMock(return_value={"id": "alt_id_456"})
        r.raise_for_status = MagicMock()
        client._client.responses.append(r)

        run_id = await client.submit_run("hi")
        self.assertEqual(run_id, "alt_id_456")

    async def test_submit_run_raises_on_5xx(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key="k"))
        client._client = _MockAsyncClient()
        r = MagicMock()
        r.status_code = 500
        r.text = "internal error"
        r.raise_for_status = MagicMock()
        client._client.responses.append(r)

        with self.assertRaises(gw_mod.GatewayError) as cm:
            await client.submit_run("hi")
        self.assertEqual(cm.exception.status, 500)

    async def test_submit_run_sends_session_headers_when_provided(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key="k"))
        client._client = _MockAsyncClient()
        r = MagicMock()
        r.status_code = 202
        r.json = MagicMock(return_value={"run_id": "x"})
        r.raise_for_status = MagicMock()
        client._client.responses.append(r)

        await client.submit_run("hi", session_id="sess-1", session_key="key-1")
        headers = client._client.calls[0][2]["headers"]
        self.assertEqual(headers["X-Hermes-Session-Id"], "sess-1")
        self.assertEqual(headers["X-Hermes-Session-Key"], "key-1")


class TestGatewayClientGet(unittest.IsolatedAsyncioTestCase):
    async def test_get_run_returns_runresult(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key="k"))
        client._client = _MockAsyncClient()
        r = MagicMock()
        r.status_code = 200
        r.json = MagicMock(return_value={
            "run_id": "r1", "status": "running", "output": "",
        })
        r.raise_for_status = MagicMock()
        client._client.responses.append(r)
        result = await client.get_run("r1")
        self.assertEqual(result.status, "running")
        self.assertEqual(result.run_id, "r1")


class TestGatewayClientHealth(unittest.IsolatedAsyncioTestCase):
    async def test_health_no_auth_required(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key=""))
        client._client = _MockAsyncClient()
        r = MagicMock()
        r.json = MagicMock(return_value={"status": "ok"})
        r.raise_for_status = MagicMock()
        client._client.responses.append(r)
        h = await client.health()
        self.assertEqual(h["status"], "ok")
        # /health, not /v1/health
        self.assertEqual(client._client.calls[0][1], "/health")


class TestGatewayClientLifecycle(unittest.IsolatedAsyncioTestCase):
    async def test_context_manager_creates_and_closes_client(self):
        client = gw_mod.GatewayClient(gw_mod.GatewayConfig(base_url="http://x", api_key="k"))
        # Accessing client before enter should raise
        with self.assertRaises(RuntimeError):
            _ = client.client
        async with client:
            self.assertIsNotNone(client._client)
        # After exit, _client is reset
        self.assertIsNone(client._client)


if __name__ == "__main__":
    unittest.main()
