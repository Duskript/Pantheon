"""Unit tests for conductor.v2.api_server — REST API + SSE.

The 8 endpoints per spec §4.4 are exercised end-to-end via FastAPI's
TestClient (sync). Each test gets a fresh tmp workflows/state dir
via the existing TmpConductor fixture so writes don't leak.

Endpoints under test:
  - GET    /api/workflows
  - GET    /api/workflows/{id}
  - PUT    /api/workflows/{id}      ← validate-first + atomic write
  - DELETE /api/workflows/{id}
  - POST   /api/workflows/{id}/validate
  - POST   /api/workflows/{id}/run
  - GET    /api/workflows/{id}/runs
  - GET    /api/workflows/{id}/runs/{run_id}/events  (SSE)

Plus: bearer-token auth (header + query), /health (unauthenticated),
the bridge-* delete guard, the body-id-mismatch guard, and the
"engine reloads a PUT'd workflow" kill criterion.
"""

from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as cf  # noqa: E402

from v2 import api_server  # noqa: E402
from v2.api_server import make_app  # noqa: E402
from v2.live_stream import LiveStreamServer, StreamEvent  # noqa: E402
from v2.engine import ConductorEngine  # noqa: E402

# Standard sample workflow used by the tests. Mirrors the production
# bug-fix.yaml shape so the validator accepts it. Note: no
# `operator_approval_required` because no step is a sovereign
# outbound.
SAMPLE_WORKFLOW = {
    # The id here matches the path id used by the PUT/GET/run tests
    # (e.g. /api/workflows/alpha). The api_server enforces a body-id
    # == path-id match and returns 400 otherwise; see
    # test_put_rejects_body_id_mismatch for the negative test. The
    # old value of "test-wf" was a placeholder that tripped every
    # test that PUT/GET/seeded the sample as if it were "alpha".
    "id": "alpha",
    "name": "Test Workflow",
    "version": "1.0.0",
    "description": "for tests",
    "context": {"required": [], "optional": []},
    "steps": [
        {
            "id": "first",
            "type": "god",
            "god": "marvin",
            "skill": "test",
            "action": "noop",
            "timeout": "1m",
            "output": "first_result",
        },
        {
            "id": "second",
            "type": "god",
            "god": "marvin",
            "skill": "test",
            "input_from": "first",
            "timeout": "1m",
            "output": "second_result",
        },
    ],
}


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestApiServerHealth(unittest.TestCase):
    """/health is unauthenticated and reports the wiring state."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_health_unauthenticated(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["platform"], "conductor-v2-api")
        # Engine not wired in this test.
        self.assertFalse(body["engine_wired"])
        self.assertFalse(body["live_stream_wired"])
        self.assertEqual(body["auth"], "DISABLED")

    def test_health_reflects_engine_wiring(self):
        # Build a fresh app with an engine wired.
        engine = MagicMock()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            engine=engine,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)
        r = self.client.get("/health")
        self.assertTrue(r.json()["engine_wired"])


class TestApiServerAuth(unittest.TestCase):
    """Bearer token enforcement (header + query)."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            api_key="secret-key-123",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_token_returns_401(self):
        r = self.client.get("/api/workflows")
        self.assertEqual(r.status_code, 401)
        self.assertIn("missing", r.json()["detail"].lower())
        # WWW-Authenticate header per RFC 7235.
        self.assertIn("Bearer", r.headers.get("www-authenticate", ""))

    def test_wrong_token_returns_403(self):
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("wrong-key"),
        )
        self.assertEqual(r.status_code, 403)

    def test_correct_header_token_passes(self):
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("secret-key-123"),
        )
        self.assertEqual(r.status_code, 200)

    def test_correct_query_token_passes(self):
        r = self.client.get("/api/workflows?api_key=secret-key-123")
        self.assertEqual(r.status_code, 200)

    def test_health_is_unauthenticated_even_with_key_set(self):
        # /health must remain open for liveness probes.
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)


class TestApiServerAuthEnvFallback(unittest.TestCase):
    """Env-var fallback: empty api_key arg must NOT disable auth when
    CONDUCTOR_API_KEY is set in the environment (Ponytail Tier-2
    finding 2 on PR #35 — production deploys that use
    `uvicorn conductor.v2.api_server:app` rely on the env var and
    would have been unauthenticated by the old behavior)."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # Patch CONDUCTOR_API_KEY for the test (cleared in tearDown).
        import os
        self._prev_env = os.environ.get("CONDUCTOR_API_KEY")
        os.environ["CONDUCTOR_API_KEY"] = "env-key-456"
        # Note: we do NOT set CONDUCTOR_WS_API_KEY so the test only
        # exercises the canonical env var (spec §6).
        from v2.auth import set_expected_api_key
        # Reset the module-level binding so the env-var resolver
        # takes over (the previous test may have set a different
        # key via make_app's api_key arg).
        set_expected_api_key(None)
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            # api_key="" (the default) — falls through to env var
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        import os
        if self._prev_env is None:
            os.environ.pop("CONDUCTOR_API_KEY", None)
        else:
            os.environ["CONDUCTOR_API_KEY"] = self._prev_env
        from v2.auth import set_expected_api_key
        set_expected_api_key(None)
        self.tmp.cleanup()

    def test_env_key_is_accepted_when_arg_is_empty(self):
        # The env-var resolver should pick up CONDUCTOR_API_KEY even
        # when make_app() was called with api_key="" (the default).
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("env-key-456"),
        )
        self.assertEqual(r.status_code, 200)

    def test_wrong_key_rejected_when_env_fallback_active(self):
        # Wrong token still 403, not 200 — auth is enforced.
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("not-the-env-key"),
        )
        self.assertEqual(r.status_code, 403)

    def test_no_token_rejected_when_env_fallback_active(self):
        # No token at all → 401, not 200.
        r = self.client.get("/api/workflows")
        self.assertEqual(r.status_code, 401)

    def test_health_still_unauthenticated_with_env_key(self):
        # /health is the load-balancer probe — must NOT require auth
        # even when env-key is set.
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)


class TestApiServerAuthEnvFile(unittest.TestCase):
    """Fallback to CONDUCTOR_API_KEY from the operator's .env file
    (~/.hermes/.env or ~/pantheon/conductor/v2/.env) when the process
    env doesn't have it set. Lets the operator set the key once in
    their global hermes config and have the conductor daemon pick it
    up without an explicit `export` at startup.
    """

    def setUp(self):
        import os
        import tempfile
        from unittest.mock import patch

        # Build a fake "~/.hermes/.env" in a tmp dir by monkey-patching
        # `_HERMES_ENV_CANDIDATES`. We DON'T write to the real
        # ~/.hermes/.env (that would be rude to the operator's real
        # config and could break the next test run if the process
        # crashes between write and cleanup).
        self._tmp_home = Path(tempfile.mkdtemp(prefix="conductor_auth_test_"))
        self._fake_hermes_dir = self._tmp_home / ".hermes"
        self._fake_hermes_dir.mkdir()
        self._env_file = self._fake_hermes_dir / ".env"
        self._env_file.write_text(
            "# Operator's hermes env file (test fixture)\n"
            "SOME_OTHER_KEY=ignored\n"
            "CONDUCTOR_API_KEY=file-key-789\n"
            "TAILSCALE_ACME_DNS=ignored\n",
            encoding="utf-8",
        )

        # Strip the process env so the file fallback is the only
        # source of the key. The helper is cached, so we clear its
        # cache after patching the candidate path.
        self._prev_api = os.environ.pop("CONDUCTOR_API_KEY", None)
        self._prev_ws_api = os.environ.pop("CONDUCTOR_WS_API_KEY", None)

        # Patch the candidate list to point at our tmp .env.
        # The test file imports `v2.api_server` (so the test runner
        # sees `v2` as a package); the auth module is `v2.auth`.
        from v2 import auth as auth_mod
        self._real_candidates = auth_mod._HERMES_ENV_CANDIDATES
        auth_mod._HERMES_ENV_CANDIDATES = (self._env_file,)
        auth_mod._read_env_file.cache_clear()
        self._auth = auth_mod

        # Set up an app with api_key="" (default) — should fall through
        # to the .env file and pick up "file-key-789".
        cf_tmp = cf.TmpConductor.create()
        self.tmp = cf_tmp
        from v2.auth import set_expected_api_key
        set_expected_api_key(None)
        self.app = make_app(
            workflows_dir=cf_tmp.workflows_dir,
            state_dir=cf_tmp.state_dir,
            api_key="",  # default — falls through to file
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        import os
        # Restore the real candidate list and env state.
        if self._prev_api is not None:
            os.environ["CONDUCTOR_API_KEY"] = self._prev_api
        if self._prev_ws_api is not None:
            os.environ["CONDUCTOR_WS_API_KEY"] = self._prev_ws_api
        self._auth._HERMES_ENV_CANDIDATES = self._real_candidates
        self._auth._read_env_file.cache_clear()
        self._auth.set_expected_api_key(None)
        self.tmp.cleanup()
        import shutil
        shutil.rmtree(self._tmp_home, ignore_errors=True)

    def test_file_key_is_accepted_when_arg_and_env_empty(self):
        # CONDUCTOR_API_KEY=file-key-789 in the .env file, api_key=""
        # (default), no process env. The auth resolver should pick up
        # the file value.
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("file-key-789"),
        )
        self.assertEqual(r.status_code, 200)

    def test_wrong_key_rejected_when_file_fallback_active(self):
        # Wrong token → 403, not 200 — auth is enforced via the file.
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("not-the-file-key"),
        )
        self.assertEqual(r.status_code, 403)

    def test_no_token_rejected_when_file_fallback_active(self):
        # No token at all → 401, not 200. The file is set, so auth is on.
        r = self.client.get("/api/workflows")
        self.assertEqual(r.status_code, 401)

    def test_legacy_alias_in_file_also_works(self):
        # CONDUCTOR_WS_API_KEY= in the file should also be picked up
        # (the legacy alias is honored the same as the canonical name).
        # Rewrite the env file to use only the legacy alias.
        self._env_file.write_text(
            "CONDUCTOR_WS_API_KEY=legacy-file-key-000\n",
            encoding="utf-8",
        )
        # Clear the lru_cache so the rewrite is seen.
        self._auth._read_env_file.cache_clear()
        r = self.client.get(
            "/api/workflows",
            headers=_auth_headers("legacy-file-key-000"),
        )
        self.assertEqual(r.status_code, 200)

    def test_process_env_wins_over_file(self):
        # Even when the .env file has a key, a process env value
        # should take precedence (lets CI and tests override without
        # touching the operator's config).
        import os
        os.environ["CONDUCTOR_API_KEY"] = "proc-env-key-111"
        try:
            r = self.client.get(
                "/api/workflows",
                headers=_auth_headers("proc-env-key-111"),
            )
            self.assertEqual(r.status_code, 200)
            # The file value should NOT work now.
            r2 = self.client.get(
                "/api/workflows",
                headers=_auth_headers("file-key-789"),
            )
            self.assertEqual(r2.status_code, 403)
        finally:
            os.environ.pop("CONDUCTOR_API_KEY", None)


class TestListAndGetWorkflows(unittest.TestCase):
    """GET /api/workflows and GET /api/workflows/{id}."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_workflows_empty(self):
        r = self.client.get("/api/workflows")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["workflows"], [])

    def test_list_workflows_returns_summaries(self):
        # Write two YAML files to the workflows dir.
        for wf_id in ("alpha", "beta"):
            doc = {**SAMPLE_WORKFLOW, "id": wf_id, "name": wf_id.title()}
            (self.tmp.workflows_dir / f"{wf_id}.yaml").write_text(
                __import__("yaml").safe_dump(doc, default_flow_style=False)
            )
        r = self.client.get("/api/workflows")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 2)
        ids = {w["id"] for w in body["workflows"]}
        self.assertEqual(ids, {"alpha", "beta"})
        # Each entry has summary fields only.
        for w in body["workflows"]:
            self.assertIn("step_count", w)
            self.assertIn("version", w)
            # Full step definitions are NOT in the list response.
            self.assertNotIn("steps", w)

    def test_get_workflow_returns_full_document(self):
        doc = {**SAMPLE_WORKFLOW, "id": "alpha"}
        (self.tmp.workflows_dir / "alpha.yaml").write_text(
            __import__("yaml").safe_dump(doc, default_flow_style=False)
        )
        r = self.client.get("/api/workflows/alpha")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["id"], "alpha")
        self.assertEqual(len(body["steps"]), 2)
        self.assertEqual(body["steps"][0]["id"], "first")
        self.assertEqual(body["steps"][1]["input_from"], "first")

    def test_get_workflow_404(self):
        r = self.client.get("/api/workflows/missing")
        self.assertEqual(r.status_code, 404)


class TestPutWorkflow(unittest.TestCase):
    """PUT /api/workflows/{id} — validate-first, atomic write, in-memory reload."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # Real engine so we can verify the in-memory reload.
        self.engine = ConductorEngine(
            workflows_dir=self.tmp.workflows_dir,
            pending_dir=self.tmp.pending_dir,
            state_dir=self.tmp.state_dir,
        )
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            engine=self.engine,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_put_writes_yaml_file(self):
        r = self.client.put(
            "/api/workflows/alpha",
            json=SAMPLE_WORKFLOW,
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "written")
        # File is on disk.
        path = self.tmp.workflows_dir / "alpha.yaml"
        self.assertTrue(path.exists())

    def test_put_picks_up_in_memory_reload_kill_criterion(self):
        """The spec's kill criterion: PUT must refresh the in-memory
        workflow registry so the next start_workflow() sees the new
        content. We PUT a workflow, then check that
        engine.workflows.get('alpha') returns the new version.
        """
        # Before PUT: registry is empty.
        self.assertIsNone(self.engine.workflows.get("alpha"))

        r = self.client.put("/api/workflows/alpha", json=SAMPLE_WORKFLOW)
        self.assertEqual(r.status_code, 200)

        # After PUT: registry has the new workflow.
        wf = self.engine.workflows.get("alpha")
        self.assertIsNotNone(wf, "engine did not reload workflow after PUT")
        # wf is not None now — assertIsNotNone narrows the type for the
        # following accesses (Pyright would otherwise flag them).
        self.assertEqual(wf.id, "alpha")  # type: ignore[union-attr]
        self.assertEqual(wf.version, "1.0.0")  # type: ignore[union-attr]
        self.assertEqual(len(wf.steps), 2)  # type: ignore[union-attr]

    def test_put_rejects_invalid_workflow(self):
        """Validator must catch errors BEFORE the file is written."""
        bad = {**SAMPLE_WORKFLOW, "id": "alpha", "steps": []}  # zero steps
        r = self.client.put("/api/workflows/alpha", json=bad)
        # Zero steps fails at the engine's from_dict (KeyError on
        # steps[0] check) or the validator — either way, 500 (the
        # engine requires at least one step). The KEY point: the file
        # was NOT written.
        self.assertNotEqual(r.status_code, 200)
        # No file on disk after a failed PUT.
        self.assertFalse((self.tmp.workflows_dir / "alpha.yaml").exists())

    def test_put_rejects_body_id_mismatch(self):
        bad = {**SAMPLE_WORKFLOW, "id": "different"}
        r = self.client.put("/api/workflows/alpha", json=bad)
        self.assertEqual(r.status_code, 400)
        self.assertIn("does not match", r.json()["detail"])

    def test_put_accepts_yaml_content_type(self):
        yaml_text = __import__("yaml").safe_dump(SAMPLE_WORKFLOW, default_flow_style=False)
        r = self.client.put(
            "/api/workflows/alpha",
            content=yaml_text.encode("utf-8"),
            headers={"Content-Type": "application/yaml"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertTrue((self.tmp.workflows_dir / "alpha.yaml").exists())

    def test_put_is_atomic_no_partial_writes(self):
        """Verify the tmp+rename pattern: no `.tmp` files linger."""
        self.client.put("/api/workflows/alpha", json=SAMPLE_WORKFLOW)
        tmp_files = list(self.tmp.workflows_dir.glob(".*.tmp"))
        self.assertEqual(tmp_files, [], f"tmp files leaked: {tmp_files}")


class TestDeleteWorkflow(unittest.TestCase):
    """DELETE /api/workflows/{id} — refuses bridge-*, reloads registry."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.engine = ConductorEngine(
            workflows_dir=self.tmp.workflows_dir,
            pending_dir=self.tmp.pending_dir,
            state_dir=self.tmp.state_dir,
        )
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            engine=self.engine,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_delete_existing(self):
        # Write a workflow first.
        (self.tmp.workflows_dir / "alpha.yaml").write_text(
            __import__("yaml").safe_dump(SAMPLE_WORKFLOW, default_flow_style=False)
        )
        self.engine.workflows.reload_workflow("alpha")
        r = self.client.delete("/api/workflows/alpha")
        self.assertEqual(r.status_code, 200)
        self.assertFalse((self.tmp.workflows_dir / "alpha.yaml").exists())
        # In-memory copy is purged.
        self.assertIsNone(self.engine.workflows.get("alpha"))

    def test_delete_missing_404(self):
        r = self.client.delete("/api/workflows/nonexistent")
        self.assertEqual(r.status_code, 404)

    def test_delete_bridge_workflow_refused(self):
        """Per spec §4.4: bridge-* workflows are test fixtures and
        must not be deletable through the API."""
        r = self.client.delete("/api/workflows/bridge-test-foo")
        self.assertEqual(r.status_code, 403)
        self.assertIn("bridge-", r.json()["detail"])


class TestValidateWorkflow(unittest.TestCase):
    """POST /api/workflows/{id}/validate — runs the validator, never mutates."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_validate_existing_passes(self):
        (self.tmp.workflows_dir / "alpha.yaml").write_text(
            __import__("yaml").safe_dump(SAMPLE_WORKFLOW, default_flow_style=False)
        )
        r = self.client.post("/api/workflows/alpha/validate")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["valid"])
        self.assertEqual(body["violations"], [])
        self.assertEqual(body["workflow_id"], "alpha")

    def test_validate_missing_404(self):
        r = self.client.post("/api/workflows/missing/validate")
        self.assertEqual(r.status_code, 404)

    def test_validate_always_returns_200_for_bad_yaml(self):
        """A bad YAML file should be reported in `violations`, NOT as
        an HTTP error. The endpoint's job is to answer 'is this
        workflow valid?', not to enforce.
        """
        (self.tmp.workflows_dir / "broken.yaml").write_text("not: valid: yaml: at all: :")
        r = self.client.post("/api/workflows/broken/validate")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["valid"])
        self.assertTrue(len(body["violations"]) > 0)


class TestRunWorkflow(unittest.TestCase):
    """POST /api/workflows/{id}/run — triggers engine execution."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # We use a real engine so start_workflow() actually works,
        # but mock the gateway to avoid hitting the real Hermes.
        self.engine = ConductorEngine(
            workflows_dir=self.tmp.workflows_dir,
            pending_dir=self.tmp.pending_dir,
            state_dir=self.tmp.state_dir,
        )
        # Mock the gateway so start_workflow's _execute_step doesn't
        # try to call the real Hermes api_server.
        self.engine.gw = MagicMock()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            engine=self.engine,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_returns_503_when_no_engine(self):
        # Build a fresh app without an engine.
        app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            api_key="",
        )
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.post("/api/workflows/alpha/run")
        self.assertEqual(r.status_code, 503)

    def test_run_unknown_workflow_404(self):
        r = self.client.post("/api/workflows/never-defined/run", json={})
        self.assertEqual(r.status_code, 404)

    def test_run_starts_workflow_and_returns_workflow_id(self):
        # Seed the registry.
        (self.tmp.workflows_dir / "alpha.yaml").write_text(
            __import__("yaml").safe_dump(SAMPLE_WORKFLOW, default_flow_style=False)
        )
        self.engine.workflows.reload_workflow("alpha")

        r = self.client.post(
            "/api/workflows/alpha/run",
            json={"context": {"k": "v"}, "initiator": "test-suite"},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "started")
        self.assertEqual(body["definition_id"], "alpha")
        # workflow_id format: wf_<8 hex>
        self.assertTrue(body["workflow_id"].startswith("wf_"))
        self.assertEqual(len(body["workflow_id"]), 11)
        self.assertEqual(body["current_step"], "first")
        # The state file was written.
        state_path = self.tmp.state_dir / f"{body['workflow_id']}.json"
        self.assertTrue(state_path.exists())


class TestListRuns(unittest.TestCase):
    """GET /api/workflows/{id}/runs — list historical runs."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_runs_empty(self):
        r = self.client.get("/api/workflows/alpha/runs")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["runs"], [])

    def test_list_runs_filters_by_definition_id(self):
        # Write two state files: one for alpha, one for beta.
        alpha = {
            "workflow_id": "wf_alpha01",
            "definition_id": "alpha",
            "definition_version": "1.0.0",
            "status": "completed",
            "current_step": None,
            "context_bag": {},
            "step_history": [],
            "created": "2026-06-16T12:00:00Z",
        }
        beta = {**alpha, "workflow_id": "wf_beta01", "definition_id": "beta"}
        (self.tmp.state_dir / "wf_alpha01.json").write_text(json.dumps(alpha))
        (self.tmp.state_dir / "wf_beta01.json").write_text(json.dumps(beta))

        r = self.client.get("/api/workflows/alpha/runs")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["runs"][0]["definition_id"], "alpha")
        self.assertEqual(body["runs"][0]["workflow_id"], "wf_alpha01")


def _free_port() -> int:
    """Bind to port 0 to discover a free port, then release it.

    There's an unavoidable race (another process could grab the port
    between close() and our start()), but for the test isolation we
    get (each test gets a fresh port), it's good enough. Pattern
    borrowed from test_live_stream.py:46.
    """
    import socket
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _run(coro):
    """Run a coroutine in a fresh loop. Matches the pattern in
    test_live_stream.py so style stays consistent across the v2
    test suite (sync test methods, async helpers via asyncio.run).
    """
    return asyncio.run(coro)


class _SseTestServer:
    """Spin up a real uvicorn instance for SSE tests.

    Why real uvicorn instead of TestClient.stream(): the
    starlette.testclient TestClient uses httpx 0.28 with the new
    ASGITransport, which doesn't drain streaming responses from
    async generators — chunks never arrive. TestClient is fine
    for non-streaming JSON (all the other 28 tests use it), but
    SSE needs a real socket pair. Pattern borrowed from
    test_live_stream.py (which uses aiohttp against a real aiohttp
    LiveStreamServer).
    """

    def __init__(self, app):
        import uvicorn
        self.port = _free_port()
        config = uvicorn.Config(
            app, host="127.0.0.1", port=self.port, log_level="warning"
        )
        self._server = uvicorn.Server(config)
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._server.serve())
        for _ in range(30):
            if self._server.started:
                break
            await asyncio.sleep(0.1)
        if not self._server.started:
            raise RuntimeError("uvicorn did not start in time")

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=3.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()


class TestSseEvents(unittest.TestCase):
    """GET /api/workflows/{id}/runs/{run_id}/events — SSE stream.

    The two non-trivial tests (`test_sse_streams_open_event` and
    `test_sse_relays_broadcast_events`) need a real uvicorn server
    because starlette's TestClient (httpx 0.28 + ASGITransport)
    doesn't drain streaming responses from async generators.
    The simpler 503 test can use TestClient — there's no streaming
    involved, the response is a plain JSON error.
    """

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        # We need a real engine + live_stream so the SSE endpoint has
        # something to subscribe to. The live_stream needs to be
        # started (bound to a port) — but for SSE tests we just
        # subscribe via the queue mechanism, no actual WS needed.
        self.live_stream = LiveStreamServer(api_key="")
        # The SSE endpoint gates on `live_stream is not None` (not
        # `is_running` — see api_server.py stream_run_events),
        # but service.py's start() does call live_stream.start() in
        # production. Marking _started=True here is what production
        # looks like at request time; tests don't need the actual
        # WebSocket bind.
        self.live_stream._started = True
        self.engine = ConductorEngine(
            workflows_dir=self.tmp.workflows_dir,
            pending_dir=self.tmp.pending_dir,
            state_dir=self.tmp.state_dir,
            live_stream=self.live_stream,
        )
        # The api_server reads the live_stream from engine.live_stream,
        # so wiring it on the engine is enough — no separate arg needed.
        self.app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            engine=self.engine,
            api_key="",
        )
        from fastapi.testclient import TestClient
        self.client = TestClient(self.app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sse_returns_503_when_no_live_stream(self):
        """No live_stream → endpoint 503s. Build a fresh engine
        without a live_stream attached so the api_server's closure
        resolves to None. (Reusing self.engine would bypass the
        503 path — engine.live_stream is set there.)
        """
        engine_no_ls = ConductorEngine(
            workflows_dir=self.tmp.workflows_dir,
            pending_dir=self.tmp.pending_dir,
            state_dir=self.tmp.state_dir,
            # no live_stream kwarg → engine.live_stream is None
        )
        app = make_app(
            workflows_dir=self.tmp.workflows_dir,
            state_dir=self.tmp.state_dir,
            engine=engine_no_ls,
            api_key="",
        )
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.get("/api/workflows/alpha/runs/wf_x/events")
        self.assertEqual(r.status_code, 503)

    def test_sse_streams_open_event(self):
        """Connect to the SSE endpoint and read the synthetic `open`
        event. Uses a real uvicorn server (TestClient + ASGITransport
        doesn't drain streaming responses in our httpx 0.28 env).
        """
        async def go():
            srv = _SseTestServer(self.app)
            await srv.start()
            try:
                import httpx
                async with httpx.AsyncClient() as ac:
                    async with ac.stream(
                        "GET",
                        f"http://127.0.0.1:{srv.port}/api/workflows/alpha/runs/wf_test123/events",
                    ) as r:
                        self.assertEqual(r.status_code, 200)
                        # uvicorn may append "; charset=utf-8" to the
                        # Content-Type. Compare on the prefix so the
                        # test is robust to that.
                        self.assertTrue(
                            r.headers["content-type"].startswith("text/event-stream"),
                            f"unexpected content-type: {r.headers['content-type']!r}",
                        )
                        # Read lines until we have both the
                        # "event: open" header AND the data line
                        # that carries the workflow_id. SSE events
                        # are separated by a blank line, so we read
                        # until the first empty line.
                        lines: list[str] = []
                        async for line in r.aiter_lines():
                            lines.append(line)
                            if line == "":  # blank line = end of event
                                break
                        body = "\n".join(lines)
                        self.assertIn("event: open", body)
                        self.assertIn('"workflow_id": "wf_test123"', body)
            finally:
                await srv.stop()

        _run(go())

    def test_sse_relays_broadcast_events(self):
        """Open the SSE stream, then broadcast an event to the
        live_stream, and verify it arrives on the wire.
        """
        async def go():
            srv = _SseTestServer(self.app)
            await srv.start()
            try:
                import httpx
                async with httpx.AsyncClient() as ac:
                    async with ac.stream(
                        "GET",
                        f"http://127.0.0.1:{srv.port}/api/workflows/alpha/runs/wf_evt01/events",
                    ) as r:
                        self.assertEqual(r.status_code, 200)
                        # Schedule a broadcast that fires after the
                        # open event has been received (so the
                        # broadcast definitely arrives AFTER the
                        # open — order matters for the assertions).
                        async def broadcast_later():
                            # Wait for the listener queue to be
                            # created (the SSE generator awaits
                            # subscribe_workflow before yielding
                            # the open event, so the queue is up
                            # by the time open is on the wire).
                            for _ in range(40):
                                if self.live_stream.workflow_listener_count > 0:
                                    break
                                await asyncio.sleep(0.05)
                            await self.live_stream.broadcast(
                                StreamEvent.now(
                                    workflow_id="wf_evt01",
                                    step_id="first",
                                    event="step.started",
                                    data={"step_type": "god"},
                                )
                            )

                        broadcaster = asyncio.create_task(broadcast_later())
                        received: list[str] = []
                        async for line in r.aiter_lines():
                            if line:
                                received.append(line)
                            # Stop after we see both the open event
                            # AND the broadcast (which carries the
                            # "step.started" payload).
                            body = "\n".join(received)
                            if (
                                "event: open" in body
                                and '"event": "step.started"' in body
                            ):
                                break
                        await broadcaster
                        self.assertIn("event: open", body)
                        self.assertIn('"event": "step.started"', body)
                        self.assertIn('"workflow_id": "wf_evt01"', body)
                # Stream closed — listener queue should be cleaned up.
                # Give the generator's `finally` a moment to run.
                for _ in range(20):
                    if self.live_stream.workflow_listener_count == 0:
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(self.live_stream.workflow_listener_count, 0)
            finally:
                await srv.stop()

        _run(go())


if __name__ == "__main__":
    unittest.main()
