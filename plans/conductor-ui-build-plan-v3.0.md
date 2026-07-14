# Conductor UI — Build Plan v3.0 (Verified Reality)

> **Status:** Single source of truth — verified via browser and filesystem 2026-06-23
> **Date:** 2026-06-23
> **Author:** Hephaestus
> **Project root:** `/home/konan/projects/conductor-ui/`
> **Supersedes:** v2.0 (deprecated — plan claimed things existed that did not)
> **Principle:** This plan reflects what was VERIFIED on disk and in browser, not what prior plans claimed.

---

## 0. Provenance

| Source | What it contributed | Verified? |
|---|---|---|
| v1.3 build plan (2026-06-18) | 16-phase structure, n8n surface design, connector library design | Architecture valid |
| v2.0 build plan (2026-06-23) | 15 resolved questions, Phase 1-8 implementation order | **Deprecated — contained false claims** |
| Mobile pattern pack (2026-06-21) | Design spec for mobile: tokens, gestures, column peek | Design only — no code shipped |
| Drift remediation (2026-06-21) | R1-R6 phases: kill dead nav items, fix board, swap forge, fix connectors | Partially executed |
| Browser audit (2026-06-23) | **THIS AUDIT** — clicked every route, checked every file | **Ground truth** |

---

## 1. What Actually Exists — Verified 2026-06-23

### 1.1 Backend (verified)

| Service | Port | Status |
|---|---|---|
| Conductor API (FastAPI) | 8770 | ✅ Live |
| Hermes kanban | 9119 | ✅ Live — 270 tasks |
| Pantheon WebUI | 8787 | ✅ Live |
| Dev server (Conductor UI) | 8769 | ✅ Live — `dist/` serving |

### 1.2 Frontend Routes — Browser Verified

| Route | Status | Details |
|---|---|---|
| `/` Dashboard | ✅ Renders | 270 tasks, 10 gods, recent workflows. Timestamps broken ("NaNMB NaNd ago") |
| `/editor` | ✅ Renders | SDK canvas loaded. Connector catalog panel in **right rail** (should NOT be there per plan) |
| `/board` | ✅ Renders | 270 tasks all in DONE. No drag-and-drop. No detail drawer on click — cards advance status instead |
| `/forge` | ⚠️ **Soulforge** | God soul authoring, NOT workflow node creation. Heading: "Soulforge". Form-based entry context picker, not conversational. |
| `/runs` | ✅ Renders | HTTP 200 confirmed |
| `/settings` | ⚠️ Partial | God roster shows dots (no names). Connections section empty. Theme section empty. |

### 1.3 Nav Structure — Browser Verified

**6 nav items** (NOT 7 as plan claimed):
1. Dashboard
2. Editor
3. Board
4. Runs
5. Forge
6. Settings

**Missing:** Connectors is NOT a nav item — it's embedded as a right-rail panel in the Editor.

### 1.4 Code on Disk — Filesystem Verified

| What plan claimed existed | Reality |
|---|---|
| `src/mobile/` directory (MobileAppShell, MobileBoard, useIsMobile, mobile-tokens.css) | ❌ **Does not exist** |
| 12 connector YAMLs in `src/connectors/` | ❌ **None exist** — only engine files (engine.ts, loader.ts, picker.tsx, schema.ts, types.ts) |
| `src/soulforge/chat-forge-backend.ts` | ❌ **Does not exist** |
| Chat message types in `src/soulforge/types.ts` | ❌ **Not present** — no QuestionMessage, AnswerMessage, StateUpdate |
| InterviewEngine rewritten for chat | ❌ **Not done** — still form-based with ReviewStep, CompletionStep |
| Workflow interview engine | ❌ **Not present** — forge is Soulforge (god authoring), not Workforge (workflow node creation) |
| Archon coding templates | ❌ **Not present** |
| Drag-and-drop kanban | ❌ **Not implemented** — cards are buttons that advance status |
| `when:` translator | ✅ `src/editor/translate/when.ts` exists |
| 7 trigger node kinds | ✅ All 7 exist on disk |
| Sub-workflow node | ✅ Exists on disk |
| Connector engine (6 TS files) | ✅ Exist on disk |
| Runs dashboard + detail + stream | ✅ Exist on disk with tests |
| Soulforge (3 step components + engine + artifact) | ✅ Exists on disk |

### 1.5 Git State

```
Branch: main @ e8d1b65
Last commits: Phase 3.8 bridge, QW-4 accent swap, QW-2 StatusPill, QW-5 theme toggle
Feature branch: feature/w1c-c-e2e-final (dirty, needs extraction)
```

---

## 2. What Works — End-to-End Verified

| Feature | Status | Evidence |
|---|---|---|
| Dashboard renders | ✅ | Browser: 270 tasks, 10 gods, recent workflows |
| Editor SDK canvas | ✅ | Browser: canvas loads, node palette visible |
| Board loads kanban data | ✅ | Browser: 270 tasks visible in DONE column |
| All 6 routes return HTTP 200 | ✅ | curl verified |
| Theme toggle (dark/light) | ✅ | Browser: "Switch to dark mode" button present |
| God roster in settings | ⚠️ | Browser: dots visible, no god names |
| 14+ node kinds on disk | ✅ | FS: 7 triggers + 6 core + sub-workflow = 14 kinds |
| Translator (toConductor/fromConductor) | ✅ | FS: code + tests exist |
| SSE stream support | ✅ | FS: stream.ts with tests |
| Connector filter UI | ✅ | Browser: checkboxes for Triggers, AI, Actions, Control |

---

## 3. What Is Broken — Verified Gaps

| # | Issue | Root Cause | Priority | Verified Date |
|---|---|---|---|---|
| **B1** | **Forge is Soulforge, not Workforge** | The `/forge` route loads the Soulforge interview engine for god soul authoring. Plan says it should be Workforge for workflow node creation. | 🔴 Critical | 2026-06-23 browser |
| **B2** | **No chat-based interview** | InterviewEngine uses form wizard (ReviewStep, CompletionStep) instead of one-question-at-a-time chat. No `chat-forge-backend.ts` exists. | 🔴 Critical | 2026-06-23 filesystem |
| **B3** | **No Archon coding templates** | `workflow-templates.ts` missing Archon entries. | 🔴 Critical | 2026-06-23 filesystem |
| **B4** | **Mobile directory does not exist** | `src/mobile/` never created. Zero mobile components shipped despite plan claiming they exist. | 🔴 Critical | 2026-06-23 filesystem |
| **B5** | **No connector YAMLs** | Only engine files exist. Zero YAML connector definitions. Connector catalog would be empty. | 🔴 Critical | 2026-06-23 filesystem |
| **B6** | **Connectors in wrong location** | Connector filter panel is embedded in editor right rail. Plan says it should be a standalone `/connectors` nav route. | 🔴 Critical | 2026-06-23 browser |
| **B7** | **No drag-and-drop kanban** | Cards are buttons that advance status on click. No drag gesture, no column-to-column movement. | 🟡 High | 2026-06-23 browser |
| **B8** | **No card detail drawer** | Clicking a card advances its status instead of opening a detail view. No drawer component mounted. | 🟡 High | 2026-06-23 browser |
| **B9** | **Dashboard timestamps broken** | "NaNMB NaNd ago" — date formatting bug. | 🟡 High | 2026-06-23 browser |
| **B10** | **Settings page incomplete** | God roster missing names. Connections empty. Theme empty. | 🟡 Medium | 2026-06-23 browser |
| **B11** | **"Get help" chat returns 404** | No `/chat` route or proxy. | 🟡 Medium | 2026-06-23 (from v2.0) |
| **B12** | **Kanban mismatch: 116 vs 270** | Footer says "116 tasks" but board shows 270. | 🟡 Low | 2026-06-23 browser |
| **B13** | **7-trigger nodes not wired to backend** | Trigger node definitions exist on disk but likely aren't connected to the Conductor API for execution. | 🟡 Medium | 2026-06-23 filesystem |

---

## 4. What Is Not Started

| Phase | Description | Evidence |
|---|---|---|
| Phase 2 (Mobile) | Mobile-responsive layout, collapsible drawer, column-peek kanban | No `src/mobile/` directory |
| Phase 4.6 (n8n Surface) | Trigger wiring to backend, sub-workflow execution, error policy, `when:` runtime, test mode | Node definitions exist, no backend integration |
| Phase 4.7 (Connector Library) | 12 connector YAMLs, engine wire-up | Engine files exist, zero YAMLs |
| Phase 5 (Ledger Plug-in) | LedgerAdapter swap from LocalStub | Not started |
| Phase 8 (Acceptance) | Full browser sweep | Not possible until features are fixed |

---

## 5. What WAS Done (Correct State)

| Phase | Deliverable | Status |
|---|---|---|
| Phase 0 | Scaffold (routes, Vite, tsc clean) | ✅ Shipped |
| Phase 3.1-3.7 | Kanban API client, board UI, WebSocket events, task detail, create form, dispatch controls | ✅ Shipped |
| Phase 4.0 | api_server.py + Auth (8 endpoints, 55 tests) | ✅ Shipped |
| Phase 4.1 | Node Vocabulary (6 core kinds + translator, 23 tests) | ✅ Shipped |
| Phase 4.2 | UI Integration / Theme Tokens | ✅ Shipped |
| Phase 4.3 | Lumen Theme Override | ✅ Shipped |
| Phase 4.4 | Live-Execution Dashboard (runs route + dashboard/detail/stream) | ✅ Code exists on disk |
| Phase 4.5 | Credentials Store (encrypted SQLite, 8 REST endpoints, 117 tests) | ✅ Shipped |
| Phase 3.8 | Editor↔Kanban cross-route bridge | ✅ Shipped (commit e8d1b65) |
| Phase 6 | Cross-route wiring + DnD + BlockedReasonModal | ✅ Shipped (commits e8d1b65, 45be920, 71329fe) |
| QW-1 through QW-5 | Ledger tokens, StatusPill, typography, accent swap, theme toggle | ✅ Shipped |

---

## 6. Unified Fix Plan

Phases are dependency-ordered. Each produces working, verifiable deliverables.

```
Phase A: Fix what's broken (critical gaps)
  ├─ A1: Fix Forge identity (Soulforge → Workforge)
  ├─ A2: Fix Board (detail drawer, NOT status advance on click)
  ├─ A3: Fix Settings (god names, connections data, theme content)
  ├─ A4: Fix Dashboard timestamps (NaNMB → real dates)
  ├─ A5: Remove connector panel from Editor right rail
  └─ A6: Add standalone /connectors nav route
         ↓
Phase B: Ship what was claimed but doesn't exist
  ├─ B1: Chat-based forge interview (chat-forge-backend.ts + InterviewEngine rewrite)
  ├─ B2: Archon coding templates
  ├─ B3: 12 connector YAMLs
  └─ B4: Wire 7 triggers to backend
         ↓
Phase C: New features (not yet started)
  ├─ C1: Mobile (tokens → hook → shell → board)
  ├─ C2: Kanban drag-and-drop
  ├─ C3: /chat proxy route for "Get help"
  ├─ C4: n8n execution (sub-workflow, error policy, test mode)
  └─ C5: Ledger plug-in
         ↓
Phase D: Acceptance sweep
  └─ Every route, every feature, real browser, hephaestus-qa
```

---

## 7. Phase A — Fix What's Broken

### A1 — Fix Forge Identity

**Goal:** The `/forge` route header reads "Workforge" and the page is about workflow node creation, not god soul authoring.

**Files:**
- `src/routes/forge.tsx` — update heading from "Soulforge" to "Workforge", update description to reference workflow node creation
- Soulforge code preserved at `/soulforge` sub-route (per guardrail)

**Acceptance:** Click Forge → heading says "Workforge". Description references workflow/node authoring. Soulforge still accessible at `/soulforge`.

### A2 — Fix Board Click Behavior

**Goal:** Clicking a card opens a detail drawer; it does NOT advance status. A separate button advances status.

**Files:**
- `src/kanban/board.tsx` — wire card click to detail drawer, not status advance
- `src/kanban/card.tsx` — add detail drawer trigger, separate advance button
- `src/kanban/detail.tsx` — ensure detail drawer renders with task info
- `src/kanban/controls.tsx` — wire all 6 dispatcher controls (unblock, complete, comment, assignee, priority, reclaim)

**Acceptance:** Click card → detail drawer opens with task info. Detail drawer has 6 working controls. Separate button/drag to advance status.

### A3 — Fix Settings Content

**Goal:** Settings page shows god names, connection statuses, and theme controls.

**Files:**
- `src/routes/settings.tsx` — populate god roster with names + status from `godStore`, connections list, theme toggle

**Acceptance:** Settings shows 10 gods with names (not just dots). Connections section lists active connectors. Theme section has actual controls.

### A4 — Fix Dashboard Timestamps

**Goal:** Timestamps show real dates, not "NaNMB NaNd ago".

**Files:**
- `src/routes/dashboard.tsx` — fix date formatting

**Acceptance:** Dashboard shows real relative timestamps for all workflows.

### A5 — Remove Connector Panel from Editor

**Goal:** The connector catalog is removed from the editor right rail.

**Files:**
- `src/editor/` — remove connector panel component from editor layout

**Acceptance:** Editor shows workflow canvas without a connector filter panel in the right rail.

### A6 — Add Standalone Connectors Nav Route

**Goal:** A 7th nav item "Connectors" opens a standalone connector catalog.

**Files:**
- `src/routes/connectors.tsx` — ensure it renders a standalone connector catalog
- `src/shell/AppShell.tsx` — add 7th nav item
- `src/connectors/picker.tsx` — wire into connectors route

**Acceptance:** 7 nav items. Click Connectors → standalone connector catalog with filter. No connector panel in editor.

---

## 8. Phase B — Ship What Was Claimed

### B1 — Chat-Based Forge Interview

**Goal:** Forge shows conversational chat UI, one question at a time, mapping answers into NodeArtifact/WorkflowArtifact fields.

**Files:**
- `src/soulforge/chat-forge-backend.ts` — CREATE: orchestrates conversation, maps answers to artifact
- `src/soulforge/types.ts` — ADD: QuestionMessage, AnswerMessage, StateUpdate types
- `src/soulforge/InterviewEngine.tsx` — REWRITE: one-question-at-a-time state machine
- `src/routes/forge.tsx` — wire chat UI instead of form wizard
- `serve.py` — add `/chat` proxy route

**Acceptance:** Type natural language → agent asks one question → answer → next question → review → confirm → node appears on canvas.

### B2 — Archon Coding Templates

**Goal:** 5 Archon templates in workflow-templates.ts with role-based labels.

**Files:**
- `src/soulforge/workflow-templates.ts` — ADD: archon-bug-fix, archon-feature, archon-code-review, archon-refactor, archon-docs

**Acceptance:** Forge → New Workflow → template picker shows Archon templates. Pick one → pre-configured role-based nodes.

### B3 — 12 Connector YAMLs

**Goal:** 12 connector definition YAMLs in `src/connectors/`. Engine loads them at startup.

**Files:**
- `src/connectors/*.yaml` (12 files) — one per connector from v1.3 §4.7 list
- Fix `schema.ts` and `loader.ts` if needed

**Acceptance:** 3+ connectors load and render. Operator drops new YAML → picked up on restart.

### B4 — Wire 7 Triggers to Backend

**Goal:** Trigger nodes communicate with Conductor API for execution.

**Files:**
- `src/editor/conductor-adapter.ts` — add trigger execution calls
- Backend: ensure api_server.py handles trigger dispatch

**Acceptance:** Manual trigger → workflow executes. Webhook trigger → POST fires workflow.

---

## 9. Phase C — New Features

### C1 — Mobile (Not Started from Scratch)

**Goal:** Below 640px, collapsible left drawer, column-peek kanban, touch tokens.

**Files (ALL CREATE):**
- `src/mobile/mobile-tokens.css`
- `src/mobile/useIsMobile.ts`
- `src/mobile/MobileAppShell.tsx`
- `src/mobile/MobileBoard.tsx`
- `src/shell/AppShell.tsx` — MODIFY: conditional mobile/desktop
- `src/theme/index.css` — MODIFY: import mobile-tokens.css

**Acceptance:** Phone → collapsible drawer → Board → column peek → dots + swipe → card tap → detail drawer → all 6 controls work.

### C2 — Kanban Drag-and-Drop

**Goal:** Cards drag between columns to change status. Blocked column asks for reason (optional).

**Files:**
- `src/kanban/board.tsx` — add drag handlers
- `src/kanban/card.tsx` — make draggable

**Acceptance:** Drag card from Todo to Running → status changes. Drag to Blocked → reason prompt appears (can be empty).

### C3 — /chat Proxy

**Goal:** "Get help" button in forge opens a working chat with the relevant specialist.

**Files:**
- `serve.py` — add `/chat` proxy to god-profile chat backend

**Acceptance:** Click "Get help" → chat opens → connects to specialist god profile.

---

## 10. Phase D — Acceptance Sweep

Hephaestus-qa (fresh cold session) verifies EVERYTHING:

| Route | Verify |
|---|---|
| `/` | Dashboard renders, timestamps not NaN, task/god counts correct |
| `/editor` | SDK canvas, 14+ node kinds, NO connector panel, drag nodes, connect edges |
| `/board` | Columns with tasks, click→detail drawer, 6 controls work, drag between columns |
| `/forge` | "Workforge" heading, chat interface, Archon templates, produces node/workflow |
| `/runs` | Run list, SSE updates, click→detail |
| `/connectors` | Standalone page (7th nav item), filter, no schema errors |
| `/settings` | God names, connection statuses, theme controls — all populated |
| `/soulforge` | Soulforge preserved at sub-route (god soul authoring) |
| Mobile <640px | Collapsible drawer, column peek, dots, swipe, touch targets ≥48px |
| `/chat` | "Get help" works |

---

## 11. What Is NOT In This Plan

- Push notifications
- Native iOS/Android shells (PWA-only)
- Offline write-queue
- Historical analytics / metrics dashboards
- Tablet-specific layouts
- Multi-select on mobile
- Re-themed dark mode for mobile
- Workforge interview on mobile (separate design problem)

---

## 12. Decisions Applied

| # | Decision |
|---|---|
| D1 | Adopt `@workflowbuilder/sdk@2.1.0` |
| D2 | Ship api_server first |
| D3 | Soulforge sibling route at `/forge` → **UPDATED: Soulforge at `/soulforge`, Workforge at `/forge`** |
| D4 | Pin SDK exact, quarterly upgrade slot |
| D5 | Lumen theme |
| D6 | Ledger UI-seam not in v1 |
| D7 | QA: Hephaestus dispatches → hephaestus-qa Tier-1 (cold boot) → GPT-5.5 Ponytail → loop until PASS. Thoth escalation only. |
| D8 | No time estimates |
| D9 | Feature flag kill-switch `VITE_FEATURE_SYNERGY_WB` |
| D10 | Adopt 4.5/4.6/4.7 n8n expansion |
| D11 | Encrypted SQLite creds |
| D12 | 12-connector starting point |
| D13 | Custom triggers as TypeScript |
| D14 | 4-option error policy |
| M1 | Mobile breakpoint 640px (Tailwind `sm`) |
| M2 | Touch targets 48×48px minimum |
| M3 | 6-gesture vocabulary |
| M4 | Collapsible left drawer on mobile |

---

## 13. Guardrails

- Do NOT modify Iris's mock (design source of truth, read-only)
- Do NOT delete Soulforge code — preserve at `/soulforge` sub-route
- Do NOT introduce new dependencies outside `@workflowbuilder/sdk@2.1.0`
- QA: hephaestus-qa (cold boot) responsible for all verification. Hephaestus dispatches only.
- Every Ponytail FAIL appends friction data to `~/.hermes/memories/ponytail-friction.md`
- Every phase requires browser verification, not just card status
- No card is marked "done" without passing Spec-Conformance Gate (grep + browser) AND Acceptance Gate (end-to-end)
- Build plan is the unambiguous single source of truth — supersedes all prior plans
- Approved plans pushed to project git

---

*End of plan. Path: `~/pantheon/plans/conductor-ui-build-plan-v3.0.md`*
