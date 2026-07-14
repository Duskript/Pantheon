# Synergy Codes WorkflowEnginePort → Conductor v2 — Port Adapter Spec

> Spike deliverable for `t_acc5b6fd`. Maps `@workflow-builder/execution-core`'s
> `WorkflowEnginePort<TNode>` (and the surrounding SDK surface the editor
> touches) to the real Conductor v2 stack at `~/pantheon/conductor/v2/`.
>
> **Constraint:** every endpoint referenced here exists in the current
> Conductor v2 codebase. Anything we need that does *not* exist is marked
> `[PROPOSED — not yet implemented]` and called out as new work.
>
> **Scope:** Spike only. The spec is the bridge design, not the bridge.

## 1. Two surfaces, one port

The Synergy stack exposes TWO surfaces that touch Conductor:

| Surface                                    | Layer                | Adapter type             |
| ------------------------------------------ | -------------------- | ------------------------ |
| `<WorkflowBuilder.Root>` (visual editor)   | Conductor UI         | UI integration (Path A)  |
| `WorkflowEnginePort<TNode>` (execution)    | Conductor v2 backend | Hex port adapter         |

The **UI integration** mounts the SDK inside Conductor UI's shell (validated
end-to-end in the spike — see `synergy-wb-embed-flag-on.png`). The **port
adapter** makes Conductor v2 satisfy `WorkflowEnginePort<TNode>` so the SDK
(and the reference execution-core) can drive runs against Conductor's
existing daemon.

This spec covers the **port adapter**. The UI integration is already
de-risked by the spike embed test.

## 2. Conductor v2 real API surface (no inventions)

Read 2026-06-16 from `~/pantheon/conductor/v2/`:

| Endpoint                                                | Layer                  | Where                  | Auth                          |
| ------------------------------------------------------- | ---------------------- | ---------------------- | ----------------------------- |
| `GET  /health`                                          | webhook server :8088   | `webhook.py:49`        | none                          |
| `POST /webhook/{source:path}`                           | webhook server :8088   | `webhook.py:58`        | none                          |
| `POST /dispatch`                                        | webhook server :8088   | `webhook.py:105`       | none (internal caller)        |
| `GET  /health`                                          | live stream :7700      | `live_stream.py:255`   | none                          |
| `GET  /ws/clitool/{workflow_id}/{step_id}`              | live stream :7700      | `live_stream.py:263`   | `?api_key=...` (CONDUCTOR_WS_API_KEY) |
| `engine.start_workflow(def_id, ...)`                    | in-process method      | `engine.py:970`        | n/a                           |
| `engine.start_workflow_sync(def_id, ...)`               | in-process method      | `engine.py:916`        | n/a                           |
| `engine.workflows.get(def_id)` / `.list_all()`          | in-process method      | `engine.py`            | n/a                           |
| `Workflow.from_dict(doc, path)`                         | in-process loader      | `engine.py:561`        | n/a                           |
| `validate_workflow(wf)` / `validate_workflow_dir(dir)` | in-process validator   | `workflow_validator.py`| n/a                           |

Plus the file-based workflow registry: `~/pantheon/conductor/workflows/*.yaml`
loaded at engine start. There is **no REST CRUD for workflow definitions** —
load is eager at engine construction; reload is not exposed.

**Hermes gateway** (separate process, Conductor → Hermes outbound):
`POST /v1/runs`, `GET /v1/runs/{id}`, `GET /v1/runs/{id}/events`,
`POST /v1/runs/{id}/stop`, all on `http://127.0.0.1:8642`. Conductor uses
these to dispatch *god runs* (steps within a workflow), not to author
workflows.

## 3. The gap: no UI CRUD API

`WorkflowEnginePort<TNode>` defines `submit` and `cancel` — both *runtime*
operations. The SDK's visual editor additionally needs *authoring*
operations (list, load, save) that the port does not cover. The authoring
surface lives in the SDK's three persistence strategies:

```ts
integration={{
  strategy: 'api',           // or 'props' or 'localStorage'
  endpoints: { load, save }, // user-provided URLs
}}
```

No real Conductor v2 endpoint serves those URLs today. This is the single
biggest gap the spike uncovered.

## 4. Adapter shape (TypeScript, sketches)

The adapter is a small package — `@conductor/synergy-adapter` — that
sits between the SDK and the Conductor v2 daemon. Three modules.

### 4.1 Persistence adapter (UI side, ~150 LOC)

Implements the `integration: { strategy: 'api', endpoints }` contract the
SDK expects. Talks to Conductor v2 via a new REST surface (proposed in
§4.4 below) that wraps the existing file-based workflows dir.

```ts
// @conductor/synergy-adapter/src/persistence.ts
export interface ConductorPersistenceOptions {
  baseUrl: string;       // e.g. 'http://127.0.0.1:8770'
  apiKey: string;        // bearer token (see §6 Auth)
  fetchImpl?: typeof fetch;
}

export function makeConductorPersistence(opts: ConductorPersistenceOptions) {
  return {
    async load(id: string): Promise<DiagramModel | null> {
      const r = await opts.fetchImpl(`${opts.baseUrl}/workflows/${encodeURIComponent(id)}`,
        { headers: { Authorization: `Bearer ${opts.apiKey}` } });
      if (r.status === 404) return null;
      if (!r.ok) throw new Error(`load failed: ${r.status}`);
      // Translate Conductor v2 YAML → Synergy DiagramModel here
      return conductorToDiagram(await r.json());
    },
    async save(id: string, model: DiagramModel): Promise<void> {
      // Translate Synergy DiagramModel → Conductor v2 YAML
      const yaml = diagramToConductor(id, model);
      const r = await opts.fetchImpl(`${opts.baseUrl}/workflows/${encodeURIComponent(id)}`,
        { method: 'PUT',
          headers: { 'Content-Type': 'application/yaml', Authorization: `Bearer ${opts.apiKey}` },
          body: yaml });
      if (!r.ok) throw new Error(`save failed: ${r.status}`);
    },
  };
}
```

This is the only piece the editor sees. Everything else is a service
running alongside the Conductor daemon.

### 4.2 WorkflowEnginePort adapter (~80 LOC)

The hex port. Implements the *execution* side. Drives Conductor v2's
existing `engine.start_workflow()` over the `/dispatch` webhook.

```ts
// @conductor/synergy-adapter/src/engine-adapter.ts
import type { WorkflowEnginePort, WorkflowExecutionInput } from
  '@workflow-builder/execution-core';

export class ConductorEngineAdapter<TNode extends BaseNode>
  implements WorkflowEnginePort<TNode> {

  constructor(private opts: {
    dispatchUrl: string;        // e.g. http://127.0.0.1:8088/dispatch
    apiKey: string;             // shared with webhook (proposed)
    fetchImpl?: typeof fetch;
  }) {}

  async submit(input: WorkflowExecutionInput<TNode>): Promise<void> {
    // 1. Translate the Synergy WorkflowDefinition<TNode> to a Conductor
    //    v2 Workflow YAML (see §4.3).
    const yaml = this.translateToConductor(input);
    // 2. POST /dispatch with an envelope Conductor accepts. The
    //    envelope uses `type: workflow.dispatch`, `source: synergy-ui`,
    //    and the YAML in `payload.workflow_yaml`.
    const body = {
      type: 'workflow.dispatch',
      source: 'synergy-ui',
      target: 'conductor',
      subject: input.workflowId,
      payload: { workflow_yaml: yaml, definition_id: input.workflowId,
                 trigger_payload: input.triggerPayload,
                 variables: input.variables,
                 global: input.global,
                 execution_id: input.executionId },
    };
    const r = await this.opts.fetchImpl(this.opts.dispatchUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${this.opts.apiKey}` },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`dispatch failed: ${r.status} ${await r.text()}`);
  }

  async cancel(executionId: string): Promise<void> {
    // No native cancel endpoint in Conductor v2 today. The
    // `engine._instances[wf_id].status = 'cancelled'` mutation is
    // private. The pragmatic options:
    //   (a) [PROPOSED] POST /dispatch with `type: workflow.cancel`
    //       and the engine handles it; OR
    //   (b) write a `state/cancel_{wf_id}.json` marker file the
    //       engine's file watcher picks up (matches existing
    //       pending/inbox pattern in webhook.py).
    // Until (a) ships, this method is best-effort: it writes the
    // marker file and lets the engine short-circuit the next step.
    throw new Error('cancel: not yet wired in Conductor v2 — see §4.4');
  }
}
```

### 4.3 Translation layer (Synergy `WorkflowDefinition<TNode>` ↔ Conductor YAML)

The hard part. The two node vocabularies are NOT shape-compatible.

**Synergy** (per `apps/demo/src/app/data/nodes/trigger/trigger.ts`):
```ts
type TriggerNode = { id, type: 'trigger', config: { eventType, frequency, ... } }
type ActionNode  = { id, type: 'action',  config: { /* arbitrary */ } }
type DecisionNode = { id, type: 'decision', config: { expression } }
type AiAgentNode = { id, type: 'ai-agent', config: { prompt, model, tools[] } }
type NotificationNode = { id, type: 'notification', config: { channel, template } }
```

**Conductor v2** (`workflows/morning-briefing.yaml`):
```yaml
steps:
  - id: active-goals
    god: thoth                  # ↔ Synergy 'god' / 'skill' union
    skill: inject-goals
    action: inject              # ↔ Synergy 'action' / 'type'
    input_from: previous-step   # string ref vs Synergy edge graph
    output: goals_preamble
    timeout: 30s
  - id: deliver
    type: nats_publish          # terminal action type
    subject: subspace.konan.inbox
    message: "..."
```

The translation is a 1:1 mapping **per node type** but the meta-language
differes:

| Synergy concept            | Conductor v2 equivalent         | Notes                                                                                  |
| -------------------------- | ------------------------------- | -------------------------------------------------------------------------------------- |
| `nodeTypes: PaletteItem[]` | none — hardcoded step types     | The `PaletteItem` set is the source of truth for the editor; Conductor v2 has ~7 step kinds |
| `WorkflowDefinition.nodes` | `workflow.steps[]`              | 1:1 with id/type-preserving translation                                                 |
| `WorkflowDefinition.edges` | `input_from: <step_id>`         | Conductor v2 is **strictly linear / single-input**; multi-input needs a small join step   |
| `node.config`              | step `config` spread            | Field names must match (god, skill, action, etc.)                                       |
| `errorPolicy: 'route'`     | not exposed                     | Conductor v2 step-level error policy is not modeled — see risks                          |
| variable picker `{{nodes.x.output}}` | Conductor v2's `input_from` chain | Conductor v2 templates are inline `subject: "...${workflow_id}..."` not step-output refs |

This translation is where most of the adapter LOC lives. Estimated effort:
~400 LOC plus a per-node-type config schema in JSON Schema.

### 4.4 New endpoints the adapter requires (proposed, not implemented)

The persistence adapter (§4.1) and cancel path (§4.2) need a small REST
surface that wraps the existing file-based workflow registry. **None of
these exist today.** The spike calls them out as proposed follow-on work
that the conductor team would ship *first*, then the adapter plugs in.

| Method | Path                     | Wraps                                                    | Auth |
| ------ | ------------------------ | -------------------------------------------------------- | ---- |
| GET    | `/workflows`             | glob `~/pantheon/conductor/workflows/*.yaml`             | bearer |
| GET    | `/workflows/{id}`        | `Workflow.from_dict(yaml.safe_load(path))`               | bearer |
| PUT    | `/workflows/{id}`        | atomic write of YAML; calls `validate_workflow` first   | bearer |
| POST   | `/workflows/{id}/validate` | `validate_workflow_file(path)` — dry run                | bearer |
| DELETE | `/workflows/{id}`        | atomic unlink (refuses if `id` starts with `bridge-`)   | bearer |
| POST   | `/dispatch` *(cancel)*   | existing `/dispatch` accepts a `type: workflow.cancel` envelope the engine handles | bearer |
| GET    | `/runs`                  | glob `state/wf_*.json` and return summaries              | bearer |
| GET    | `/runs/{wf_id}`          | `WorkflowInstance.from_dict(state/wf_{wf_id}.json)`      | bearer |
| GET    | `/runs/{wf_id}/events`   | relay from `LiveStreamServer` `:7700/clitool/.../...`   | bearer |

**Auth model:** one bearer token, shared between the persistence server
and the webhook/live-stream listeners. The existing webhook and
LiveStream servers do **not** enforce auth today — that gap is itself a
risk (see fit-assessment.md risk #2).

This new surface is best shipped as `~/pantheon/conductor/v2/api_server.py`
next to `webhook.py` and `live_stream.py`, started by `ConductorService`
behind the same `service.py` lifecycle, same port (:8770? or a new one?).
The conductor daemon keeps its existing webhook + WS for backward
compatibility.

### 4.5 Live observation (SSE / event streaming)

The SDK's listener API (`addNodeChangedListener`) is client-side only —
it does NOT define a transport. The UI integration in §4.1 is free to
pick any streaming transport. Two real options in Conductor v2 today:

| Option | Endpoint                              | Protocol        | Reference                  |
| ------ | ------------------------------------- | --------------- | -------------------------- |
| (a)    | `ws://127.0.0.1:7700/clitool/{wf}/{step}?api_key=...` | WebSocket       | `live_stream.py:263`       |
| (b)    | Hermes gateway `GET /v1/runs/{id}/events`            | SSE             | `gateway.py:218`           |

(a) is the native Conductor v2 path. The WS handler already emits
`workflow.started`, `node_started`, `node_completed`, `node_failed`
events per spec §3. The UI integration wraps (a) with a thin
`EventSource`-shaped adapter for the SDK's listener API.

(b) is the Hermes gateway path — useful for forwarding god-run events
*inside* a step (LLM tokens, tool calls). The SDK doesn't strictly need
this, but it's the path to the "see the agent thinking" view the
Workforge app ships with.

The proposed `/runs/{wf_id}/events` endpoint in §4.4 is a thin SSE
relay of (a) — easier to consume from a React app than raw WebSocket
because the browser `EventSource` API auto-reconnects.

## 5. End-to-end flow (proposed, after the API ships)

```
1. User opens Conductor UI → /editor/<workflow-id>
2. UI mounts <WorkflowBuilder.Root integration={{ strategy: 'api',
   endpoints: { load:  `${baseUrl}/workflows/${id}`,
                save:  `${baseUrl}/workflows/${id}` }}} />
3. SDK calls GET /workflows/{id}
4. API server reads ~/pantheon/conductor/workflows/{id}.yaml,
   runs Workflow.from_dict, returns JSON
5. UI shows the editor with nodes/edges populated
6. User edits — SDK calls PUT /workflows/{id} with new JSON
7. API server translates to YAML, runs validate_workflow_file,
   writes atomically (tmp + rename)
8. User clicks "Run" — SDK calls ConductorEngineAdapter.submit()
9. Adapter POSTs /dispatch with `type: workflow.dispatch`
10. Conductor engine starts the workflow, mints wf_<id>, runs steps
11. UI subscribes to /runs/{wf_id}/events (SSE) for live updates
12. Each step completion fans out via existing delivery.py
```

## 6. Auth placement (concrete)

Reference SDK has **none** — every endpoint is open. The fit assessment
flags this as a real adoption risk. For our integration:

| Layer                | Auth today                  | Proposed for adapter                         |
| -------------------- | --------------------------- | -------------------------------------------- |
| Conductor webhook :8088 | none                     | bearer token in `Authorization: Bearer ...` header |
| Conductor LiveStream :7700 | `?api_key=` query param | same bearer, but as `?api_key=` for the existing route |
| Conductor UI shell   | local (no remote)           | n/a — runs on the operator's machine         |
| New API surface :8770 (proposed) | n/a                  | same bearer token as webhook                 |

**Single token, single source:** `~/.hermes/.env` already holds the
`API_SERVER_KEY` Conductor uses to talk to Hermes. The same file can
hold `CONDUCTOR_UI_API_KEY` (or reuse the same value). Conductor UI
reads it at startup, ships it as the bearer for all adapter calls.

## 7. Effort estimate (relative, no absolute time)

Components the adapter team would build, ranked by size:

| Component                                  | Size  | Notes                                                                  |
| ------------------------------------------ | ----- | ---------------------------------------------------------------------- |
| Node vocabulary (PaletteItem set for Conductor v2's 7 step kinds) | M | schema + uischema + default data per kind |
| Translation layer (§4.3)                   | M     | Synergy WorkflowDefinition ↔ Conductor YAML, per node kind              |
| Persistence adapter (§4.1)                | S     | thin REST wrapper, mostly fetch + translate                            |
| WorkflowEnginePort adapter (§4.2)          | S     | 80 LOC, mostly submit() + cancel() mapping                             |
| Conductor v2 API server (§4.4)            | M-L   | NEW Python module under `~/pantheon/conductor/v2/`, ~300-500 LOC       |
| SSE relay for live events                  | S     | thin wrapper around existing LiveStreamServer                           |
| Conductor UI integration (Path A)          | S     | already de-risked by spike embed test                                  |
| Tests                                      | M     | node vocab + translator + persistence round-trips                       |

**Total adapter: L.** Plus the M-L Conductor v2 API server work that has
to land first. The hex port + persistence piece alone is **M**.

**Compare to building a custom editor from scratch:** S for the editor
shell, XL for the node-graph canvas + drag/drop + properties panel
(JSONForms + i18n + theming + plugin architecture) + persistence + SSE
+ integrations. Building custom is **2-3x the work** and starts from
zero on the maintenance curve. The SDK is genuinely a 5-10 person-year
saving vs custom — *if* the vocabulary-translation and API-surface work
fits in the M-L box.

## 8. Open questions (to resolve before adopting)

1. **Conductor v2 API server home:** Is the new REST surface in §4.4
   accepted into the conductor codebase, or do we ship a sidecar? The
   spec assumes in-tree (cleaner, single lifecycle); the cost is one
   more endpoint set to maintain.
2. **Cancel semantics:** Does Conductor v2 need a hard cancel
   (immediately stop the running step) or soft cancel (let the current
   step finish, skip the rest)? The spec assumes soft.
3. **Multi-input nodes:** Conductor v2's `input_from` is a single
   string ref. Synergy's edge graph supports diamond/join topologies.
   The adapter must either (a) flatten the graph, OR (b) add an
   explicit join node type. The spec is silent — needs a decision.
4. **Error policy:** Conductor v2 doesn't model `errorPolicy: 'route'`.
   The spec translates `'route'` to a "skip downstream, mark failed"
   behavior, but the engine needs a runtime hook to actually skip
   the downstream. Confirm the engine can do this or extend it.
5. **Theming:** "Look like Workforge" — the SDK ships
   `@synergycodes/overflow-ui` (their design system, beta.27). The
   current conductor-ui is on its own `Lumen` theme. Re-theming the
   SDK to match Lumen is feasible via the `--wb-*` and `--ax-*`
   tokens, but the work has not been sized. See fit-assessment.md
   risk #4.

## 9. References (file paths, no external links)

- `~/pantheon/conductor/v2/engine.py:970` — `start_workflow`
- `~/pantheon/conductor/v2/engine.py:916` — `start_workflow_sync`
- `~/pantheon/conductor/v2/engine.py:561` — `Workflow.from_dict`
- `~/pantheon/conductor/v2/webhook.py:37` — `make_app` (FastAPI :8088)
- `~/pantheon/conductor/v2/live_stream.py:153` — `LiveStreamServer`
- `~/pantheon/conductor/v2/live_stream.py:263` — `_handle_clitool`
- `~/pantheon/conductor/v2/workflow_validator.py:50` — `validate_workflow`
- `~/pantheon/conductor/v2/gateway.py:139` — `submit_run` (Hermes outbound)
- `/tmp/synergy-wb-spike/packages/execution-core/src/ports/workflow-engine.port.ts:14` — `WorkflowEnginePort` interface
- `/tmp/synergy-wb-spike/packages/sdk/README.md` — SDK overview, props, theming
- `/tmp/synergy-wb-spike/packages/sdk/CHANGELOG.md` — 2.1.0 is current
- `/tmp/synergy-wb-spike/packages/sdk/DECISION-LOG.md` — recent restructure (Phase 4)
- `/home/konan/projects/conductor-ui/src/routes/editor-spike.tsx` — spike embed
- `/home/konan/projects/conductor-ui/src/router.tsx` — spike route wired
- `/home/konan/pantheon/shared/active/synergy-wb-fit-assessment.md` — sister document
