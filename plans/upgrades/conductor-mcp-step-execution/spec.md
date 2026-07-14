# Conductor MCP Step Execution — Upgrade Spec

> **Status:** Draft v1
> **Date:** 2026-07-05
> **Location:** `~/pantheon/plans/upgrades/conductor-mcp-step-execution/`
> **Parent:** Not part of the unified upgrade — standalone upgrade
> **Build time:** ~4 days
> **Risk:** Medium — changes the Conductor step execution layer (engine does not change)

---

## 1. What This Is

This upgrade changes **how the Conductor engine executes individual steps** — from direct god dispatch to wrapping each step as an MCP Task. The Conductor engine (DAG parsing, step ordering, branching logic, state file writing, RALPH gate integration) stays exactly as it is. Only the execution layer changes.

**The Conductor is NOT replaced by MCP Tasks.** MCP Tasks are the execution mechanism for individual steps. The Conductor remains the workflow DAG orchestrator.

---

## 2. Current Architecture

```
Conductor Engine
  └── workflow YAML parsed into WorkflowStep objects
  └── _exec_god_dispatch(step) called for each step
       └── direct god invocation (blocking)
       └── step blocks until god returns
       └── no progress reporting
       └── no timeout enforcement
       └── if step hangs, workflow hangs
  └── branching logic reads step result
  └── state written to JSON file
```

**Problems this solves:**

| Problem | Current | After Upgrade |
|---------|---------|---------------|
| Hanging steps | Workflow stalls until manual intervention | MCP Task timeout fires → engine moves on |
| No progress visibility | Must read raw state files | `tasks/get` shows step status in real-time |
| Opaque failure | "Step failed" — no detail at the workflow level | Task result includes structured error + evidence |
| No cancellation mechanism | Must kill the whole process | `tasks/cancel` on a single step |
| No integration surface | Only readable via state file parsing | MCP tools expose step lifecycle to any consumer |

---

## 3. Target Architecture

```
Conductor Engine (unchanged)
  └── workflow YAML parsed into WorkflowStep objects
  └── _exec_god_dispatch(step) → now wraps in MCP Task
       └── engine creates a Task for each step
       └── engine returns task_id immediately (non-blocking)
       └── engine polls tasks/get for status
       └── engine reads task result (structured: {verdict, evidence, output})
       └── branching logic reads the result — same format as today
  └── state still written to JSON file (plus task_id in state)
```

### 3.1 Step Execution Flow

```
1. Engine creates task:
   task_id = create_task(
       name=f"{workflow_id}.{step_name}",
       handler="god_dispatch",
       input={step_config, context}
   )
   # Returns immediately. Non-blocking.

2. Engine enters polling loop:
   while True:
       status = tasks/get(task_id)
       if status == "completed":
           result = tasks/result(task_id)
           break
       elif status == "failed":
           result = tasks/result(task_id)  # includes error
           break
       elif status == "timeout":
           result = {"verdict": "TIMEOUT", "evidence": "20s limit exceeded"}
           tasks/cancel(task_id)
           break
       await sleep(2)  # poll interval
       # Optionally: surface status to dashboard

3. Engine uses task result for branching (unchanged logic):
   if result.verdict == "PASS":
       next_step = step.on_pass
   else:
       next_step = step.on_fail
```

### 3.2 What Changes in the Conductor

| File | Change | Lines Changed |
|------|--------|---------------|
| `~/pantheon/conductor/v2/engine.py` | `_exec_god_dispatch` wraps call in MCP Task + polling loop | ~60 lines |
| (none) — workflow YAML unchanged | — | 0 |

The rest of the engine (state file writing, branching, RALPH gates, event emissions) is unchanged.

### 3.3 What Gets Exposed as MCP Tools

```python
# NEW — exposed on Ichor MCP server alongside existing tools

@mcp.tool()
async def conductor_list(status: str = None) -> list:
    """List all workflows with optional status filter.
    Reads conductor/state/ directory.
    Returns workflow_id, name, status, current_step, started_at."""

@mcp.tool()
async def conductor_state(workflow_id: str) -> dict:
    """Read a single workflow state file.
    Returns full state dict including all step results."""

@mcp.tool()
async def conductor_start(workflow_id: str, context: dict = None) -> str:
    """Start a workflow by its YAML definition.
    Returns workflow_id immediately."""

@mcp.tool()
async def conductor_cancel(workflow_id: str) -> bool:
    """Cancel a running workflow. Cancels all active step tasks."""

@mcp.tool()
async def conductor_step_cancel(workflow_id: str, step: str) -> bool:
    """Cancel a specific step task within a running workflow."""
```

### 3.4 Conductor Dashboard (Persistent Web Route)

The dashboard lives at `/dashboard/conductor/` on the Ichor MCP server:

| Route | What It Shows | Delivery |
|---|---|---|
| `/dashboard/conductor/` | Workflow list with status cards — running, completed, failed counts | WebUI iframe + Telegram Tailscale link |
| `/dashboard/conductor/{wf_id}` | Single workflow detail — step timeline, current task status, state file diff | Same |
| `/api/dashboard/conductor` | Structured JSON for Olympus UI — workflows, steps, timestamps | Olympus UI fetches this |

**Implementation:** The dashboard reads the same `~/pandemon/conductor/state/` JSON files that the engine writes. It's a read-only presentation layer — no state modification.

---

## 4. Conductor + MCP App vs Conductor Dashboard

| | MCP App (per-tool state card) | Dashboard (persistent page) |
|---|---|---|
| **What** | `conductor_state(wf_id)` returns an HTML card for one workflow | `/dashboard/conductor/` shows all workflows |
| **When** | You ask for a specific state — "what's wf_42 doing?" | You open the dashboard to monitor everything |
| **Delivery** | Telegram link to `/apps/wf-42-card` + WebUI iframe | Telegram link to `/dashboard/conductor/` |
| **TTL** | 5 min (ephemeral) | Always live |
| **Interaction** | Read-only snapshot | Start/cancel/retry actions |
| **Olympus UI** | Embeds the card or calls the API | Calls `/api/dashboard/conductor` for structured data |

Both exist. They serve different use cases.

---

## 5. How This Relates to the Unified Upgrade

| Dimension | Conductor Upgrade | Unified Upgrade |
|---|---|---|
| Scope | Conductor step execution only | Ichor MCP, hooks, accordion, observability, flip |
| Timeline | Independent — can build before, during, or after | ~13 days + 7 day dual-run |
| Dependencies | Requires MCP Tasks (FastMCP 3.x) | Phase A delivers MCP infrastructure |
| Conflict? | None — they complement each other | The upgrade uses the MCP infrastructure that Phase A builds |

**Build order recommendation:** Phase A (Ichor MCP server) first — it provides the MCP Task infrastructure this upgrade needs. Then the Conductor upgrade, then the unified upgrade's remaining phases.

---

## 6. Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| 1 | `conductor_list` returns all known workflows | Compare output to `ls ~/pantheon/conductor/state/` — counts match |
| 2 | `conductor_start` begins workflow execution | Workflow state file appears in state/ within 5 seconds |
| 3 | `conductor_cancel` stops a running workflow | After cancel, workflow status changes to `cancelled`, step processes killed |
| 4 | `conductor_step_cancel` cancels one step without aborting the workflow | Step status changes to `cancelled` + `cancelled_by`, workflow continues at next step |
| 5 | `conductor_state` matches the on-disk state file | Read state file, read tool output — JSON is byte-identical |
| 6 | Step timeout fires correctly | Set step timeout to 3s, dispatch a step that sleeps 10s — assert workflow continues with TIMEOUT verdict after 3s |
| 7 | Dashboard renders workflow list | Open `/dashboard/conductor/` in browser — list matches conductor_list output |
| 8 | Dashboard detail shows step timeline | Open `/dashboard/conductor/wf_xxx` — each step shows status, duration, result |
| 9 | Olympus API returns structured data | `GET /api/dashboard/conductor` returns valid JSON matched to route output |

---

## 7. Tests

| Test | What it covers |
|------|---------------|
| `test_step_wraps_task.py` | _exec_god_dispatch creates an MCP Task with correct input |
| `test_polling_loop.py` | Engine reads task status correctly through states (running→completed→result) |
| `test_timeout.py` | Step timeout triggers TIMEOUT verdict + task cancellation |
| `test_conductor_tools.py` | All 4 MCP tools respond correctly with live conductor state |
| `test_conductor_list.py` | List matches file system state |
| `test_dashboard_routes.py` | Dashboard pages render without errors |
| `test_existing_workflows.py` | All 22+ existing YAML workflows run identically before and after upgrade |

---

## 8. Rollout

| Step | What | Verify |
|------|------|--------|
| 1 | Add `conductor_list/start/cancel/state/step_cancel` MCP tools to Ichor MCP server | All 5 tools respond in MCP list |
| 2 | Modify `_exec_god_dispatch` to wrap calls in MCP Task + polling loop | Unit tests pass |
| 3 | Run all 22+ existing workflows — compare outputs before/after | Zero behavioural diffs |
| 4 | Build dashboard routes (list + detail) | Render correctly in browser |
| 5 | Build Olympus API endpoint | Returns valid JSON |
| 6 | Dual-run: old dispatch path (current) runs alongside new MCP Task path — compare results for 7 days | Zero divergences |
| 7 | Flip: remove old dispatch path, keep MCP Task path | All workflows still pass |

**Rollback:** Revert `_exec_god_dispatch` to the old direct god invocation. MCP tools (list, start, cancel, state) remain available and useful regardless.
