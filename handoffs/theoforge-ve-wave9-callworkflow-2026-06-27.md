# TheoForge VE — Wave 9 `callWorkflow` Handoff

**Date:** 2026-06-27
**Session:** theoforge-ve UI node + E2E (got cut off mid-bugfix)
**Status:** 95% done. UI node shipped + verified in browser. E2E wired + orchestrator completes. ONE bug remains in the executor input envelope.

---

## TL;DR — The Bug (fix this first)

**File:** `src/workflow-executor.ts` — lines 220 and 412
**Code:** `const exec = await wf.run(subInput)`
**Symptom:** Sub-workflow state shows `input: {}`, then the first step that touches `data.X` crashes on `Cannot read properties of undefined (reading 'X')`.
**Why:** When invoked from inside an `andThen.execute()` of a `createWorkflowChain`-built workflow, `wf.run(subInput)` is somehow getting stripped. The `POST /workflows/:id/execute` HTTP endpoint wraps the body as `{ input: { ... } }` and the server passes `body.input` to `wf.run()`. But our `callWorkflow` step calls `wf.run(subInput)` directly, and the sub-workflow's data bag ends up empty.
**Fix (recommended, try in this order):**
1. **Try first (most likely):** change to `wf.run({ input: subInput })` — wrap in the same envelope the HTTP endpoint uses
2. **If that doesn't work:** check what `Workflow.run()` actually expects by looking at the VoltAgent source at `node_modules/@voltagent/core/dist/index.js` — search for `class Workflow` and inspect the `run` method
3. **If still broken:** the `getWorkflow(id)` may be returning a chain wrapper rather than a real `Workflow`. Add a `.toWorkflow()` call: `const wf = voltAgentRef.getWorkflow(id); const realWf = wf.toWorkflow ? wf.toWorkflow() : wf;`

**Verify with:**
```bash
curl -s -X POST http://localhost:3141/api/workflows/register \
  -H "Content-Type: application/json" \
  -d @/home/konan/projects/theoforge-visual-editor/saved-workflows/e2e-callworkflow-orchestrator.json
# (note: this re-register will fail because the workflow is already registered;
# instead use the body shape below)

curl -s -X POST http://localhost:3141/workflows/e2e-callworkflow-orchestrator/execute \
  -H "Content-Type: application/json" \
  -d '{ "input": { "message": "Hello from E2E callWorkflow test" } }'
# Expected when fixed: status="completed", result.call-smoke-test_result.result.summary == "[ENRICHED] Hello from E2E callWorkflow test (length: 31)"
```

---

## What Got Built (this session)

### 1. UI node for `callWorkflow` ✅
- **`web/src/nodes/registry.ts`** — added `"call-workflow"` to `NodeKind` enum (line 30) + added full node definition (line 300+) with icon `↪`, teal `#14b6a6`, 4 fields: `stepId`, `stepName`, `workflowId`, `inputJson`. `compileStructured` emits a `callWorkflow` JSON step. `compile` emits TS source calling `callWorkflow()`.
- **`web/src/nodes/components.tsx`** — added `"call-workflow"` to `KIND_ORDER` (line 38) and `designNodeTypes` (line 200).
- **Verified in browser** at http://localhost:5174 — palette shows 7 items, "Call Workflow" is the last with teal border + `↪` icon. Drag → drop on canvas produces a `react-flow__node-call-workflow` element with the right config panel.

### 2. Executor wiring (the `callWorkflow` step type) ✅
- **`src/workflow-executor.ts`** — added `case "callWorkflow"` to both `applyStep()` (line 181) and `runBodyStep()` (line 388). Resolves input field paths (`data.foo.bar`) against the caller's data bag, calls `wf.run(subInput)`, returns `{ subWorkflowResult, subWorkflowStatus, subWorkflowExecutionId, [stepId_result]: ... }`. 30 LOC.
- **Singleton injection** — `src/workflow-executor.ts:314-317` has `let voltAgentRef` + `setVoltAgentForExecutor()`. Called in `src/index.ts:499-502` inside `configureApp`.

### 3. E2E test workflow ✅
- **`saved-workflows/e2e-callworkflow-orchestrator.json`** — registered as `e2e-callworkflow-orchestrator` on the live server. 3 steps: trigger → `andThen` echo-input → `callWorkflow` invoke `smoke-test` with `{ message: "data.message" }`.
- **Smoke-test** (`src/index.ts:232`) is a 3-step `andThen` chain with input schema `z.object({ message: z.string() })` and result `{ original, enriched, summary }`.

### 4. Bug fix #1: `setVoltAgentForExecutor` was never called ✅
- The earlier claim that it was wired was wrong. Real fix in `src/index.ts:499-502`:
  ```ts
  configureApp: async (app) => {
    setVoltAgentForExecutor(voltAgent)
    // First: auto-register all disk-saved workflows so they survive restarts.
  ```
- Server restarted on PID 722317 with this fix. The orchestrator now successfully completes (no more "voltAgent not injected" error).

### 5. The remaining bug (input envelope)
- See TL;DR above. Sub-workflow starts with `input: {}` instead of `{ message: "..." }`.

---

## Live State (right now)

- **Server:** PID 722317, listening on `:3141` (VoltAgent on `localhost:3141`, Swagger at `/ui`)
- **Vite:** PID 715894, on `:5174` (Tailscale `100.115.50.41`)
- **Chrome:** PID 720951, on `:9222` for browser automation
- **Server log:** `/tmp/server-e2e.log` (tail it to see startup output)
- **31 workflows registered** including: `smoke-test`, `phase-orchestrator`, `parallel-ralph-qa`, `ralph-dag`, `idea-to-pr`, `callworkflow-test`, `e2e-callworkflow-orchestrator`
- **11 templates** in the marketplace (see `GET /api/templates`)

---

## Next Session — Pick Up Here

1. **Fix the input envelope bug** in `src/workflow-executor.ts:220` and `:412`. Most likely fix: `wf.run({ input: subInput })`.
2. **Restart server:** `kill 722317 && cd /home/konan/projects/theoforge-visual-editor && npm start &`
3. **Re-run E2E:** the curl command in the TL;DR above. Expect `status: "completed"` with `subWorkflowResult.result.summary` populated.
4. **If the fix works:** mark `callWorkflow` as done. Move on to whatever the next priority is.
5. **If the fix doesn't work:** add `console.log("[callWorkflow] subInput:", subInput)` and `console.log("[callWorkflow] exec:", exec)` right before the `return` statement. Rerun. Read `/tmp/server-e2e.log` to see what shape the workflow actually received.

---

## Architectural Context (so the new session understands WHY)

### Why `callWorkflow` exists
The `phase-orchestrator` workflow runs multiple phases of a build. Each phase is itself a `parallel-ralph-qa` workflow. Before `callWorkflow`, the orchestrator's `run-phase` step was an LLM prompt that said "invoke parallel-ralph-qa" — which doesn't actually invoke anything, it just generates text. The user correctly called this out: "I don't want an LLM. Just deciding whether it's done or not." The fix is a real deterministic function call between workflows.

### Why it's ~30 LOC, not "infra"
The whole executor is a JSON shape → real Workflow builder. Every step type is just a switch case. `callWorkflow` looks up the registered workflow by id, calls `.run()` on it, returns the result. The only piece of "infra" is the module-level `voltAgentRef` singleton — which is 4 LOC.

### Live registered workflows to use as sub-workflow targets
- `smoke-test` — 3 andThen steps, no LLM, schema `{message: string}`, result `{original, enriched, summary}`
- `parallel-ralph-qa` — multi-LLM Ralph DAG, schema `{prdDir, storySetCount}`
- `phase-orchestrator` — manifest-driven orchestrator, schema `{manifestPath, completionRecordPath}`

---

## Files Touched This Session

| File | Change |
|---|---|
| `web/src/nodes/registry.ts` | Added `call-workflow` to `NodeKind` + full registry entry |
| `web/src/nodes/components.tsx` | Added `call-workflow` to `KIND_ORDER` + `designNodeTypes` |
| `src/workflow-executor.ts` | Added `case "callWorkflow"` to `applyStep` + `runBodyStep` (lines 181, 388) |
| `src/index.ts` | Added `setVoltAgentForExecutor(voltAgent)` inside `configureApp` (lines 499-502) |
| `saved-workflows/e2e-callworkflow-orchestrator.json` | NEW — E2E test workflow definition |

## Key Endpoint Reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/workflows/registered` | List all live-registered workflows |
| POST | `/api/workflows/register` | Register a workflow from JSON (body: `{id, name, input, result, steps[]}`) |
| POST | `/workflows/:id/execute` | Run a workflow (body: `{input: {...}}`) |
| GET | `/workflows/:id/executions/:eid/state` | Get execution state incl. error |
| GET | `/api/templates` | List all templates |
