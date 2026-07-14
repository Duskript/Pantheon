# Conductor spec v2.0.0 — Changes from v1.1.0

Spec at: `~/athenaeum/Codex-Pantheon/specs/conductor-workflow-engine.md`
Build brief at: `~/pantheon/shared/active/conductor-build-brief.md`

## 1. Handoff schema simplified

**Before:** Gods had to provide `gates_passed`, `confidence`, `state.previous_handoffs`, `routing.workflow_position`, `routing.deadline`, etc. — many of which Conductor could derive.

**After:** Gods provide four fields: `summary`, `decisions`, `artifacts`. Conductor fills in everything else from workflow state. Schema updated in both spec and build brief.

**Code change needed in conductor-server.py:** The `submit_handoff` function accepts the simplified schema. Conductor adds derived fields when processing.

## 2. Ack timeout simplified

**Before:** 3-tier escalation (5min reminder → 15min reminder → 30min escalate).

**After:** Single timeout from the workflow step's `timeout` field. No ladder. Gods are local processes — if one doesn't ack, it's crashed. Escalate directly to Hermes.

**Code change needed:** In the `ack_handoff` function, remove the escalation_level tracking. Just start a single timer with the step timeout.

## 3. Triggers removed from workflow YAML

**Before:** Workflow YAML had both a `triggers:` section AND separate reaction rule YAML files that did the same thing.

**After:** Reaction rules are the single source of truth for event→workflow binding. The `triggers:` section was removed from the workflow YAML example. Removed from spec Section 3.2 and build brief Phase 8.

## 4. Abort stamping simplified

**Before:** Conductor opened every artifact file and appended an abort footer. This breaks for binary files (images, compiled artifacts) and couples Conductor to every file format.

**After:** Conductor writes an abort manifest JSON + places zero-byte `.aborted` marker files beside each artifact. No file content is touched.

**Code change needed in `abort_workflow`:** Instead of `open(art_path, "a")` and writing a footer, the function now creates `{art_path}.aborted` with 0 bytes. The cleanup function removes these markers. (Build brief abort_workflow function already updated; cleanup function still references old `artifacts_stamped` — swap to `artifacts_marked` when you hit that code.)

## 5. Unified single process

**Before:** Separate conductor-router.py, conductor-engine.py, conductor-nats-bridge.py — three processes to start, monitor, restart, debug.

**After:** Single `conductor-server.py` with optional feature flags: `--nats` enables NATS subscriber thread, `--webhook-port 8088` enables HTTP webhook gateway thread. Import and run, not spawn and forget.

**Build brief update needed:** Phases 5 (NATS bridge) and 6 (webhook gateway) are now part of Phase 4. The code from those phases lives as optional threads inside conductor-server.py, not separate files.

## Build order (simplified from 9 phases to 7)

| Order | What | Time |
|---|---|---|
| 1 | Directory structure | 5m |
| 2 | Handoff + ack schemas | 15m |
| 3 | **Conductor server** (MCP + NATS + webhook in one file) | 2.5h |
| 4 | Workflow YAML definition | 15m |
| 5 | Reaction rule YAML | 10m |
| 6 | NATS server config + systemd service | 15m |
| 7 | God SKILL.md updates | 1h |
| | **Total** | **~5h** |
