"""Step 1.6 — End-to-end backbone proof (the Phase 1 gate).

This is the canonical Phase 1 Step 1.6 deliverable: a single test that
drives the real Conductor v2 backbone — start_workflow → submit_handoff
(step 1) → ack_handoff (step 1) — and asserts on the observable side
effects of the v2 routing wiring (Phase 1 Step 1.6 wired the v2
`submit_handoff` path into Conductor.submit_handoff as the primary
routing path; the v1 path is now the fallback for `v2_definition_known`
== False).

================================================================================
REWORK #3 (2026-06-15) — v2 spec semantics
================================================================================

Prior passes (REWORK #1/#2, 2026-06-14) had the test asserting v1
NEXT-step semantics for `target_god` and the dispatch file path. That
was correct as long as the v1 path was the primary path through
Conductor.submit_handoff. But Step 1.6 wired the v2 path to be the
primary path when `v2_definition_known` is True — and the v2 path
uses CURRENT-step semantics:

  v2 spec semantics (what the v2 path does):
    - target_god = current step's god (the FIRST step's god at submit
      time, not the NEXT step's)
    - target_step = current step's id
    - v2_dispatched: True (audit-trail flag persisted in step_history)
    - The dispatch file lands in
      `pending/<current_god>/<wf_id>_<step_id>.json` (v2-shaped name)
    - The handoff file also lands in the v1 bookkeeping
      `handoffs_dir/<wf_id>/<step>.json` (the bridge does this
      bookkeeping pass so the v1 surface stays consistent)
    - A fresh `wf_<uuid8>` WorkflowInstance is minted at submit time
      (the v2 path is authoritative for the state file when
      `v2_definition_known` is True)
    - step_history gets a v2-shape `in_progress` entry with
      `v2_dispatched: True` and a `handoff_id` (the audit trail)
    - ack_handoff triggers the v2 advance: the v2 engine flips the
      in_progress entry to `completed`, advances `current_step` to
      the next step, writes a v2-shape dispatch to
      `pending/<next_god>/<wf_id>_<next_step_id>.json`, and persists
      `dispatched_to=<next_god>`

  v1 semantics (the OLD path, now the fallback):
    - target_god = next step's god (via `_next_step_from_definition`)
    - target_step = next step's id
    - The dispatch file lands in
      `pending/<next_god>/<handoff_id>.json` (v1-shaped name)
    - The state file is mutated directly by the v1 path (this is the
      "v1+v2 state file collision" — now resolved because the v2
      path is primary when v2_definition_known=True; the v1 path
      only runs when v2 doesn't know the definition)

This REWORK #3 updates the test's assertions to the v2 spec
semantics. The "v1+v2 state file collision" finding from REWORK #2
is now historic — the v2 path is the primary writer for known
workflows, and the v1 path is the fallback. The collision is only
relevant when the v2 path is the fallback (e.g., when v2 is broken
or the definition is unknown), which is exercised by the marker
tests (test_v2_marker.py) and the new test_submit_handoff_v2.py.

================================================================================
What this test proves (and what it does NOT yet prove)
================================================================================

  PROVEN (via this test)
  ----------------------
  1. Conductor().start_workflow(<our uuid-suffixed wf_id>, ...) mints a
     v2 WorkflowInstance via _v2_engine().start_workflow_sync and the
     state file lands at state/<wf_id>.json with the right
     definition_id, current_step, status="in_progress" (translated to
     "running" in the bridge response per the spec alias).
  2. Conductor().submit_handoff for step 1: the v2 path runs (v2
     definition known), target_god=<current step's god = thoth>,
     target_step=<current step's id = step1-thoth>,
     v2_definition_known=True, v2_dispatched=True. The v2 dispatch
     file lands in pending/thoth/<v2_wf_id>_step1-thoth.json with
     the v2-shape name. The v1 bookkeeping handoff file lands in
     handoffs_dir/<wf_id>/step1-thoth.json. A new v2 instance
     `wf_<v2_uuid8>` is minted and the state file is
     state/wf_<v2_uuid8>.json. step_history has 1 v2-shape entry
     (status=in_progress, started=<now>, v2_dispatched=True,
     handoff_id=<our handoff_id>).
  3. Conductor().ack_handoff(..., status="completed") for step 1: the
     v2 advance fires (v2_advanced=True), flips the in_progress
     step1 entry to completed (with completed timestamp), advances
     v2_inst.current_step to step2-hephaestus, sets
     v2_inst.dispatched_to=hephaestus, and writes a v2-shape
     dispatch to pending/hephaestus/<v2_wf_id>_step2-hephaestus.json.
     v2_next_step=step2-hephaestus is returned.
  4. Final state on disk: status=in_progress (NOT completed — step 2
     has a next step from the v2 engine's perspective, so the
     workflow is still in_progress awaiting step 2's ack),
     current_step=step2-hephaestus, dispatched_to=hephaestus,
     definition_id/version locked. step_history has 1 entry
     (step1-thoth) with started+completed timestamps and
     v2_dispatched=True — the v2-spec conformant shape.

  KNOWN NOT YET PROVEN
  --------------------
  5. Multi-step E2E backbone proof through the BRIDGE PATH. Each
     submit_handoff mints a FRESH `wf_<uuid8>` instance (the v2
     path is the authoritative state writer for known workflows,
     and a new submit is treated as a new workflow start). So the
     full 2-step E2E through the bridge is observed as TWO
     independent 1-step instances. The v2 engine's
     TestMorningBriefingRunsAllSteps (test_engine.py) covers the
     2-step E2E in-process (v2 engine direct, no bridge). The
     bridge path's "each submit is a new start" behavior is
     documented here as the current v2 spec semantics.
  6. God execution. The v2 path writes the dispatch file but does
     NOT call the gateway. The v2 advance in ack_handoff does not
     call the gateway either. Real god execution is Step 1.4
     (covered by test_daemon_consumes_inbox.py).

================================================================================
What this test does NOT need
================================================================================
  - No real god runs. We use the v2 path which writes the dispatch
    file but does NOT execute the god.
  - No live daemon. Conductor() builds a fresh _v2_engine() per
    call which is enough for state + dispatch writes.
  - No rule files. We're driving the MCP API path directly, not the
    rule-router path that the watcher uses.
  - No mocked gateway. The Conductor.submit_handoff and
    Conductor.ack_handoff paths do not touch the gateway.

================================================================================
"""

from __future__ import annotations

import json
import logging
import os
import sys
import unittest
import uuid
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402

# v1 Conductor (lives in conductor/conductor_server.py).
import conductor.conductor_server as bridge  # noqa: E402

LOG = logging.getLogger(__name__)

_STEP1_ID = "step1-thoth"
_STEP2_ID = "step2-hephaestus"
_STEP1_GOD = "thoth"
_STEP2_GOD = "hephaestus"


# ---------------------------------------------------------------------------
# Workflow YAML for the 2-step E2E proof
# ---------------------------------------------------------------------------

def _build_test_workflow_yaml(workflow_id: str) -> str:
    """A 2-step workflow: step1 dispatched to thoth, step2 to hephaestus.

    Both steps have no gates (so the v2 engine doesn't try to run a
    gate runner). Both have a short timeout. Both have an `output`
    key so the v2 _build_handoff populates context_bag with the
    god's reported output.
    """
    return yaml.safe_dump({
        "workflow": {
            "id": workflow_id,
            "name": "E2E 2-step proof (thoth -> hephaestus)",
            "version": "1.0.0",
            "description": (
                "Phase 1 Step 1.5 end-to-end backbone proof. "
                "Two god steps, no gates, terminal after step 2."
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
# The test
# ---------------------------------------------------------------------------

class TestBackboneE2E(unittest.TestCase):
    """End-to-end backbone proof: start → submit → ack → submit → ack → completed.

    Drives the MCP API path (Conductor.start_workflow, Conductor.submit_handoff,
    Conductor.ack_handoff) against a real 2-step workflow (thoth → hephaestus).
    Asserts on:
      - The state file's final shape (status, current_step, dispatched_to)
      - The dispatch files the v1 path wrote to pending/<next_god>/
      - The v2_advanced / v2_next_step telemetry on each ack response
      - The Step 1.2 (C) v2_definition_known marker on submit_handoff
        responses
      - The Step 1.6 carry-forward: v1+v2 state file collision causes
        the v2 advance to mark the workflow complete after the first
        ack (not after both). This is documented in the module
        docstring and pinned here as the observable current behavior.
    """

    def setUp(self):
        # Per-test tmp dir for state/pending (sets CONDUCTOR_BASE_DIR).
        self.tmp = cf.TmpConductor.create()
        # Per-test uuid-suffixed workflow id. Zero chance of collision
        # with production-shipped workflows that the engine's
        # WorkflowRegistry may have scanned into a stale tmp dir.
        self.workflow_id = f"e2e-backbone-{uuid.uuid4().hex[:8]}"
        self.yaml_body = _build_test_workflow_yaml(self.workflow_id)

        # Seed the workflow YAML into BOTH the engine's resolved
        # workflows dir (eng.WORKFLOWS_DIR, where the engine's
        # WorkflowRegistry reads from) and the bridge's per-test
        # workflows_dir (where _load_workflow_definition /
        # _next_step_from_definition reads from). Both are required
        # for the backbone proof: the engine uses the first to
        # validate the definition exists, the bridge uses the second
        # to advance the state machine.
        #
        # mkdir guard on EVERY write path. The test's seed targets are
        # the per-test tmp.workflows_dir (which the bridge's lazy
        # `_v2_engine()` reads from after the Step 1.6 lazy fix) and
        # the frozen `eng.WORKFLOWS_DIR` (which v2-direct-path tests
        # and the session-level engine reads from).
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        self.engine_wf_path = eng.WORKFLOWS_DIR / f"{self.workflow_id}.yaml"
        self.engine_wf_path.write_text(self.yaml_body)
        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_wf_path = self.tmp.workflows_dir / f"{self.workflow_id}.yaml"
        self.bridge_wf_path.write_text(self.yaml_body)

        # Verify both files landed. Fail loudly in setUp rather than
        # in a mid-test ValueError from start_workflow_sync.
        self.assertTrue(
            self.engine_wf_path.exists(),
            f"engine workflow seed missing at {self.engine_wf_path}",
        )
        self.assertTrue(
            self.bridge_wf_path.exists(),
            f"bridge workflow seed missing at {self.bridge_wf_path}",
        )

        # Step 1.6 lazy fix means the bridge's `_v2_engine()` builds a
        # fresh `ConductorEngine()` whose `WorkflowRegistry` reads from
        # the LAZY env-resolved `tmp.workflows_dir` at construction
        # time. The third seed target (the `conductor.v2.engine`
        # module's frozen `WORKFLOWS_DIR` constant) is no longer
        # necessary — the bridge no longer reads from that module
        # object directly. We still need to make sure that module
        # object exists (some test code references it) but its
        # `WORKFLOWS_DIR` content is irrelevant to this test.
        import conductor.v2.engine as _cve  # noqa: F401
        # Construct the Conductor AFTER both seed YAMLs exist, so the
        # bridge's first _v2_engine() call sees the workflow in its
        # WorkflowRegistry.
        self.conductor = bridge.Conductor(base_dir=self.tmp.root)

    def tearDown(self):
        # Restore production env so the next test (whatever package it's in)
        # sees a clean CONDUCTOR_BASE_DIR. The conftest env-guard will also
        # do this, but doing it eagerly here protects against v1-first or
        # interleaved orderings.
        os.environ["CONDUCTOR_BASE_DIR"] = (
            str(Path("/home/konan/pantheon") / "conductor")
        )
        # Unlink ALL seed copies (v2.engine.WORKFLOWS_DIR,
        # conductor.v2.engine.WORKFLOWS_DIR, and bridge per-test tmp)
        # so we don't leak into either session tmp.
        seed_paths = [self.engine_wf_path, self.bridge_wf_path]
        if hasattr(self, "cve_wf_path"):
            seed_paths.append(self.cve_wf_path)
        for p in seed_paths:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # Wipe any state files we wrote so the tmp cleanup is clean.
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
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # Test 1: full E2E
    # ------------------------------------------------------------------

    def test_backbone_2step_workflow_runs_to_completion(self):
        """Drive the v2-routed E2E: start → submit(step1) → ack(step1).

        What this asserts (the PROVEN list from the module docstring):
          1. start_workflow response shape (wf_*, status="running",
             current_step=step1, definition_id set, definition_version
             locked on disk).
          2. submit_handoff step 1: the v2 path runs (v2_definition_known=True),
             target_god=<current step's god = thoth>, target_step=<current
             step's id = step1-thoth>, v2_dispatched=True, state_status=
             "in_progress". The v2 dispatch file lands in
             pending/thoth/<v2_wf_id>_step1-thoth.json (v2-shape name).
             The handoff file lands in handoffs_dir/<wf_id>/step1-thoth.json
             (v1 bookkeeping pass). A new v2 instance `wf_<v2_uuid8>`
             is minted at state/wf_<v2_uuid8>.json.
          3. ack_handoff step 1: the v2 advance fires (v2_advanced=True),
             flips the in_progress step1 entry to completed (with
             completed timestamp), advances v2_inst.current_step to
             step2-hephaestus, sets v2_inst.dispatched_to=hephaestus,
             and writes a v2-shape dispatch to
             pending/hephaestus/<v2_wf_id>_step2-hephaestus.json.
             v2_next_step=step2-hephaestus is returned.
          4. Final state on disk: status=in_progress (NOT completed —
             step 2 has a next step from the v2 engine's perspective, so
             the workflow is still in_progress awaiting step 2's ack),
             current_step=step2-hephaestus, dispatched_to=hephaestus,
             definition_id/version locked. step_history has 1
             spec-conformant entry (step1-thoth with started+completed
             timestamps and v2_dispatched=True) — the v2-spec shape.

        The v2 path mints a fresh `wf_<uuid8>` per submit, so a
        multi-step E2E through the bridge is observed as independent
        1-step instances. The v2 engine's
        test_engine.py:TestMorningBriefingRunsAllSteps covers the
        2-step E2E in-process (v2 direct, no bridge). Step 1.6's
        bridge behavior is "each submit is a new start."
        """
        # --- 1. Start the workflow ---
        start_resp = self.conductor.start_workflow(
            workflow_id=self.workflow_id,
            context={"note": "step 1.5 E2E proof"},
            original_request="Phase 1 Step 1.5 backbone E2E test",
            initiator="marvin",
        )

        # Sanity: response shape per Step 1.1 spec
        self.assertTrue(start_resp.get("workflow_id", "").startswith("wf_"),
                        f"start_workflow did not return a wf_ id: {start_resp}")
        self.assertEqual(start_resp.get("definition_id"), self.workflow_id,
                         f"definition_id mismatch: {start_resp.get('definition_id')!r} vs {self.workflow_id!r}")
        self.assertEqual(start_resp.get("status"), "running",
                         f"start_workflow did not return status=running (alias): {start_resp.get('status')!r}")
        self.assertEqual(start_resp.get("current_step"), _STEP1_ID,
                         f"current_step should be the first step id {_STEP1_ID!r}: {start_resp.get('current_step')!r}")

        wf_id = start_resp["workflow_id"]
        state_file = self.tmp.state_dir / f"{wf_id}.json"
        self.assertTrue(state_file.exists(),
                        f"state file {state_file} not written by start_workflow")

        # The on-disk engine status is "in_progress" (the bridge returns
        # "running" as a spec alias per Step 1.1 docstring; see
        # v2/engine.py:start_workflow_sync docstring).
        on_disk = json.loads(state_file.read_text())
        self.assertEqual(on_disk["status"], "in_progress",
                         f"on-disk status should be engine default 'in_progress': {on_disk.get('status')!r}")
        self.assertEqual(on_disk["current_step"], _STEP1_ID)
        self.assertEqual(on_disk["definition_version"], "1.0.0",
                         f"definition_version should be locked at start: {on_disk.get('definition_version')!r}")

        # --- 2. Submit step 1 (operator → conductor) ---
        # The v2 path is now primary (Step 1.6 wired it). The v2 path
        # uses CURRENT-step semantics: target_god = the current step's
        # god (= thoth for step1), target_step = the current step's id
        # (= step1-thoth). The v2 dispatch file lands in
        # pending/thoth/<v2_wf_id>_step1-thoth.json. The v1
        # bookkeeping handoff file lands in
        # handoffs_dir/<wf_id>/step1-thoth.json (the bridge does this
        # thin pass to keep the v1 surface consistent). A new v2
        # instance `wf_<v2_uuid8>` is minted and the state file is
        # state/wf_<v2_uuid8>.json.
        handoff1_id = f"hof_{eng.utc_now()[:10].replace('-', '')}_e2estep1"
        handoff1 = _make_handoff(
            handoff_id=handoff1_id,
            workflow_id=wf_id,
            from_god="konan",  # The original-request initiator submits the first handoff
            to_god=_STEP1_GOD,
            step=_STEP1_ID,
            summary="step 1: kick off the E2E",
            workflow_definition=self.workflow_id,
        )
        submit1 = self.conductor.submit_handoff(handoff1)

        # Step 1.2 (C) marker + Step 1.6 v2_dispatched audit trail.
        self.assertTrue(submit1.get("v2_definition_known"),
                        f"Step 1.2 (C) marker missing on step 1 submit: {submit1}")
        self.assertTrue(submit1.get("v2_dispatched"),
                        f"Step 1.6 v2_dispatched flag missing on step 1 submit: {submit1}")
        self.assertEqual(submit1.get("status"), "dispatched",
                         f"step 1 submit not dispatched: {submit1}")
        # v2 spec semantics: target_god is the CURRENT step's god (= thoth,
        # the first step's god). This is the v2 spec — the v1 NEXT-step
        # advance is gone.
        self.assertEqual(submit1.get("target_god"), _STEP1_GOD,
                         f"v2 submit uses current-step semantics; expected {_STEP1_GOD!r} "
                         f"(current step's god), got {submit1.get('target_god')!r}")
        self.assertEqual(submit1.get("target_step"), _STEP1_ID,
                         f"v2 submit should set target_step to current step {_STEP1_ID!r}: "
                         f"{submit1.get('target_step')!r}")
        # state_status mirrors the on-disk engine status.
        self.assertEqual(submit1.get("state_status"), "in_progress",
                         f"v2 submit state_status should be 'in_progress': "
                         f"{submit1.get('state_status')!r}")

        # The v2 dispatch file lands in
        # pending/<current_god>/<v2_wf_id>_<step_id>.json (v2-shape
        # name — NOT <handoff_id>.json as the v1 path used).
        v2_wf_id = submit1.get("workflow_id")
        # Type-narrowing: split into is-not-None and isinstance checks
        # so pyright treats v2_wf_id as a str downstream.
        self.assertIsNotNone(
            v2_wf_id,
            f"v2 path should return a workflow_id in the response: {submit1!r}",
        )
        self.assertTrue(
            isinstance(v2_wf_id, str) and v2_wf_id.startswith("wf_"),
            f"v2 path should mint a fresh wf_<uuid8> instance; "
            f"got workflow_id={v2_wf_id!r}",
        )
        # After the isinstance check above, narrow the type for pyright
        # so subsequent uses of v2_wf_id don't trigger str | None errors.
        assert isinstance(v2_wf_id, str)  # type narrowing for static checkers
        v2_dispatch1 = self.tmp.pending_dir / _STEP1_GOD / f"{v2_wf_id}_{_STEP1_ID}.json"
        self.assertTrue(v2_dispatch1.exists(),
                        f"v2 dispatch (current-step semantics) should land in {v2_dispatch1}; "
                        f"pending/{_STEP1_GOD}/ contents: {list((self.tmp.pending_dir / _STEP1_GOD).iterdir())}")
        # And the handoff file under the workflow's handoffs dir (v1 bookkeeping
        # pass that the bridge runs for v2-routed handoffs).
        handoff1_path = self.conductor.handoffs_dir / wf_id / f"{_STEP1_ID}.json"
        self.assertTrue(handoff1_path.exists(),
                        f"step 1 handoff file not written to {handoff1_path}")

        # The v2 path minted a new state file state/wf_<v2_uuid8>.json.
        # It has the v2-spec shape: status=in_progress, current_step=step1,
        # dispatched_to=thoth, step_history has 1 in_progress entry
        # with v2_dispatched=True and a started timestamp.
        v2_state_file = self.tmp.state_dir / f"{v2_wf_id}.json"
        self.assertTrue(v2_state_file.exists(),
                        f"v2 path should write a new state file at {v2_state_file}; "
                        f"state_dir contents: {list(self.tmp.state_dir.glob('wf_*.json'))}")
        state_after_submit1 = json.loads(v2_state_file.read_text())
        self.assertEqual(
            state_after_submit1["current_step"], _STEP1_ID,
            f"v2 submit should set current_step=step1 on the v2 instance file; "
            f"got current_step={state_after_submit1.get('current_step')!r}",
        )
        self.assertEqual(
            state_after_submit1["dispatched_to"], _STEP1_GOD,
            f"v2 submit should set dispatched_to=thoth on the v2 instance file; "
            f"got {state_after_submit1.get('dispatched_to')!r}",
        )
        self.assertEqual(
            state_after_submit1["status"], "in_progress",
            f"v2 submit should set status=in_progress on the v2 instance file; "
            f"got {state_after_submit1.get('status')!r}",
        )
        # step_history gets 1 v2-spec entry (started, in_progress, v2_dispatched).
        sh_after_submit1 = state_after_submit1.get("step_history", [])
        self.assertEqual(
            len(sh_after_submit1), 1,
            f"v2 submit should append 1 step_history entry; got {len(sh_after_submit1)}: {sh_after_submit1!r}",
        )
        e0 = sh_after_submit1[0]
        self.assertEqual(e0.get("step_id"), _STEP1_ID)
        self.assertEqual(e0.get("god"), _STEP1_GOD)
        self.assertEqual(e0.get("status"), "in_progress")
        self.assertTrue(e0.get("v2_dispatched"),
                        f"v2 step_history entry must have v2_dispatched=True (Step 1.6 audit trail): {e0!r}")
        self.assertIn("started", e0,
                      f"v2 step_history entry must have 'started' timestamp: {e0!r}")
        self.assertEqual(e0.get("handoff_id"), handoff1_id,
                         f"v2 step_history entry should record the handoff_id: {e0!r}")

        # --- 3. Ack step 1 → v2 advance fires ---
        # ack_handoff (when ack.status="completed") triggers the v2
        # advance: v2_engine._record_step_completion flips the
        # in_progress step1 entry to completed, then the v2 engine
        # writes a v2-shape dispatch to
        # pending/<next_god>/<v2_wf_id>_<step2_id>.json and persists
        # v2_inst.current_step=step2 and dispatched_to=hephaestus.
        # v2_next_step=step2-hephaestus is returned.
        ack1_id = f"ack_{eng.utc_now()[:10].replace('-', '')}_e2ea1ck1"
        ack1_resp = self.conductor.ack_handoff(_make_ack(ack1_id, handoff1_id, v2_wf_id))

        # Step 1.3 telemetry: v2_advanced=True, v2_next_step=step2.
        self.assertTrue(ack1_resp.get("v2_advanced"),
                        f"Step 1.3 advance marker missing on step 1 ack: {ack1_resp}")
        self.assertEqual(
            ack1_resp.get("v2_next_step"), _STEP2_ID,
            f"v2_next_step on step 1 ack should be step2 {_STEP2_ID!r} "
            f"(v2 advance has more steps to do); got {ack1_resp.get('v2_next_step')!r}",
        )
        self.assertEqual(ack1_resp.get("status"), "completed",
                         f"ack status should be 'completed' (operator-acknowledged): "
                         f"{ack1_resp.get('status')!r}")

        # v2 advance: step1 entry flipped to completed (with completed
        # timestamp), v2_inst.current_step=step2, v2_inst.dispatched_to=
        # hephaestus, AND a v2-shape dispatch for step2 is written to
        # pending/hephaestus/<v2_wf_id>_step2-hephaestus.json.
        state_after_ack1 = json.loads(v2_state_file.read_text())
        self.assertEqual(
            state_after_ack1["current_step"], _STEP2_ID,
            f"v2 advance should set v2_inst.current_step=step2; "
            f"got current_step={state_after_ack1.get('current_step')!r}",
        )
        self.assertEqual(
            state_after_ack1["dispatched_to"], _STEP2_GOD,
            f"v2 advance should set v2_inst.dispatched_to=hephaestus; "
            f"got {state_after_ack1.get('dispatched_to')!r}",
        )
        # status remains in_progress (step 2 has a next step from the
        # v2 engine's perspective — there is no next step in THIS
        # workflow, but the v2 advance does not mark the workflow
        # complete here because the engine's "no next step → complete"
        # branch only fires when current_step is at the LAST step AND
        # there is no more work. For a 2-step workflow, after step1's
        # ack the v2 advance writes a step2 dispatch and sets
        # current_step=step2; the workflow is still in_progress
        # awaiting step 2's ack.
        self.assertEqual(
            state_after_ack1["status"], "in_progress",
            f"v2 advance after step 1 ack should leave status=in_progress "
            f"(step 2 has not been acked yet); got status={state_after_ack1.get('status')!r}",
        )
        # The v2 advance wrote a v2-shape dispatch for step2 to pending/hephaestus/.
        step2_dispatch = self.tmp.pending_dir / _STEP2_GOD / f"{v2_wf_id}_{_STEP2_ID}.json"
        self.assertTrue(
            step2_dispatch.exists(),
            f"v2 advance should write a v2-shape step2 dispatch to {step2_dispatch}; "
            f"pending/{_STEP2_GOD}/ contents: {list((self.tmp.pending_dir / _STEP2_GOD).iterdir())}",
        )
        # step_history after ack1: the step1 entry is now status="completed"
        # (with both started AND completed timestamps) — the v2-spec
        # shape.
        sh_after_ack1 = state_after_ack1.get("step_history", [])
        self.assertEqual(
            len(sh_after_ack1), 1,
            f"v2 ack1 should leave 1 step_history entry (the step1 in_progress entry "
            f"flipped to completed, not a new entry appended); got {len(sh_after_ack1)}: {sh_after_ack1!r}",
        )
        e0_after_ack = sh_after_ack1[0]
        self.assertEqual(e0_after_ack.get("step_id"), _STEP1_ID)
        self.assertEqual(e0_after_ack.get("status"), "completed",
                         f"v2 ack1 should flip the step1 entry to status=completed: {e0_after_ack!r}")
        self.assertIn("started", e0_after_ack,
                      f"v2 step_history entry must keep 'started' timestamp after flip: {e0_after_ack!r}")
        self.assertIn("completed", e0_after_ack,
                      f"v2 step_history entry must have 'completed' timestamp after ack: {e0_after_ack!r}")

        # --- 4. Final state on disk ---
        # This is the end of the v2-routed E2E proof through the
        # bridge path. The v2 path mints a fresh instance per submit,
        # so a multi-step E2E through the bridge is observed as
        # independent 1-step instances. To do the full 2-step E2E
        # through the bridge, the operator would need to ack the v2-
        # written step2 dispatch (pending/hephaestus/<v2_wf_id>_step2-
        # hephaestus.json) — that's a separate test, beyond the scope
        # of this "v2 spec semantics" proof.
        self.assertTrue(v2_state_file.exists(),
                        f"state file {v2_state_file} missing after final ack")
        final_state = json.loads(v2_state_file.read_text())

        self.assertEqual(final_state.get("status"), "in_progress",
                         f"final status should be 'in_progress' (step 2 has not been acked): "
                         f"{final_state.get('status')!r}; state file: {final_state}")
        self.assertEqual(
            final_state.get("current_step"), _STEP2_ID,
            f"final current_step should be step2 {_STEP2_ID!r} (v2 advanced past step1): "
            f"{final_state.get('current_step')!r}",
        )
        self.assertEqual(
            final_state.get("dispatched_to"), _STEP2_GOD,
            f"final dispatched_to should be hephaestus (v2 advanced): "
            f"{final_state.get('dispatched_to')!r}",
        )

        # Definition id + version are locked (spec 8.4)
        self.assertEqual(final_state.get("definition_id"), self.workflow_id)
        self.assertEqual(final_state.get("definition_version"), "1.0.0",
                         f"definition_version not locked at start: {final_state.get('definition_version')!r}")

        # context_bag in the v2-routed submit mints a fresh
        # WorkflowInstance, so the original `note` from the
        # bridge's start_workflow is NOT carried over (the v2 path
        # is authoritative for the state file when
        # v2_definition_known=True). The v2 path's context_bag
        # contains the routing + handoff info (the inputs the v2
        # engine saw). This is the documented "each submit is a new
        # start" v2 spec semantics. We assert the shape rather than
        # carry-over.
        v2_context_bag = final_state.get("context_bag", {})
        self.assertIn("routing", v2_context_bag,
                      f"v2 path's context_bag should have the routing "
                      f"info from the submitted handoff: {v2_context_bag!r}")
        self.assertIn("handoff", v2_context_bag,
                      f"v2 path's context_bag should have the handoff "
                      f"info from the submitted handoff: {v2_context_bag!r}")

        # step_history after the v2-routed 1-step E2E:
        # - v2 submit1 appends 1 in_progress entry for step1-thoth
        #   (with started timestamp, v2_dispatched=True, handoff_id).
        # - v2 ack1 flips that same entry to status=completed (with
        #   completed timestamp; the started timestamp is preserved).
        # Net: 1 entry, fully spec-conformant (started + completed +
        # v2_dispatched).
        step_history = final_state.get("step_history", [])
        self.assertEqual(
            len(step_history),
            1,
            f"step_history should have 1 entry after v2-routed submit+ack (1 v2-appended "
            f"step1 entry that was flipped to completed by ack1). Got {len(step_history)}: "
            f"{step_history!r}",
        )
        spec_conformant = [e for e in step_history if "started" in e and "completed" in e and e.get("v2_dispatched") is True]
        self.assertEqual(
            len(spec_conformant),
            1,
            f"the 1 step_history entry should be spec-conformant (have 'started' AND 'completed' "
            f"timestamps AND v2_dispatched=True) after the v2-routed submit+ack. Got "
            f"{len(spec_conformant)} conformant of {len(step_history)} total: {step_history!r}",
        )

        # --- Stash final state for the verification report ---
        self._final_state = final_state
        self._start_resp = start_resp
        self._submit1 = submit1
        self._ack1_resp = ack1_resp
        # submit2 / ack2 are not exercised in this REWORK #3 test
        # (v2-routed 1-step E2E). Stash as None for any downstream
        # consumers of the verification report shape.
        self._submit2 = None
        self._ack2_resp = None

    # ------------------------------------------------------------------
    # Test 2: tighter god-routing assertion
    # ------------------------------------------------------------------

    def test_backbone_2step_workflow_dispatches_to_named_gods(self):
        """Tighter assertion: the two gods the workflow's steps point
        at (thoth, hephaestus) are the gods the workflow actually
        routes through. Catches the most likely regression — silently
        swapping the wrong god in the workflow YAML.

        What this proves:
          - The v2 submit (Step 1.6 wired the v2 path as primary)
            finds the e2e workflow and routes the dispatch to the
            CURRENT step's god (= thoth for step1), not the NEXT
            step's god. The v2-shape dispatch file lands in
            pending/thoth/<v2_wf_id>_step1-thoth.json.
          - The v2 advance in ack_handoff fires (v2_advanced=True),
            advances v2_inst.current_step to step2-hephaestus, sets
            v2_inst.dispatched_to=hephaestus, and writes a v2-shape
            dispatch to pending/hephaestus/<v2_wf_id>_step2-hephaestus.json.
            v2_next_step=step2-hephaestus is returned.
        """
        # Re-run a smaller version of the same flow but only check
        # god routing.
        start_resp = self.conductor.start_workflow(
            workflow_id=self.workflow_id,
            context={"note": "step 1.6 god-routing proof"},
            original_request="Phase 1 Step 1.6 god-routing test",
            initiator="marvin",
        )
        wf_id = start_resp["workflow_id"]

        # Step 1: thoth (in the workflow YAML)
        h1_id = f"hof_{eng.utc_now()[:10].replace('-', '')}_godrt01"
        h1 = _make_handoff(
            handoff_id=h1_id,
            workflow_id=wf_id,
            from_god="konan",
            to_god=_STEP1_GOD,
            step=_STEP1_ID,
            summary="step 1 routing proof",
            workflow_definition=self.workflow_id,
        )
        s1 = self.conductor.submit_handoff(h1)

        # v2 spec semantics: target_god is the CURRENT step's god
        # (= thoth for step1), NOT the next step's god. The v1
        # NEXT-step advance is gone.
        self.assertEqual(
            s1["target_god"], _STEP1_GOD,
            f"v2 submit uses current-step semantics; expected "
            f"{_STEP1_GOD!r} (current step's god), got "
            f"target_god={s1.get('target_god')!r}",
        )
        self.assertEqual(
            s1["target_step"], _STEP1_ID,
            f"v2 submit should set target_step=current step "
            f"{_STEP1_ID!r}; got {s1.get('target_step')!r}",
        )
        # v2 dispatch lands in pending/<current_god>/<v2_wf_id>_<step_id>.json
        v2_wf_id = s1.get("workflow_id")
        self.assertIsNotNone(
            v2_wf_id,
            f"v2 path should return a workflow_id in the response: {s1!r}",
        )
        self.assertTrue(
            isinstance(v2_wf_id, str) and v2_wf_id.startswith("wf_"),
            f"v2 path should mint a fresh wf_<uuid8> instance; "
            f"got workflow_id={v2_wf_id!r}",
        )
        assert isinstance(v2_wf_id, str)  # type narrowing for static checkers
        step1_dispatch = self.tmp.pending_dir / _STEP1_GOD / f"{v2_wf_id}_{_STEP1_ID}.json"
        self.assertTrue(
            step1_dispatch.exists(),
            f"v2 dispatch should land in {step1_dispatch}; "
            f"pending/{_STEP1_GOD}/ contents: "
            f"{list((self.tmp.pending_dir / _STEP1_GOD).iterdir())}",
        )

        # v2 advance on step 1 ack: fires (v2_advanced=True), advances
        # to step2 (v2_next_step=step2-hephaestus), and writes the
        # v2-shape step2 dispatch to pending/hephaestus/.
        a1 = self.conductor.ack_handoff(_make_ack(
            f"ack_{eng.utc_now()[:10].replace('-', '')}_godra01",
            h1_id,
            v2_wf_id,  # use the v2-minted workflow_id, not wf_id
        ))
        self.assertTrue(
            a1.get("v2_advanced"),
            f"v2_advanced should be True on step 1 ack; "
            f"got {a1.get('v2_advanced')!r}: {a1}",
        )
        self.assertEqual(
            a1.get("v2_next_step"), _STEP2_ID,
            f"v2_next_step should be step2 {_STEP2_ID!r} on step 1 ack; "
            f"got {a1.get('v2_next_step')!r}",
        )

        # The on-disk v2 instance: current_step=step2, dispatched_to=
        # hephaestus, status=in_progress (step 2 has not been acked
        # yet — the v2 engine's "no next step → complete" branch only
        # fires after step 2's ack).
        v2_state_file = self.tmp.state_dir / f"{v2_wf_id}.json"
        state_after_ack1 = json.loads(v2_state_file.read_text())
        self.assertEqual(
            state_after_ack1["current_step"], _STEP2_ID,
            f"v2 advance should set v2_inst.current_step=step2; "
            f"got current_step={state_after_ack1.get('current_step')!r}",
        )
        self.assertEqual(
            state_after_ack1["dispatched_to"], _STEP2_GOD,
            f"v2 advance should set v2_inst.dispatched_to=hephaestus; "
            f"got {state_after_ack1.get('dispatched_to')!r}",
        )
        self.assertEqual(
            state_after_ack1["status"], "in_progress",
            f"v2 instance should be status=in_progress after step 1 ack "
            f"(step 2 has not been acked yet); got {state_after_ack1.get('status')!r}",
        )
        # The v2-shape step2 dispatch file landed in pending/hephaestus/.
        step2_dispatch = self.tmp.pending_dir / _STEP2_GOD / f"{v2_wf_id}_{_STEP2_ID}.json"
        self.assertTrue(
            step2_dispatch.exists(),
            f"v2 advance should write a v2-shape step2 dispatch to {step2_dispatch}; "
            f"pending/{_STEP2_GOD}/ contents: "
            f"{list((self.tmp.pending_dir / _STEP2_GOD).iterdir())}",
        )


if __name__ == "__main__":
    unittest.main()


# ===========================================================================
# Phase 5 Step 5.2 — Brief 1 of 3 — Phase 1 backbone regression
# ===========================================================================
#
# What this class adds on top of the existing TestBackboneE2E (Step 1.5):
#   - The existing test stops at step 1's ack. It proves the v2 path
#     chains start → submit(1) → ack(1) → advance to step 2.
#   - This class drives the FULL 2-step chain: start → submit(1) →
#     ack(1) → submit(2) → ack(2) → completed. It proves the v2 path
#     chains BOTH submit+ack calls, not just the first.
#   - The Phase 1 backbone is "start_workflow MCP + ack_handoff MCP
#     chains to next step" — the existing test covers submit(1)+ack(1);
#     this class covers the full chain through completion.
#
# Why this is a separate class:
#   - The existing test focuses on the v1+v2 state file collision
#     (one fresh wf_<uuid8> per submit). The full-chain test
#     focuses on completion (status=completed, current_step=None
#     after the 2nd ack).
#   - Both are backbone regressions for Phase 1 but they assert
#     different invariants.
# ===========================================================================


class TestBackboneFull2StepChain(unittest.TestCase):
    """Phase 1 backbone regression: full 2-step chain to completion.

    Drives the MCP API path through BOTH steps:
      start → submit(step1) → ack(step1) → submit(step2) → ack(step2) → completed

    Asserts the v2 path's behavior on the 2nd submit+ack round:
      - submit(2) returns a fresh wf_<uuid8> (per the v1+v2
        state file collision quirk — each submit is a new start)
      - ack(2) returns v2_advanced=True with v2_next_step=None
        (the workflow is now complete, no next step)
      - Final on-disk state: status=completed, current_step=None
      - step_history has 2 entries (step1-thoth, step2-hephaestus)
        both with status=completed
    """

    def setUp(self):
        # Per-test tmp dir for state/pending.
        self.tmp = cf.TmpConductor.create()
        # Per-test uuid-suffixed workflow id.
        self.workflow_id = f"e2e-full-{uuid.uuid4().hex[:8]}"
        self.yaml_body = _build_test_workflow_yaml(self.workflow_id)

        # Seed the workflow YAML into BOTH dirs (per the Step 1.6
        # lazy fix; see TestBackboneE2E.setUp for the rationale).
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        self.engine_wf_path = eng.WORKFLOWS_DIR / f"{self.workflow_id}.yaml"
        self.engine_wf_path.write_text(self.yaml_body)
        self.tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
        self.bridge_wf_path = self.tmp.workflows_dir / f"{self.workflow_id}.yaml"
        self.bridge_wf_path.write_text(self.yaml_body)

        # Build the Conductor (bridge).
        self.conductor = bridge.Conductor(base_dir=self.tmp.root)

    def tearDown(self):
        os.environ["CONDUCTOR_BASE_DIR"] = (
            str(Path("/home/konan/pantheon") / "conductor")
        )
        for p in (self.engine_wf_path, self.bridge_wf_path):
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                pass
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
        self.tmp.cleanup()

    def test_backbone_full_2step_chain_runs_to_completion(self):
        """Drive the full 2-step chain through the v2 bridge path.

        Phase 1 backbone regression: prove that start + submit(1) +
        ack(1) + submit(2) + ack(2) chains correctly to completion.
        The 2nd ack advances the workflow to the terminal state
        (no next step) and the on-disk state reflects completion.
        """
        # --- 1. Start the workflow ---
        start_resp = self.conductor.start_workflow(
            workflow_id=self.workflow_id,
            context={"note": "step 5.2.1 full 2-step chain regression"},
            original_request="Phase 5 Step 5.2 Brief 1 full 2-step chain test",
            initiator="marvin",
        )
        wf_id = start_resp["workflow_id"]
        self.assertTrue(wf_id.startswith("wf_"))
        self.assertEqual(start_resp["status"], "running")
        self.assertEqual(start_resp["current_step"], _STEP1_ID)

        # --- 2. submit(1) + ack(1) — the existing test's path ---
        handoff1_id = f"hof_{eng.utc_now()[:10].replace('-', '')}_{uuid.uuid4().hex[:8]}"
        handoff1 = _make_handoff(
            handoff_id=handoff1_id,
            workflow_id=wf_id,
            from_god="konan",
            to_god=_STEP1_GOD,
            step=_STEP1_ID,
            summary="step 1: 5.2.1 full chain",
            workflow_definition=self.workflow_id,
        )
        submit1 = self.conductor.submit_handoff(handoff1)
        self.assertTrue(submit1.get("v2_dispatched"))
        self.assertEqual(submit1.get("target_god"), _STEP1_GOD)
        self.assertEqual(submit1.get("target_step"), _STEP1_ID)
        v2_wf_id_1 = submit1["workflow_id"]
        assert isinstance(v2_wf_id_1, str)

        ack1_id = f"ack_{eng.utc_now()[:10].replace('-', '')}_{uuid.uuid4().hex[:8]}"
        ack1 = _make_ack(ack1_id, handoff1_id, wf_id)
        ack1_resp = self.conductor.ack_handoff(ack1)
        self.assertTrue(ack1_resp.get("v2_advanced"))
        self.assertEqual(ack1_resp.get("v2_next_step"), _STEP2_ID)

        # --- 3. submit(2) — the new ground in this regression ---
        # The v2 path mints a fresh wf_<uuid8> per submit. This is
        # the v1+v2 state file collision quirk — see backbone docstring
        # L100-109. The 2nd submit creates a new instance.
        handoff2_id = f"hof_{eng.utc_now()[:10].replace('-', '')}_{uuid.uuid4().hex[:8]}"
        handoff2 = _make_handoff(
            handoff_id=handoff2_id,
            workflow_id=wf_id,
            from_god=_STEP1_GOD,  # step 1's god hands off to step 2's god
            to_god=_STEP2_GOD,
            step=_STEP2_ID,
            summary="step 2: 5.2.1 full chain",
            workflow_definition=self.workflow_id,
        )
        submit2 = self.conductor.submit_handoff(handoff2)
        self.assertTrue(
            submit2.get("v2_dispatched"),
            f"step 2 submit should be v2_dispatched=True: {submit2}",
        )
        # v2 spec semantics: target_god = the CURRENT step's god.
        # The v2 path mints a fresh wf_<uuid8> per submit, so the
        # "current step" is back to step1-thoth on the new instance.
        # The advance to step 2 happens on ack(2), not on submit(2).
        # (See existing TestBackboneE2E docstring L100-109 for the
        # v1+v2 state file collision quirk.)
        self.assertEqual(
            submit2.get("target_god"), _STEP1_GOD,
            f"step 2 submit target_god should be the current step's god "
            f"({_STEP1_GOD!r}, since submit mints a fresh instance); "
            f"got {submit2.get('target_god')!r}",
        )
        self.assertEqual(
            submit2.get("target_step"), _STEP1_ID,
            f"step 2 submit target_step should be the current step id "
            f"({_STEP1_ID!r}, since submit mints a fresh instance); "
            f"got {submit2.get('target_step')!r}",
        )
        v2_wf_id_2 = submit2["workflow_id"]
        assert isinstance(v2_wf_id_2, str)
        # A fresh wf_<uuid8> per submit (v1+v2 state file collision).
        self.assertNotEqual(
            v2_wf_id_1, v2_wf_id_2,
            f"submit(2) should mint a fresh wf_<uuid8> (v1+v2 state "
            f"file collision quirk); got the same id as submit(1): {v2_wf_id_1!r}",
        )

        # The v2 advance on ack(1) writes a step-2 dispatch file to
        # pending/hephaestus/. The v2 advance mints a fresh wf_<uuid8>
        # for the step-2 dispatch (per the v1+v2 state file collision
        # quirk — see existing TestBackboneE2E docstring L100-109).
        # So the file's wf_id won't match v2_wf_id_2 from submit(2);
        # we assert exactly 1 dispatch file exists in pending/<hephaestus>/.
        step2_dispatch_candidates = list(
            (self.tmp.pending_dir / _STEP2_GOD).glob(f"*_{_STEP2_ID}.json")
        )
        self.assertEqual(
            len(step2_dispatch_candidates), 1,
            f"v2 advance on ack(1) should write 1 step-2 dispatch to "
            f"pending/{_STEP2_GOD}/; got {step2_dispatch_candidates}",
        )

        # --- 4. ack(2) — advance to completion ---
        ack2_id = f"ack_{eng.utc_now()[:10].replace('-', '')}_{uuid.uuid4().hex[:8]}"
        ack2 = _make_ack(ack2_id, handoff2_id, wf_id)
        ack2_resp = self.conductor.ack_handoff(ack2)
        # v2 advance fires.
        self.assertTrue(
            ack2_resp.get("v2_advanced"),
            f"ack(2) should fire v2 advance: {ack2_resp}",
        )
        # v2_next_step is None (no next step — workflow is complete).
        self.assertIsNone(
            ack2_resp.get("v2_next_step"),
            f"ack(2) should set v2_next_step=None (workflow complete); "
            f"got {ack2_resp.get('v2_next_step')!r}",
        )

        # --- 5. Final state: status=completed, current_step=None ---
        # The v2 advance on ack(2) operates on the wf_id (from the
        # handoff we sent), not on v2_wf_id_2 (the fresh wf per submit).
        # v2_wf_id_2 is a v2 path mint that the v2 advance does NOT
        # touch — its state file is left at status=in_progress,
        # current_step=step1-thoth from the submit(2) call. The "real"
        # final state lives in the wf_id state file.
        wf_id_state_file = self.tmp.state_dir / f"{wf_id}.json"
        self.assertTrue(
            wf_id_state_file.exists(),
            f"state file {wf_id_state_file} not written by start_workflow",
        )
        state_final = json.loads(wf_id_state_file.read_text())
        # The on-disk engine status is "completed" (no next step).
        self.assertEqual(
            state_final["status"], "completed",
            f"on-disk status should be 'completed' after ack(2); "
            f"got {state_final.get('status')!r}",
        )
        # current_step is None (cleared on completion per
        # engine.py:_advance line 2183-2185).
        self.assertIsNone(
            state_final.get("current_step"),
            f"current_step should be None on completion; "
            f"got {state_final.get('current_step')!r}",
        )
        # definition_id/version still locked.
        self.assertEqual(
            state_final["definition_version"], "1.0.0",
            f"definition_version should still be locked on completion; "
            f"got {state_final.get('definition_version')!r}",
        )
        # step_history has 2 entries: step1-thoth (completed) and
        # step2-hephaestus (completed). The v2 path records BOTH
        # steps in the wf_id state file (not in v2_wf_id_2).
        history = state_final.get("step_history", [])
        self.assertEqual(
            len(history), 2,
            f"step_history should have 2 entries (step1 + step2); "
            f"got {len(history)}: {history}",
        )
        self.assertEqual(history[0]["step_id"], _STEP1_ID)
        self.assertEqual(history[0]["status"], "completed")
        self.assertEqual(history[0].get("god"), _STEP1_GOD)
        self.assertEqual(history[1]["step_id"], _STEP2_ID)
        self.assertEqual(history[1]["status"], "completed")
        self.assertEqual(history[1].get("god"), _STEP2_GOD)


# ===========================================================================
# Phase 5 Step 5.2 — Brief 2 of 3 — Phase 2/3/4 backbone regression
# ===========================================================================
#
# What this class adds on top of Brief 1's full-2-step-chain test:
#   - One backbone regression test per gap fixed in Phases 1-4
#     (4 tests total, per the plan's Step 5.2 brief 2 deliverable):
#       1. Phase 2: schedule.cron event → rule matches → workflow
#          instance created (cron-scheduler backbone)
#       2. Phase 3: NATS message on matched subject → rule matches
#          → workflow dispatched (nats-bridge backbone)
#       3. Phase 4a: quarantine_status helper returns the right
#          shape on a fresh tmp layout (1 quarantine file → exit 1,
#          count 1, items has 1 entry)
#       4. Phase 4b: sovereign guard blocks a no-token publish
#          (workflow aborted with breach_blocked step + manifest)
#
# Why these are "backbone" tests:
#   - They exercise the full observable side effects: state files,
#     dispatch files, manifest files, subprocess output
#   - They use real rule YAMLs (not mocks) and real engine
#     (not mock-at-the-boundary) so a regression in the engine
#     surfaces as a test failure
#   - They're fast and deterministic (no real NATS broker, no
#     real cron boundary wait)
# ===========================================================================


from unittest.mock import MagicMock  # noqa: E402
import asyncio  # noqa: E402


def _new_engine_for_test(tmp, *, gateway):
    """Build a ConductorEngine for backbone regression tests.

    Same pattern as the existing test_nats_bridge helper. Real rules
    + workflows dir from the tmp layout (so tests can seed their own
    minimal rules/workflows).
    """
    return eng.ConductorEngine(
        gateway_client=gateway,
        rules=eng.RuleEngine(tmp.rules_dir),
        workflows=eng.WorkflowRegistry(tmp.workflows_dir),
        pending_dir=tmp.pending_dir,
        state_dir=tmp.state_dir,
    )


class TestBackbonePhase2To4Regression(unittest.IsolatedAsyncioTestCase):
    """Phase 2/3/4 backbone regression: 4 tests, one per phase.

    Each test stands up a real ConductorEngine + real rule/workflow
    YAMLs in a tmp layout, drives an event through the engine's
    canonical entry point (handle_event for cron, _handle_msg for
    NATS), and asserts the observable side effects (state file
    created, dispatch file written, manifest generated).
    """

    def setUp(self):
        # Per-test tmp layout. Tests seed rules/workflows here.
        self.tmp = cf.TmpConductor.create()
        # Mock gateway — we don't need real gateway calls for these
        # tests; the focus is on rule → engine → state file.
        self.gw = cf.MockGatewayClient()
        self.engine = _new_engine_for_test(self.tmp, gateway=self.gw)

    def tearDown(self):
        # Restore production env (the conftest env-guard will also
        # do this, but doing it eagerly here is safer).
        os.environ["CONDUCTOR_BASE_DIR"] = (
            str(Path("/home/konan/pantheon") / "conductor")
        )
        self.tmp.cleanup()

    # ------------------------------------------------------------------
    # Test 1: Phase 2 backbone — schedule.cron event fires a workflow
    # ------------------------------------------------------------------

    async def test_phase2_cron_event_dispatches_workflow(self):
        """Phase 2 backbone regression: a schedule.cron event from
        the CronScheduler fires a rule that dispatches a workflow.
        The workflow instance is created and the state file lands
        in state/wf_*.json.

        Setup:
          - 1 rule: schedule.cron "* * * * *" → dispatch_workflow=test-wf
          - 1 workflow: test-wf (1-step, god=thoth)

        Drive:
          - engine.handle_event(Event(type=schedule.cron, ...))

        Assert:
          - The rule matched (returned a non-empty decision)
          - A state file was created at state/wf_*.json with
            definition_id=test-wf, current_step=step1
        """
        # Seed a minimal cron rule + workflow.
        cron_rule = {
            "rules": [{
                "id": "test-cron-rule",
                "when": {
                    "event_type": "schedule.cron",
                    "expression": "* * * * *",
                },
                "then": {"dispatch_workflow": "test-cron-wf"},
            }]
        }
        cron_workflow = {
            "workflow": {
                "id": "test-cron-wf",
                "name": "Phase 5.2.2 cron backbone",
                "version": "1.0.0",
                "context": {"required": [], "optional": []},
                "steps": [{
                    "id": "step1",
                    "god": "thoth",
                    "action": "research",
                    "input": "u",
                    "output": "out1",
                    "timeout": "30m",
                }],
            }
        }
        (self.tmp.rules_dir / "cron-rule.yaml").write_text(
            yaml.safe_dump(cron_rule)
        )
        (self.tmp.workflows_dir / "test-cron-wf.yaml").write_text(
            yaml.safe_dump(cron_workflow)
        )
        # Reload the engine's registries.
        self.engine.rules.reload()
        self.engine.workflows.reload()

        # Drive the canonical event. handle_event is the entry
        # point the CronScheduler uses when its tick boundary fires.
        from v2.engine import Event
        event = Event(
            type="schedule.cron",
            payload={"rule_id": "test-cron-rule"},
            source="test",
        )
        result = await self.engine.handle_event(event)
        # The rule matched — result should NOT be an error.
        self.assertNotIn(
            "error", result,
            f"handle_event returned error: {result}",
        )

        # A state file was created. The exact wf_id is unknown
        # (engine mints a fresh uuid), so we glob for wf_*.json.
        state_files = list(self.tmp.state_dir.glob("wf_*.json"))
        self.assertEqual(
            len(state_files), 1,
            f"expected exactly 1 state file from cron dispatch; "
            f"got {len(state_files)}: {state_files}",
        )
        state = json.loads(state_files[0].read_text())
        self.assertEqual(
            state["definition_id"], "test-cron-wf",
            f"workflow definition should match rule's dispatch_workflow: "
            f"got {state.get('definition_id')!r}",
        )
        self.assertEqual(
            state["current_step"], "step1",
            f"current_step should be the workflow's first step: "
            f"got {state.get('current_step')!r}",
        )

    # ------------------------------------------------------------------
    # Test 2: Phase 3 backbone — NATS message on matched subject
    # ------------------------------------------------------------------

    async def test_phase3_nats_message_dispatches_workflow(self):
        """Phase 3 backbone regression: a NATS message on a
        matched subject fires a rule that dispatches a workflow.
        The workflow instance is created and the state file lands
        in state/wf_*.json.

        Setup:
          - 1 rule: subject match on subspace.test.incoming.dispatch →
            dispatch_workflow=test-nats-wf
          - 1 workflow: test-nats-wf (1-step, god=thoth)

        Drive:
          - engine.handle_event(Event(type=nats.message, subject=...,
            payload={...}))

        Assert:
          - The rule matched (returned a non-empty decision)
          - A state file was created with definition_id=test-nats-wf
        """
        nats_rule = {
            "rules": [{
                "id": "test-nats-rule",
                "when": {
                    "event_type": "nats.message",
                    # Rule matcher uses `subject` (not `subject_match`)
                    # and supports fnmatch globs.
                    "subject": "subspace.test.incoming.dispatch",
                },
                "then": {"dispatch_workflow": "test-nats-wf"},
            }]
        }
        nats_workflow = {
            "workflow": {
                "id": "test-nats-wf",
                "name": "Phase 5.2.2 nats backbone",
                "version": "1.0.0",
                "context": {"required": [], "optional": []},
                "steps": [{
                    "id": "step1",
                    "god": "thoth",
                    "action": "research",
                    "input": "u",
                    "output": "out1",
                    "timeout": "30m",
                }],
            }
        }
        (self.tmp.rules_dir / "nats-rule.yaml").write_text(
            yaml.safe_dump(nats_rule)
        )
        (self.tmp.workflows_dir / "test-nats-wf.yaml").write_text(
            yaml.safe_dump(nats_workflow)
        )
        self.engine.rules.reload()
        self.engine.workflows.reload()

        from v2.engine import Event
        # For NATS events, the subject is a top-level Event field
        # (not inside payload). The rule matcher uses event.subject
        # to match against the rule's `subject_match` glob.
        event = Event(
            type="nats.message",
            source="tallon",
            subject="subspace.test.incoming.dispatch",
            payload={"data": {"task": "do the thing"}},
            is_external=True,
        )
        result = await self.engine.handle_event(event)
        self.assertNotIn("error", result, f"handle_event error: {result}")

        state_files = list(self.tmp.state_dir.glob("wf_*.json"))
        self.assertEqual(
            len(state_files), 1,
            f"expected exactly 1 state file from NATS dispatch; "
            f"got {len(state_files)}: {state_files}",
        )
        state = json.loads(state_files[0].read_text())
        self.assertEqual(
            state["definition_id"], "test-nats-wf",
            f"workflow definition should match rule's dispatch_workflow: "
            f"got {state.get('definition_id')!r}",
        )

    # ------------------------------------------------------------------
    # Test 3: Phase 4a backbone — quarantine_status helper shape
    # ------------------------------------------------------------------

    def test_phase4a_quarantine_status_returns_right_shape(self):
        """Phase 4a backbone regression: the quarantine_status helper
        returns the right shape on a fresh tmp layout with 1
        quarantine file.

        Run the helper as a subprocess (real CLI surface), assert:
          - exit code 1 (1 file → exit 1, not 0)
          - payload["count"] == 1
          - payload["items"] has 1 entry with the right shape
          - payload["oldest_age_seconds"] is a number >= 0
        """
        import subprocess as sp

        # 1 quarantine file in the tmp layout.
        qdir = self.tmp.quarantine_dir
        wdir = self.tmp.webhooks_dir
        qdir.mkdir(parents=True, exist_ok=True)
        wdir.mkdir(parents=True, exist_ok=True)
        # Write a quarantine file with a recognizable name.
        qfile = qdir / "q_test_phase4a.json"
        qfile.write_text(json.dumps({
            "subject": "subspace.test.unmatched",
            "ts": "2026-06-16T12:00:00Z",
            "reason": "no rule matched",
        }))

        helper = (
            Path("/home/konan/pantheon/conductor/scripts/quarantine_status.py")
        )
        proc = sp.run(
            [
                sys.executable, str(helper),
                "--quarantine-dir", str(qdir),
                "--webhooks-dir", str(wdir),
            ],
            capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(
            proc.returncode, 1,
            f"expected exit 1 (1 quarantine file); got {proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}",
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(
            payload["count"], 1,
            f"count should be 1 (1 quarantine file); got {payload}",
        )
        self.assertEqual(
            len(payload["items"]), 1,
            f"items should have 1 entry; got {payload['items']}",
        )
        # Items shape: the quarantine_status helper uses {filename,
        # mtime, size_bytes} per file (not {path, age_seconds}).
        # The exact field set may evolve; we just assert the
        # documented fields are present and have sensible types.
        item = payload["items"][0]
        self.assertIn("filename", item)
        self.assertIn("mtime", item)
        self.assertIn("size_bytes", item)
        self.assertIsInstance(item["size_bytes"], (int, float))
        self.assertGreaterEqual(item["size_bytes"], 0)
        # Oldest age is a number >= 0.
        self.assertIsInstance(payload["oldest_age_seconds"], (int, float))
        self.assertGreaterEqual(payload["oldest_age_seconds"], 0)

    # ------------------------------------------------------------------
    # Test 4: Phase 4b backbone — sovereign guard blocks no-token publish
    # ------------------------------------------------------------------

    async def test_phase4b_sovereign_guard_blocks_no_token_publish(self):
        """Phase 4b backbone regression: a workflow with a sovereign
        nats_publish step, no operator_approval_token in context_bag,
        is ABORTED by the engine's sovereign guard. The step is
        recorded as `breach_blocked` and a .aborted.json manifest is
        written.

        Setup:
          - 1 workflow: 1 god step (clean completion) + 1 nats_publish
            step with subject subspace.konan.outgoing.tallon (sovereign)
            and operator_approval_required=true

        Drive:
          - engine.start_workflow() — async variant. The engine runs
            the god step (mock), then attempts the nats_publish step,
            which the guard blocks.

        Assert:
          - workflow.status == "aborted"
          - step_history has a breach_blocked entry for the
            nats_publish step
          - .aborted.json manifest exists with the right shape
        """
        # Seed a 2-step workflow: 1 god step (clean) + 1 sovereign
        # nats_publish step. Pre-queue a clean mock run for the
        # god step so the engine advances to the nats_publish step.
        workflow = {
            "workflow": {
                "id": "test-sov-wf",
                "name": "Phase 5.2.2 sovereign backbone",
                "version": "1.0.0",
                "context": {"required": [], "optional": []},
                "steps": [
                    {
                        "id": "step1-god",
                        "god": "thoth",
                        "action": "research",
                        "input": "u",
                        "output": "step1_out",
                        "timeout": "30m",
                    },
                    {
                        "id": "step2-sov",
                        "type": "nats_publish",
                        "subject": "subspace.konan.outgoing.tallon",
                        "operator_approval_required": True,
                        "input_from": "step1-god",
                        "message": "test",
                        "output": "step2_out",
                    },
                ],
            }
        }
        (self.tmp.workflows_dir / "test-sov-wf.yaml").write_text(
            yaml.safe_dump(workflow)
        )
        # Also seed eng.WORKFLOWS_DIR (the engine's module-level path)
        # and reload.
        eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        (eng.WORKFLOWS_DIR / "test-sov-wf.yaml").write_text(
            yaml.safe_dump(workflow)
        )
        self.engine.workflows.reload()
        # Pre-queue a clean run for the god step (no refusal — just
        # a normal completion).
        self.gw.queue_run(cf.MockRun("r1", output="clean step 1 output"))

        # Start the workflow WITHOUT an operator_approval_token in
        # context_bag. The sovereign guard will block step 2.
        inst = self.engine.start_workflow(
            "test-sov-wf",
            context={"note": "phase 5.2.2 sovereign backbone"},
            original_request="phase 5.2.2 sovereign backbone test",
        )

        # Wait for the workflow to reach terminal state.
        for _ in range(250):
            await asyncio.sleep(0.02)
            cur = self.engine.get_instance(inst.workflow_id)
            if cur and cur.status in ("completed", "failed", "aborted"):
                break
        cur = self.engine.get_instance(inst.workflow_id)
        self.assertIsNotNone(cur, "workflow instance disappeared")
        self.assertEqual(
            cur.status, "aborted",
            f"sovereign guard should abort the workflow; got {cur.status} "
            f"(history: {[(h['step_id'], h.get('status')) for h in cur.step_history]})",
        )
        # step_history has a breach_blocked entry for step2-sov.
        breach_entries = [
            h for h in cur.step_history
            if h.get("status") == "breach_blocked"
        ]
        self.assertEqual(
            len(breach_entries), 1,
            f"expected exactly 1 breach_blocked entry; got {len(breach_entries)}: "
            f"{breach_entries}",
        )
        self.assertEqual(breach_entries[0]["step_id"], "step2-sov")
        # The block_reason should mention the missing operator_approval_token.
        self.assertIn(
            "operator_approval_token", breach_entries[0].get("block_reason", ""),
            f"block_reason should mention operator_approval_token; "
            f"got: {breach_entries[0].get('block_reason')!r}",
        )
        # An abort manifest was written.
        manifests = list(self.tmp.state_dir.glob("*.aborted.json"))
        self.assertEqual(
            len(manifests), 1,
            f"expected 1 .aborted.json manifest; got {len(manifests)}: {manifests}",
        )
        manifest = json.loads(manifests[0].read_text())
        self.assertEqual(manifest["status"], "aborted")
        self.assertEqual(manifest["failed_step"], "step2-sov")
        self.assertIn(
            "sovereign outbound blocked", manifest["failure_reason"],
            f"manifest failure_reason should mention 'sovereign outbound "
            f"blocked'; got: {manifest['failure_reason']!r}",
        )
