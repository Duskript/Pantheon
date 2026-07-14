"""Conductor Phase 1-2 contract tests.

Spec: ~/athenaeum/Codex-Pantheon/specs/conductor-workflow-engine.md v2.0.0
Build brief: ~/pantheon/shared/active/conductor-build-brief.md

These tests cover the initial filesystem + schema contract before the
Conductor MCP server starts mutating workflow state. They intentionally use
only local files under the Pantheon repo and do not require a running NATS
server, MCP client, or god session.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
CONDUCTOR_DIR = ROOT / "conductor"
PENDING_DIR = CONDUCTOR_DIR / "pending"
HANDOFFS_DIR = ROOT / "shared" / "handoffs"
SCHEMA_PATH = HANDOFFS_DIR / "schema.json"

EXPECTED_CONDUCTOR_DIRS = [
    CONDUCTOR_DIR / "rules",
    CONDUCTOR_DIR / "workflows",
    CONDUCTOR_DIR / "state",
    CONDUCTOR_DIR / "nats",
    HANDOFFS_DIR,
]

EXPECTED_PENDING_DIRS = {
    "thoth",
    "hephaestus",
    "marvin",
    "hermes",
    "iris",
    "caduceus",
    "mercer",
    "rheta",
    "inbox",
    "_webhooks",
    "_quarantine",
}


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _validator(def_name: str) -> jsonschema.Draft7Validator:
    schema = _schema()
    return jsonschema.Draft7Validator(
        {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]},
        format_checker=jsonschema.Draft7Validator.FORMAT_CHECKER,
    )


def assert_valid(def_name: str, payload: dict) -> None:
    errors = sorted(_validator(def_name).iter_errors(payload), key=lambda e: e.path)
    assert errors == []


def assert_invalid(def_name: str, payload: dict) -> None:
    errors = sorted(_validator(def_name).iter_errors(payload), key=lambda e: e.path)
    assert errors != []


def test_phase1_directories_exist() -> None:
    missing = [path for path in EXPECTED_CONDUCTOR_DIRS if not path.is_dir()]
    assert missing == []


def test_phase1_pending_inboxes_exist() -> None:
    actual = {path.name for path in PENDING_DIR.iterdir() if path.is_dir()}
    assert EXPECTED_PENDING_DIRS.issubset(actual)


def test_schema_file_is_valid_json_schema() -> None:
    schema = _schema()
    jsonschema.Draft7Validator.check_schema(schema)
    assert {"handoff", "ack", "event_envelope", "workflow_state"}.issubset(schema["$defs"])


def test_minimal_handoff_matches_contract() -> None:
    assert_valid(
        "handoff",
        {
            "handoff_id": "hof_20260613_abc123",
            "workflow_id": "wf_deploy_42",
            "from_god": "thoth",
            "to_god": "hephaestus",
            "step": "research",
            "context": {
                "summary": "Researched MCP ecosystem migration options.",
                "decisions": ["Migrate to FastMCP 3.x"],
                "artifacts": ["/athenaeum/research/mcp-report.md"],
                "open_questions": ["Should Hermes coordinate the upgrade schedule?"],
            },
        },
    )


@pytest.mark.parametrize("field", ["handoff_id", "workflow_id", "from_god", "to_god", "step", "context"])
def test_handoff_rejects_missing_required_fields(field: str) -> None:
    payload = {
        "handoff_id": "hof_20260613_abc123",
        "workflow_id": "wf_deploy_42",
        "from_god": "thoth",
        "to_god": "hephaestus",
        "step": "research",
        "context": {
            "summary": "Researched MCP ecosystem migration options.",
            "decisions": [],
            "artifacts": [],
        },
    }
    payload.pop(field)
    assert_invalid("handoff", payload)


@pytest.mark.parametrize("status", ["accepted", "pending", "rejected", "completed"])
def test_ack_status_contract(status: str) -> None:
    assert_valid(
        "ack",
        {
            "ack_id": "ack_20260613_456",
            "handoff_id": "hof_20260613_abc123",
            "workflow_id": "wf_deploy_42",
            "status": status,
            "eta": "2026-06-13T15:00:00Z",
            "message": "Heard, pulling context now.",
        },
    )


def test_ack_rejects_unknown_status() -> None:
    assert_invalid(
        "ack",
        {
            "ack_id": "ack_20260613_456",
            "handoff_id": "hof_20260613_abc123",
            "status": "ignored",
        },
    )


def test_event_envelope_contract() -> None:
    assert_valid(
        "event_envelope",
        {
            "id": "evt_20260613_abc123",
            "type": "handoff.completed",
            "source": "marvin",
            "target": "hephaestus",
            "timestamp": "2026-06-13T14:30:00Z",
            "workflow_id": "wf_deploy_42",
            "step_id": "implement",
            "context": {
                "summary": "Implementation completed and logic gate passed.",
                "decisions": ["Keep Conductor state file-backed."],
                "artifacts": ["/home/konan/pantheon/conductor/conductor-server.py"],
                "gates_passed": ["logic_gate"],
            },
            "payload": {
                "handoff_path": "/home/konan/pantheon/shared/handoffs/wf_deploy_42/implement.json",
                "priority": "normal",
            },
        },
    )


def test_workflow_state_contract() -> None:
    assert_valid(
        "workflow_state",
        {
            "workflow_id": "wf_deploy_42",
            "definition_id": "deploy-feature",
            "definition_version": "1.0.0",
            "status": "waiting_for_ack",
            "current_step": "implement",
            "context_bag": {
                "decisions": ["Use FastMCP 3.x"],
                "artifacts": ["/athenaeum/research/mcp-report.md"],
            },
            "step_history": [
                {
                    "step_id": "research",
                    "god": "thoth",
                    "status": "completed",
                    "completed_at": "2026-06-13T10:25:00Z",
                    "gates_passed": ["state_gate"],
                    "summary": "MCP ecosystem researched.",
                }
            ],
            "created": "2026-06-13T10:00:00Z",
            "completion_target": "2026-06-14T18:00:00Z",
            "dispatched_to": "marvin",
        },
    )
