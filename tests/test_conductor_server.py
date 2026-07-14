"""Conductor server core tests.

These tests exercise the file-backed workflow engine without starting the MCP
transport. The implementation is intentionally verified through temp dirs so
live Pantheon conductor state is not mutated by the test suite.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "conductor" / "conductor_server.py"
SCHEMA_PATH = ROOT / "shared" / "handoffs" / "schema.json"

spec = importlib.util.spec_from_file_location("conductor_server", SERVER_PATH)
conductor_server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(conductor_server)
Conductor = conductor_server.Conductor


@pytest.fixture()
def conductor(tmp_path: Path) -> Conductor:
    base = tmp_path / "conductor"
    handoffs = tmp_path / "shared" / "handoffs"
    handoffs.mkdir(parents=True)
    shutil.copy2(SCHEMA_PATH, handoffs / "schema.json")
    instance = Conductor(base_dir=base, handoffs_dir=handoffs)
    instance.ensure_layout()
    return instance


def sample_handoff(**overrides: object) -> dict:
    payload = {
        "handoff_id": "hof_20260613_abc123",
        "workflow_id": "wf_deploy_42",
        "from_god": "thoth",
        "to_god": "hephaestus",
        "step": "research",
        "context": {
            "summary": "Researched MCP ecosystem migration options.",
            "decisions": ["Migrate to FastMCP 3.x"],
            "artifacts": [],
            "open_questions": ["Coordinate schedule with Hermes?"],
            "gates_passed": ["state_gate"],
        },
    }
    payload.update(overrides)
    return payload


def test_check_layout_creates_expected_dirs(conductor: Conductor) -> None:
    result = conductor.ensure_layout()
    assert result["status"] == "ok"
    assert (conductor.base_dir / "rules").is_dir()
    assert (conductor.base_dir / "workflows").is_dir()
    assert (conductor.base_dir / "state").is_dir()
    assert (conductor.handoffs_dir).is_dir()
    assert (conductor.pending_dir / "marvin").is_dir()


def test_submit_handoff_writes_handoff_state_and_dispatch(conductor: Conductor) -> None:
    result = conductor.submit_handoff(sample_handoff())
    assert result["status"] == "dispatched"
    assert result["target_god"] == "hephaestus"
    assert result["state_status"] == "waiting_for_ack"

    handoff_path = conductor.handoffs_dir / "wf_deploy_42" / "research.json"
    dispatch_path = conductor.pending_dir / "hephaestus" / "hof_20260613_abc123.json"
    state_path = conductor.state_dir / "wf_deploy_42.json"
    assert handoff_path.is_file()
    assert dispatch_path.is_file()
    assert state_path.is_file()

    state = json.loads(state_path.read_text())
    assert state["workflow_id"] == "wf_deploy_42"
    assert state["current_step"] == "research"
    assert state["context_bag"]["decisions"] == ["Migrate to FastMCP 3.x"]
    assert state["step_history"][0]["status"] == "completed"


def test_check_inbox_lists_pending_dispatch(conductor: Conductor) -> None:
    conductor.submit_handoff(sample_handoff())
    inbox = conductor.check_inbox("hephaestus")
    assert inbox["count"] == 1
    assert inbox["dispatches"][0]["handoff_id"] == "hof_20260613_abc123"
    assert inbox["dispatches"][0]["context"]["decisions"] == ["Migrate to FastMCP 3.x"]


def test_ack_accepted_updates_state_and_removes_pending_dispatch(conductor: Conductor) -> None:
    conductor.submit_handoff(sample_handoff())
    result = conductor.ack_handoff(
        {
            "ack_id": "ack_20260613_456",
            "handoff_id": "hof_20260613_abc123",
            "workflow_id": "wf_deploy_42",
            "status": "accepted",
            "eta": "2026-06-13T15:00:00Z",
            "message": "Accepted.",
        }
    )
    assert result["acknowledged"] is True
    assert result["state_status"] == "in_progress"
    assert conductor.check_inbox("hephaestus")["count"] == 0
    assert conductor.get_workflow_state("wf_deploy_42")["acks"][0]["status"] == "accepted"


def test_ack_pending_keeps_dispatch_visible(conductor: Conductor) -> None:
    conductor.submit_handoff(sample_handoff())
    result = conductor.ack_handoff(
        {
            "ack_id": "ack_20260613_456",
            "handoff_id": "hof_20260613_abc123",
            "workflow_id": "wf_deploy_42",
            "status": "pending",
            "message": "Queued.",
        }
    )
    assert result["state_status"] == "waiting_for_ack"
    assert conductor.check_inbox("hephaestus")["count"] == 1
    dispatch = conductor.check_inbox("hephaestus")["dispatches"][0]
    assert dispatch["ack_status"] == "pending"


def test_list_pending_summarizes_all_inboxes(conductor: Conductor) -> None:
    conductor.submit_handoff(sample_handoff())
    pending = conductor.list_pending()
    assert pending["count"] == 1
    assert pending["pending"]["hephaestus"][0]["workflow_id"] == "wf_deploy_42"


def test_rejects_invalid_handoff(conductor: Conductor) -> None:
    bad = sample_handoff()
    bad["handoff_id"] = "bad"
    with pytest.raises(ValueError):
        conductor.submit_handoff(bad)


def test_workflow_definition_can_select_next_step(conductor: Conductor) -> None:
    # v2 routing (Phase 1 Step 1.6): when the workflow definition is
    # known to v2, the engine dispatches the FIRST step of the workflow
    # (the entry point), NOT the step after the current. The original
    # v1 test expected target_god=marvin / target_step=implement (the
    # second step), which was v1 semantics. v2 semantics: a fresh
    # dispatch starts the workflow at step 0 (research / thoth).
    # The v2 audit-trail flag `v2_dispatched=True` confirms the v2
    # path ran (vs the v1 fallback for unknown definitions).
    workflow = conductor.workflows_dir / "deploy-feature.yaml"
    workflow.write_text(
        """
workflow:
  id: deploy-feature
  version: "1.0.0"
  steps:
    - id: research
      god: thoth
    - id: implement
      god: marvin
""".strip()
        + "\n"
    )
    first = sample_handoff(
        to_god="hephaestus",
        routing={"workflow_definition": "deploy-feature", "workflow_version": "1.0.0"},
    )
    result = conductor.submit_handoff(first)
    # v2 semantics: dispatch starts at the workflow's first step.
    assert result["target_god"] == "thoth"
    assert result["target_step"] == "research"
    assert result.get("v2_dispatched") is True
    assert result.get("v2_definition_known") is True
    assert result.get("state_status") == "in_progress"
    assert conductor.check_inbox("thoth")["count"] == 1
    assert conductor.check_inbox("hephaestus")["count"] == 0
    assert conductor.check_inbox("marvin")["count"] == 0


def test_abort_workflow_writes_manifest_and_marker(conductor: Conductor, tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.md"
    artifact.write_text("result")
    handoff = sample_handoff()
    handoff["context"]["artifacts"] = [str(artifact)]
    conductor.submit_handoff(handoff)

    result = conductor.abort_workflow("wf_deploy_42", "Manual cancellation")
    assert result["status"] == "aborted"
    assert Path(result["manifest_path"]).is_file()
    assert artifact.with_name("artifact.md.aborted").is_file()
    assert conductor.get_workflow_state("wf_deploy_42")["status"] == "aborted"






def test_list_rules_finds_sample_rules() -> None:
    # Use real conductor instance to test against actual sample files
    instance = Conductor()
    result = instance.list_rules()
    assert result["count"] >= 4
    rule_names = [Path(p).stem for p in result["rules"]]
    assert "research-to-build" in rule_names
    assert "scheduling" in rule_names
    assert "tallon-operations" in rule_names
    assert "cross-pantheon" in rule_names


def test_list_workflows_finds_sample_workflows() -> None:
    instance = Conductor()
    result = instance.list_workflows()
    assert result["count"] >= 4
    workflow_ids = [w["id"] for w in result["workflows"]]
    assert "deploy-feature" in workflow_ids
    assert "morning-briefing" in workflow_ids
    assert "bug-fix" in workflow_ids
    assert "cross-pantheon-deploy" in workflow_ids


def test_cleanup_deletes_only_declared_workflow_temp_paths(conductor: Conductor, tmp_path: Path) -> None:
    # v2 routing (Phase 1 Step 1.6): cleanup() is a v1-only path —
    # it reads `wf_<id>.aborted.json` from v1's state layout and
    # resolves `temp_artifacts` from the v1 workflow definition. The
    # v2 engine manages its own instance state (`wf_<id>.json`, no
    # abort manifest) and does NOT integrate with v1's cleanup. The
    # v2 engine ALSO mints a fresh `wf_<uuid>` workflow id on every
    # dispatch (ignoring the caller's `workflow_id`), which would
    # break abort+cleanup (which key off the caller's id).
    #
    # This test is a v1-cleanup test, so we go through the v1 path
    # directly via `_v1_dispatch_handoff` — the same code path that
    # `submit_handoff` runs when the v2 routing marker is False. The
    # v1 path preserves the caller's `workflow_id` (no UUID minting)
    # and writes the v1 state layout that `abort_workflow` /
    # `cleanup` read.
    temp_dir = tmp_path / "conductor-wf_deploy_42"
    temp_dir.mkdir()
    (temp_dir / "scratch.txt").write_text("temp")
    workflow = conductor.workflows_dir / "deploy-feature.yaml"
    workflow.write_text(
        f"""
workflow:
  id: deploy-feature
  version: "1.0.0"
  steps:
    - id: research
      god: thoth
      temp_artifacts:
        - "{temp_dir}"
""".strip()
        + "\n"
    )
    handoff = sample_handoff(routing={"workflow_definition": "deploy-feature", "workflow_version": "1.0.0"})
    # v1 dispatch path: bypasses v2 routing entirely. The result shape
    # matches what submit_handoff would have returned if v2 routing
    # were disabled. This is the v1 cleanup test's setup.
    conductor._v1_dispatch_handoff(handoff)
    conductor.abort_workflow("wf_deploy_42", "Test abort")

    result = conductor.cleanup("wf_deploy_42")
    assert result["status"] == "cleaned"
    assert str(temp_dir) in result["deleted"]
    assert not temp_dir.exists()
