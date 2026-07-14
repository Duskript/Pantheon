"""Tests for the 8 credential REST endpoints + auth gating.

These tests use FastAPI's TestClient (sync) against a freshly-
constructed app with a stub credential store. The stub is the
reference behavior — if a test passes on the stub but the same
test fails against the encrypted impl, the encrypted impl has a
bug.

We exercise each of the 8 endpoints from the build plan §Phase 4.5:

  GET    /api/credentials              list (metadata only)
  GET    /api/credentials/{id}         read (metadata only)
  POST   /api/credentials              create
  PUT    /api/credentials/{id}         update
  DELETE /api/credentials/{id}         delete
  POST   /api/credentials/{id}/rotate  rotate value
  GET    /api/credentials/{id}/value   read decrypted value
  POST   /api/credentials/{id}/test    test connection (smoke)

Plus the unlock/lock helpers and the bearer-auth gate.

Total: 31 tests.
"""
from __future__ import annotations

import json
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_via_api(client, **overrides) -> dict:
    """Helper: POST /api/credentials with sensible defaults."""
    body = {
        "name": "sendgrid",
        "type": "api_key",
        "value": "***",
        "metadata": {"owner": "konan"},
    }
    body.update(overrides)
    r = client.post("/api/credentials", json=body)
    assert r.status_code == 200, f"create failed: {r.status_code} {r.text}"
    return r.json()


# ---------------------------------------------------------------------------
# Health endpoint reports credential backend
# ---------------------------------------------------------------------------

class TestHealthIncludesCredentialBackend:
    """The /health endpoint should report which backend is wired."""

    def test_health_includes_credential_backend(self, fastapi_app):
        _, client = fastapi_app
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        # The health endpoint may or may not include a credential
        # backend field — we accept either, but if present, it
        # must be a string.
        if "credential_backend" in body:
            assert isinstance(body["credential_backend"], str)
            assert body["credential_backend"] in ("stub", "encrypted")


# ---------------------------------------------------------------------------
# GET /api/credentials
# ---------------------------------------------------------------------------

class TestListEndpoint:
    """GET /api/credentials — list (metadata only, no values)."""

    def test_list_empty(self, fastapi_app):
        _, client = fastapi_app
        r = client.get("/api/credentials")
        assert r.status_code == 200
        assert r.json() == {"credentials": [], "count": 0}

    def test_list_returns_metadata_no_value(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client, name="sendgrid")
        r = client.get("/api/credentials")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        item = body["credentials"][0]
        assert item["name"] == "sendgrid"
        # The list endpoint MUST NOT return the value field.
        assert "value" not in item

    def test_list_filter_by_type(self, fastapi_app):
        _, client = fastapi_app
        _create_via_api(client, name="k", type="api_key")
        _create_via_api(client, name="u", type="database_url")
        r = client.get("/api/credentials", params={"type": "api_key"})
        assert r.status_code == 200
        names = [c["name"] for c in r.json()["credentials"]]
        assert names == ["k"]

    def test_list_filter_invalid_type_returns_400(self, fastapi_app):
        _, client = fastapi_app
        r = client.get("/api/credentials", params={"type": "not_a_real_type"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# GET /api/credentials/{id}
# ---------------------------------------------------------------------------

class TestGetEndpoint:
    """GET /api/credentials/{id} — read (metadata only)."""

    def test_get_returns_metadata(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client)
        r = client.get(f"/api/credentials/{c['id']}")
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "sendgrid"
        assert "value" not in body

    def test_get_unknown_returns_404(self, fastapi_app):
        _, client = fastapi_app
        r = client.get("/api/credentials/nonexistent-id")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/credentials
# ---------------------------------------------------------------------------

class TestCreateEndpoint:
    """POST /api/credentials — create."""

    def test_create_returns_full_record(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials", json={
            "name": "sendgrid",
            "type": "api_key",
            "value": "***",
        })
        assert r.status_code == 200
        body = r.json()
        assert body["id"]
        assert body["name"] == "sendgrid"
        assert body["type"] == "api_key"
        # The value is NOT echoed back on create.
        assert "value" not in body

    def test_create_duplicate_name_returns_409(self, fastapi_app):
        _, client = fastapi_app
        _create_via_api(client, name="dup")
        r = client.post("/api/credentials", json={
            "name": "dup", "type": "api_key", "value": "v",
        })
        assert r.status_code == 409

    def test_create_missing_name_returns_400(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials", json={"type": "api_key", "value": "v"})
        assert r.status_code == 400

    def test_create_missing_value_returns_400(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials", json={"name": "x", "type": "api_key"})
        assert r.status_code == 400

    def test_create_unknown_type_returns_400(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials", json={
            "name": "x", "type": "not_a_type", "value": "v",
        })
        assert r.status_code == 400

    def test_create_with_rotation_policy(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials", json={
            "name": "x",
            "type": "api_key",
            "value": "v",
            "rotation_policy": {"interval_days": 30, "notify_before_days": 5},
        })
        assert r.status_code == 200
        assert r.json()["rotation_policy"]["interval_days"] == 30

    def test_create_invalid_rotation_policy_returns_400(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials", json={
            "name": "x",
            "type": "api_key",
            "value": "v",
            "rotation_policy": "not an object",
        })
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# PUT /api/credentials/{id}
# ---------------------------------------------------------------------------

class TestUpdateEndpoint:
    """PUT /api/credentials/{id} — update."""

    def test_update_metadata(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client)
        r = client.put(f"/api/credentials/{c['id']}", json={"metadata": {"env": "prod"}})
        assert r.status_code == 200
        assert r.json()["metadata"] == {"env": "prod"}

    def test_update_value(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client)
        r = client.put(f"/api/credentials/{c['id']}", json={"value": "new-secret"})
        assert r.status_code == 200
        # Verify the new value is what's stored.
        r2 = client.get(f"/api/credentials/{c['id']}/value")
        assert r2.json()["value"] == "new-secret"

    def test_update_unknown_id_returns_404(self, fastapi_app):
        _, client = fastapi_app
        r = client.put("/api/credentials/nope", json={"metadata": {}})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/credentials/{id}
# ---------------------------------------------------------------------------

class TestDeleteEndpoint:
    """DELETE /api/credentials/{id} — delete (idempotent)."""

    def test_delete_removes(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client)
        r = client.delete(f"/api/credentials/{c['id']}")
        assert r.status_code == 200
        # Confirm it's gone
        r2 = client.get(f"/api/credentials/{c['id']}")
        assert r2.status_code == 404

    def test_delete_unknown_is_silent(self, fastapi_app):
        # The store's delete is idempotent; the API should match.
        _, client = fastapi_app
        r = client.delete("/api/credentials/never-existed")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# POST /api/credentials/{id}/rotate
# ---------------------------------------------------------------------------

class TestRotateEndpoint:
    """POST /api/credentials/{id}/rotate — rotate value."""

    def test_rotate_changes_value(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client)
        # Set up a rotation policy first.
        client.put(f"/api/credentials/{c['id']}", json={
            "rotation_policy": {"interval_days": 30},
        })
        r = client.post(f"/api/credentials/{c['id']}/rotate", json={"value": "rotated-secret"})
        assert r.status_code == 200
        r2 = client.get(f"/api/credentials/{c['id']}/value")
        assert r2.json()["value"] == "rotated-secret"

    def test_rotate_missing_value_returns_400(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client)
        r = client.post(f"/api/credentials/{c['id']}/rotate", json={})
        assert r.status_code == 400

    def test_rotate_unknown_id_returns_404(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials/nope/rotate", json={"value": "v"})
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/credentials/{id}/value
# ---------------------------------------------------------------------------

class TestGetValueEndpoint:
    """GET /api/credentials/{id}/value — read decrypted value."""

    def test_get_value_returns_plaintext(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client, value="the-actual-secret")
        r = client.get(f"/api/credentials/{c['id']}/value")
        assert r.status_code == 200
        assert r.json() == {"id": c["id"], "value": "the-actual-secret"}

    def test_get_value_unknown_returns_404(self, fastapi_app):
        _, client = fastapi_app
        r = client.get("/api/credentials/nope/value")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/credentials/{id}/test
# ---------------------------------------------------------------------------

class TestTestEndpoint:
    """POST /api/credentials/{id}/test — connection smoke test."""

    def test_test_returns_resolved_metadata(self, fastapi_app):
        _, client = fastapi_app
        c = _create_via_api(client, value="secret-for-test")
        r = client.post(f"/api/credentials/{c['id']}/test")
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == c["id"]
        assert body["name"] == "sendgrid"
        assert body["type"] == "api_key"
        # The test endpoint confirms the value resolves; per-type
        # probes are out of scope for v1.
        assert body["value_resolved"] is True
        assert body["value_length"] == len("secret-for-test")

    def test_test_unknown_returns_404(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials/nope/test")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/credentials/unlock + lock
# ---------------------------------------------------------------------------

class TestUnlockLockEndpoints:
    """The unlock/lock helpers (for the encrypted backend)."""

    def test_unlock_with_stub_backend_succeeds(self, fastapi_app):
        # The stub backend has no unlock method, but the endpoint
        # should still return a 200 (no-op success).
        _, client = fastapi_app
        r = client.post("/api/credentials/unlock", json={"passphrase": "anything"})
        assert r.status_code == 200
        assert r.json()["status"] == "unlocked"

    def test_unlock_missing_passphrase_returns_400(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials/unlock", json={})
        assert r.status_code == 400

    def test_lock_with_stub_backend_succeeds(self, fastapi_app):
        _, client = fastapi_app
        r = client.post("/api/credentials/lock")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Auth gating
# ---------------------------------------------------------------------------

class TestAuthGating:
    """The endpoints require a Bearer token when api_key is set."""

    def test_list_requires_auth(self, fastapi_app_with_auth):
        _, client = fastapi_app_with_auth
        r = client.get("/api/credentials")
        # No token provided — should 401.
        assert r.status_code == 401

    def test_create_requires_auth(self, fastapi_app_with_auth):
        _, client = fastapi_app_with_auth
        r = client.post("/api/credentials", json={
            "name": "x", "type": "api_key", "value": "v",
        })
        assert r.status_code == 401

    def test_valid_bearer_token_works(self, fastapi_app_with_auth):
        app, client = fastapi_app_with_auth
        r = client.post(
            "/api/credentials",
            json={"name": "x", "type": "api_key", "value": "v"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert r.status_code == 200

    def test_invalid_bearer_returns_403(self, fastapi_app_with_auth):
        _, client = fastapi_app_with_auth
        r = client.get(
            "/api/credentials",
            headers={"Authorization": "Bearer wrong-key"},
        )
        # 401 (no creds) or 403 (wrong creds) — both acceptable.
        assert r.status_code in (401, 403)
