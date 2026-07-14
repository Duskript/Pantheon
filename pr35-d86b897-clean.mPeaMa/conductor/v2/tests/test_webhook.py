"""Unit tests for conductor.v2.webhook — FastAPI app + endpoints.

Drives the FastAPI app via TestClient (sync) against a tmp pending dir.
No real HTTP server is started. Each test gets a fresh tmp so writes
don't leak between cases.

Endpoints under test (per spec section 6 Layer 5):
  - GET  /health                  liveness + inbox path
  - POST /webhook/{source:path}   generic webhook catch-all (external)
  - POST /dispatch                pre-formed event envelopes (Talon/internals)
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import webhook  # noqa: E402


class TestWebhookApp(unittest.TestCase):
    """Drive the FastAPI app via TestClient. Each test gets a fresh
    tmp pending dir so writes don't leak."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.app = webhook.make_app(pending_dir=self.tmp.pending_dir)
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    # ----- /health -----

    def test_health_returns_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("pending_inbox", body)
        self.assertTrue(body["pending_inbox"].endswith("_webhooks"))

    # ----- /webhook/{source} -----

    def test_webhook_writes_event_envelope(self):
        r = self.client.post(
            "/webhook/github",
            json={"action": "opened", "issue": {"number": 42}},
        )
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertEqual(body["status"], "accepted")
        self.assertIn("queued_as", body)
        # File should exist in _webhooks/
        queued = body["queued_as"]
        fpath = self.tmp.webhooks_dir / queued
        self.assertTrue(fpath.exists(), f"file not written: {fpath}")
        # Verify envelope shape — every field the engine needs to route
        env = json.loads(fpath.read_text())
        self.assertEqual(env["type"], "webhook")
        self.assertEqual(env["source"], "github")
        self.assertTrue(env["is_external"])
        self.assertEqual(env["payload"]["action"], "opened")
        self.assertEqual(env["payload"]["issue"]["number"], 42)

    def test_webhook_handles_non_json_body(self):
        r = self.client.post(
            "/webhook/legacy",
            content=b"not json at all",
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(r.status_code, 202)
        queued = r.json()["queued_as"]
        env = json.loads((self.tmp.webhooks_dir / queued).read_text())
        # Non-JSON bodies are wrapped in _raw so the engine can still read them
        self.assertIn("_raw", env["payload"])
        self.assertEqual(env["payload"]["_raw"], "not json at all")

    def test_webhook_handles_empty_body(self):
        r = self.client.post("/webhook/empty")
        self.assertEqual(r.status_code, 202)
        queued = r.json()["queued_as"]
        env = json.loads((self.tmp.webhooks_dir / queued).read_text())
        self.assertEqual(env["source"], "empty")

    def test_webhook_nested_source_path(self):
        r = self.client.post(
            "/webhook/jira/projects/PROJ/issues/created",
            json={"key": "PROJ-1"},
        )
        self.assertEqual(r.status_code, 202)
        env = json.loads(
            (self.tmp.webhooks_dir / r.json()["queued_as"]).read_text()
        )
        self.assertEqual(env["source"], "jira/projects/PROJ/issues/created")
        self.assertEqual(env["payload"]["key"], "PROJ-1")

    # ----- /dispatch -----

    def test_dispatch_requires_type_and_source(self):
        r = self.client.post("/dispatch", json={"foo": "bar"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("type", r.json()["detail"])

    def test_dispatch_writes_event_to_inbox(self):
        r = self.client.post("/dispatch", json={
            "type": "user.request",
            "source": "telegram",
            "payload": {"text": "build me a thing"},
        })
        self.assertEqual(r.status_code, 202)
        body = r.json()
        self.assertEqual(body["status"], "queued")
        # File in inbox/
        fpath = self.tmp.inbox_dir / f"{body['id']}.json"
        self.assertTrue(fpath.exists(), f"file not written: {fpath}")
        env = json.loads(fpath.read_text())
        self.assertEqual(env["type"], "user.request")
        self.assertEqual(env["source"], "telegram")
        # Default is_external: True (external call)
        self.assertTrue(env["is_external"])

    def test_dispatch_respects_explicit_is_external_false(self):
        r = self.client.post("/dispatch", json={
            "type": "internal.tick",
            "source": "scheduler",
            "is_external": False,
        })
        self.assertEqual(r.status_code, 202)
        env = json.loads(
            (self.tmp.inbox_dir / f"{r.json()['id']}.json").read_text()
        )
        self.assertFalse(env["is_external"])


if __name__ == "__main__":
    unittest.main()
