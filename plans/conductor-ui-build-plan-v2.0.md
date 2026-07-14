> **DEPRECATED 2026-06-23** — Superseded by `conductor-ui-build-plan-v3.0.md`
>
> # Conductor UI — Build Plan v2.0 (Unified)
>
> **Status:** DEPRECATED. This plan had multiple discrepancies with reality (mobile directory did not exist, forge was Soulforge not Workforge, connectors were not a nav item, drag-and-drop not implemented). See v3.0 for the accurate single source of truth.
>
> **Date:** 2026-06-23 (spec reviewed, 15 questions answered)
> **Author:** Hephaestus
> **Project root:** `/home/konan/projects/conductor-ui/`
> **Supersedes:** v1.3 build plan, mobile pattern pack, drift remediation plan — this is the single source of truth
> **Principle:** Nothing from prior plans is removed. Every revision is additive. This plan captures the full feature set.

---

## 0. Provenance

| Source | What it contributed |
|---|---|
| v1.3 build plan (2026-06-18) | 16-phase structure: Phase 0 scaffold, Phase 3 kanban, Phase 4.0-4.7 (SDK editor, node vocabulary, theme, live dashboard, credentials, n8n surface, connector library), Phase 5 Ledger plug-in |
| Mobile pattern pack (2026-06-21) | Mobile-responsive layout: compressed Lumen tokens, 2 HTML prototypes (workflow editor + kanban), gesture vocabulary, dot indicators + swipe navigation, column peek pattern |
| Drift remediation (2026-06-21) | R1-R6 phases: kill dead nav items, fix board, swap Soulforge→Workforge, fix connectors, populate settings, acceptance gate |
| Board Rich Data (2026-06-22) | R6a-j: task detail drawer, comments, events log, block reasons, dispatcher controls (unblock, complete, comment, assignee, priority, reclaim) |
| Soulforge interview design (2026-06-16) | Conversational chat-first authoring, NOT form-based. Adaptive follow-ups. Skip interview + Get Help chat fallback. Role-based labels. |
| Konan's feedback (2026-06-22) | Forge must be a chat, not a form. Archon coding templates required. Mobile must actually work. Kanban drag-and-drop. |

---

## 1. What Exists — Verified Working

### 1.1 Backend

| Service | Port | Status |
|---|---|---|
| Conductor API (FastAPI) | 8770 | 16 workflows, auth disabled, `/api/workflows/*`, `/health` |
| Conductor webhook gateway | 8088 | `/health`, `/webhook/{source}`, `/dispatch` |
| Hermes kanban dashboard | 9119 | 258 done tasks, board API live |
| Pantheon WebUI | 8787 | Hermes chat + settings |
| Pantheon MCP | 8010 | Athenaeum, messaging, god systems |

### 1.2 Frontend — What Renders

| Route | What it does | Status |
|---|---|---|
| `/` | Dashboard | ✅ Renders |
| `/editor` | SDK workflow editor (14 node kinds) | ✅ Renders, SDK wired |
| `/board` | Kanban board (116 tasks visible) | ✅ Renders, tasks load, detail drawer opens on click |
| `/forge` | Workforge interview | ⚠️ Renders but uses form-based interview not chat |
| `/runs` | Live execution dashboard | ⚠️ Renders but data may be empty |
| `/connectors` | Connector catalog | ⚠️ May have schema errors |
| `/settings` | Settings page | ✅ Content populated (god roster, connections, theme) |

### 1.3 Frontend — Code Exists But Not Integrated

| Component | Location | Integration status |
|---|---|---|
| Task detail drawer | `src/kanban/drawer.tsx` | ✅ Wired into board |
| Drawer controls (all 6 buttons) | `src/kanban/drawer-controls.tsx` | ✅ Wired into drawer |
| Comments display | `src/kanban/detail.tsx` | ✅ Wired via `task.comments[]` |
| Events log | `src/kanban/detail.tsx` | ✅ Wired via `task.events[]` |
| MobileAppShell | `src/mobile/MobileAppShell.tsx` | ❌ NOT imported by `AppShell.tsx` |
| MobileBoard | `src/mobile/MobileBoard.tsx` | ❌ NOT imported by board route |
| useIsMobile hook | `src/mobile/useIsMobile.ts` | ❌ NOT imported by AppShell |
| mobile-tokens.css | `src/mobile/mobile-tokens.css` | ❌ NOT included in theme |
| Workflow interview engine | `src/soulforge/InterviewEngine.tsx` | ⚠️ Used by forge but form-based, not chat |

### 1.4 Credentials Store

| File | Status |
|---|---|
| `~/pantheon/conductor/credentials/__init__.py` | ✅ Exists |
| `~/pantheon/conductor/credentials/interface.py` | ✅ Exists |
| `~/pantheon/conductor/credentials/types.py` | ✅ Exists |
| `~/pantheon/conductor/credentials/encrypted_sqlite_impl.py` | ✅ Exists |
| `~/pantheon/conductor/credentials/local_stub.py` | ✅ Exists |
| API endpoints in `api_server.py` | ✅ 8 endpoints added |

---

## 2. What Is Broken — Verified Gaps

| # | Issue | Root cause | Priority |
|---|---|---|---|
| B1 | **Forge is a form, not a chat** | Interview engine renders structured question groups instead of conversational dialogue. The soulforge interview design (§3.2) explicitly says "conversational dialogue, not rigid static questionnaire." | 🔴 Critical |
| B2 | **No Archon coding templates** | 13 workflow templates exist but zero for coding/Archon workflows. The `workflow-templates.ts` catalog needs Archon entries. | 🔴 Critical |
| B3 | **Mobile not wired** | `MobileAppShell`, `MobileBoard`, `useIsMobile`, `mobile-tokens.css` all exist in `src/mobile/` but are never imported by the main app. | 🔴 Critical |
| B4 | **No drag-and-drop** | Cards cannot be dragged between kanban columns. | 🟡 High |
| B5 | **"Get help" chat returns 404** | The "Get help" button in forge tries to open `/chat?subject=...&specialist=marvin` — no route or proxy for this exists. | 🟡 High |
| B6 | **Kanban shows 116 tasks, CLI shows 258** | Board slug mismatch or different API endpoint. The UI's kanban client may be pointing at a different board or a filtered view. | 🟡 Medium |

---

## 3. What Is Not Started — From v1.3 Plan

| Phase | Description | Status |
|---|---|---|
| 4.4 | Live-Execution Dashboard (`/runs` with SSE streaming) | ⏳ Route exists, content incomplete |
| 4.6 | n8n Surface (7 trigger kinds, sub-workflow, error policy, `when:`, Archon patterns, test-workflow mode) | ⏳ NOT STARTED |
| 4.7 | Connector Library (12 connector YAMLs, engine, picker, operator-extensible) | ⏳ NOT STARTED |
| 3.8 | Editor↔Kanban cross-route ("Dispatch as kanban task" button, "Open in editor" link) + DnD | ✅ Phase 6 shipped (commits `e8d1b65`, `45be920`, `71329fe`). P048 dispatch (12/12 tests), P049 workflow_id link (23/23), P050 DnD + P051 BlockedReasonModal (18/18, 310 draggable cards in browser). Ponytail QA: PASS_WITH_WARNINGS. See /tmp/ponytail-qa-output-phase6.md |
| 5 | Ledger Plug-in (LedgerAdapter swap from LocalStub) | ⏳ NOT STARTED |

---

## 4. Unified Implementation Plan

Phases are sequential where dependencies exist, parallel where they don't.

```
Phase 1: Fix the forge (chat interface + Archon templates + role assignments)
  ↓
Phase 2: Wire mobile (tokens → hook → shell → board, collapsible drawer)
  ↓
Phase 3: Live dashboard (SSE streaming, run detail)
  ↓
Phase 4: n8n surface (triggers as new node types, sub-workflow, error policy, when:, test mode)
  ↓
Phase 5: Connector library (12 YAMLs, engine, picker)
  ↓
Phase 6: Cross-route wiring (editor↔kanban) + kanban drag-and-drop
  ↓
Phase 7: Ledger plug-in
  ↓
Phase 8: Full acceptance sweep (every route, every feature, real browser)
```

---

## 5. Phase 1 — Fix the Forge

**Goal:** The `/forge` route shows a conversational chat interface that walks the customer through authoring a workflow node or workflow. Archon coding templates are available in the template picker with role-based labels.

### 5.1 Chat Interface

The current forge renders question groups as a form (`ReviewStep`, `CompletionStep`). It must be replaced with an **agent-driven conversational interface** that operates identically to how Soulforge is designed to work:

- A Pantheon god agent (e.g., Hephaestus) drives the conversation
- The agent asks **one question at a time**, the customer responds, the agent moves to the next question
- The agent assists the customer with adjustments throughout
- The conversation fills in the **same structured forms that already exist** — it's an interactive, less-daunting way to arrive at a `NodeArtifact` or `WorkflowArtifact`
- The "Skip interview" button drops into the structured form directly (already exists, keep it)
- The "Get help" button opens a chat with the relevant domain specialist — this requires a working `/chat` route

**Backend model:** The chat endpoint proxies to a Pantheon god profile (Hephaestus for workflow forging). The god asks targeted questions drawn from the interview schema, maps each answer into the artifact fields, and returns the next question plus accumulated state.

**Files to modify:**
- `src/routes/forge.tsx` — replace form-based interview with chat-based interview UI
- `src/soulforge/InterviewEngine.tsx` — make the engine drive a chat UI (one question at a time), not a form wizard
- `src/soulforge/types.ts` — add chat message types (`QuestionMessage`, `AnswerMessage`, `StateUpdate`)
- Create `/chat` proxy route in `serve.py` to forward to the god-profile chat backend
- New: `src/soulforge/chat-forge-backend.ts` — orchestrates the conversation, maps answers into artifact fields

**Acceptance:** Type a natural language request → agent responds with one clarifying question → answer → next question → after 2-5 exchanges, Review step shows the structured artifact → confirm → node appears on canvas.

### 5.2 Archon Coding Templates

Add to `src/soulforge/workflow-templates.ts`:

| Template | Description | Starter nodes |
|---|---|---|
| `archon-bug-fix` | Rapid bug fix pipeline | triage → implement → review → test → deploy |
| `archon-feature` | New feature from spec | research → design → implement → review → QA → ship |
| `archon-code-review` | Automated code review | fetch PR → lint → review → comment |
| `archon-refactor` | Systematic refactor | analyze → plan → extract → test → verify |
| `archon-docs` | Documentation generation | scan codebase → generate docs → review → publish |

Each template produces a `WorkflowArtifact` with pre-configured role-call nodes using **role labels** (e.g., "AI for code", "AI for review", "AI for design") — never god names. This requires adding a **role-assignment capability** to map Hermes god profiles to functional roles, so the system can route to the correct god based on role.

**Acceptance:** Open forge → "New Workflow" → template picker shows Archon templates → pick one → interview confirms details → workflow renders on canvas with pre-configured role-based nodes.

---

## 6. Phase 2 — Wire Mobile

**Goal:** Below 640px viewport, the app switches to mobile layout with a **collapsible left drawer** for navigation (not bottom tabs), column-peek kanban with swipe + dot indicators, and touch-optimized tokens.

**Nav pattern:** A highly constrained drawer (collapsible from the left) replaces bottom tabs. The drawer contains the navigation items. Currently, only Settings lives inside "More."

### 6.1 Mount mobile-tokens.css

- Import `src/mobile/mobile-tokens.css` into `src/theme/index.css` inside `@media (max-width: 639px)`
- Verify: resize browser below 640px → Lumen tokens compress, touch targets enlarge

### 6.2 Wire useIsMobile hook

- Import `useIsMobile` in `src/shell/AppShell.tsx`
- Add conditional: `{isMobile ? <MobileAppShell /> : <DesktopAppShell />}`

### 6.3 Wire MobileAppShell

- Import `MobileAppShell` from `src/mobile/`
- **Collapsible left drawer** containing nav items (Dashboard, Editor, Board, More → Settings)
- Side rail hidden entirely on mobile
- Top bar collapses to compact form (56px)
- Drawer toggle (hamburger or swipe-open)

### 6.4 Wire MobileBoard

- Import `MobileBoard` from `src/mobile/`
- Board route conditionally renders MobileBoard when `isMobile`
- Column peek: single column + 24px next-column sliver
- **Dot indicators** show which column is active
- **Swipe left/right** for column navigation (dots update to reflect active column)
- Same data hooks as desktop Board (no duplicated fetch logic)

**Acceptance:** Open on phone → collapsible left drawer → tap Board → column peek layout → dots show active column → swipe between columns → tap card → detail drawer opens → all 6 dispatcher controls work.

> **Delivered 2026-06-23 (P011, t_2c87ab90):** Dot indicators + horizontal swipe navigation shipped in `src/mobile/MobileBoard.tsx`. The dot strip remains the primary affordance; swipe uses touch events on the columns container with a 40px threshold and vertical-dominant-motion detection so card-column scrolling continues to work. The `--column-swipe-threshold` token (`30%`) in `mobile-tokens.css` is documented but not yet read at swipe-time — a separate follow-up card will bridge that.

---

## 7. Phase 3 — Live Dashboard

**Goal:** `/runs` shows currently-running and recently-completed workflow runs with live SSE updates.

**Backend prerequisite:** Before building the frontend, investigate what SSE/streaming endpoints already exist in the Conductor v2 API server (`api_server.py`). If `live_stream.py` or an equivalent SSE endpoint is available, reuse it. If not, create a new `/api/runs/stream` SSE endpoint as part of this phase.

From v1.3 plan §4.4:
- Run list view: workflow name, started-at, elapsed, current node, progress bar
- Click into a run → live SSE event stream
- "View Runs" link in editor top bar
- 6th route in AppShell (already added per drift fix)

**Files:**
- `src/runs/dashboard.tsx` — run list (create or complete)
- `src/runs/detail.tsx` — SSE event viewer (create or complete)
- `src/editor/dispatch.tsx` — add "View Runs" link
- Backend (if needed): add SSE endpoint to `api_server.py`

**Out of scope:** Historical analytics, failure rate charts.

---

## 8. Phase 4 — n8n Surface

**Goal:** Full trigger/workflow execution surface matching the v1.3 plan §4.6.

### 8.1 7 Trigger Kinds

Each trigger is an **entirely new node type** (not a property layered on existing nodes). Reference how n8n handles trigger node types and how Archon models trigger execution for patterns. Each trigger is a PaletteItem with `node.ts`, `schema.ts`, `uischema.ts`, `icon.tsx`:

| Trigger | Needs credentials |
|---|---|
| `manual-trigger` | No |
| `webhook-trigger` | Optional |
| `cron-trigger` | No |
| `nats-trigger` | No |
| `email-trigger` | Yes (IMAP) |
| `polling-trigger` | Yes (HTTP auth) |
| `custom-trigger` | Optional (TypeScript plugin) |

### 8.2 Sub-workflow Node

- `src/editor/nodes/sub-workflow/` — 6 files
- `workflow_ref` + `payload_mapping` + `join_policy`
- Cycle detection at save time

### 8.3 Per-node Error Policy

Property on every node (not a new kind):
- `fail-fast` (default)
- `retry-with-backoff` (1s–60s cap)
- `continue-and-log`
- `branch-to-error-handler`

Total retry budget: 10 min wall-clock per workflow.

### 8.4 Conditional Execution (`when:`)

- `when:` property on every node
- ⚠️ **Needs research:** The expression evaluator implementation is not yet specified. Options: TypeScript library in the frontend, or Python validator in the backend. Research n8n's `when:` implementation and Archon's conditional execution model before committing to an approach.
- Sandboxed expression language (`$`, `==`, `!=`, `&&`, `||`, `>`, `<`)
- Evaluates before node runs; skip without a `decision` branch

### 8.5 Archon Patterns

From v1.3 plan §4.6.5:
- `trigger_rule: all_success | one_success | none_failed_min_one_success | all_done` on `join` nodes
- `context: fresh | continue` on every node (session isolation)
- `when:` conditional on every node

### 8.6 Test-Workflow Mode

**Included in this phase** — not a separate plan.

- `POST /api/workflows/{id}/test-run` (backend endpoint — must be added to `api_server.py` if it doesn't already exist)
- `src/editor/test-run-panel.tsx` (frontend)
- Dry-run: exercises full DAG, routes I/O through recorder, no external writes
- "Test Workflow" button in editor top bar

---

## 9. Phase 5 — Connector Library

**Goal:** 12 connector YAMLs, connector engine, picker UI, operator-extensible. YAML files live under `~/projects/conductor-ui/src/connectors/`.

From v1.3 plan §4.7:

| # | Connector | Status |
|---|---|---|
| 1 | NATS | Active |
| 2 | Slack | Active |
| 3 | GitHub | Active |
| 4 | Discord | Not connected |
| 5 | Telegram | Active |
| 6 | Mercer CRM | Active |
| 7 | Email (SMTP) | Active |
| 8 | Linear | 401 |
| 9 | Ichor (memory) | Active |
| 10 | PostgreSQL | Off |
| 11 | Webhook (generic) | Off |
| 12 | Anthropic API | Off |

**Ship requirement:** 3+ working connectors as proof. Operator drops new YAML → picked up on restart.

---

## 10. Phase 6 — Cross-Route Wiring + Drag-and-Drop

### 10.1 Editor↔Kanban

From v1.3 plan §3.8:
- "Dispatch as kanban task" button in editor → POSTs to kanban API
- "Open in editor" link on kanban task → navigates to `/editor/$id`

### 10.2 Kanban Drag-and-Drop

**Kanban-only.** Cards can be dragged between kanban columns to change status. The kanban and editor canvas are separate domains — kanban displays workflows with their statuses, editor canvas is for workflow editing. There is no cross-route drag between them.

- Long-press (or mouse drag) to initiate drag
- Drop on target column triggers the status transition for that column
- Dragging to "Blocked" column **asks for a block reason** (but reason is **not required** — can be left empty)
- Visual feedback during drag (ghost card, drop indicator)

---

## 11. Phase 7 — Ledger Plug-in

From v1.3 plan §5:
- Data seam only: `LedgerAdapter` swap from `LocalStub`
- UI mounting in Ledger operator UI is post-v1

---

## 12. Phase 8 — Full Acceptance Sweep

Hephaestus verifies every route, every feature, in a real browser:

| Route | Verify |
|---|---|
| `/` | Dashboard renders |
| `/editor` | SDK canvas, 14 node kinds, drag nodes, connect edges |
| `/board` | Kanban columns load, click→drawer, all 6 controls work, drag cards between columns |
| `/forge` | Chat interface, conversational flow, template picker, Archon templates, produces node/workflow |
| `/runs` | Run list renders, SSE updates live, click→detail |
| `/connectors` | Connector catalog, filter, no schema errors |
| `/settings` | God roster, connections, theme toggle — all populated |
| Mobile <640px | Collapsible left drawer, column peek, dot indicators, swipe navigation, touch targets ≥48px |
| `/chat` | "Get help" chat opens, connects to specialist |

---

## 13. What Is NOT In This Plan

Explicitly out of scope — none of these were in any prior revision:

- Push notifications
- Native iOS/Android shells (PWA-only)
- Offline write-queue
- Historical analytics / metrics dashboards
- Multi-select on mobile
- Tablet-specific layouts
- Re-themed dark mode for mobile
- Workforge interview on mobile (separate design problem)

---

## 14. Decisions Applied

All decisions from v1.3 plan §6 are preserved, with D7 updated:

| # | Decision |
|---|---|
| D1 | Adopt `@workflowbuilder/sdk@2.1.0` |
| D2 | Ship api_server first |
| D3 | Soulforge sibling route at `/forge` |
| D4 | Pin SDK exact, quarterly upgrade slot |
| D5 | Lumen theme |
| D6 | Ledger UI-seam not in v1 |
| D7 | QA: Hephaestus Tier-1 → GPT-5.5 Ponytail QA gate → loop until PASS (per spec-to-kanban-dispatch skill). Thoth is escalation only. |
| D8 | No time estimates |
| D9 | Feature flag kill-switch `VITE_FEATURE_SYNERGY_WB` |
| D10 | Adopt 4.5/4.6/4.7 n8n expansion |
| D11 | Encrypted SQLite creds |
| D12 | 12-connector starting point |
| D13 | Custom triggers as TypeScript |
| D14 | 4-option error policy |
| M1 | Mobile breakpoint 640px (Tailwind `sm`) |
| M2 | Touch targets 48×48px minimum |
| M3 | 6-gesture vocabulary (tap, double-tap, long-press, swipe, drag, pinch) |
| M4 | Collapsible left drawer on mobile, side rail on desktop |

---

## 15. Guardrails

- Do NOT modify Iris's mock (design source of truth, read-only)
- Do NOT delete Soulforge code — preserve at `/soulforge` sub-route if needed
- Do NOT introduce new nav items beyond the 7-route shell
- Do NOT add new dependencies outside `@workflowbuilder/sdk@2.1.0`
- Do NOT ship a custom editor alongside the SDK
- QA loop per spec-to-kanban-dispatch: Hephaestus Tier-1 → GPT-5.5 Ponytail QA → loop until PASS → then next card
- Every Ponytail FAIL appends friction data to `~/.hermes/memories/ponytail-friction.md`
- Integration map (`docs/integration-map.md`) is the reference for file paths and API hooks
- Every phase requires browser verification, not just card status
- No card is marked "done" without passing Spec-Conformance Gate (grep + browser) AND Acceptance Gate (end-to-end)

---

## 16. Deliverables

| Phase | Files created/modified | Acceptance |
|---|---|---|
| 1 — Fix Forge | `forge.tsx`, `InterviewEngine.tsx`, `types.ts`, `workflow-templates.ts`, `chat-forge-backend.ts`, `serve.py` (chat proxy) | Chat interface works, Archon templates appear, role assignment functional |
| 2 — Mobile | `AppShell.tsx`, `index.css`, board route, `MobileAppShell.tsx`, `MobileBoard.tsx` | Phone renders mobile layout with collapsible drawer, all features work |
| 3 — Dashboard | `dashboard.tsx`, `detail.tsx`, `dispatch.tsx`, potentially `api_server.py` | `/runs` shows live runs with SSE |
| 4 — n8n | 7 node dirs, `sub-workflow/`, error policy, `when:` research card, test-run panel + backend | All 7 triggers work, sub-workflow executes, error policies fire, test-run works |
| 5 — Connectors | 12 YAMLs in `src/connectors/`, `engine.ts`, `picker.tsx`, `loader.ts`, `schema.ts`, `types.ts` | 3+ connectors work, operator-extensible |
| 6 — Cross-route | `dispatch.tsx`, kanban route, drag handlers | Drag cards between columns. Dispatch creates real task. |
| 7 — Ledger | `ledger_adapter.ts` | Adapter swap test passes |
| 8 — Sweep | Hephaestus manual verification | Every route, every feature, real browser |

---

## Resolved Questions (2026-06-23)

Step 0 of spec-to-kanban-dispatch. 15 questions asked, 15 answered.

| # | Question | Answer |
|---|---|---|
| Q1 | What backs the forge chat AI? | A Pantheon god agent (e.g., Hephaestus) drives the conversation, asking one question at a time. Identical to Soulforge design. |
| Q2 | How does conversation map to structured artifact? | Conversation fills in the same forms that already exist. Agent maps answers into artifact fields. |
| Q3 | Keep the form or replace entirely? | Keep the form as "Skip interview" path. Chat is the primary path. |
| Q4 | God names or role labels in templates? | Role labels: "AI for code", "AI for review", "AI for design". Requires role-assignment capability. |
| Q5 | Dots or swipe for mobile column navigation? | Both: dots indicate active column, swipe left/right navigates. |
| Q6 | Bottom tabs or alternative? | **Collapsible left drawer** — not bottom tabs. Currently only Settings inside More. |
| Q7 | SSE backend — reuse or new? | Investigate existing endpoint first (`live_stream.py`). New endpoint if needed. |
| Q8 | Triggers as new node types or properties? | Entirely new node types. Reference n8n + Archon for patterns. |
| Q9 | Who builds the `when:` expression evaluator? | Deferred. Needs research. Marked in plan. |
| Q10 | Test-run endpoint — separate plan? | Included in this phase. Not separate. |
| Q11 | Where do connector YAMLs live? | `~/projects/conductor-ui/src/connectors/` |
| Q12 | What does kanban drag trigger? What about Blocked? | Status transition for target column. Blocked asks for reason but **not required**. |
| Q13 | Cross-route drag between kanban and editor? | **No.** Kanban and editor are separate domains. Kanban displays workflows with statuses. |
| Q14 | Which QA gate applies? | spec-to-kanban-dispatch: Hephaestus Tier-1 → Ponytail QA → loop until PASS. Thoth escalation only. |
| Q15 | Who owns which phase? | Specialists assigned by specialty. No one "owns" a phase. Phases dictate blockers. Cards per the skill: one per file, one per seam. |

---

*End of plan. Path: `~/pantheon/plans/conductor-ui-build-plan-v2.0.md`*
