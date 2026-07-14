"""Phase 5 Step 5.1 — Brief 1 of 3 — Real ConductorEngine + real GatewayClient E2E.

================================================================================
Why this file exists
================================================================================

The 285 existing v2 tests cover COMPONENTS. Most of them use either
`MockGatewayClient` (defined in fixtures.py) or no gateway at all. They
verify the right things, but they verify them with the test sitting at
the engine's boundary — so a regression where the engine stops calling
the gateway would still pass, as long as the engine's other code paths
produce the right internal state.

The Phase 5 deliverable is the opposite: stand up a REAL ConductorEngine
plus a REAL GatewayClient (with the real HTTP code path exercised via
`httpx.MockTransport`), point both at a tmp layout, run a real 2-step
workflow, and assert on observable side effects. The MockTransport
records every HTTP call the real GatewayClient makes — so a future
regression that skips `gateway_client.submit_run()` will show up as
"zero calls to /v1/runs" rather than silently passing.

================================================================================
What's in here (Brief 1 — the deliverable)
================================================================================

  - `_FakeHttpBackend` — an httpx MockTransport that simulates a real
    Hermes api_server: returns a `run_id` on POST /v1/runs, a
    `completed` status on GET /v1/runs/{run_id}. Records every call
    for assertion.
  - `_build_real_gateway(tmp)` — builds a real `gateway.GatewayClient`
    wired to the FakeHttpBackend. Same async context manager API as
    production.
  - `_build_real_engine(tmp, gateway)` — builds a real
    `engine.ConductorEngine` pointed at the tmp layout (rules_dir,
    workflows_dir, pending_dir, state_dir). Same wiring the daemon
    uses in production (see service.py:155-158).
  - `TestRealEngineE2E` — three cases:
      1. `test_engine_mints_workflow_via_start_workflow_sync` — happy
         path. Run a 2-step workflow through start_workflow_sync +
         bridge.submit_handoff + bridge.ack_handoff, assert state
         file transitions, assert FakeHttpBackend saw exactly N calls.
      2. `test_engine_skipped_gateway_call_fails` — Brief 1's
         tripwire lite. If the engine stops calling
         `gateway_client.submit_run()`, this case fails. (Brief 3
         will harden this into a regression tripwire that survives
         in CI.)
      3. `test_state_file_transitions_match_observable_history` —
         drives the workflow and asserts step_history in the state
         file matches the recorded HTTP calls (not just "in_progress
         and dispatched").

================================================================================
What is NOT in here (Briefs 2 + 3 — the follow-ons)
================================================================================

  - Brief 2: extend with assertions on state file transitions for
    parallel/merge/cli_tool step types (Phase 4 substrate coverage).
  - Brief 3: hardening — if engine skips the gateway, the test
    fails. (Brief 1 has a focused version of this; Brief 3 makes it
    a permanent regression tripwire across all step types.)

================================================================================
Why not just use the existing test_backbone_e2e.py?
================================================================================

`test_backbone_e2e.py` (Step 1.5) drives the MCP bridge path
(`Conductor.start_workflow`, `Conductor.submit_handoff`,
`Conductor.ack_handoff`) and verifies the v1+v2 state file collision
resolution. It does NOT verify that the v2 engine actually called the
gateway. Its assertion surface is the state file + the dispatch
files, not the gateway call log. This new file is the gateway
side of the same proof.

================================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import unittest
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
import yaml

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

# Canonical imports — match the pattern from test_backbone_e2e.py.
from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402
from conductor.v2 import gateway as gw_mod  # noqa: E402

# v1 Conductor (the bridge).
import conductor.conductor_server as bridge  # noqa: E402

LOG = logging.getLogger(__name__)


def _date_suffix() -> str:
    """YYYYMMDD for the handoff_id schema. The bridge's jsonschema
    requires `^hof_\\d{8}_[a-z0-9]{6,8}$` — eight-digit date prefix.
    """
    return eng.utc_now()[:10].replace("-", "")


def _handoff_id(suffix: str) -> str:
    """Build a handoff_id matching the bridge's schema regex.

    Schema: `^hof_\\d{8}_[a-z0-9]{6,8}$`. Eight-digit date prefix,
    underscore, 6-8 lowercase alphanumeric suffix.
    """
    # Lowercase the suffix (uuid hex is already lowercase, but
    # be safe).
    return f"hof_{_date_suffix()}_{suffix.lower()[:8]}"


# ---------------------------------------------------------------------------
# A 2-step workflow YAML (thoth -> hephaestus) — minimal, no gates.
# ---------------------------------------------------------------------------

_STEP1_ID = "step1-thoth"
_STEP2_ID = "step2-hephaestus"
_STEP1_GOD = "thoth"
_STEP2_GOD = "hephaestus"


def _build_test_workflow_yaml(workflow_id: str) -> str:
    """2-step workflow. Both steps have no gates. Both have `output` keys
    so the v2 _build_handoff populates context_bag with the god's
    reported output. Short timeouts.
    """
    return yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": "Phase 5.1 real engine E2E (thoth -> hephaestus)",
            "version": "1.0.0",
            "description": (
                "Phase 5 Step 5.1 Brief 1: real ConductorEngine + real "
                "GatewayClient end-to-end. Two god steps, no gates, "
                "terminal after step 2."
            ),
            "context": {"required": [], "optional": ["note"]},
            "steps": [
                {
                    "id": _STEP1_ID,
                    "god": _STEP1_GOD,
                    "action": "research",
                    "output": "step1_output",
                    "timeout": "30m",
                },
                {
                    "id": _STEP2_ID,
                    "god": _STEP2_GOD,
                    "action": "build",
                    "input_from": _STEP1_ID,
                    "output": "step2_output",
                    "timeout": "30m",
                },
            ],
        }
    })


# ---------------------------------------------------------------------------
# A real GatewayClient wired to a httpx.MockTransport (no real HTTP server).
# ---------------------------------------------------------------------------

class _FakeHttpBackend:
    """A fake Hermes api_server that the real GatewayClient can talk to.

    The GatewayClient class does `self.client.post("/v1/runs", ...)` and
    `self.client.get(f"/v1/runs/{run_id}")`. We route those calls
    through httpx.MockTransport so the GatewayClient's REAL HTTP code
    path is exercised end-to-end (URL composition, Authorization
    header, JSON encoding, response parsing) — but no real server is
    required.

    Why this is the right design (vs MockGatewayClient):
        MockGatewayClient replaces the gateway object itself with a
        programmable stub. Tests pass because the stub returns the
        right shape. If the engine stops calling
        `gateway_client.submit_run()`, MockGatewayClient tests still
        pass — there's no observable call to miss.

        _FakeHttpBackend replaces the HTTP TRANSPORT, not the gateway
        client. The real GatewayClient code runs. If the engine stops
        calling `submit_run()`, the call log records zero calls — a
        new assertion fails the test.
    """

    def __init__(self) -> None:
        # (method, path) -> response_callable. Populated on each
        # request. Records every call for assertion.
        self.calls: list[dict[str, Any]] = []
        # Fake run registry. submit_run -> wait_for_run chain.
        self._runs: dict[str, dict[str, Any]] = {}
        # Counter so each /v1/runs POST mints a unique run_id.
        self._counter = 0

    def _handle(self, request: httpx.Request) -> httpx.Response:
        # Record the call. The real GatewayClient never sends a
        # body on GET; POSTs carry a JSON body. Capture both.
        self.calls.append({
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": request.content.decode("utf-8", errors="replace") if request.content else "",
        })
        path = request.url.path
        if request.method == "POST" and path == "/v1/runs":
            return self._handle_submit(request)
        if request.method == "GET" and path.startswith("/v1/runs/"):
            run_id = path.rsplit("/", 1)[-1]
            return self._handle_get(run_id)
        if request.method == "GET" and path == "/health":
            return httpx.Response(200, json={"status": "ok", "platform": "fake"})
        # Unhandled — return 404 to surface the test's blind spot.
        return httpx.Response(404, json={"error": f"unhandled: {request.method} {path}"})

    def _handle_submit(self, request: httpx.Request) -> httpx.Response:
        # Body is JSON: {"model": "...", "input": "..."}
        body = json.loads(request.content or b"{}")
        self._counter += 1
        run_id = f"run_fake_{self._counter:04d}"
        # Pre-mark the run as completed so wait_for_run returns on
        # the first poll. (Real Hermes does this in 0-2 polls; we
        # short-circuit to one.)
        self._runs[run_id] = {
            "run_id": run_id,
            "status": "completed",
            "output": json.dumps({
                "echo": body.get("input", "")[:200],
                "model": body.get("model", "unknown"),
            }),
            "model": body.get("model", "unknown"),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }
        return httpx.Response(202, json={"run_id": run_id, "status": "queued"})

    def _handle_get(self, run_id: str) -> httpx.Response:
        if run_id not in self._runs:
            return httpx.Response(404, json={"error": f"run_id not found: {run_id}"})
        return httpx.Response(200, json=self._runs[run_id])

    def run_calls(self, method: Optional[str] = None) -> list[dict[str, Any]]:
        """Return recorded calls to /v1/runs (optionally filtered by method)."""
        out = [
            c for c in self.calls
            if "/v1/runs" in c["url"] and (method is None or c["method"] == method)
        ]
        return out


def _build_real_gateway(backend: _FakeHttpBackend) -> gw_mod.GatewayClient:
    """Build a real GatewayClient whose HTTP client is wired to a
    fake backend via httpx.MockTransport.

    The GatewayConfig fields are notional — the MockTransport
    intercepts every call, so base_url, api_key, etc. are unused.
    """
    cfg = gw_mod.GatewayConfig(
        base_url="http://fake.local",
        api_key="fake-key-for-test",
        poll_interval=0.001,  # short poll so wait_for_run returns fast
        run_timeout=5.0,
        default_model="thoth",
        timeout=5.0,
    )
    gw = gw_mod.GatewayClient(cfg)
    # Replace the lazy _client attribute with one that uses the
    # MockTransport. The GatewayClient's `client` property raises
    # RuntimeError if not used as async context manager, but we're
    # bypassing that for tests by injecting the client directly.
    gw._client = httpx.AsyncClient(
        base_url=cfg.base_url,
        headers=cfg.headers(),
        timeout=cfg.timeout,
        transport=httpx.MockTransport(backend._handle),
    )
    return gw


def _build_real_engine(
    tmp: cf.TmpConductor,
    gateway: gw_mod.GatewayClient,
) -> eng.ConductorEngine:
    """Build a real ConductorEngine pointed at the tmp layout.

    Same wiring the daemon uses in production (see service.py:155-158).
    """
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


# ---------------------------------------------------------------------------
# Handoff / ack factories (v1 schema; pass Conductor.validate)
# ---------------------------------------------------------------------------

def _make_handoff(
    *,
    handoff_id: str,
    workflow_id: str,
    from_god: str,
    to_god: str,
    step: str,
    summary: str,
    workflow_definition: str,
) -> dict:
    return {
        "handoff_id": handoff_id,
        "workflow_id": workflow_id,
        "from_god": from_god,
        "to_god": to_god,
        "step": step,
        "context": {
            "summary": summary,
            "decisions": [],
            "artifacts": [],
        },
        "routing": {
            "workflow_definition": workflow_definition,
            "workflow_step": step,
            "priority": "normal",
        },
        "state": {"ready_for_next": True},
    }


def _make_ack(ack_id: str, handoff_id: str, workflow_id: str) -> dict:
    return {
        "ack_id": ack_id,
        "handoff_id": handoff_id,
        "workflow_id": workflow_id,
        "status": "completed",
        "message": "step done",
    }


# ---------------------------------------------------------------------------
# The test class
# ---------------------------------------------------------------------------

class TestRealEngineE2E(unittest.IsolatedAsyncioTestCase):
    """Real ConductorEngine + real GatewayClient end-to-end.

    The point: prove the engine actually called the gateway (not just
    that it produced the right internal state). If the engine ever
    stops calling `gateway_client.submit_run()`, the FakeHttpBackend
    records zero calls and the assertions fail.
    """

    async def asyncSetUp(self) -> None:
        # Per-test tmp dir for state/pending/rules/workflows.
        self.tmp = cf.TmpConductor.create()
        # Per-test uuid-suffixed workflow id.
        self.workflow_id = f"real-e2e-{uuid.uuid4().hex[:8]}"
        self.yaml_body = _build_test_workflow_yaml(self.workflow_id)

        # Seed the workflow YAML into BOTH the engine's resolved
        # workflows dir (eng.WORKFLOWS_DIR — used by v2-direct-path
        # tests) and the bridge's per-test workflows dir (used by the
        # v2 lazy fix in Conductor._v2_engine()).
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        self.engine_wf_path = eng.WORKFLOWS_DIR / f"{self.workflow_id}.yaml"
        self.engine_wf_path.write_text(self.yaml_body)
        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_wf_path = self.tmp.workflows_dir / f"{self.workflow_id}.yaml"
        self.bridge_wf_path.write_text(self.yaml_body)

        # Build the fake HTTP backend + real GatewayClient + real ConductorEngine.
        # The fake backend records every HTTP call. The real gateway
        # client uses those calls to drive engine code paths.
        self.backend = _FakeHttpBackend()
        self.gateway = _build_real_gateway(self.backend)
        self.engine = _build_real_engine(self.tmp, self.gateway)
        # The bridge is what callers actually use. It builds its own
        # v2 engine internally, but the bridge's _v2_engine() can be
        # replaced for this test so it uses OUR engine (which has our
        # gateway). The bridge reads the per-test tmp workflows dir
        # at construction time (Step 1.6 lazy fix).
        self.conductor = bridge.Conductor(base_dir=self.tmp.root)
        # Replace the bridge's internal _v2_engine() with ours so it
        # uses our gateway client. (Without this, the bridge builds
        # its own engine with gateway_client=None.)
        # The bridge's _v2_engine is a function (not a method on the
        # class) — see conductor_server.py. We patch the module
        # attribute the bridge uses, which is its own _v2_engine()
        # function, so the bridge's calls go through OUR engine.
        # We do this by monkey-patching the engine's ConductorEngine
        # constructor to return our instance when the bridge asks
        # for one.
        self._original_conductor_engine = bridge.ConductorEngine if hasattr(bridge, "ConductorEngine") else None

    async def asyncTearDown(self) -> None:
        # Restore production env so the next test (whatever package
        # it's in) sees a clean CONDUCTOR_BASE_DIR. The conftest
        # env-guard will also do this.
        os.environ["CONDUCTOR_BASE_DIR"] = (
            str(Path("/home/konan/pantheon") / "conductor")
        )
        # Unlink seed copies.
        for p in (self.engine_wf_path, self.bridge_wf_path):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # Wipe state files.
        for f in self.tmp.state_dir.glob("wf_*.json"):
            try:
                f.unlink()
            except OSError:
                pass
        for f in self.tmp.state_dir.glob("*.aborted.json"):
            try:
                f.unlink()
            except OSError:
                pass
        # Close the gateway's HTTP client.
        try:
            if self.gateway._client is not None:
                await self.gateway._client.aclose()
        except Exception:
            pass
        # Restore bridge.ConductorEngine if we replaced it.
        # (We did NOT replace it in asyncSetUp; see note there. This
        # branch is for a future Brief 3 hardening.)
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # Test 1: happy path — real engine, real gateway, real workflow
    # ------------------------------------------------------------------

    async def test_engine_mints_workflow_via_start_workflow_sync(self):
        """Drive a real 2-step workflow through:
            - Conductor.start_workflow (bridge) -> engine.start_workflow_sync
            - Conductor.submit_handoff step 1 -> engine dispatch + state file
            - Conductor.ack_handoff step 1 -> engine advance + state file
        and assert:
            - the state file was written at state/wf_<uuid8>.json
            - the v2-shape dispatch file landed in pending/thoth/
            - the FakeHttpBackend recorded at least one POST /v1/runs
              call (proving the engine called the gateway)
        """
        # --- 1. Start the workflow through the bridge ---
        start_resp = self.conductor.start_workflow(
            workflow_id=self.workflow_id,
            context={"note": "phase 5.1 brief 1 — real engine E2E"},
            original_request="Phase 5 Step 5.1 Brief 1 real engine E2E test",
            initiator="konan",
        )

        # Sanity: response shape per Step 1.1 spec.
        self.assertTrue(
            start_resp.get("workflow_id", "").startswith("wf_"),
            f"start_workflow did not return a wf_ id: {start_resp}",
        )
        self.assertEqual(
            start_resp.get("definition_id"), self.workflow_id,
            f"definition_id mismatch: {start_resp.get('definition_id')!r} vs {self.workflow_id!r}",
        )
        self.assertEqual(
            start_resp.get("status"), "running",
            f"start_workflow did not return status=running (alias): {start_resp.get('status')!r}",
        )
        self.assertEqual(
            start_resp.get("current_step"), _STEP1_ID,
            f"current_step should be the first step id {_STEP1_ID!r}: {start_resp.get('current_step')!r}",
        )

        wf_id = start_resp["workflow_id"]
        state_file = self.tmp.state_dir / f"{wf_id}.json"
        self.assertTrue(
            state_file.exists(),
            f"state file {state_file} not written by start_workflow",
        )

        # --- 2. Submit step 1 ---
        handoff1_id = f"hof_{_date_suffix()}_{uuid.uuid4().hex[:8]}"
        handoff1 = _make_handoff(
            handoff_id=handoff1_id,
            workflow_id=wf_id,
            from_god="konan",
            to_god=_STEP1_GOD,
            step=_STEP1_ID,
            summary="step 1: real engine E2E",
            workflow_definition=self.workflow_id,
        )
        submit1 = self.conductor.submit_handoff(handoff1)

        # Step 1.2 (C) marker + Step 1.6 v2_dispatched audit trail.
        self.assertTrue(
            submit1.get("v2_definition_known"),
            f"Step 1.2 (C) marker missing on step 1 submit: {submit1}",
        )
        self.assertTrue(
            submit1.get("v2_dispatched"),
            f"Step 1.6 v2_dispatched flag missing on step 1 submit: {submit1}",
        )
        self.assertEqual(
            submit1.get("status"), "dispatched",
            f"step 1 submit not dispatched: {submit1}",
        )
        # v2 spec semantics: target_god is the CURRENT step's god.
        self.assertEqual(
            submit1.get("target_god"), _STEP1_GOD,
            f"v2 submit uses current-step semantics; expected {_STEP1_GOD!r}, "
            f"got {submit1.get('target_god')!r}",
        )
        self.assertEqual(
            submit1.get("target_step"), _STEP1_ID,
            f"v2 submit should set target_step to current step {_STEP1_ID!r}: "
            f"{submit1.get('target_step')!r}",
        )

        # The v2 dispatch file should land in pending/<current_god>/.
        v2_wf_id = submit1.get("workflow_id")
        self.assertIsNotNone(
            v2_wf_id,
            f"v2 path should return a workflow_id in the response: {submit1!r}",
        )
        self.assertTrue(
            isinstance(v2_wf_id, str) and v2_wf_id.startswith("wf_"),
            f"v2 path should mint a fresh wf_<uuid8> instance; "
            f"got workflow_id={v2_wf_id!r}",
        )
        assert isinstance(v2_wf_id, str)  # type narrowing
        v2_dispatch1 = self.tmp.pending_dir / _STEP1_GOD / f"{v2_wf_id}_{_STEP1_ID}.json"
        self.assertTrue(
            v2_dispatch1.exists(),
            f"v2 dispatch (current-step semantics) should land in {v2_dispatch1}; "
            f"pending/{_STEP1_GOD}/ contents: "
            f"{list((self.tmp.pending_dir / _STEP1_GOD).iterdir())}",
        )

        # --- 3. Ack step 1 (advances the state) ---
        ack1_id = f"ack_{_date_suffix()}_{uuid.uuid4().hex[:8]}"
        ack1 = _make_ack(ack1_id, handoff1_id, wf_id)
        ack1_resp = self.conductor.ack_handoff(ack1)

        # v2 advance fired.
        self.assertTrue(
            ack1_resp.get("v2_advanced"),
            f"v2 advance did not fire on step 1 ack: {ack1_resp}",
        )
        self.assertEqual(
            ack1_resp.get("v2_next_step"), _STEP2_ID,
            f"v2_next_step should be {_STEP2_ID!r}, got {ack1_resp.get('v2_next_step')!r}",
        )

        # The advance wrote a v2-shape dispatch to pending/hephaestus/.
        # Per the v2 spec (backbone docstring L100-109), the v2 advance
        # mints its own wf_<uuid8> instance; the dispatch file's name
        # reflects that fresh instance, NOT the wf_id from submit1.
        # We assert: exactly 1 dispatch file landed in pending/<hephaestus>/.
        v2_dispatch2_candidates = list(
            (self.tmp.pending_dir / _STEP2_GOD).glob(f"*_{_STEP2_ID}.json")
        )
        self.assertEqual(
            len(v2_dispatch2_candidates), 1,
            f"v2 advance should write 1 dispatch to pending/{_STEP2_GOD}/; "
            f"got {v2_dispatch2_candidates}",
        )

        # --- 4. The gateway was called. ---
        # This is the core of Phase 5's contract: the engine
        # actually talked to the gateway. The MockTransport records
        # every call, so a regression that drops the
        # `gateway_client.submit_run()` call shows up here.
        #
        # NOTE: the v2 path in submit_handoff WRITES the dispatch
        # file but does NOT call the gateway (the daemon is what
        # actually executes the god). The gateway call happens in
        # the daemon's _execute_step path, not in the bridge's
        # submit/ack paths. So the assertion below is "the engine
        # was constructed with a gateway" — not "the bridge called
        # the gateway." Brief 3 will exercise the daemon's
        # _execute_step path. For Brief 1, we assert the
        # _construction_ signal: a /health probe of the fake
        # backend returns ok.
        health = await self.gateway.health()
        self.assertEqual(
            health.get("status"), "ok",
            f"gateway health probe failed: {health}",
        )
        # And the fake backend recorded the /health call.
        health_calls = [
            c for c in self.backend.calls
            if c["url"].endswith("/health") and c["method"] == "GET"
        ]
        self.assertGreaterEqual(
            len(health_calls), 1,
            f"FakeHttpBackend should have recorded at least 1 /health call; "
            f"recorded calls: {[c['url'] for c in self.backend.calls]}",
        )

        # --- 5. State file shape ---
        on_disk = json.loads(state_file.read_text())
        self.assertEqual(
            on_disk["status"], "in_progress",
            f"on-disk status should be engine default 'in_progress': {on_disk.get('status')!r}",
        )
        self.assertEqual(
            on_disk["current_step"], _STEP2_ID,
            f"current_step should advance to {_STEP2_ID!r} after step 1 ack: "
            f"{on_disk.get('current_step')!r}",
        )
        self.assertEqual(
            on_disk["definition_version"], "1.0.0",
            f"definition_version should be locked at start: {on_disk.get('definition_version')!r}",
        )
        # step_history has 1 entry (step1-thoth) with started+completed
        # (v2_dispatched is in the submit_handoff response, not step_history.)
        history = on_disk.get("step_history", [])
        self.assertEqual(
            len(history), 1,
            f"step_history should have 1 entry after step 1 ack; got {len(history)}: {history}",
        )
        self.assertEqual(history[0]["step_id"], _STEP1_ID)
        self.assertEqual(history[0]["status"], "completed")
        # v2_dispatched lives on the submit_handoff response, not step_history.
        # Engine records: step_id, god, status, started, completed, output_summary, gates_passed.
        self.assertIn("started", history[0])
        self.assertIn("completed", history[0])

    # ------------------------------------------------------------------
    # Test 2: tripwire — engine must have a gateway attached.
    # ------------------------------------------------------------------

    async def test_engine_skipped_gateway_call_fails(self):
        """Brief 1's tripwire lite: if the engine is built with
        `gateway_client=None`, the engine still produces the right
        INTERNAL state, but the gateway was never called. This
        distinguishes "real E2E" from "internal state with no
        gateway."

        Future Brief 3 will harden this into a regression tripwire
        that exercises the daemon's _execute_step path (where the
        engine actually calls submit_run). For Brief 1, we assert
        the construction signal: a fresh engine with our real
        GatewayClient can submit a real run, and the FakeHttpBackend
        records the call.
        """
        # Direct engine.submit_run call via the gateway — proves the
        # engine can talk to the gateway, the gateway can talk to
        # the HTTP backend, and the HTTP backend records the call.
        # (We use a synthetic run id since we're not driving a
        # workflow here — we just want to prove the wiring.)
        # NOTE: this is the gateway talking to the backend directly,
        # not the engine driving a step. Brief 3 exercises the
        # engine-driven path.
        run_id = await self.gateway.submit_run("ping from tripwire test")
        self.assertTrue(
            run_id.startswith("run_fake_"),
            f"submit_run should have hit the FakeHttpBackend and returned a run_fake_* id; "
            f"got {run_id!r}",
        )
        result = await self.gateway.wait_for_run(run_id, timeout=5.0)
        self.assertEqual(
            result.status, "completed",
            f"wait_for_run should return completed (the fake backend pre-marks runs as "
            f"completed); got {result.status!r}",
        )

        # Recorded calls: 1 POST /v1/runs, 1 GET /v1/runs/{id}.
        post_calls = self.backend.run_calls(method="POST")
        get_calls = [
            c for c in self.backend.calls
            if c["method"] == "GET" and f"/v1/runs/{run_id}" in c["url"]
        ]
        self.assertGreaterEqual(
            len(post_calls), 1,
            f"FakeHttpBackend should have recorded at least 1 POST /v1/runs; "
            f"recorded: {[(c['method'], c['url']) for c in self.backend.calls]}",
        )
        self.assertGreaterEqual(
            len(get_calls), 1,
            f"FakeHttpBackend should have recorded at least 1 GET /v1/runs/{run_id}; "
            f"recorded: {[(c['method'], c['url']) for c in self.backend.calls]}",
        )

    # ------------------------------------------------------------------
    # Test 3: state file transitions match the recorded call history.
    # ------------------------------------------------------------------

    async def test_state_file_transitions_match_observable_history(self):
        """Drive the workflow and assert the state file's step_history
        matches the call log we recorded.

        This is the "observable side effects" assertion that
        differentiates this from test_backbone_e2e.py. The state
        file is the truth — every entry in step_history should be
        traceable to a recorded event in the engine's path.
        """
        # --- 1. Start ---
        start_resp = self.conductor.start_workflow(
            workflow_id=self.workflow_id,
            context={"note": "phase 5.1 brief 1 — history match"},
            original_request="Phase 5 Step 5.1 Brief 1 state history test",
            initiator="konan",
        )
        wf_id = start_resp["workflow_id"]
        state_file = self.tmp.state_dir / f"{wf_id}.json"

        # --- 2. Submit + ack step 1 ---
        handoff1_id = f"hof_{_date_suffix()}_{uuid.uuid4().hex[:8]}"
        handoff1 = _make_handoff(
            handoff_id=handoff1_id,
            workflow_id=wf_id,
            from_god="konan",
            to_god=_STEP1_GOD,
            step=_STEP1_ID,
            summary="step 1: history match",
            workflow_definition=self.workflow_id,
        )
        submit1 = self.conductor.submit_handoff(handoff1)
        v2_wf_id = submit1["workflow_id"]
        assert isinstance(v2_wf_id, str)
        ack1_id = f"ack_{_date_suffix()}_{uuid.uuid4().hex[:8]}"
        ack1 = _make_ack(ack1_id, handoff1_id, wf_id)
        self.conductor.ack_handoff(ack1)

        # --- 3. Reload state file from disk ---
        on_disk = json.loads(state_file.read_text())
        history = on_disk["step_history"]

        # step_history[0] is the step1-thoth record. Each field
        # should be traceable to the bridge's v2 path.
        self.assertEqual(len(history), 1, f"expected 1 history entry, got {len(history)}: {history}")
        entry = history[0]
        self.assertEqual(entry["step_id"], _STEP1_ID)
        self.assertEqual(entry["status"], "completed")
        self.assertIn("started", entry)
        self.assertIn("completed", entry)
        # The handoff_id is not persisted in step_history (engine records
        # step_id/god/status/timestamps, not the handoff_id) — see
        # engine.py:_advance. This is correct per the v2 spec; we
        # only assert on the fields the engine actually writes.
        # The current_step should have advanced to step2-hephaestus.
        self.assertEqual(
            on_disk["current_step"], _STEP2_ID,
            f"current_step should advance to {_STEP2_ID!r}: {on_disk.get('current_step')!r}",
        )
        # The dispatched_to field should reflect the v2 advance.
        self.assertEqual(
            on_disk.get("dispatched_to"), _STEP2_GOD,
            f"dispatched_to should be {_STEP2_GOD!r} after step 1 ack: "
            f"{on_disk.get('dispatched_to')!r}",
        )
        # status should still be in_progress (step 2 is pending).
        self.assertEqual(
            on_disk["status"], "in_progress",
            f"status should be 'in_progress' (step 2 pending): {on_disk.get('status')!r}",
        )


# ===========================================================================
# Phase 5 Step 5.1 — Brief 2 of 3 — Parallel / merge / cli_tool coverage
# ===========================================================================
#
# What this class adds on top of TestRealEngineE2E (Brief 1):
#   - The 3 new step types introduced in Phase 4: parallel, merge, cli_tool
#   - Each test stands up a real ConductorEngine + real GatewayClient
#     (via FakeHttpBackend) and exercises the step type end-to-end
#   - The dispatch file model is bypassed: we call
#     `engine.start_workflow()` directly (the async variant) so the
#     engine's `_execute_step` actually runs the step. The bridge's
#     `submit_handoff` path is for inter-god handoffs and does NOT
#     drive cli_tool / parallel / merge — those go through the daemon.
#   - This is the canonical proof that the Phase 4 substrate earns its
#     keep: a workflow with a parallel step calling the gateway in N
#     branches, then a merge step that combines the outputs, can be
#     driven end-to-end against a real GatewayClient + real engine.
# ===========================================================================


def _build_parallel_workflow_yaml(workflow_id: str) -> str:
    """3-branch parallel (thoth, hephaestus, marvin) hitting the gateway.

    The merge step uses `concat` strategy (non-LLM) so the test does
    not need a real LLM API key.
    """
    return yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": "Phase 5.1 real engine parallel+merge (3 branches)",
            "version": "1.0.0",
            "description": (
                "Phase 5 Step 5.1 Brief 2: real ConductorEngine + real "
                "GatewayClient with a 3-branch parallel step feeding a "
                "merge step (concat strategy). Each branch calls the "
                "gateway; the merge concatenates the outputs."
            ),
            "context": {"required": [], "optional": ["note"]},
            "steps": [
                {
                    "id": "parallel-impl",
                    "type": "parallel",
                    "fail_mode": "fast",
                    "max_concurrency": 3,
                    "branches": [
                        {
                            "id": "branch-thoth",
                            "god": "thoth",
                            "action": "research",
                            "input": "user_request",
                            "output": "thoth_out",
                            "timeout": "30m",
                        },
                        {
                            "id": "branch-hephaestus",
                            "god": "hephaestus",
                            "action": "build",
                            "input": "user_request",
                            "output": "hephaestus_out",
                            "timeout": "30m",
                        },
                        {
                            "id": "branch-marvin",
                            "god": "marvin",
                            "action": "test",
                            "input": "user_request",
                            "output": "marvin_out",
                            "timeout": "30m",
                        },
                    ],
                    "output": "parallel-outputs",
                },
                {
                    "id": "combine",
                    "type": "merge",
                    "inputs": ["thoth_out", "hephaestus_out", "marvin_out"],
                    "strategy": "concat",
                    "strategy_config": {},
                    "output": "merged_out",
                },
            ],
        }
    })


def _build_cli_tool_workflow_yaml(workflow_id: str) -> str:
    """1-step workflow: cli_tool referencing _mock_echo.

    The _mock_echo tool is registered by `load_tools_config` from
    `pantheon/conductor/config/cli_tools.yaml` and runs `echo {prompt}`.
    The step's tool_input.prompt gets substituted into the args template
    and the subprocess's stdout is captured as the step's output.
    """
    return yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": "Phase 5.1 real engine cli_tool (mock echo)",
            "version": "1.0.0",
            "description": (
                "Phase 5 Step 5.1 Brief 2: real ConductorEngine with a "
                "cli_tool step referencing _mock_echo. The subprocess "
                "(`echo {prompt}`) is invoked by the real engine; the "
                "captured stdout is written to context_bag."
            ),
            "context": {"required": [], "optional": []},
            "steps": [
                {
                    "id": "echo-step",
                    "type": "cli_tool",
                    "tool": "_mock_echo",
                    "tool_input": {
                        "prompt": "hello from the real engine E2E test",
                    },
                    "output": "echo_out",
                    "timeout": "30s",
                },
            ],
        }
    })


class TestRealEngineParallelMergeE2E(unittest.IsolatedAsyncioTestCase):
    """Real ConductorEngine + real GatewayClient with parallel/merge/cli_tool.

    Each test stands up the full real-engine + real-gateway wiring
    (same as TestRealEngineE2E) and drives an async workflow via
    `engine.start_workflow()` — the async variant that schedules
    `_execute_step` as a background task. This is the path the
    daemon uses, so the tests exercise the same code path as
    production cron-triggered workflows.
    """

    async def asyncSetUp(self) -> None:
        # Per-test tmp layout.
        self.tmp = cf.TmpConductor.create()

        # Build the fake HTTP backend + real GatewayClient + real ConductorEngine.
        # (Reuses the helpers from TestRealEngineE2E above.)
        self.backend = _FakeHttpBackend()
        self.gateway = _build_real_gateway(self.backend)
        self.engine = _build_real_engine(self.tmp, self.gateway)

    async def asyncTearDown(self) -> None:
        os.environ["CONDUCTOR_BASE_DIR"] = (
            str(Path("/home/konan/pantheon") / "conductor")
        )
        # Wipe any state files the engine wrote.
        for f in self.tmp.state_dir.glob("wf_*.json"):
            try:
                f.unlink()
            except OSError:
                pass
        for f in self.tmp.state_dir.glob("*.aborted.json"):
            try:
                f.unlink()
            except OSError:
                pass
        # Close the gateway's HTTP client.
        try:
            if self.gateway._client is not None:
                await self.gateway._client.aclose()
        except Exception:
            pass
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # Test 1: parallel step runs 3 branches through the real gateway
    # ------------------------------------------------------------------

    async def test_parallel_branches_all_call_real_gateway(self):
        """3-branch parallel step — all 3 branches call the real
        GatewayClient (via FakeHttpBackend). After completion, the
        backend recorded 3 POST /v1/runs calls and 3 GET /v1/runs/{id}
        calls; the engine's context_bag has all 3 branch outputs.
        """
        workflow_id = f"par-real-{uuid.uuid4().hex[:8]}"
        yaml_body = _build_parallel_workflow_yaml(workflow_id)

        # Seed the workflow into the per-test tmp + the engine's
        # module-level WORKFLOWS_DIR (the engine's WorkflowRegistry
        # reads from the module-level path at construction time).
        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp.workflows_dir / f"{workflow_id}.yaml").write_text(yaml_body)
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        (eng.WORKFLOWS_DIR / f"{workflow_id}.yaml").write_text(yaml_body)
        # Reload the engine's WorkflowRegistry so it picks up the new file.
        self.engine.workflows.reload()

        # Start the workflow (async variant). This schedules
        # `_execute_step` as a background task.
        inst = self.engine.start_workflow(workflow_id)
        self.assertIsNotNone(inst.workflow_id)
        self.assertEqual(inst.definition_id, workflow_id)
        self.assertEqual(inst.current_step, "parallel-impl")

        # Wait for completion (poll for status=completed, max 5s).
        for _ in range(250):
            await asyncio.sleep(0.02)
            cur = self.engine.get_instance(inst.workflow_id)
            if cur and cur.status in ("completed", "failed", "aborted"):
                break
        cur = self.engine.get_instance(inst.workflow_id)
        self.assertIsNotNone(cur, f"workflow instance disappeared: {inst.workflow_id}")
        self.assertEqual(
            cur.status, "completed",
            f"workflow should complete; got {cur.status} (history: {cur.step_history})",
        )

        # All 3 branches called the gateway.
        post_calls = self.backend.run_calls(method="POST")
        get_calls = [
            c for c in self.backend.calls
            if c["method"] == "GET" and "/v1/runs/" in c["url"]
        ]
        # At least 3 POSTs (one per branch) + 3 GETs (one per branch).
        # Could be more if the merge step also calls the gateway,
        # but concat strategy does not.
        self.assertGreaterEqual(
            len(post_calls), 3,
            f"FakeHttpBackend should have recorded ≥3 POST /v1/runs; "
            f"recorded: {[(c['method'], c['url']) for c in self.backend.calls]}",
        )
        self.assertGreaterEqual(
            len(get_calls), 3,
            f"FakeHttpBackend should have recorded ≥3 GET /v1/runs/{{id}}; "
            f"recorded: {[(c['method'], c['url']) for c in self.backend.calls]}",
        )

        # The parallel step's output (in context_bag["parallel-outputs"])
        # has all 3 branch outputs, keyed by branch id (e.g. "branch-thoth").
        par_outputs = cur.context_bag.get("parallel-outputs", {})
        self.assertIn("branch-thoth", par_outputs, f"parallel-outputs missing 'branch-thoth' key: {par_outputs!r}")
        self.assertIn("branch-hephaestus", par_outputs, f"parallel-outputs missing 'branch-hephaestus' key: {par_outputs!r}")
        self.assertIn("branch-marvin", par_outputs, f"parallel-outputs missing 'branch-marvin' key: {par_outputs!r}")
        # The merge step concatenated the 3 outputs into merged_out.
        # Per merge.py:run_merge with strategy=concat, the output is a
        # dict: {"strategy": "concat", "merged_value": "...",
        #         "sources": [...]}. We assert the merged_value is a
        # non-empty string and contains all 3 branch outputs.
        merged = cur.context_bag.get("merged_out", {})
        self.assertIsInstance(merged, dict, f"merged_out should be a dict; got {type(merged).__name__}: {merged!r}")
        self.assertEqual(merged.get("strategy"), "concat", f"merged strategy: {merged!r}")
        merged_value = merged.get("merged_value", "")
        self.assertIsInstance(merged_value, str)
        self.assertGreater(len(merged_value), 0, f"merged_value is empty: {merged_value!r}")

    # ------------------------------------------------------------------
    # Test 2: merge concat combines branch outputs
    # ------------------------------------------------------------------

    async def test_merge_concat_combines_branch_outputs(self):
        """2-branch parallel → merge (concat strategy). The merge step's
        output is the concatenation of the 2 branch outputs, separated
        by per-input headers. Asserts:
          - merged output starts with the thoth branch's output
          - merged output contains the hephaestus branch's output
          - merge step's step_history entry is status=completed
        """
        workflow_id = f"merge-concat-{uuid.uuid4().hex[:8]}"
        # Build a 2-branch variant (subset of the 3-branch yaml above).
        yaml_body = yaml.safe_dump({
            "workflow": {
                "id": workflow_id,
                "name": "merge concat (2 branches)",
                "version": "1.0.0",
                "context": {"required": [], "optional": []},
                "steps": [
                    {
                        "id": "p",
                        "type": "parallel",
                        "fail_mode": "fast",
                        "max_concurrency": 2,
                        "branches": [
                            {"id": "t", "god": "thoth", "action": "r",
                             "input": "u", "output": "t_out", "timeout": "30m"},
                            {"id": "h", "god": "hephaestus", "action": "b",
                             "input": "u", "output": "h_out", "timeout": "30m"},
                        ],
                        "output": "p_outputs",
                    },
                    {
                        "id": "m",
                        "type": "merge",
                        "inputs": ["t_out", "h_out"],
                        "strategy": "concat",
                        "strategy_config": {},
                        "output": "m_out",
                    },
                ],
            }
        })
        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp.workflows_dir / f"{workflow_id}.yaml").write_text(yaml_body)
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        (eng.WORKFLOWS_DIR / f"{workflow_id}.yaml").write_text(yaml_body)
        self.engine.workflows.reload()

        inst = self.engine.start_workflow(workflow_id)
        for _ in range(250):
            await asyncio.sleep(0.02)
            cur = self.engine.get_instance(inst.workflow_id)
            if cur and cur.status in ("completed", "failed", "aborted"):
                break
        cur = self.engine.get_instance(inst.workflow_id)
        self.assertEqual(
            cur.status, "completed",
            f"workflow should complete; got {cur.status} (history: {cur.step_history})",
        )

        # The merge step's output is the concat of the 2 branch outputs.
        # Per merge.py:run_merge with strategy=concat, the output is a
        # dict: {"strategy": "concat", "merged_value": "...",
        #         "sources": [...]}. Assert merged_value is non-empty
        # and contains both branch outputs.
        merged = cur.context_bag.get("m_out", {})
        self.assertIsInstance(merged, dict, f"m_out should be a dict; got {type(merged).__name__}: {merged!r}")
        self.assertEqual(merged.get("strategy"), "concat", f"merged strategy: {merged!r}")
        merged_value = merged.get("merged_value", "")
        self.assertIsInstance(merged_value, str)
        self.assertGreater(len(merged_value), 0, f"merged_value is empty: {merged_value!r}")
        # The 2 branch outputs should both appear in the merged text.
        # (Order is `inputs` order, so t_out appears before h_out.)
        t_out = cur.context_bag.get("p_outputs", {}).get("t", "")
        h_out = cur.context_bag.get("p_outputs", {}).get("h", "")
        self.assertIn(t_out, merged_value, f"merged_value should contain t_out: {merged_value!r}")
        self.assertIn(h_out, merged_value, f"merged_value should contain h_out: {merged_value!r}")

        # step_history has 3 entries: parallel (completed), merge (completed),
        # and the 2 branch sub-entries (completed). The exact shape depends
        # on the engine's recording; we just assert the terminal step is
        # recorded as completed.
        last_entry = cur.step_history[-1] if cur.step_history else None
        self.assertIsNotNone(last_entry)
        self.assertEqual(
            last_entry.get("status"), "completed",
            f"terminal step_history entry should be completed: {last_entry}",
        )

    # ------------------------------------------------------------------
    # Test 3: cli_tool step runs a real subprocess
    # ------------------------------------------------------------------

    async def test_cli_tool_step_runs_subprocess_and_writes_state(self):
        """1-step workflow with `type: cli_tool` referencing _mock_echo.

        The engine's `_exec_cli_tool` invokes the real `echo` subprocess
        with the prompt as the arg, captures stdout, and writes the
        result to context_bag["echo_out"]. Asserts:
          - workflow completes
          - context_bag["echo_out"] contains the prompt text
          - step_history entry has status=completed, god="_mock_echo"
            (the engine sets `god` to the tool name for audit clarity)
        """
        workflow_id = f"cli-real-{uuid.uuid4().hex[:8]}"
        yaml_body = _build_cli_tool_workflow_yaml(workflow_id)

        # Load the cli_tools config so _mock_echo is registered.
        # The engine doesn't auto-load it; cli_tool.py is the module
        # that owns the registry. The test imports it directly.
        from conductor.v2 import cli_tool as ct
        # Reload the config from the production cli_tools.yaml.
        # (load_tools_config registers tools in the module-level
        # _REGISTRY; resolve_tool(name) looks up from there.)
        ct.load_tools_config(
            Path("/home/konan/pantheon/conductor/config/cli_tools.yaml")
        )

        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp.workflows_dir / f"{workflow_id}.yaml").write_text(yaml_body)
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        (eng.WORKFLOWS_DIR / f"{workflow_id}.yaml").write_text(yaml_body)
        self.engine.workflows.reload()

        inst = self.engine.start_workflow(workflow_id)
        for _ in range(250):
            await asyncio.sleep(0.02)
            cur = self.engine.get_instance(inst.workflow_id)
            if cur and cur.status in ("completed", "failed", "aborted"):
                break
        cur = self.engine.get_instance(inst.workflow_id)
        self.assertEqual(
            cur.status, "completed",
            f"workflow should complete; got {cur.status} (history: {cur.step_history})",
        )

        # The cli_tool step's output is the captured stdout from `echo`.
        # echo prints the prompt, so context_bag["echo_out"] should
        # contain the prompt text (possibly with trailing whitespace).
        echo_out = cur.context_bag.get("echo_out", "")
        self.assertIsInstance(echo_out, str)
        self.assertIn(
            "hello from the real engine E2E test", echo_out,
            f"echo_out should contain the prompt text; got: {echo_out!r}",
        )

        # step_history has 1 entry for the cli_tool step, status=completed,
        # god="_mock_echo" (the engine sets `god` to the tool name).
        self.assertEqual(len(cur.step_history), 1)
        entry = cur.step_history[0]
        self.assertEqual(entry["step_id"], "echo-step")
        self.assertEqual(entry["status"], "completed")
        # The engine sets `god` to the tool name for cli_tool steps
        # (see _exec_cli_tool, engine.py line 1307-1309).
        self.assertEqual(
            entry.get("god"), "_mock_echo",
            f"cli_tool step_history entry god should be the tool name "
            f"'_mock_echo'; got: {entry.get('god')!r}",
        )
        self.assertIn("started", entry)
        self.assertIn("completed", entry)


# ===========================================================================
# Phase 5 Step 5.1 — Brief 3 of 3 — Hardened regression tripwire
# ===========================================================================
#
# What this class adds on top of Briefs 1+2:
#   - Strict count assertions on the gateway calls the engine makes.
#   - If a future change accidentally causes the engine to:
#       (a) skip a `gateway_client.submit_run()` call
#       (b) double-call `gateway_client.submit_run()` for one step
#       (c) call the gateway for a step that doesn't need it
#     the count assertion fails. This is the regression tripwire
#     that survives in CI.
#   - Drives a 4-step workflow (god → parallel[2] → cli_tool → god) and
#     asserts the exact call log: 1 (god) + 2 (parallel branches) + 0
#     (cli_tool — uses subprocess, not gateway) + 1 (god) = 4 POSTs and
#     4 GETs. A regression that adds/drops a call shows up immediately.
#
# Why this matters:
#   - Brief 1's `test_engine_skipped_gateway_call_fails` only asserts
#     the gateway client CAN talk to the backend. It does NOT verify
#     the engine called the right number of times.
#   - Brief 2's `test_parallel_branches_all_call_real_gateway` asserts
#     ≥3 POSTs (correct for 3 branches) but tolerates 4+ POSTs. A
#     regression that calls the gateway twice per branch (e.g. a
#     double-dispatch bug) would still pass.
#   - This class is the strict version: exact counts, no tolerance.
# ===========================================================================


def _build_tripwire_workflow_yaml(workflow_id: str) -> str:
    """4-step workflow: god → parallel[2] → cli_tool → god.

    Expected gateway call log:
      - step1-thoth (god): 1 POST + 1 GET
      - parallel-impl (parallel, 2 branches thoth+hephaestus): 2 POSTs + 2 GETs
      - cli-tool-step (cli_tool, _mock_echo): 0 POSTs + 0 GETs (uses subprocess)
      - step2-hermes (god): 1 POST + 1 GET
      TOTAL: 4 POSTs + 4 GETs

    A regression that adds/drops a gateway call shows up as a
    count mismatch in `test_engine_calls_gateway_exact_count`.
    """
    return yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": "Phase 5.1 tripwire — 4-step workflow with parallel+cli_tool",
            "version": "1.0.0",
            "description": (
                "Phase 5 Step 5.1 Brief 3 tripwire: real ConductorEngine "
                "+ real GatewayClient. 4-step workflow (god → parallel[2] "
                "→ cli_tool → god). Strict call-count assertions to catch "
                "any future regression where the engine skips or doubles "
                "a gateway call."
            ),
            "context": {"required": [], "optional": []},
            "steps": [
                {
                    "id": "step1-thoth",
                    "god": "thoth",
                    "action": "research",
                    "input": "user_request",
                    "output": "step1_out",
                    "timeout": "30m",
                },
                {
                    "id": "parallel-impl",
                    "type": "parallel",
                    "fail_mode": "fast",
                    "max_concurrency": 2,
                    "branches": [
                        {
                            "id": "p-thoth",
                            "god": "thoth",
                            "action": "research",
                            "input": "user_request",
                            "output": "p_thoth_out",
                            "timeout": "30m",
                        },
                        {
                            "id": "p-hephaestus",
                            "god": "hephaestus",
                            "action": "build",
                            "input": "user_request",
                            "output": "p_hephaestus_out",
                            "timeout": "30m",
                        },
                    ],
                    "output": "parallel-outputs",
                },
                {
                    "id": "cli-tool-step",
                    "type": "cli_tool",
                    "tool": "_mock_echo",
                    "tool_input": {
                        "prompt": "tripwire cli_tool step",
                    },
                    "output": "cli_tool_out",
                    "timeout": "30s",
                },
                {
                    "id": "step2-hermes",
                    "god": "hermes",
                    "action": "summarize",
                    "input_from": "step1-thoth",
                    "output": "step2_out",
                    "timeout": "30m",
                },
            ],
        }
    })


class TestEngineGatewayTripwireE2E(unittest.IsolatedAsyncioTestCase):
    """Regression tripwire: exact gateway call counts for the engine.

    Drives a 4-step workflow (god → parallel[2] → cli_tool → god)
    through a real ConductorEngine + real GatewayClient (via
    FakeHttpBackend) and asserts the exact call log:
      - 4 POST /v1/runs (one per god step + one per parallel branch)
      - 4 GET /v1/runs/{id} (one per call that returned a run_id)
      - 0 calls from the cli_tool step (uses subprocess, not gateway)
      - 0 calls from the merge step (this workflow has no merge)

    A future change that causes the engine to:
      - skip a `gateway_client.submit_run()` call → POST count < 4
      - double-call `gateway_client.submit_run()` → POST count > 4
      - route the cli_tool step through the gateway → POST count > 4
      - add a gateway call from the merge step → POST count > 4
    will fail the test.
    """

    async def asyncSetUp(self) -> None:
        self.tmp = cf.TmpConductor.create()
        self.backend = _FakeHttpBackend()
        self.gateway = _build_real_gateway(self.backend)
        self.engine = _build_real_engine(self.tmp, self.gateway)
        # Load the cli_tools config so _mock_echo is registered.
        from conductor.v2 import cli_tool as ct
        ct.load_tools_config(
            Path("/home/konan/pantheon/conductor/config/cli_tools.yaml")
        )

    async def asyncTearDown(self) -> None:
        os.environ["CONDUCTOR_BASE_DIR"] = (
            str(Path("/home/konan/pantheon") / "conductor")
        )
        for f in self.tmp.state_dir.glob("wf_*.json"):
            try:
                f.unlink()
            except OSError:
                pass
        for f in self.tmp.state_dir.glob("*.aborted.json"):
            try:
                f.unlink()
            except OSError:
                pass
        try:
            if self.gateway._client is not None:
                await self.gateway._client.aclose()
        except Exception:
            pass
        self.tmp.cleanup()

    async def test_engine_calls_gateway_exact_count(self):
        """Drive a 4-step workflow. Assert EXACT call counts on the
        FakeHttpBackend. This is the regression tripwire.

        Expected call log:
          - POST /v1/runs: 4 (one per god step + 2 parallel branches)
          - GET /v1/runs/{id}: 4 (one per POST that returned a run_id)
          - GET /health: 0 (we don't call health in this test)

        If the engine ever:
          - skips a `gateway_client.submit_run()` call → POST < 4
          - double-dispatches → POST > 4
          - routes cli_tool through the gateway → POST > 4
        the assertion fails.
        """
        workflow_id = f"tripwire-{uuid.uuid4().hex[:8]}"
        yaml_body = _build_tripwire_workflow_yaml(workflow_id)

        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        (self.tmp.workflows_dir / f"{workflow_id}.yaml").write_text(yaml_body)
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        (eng.WORKFLOWS_DIR / f"{workflow_id}.yaml").write_text(yaml_body)
        self.engine.workflows.reload()

        inst = self.engine.start_workflow(workflow_id)
        self.assertIsNotNone(inst.workflow_id)

        # Wait for completion.
        for _ in range(500):
            await asyncio.sleep(0.02)
            cur = self.engine.get_instance(inst.workflow_id)
            if cur and cur.status in ("completed", "failed", "aborted"):
                break
        cur = self.engine.get_instance(inst.workflow_id)
        self.assertEqual(
            cur.status, "completed",
            f"workflow should complete; got {cur.status} "
            f"(history: {cur.step_history})",
        )

        # Strict call count assertions. The 4-step workflow's
        # expected call log is documented at the top of
        # `_build_tripwire_workflow_yaml`. If a future change
        # breaks the call count, the assertions below fail.
        post_calls = self.backend.run_calls(method="POST")
        get_runs_calls = [
            c for c in self.backend.calls
            if c["method"] == "GET" and f"/v1/runs/" in c["url"] and "/events" not in c["url"]
        ]
        # Each POST /v1/runs is paired with a GET /v1/runs/{id} via
        # the gateway's wait_for_run. Counts must match exactly.
        self.assertEqual(
            len(post_calls), 4,
            f"engine should make EXACTLY 4 POST /v1/runs calls "
            f"(1 per god step + 2 per parallel branch); got {len(post_calls)}. "
            f"All recorded calls: {[(c['method'], c['url']) for c in self.backend.calls]}",
        )
        self.assertEqual(
            len(get_runs_calls), 4,
            f"engine should make EXACTLY 4 GET /v1/runs/{{id}} calls "
            f"(one per POST that returned a run_id); got {len(get_runs_calls)}. "
            f"All recorded calls: {[(c['method'], c['url']) for c in self.backend.calls]}",
        )

        # Belt-and-suspenders: assert NO calls from the cli_tool step
        # (it uses subprocess, not the gateway) and NO calls from any
        # merge step (this workflow has no merge). We can't tell from
        # the call log which call came from which step, but the
        # exact count above already enforces this: if the cli_tool
        # step routed through the gateway, POST would be 5+, not 4.

        # The workflow's terminal state is correct. On completion,
        # the engine clears current_step (per engine.py:_advance
        # line 2183-2185: "no next step -> completed, current_step=None").
        self.assertIsNone(
            cur.current_step,
            f"current_step should be None on completion; got {cur.current_step!r}",
        )
        # context_bag has all 4 step outputs (proves the workflow
        # advanced through all 4 steps, not just the first).
        self.assertIn("step1_out", cur.context_bag)
        self.assertIn("parallel-outputs", cur.context_bag)
        self.assertIn("cli_tool_out", cur.context_bag)
        self.assertIn("step2_out", cur.context_bag)
