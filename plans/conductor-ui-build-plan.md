# Conductor UI — Build Plan

> **Status:** DRAFT v1.1 — pending operator (Konan) review. Path B: this is the t3 read-the-plan checkpoint. Reply `approved` to dispatch, or `change: <what>` to revise.
> **Date:** 2026-06-16
> **Author:** Thoth (kanban task `t_aeb9804a`); v1.1 patched by Thoth after Konan answered Q1-Q8 + directed the Hephaestus→Marvin swap + QA gate rule.
> **Project root:** `/home/konan/projects/conductor-ui/` (per [Build Path Convention] — all builds live under `~/projects/`)
> **Foundation:** Iris's mock at `/home/konan/workspace/conductor-mock/` (operator-provided local files — **greenfield-from-mock**, do not base on prior desktop/webui/olympus builds)

---

## 0. Provenance — read this first

| Source | What it told us |
|---|---|
| **Operator build request** (paraphrased 2026-06-16) | "Iris has built a mock. Convert to a full project using the framework. She has established the UI and wire all of the conductor and kanban features and abilities into that system. So that is a fully operational visual workflow editor that uses a soul forge like interview process for making new nodes and workflows as an effort of reducing friction for creating new ones." |
| **tier-routing decision** (task `t_56938dca`) | Hybrid T2 (Conductor YAML for runtime architecture) + T1 (kanban tasks for build execution). User-in-the-loop with t3/t4 operator checkpoints. Soulforge is **both** a UI surface (the editor exposes it) and a workflow tool (Iris invokes it from kanban tasks). Ledger-shaped from day 1 via stubbed `ledger_client` interface. |
| **catalog lookup** (task `t_fad2b870`) | Best fit is `build-plan-conversion` (0.92 — the build itself is an instance of the 5-step user-in-the-loop chain). Best parallel pattern is `fan-out-then-merge` (0.85) for parallel UI surface work. Best approval pattern is `approval-gated` (0.88) for t3/t4. Catalog gaps logged: Soulforge interview pattern + Ledger integration pattern not in catalog (treat as build-plan decisions, queue follow-up kanban tasks to add them). |
| **Catalog gap follow-ups** (from t2) | (a) `workflows/conductor/soulforge-interview.md` — derived from the Olympus Native contract, (b) `workflows/conductor/ledger-shaped-build.md` — derived from this build's stub pattern. (c) Theoforge Visual Editor (n8n replacement) is a separate post-Conductor-v2 project, not a workflow match. |
| **Soul Forge interview design spec** | `~/athenaeum/Codex-Olympus/OLYMPUS_NATIVE_SOUL_FORGE_INTERVIEW_CONTRACT.md` (15K, 491 lines) — 8 question groups, conversational + structured, structured soul artifact output, hidden backend scaffold bundle, 4 entry contexts (new god / full reforge / targeted reforge / required reforge). **This is the contract the Conductor UI Soulforge node type must conform to.** |
| **Olympus Native app shell reference** | `~/athenaeum/Codex-Olympus/OLYMPUS_NATIVE_APP_SHELL_AND_NAVIGATION_ARCHITECTURE.md` (18K, 520 lines) — 4-layer shell model, gods-first navigation, fast-entry + workspace coexistence, deployment-aware menu/surface visibility. **Architectural reference for React-based Pantheon UIs.** |
| **The mock** | Iris's mock files at `/home/konan/workspace/conductor-mock/` (1 file: `index.html`, 111K, plus `assets/`). **Operator-provided locally — the build host can re-inspect directly.** No network call, no static export needed. The build proceeds from the artifact-first inspection recorded by t_56938dca + t_fad2b870 — 5-screen visual editor with soulforge chat at the bottom and a right-rail inspector with per-type config forms (per build request summary). First Phase 0 task MUST re-inspect the local mock files to capture the exact screen inventory, IDs, and class names. |

---

## 1. Tier routing summary (from t_56938dca)

**Tools to use:** `conductor_yaml` (runtime architecture) + `kanban_task` (build execution) + `direct_session` (Soulforge interview sessions) + `cli_tool` (when cli's ship in Phase 1 of parallel-work build)

**Pattern:** Hybrid — `pipeline` (Foundation → Runtime → Features → Editor → Ledger stubs) with `approval_gated` steps at every phase boundary. Within Phase 4 (Visual Editor), use `fan_out_fan_in` to ship the node-type editors in parallel (chat/forge, god, workflow, settings, theming).

**Catalog search terms used:** `visual workflow editor`, `node graph`, `soulforge interview`, `kanban task board`, `ledger integration stub`, `5-step user-in-the-loop`, `approval-gated phase transition`

**Estimated complexity:** **High** — 5 phases, ~30+ tasks, multi-god, novel architecture (visual node graph + soulforge-driven authoring). Rationale: high because (a) 5 distinct subsystems (Conductor runtime, Kanban dashboard, Soulforge, Visual Editor, Ledger stubs), (b) 4 builders (Iris, Marvin, Hermes, Thoth), (c) Ledger-shaped day 1 means architectural seams must be correct from Phase 0, (d) every code-producing task requires a Thoth QA review follow-on (operator-locked 2026-06-16).

**Specialists (v1.1, post Konan direction):**
- **Iris** (UI god, frontend React/Vite specialist) — UI/UX design, mock translation, theming, inspector shell, soulforge chat surface, node-type editor UI, fan-out-merge in Phase 4 as LLM judge
- **Marvin** (master coder) — **primary code producer**. Owns all file-by-file `CREATE` and `MODIFY` rows. This is the swap from v1.0: Hephaestus was named as the builder, but the operator confirmed Marvin is the workhorse and Hephaestus was reworked into **God of Building and Architecture** (conductor + builder, not planner, not architect). See `Codex-Pantheon/design/hephaestus-rework-workflow-god.md` for the rework design.
- **Hephaestus** (builder, post-rework) — executes the plan, dispatches the work to Marvin (code), Iris (UI), Thoth (review); monitors the chain; catches convention drift; reviews the design against the architecture contract. Knows which tool to reach for. Does not develop plans (Konan + Thoth do that) and does not write production code (Marvin does that). See `Codex-Pantheon/design/hephaestus-rework-workflow-god.md` for the full rework design.
- **Thoth** (research + QA) — spec author, library/dependency research, archive, **AND QA gate reviewer on all code produced** (operator-locked 2026-06-16 — every code-producing task has a follow-on Thoth review task).
- **Hermes** (PM/coordinator) — build dispatch, kanban chain construction, parent-child gating
- **Konan** (operator) — read-the-plan sign-off, phase boundary approvals, Ledger day-1 decision

**Soulforge integration:** **Both** — (a) UI surface: the visual editor has a "Forge New Node" action that opens a soulforge chat panel in the right-rail inspector (mirrors Iris's mock), (b) workflow tool: when Konan dispatches a "create a new node type X" kanban task, the system invokes Soulforge interview via `direct_session` to author the node spec before scaffold. Soulforge is the **primary authoring path** for new nodes/workflows — operators don't drop into raw JSON/YAML.

**Ledger architectural stance:** **Ledger-shaped day 1, Ledger-deferred in v1.** Phase 5 ships:
- `ledger_client/` interface module with `Client` ABC + `LocalStub` implementation
- All subsystems that touch persistence go through `ledger_client` (not raw SQLite/JSON)
- Adapter tests prove: "if you swap `LocalStub` for a real Ledger, the same code paths still work"
- **No actual Ledger features in v1.** This means: 0 schema migration work, 0 real-Ledger integration, 0 sync. Just seams. Konan's directive (Q8): "I want to have the ability to make it feel seamless inside of Ledger. So if we need to create like a rest API or something like that, it might be a good idea." → ships as the `LedgerAdapter` REST-shape interface in Phase 5, even though the adapter is never instantiated in v1. The interface contract must match what a real Ledger REST API would look like.

---

## 2. Similar workflows considered (from t_fad2b870)

| Match | Score | Use |
|---|---|---|
| `build-plan-conversion` | 0.92 | **The build itself is an instance of this pattern.** Step 1 (tier-route) ✅ done. Step 2 (find similar) ✅ done. Step 3 (write plan) ← this document. Step 4 (final sign-off) ← operator reads this plan. Step 5 (dispatch) ← after approval, Hermes creates kanban tasks for each phase. |
| `fan-out-then-merge` | 0.85 | Use in **Phase 4 only** (Visual Editor) to ship 4-5 node-type editors in parallel. Each branch owns a separate dir under `src/conductor-ui/editors/{node-type}/`. Merge task: Iris as LLM judge, writes unified `index.tsx` shell. Concurrency cap = 5. |
| `approval-gated` | 0.88 | Use between **every major build phase** (0→1, 1→2, 2→3, 3→4, 4→5) AND within t3/t4 (read-the-plan, approve-to-dispatch). Existing chain already uses this — t_9b067dde (final sign-off) is an approval-gated child of t_fad2b870. |
| `claude-x-codex-feature` | 0.80 | **Defer.** Prerequisite step types (cli_tool, parallel, merge with llm_pick_best) not yet shipped. Reserve for v2+ when cli-orchestration lands. Don't fan out to 4 coding agents in v1. |
| `forge-overnight-research` | 0.75 | Pattern reference for "Conductor YAML that has a side effect + morning-brief approval." Not directly applicable but informs the Ledger day-1 design (operator-approval-before-actual-Ledger). |

**Decision:** Use `build-plan-conversion` for the outer chain (operator check at t3 = this document, t4 = approve to dispatch). Use `fan-out-then-merge` **only** in Phase 4 for the node-type editors. Use `approval-gated` between every phase boundary. Do not invoke `claude-x-codex-feature` (prereqs not shipped) or `forge-overnight-research` (wrong pattern).

---

## 3. Foundation — Iris's mock at `/home/konan/workspace/conductor-mock/`

**Operator-locked constraint:** Do NOT base this on prior desktop/webui/olympus builds. This is **greenfield-from-mock** — the project structure, the components, the design system are all derived from Iris's mock + the Soulforge interview contract + the Olympus app-shell architecture.

**Mock file inventory (verified by Konan 2026-06-16):**
- `/home/konan/workspace/conductor-mock/index.html` (111K)
- `/home/konan/workspace/conductor-mock/assets/` (directory — contents TBD in P0a)

**What the mock contains** (per build request summary + tier-routing context — **must re-verify in Phase 0**):
- 5 screens: Dashboard, Workflow Editor, Kanban Board, Soulforge Chat, Settings
- 14-connector catalog (per AI connector taxonomy — internal to the mock)
- Visual node-graph editor with soulforge chat at the bottom
- Olympus design system (dark theme, lumen scale, god glow per active god)
- Right-rail inspector with per-type config forms

**Phase 0 task P0a** (re-inspect the mock, see §5) will lock the actual screen inventory, data shapes, and per-type config forms. This is the **artifact-first inspection** per `build-spec-authoring` Phase 0.05 — we DO NOT write the spec from assumptions; we read the artifact first.

**Reusable parts from the mock** (predicted; verify in P0a):
- Visual node graph renderer (Canvas/SVG-based, 5-10 nodes, drag-to-connect)
- Soulforge chat panel component (chat history, input, progress dots)
- Connector catalog (14 AI connectors with their config schemas)
- Right-rail inspector shell (form scaffolding, validation, save)

**Parts to rebuild from scratch** (predicted; verify in P0a):
- Backend integration (Iris's mock is frontend-only; we need the actual Conductor + Kanban + Ledger stub)
- Persistence (mock uses in-memory state; we need `ledger_client` + `kanban_db`)
- Auth + role gating (mock has none; Pantheon roles are operator/admin/agent)
- Theming (mock uses one theme; we need Olympus lumen scale + per-god glow)
- Multi-user (mock is single-user; we need operator-scope per the build)

---

## 4. Phased implementation plan

```
Phase 0 (Foundation)                  Phase 1 (Standalone Runtime)
  ↓ re-inspect mock                     ↓ wire up Conductor + Kanban APIs
  ↓ lock project layout                 ↓ build the shell + 5 routes
  ↓ forge scaffold bundle               ↓ persistence via ledger_client stub
  ↓ define ledger_client interface      ↓ auth + role gating
        ↓                                       ↓
        └───────────── approval-gated ───────────┘
                                              ↓
Phase 2 (Conductor features)           Phase 3 (Kanban features)
  ↓ workflow CRUD (list/edit/duplicate/delete)   ↓ task board (KanbanBoard component)
  ↓ rules editor (triggers, conditions, actions) ↓ dispatch (parent-child chain, claim)
  ↓ webhook config                                ↓ run view (live log, abort)
  ↓ reports (run history, audit)                  ↓ audit (decision log, handoffs)
  ↓ 5-step user-in-the-loop viz                   ↓ parent/child relationships
        ↓                                       ↓
        └───────────── approval-gated ───────────┘
                                              ↓
Phase 4 (Visual Editor — fan_out_fan_in)    Phase 5 (Ledger stubs)
  ↓ node graph renderer (Marvin)              ↓ ledger_client.LocalStub impl
  ↓ soulforge chat in inspector (Iris)          ↓ adapter tests
  ↓ node-type editors (fan-out: 4-5 agents)     ↓ schema migration framework
  ↓ drag-to-connect + node CRUD                 ↓ swap-LocalStub-for-Ledger proof
  ↓ merge: unified editor shell (Iris judge)
        ↓                                       ↓
        └───────────── approval-gated ───────────┘
```

> **v1.1 note:** The "node graph renderer" and "Ledger stubs" owners changed from Hephaestus to Marvin. This is the operator-locked swap — Marvin is the primary code producer, Hephaestus is the builder/conductor (he executes the plan, dispatches, monitors, reviews). Per the Hephaestus rework: Hephaestus does NOT develop plans (Konan + Thoth do that) and does NOT write production code (Marvin does that). Hephaestus reads the signed-off plan and dispatches.

### Phase 0: Foundation (5 tasks, scope shifted 2026-06-16)

**Scope shift (operator directive 2026-06-16, mid-dispatch):** The P0a mock re-inspection task was removed from Phase 0 and folded into Phase 1's shell work. Reason: Iris's worker crashed twice on skill resolution; the mock re-inspection is a planning artifact, not a build artifact; the v1.1 plan §3 already describes the mock's screen inventory; the formal `docs/mock-inspection.md` doc becomes a Phase 1 deliverable written by whoever builds the shell (after the shell reads the mock). Phase 0's owner changed from Iris to Marvin (Marvin has the required skills, doesn't crash on the planning skills the task loaded).

**Ships:** Locked project layout, Vite + React + TypeScript scaffold, design tokens (lumen scale + per-god glow), the `ledger_client` interface module + `LocalStub` impl + adapter tests, the Conductor + Kanban API client skeletons, the Soulforge interview question-group registry (the registry consumes the already-shipped P0b design at `docs/conductor-soulforge-interview-design.md`), the routing scaffold (5 routes: `/`, `/editor/:id?`, `/board`, `/forge`, `/settings`).

**Key deliverables:**
- `/home/konan/projects/conductor-ui/` project root (Vite 6 + React 19 + TS 6, same stack as Olympus UI per `olympus-ui` skill)
- `src/ledger_client/` — interface + LocalStub + tests
- `src/api/conductor.ts` + `src/api/kanban.ts` — typed API clients
- `src/soulforge/groups.ts` — the question groups from the P0b design (the design is signed off, this file consumes it)
- `src/theme/` — lumen scale, god glow CSS vars, dark theme by default
- 5 placeholder routes
- Existing: `docs/conductor-soulforge-interview-design.md` (P0b, signed off 2026-06-16)

**Dependencies:** None (this is Phase 0 — independent foundation). The mock is at `/home/konan/workspace/conductor-mock/` — operator-provided locally, reachable from the build host. The mock is *not* inspected in Phase 0; the inspection is Phase 1 work.

**Owner:** Marvin (post-scope-shift, 2026-06-16). Iris is reserved for Phase 1+ UI/UX work.

### Phase 1: Standalone Runtime (~9 tasks, scope shifted 2026-06-16)

**Scope shift (operator directive 2026-06-16, mid-dispatch):** Phase 1 now includes the P0a mock re-inspection (folded in from Phase 0). The `docs/mock-inspection.md` doc is a Phase 1 deliverable, written by whoever builds the shell. The shell build reads the mock as part of its work, and the doc captures the findings (5 screens, 14-connector catalog, per-type config forms, reusable parts vs parts to rebuild).

**Ships:** All 5 routes functional with the actual Conductor + Kanban backend wiring. Dashboard shows recent workflows + active tasks. Editor route opens an empty workflow. Board route shows the kanban dashboard. Forge route opens the Soulforge interview with the 7 question groups (per P0b design). Settings route shows profile + active god + theme. The system runs end-to-end without Ledger — `ledger_client.LocalStub` backs everything. The mock re-inspection doc (`docs/mock-inspection.md`) is written as part of the shell work.

**Key deliverables:**
- `docs/mock-inspection.md` — the artifact-first inspection of `/home/konan/workspace/conductor-mock/` (folded in from Phase 0 P0a, 2026-06-16)
- `src/shell/AppShell.tsx` — 4-layer shell (per Olympus Native architecture): process/bootstrap → navigation → content surface → composer
- `src/routes/dashboard.tsx` — recent workflows, active tasks, god-picker capsule
- `src/routes/editor.tsx` — workflow editor placeholder
- `src/routes/board.tsx` — kanban board placeholder
- `src/routes/forge.tsx` — soulforge interview (new-node context, per P0b design)
- `src/routes/settings.tsx` — profile, god, theme
- `src/state/` — Zustand stores: `workflowStore`, `taskStore`, `godStore`, `sessionStore`, `appStore` (per Olympus UI pattern)
- `src/ledger_client/local_stub.ts` — JSON-file-backed implementation

**Dependencies:** Phase 0 ✅

**Owner:** Iris (or whoever the dispatcher routes to for UI/UX + shell work). Marvin is on Phase 3+ for coder-heavy work.

### Phase 2: Conductor features wired into the editor (~10 tasks)

**Ships:** Workflow CRUD (list, create, edit, duplicate, delete, activate, deactivate). Rules editor (trigger type, condition builder, action picker). Webhook config (URL, method, headers, secret). Reports (run history with status, duration, god, audit). The 5-step user-in-the-loop chain visualization (a horizontal stepper showing plan-tier → similar → write → sign-off → dispatch with the actual kanban task IDs pulled from `kanban.db`).

**Key deliverables:**
- `src/conductor/workflows/` — list + detail + editor
- `src/conductor/rules/` — rule editor with trigger/condition/action components
- `src/conductor/webhooks/` — webhook config form
- `src/conductor/reports/` — run history table + filter
- `src/conductor/chain-viz/` — 5-step stepper component (per `pantheon-dev-workflow` user-in-the-loop-chains reference)
- `src/api/conductor.ts` — full implementation (Phase 0 was skeleton)

**Dependencies:** Phase 1 ✅

### Phase 3: Kanban features wired in (~10 tasks)

**Ships:** Task board (columns: triage, ready, running, blocked, done). Task card with parent/child links. Dispatch button (creates a child task chain via the dispatcher). Claim button (atomically claims a ready task). Run view (live log streaming, abort button, retry button). Audit log (decision timeline per task, who blocked, who unblocked). Filter by god, by assignee, by status, by parent.

**Key deliverables:**
- `src/kanban/board.tsx` — column-based board with drag-to-move-status (or click-to-advance)
- `src/kanban/card.tsx` — task card with parent/child, god, profile, status
- `src/kanban/run-view.tsx` — live log + abort + retry
- `src/kanban/audit.tsx` — decision timeline
- `src/api/kanban.ts` — full implementation (Phase 0 was skeleton)

**Dependencies:** Phase 1 ✅ (Phase 2 is parallelizable — same shell, different feature surface)

### Phase 4: Visual workflow editor + Soulforge-driven node creation (~15 tasks, includes fan-out)

**Ships:** Visual node graph (Canvas or SVG-based, 5-10 nodes, drag-to-connect, click-to-inspect, double-click-to-edit). Each node type has its own editor (chat node, forge node, god node, webhook node, rule node). **Soulforge chat in the right-rail inspector** for creating new nodes/workflows via conversational interview — when the operator drags a "New Node" action onto the canvas, the right rail opens the Soulforge interview, the operator walks the 8 question groups, and the structured output is rendered as a new node in the graph. This is the headline feature.

**Fan-out-then-merge shape:**
- Branch 1: `editors/chat-node/` (Marvin, with Iris design input)
- Branch 2: `editors/forge-node/` (Marvin, with Iris design input)
- Branch 3: `editors/god-node/` (Marvin, with Iris design input)
- Branch 4: `editors/webhook-node/` (Marvin, with Iris design input)
- Branch 5: `editors/rule-node/` (Marvin, with Iris design input)
- Merge: Iris as LLM judge reads all 5 editors, writes unified `editors/index.tsx` shell

**Key deliverables:**
- `src/editor/canvas/` — node graph renderer (Marvin, with Hephaestus architecture review)
- `src/editor/inspector/` — right-rail inspector shell
- `src/editor/soulforge/` — Soulforge interview integration in the inspector
- `src/editor/nodes/` — 5 node types with their config forms
- `src/editor/connection-edge.tsx` — drag-to-connect
- `src/soulforge/render-as-node.ts` — convert interview output → node spec

**Dependencies:** Phase 2 ✅ (workflows must exist before you can edit them visually) + Phase 3 ✅ (kanban tasks must exist before you can dispatch them as part of a workflow)

### Phase 5: Ledger integration stubs (~4 tasks)

**Ships:** The `ledger_client` interface is already in Phase 0. Phase 5 ships:
- `ledger_client.LocalStub` upgraded to handle all subsystems (not just the ones Phase 1-4 use)
- `ledger_client.LedgerAdapter` (real Ledger, REST-shaped — never instantiated in v1, but interface matches what a real Ledger REST API would look like per Konan's Q8 directive)
- Adapter tests proving: "swap LocalStub for LedgerAdapter → all subsystem code paths still work"
- Schema migration framework (so when real Ledger lands, migrations can be defined declaratively)
- **Documentation:** `docs/ledger-integration-day1.md` explaining what subsystems need to know about Ledger from day 1 vs. what was deferred

**Key deliverables:**
- `src/ledger_client/adapter.ts` — real Ledger adapter (REST-shaped, never instantiated)
- `src/ledger_client/migrations/` — declarative migration framework
- `tests/ledger_client/` — adapter swap tests (the proof)

**Dependencies:** Phase 4 ✅ (so all subsystems exist and the adapter tests can prove the seams hold)

### Total scope

- **Phases:** 6 (0, 1, 2, 3, 4, 5)
- **Tasks:** ~53 (6 + 8 + 10 + 10 + 15 + 4) plus ~53 follow-on Thoth QA review tasks (one per code-producing task)
- **Builders:** Iris (UI/UX), Marvin (code), Hephaestus (builds + executes + monitors), Hermes (PM), Thoth (QA + research), Konan + Thoth (plan)
- **Critical path:** Phase 0 → Phase 1 → Phase 2/3 (parallel) → Phase 4 → Phase 5

---

## 5. File-by-file changes

> **v1.1 note:** All `Owner` cells are **Marvin** unless explicitly named otherwise (Iris for UI/UX-heavy work, Hephaestus for architecture review, Thoth for QA reviews). Every code-producing row has a follow-on Thoth QA review task (not shown in this table — generated at dispatch time by `kanban-orchestrator` per the QA-gate rule in the `build-plan-orchestrator` skill v1.0.4). The `// owner: <god>` comment at the top of each file still applies.

### Phase 0 files (Foundation)

| Path | Action | Owner | Verification |
|---|---|---|---|
| `/home/konan/projects/conductor-ui/package.json` | CREATE | Marvin | `npm install` succeeds; Vite 6 + React 19 + TS 6 + TanStack Router + Tailwind v4 + Zustand |
| `/home/konan/projects/conductor-ui/vite.config.ts` | CREATE | Marvin | `npm run dev` starts on `:5173` |
| `/home/konan/projects/conductor-ui/tsconfig.json` | CREATE | Marvin | `npx tsc --noEmit` passes |
| `/home/konan/projects/conductor-ui/index.html` | CREATE | Marvin | `<div id="root">` mounts; theme tokens applied |
| `src/main.tsx` | CREATE | Marvin | App boots; shell renders |
| `src/shell/AppShell.tsx` | CREATE (skeleton) | Marvin | 4-layer shell scaffold |
| `src/router.tsx` | CREATE | Marvin | 5 routes: `/`, `/editor/:id?`, `/board`, `/forge`, `/settings` |
| `src/routes/` × 5 | CREATE (skeletons) | Marvin | Each route renders a placeholder |
| `src/theme/tokens.ts` | CREATE | Iris (design) + Marvin (impl) | 8 lumen tokens + god glow CSS vars exported |
| `src/theme/index.css` | CREATE | Iris (design) + Marvin (impl) | `@theme` block with `--color-*` mapped to lumen |
| `src/ledger_client/index.ts` | CREATE | Marvin (with Hephaestus architecture review) | `Client` interface exported; `LocalStub` is the default impl |
| `src/ledger_client/local_stub.ts` | CREATE | Marvin (with Hephaestus architecture review) | JSON-file-backed read/write/list; atomic writes |
| `src/ledger_client/types.ts` | CREATE | Marvin | Workflow, Task, God, Handoff, AuditEvent types |
| `src/ledger_client/__tests__/local_stub.test.ts` | CREATE | Marvin | 8+ tests: write/read/list/delete/atomicity |
| `src/api/conductor.ts` | CREATE (skeleton) | Marvin | Typed client with `listWorkflows`, `getWorkflow`, `createWorkflow`, etc. — stubbed |
| `src/api/kanban.ts` | CREATE (skeleton) | Marvin | Typed client with `listTasks`, `claimTask`, `dispatchChild` — stubbed |
| `src/soulforge/groups.ts` | CREATE | Marvin (transcribing from Olympus contract) | The 8 question groups from the interview contract: Core Identity, Domain & Purpose, Personality & Voice, Responsibilities & Boundaries, Working Style, Capabilities & Modality, Hidden Backend Requirements, Review & Confirmation |
| `src/soulforge/render-as-node.ts` | CREATE | Marvin | Convert interview output → node spec (used in Phase 4, but interface defined in Phase 0) |
| `src/state/` × 5 stores | CREATE (skeletons) | Marvin | Zustand: workflowStore, taskStore, godStore, sessionStore, appStore |
| `docs/mock-inspection.md` | CREATE | Iris (with Marvin assist) | The artifact-first inspection of `/home/konan/workspace/conductor-mock/` — screen inventory, IDs, data shapes |

### Phase 1 files (Standalone Runtime)

| Path | Action | Owner |
|---|---|---|
| `src/shell/AppShell.tsx` | REWRITE | Marvin (real shell with sidebar + topbar + content + composer) |
| `src/shell/Sidebar.tsx` | CREATE | Marvin (5-route nav + active god indicator) |
| `src/shell/Topbar.tsx` | CREATE | Marvin (god picker capsule + breadcrumb + profile) |
| `src/shell/Composer.tsx` | CREATE | Marvin (god-scoped quick-capture) |
| `src/routes/dashboard.tsx` | REWRITE | Marvin (recent workflows, active tasks, god picker) |
| `src/routes/editor.tsx` | REWRITE | Marvin (empty workflow placeholder) |
| `src/routes/board.tsx` | REWRITE | Marvin (kanban dashboard placeholder) |
| `src/routes/forge.tsx` | REWRITE | Marvin (Soulforge interview entry — context picker) |
| `src/routes/settings.tsx` | REWRITE | Marvin (profile, god, theme) |
| `src/api/conductor.ts` | REWRITE | Marvin (real impl, talks to Conductor at `:8770`) |
| `src/api/kanban.ts` | REWRITE | Marvin (real impl, talks to Kanban at SQLite) |
| `src/ledger_client/local_stub.ts` | EXTEND | Marvin (handle workflow + task + god + handoff CRUD) |
| `src/auth/roles.ts` | CREATE | Marvin (operator/admin/agent/observer role checks) |
| `src/auth/gate.tsx` | CREATE | Marvin (route-level role gate component) |
| `src/state/workflowStore.ts` | REWRITE | Marvin (load from API, cache, optimistic updates) |
| `src/state/taskStore.ts` | REWRITE | Marvin (load from API, claim, advance status) |
| `src/state/godStore.ts` | REWRITE | Marvin (load from `/api/gods`, apply god glow) |
| `src/state/sessionStore.ts` | REWRITE | Marvin (per-god session scoping) |
| `src/state/appStore.ts` | REWRITE | Marvin (UI state: active surface, sidebar open, theme) |
| `src/test/setup.ts` | CREATE | Marvin (Vitest + RTL + msw handlers) |
| `tests/e2e/shell-renders.test.ts` | CREATE | Marvin (5 routes render, role gate works) |

### Phase 2 files (Conductor features)

| Path | Action | Owner |
|---|---|---|
| `src/conductor/workflows/WorkflowList.tsx` | CREATE | Marvin |
| `src/conductor/workflows/WorkflowDetail.tsx` | CREATE | Marvin |
| `src/conductor/workflows/WorkflowEditor.tsx` | CREATE | Marvin (text-based YAML/JSON editor for the workflow file) |
| `src/conductor/rules/RuleEditor.tsx` | CREATE | Marvin (trigger + condition + action builder) |
| `src/conductor/rules/TriggerPicker.tsx` | CREATE | Marvin (cron, event.nats.message, handoff, manual) |
| `src/conductor/rules/ActionPicker.tsx` | CREATE | Marvin (run kanban task, call god, publish NATS) |
| `src/conductor/webhooks/WebhookConfig.tsx` | CREATE | Marvin (URL, method, headers, secret) |
| `src/conductor/reports/RunHistory.tsx` | CREATE | Marvin (filterable table) |
| `src/conductor/reports/RunDetail.tsx` | CREATE | Marvin (log stream, audit, abort) |
| `src/conductor/chain-viz/Stepper.tsx` | CREATE | Marvin (5-step user-in-the-loop stepper, per `pantheon-dev-workflow` reference) |
| `src/api/conductor.ts` | EXTEND | Marvin (add rules, webhooks, reports endpoints) |

### Phase 3 files (Kanban features)

| Path | Action | Owner |
|---|---|---|
| `src/kanban/board/KanbanBoard.tsx` | CREATE | Marvin (column-based board) |
| `src/kanban/board/Column.tsx` | CREATE | Marvin (triage/ready/running/blocked/done) |
| `src/kanban/card/TaskCard.tsx` | CREATE | Marvin (parent/child, god, profile, status) |
| `src/kanban/card/ParentChildTree.tsx` | CREATE | Marvin (inline mini-tree of relationships) |
| `src/kanban/run/RunView.tsx` | CREATE | Marvin (live log, abort, retry) |
| `src/kanban/run/LiveLog.tsx` | CREATE | Marvin (SSE consumer, formatted) |
| `src/kanban/audit/AuditLog.tsx` | CREATE | Marvin (decision timeline per task) |
| `src/kanban/dispatch/DispatchButton.tsx` | CREATE | Marvin (creates child task chain) |
| `src/kanban/dispatch/ChainBuilder.tsx` | CREATE | Marvin (picks parent + assignee + body) |
| `src/kanban/claim/ClaimButton.tsx` | CREATE | Marvin (atomically claims a ready task) |
| `src/api/kanban.ts` | EXTEND | Marvin (add claim, dispatch, audit endpoints) |

### Phase 4 files (Visual Editor — fan-out-then-merge)

| Path | Action | Owner | Branch |
|---|---|---|---|
| `src/editor/canvas/NodeGraph.tsx` | CREATE | Marvin (with Hephaestus architecture review) | (sequential — foundation) |
| `src/editor/canvas/Node.tsx` | CREATE | Marvin | (sequential) |
| `src/editor/canvas/Edge.tsx` | CREATE | Marvin | (sequential) |
| `src/editor/canvas/Background.tsx` | CREATE | Marvin | (sequential — dotted-grid) |
| `src/editor/inspector/InspectorShell.tsx` | CREATE | Iris (design) + Marvin (impl) | (sequential — used by all editors) |
| `src/editor/inspector/NodeTypePicker.tsx` | CREATE | Iris (design) + Marvin (impl) | (sequential) |
| `src/editor/soulforge/InterviewPanel.tsx` | CREATE | Iris (design) + Marvin (impl) | (sequential — Soulforge chat in inspector) |
| `src/editor/soulforge/GroupProgress.tsx` | CREATE | Iris (design) + Marvin (impl) | (sequential — 8-group progress) |
| `src/editor/soulforge/ReviewStep.tsx` | CREATE | Iris (design) + Marvin (impl) | (sequential — final review before node creation) |
| `src/editor/nodes/chat-node/ChatNodeEditor.tsx` | CREATE | Marvin | Branch 1 (parallel) |
| `src/editor/nodes/chat-node/ChatNodePreview.tsx` | CREATE | Marvin | Branch 1 |
| `src/editor/nodes/forge-node/ForgeNodeEditor.tsx` | CREATE | Marvin | Branch 2 (parallel) |
| `src/editor/nodes/forge-node/ForgeNodePreview.tsx` | CREATE | Marvin | Branch 2 |
| `src/editor/nodes/god-node/GodNodeEditor.tsx` | CREATE | Marvin | Branch 3 (parallel) |
| `src/editor/nodes/god-node/GodPicker.tsx` | CREATE | Iris (design) + Marvin (impl) | Branch 3 |
| `src/editor/nodes/webhook-node/WebhookNodeEditor.tsx` | CREATE | Marvin | Branch 4 (parallel) |
| `src/editor/nodes/rule-node/RuleNodeEditor.tsx` | CREATE | Marvin | Branch 5 (parallel) |
| `src/editor/nodes/index.tsx` | CREATE (merge) | Iris (judge) | Merge — unified node registry |
| `src/editor/canvas/DragConnect.tsx` | CREATE | Marvin (with Hephaestus architecture review) | (sequential — post-merge) |

### Phase 5 files (Ledger stubs)

| Path | Action | Owner |
|---|---|---|
| `src/ledger_client/adapter.ts` | CREATE | Marvin (REST-shaped per Konan's Q8 directive; never instantiated in v1) |
| `src/ledger_client/migrations/framework.ts` | CREATE | Marvin (declarative migration runner) |
| `src/ledger_client/migrations/v1_to_v2.example.ts` | CREATE | Marvin (example migration as a test) |
| `src/ledger_client/__tests__/adapter-swap.test.ts` | CREATE | Marvin (proves: swap LocalStub for LedgerAdapter → all code paths still work) |
| `docs/ledger-integration-day1.md` | CREATE | Marvin (documents: which subsystems needed Ledger seams day 1, which were deferred) |

---

## 6. Tests + verification gates

**Per-phase "done" check:**

| Phase | Gate | Command |
|---|---|---|
| **Phase 0** | All files created, `npx tsc --noEmit` clean, `npm test` passes, mock inspection doc written | `cd /home/konan/projects/conductor-ui && npx tsc --noEmit && npm run test:run` |
| **Phase 1** | All 5 routes render with real data, role gate works, no console errors, dark theme applies, god glow works | `npm run test:run` + manual walkthrough of all 5 routes |
| **Phase 2** | Can create/edit/duplicate/delete a workflow, can create a rule with cron trigger + kanban action, can configure a webhook, can view run history, can see the 5-step stepper for an in-flight build | `npm run test:run` + e2e: create workflow → add rule → see it in run history |
| **Phase 3** | Can see all tasks on the board, can advance/claim/dispatch, can view live log of a running task, can see audit timeline | `npm run test:run` + e2e: dispatch a 3-task chain → claim the first → see live log |
| **Phase 4** | Can open a workflow in the visual editor, can drag a "New Node" onto the canvas, can walk the Soulforge interview, can see the new node rendered with its config, can connect two nodes with an edge, can save the workflow | `npm run test:run` + e2e: open blank workflow → forge new node via Soulforge → connect to existing node → save |
| **Phase 5** | Adapter swap test passes (proving all subsystems can talk to Ledger when it ships), migration framework runs the example migration, doc explains day-1 seams | `npm run test:run` + `npm run test:integration` (adapter swap test) |

**Per-test minimums** (per `olympus-ui` skill pattern):
- Unit/component: Vitest + @testing-library/react — one render test + one interaction test per component
- Integration: msw handlers stub Conductor + Kanban + ledger_client
- E2E: Playwright for the cross-surface journeys (Phase 0-1: shell renders, Phase 2: workflow CRUD, Phase 3: task dispatch, Phase 4: visual editor + Soulforge, Phase 5: adapter swap)

**Build-test gate:** All tests must pass before advancing between phases. Konan's explicit rule: no phase transition with red tests.

**QA gate (operator-locked 2026-06-16):** Every code-producing kanban task in this build has a follow-on Thoth `Action: REVIEW` task. The reviewer task blocks until the coder task completes; the coder task is not considered done until the reviewer task passes (`pass` or `pass_with_notes`). `needs_changes` sends the coder task back for revisions. `block` halts the chain until operator decision. For Phase 0 (foundation, scaffold), the reviewer is **lighter** — verify the scaffold matches the spec, no broken imports, types pass. For Phase 4+ (soulforge, ledger, integration), the reviewer is **deeper** — verify behavior matches contract, edge cases handled, docs updated.

---

## 7. Decisions applied (Konan's answers, 2026-06-16)

This section replaces v1.0's "Open questions" table. Q1-Q8 are now answered.

| # | Question | Konan's answer | Effect on plan |
|---|---|---|---|
| **Q1** | Is Iris's mock reachable? | **Yes** — local files at `/home/konan/workspace/conductor-mock/` (index.html, 111K, plus assets/). | P0a uses the local path. No static export needed. |
| **Q2** | Confirm: greenfield-from-mock | **Confirmed.** | Project root: `/home/konan/projects/conductor-ui/`. No file reuse from `~/pantheon/webui/`. |
| **Q3** | Soulforge interview question groups: same 8 as Olympus, or node-specific? | **Konan's clarification:** "the process of having a conversation to set up all the settings and get the necessary things in order for a node to work properly. That's what I meant by soulforge like. So we would need to determine what that interview looks like." | The Soulforge interview for Conductor UI is **a new authoring process for nodes/workflows** — distinct from the Olympus god-reforge interview. The plan needs a Phase 0 task to **design the interview from scratch**: identify the 8 question groups (or different number) specific to node/workflow authoring. This is a real design decision, not a configuration choice. Phase 4 implementation depends on it. **Open design work to be done in Phase 0 — not a config knob.** |
| **Q4** | Soulforge: mandatory or default-with-opt-out? | **Default with opt-out** (operator's directive: "Default's good"). | "Skip interview" button in the inspector for advanced users. |
| **Q5** | Visual node graph library? | **React Flow** (operator's directive: "react probably"). | Phase 4 uses React Flow. |
| **Q6** | Kanban board drag library? | **@dnd-kit** (operator's directive: "That should work"). | Phase 3 uses @dnd-kit. |
| **Q7** | Server port? | **Vite proxy on `:5173` → `:8770`** (operator's directive: "That's good"). | Same pattern as `olympus-ui`. |
| **Q8** | Ledger interface: seam or full abstraction? | **Full abstraction** + **REST-shaped** (operator's directive: "Agreed. I want to have the ability to make it feel seamless inside of Ledger. So if we need to create like a rest API or something like that, it might be a good idea."). | Phase 5 ships `LedgerAdapter` as a REST-shaped stub — interface matches what a real Ledger REST API would look like, even though the adapter is never instantiated in v1. The seam is "swap LocalStub for LedgerAdapter" but the LedgerAdapter contract is "talks to a real Ledger over HTTP." |

**Additional v1.1 decisions (from Konan, not in v1.0's Q1-Q8):**

| Decision | Rationale | Effect on plan |
|---|---|---|
- **Hephaestus → Marvin swap** | "I'm noticing there's no Marvin for coding. We need to swap Hephaestus for Marvin." | All file-by-file `Owner` cells flipped from Hephaestus to Marvin. Hephaestus is the builder/conductor — he executes the plan, dispatches Marvin's tasks, monitors the chain, catches convention drift, reviews the design against the architecture contract. Hephaestus does NOT develop plans (Konan + Thoth) and does NOT write production code (Marvin). Hephaestus's rework as "God of Building and Architecture" is captured in `Codex-Pantheon/design/hephaestus-rework-workflow-god.md`. |
| **QA gate (Thoth on all code)** | "We also need to make sure there are QA checks — Thoth on all code produced — before sign off and going to the next task." | Every code-producing kanban task has a follow-on Thoth `Action: REVIEW` task. The build-plan-orchestrator skill v1.0.4 enforces this in t5's dispatch metadata. See §6. |
| **No time estimates in plans or reports** | "Stop giving me time estimates. They're always wrong." | Removed the v1.0 "5-6 weeks" / "3-4 weeks" / "~3.5 weeks" / "~5.5 weeks" timeline estimates. Replaced with "Phases, tasks, builders" scope summary. No calendar durations anywhere in this plan. |
| **All builds under `~/projects/`** | Operator directive 2026-06-16. | Project root: `/home/konan/projects/conductor-ui/`. Convention: `Codex-Pantheon/design/build-path-convention.md`. |

---

## 8. Phase scope (no calendar durations, per operator directive)

| Phase | Scope | Critical-path? | Parallelizable? |
|---|---|---|---|
| Phase 0 (Foundation) | 6 tasks | Yes | No (one builder, one mock re-inspection) |
| Phase 1 (Standalone Runtime) | ~8 tasks | Yes | Partial (Marvin can build shell while Marvin builds ledger_client tests) |
| Phase 2 (Conductor features) | ~10 tasks | No (parallel to Phase 3) | Yes — Marvin |
| Phase 3 (Kanban features) | ~10 tasks | No (parallel to Phase 2) | Yes — Marvin |
| Phase 4 (Visual Editor + fan-out) | ~15 tasks | Yes | Yes — 5 fan-out branches + 1 merge |
| Phase 5 (Ledger stubs) | ~4 tasks | No (final, can slip) | No (Marvin solo) |

**Dependencies between phases:**
- 0 → 1 (sequential)
- 1 → 2, 1 → 3 (parallelizable)
- 2 + 3 → 4 (both must complete)
- 4 → 5 (sequential, but can be brief — most of Phase 5 is test-writing)

**QA review overhead:** ~53 follow-on Thoth review tasks (one per code-producing task in the build). These run in parallel with the next coder task — they don't block phase progression unless a review returns `block`.

---

## 9. Soulforge integration design (UI level)

**Who is interviewed?** The **operator** (Konan, in v1). The Soulforge interview in the Conductor UI is operator-facing — it walks the operator through a structured set of question groups to author a new node or workflow.

**Design decision (per Q3 above):** The Olympus Native interview contract (`OLYMPUS_NATIVE_SOUL_FORGE_INTERVIEW_CONTRACT.md`) defines 8 question groups for **god-reforge authoring**. The Conductor UI Soulforge is for **node/workflow authoring** — a different domain, different questions. The plan's Phase 0 task P0b is to **design the Conductor UI Soulforge interview from scratch**, with the following constraints:
- Borrow the **structure** (question groups, conversational + structured, review step, soul artifact output) from the Olympus contract
- Determine the **content** (which question groups, how many, what node-type-specific sublayer) — this is a real design decision, not a config knob
- Phase 4 implementation depends on the Phase 0 design
- Output: `docs/conductor-soulforge-interview-design.md` (a deliverable of Phase 0, used by Phase 4)

**How is the output rendered as workflow nodes?** Per the Olympus contract's principle 3.3 (conversational first, structured underneath):
- The chat transcript is **not** the canonical artifact. The canonical artifact is a **structured soul spec** that the interview maps answers into.
- `src/soulforge/render-as-node.ts` (Phase 0 deliverable, used in Phase 4) takes the structured soul spec + node-type-specific config and produces a **node spec** in the visual editor's data format (id, position, type, label, config, connections).
- The new node is rendered on the canvas with the operator's chosen name, the soul artifact in its tooltip, and the node-type-specific config in the right-rail inspector.

**How does the interview work in the UI?**
- The operator opens the visual editor on a workflow
- They click "+ New Node" in the topbar (or drag a "+" from the node-type picker into the canvas)
- The right-rail inspector opens with the Soulforge interview panel
- The interview walks the question groups (designed in P0b), with progress dots and group names visible at the top
- The operator can edit prior answers via back-navigation or jump-to-section links
- The interview is **adaptive** — if the operator's answer is vague, the Soulforge AI asks a natural-language follow-up
- At the end, the operator sees a review screen
- On confirmation, the Soulforge interview calls `render-as-node.ts` and the new node appears on the canvas
- **Advanced users can opt out** of the interview via a "Skip interview" button in the inspector (per Q4)

**How is Soulforge invoked?**
- As a **UI surface** (the inspector panel) — the operator drives the interview
- As a **workflow tool** (the system invokes it from a kanban task) — when a kanban task is "create a new chat node that does X," the system opens a Soulforge interview session to author the spec, then writes the node to the workflow

**State persistence:** The interview is **interruptible**. The draft is saved on every answer to `ledger_client.LocalStub` (per the Olympus contract's §7.4: "pause and resume tolerance"). The operator can close the panel and come back later — the draft resumes from where they left off.

**Hidden backend requirements:** The operator should not see raw config trivia. The interview captures operator-facing soul/behavior authoring, and the **backend** (Phase 4's `render-as-node.ts`) installs the standard scaffold bundle (identity, soul artifact, profile, runtime bindings, tooling, knowledge attachments, launch-surface, notification registration, provenance) automatically. The operator only sees a warning if a hidden requirement failed and needs manual resolution.

---

## 10. Ledger integration architecture (interfaces day 1, features deferred)

**Interfaces defined day 1 (Phase 0):**

```typescript
// src/ledger_client/types.ts
export type Workflow = { id, name, definition, status, createdAt, updatedAt, ... }
export type Task = { id, title, body, status, assignee, parent, children, ... }
export type God = { id, name, domain, model, color, icon, ... }
export type Handoff = { id, from, to, payload, status, ... }
export type AuditEvent = { id, type, actor, target, payload, timestamp, ... }

// src/ledger_client/index.ts
export interface Client {
  // Workflows
  listWorkflows(): Promise<Workflow[]>
  getWorkflow(id: string): Promise<Workflow | null>
  createWorkflow(workflow: Omit<Workflow, 'id'>): Promise<Workflow>
  updateWorkflow(id: string, patch: Partial<Workflow>): Promise<Workflow>
  deleteWorkflow(id: string): Promise<void>

  // Tasks
  listTasks(filter?: TaskFilter): Promise<Task[]>
  getTask(id: string): Promise<Task | null>
  createTask(task: Omit<Task, 'id'>): Promise<Task>
  updateTask(id: string, patch: Partial<Task>): Promise<Task>
  deleteTask(id: string): Promise<void>
  claimTask(id: string, assignee: string): Promise<Task>
  dispatchChildTask(parentId: string, child: Omit<Task, 'id'>): Promise<Task>

  // Gods
  listGods(): Promise<God[]>
  getGod(id: string): Promise<God | null>

  // Handoffs
  listHandoffs(filter?: HandoffFilter): Promise<Handoff[]>
  createHandoff(handoff: Omit<Handoff, 'id'>): Promise<Handoff>
  ackHandoff(id: string, ack: any): Promise<Handoff>

  // Audit
  appendAudit(event: Omit<AuditEvent, 'id'>): Promise<AuditEvent>
  listAudit(filter?: AuditFilter): Promise<AuditEvent[]>
}
```

**Subsystems that need to know about Ledger from day 1:**

| Subsystem | Why day 1 | Deferred to Phase 5 |
|---|---|---|
| `src/ledger_client/` (itself) | Defines the interface | Adapter (REST-shaped), migrations, swap tests |
| `src/api/conductor.ts` | Uses `Client` for all CRUD | Real Conductor API integration (Phase 1) |
| `src/api/kanban.ts` | Uses `Client` for all CRUD | Real Kanban API integration (Phase 1) |
| `src/state/` × 5 stores | All stores hydrate from `Client` | Zustand persistence (always ephemeral) |
| `src/soulforge/render-as-node.ts` | Writes nodes via `Client.updateWorkflow` | Real Conductor persistence (Phase 4) |
| `src/kanban/dispatch/DispatchButton.tsx` | Creates child tasks via `Client.dispatchChildTask` | Real Kanban dispatch (Phase 3) |
| `src/ledger_client/local_stub.ts` | The default impl in v1 | Real Ledger adapter (Phase 5, never instantiated) |

**Subsystems that can ignore Ledger until Phase 5:**

- `src/theme/` (CSS only)
- `src/auth/` (role checks, no persistence)
- `src/kanban/board/` UI components (read from `taskStore`, not `Client` directly)
- `src/editor/canvas/` (graph layout, no persistence — saves go through `Client.updateWorkflow`)
- `src/components/` (generic UI primitives)

**The seam in plain English:** Every subsystem that persists data calls `Client.method()` instead of touching the database directly. The `Client` interface is the seam. In v1, `Client` is implemented by `LocalStub` (JSON files). When real Ledger ships, we write `LedgerAdapter implements Client` and swap the DI binding. No subsystem code changes. The `LedgerAdapter` contract is **REST-shaped** (per Q8) — it talks to a real Ledger over HTTP, even though the adapter is never instantiated in v1.

**Day-1 vs deferred summary:**
- **Day 1 (Phase 0):** Interface, types, `LocalStub` impl, adapter tests
- **Phase 1-4:** All subsystems use `Client` indirectly through the API clients + stores
- **Phase 5:** `LedgerAdapter` (REST-shaped, never instantiated), migration framework, swap tests, `docs/ledger-integration-day1.md`

---

## 11. Pitfalls + operator feedback to encode

From prior sessions, the build pattern that fails:
- **Skip Phase 0 mock re-inspection** → spec written from assumptions → 2 weeks of misaligned build work (Conductor UI case is similar to the Conductor YAML case on 2026-06-15)
- **Don't base on prior desktop/webui/olympus builds** → operator-locked, do not skip
- **Compacting mid-research** → context loss; we write the spec with context hot
- **One-at-a-time delegation** with spec verification → no batched fixes, no bypassed spec-reading
- **Hephaestus as planner/architect** → operator correction 2026-06-16: Hephaestus is the conductor/builder (God of Building and Architecture), NOT the planner, NOT the architect. Konan + Thoth develop the plan. Marvin writes the code. Hephaestus executes the plan, dispatches, monitors, reviews against the architecture contract. Don't conflate.
- **Time estimates in plans** → operator correction 2026-06-16: "stop giving me time estimates, they're always wrong." Phase scope only, no calendar durations.
- **No QA gate on coder tasks** → operator correction 2026-06-16: Thoth reviews all code before sign-off. The coder task is not done until the reviewer task passes.

The build pattern that works:
- **Artifact-first inspection** (the mock MUST be re-read in Phase 0 before any spec is locked)
- **Operator sign-off at every phase boundary** (the `approval-gated` pattern)
- **Complete system first** (no deferring things we can build now)
- **Extend, don't fork** (reuse Olympus UI patterns: `olympus-ui` skill's stack, `pantheon-dev-workflow` 5-step chain, OLYMPUS_NATIVE_SOUL_FORGE contract)
- **Dual-track from day 1** (Konan is v0.1 user + TheoForge is the product; the `ledger_client` seam enables future productization)
- **Builds under `~/projects/`, plans under `~/pantheon/plans/`** (build-path convention)

---

## 12. Post-build artifacts (catalog + wiki ingest)

After this plan is approved and dispatch begins, two follow-up kanban tasks should be created:

1. **Catalog entry: `workflows/conductor/soulforge-interview.md`** — derived from `OLYMPUS_NATIVE_SOUL_FORGE_INTERVIEW_CONTRACT.md` + this build's Phase 0 P0b (the Conductor UI Soulforge design) + Phase 4. Write after Phase 4 ships. Assignee: Thoth. Parent: `t_fad2b870`.
2. **Catalog entry: `workflows/conductor/ledger-shaped-build.md`** — derived from this build's Phase 0+5 design. Write after Phase 5 ships. Assignee: Thoth. Parent: `t_fad2b870`.

These close the catalog gaps flagged in t_fad2b870.

---

## 13. Operator sign-off

> **Path B: this is the t3 checkpoint.** Reply `approved` to dispatch the build (Hermes creates the kanban tasks for Phase 0 first — including P0a mock re-inspection and P0b Soulforge interview design — then progresses through phases with operator approval at each boundary), or `change: <what>` to revise specific sections. Per `pantheon-dev-workflow` user-in-the-loop-chains: the unblock comment carries context to the dispatch step.

**v1.1 changes summary (for operator's review):**
- Q1-Q8 all answered; §7 captures the decisions
- Mock path updated: `/home/konan/workspace/conductor-mock/` (local, no network)
- Hephaestus → Marvin swap on all file-by-file owners; Hephaestus is conductor/builder (God of Building and Architecture per his rework)
- QA gate added: every code-producing task has a follow-on Thoth review
- All time estimates removed (operator directive)
- Project root: `/home/konan/projects/conductor-ui/` (build-path convention)
- New Phase 0 task P0b: design the Conductor UI Soulforge interview (Q3 was a real design decision, not a config knob)
- Ledger adapter is REST-shaped (Q8)
