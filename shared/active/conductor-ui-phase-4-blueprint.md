# Conductor UI — Phase 4+ Blueprint: SDK Adoption with Iris's Mock Preserved

**For:** Hephaestus (build plan author), Konan (sign-off), Iris (design review against her mock), Thoth (QA gate)
**From:** Thoth (synthesis)
**Date:** 2026-06-17
**Status:** Proposal — awaiting Konan sign-off, then Hephaestus build plan

---

## TL;DR

**Adopt `@workflowbuilder/sdk` as the visual editor inside the Conductor UI, but keep Iris's mock as the design source of truth for the visual language of the canvas and the right-rail inspector.** The SDK is the *engine inside the canvas* — the 5-route shell, the AppShell, the Lumen theme, the Workforge interview, and the node-type vocabulary stay ours. The SDK handles the *React Flow + properties panel + drag/drop mechanics* we would otherwise build from scratch.

**Iris's role is design review against her mock** — the SDK adoption should be evaluated against the visual language she established in `/home/konan/workspace/conductor-mock/index.html`, not against the current code in `src/` (which is Marvin's translation of her mock + the Olympus Native 4-layer shell reference).

**The kanban surface hooks into Hermes's existing kanban system** — it's already a mature SQLite-backed FastAPI plugin with 11+ REST endpoints, a WebSocket event stream, and a typed TypeScript client skeleton already started in `src/api/kanban.ts`. The work is *wiring the stub to the real API + building the UI*, not building from scratch.

**Net effect on the build plan:** Phase 4 collapses from "build React Flow + drag/drop + properties + persistence" to "mount the SDK + write a port adapter + ship 4 PaletteItem kinds + theme override." Risk drops. Timeline compresses. Iris's mock stays the design north star.

---

## 1. What already exists (the honest inventory)

**This section was previously wrong — Iris did not design the Lumen scale, AppShell, or 5-route shell. Corrected provenance below.**

| Asset | Location | Real author | Status |
|---|---|---|---|
| **The mock** (single-file HTML, 5 screens, visual node editor, soulforge chat at bottom, right-rail inspector) | `/home/konan/workspace/conductor-mock/index.html` (113K) | **Iris (designed)** | ✅ The design source of truth |
| **5-route shell** (Dashboard / Editor / Board / Forge / Settings) | `src/router.tsx` | Marvin (Phase 0) — translated from the mock + Olympus Native 4-layer shell ref | ✅ Shipped |
| **AppShell** (4-layer glass, top bar, side rail, content area) | `src/shell/AppShell.tsx` | Marvin (Phase 0) — pattern from `Codex-Olympus/OLYMPUS_NATIVE_APP_SHELL_AND_NAVIGATION_ARCHITECTURE.md` | ✅ Shipped |
| **Lumen scale** (8-step luminance, 0 chromatic accents) + **Per-god glow** (`--god-glow` CSS var) | `src/theme/tokens.ts` | Marvin (Phase 0) — "engineered glass at dusk" visual language, named from Olympus's "lumen" terminology | ✅ Shipped |
| **Soulforge interview design** (7 question groups, plain-language, free-text + structured, 6-item hidden backend, "Get help" safety net) | `docs/conductor-soulforge-interview-design.md` (32K) | **Thoth (authored) + Konan (signed off 2026-06-16)** | ✅ Shipped |
| **Workforge vocabulary** (kanban, ledger, workforge, role-based labels, no god names on customer surfaces) | Per operator convention | **Konan (locked)** | ✅ Locked |
| **Ledger-shaped day-1** (`ledger_client/` interface + `LocalStub` + adapter tests) | `src/ledger_client/` | Marvin (Phase 0) | ✅ Shipped |
| **Workforge interview contract** (the Olympus-derived 8 question groups, customer-facing label "Get help", etc.) | `Codex-Olympus/OLYMPUS_NATIVE_SOUL_FORGE_INTERVIEW_CONTRACT.md` | Olympus team (not Iris) | ✅ Reference contract |

**What this means for the SDK adoption:**

- **Iris's design contribution is the mock, not the code.** Anything that needs to stay "Iris's design" must be validated against the mock, not the current code in `src/`.
- **The Lumen scale, AppShell, and 5-route shell are Marvin-built scaffolding** — they're not sacred. If the SDK adoption requires tweaking the shell layout (e.g., to make the SDK canvas fit cleanly), that's an acceptable change.
- **The Soulforge interview is Thoth's design + Konan's sign-off, not Iris's.** I authored the P0b doc. The interview contract must still be honored (it has customer-facing commitments), but the design is not Iris-owned.
- **Iris is the design reviewer, not the design owner of the implemented code.** Her role in Phase 4 (per build plan v1.1 §1) is **judge of the fan-out-merge implementation** — she picks the best of the parallel node-type editor implementations against her mock. She's the source of truth for the visual language of the canvas and the right-rail inspector.

**The SDK sits inside the Editor route only.** It does not own the shell, the routes, the Soulforge interview, the kanban board, the dashboard, or the settings. It is a *canvas component* in one route.

---

## 2. What the SDK does (and what it doesn't)

**The SDK is a `<WorkflowBuilder.Root>` React compound component backed by:**
- `@xyflow/react` (the canvas — node + edge rendering, pan, zoom, minimap)
- `@jsonforms/react` (the properties panel — schema-driven form rendering)
- `@phosphor-icons/react` (the palette icons)
- `@synergycodes/overflow-ui` (their design system, beta — see §6)
- `i18next` (translations)
- A plugin architecture (component / function / translation decorators)
- Three persistence strategies: `localStorage` default, `api` for backend, `props` for fully host-owned

**What it gives us for free:**
- Drag-to-connect edges
- Multi-select, copy-paste, undo/redo (8 official plugins)
- Orthogonal edge routing (ELK layout plugin)
- PDF export
- Node validation against a JSON schema
- Resizable / reshapable edges
- Theming via CSS variables (top-level `--wb-*` tokens)

**What it does NOT give us:**
- A back-end (we use Conductor v2, not Temporal)
- A node vocabulary (we define our 4-6 PaletteItem kinds for Conductor v2 step types)
- The Lumen theme (we override Overflow UI's `--ax-*` tokens)
- The Soulforge interview (separate route, separate component)
- Auth (their ref impl has none; we add a bearer token)

**What it requires from us:**
- A `WorkflowEnginePort` implementation that proxies to Conductor v2's REST API
- A node-type vocabulary for Conductor v2's step kinds (god-call, nats-publish, decision, parallel-fanout, etc.)
- A persistence adapter (`api` strategy) that talks to `api_server.py`
- An SSE event relay for live node state updates
- A theme override file for Lumen

---

## 3. The new architecture (visual)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  AppShell (Marvin, Phase 0, Olympus Native 4-layer pattern) —           │
│  glass, lumen tokens, god glow                                           │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │ Top bar: brand + god indicator + user + theme toggle              │  │
│  ├─────────┬─────────────────────────────────────────────────────────┤  │
│  │ Side    │                                                         │  │
│  │ rail    │  /editor/$id?                                           │  │
│  │ (5 nav  │  ┌───────────────────────────────────────────┐         │  │
│  │  items) │  │  <WorkflowBuilder.Root>                    │         │  │
│  │         │  │  ┌─────┬─────────────────────────┬─────┐  │         │  │
│  │ • Home  │  │  │ Pal-│  Canvas (xyflow)        │ Prop│  │         │  │
│  │ • Edit  │  │  │ ette│  - drag nodes           │ erty│  │         │  │
│  │ • Board │  │  │     │  - connect edges        │ pane│  │         │  │
│  │ • Forge │  │  │ 4-6 │  - validate on edit     │ JSON│  │         │  │
│  │ • Set   │  │  │ Con-│  - SSE live state        │ Form│  │         │  │
│  │         │  │  │ ductor│                          │ s   │  │         │  │
│  │         │  │  │ v2   │                          │     │  │         │  │
│  │         │  │  │ step │                          │     │  │         │  │
│  │         │  │  │ kinds│                          │     │  │         │  │
│  │         │  │  └─────┴─────────────────────────┴─────┘  │         │  │
│  │         │  │  [Top bar: save / validate / run / share] │         │  │
│  │         │  └───────────────────────────────────────────┘         │  │
│  │         │  + "Forge New Node" button (top-right)                  │  │
│  │         │    → opens /forge?from=editor&node-kind=X with           │  │
│  │         │    context pre-loaded (Workforge interview, Thoth-      │  │
│  │         │    authored, Konan-signed 2026-06-16)                    │  │
│  └─────────┴─────────────────────────────────────────────────────────┘  │
│                                                                          │
│  /forge   — Workforge interview UI (Thoth-authored, Konan-signed)      │
│  /board   — Kanban dashboard (Marvin, Phase 0)                         │
│  /settings — Settings (Marvin, Phase 0)                                │
│  /        — Dashboard (Marvin, Phase 0)                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**Soulforge is a sibling route, not an embedded panel.** The editor has a "Forge New Node" button in the top bar that navigates to `/forge?from=editor&node-kind=god-call` with the current context pre-loaded. After the interview completes, the user is returned to the editor with the new node dropped onto the canvas. This keeps the Workforge interview flow (Thoth-authored, Konan-signed 2026-06-16) intact and avoids re-implementing a chat panel inside the SDK.

---

## 4. The 5-milestone pilot (the work plan)

**Each milestone is independently shippable. The kill criterion is at Milestone 1.**

### Milestone 0 — SDK Validation (DONE)

**Status:** ✅ Completed by `t_acc5b6fd` (Marvin spike, 2026-06-17).

**Deliverables shipped:**
- `/home/konan/pantheon/shared/active/synergy-wb-fit-assessment.md` (16.5K, 11 sections)
- `/home/konan/pantheon/shared/active/synergy-wb-port-adapter-spec.md` (20.9K, 9 sections)
- `/home/konan/projects/conductor-ui/src/routes/editor-spike.tsx` (live embed at `/editor-spike` behind `VITE_FEATURE_SYNERGY_WB=true`)
- 3 screenshots (demo, flag-off, flag-on)
- 134 npm packages installed, 34.5s, no React 19 conflicts
- 11/11 acceptance criteria met, 0 new TS errors

**Verdict:** YES-WITH-CAVEATS — adopt via pilot.

### Milestone 1 — Conductor v2 `api_server.py` + Auth (BLOCKER for save/load)

**Goal:** Ship the REST CRUD surface that the SDK's `api` persistence strategy talks to.

**Why first:** Without this, the editor is read-only. The pilot fails on day 1.

**Scope:**
- New file: `~/pantheon/conductor/v2/api_server.py` (~300-500 LOC)
- 8 endpoints (full list in `synergy-wb-port-adapter-spec.md` §4.4):
  - `GET /api/workflows` — list workflow YAML files in the workflows dir
  - `GET /api/workflows/{id}` — read single workflow YAML
  - `PUT /api/workflows/{id}` — write single workflow YAML
  - `DELETE /api/workflows/{id}` — delete workflow
  - `POST /api/workflows/{id}/validate` — run the existing `workflow_validator.py` against a candidate graph
  - `POST /api/workflows/{id}/run` — trigger execution via the existing engine
  - `GET /api/workflows/{id}/runs` — list run history
  - `GET /api/workflows/{id}/runs/{run_id}/events` — SSE stream of live node state
- Bearer token auth (`CONDUCTOR_API_KEY` env var, ~30 LOC per server)
- Auth also added to existing `webhook.py:34` and `live_stream.py:DEFAULT_HOST` (currently bind `0.0.0.0` with no auth — security gap)
- Server lifecycle managed by `ConductorService` in `service.py:56`

**Size:** M-L
**Owner:** Marvin (code) + Hephaestus (architecture review) + Thoth (QA gate)
**Out of scope:** New engine features, schema migration, real Ledger integration

**Kill criterion:** If the engine can't reload a PUT'd workflow at runtime, or the validator rejects visually-valid graphs, stop and reassess. The custom-editor-from-scratch path is the fallback.

### Milestone 2 — Node Vocabulary + Translation Layer

**Goal:** Define 4-6 Conductor v2 step kinds as SDK PaletteItems + build a translator that goes both ways.

**Why second:** The SDK's `nodeTypes` prop requires an array of PaletteItems. Until we have them, the canvas is empty.

**Scope:**
- New dir: `/home/konan/projects/conductor-ui/src/conductor-ui/editor/nodes/{kind}/`
- 4-6 node kinds (pick from Conductor v2's step vocabulary):
  - `god-call` — invoke a god agent (label, target god, prompt, timeout)
  - `nats-publish` — emit a NATS message (subject, payload schema, correlation id)
  - `decision` — branching on a runtime condition (expression, true-branch, false-branch)
  - `parallel-fanout` — concurrent execution (sub-steps, wait policy)
  - `join` — synchronize parallel branches (input_from, wait policy)
  - `human-approval` — gate the workflow on operator sign-off (prompt, timeout, escalation)
- Per kind: `node.ts` (PaletteItem definition), `schema.ts` (JSON Forms schema for the properties panel), `uischema.ts` (layout for the properties panel), `icon.tsx` (palette icon)
- Translation layer: `src/conductor-ui/editor/translate/`
  - `toConductor(workflowDef: WorkflowDefinition) → WorkflowYAML` (~200 LOC)
  - `fromConductor(workflowYAML: WorkflowYAML) → WorkflowDefinition` (~200 LOC)
  - Handles the `input_from` multi-input edge case (flatten at translate, or add a join node — TBD per spike)

**Size:** M (vocab) + M (translator) = M total
**Owner:** Iris (label/copy/icon design — per her mock's right-rail inspector patterns) + Marvin (code) + Thoth (QA)
**Reference:** `apps/demo/src/app/data/nodes/{trigger,...}/` in the Synergy repo is a copy-paste template (~100-120 LOC per kind)

### Milestone 3 — UI Integration (replace the `/editor/$id` placeholder)

**Goal:** Mount `<WorkflowBuilder.Root>` in the actual `/editor/$id` route, behind the feature flag flipped to default-on for the pilot.

**Why third:** Needs Milestone 1 (REST API) and Milestone 2 (node vocabulary).

**Scope:**
- Update `src/router.tsx`: replace the placeholder `EditorRoute` with the SDK mount
- Wire persistence: pass `api` strategy pointing at Conductor v2 endpoints
- Wire SSE event relay: subscribe to `LiveStreamServer` at `:7700`, pipe node state updates into the SDK's node state channel
- Add the "Forge New Node" button to the editor's top bar — navigates to `/forge?from=editor&node-kind={kind}` with the current context (existing workflow id, target node type) pre-loaded into the Soulforge interview state
- Flip the feature flag: `VITE_FEATURE_SYNERGY_WB=true` becomes the default for the editor route; remove the `/editor-spike` placeholder
- Iris reviews the integration against her mock: does the SDK's chrome sit well in the visual language she established? Are the navigation cues clear? Does the editor respect the right-rail inspector pattern from her mock?

**Size:** S (UI integration) + S (SSE relay)
**Owner:** Iris (design review against mock) + Marvin (code) + Thoth (QA)
**Flag:** `VITE_FEATURE_SYNERGY_WB` is still a kill-switch if something breaks in prod

### Milestone 4 — Lumen Theme Override

**Goal:** Make the SDK's chrome look like the visual language in Iris's mock, not like Overflow UI.

**Why fourth:** The pilot's value is the workflow-authoring flow, not the visual polish. We can ship visually inconsistent at first and re-theme in this milestone.

**Scope:**
- New file: `src/conductor-ui/editor/theme/overrides.css` (~100-200 LOC)
- Override `--wb-*` tokens (top-level background, font, transitions) to match the Lumen scale
- Override `--ax-*` tokens (Overflow UI's design system) to map to Lumen's equivalent values
- Override `--wb-font-family` to drop `@fontsource/poppins` from the visible path
- Iris reviews against her mock: does the editor feel like the visual language she designed, or like a bolted-on foreign body?

**Size:** M (or S to defer and accept the visual mismatch)
**Owner:** Iris (lead, design review against her mock) + Marvin (impl) + Thoth (QA)
**Decision point:** If M is needed, ship it. If L is needed, defer and accept Overflow UI as-is inside the editor.

### Milestone 5 (post-pilot, optional) — Polyrepo extraction

**Goal:** Once the pilot is stable, extract the editor + port adapter + node vocabulary into a versioned package (e.g., `@workforge/conductor-editor`).

**Why:** If the editor matures, it can be reused for other Workforge products. The Synergy SDK sits underneath; the Workforge layer above is the brand-bearing interface.

**Scope:** TBD. Pilot must complete first.

---

## 5. The kanban hook (existing system, surface appropriately)

**Konan's directive (2026-06-17):** "The kanban which we should be able to hook right into. It's an existing system in Hermes agent. We just have to surface it appropriately."

**The good news:** this is a *surface* problem, not a *build* problem. The kanban already exists in full. The work is wiring the Conductor UI to it cleanly.

### 5.1 What already exists (no work needed)

| Asset | Location | Status |
|---|---|---|
| SQLite database | `/home/konan/.hermes/kanban.db` (6 tables: tasks, task_links, task_comments, task_events, task_runs, kanban_notify_subs, task_attachments) | ✅ Live, in use by all god workflows |
| FastAPI plugin | `/home/konan/.hermes/hermes-agent/plugins/kanban/dashboard/plugin_api.py` mounted at `/api/plugins/kanban/` | ✅ Live, 11+ REST endpoints |
| WebSocket event stream | `/api/plugins/kanban/events` (tails `task_events` table in WAL mode) | ✅ Live, supports live UI updates |
| CLI surface | `hermes kanban ...` (30+ subcommands) | ✅ Live, parallel to API |
| Typed client skeleton | `/home/konan/projects/conductor-ui/src/api/kanban.ts` (17 methods) | ⚠️ Phase 0 stub — returns empty arrays + mock tasks |
| Status columns | `triage, todo, ready, running, blocked, done` (per `BOARD_COLUMNS` in the plugin) | ✅ Live |
| Notify subscriptions | `kanban_notify_subs` table for Telegram-style event delivery | ✅ Live |

### 5.2 The 11+ REST endpoints to wire

Per `plugin_api.py`:
- `GET /api/plugins/kanban/board` — list all tasks grouped by column (the main board view)
- `GET /api/plugins/kanban/tasks/{id}` — read a single task
- `POST /api/plugins/kanban/tasks` — create a task
- `POST /api/plugins/kanban/tasks/{id}/comments` — comment on a task
- `POST /api/plugins/kanban/links` — link parent/child
- `POST /api/plugins/kanban/tasks/bulk` — bulk operations
- `GET /api/plugins/kanban/config` — board config
- `GET /api/plugins/kanban/stats` — board stats (counts by status, by assignee, etc.)
- `GET /api/plugins/kanban/assignees` — list assignees (which god owns which task)
- `GET /api/plugins/kanban/tasks/{id}/log` — task run log (live stream)
- `POST /api/plugins/kanban/dispatch` — dispatch a task to a worker
- `WS /api/plugins/kanban/events` — live event stream (WebSocket)

### 5.3 The work to do (size: M-L, in Phase 3 per the existing build plan)

The build plan v1.1 already defines Phase 3 as "Kanban features wired in (~10 tasks)." The work breaks into:

**5.3.1 — Wire the API client to the real backend (size: S)**
- Update `/home/konan/projects/conductor-ui/src/api/kanban.ts` to call `/api/plugins/kanban/...` instead of returning stubs
- All 17 method stubs already exist; just replace the stubbed returns with real `fetchJson` calls
- Add a base-URL config: same plugin-host as the rest of the dashboard (likely `http://localhost:9119/api/plugins/kanban` based on the dashboard plugin pattern)
- The existing TypeScript types in `src/ledger_client/types.ts` are the canonical task shape — keep using them, no schema translation needed (the plugin's JSON shape is compatible)

**5.3.2 — Build the 7-column board UI (size: M)**
- New: `src/kanban/board.tsx` — column-based board with the 7 statuses from `BOARD_COLUMNS`
- New: `src/kanban/card.tsx` — task card with parent/child, god, profile, status, last-heartbeat
- Click-to-advance-status (no drag/drop required; drag is M+ effort and the CLI / dispatch already handle transitions)
- Or drag-to-move-status if Iris's mock has it (need to check — if not, click-advance is the right answer)

**5.3.3 — Wire the live event stream (size: S)**
- Subscribe to `ws://localhost:9119/api/plugins/kanban/events?token=X` on board mount
- Re-fetch the relevant task on event (or just patch the local cache with the event payload)
- Reconnect on disconnect (the WebSocket's token-based auth means a re-handshake is needed on reconnect)
- This is the **same pattern** the SDK uses for SSE — one reconnect loop, one auth token

**5.3.4 — Build the task detail panel (size: M)**
- New: `src/kanban/detail.tsx` — single task view with parent/child tree, run log, comments, audit
- Reuse the `getTask`, `getTaskRunLog`, `getTaskAuditLog` methods from the existing client
- Parent/child tree visual: simple list with indentation, or a mini-graph (skip mini-graph in v1)

**5.3.5 — Build the create-task form (size: S)**
- New: `src/kanban/create.tsx` — modal that POSTs to `/api/plugins/kanban/tasks`
- Fields: title, body, assignee (dropdown of registered assignees from `/assignees`), priority, parent (optional), workspace path
- Reuses the `createTask` method from the client

**5.3.6 — Build the dispatch control (size: S)**
- Claim button (atomic, calls `claimTask` which already exists in the client)
- Advance status button (calls `advanceTaskStatus`)
- Abort button (calls `abortTaskRun`)
- Retry button (calls `retryTaskRun`)

**5.3.7 — Surface the 14-connector catalog (size: S)**
- Per Iris's mock: there's a 14-connector catalog in the Workforge interface
- The kanban has assignees (gods) that map to this catalog
- Surface as a "Connectors" filter in the board view, or as a sidebar

**5.3.8 — Cross-route integration: editor → kanban (size: M)**
- From the editor (`/editor/$id`): "Dispatch this workflow as a kanban task" button
- POSTs to `/api/plugins/kanban/tasks` with the workflow yaml as the body, assignee = the operator's selected god
- From the kanban board: "Open in editor" link on a workflow task → navigates to `/editor/$workflow_id` with the task context in the URL params

### 5.4 What this does NOT require

- ❌ A new kanban database (we use the existing one)
- ❌ A new FastAPI plugin (we use the existing one)
- ❌ A new auth system (the plugin has its own session-token pattern, documented in `plugin_api.py:40-50`)
- ❌ A new WebSocket implementation (the plugin's `/events` endpoint is already there)
- ❌ A new CLI (the `hermes kanban ...` commands already work for everything we need)
- ❌ A new task model (the existing 6-table schema is the canonical model)

### 5.5 The kanban-hook ordering relative to the SDK milestones

| Kanban task | Blocked by | Notes |
|---|---|---|
| 5.3.1 (wire API client) | nothing | S — can ship in any phase |
| 5.3.2 (board UI) | 5.3.1 | M — Phase 3 work |
| 5.3.3 (live events) | 5.3.1 | S — Phase 3 work, can parallel 5.3.2 |
| 5.3.4 (task detail) | 5.3.1 | M — Phase 3 work |
| 5.3.5 (create form) | 5.3.1 | S — Phase 3 work |
| 5.3.6 (dispatch controls) | 5.3.1 | S — Phase 3 work |
| 5.3.7 (connector catalog) | 5.3.2 | S — Phase 3 work |
| 5.3.8 (editor ↔ kanban) | 5.3.2 + Phase 4 Milestone 3 (UI integration) | M — Phase 4 work, after the SDK is mounted |

**The kanban work can start immediately** — Phase 3 in the build plan already exists. It does not need to wait for the SDK.

### 5.6 What changes in §5 (the build plan changes for Phase 4)

The Phase 3 work (kanban) and the Phase 4 work (SDK adoption) are now decoupled. The build plan v1.2 should:

- **Keep Phase 3 as-is** (kanban features, ~10 tasks, parallelizable with Phase 2)
- **Replace Phase 4 v1.1 with the 4 sub-phases** in this blueprint (api_server+auth → node vocab+translator → UI integration → Lumen theme)
- **Add 5.3.8 (editor ↔ kanban) as a Phase 4 deliverable**, not Phase 3 — it's coupled to the SDK being mounted

**No changes to Phase 0/1/2/5.** The kanban hook fits cleanly into the existing Phase 3.

---

**Current Phase 4 in `conductor-ui-build-plan.md` v1.1:**
> Phase 4 — Visual Editor + Soulforge-driven node creation (React Flow, 5 node-type editors, fan-out-merge, drag-to-connect)
> Owner: Marvin | Scope: ~6+ hours | Pattern: fan_out_fan_in

**Proposed Phase 4 v1.2:**

| Sub-phase | Owner | Pattern | Scope | Blocked by |
|---|---|---|---|---|
| **4.0** (was Milestone 1 above) | Marvin + Hephaestus | sequential | M-L: `api_server.py` + auth | Milestone 0 (done) |
| **4.1** (was Milestone 2 above) | Iris (mock-based design) + Marvin (code) | parallel (4-6 node kinds in parallel) | M: 4-6 PaletteItems + translator | 4.0 |
| **4.2** (was Milestone 3 above) | Iris (mock review) + Marvin (code) | sequential | S: replace placeholder + wire SSE | 4.0, 4.1 |
| **4.3** (was Milestone 4 above) | Iris (mock lead) + Marvin (impl) | sequential | M (or S to skip): Lumen theme | 4.2 |
| **4.4** (post-pilot) | Marvin | sequential | M: extract to `@workforge/conductor-editor` | 4.3 |

**Phase 4 budget:** L (vs. previous XL for from-scratch) — net savings: M, absorbed partially by the new `api_server.py` work that would have been needed regardless.

**Pattern:** Replace `fan_out_fan_in` (5 parallel node-type editors) with `parallel_branches` (4-6 PaletteItem kinds, each a small task, Iris as mock-based design lead) + sequential integration + sequential theming. The fan-out only works for parallel-safe work; the integration is sequential because of the API-first dependency.

**Phase 4 QA gate:** The Thoth review follow-on remains mandatory (operator-locked 2026-06-16). Each sub-phase ships with its own review task.

---

## 6. The Ledger plug-in path (already designed in)

**Konan's directive (2026-06-17):** "Will this be something that can easily act as a plug-in for Ledger? Because that's the final step. After this thing is built, we've got to be able to plug it in there."

**Short answer: YES.** The Conductor UI is already designed Ledger-shaped from day 1. The seam is `src/ledger_client/`, the LocalStub already implements the full interface, and the design standard (`subsystem-shape.md`, operator-locked 2026-06-16) requires every subsystem to follow the same shape. The "plug into Ledger" work is shipping the `LedgerAdapter` (REST-shaped) and swapping `LocalStub` for it.

### 6.1 What's already in place (the seam is built)

| Asset | Location | Status |
|---|---|---|
| **The `Client` interface** | `src/ledger_client/index.ts` (~5K) | ✅ Defines the full contract: 30+ methods across Workflows, Tasks, Gods, Handoffs, Audit Events |
| **The domain types** | `src/ledger_client/types.ts` (5.8K) | ✅ Versioned, immutable from consumer's perspective |
| **The `LocalStub` impl** | `src/ledger_client/local_stub.ts` (18.6K) | ✅ JSON-file-backed, atomic writes, in-memory cache, full CRUD |
| **The unit tests** | `src/ledger_client/__tests__/local_stub.test.ts` | ✅ 8+ tests covering read/write/list/delete/atomicity/error paths |
| **The design standard** | `Codex-Pantheon/design/standards/subsystem-shape.md` (operator-locked 2026-06-16) | ✅ Codifies the 6-component shape as a pattern every new subsystem follows |
| **The Phase 5 plan** | `conductor-ui-build-plan.md` v1.1 §Phase 5 | ✅ Already names: ledger_client.LocalStub + adapter tests + schema migration + swap-LocalStub-for-Ledger proof |

**This means the "plug into Ledger" work is Phase 5 of the existing build plan — not new architecture, just implementation of the already-designed adapter.**

### 6.2 The plug-in work (3 concrete steps, S-M total)

**Step 1: Build the LedgerAdapter** (~S-M)
- New file: `src/ledger_client/ledger_adapter.ts`
- Implements the same `Client` interface
- REST calls to Frappe/ERPNext's API (or the TheoForge REST layer in front of it)
- All 30+ methods get a real implementation
- Auth: bearer token, same pattern as the kanban plugin + the new `api_server.py` from the SDK pilot
- Reuses the existing types from `types.ts` — no schema translation, just HTTP plumbing

**Step 2: Build the swap test** (~S)
- One test that swaps `LocalStub` for `LedgerAdapter` and proves the board, editor, kanban, and other consumers all still work
- This is the proof the seam holds
- The existing design standard requires this test as part of the adapter

**Step 3: Wire the migration framework** (~S-M)
- Already in the design standard
- Declarative: when the real Ledger ships, LocalStub data migrates to the real backend via a versioned migration runner
- Example: `migrations/v1_to_v2.example.ts` (the design standard calls for this)

**Total: S-M.** This is a single Phase 5 sub-phase, not a new architecture.

### 6.3 How the SDK adoption + kanban hook fit

Both Phase 3 (kanban) and Phase 4 (SDK adoption) write to the `ledger_client` interface, not directly to LocalStub. That means:

- ✅ When `LedgerAdapter` ships, both subsystems auto-plug-in (no consumer-side changes)
- ✅ The kanban surface (5.3 in §5) goes through the same `Client.listTasks()` / `createTask()` / `claimTask()` methods that the LocalStub already implements
- ✅ The SDK's workflow editor (Phase 4) calls the same `Client.listWorkflows()` / `getWorkflow()` / `updateWorkflow()` methods
- ✅ The "swap-LocalStub-for-Ledger proof" test covers BOTH subsystems in one test

**This is the architectural win of the Ledger-shaped day-1 approach:** subsystems are plug-in to the real Ledger by *swapping the impl, not by changing the consumers.*

### 6.4 What "plug into Ledger" means in the Ledger product context

Per `ledger-stack-architecture.md`:

- The Conductor UI is the **Workflow Engine's GUI** (Layer 2)
- The Workflow Engine is one of 7 add-on tiers in the Ledger product
- When the operator enables the Workflow Engine tier in Ledger, the Conductor UI appears as a gated add-on
- "No Frappe iframe, no Frappe doctype — Conductor's GUI is the surface, branded as Ledger"

**So "plug into Ledger" has two parts:**

1. **The data seam** (Phase 5 of the build plan) — `LedgerAdapter` swaps `LocalStub`. All consumers (kanban, editor, dashboard) automatically talk to the real Ledger.
2. **The UI seam** (post-Phase 5, not yet designed) — the Conductor UI is mounted inside Ledger's operator UI as a gated add-on. This is the actual "this app shows up inside Ledger" work. It's a separate task that's not in the current build plan; it's a future Ledger product decision.

**For the current build plan, the data seam is the entire "plug into Ledger" deliverable. The UI seam is a future decision.**

### 6.5 What changes in §5 (the build plan changes for Phase 4)

The Phase 5 work (Ledger plug-in) is *unchanged* by the SDK adoption. The build plan v1.2 should:

- **Keep Phase 5 as-is** (ledger_client.LocalStub + adapter tests + migrations + swap proof)
- **Add a note** to Phase 5: the LedgerAdapter implementation is what enables the "plug into Ledger" deliverable; the UI seam (mounting Conductor UI as a Frappe add-on) is a separate future task
- **Cross-reference §6 of this blueprint** in the Phase 5 task bodies, so the implementer knows the seam is already designed

### 6.6 The honest answer to Konan's question

**Yes, this will be a plug-in for Ledger.** The seam is already built (`ledger_client/`), the interface is already designed (operator-locked standard), the LocalStub already implements the full contract, the build plan already names Phase 5 as the plug-in work. **The "final step" is not new architecture — it's a single S-M sub-phase in Phase 5 of the existing build plan.**

The only thing that changes between now and the plug-in step is: when Ledger ships its REST API, we point the LedgerAdapter at it. The consumers (kanban, editor, dashboard) don't change.

---

## 7. The 5 risks (carried forward from the fit assessment, with mitigations)

| # | Risk | Mitigation | Owner |
|---|---|---|---|
| 1 | Conductor v2 has no workflow CRUD API (BLOCKER) | Milestone 1 ships `api_server.py` first | Marvin + Hephaestus |
| 2 | Existing Conductor v2 servers have no auth (security gap) | Add `CONDUCTOR_API_KEY` bearer in Milestone 1, applied to webhook + livestream + new api_server | Marvin |
| 3 | Node vocabulary mismatch (SDK uses PaletteItem, Conductor uses YAML step kinds) | Milestone 2: define 4-6 PaletteItems + translator | Iris + Marvin |
| 4 | Theming depth unproven (Overflow UI is beta, Lumen re-theme not documented) | Milestone 4 as separate sub-phase; option to skip and accept visual mismatch | Iris |
| 5 | SDK is on a moving target (just shipped 2.1.0, 3 prior entry-point rewrites in 12 months) | Pin `@workflowbuilder/sdk@2.1.0` exactly; budget recurring upgrade slot | Hephaestus |

---

## 8. The decisions to make now (for Konan)

**Before Hephaestus writes the v1.2 build plan, sign off on these:**

### 7.1 — Adopt the SDK as Phase 4 (vs. build from scratch)

**Recommendation: YES.** The fit assessment (16.5K) and the live embed screenshot are the evidence. The savings are M-effort, the maintenance curve is real (Synergy Codes ships), and the operator authoring flow is the highest-leverage UI work in the Phase 1-4 plan.

**Alternatives:**
- **(a) Build from scratch** — XL effort, full control, no SDK dep
- **(b) Adopt with pilot** — L effort, accept the SDK as a dep, kill-switch via feature flag *(my recommendation)*

### 7.2 — Ship `api_server.py` in Milestone 1 (vs. defer until after the editor ships)

**Recommendation: YES, ship first.** The editor without an API to save to is a demo, not a product. The api_server is M-L work but it's needed regardless of which editor we pick (even a custom editor would need this).

**Alternatives:**
- **(a) Ship api_server first** — pilot's value is real on day 1 *(my recommendation)*
- **(b) Ship the editor first as read-only** — visually complete, but no save/load. Operator flow is broken.

### 7.3 — Keep Soulforge as a sibling route (vs. embed as a panel inside the editor)

**Recommendation: SIBLING ROUTE.** The Workforge interview contract is already designed (Thoth-authored P0b doc, 32K, signed off 2026-06-16) and validated against the Olympus Native contract. Re-implementing it as an embedded panel inside the SDK adds complexity for no win. A "Forge New Node" button in the editor's top bar that navigates to `/forge?from=editor&node-kind=X` with context pre-loaded is the cleanest integration. It also preserves the visual language of the Soulforge chat surface from Iris's mock (chat at the bottom of the editor) as a separate, full-screen experience.

**Alternatives:**
- **(a) Sibling route via top-bar button** — keeps the Thoth-authored interview design intact, context-preserved nav *(my recommendation)*
- **(b) Embedded panel in the editor's right rail** — adds SDK layout work, but one-click access. Conflicts with Iris's mock, which places the chat at the bottom, not the right rail.
- **(c) Modal overlay** — interrupts the editor flow, but keeps the editor in the background

### 7.4 — Pin the SDK version exactly (vs. follow latest)

**Recommendation: PIN `@workflowbuilder/sdk@2.1.0` exactly.** The SDK has 3 prior entry-point rewrites in 12 months. Pinning gives us a stable surface. Upgrades are a deliberate decision per release cycle, not an automatic pull.

**Alternatives:**
- **(a) Pin exact** — stable, deliberate upgrades *(my recommendation)*
- **(b) Caret range** — auto-pulls minor + patch, but a breaking change in 2.2.0 will break us

### 7.5 — Theme to Lumen in Milestone 4 (vs. accept Overflow UI as-is)

**Recommendation: SHIP Milestone 4 as S-to-M, but don't gate the pilot on it.** If the Lumen re-theme is bigger than M, accept the visual mismatch (Overflow UI inside the editor, Lumen on the shell) and re-evaluate post-pilot. The operator's workflow-authoring benefit is the actual win, not the visual polish.

**Alternatives:**
- **(a) Ship with theme override** — full visual parity, ~M extra effort *(my recommendation)*
- **(b) Ship without** — faster, visual mismatch, defer to v2

---

## 9. The handoff checklist (for Hephaestus)

**Before writing the v1.2 build plan, read in this order:**

1. **`synergy-wb-fit-assessment.md`** (16.5K) — the operator's question, the 5 risks, the recommended pilot
2. **`synergy-wb-port-adapter-spec.md`** (20.9K) — the 8 proposed endpoints, the SSE event relay design, the auth placement
3. **The 2 screenshots:**
   - `synergy-wb-demo.png` — the SDK running standalone on `localhost:4200`
   - `synergy-wb-embed-flag-on.png` — the SDK mounted inside the Conductor UI AppShell
4. **The current Phase 4 in `conductor-ui-build-plan.md`** — understand the v1.1 baseline before replacing it
5. **The Soulforge P0b design doc** (`docs/conductor-soulforge-interview-design.md`, 32K) — the interview flow that lives at `/forge`, the context-preservation pattern for editor → forge navigation
6. **The kanban plugin source** (`/home/konan/.hermes/hermes-agent/plugins/kanban/dashboard/plugin_api.py`, ~600 lines) — the 11+ REST endpoints, the WebSocket `/events` pattern, the session-token auth, the `BOARD_COLUMNS` definition, the serialization helpers
7. **The kanban API client stub** (`/home/konan/projects/conductor-ui/src/api/kanban.ts`, ~250 lines) — the 17 methods to wire, the type imports from `src/ledger_client/types.ts`

**What the v1.2 build plan must contain:**
- The 4 sub-phases of Phase 4 (4.0 through 4.3), each with: owner, pattern, scope (T-shirt size), blocked-by, deliverables, QA review task
- **The Phase 3 kanban tasks** (per §5.3.1-§5.3.8 above) — ~8 tasks, sizes S/M, blocked by nothing (can start immediately)
- The Phase 4 ↔ kanban cross-route task (5.3.8) — editor "Dispatch as task" button + kanban "Open in editor" link
- The feature flag policy: `VITE_FEATURE_SYNERGY_WB` is the kill-switch throughout the SDK pilot; default flips to `true` at end of Milestone 3
- The kill criterion: if Milestone 1 surfaces a deeper engine gap, stop and reassess
- The QA gate: every sub-phase ships with a Thoth review follow-on (operator-locked 2026-06-16)
- The no-absolute-time-estimates rule (operator-locked 2026-06-16)
- The "no Phase 0/1 modifications" guard — the spike touched `editor-spike.tsx` and `router.tsx`; further Phase 4 work should not regress those
- The "no new kanban infrastructure" rule — Phase 3 wires to the existing plugin, does not build a new one

**What the v1.2 build plan must NOT do:**
- Modify Iris's mock (it's the design source of truth, read-only)
- Re-design the 5-route shell, AppShell, Lumen scale, or per-god glow (Marvin-built scaffolding, not Iris-owned)
- Re-design the Workforge interview (Thoth-authored, Konan-signed)
- Re-design the 14-connector catalog or the right-rail inspector pattern (Iris's mock)
- Introduce new dependencies outside the SDK + its peer deps
- Ship a custom editor alongside the SDK (kill the React Flow direct usage in the spike)

---

## 10. The end state (what success looks like)

**The pilot is done when:**

1. The operator opens `/editor/$id` and sees a working visual editor (SDK mounted) with the Lumen chrome
2. The operator can drag a node from the palette, configure it in the properties panel, connect it to another node, validate, and save
3. The save lands in `~/pantheon/conductor/workflows/$id.yaml` (via `api_server.py`)
4. The operator can trigger a run from the editor's "Run" button
5. Live node state updates flow back via SSE and the canvas reflects them
6. The "Forge New Node" button opens `/forge?from=editor&node-kind=X` with context pre-loaded
7. The operator's auth token is required for every API call
8. Iris reviews the integration against her mock and approves: "this feels like the visual language I designed, not like a foreign app"
9. The QA gate passes (Thoth review follow-on, no new errors, port adapter spec is faithful to Conductor v2)
10. The feature flag can be flipped off and the placeholder restored in 1 command (kill-switch)

**The pilot is killed if:**
- Milestone 1 surfaces a deeper engine gap (e.g., PUT-then-reload breaks, or the validator rejects visually-valid graphs)
- The Lumen re-theme is XL (we accept the visual mismatch and re-evaluate)
- Synergy Codes breaks the API in 2.2.0 and the upgrade is non-trivial

---

## 11. Open questions (for Konan)

1. **Sign off on the 5 decisions in §8** — adopt SDK, ship api_server first, sibling Soulforge route, pin exact version, ship with theme override (S-to-M, not gated)
2. **Confirm the pilot kill criteria in §10** — what counts as "deeper engine gap"?
3. **Confirm Iris's review cadence** — does she review at Milestone 3 (UI integration) only, or at every sub-phase boundary?
4. **Decide on the SDK upgrade policy** — quarterly / per-release / only when needed
5. **Decide on `api_server.py` location** — `conductor/v2/api_server.py` (per the spike) or separate service?
6. **Decide on the Ledger UI-seam work** — is mounting the Conductor UI as a gated add-on inside the Ledger operator UI in scope for v1, or is that a post-Phase-5 future decision?

**Once these are answered, Hephaestus has everything needed to write the v1.2 build plan.**
