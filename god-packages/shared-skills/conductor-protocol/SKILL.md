---
name: conductor-protocol
description: Conductor handoff and acknowledgement protocol for Pantheon gods
category: software-development
version: "1.0.0"
author: Marvin
tags: [conductor, handoff, ack, protocol, workflow, pantheon]
---

# Conductor Protocol — Handoff & Acknowledgement

## Purpose

This skill documents the Conductor workflow engine's handoff and acknowledgement protocol. Every god in the Pantheon must follow this protocol when completing workflow steps or receiving dispatches from Conductor.

**Spec:** `~/athenaeum/Codex-Pantheon/specs/conductor-workflow-engine.md` v2.0.0
**Runtime:** `~/pantheon/conductor/conductor-server.py`

---

## Handoff Protocol

When you complete a workflow step, you MUST submit a structured handoff to Conductor.

### Submit a Handoff

Call the `conductor.submit_handoff` MCP tool with this payload:

```json
{
  "handoff_id": "hof_20260614_abc123",
  "workflow_id": "wf_deploy_42",
  "from_god": "thoth",
  "to_god": "hephaestus",
  "step": "research",
  "context": {
    "summary": "Researched MCP ecosystem migration options.",
    "decisions": ["Migrate to FastMCP 3.x", "Priority: MCP migration (critical)"],
    "artifacts": ["/athenaeum/research/mcp-ecosystem-2026/report.md"],
    "open_questions": ["Should Hermes coordinate upgrade schedule?"],
    "gates_passed": ["state_gate"]
  },
  "routing": {
    "workflow_definition": "deploy-feature",
    "workflow_version": "1.0.0",
    "workflow_step": "architect"
  }
}
```

### Required Fields

| Field | Format | Description |
|-------|--------|-------------|
| `handoff_id` | `hof_YYYYMMDD_random6` | Unique ID. Generate with timestamp + 6-char hex. |
| `workflow_id` | `wf_{name}_{seq}` | Workflow instance this belongs to. |
| `from_god` | God name | Your god name (thoth, hephaestus, marvin, etc.) |
| `to_god` | God name | Next god in the workflow. |
| `step` | Step ID | Step you just completed. |
| `context.summary` | String | One-line summary of what you did. |
| `context.decisions` | String[] | Decisions made during this step. |
| `context.artifacts` | String[] | Paths to files you produced. |
| `context.open_questions` | String[] | (Optional) Questions for next god. |
| `context.gates_passed` | String[] | (Optional) RALPH gates you passed. |

### What Conductor Does

1. Validates your handoff against the schema (`shared/handoffs/schema.json`).
2. Writes the handoff file to `shared/handoffs/{workflow_id}/{step}.json`.
3. Updates the workflow state in `conductor/state/{workflow_id}.json`.
4. If there's a next step (from workflow YAML or your `routing`), dispatches to the target god's pending inbox.
5. Returns `{ "status": "dispatched", "target_god": "...", "target_step": "..." }`.

---

## Acknowledgement Protocol

When Conductor dispatches work to you, a dispatch file appears in your pending inbox at `conductor/pending/{your_god_name}/{handoff_id}.json`.

### Check Your Inbox

At session start, call:

```python
inbox = conductor.check_inbox(god_name="marvin")
```

Returns:
```json
{
  "god": "marvin",
  "dispatches": [
    {
      "dispatch_id": "disp_20260614_123456_abc123",
      "handoff_id": "hof_20260614_abc123",
      "workflow_id": "wf_deploy_42",
      "from_god": "hephaestus",
      "to_god": "marvin",
      "step": "implement",
      "context": { ... },
      "dispatched_at": "2026-06-14T10:30:00Z",
      "ack_status": "unacked"
    }
  ],
  "count": 1
}
```

### Acknowledge the Dispatch

You MUST call `conductor.ack_handoff` with one of these statuses:

| Status | When to Use | Conductor Action |
|--------|-------------|------------------|
| `accepted` | You have the work, will execute | Sets workflow `in_progress`, waits for your handoff |
| `pending` | You're busy, queued it | Keeps dispatch visible, checks back later |
| `rejected` | Wrong god / out of scope | Marks workflow `failed`, looks for alternative routing |
| `completed` | Step done, result follows | Triggers next step immediately |

```json
{
  "ack_id": "ack_20260614_456",
  "handoff_id": "hof_20260614_abc123",
  "workflow_id": "wf_deploy_42",
  "status": "accepted",
  "eta": "2026-06-14T12:00:00Z",
  "message": "Heard, pulling context now. ETA ~90min."
}
```

### Ack ID Format

`ack_YYYYMMDD_random3` — timestamp + 3-char minimum hex.

---

## Session-Start Checklist

Every god session should:

1. **Check inbox**: `conductor.check_inbox(god_name="your_name")`
2. **Acknowledge pending**: For each dispatch, call `ack_handoff` with `accepted` or `pending`
3. **Read context**: The dispatch's `context` contains all prior decisions, artifacts, summaries — **do not ask the user to repeat information already in context**.
4. **Execute**: Do the work.
5. **Submit handoff**: When step completes, call `submit_handoff` with your results.

---

## RALPH Gates

Conductor runs RALPH gates at step boundaries. Your handoff's `context.gates_passed` should list gates you've satisfied.

| Gate | Skill | When It Runs |
|------|-------|--------------|
| `state_gate` | Read-before-write check | Before any file mutation |
| `logic_gate` | Syntax/type validation | After code generation |
| `phase_detect` | RALPH phase detection | At step boundaries |
| `handoff` | Handoff validation | On every `submit_handoff` |

---

## Workflow State Queries

- `conductor.get_workflow_state(workflow_id)` — Full state of a workflow.
- `conductor.list_pending()` — All pending dispatches across all gods.
- `conductor.list_rules()` — Active reaction rules.
- `conductor.list_workflows()` — Available workflow definitions.

---

## Abort & Cleanup

If a workflow fails irrecoverably:

- `conductor.abort_workflow(workflow_id, reason)` — Writes abort manifest + `.aborted` markers beside artifacts.
- `conductor.cleanup(workflow_id)` — Deletes declared `temp_artifacts` from workflow YAML (opt-in).

---

## Integration Notes for Gods

### Update Your SKILL.md

Add this to your god's SKILL.md:

```markdown
## Conductor Integration

When you receive a handoff via Conductor:
1. Call `conductor.check_inbox(god_name="your_name")` at session start.
2. Acknowledge with `conductor.ack_handoff({ status: "accepted", ... })`.
3. Read the full `context` block — it contains ALL prior decisions and artifacts.
4. Execute the step.
5. Submit handoff with `conductor.submit_handoff({ ... })` including:
   - `context.summary`: one-line summary
   - `context.decisions`: array of decisions made
   - `context.artifacts`: array of file paths produced
   - `context.gates_passed`: gates you satisfied
```

### Environment Variables

- `PANTHEON_ROOT` — Override Pantheon root (default: `~/pantheon`)
- `CONDUCTOR_BASE_DIR` — Override Conductor base dir
- `CONDUCTOR_HANDOFFS_DIR` — Override handoffs dir

---

## Quick Reference

| Tool | Call When | Returns |
|------|-----------|---------|
| `submit_handoff` | Step complete | `{ status, target_god, target_step }` |
| `check_inbox` | Session start | `{ dispatches[], count }` |
| `ack_handoff` | Dispatch received | `{ acknowledged, state_status }` |
| `get_workflow_state` | Need status | Full workflow state JSON |
| `list_pending` | Overview | All pending across gods |
| `list_rules` | Debug routing | Rule file paths |
| `list_workflows` | Discover | Workflow definitions |

---

## Files

- **Schema**: `~/pantheon/shared/handoffs/schema.json`
- **Server**: `~/pantheon/conductor/conductor_server.py`
- **Executable**: `~/pantheon/conductor/conductor-server.py`
- **Tests**: `~/pantheon/tests/test_conductor_*.py`

Run tests: `python3 -m pytest tests/test_conductor_*.py -q`

---

## Version History

- **1.0.0** (2026-06-14): Initial protocol from Conductor v2.0.0 spec.
