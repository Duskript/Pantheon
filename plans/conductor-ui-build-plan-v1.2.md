# Conductor UI — Build Plan v1.2 (SDK Pivot)

> **SUPERSEDED 2026-06-18:** See [conductor-ui-build-plan-v1.3.md](conductor-ui-build-plan-v1.3.md) for current state. The n8n addendum (operator-locked 2026-06-18 09:30Z) adds Phases 4.4–4.7 and revises the dependency graph.
>
> **Status:** SUPERSEDED
> **Date:** 2026-06-17
> **Author:** Hephaestus (from Thoth's Phase 4 blueprint + Konan's signed-off decisions)
> **Project root:** `/home/konan/projects/conductor-ui/`
> **Supersedes:** `conductor-ui-build-plan.md` v1.1 — Phase 4 replaced per blueprint
> **Superseded by:** `conductor-ui-build-plan-v1.3.md` — n8n expansion (2026-06-18)
> **Blueprint:** `~/pantheon/shared/active/conductor-ui-phase-4-blueprint.md` (45K, 11 sections)

---

## 0. Provenance

| Source | What it told us |
|---|---|
| **Thoth's Phase 4 blueprint (2026-06-17)** | Adopt `@workflowbuilder/sdk` as visual editor engine. SDK handles canvas mechanics; we build Conductor v2 integration, node vocabulary, Lumen theme. Soulforge stays as sibling route at `/forge`. |
| **Marvin's spike (2026-06-17)** | SDK validated — 134 npm packages, live embed at `/editor-spike`, 11/11 acceptance criteria met. Verdict: YES-WITH-CAVEATS. |
| **Fit assessment** | `synergy-wb-fit-assessment.md` (16.5K) — 5 risks with mitigations. |
| **Port adapter spec** | `synergy-wb-port-adapter-spec.md` (20.9K) — 8 endpoints, SSE relay design, auth placement. |
| **Konan's decisions (2026-06-17, 03:58Z)** | Adopt SDK ✅, api_server first ✅, Soulforge sibling route ✅, pin SDK exact ✅, Lumen theme ✅, Ledger UI-seam not in v1 ✅ |
| **Existing scaffold** | Phase 0 scaffold at `~/projects/conductor-ui/` — 23 files, package.json, src/, 10 dirs. Scaffold is 80% complete (was halted due to OOM crashes on 8GB). |
| **Existing kanban** | Hermes kanban plugin at `~/.hermes/hermes-agent/plugins/kanban/dashboard/plugin_api.py` — 11+ REST endpoints, WebSocket events, 6-table SQLite. Live, in use. |

---

## 1. Tier routing summary

**Tools:** `cli_tool` (api_server.py), `direct_session` (TypeScript/React dev), `kanban_task` (dispatch)

**Pattern:** Hybrid — sequential milestones (4.0 → 4.1 → 4.2 → 4.3) with parallel branches within Phase 3 (kanban) and Phase 4.1 (node kinds)

**Specialists:**
- **Marvin** — primary coder (all `Action: CREATE` / `Action: MODIFY`)
- **Iris** — design review against her mock, node-type labels/icons/copy
- **Hephaestus** — architecture review, api_server.py co-design, dispatches, tier-1 verify
- **Thoth** — tier-2 QA on all code deliverables
- **Konan** — operator sign-off at plan approval + phase boundaries

**Complexity:** High — SDK integration + REST API + node vocabulary + theming + kanban hook

---

## 2. Foundation — what exists

| Asset | Status |
|---|---|
| Phase 0 scaffold (23 files, 80% complete) | ✅ Partial — halted on OOM |
| SDK spike (`editor-spike.tsx`, live embed) | ✅ Validated |
| Conductor v2 engine (workflows, validators, CLI tools) | ✅ Live |
| Hermes kanban plugin (11+ REST endpoints, WebSocket events) | ✅ Live |
| Kanban API client stub (`src/api/kanban.ts`, 17 methods) | ⚠️ Stubbed — needs wiring |
| Soulforge interview design (`docs/conductor-soulforge-interview-design.md`, 32K) | ✅ Signed off |
| Ledger-shaped day-1 (`ledger_client/` interface + LocalStub) | ✅ Shipped |

**Phase 0 must be completed before Phase 3/4 dispatch.** The current scaffold needs finishing (5 route skeletons, soulforge/groups.ts, test/setup.ts, mock-inspection.md, clean tsc).

---

## 3. Phased implementation plan

```
Phase 0 (Foundation — complete scaffold)
  ↓
Phase 3 (Kanban Hook — can start immediately, parallel to Phase 4.0)
  ↓
Phase 4.0 (api_server.py + Auth — BLOCKER for save/load)
  ↓
Phase 4.1 (Node Vocabulary + Translator — 4-6 PaletteItems)
  ↓
Phase 4.2 (UI Integration — mount SDK in /editor/$id)
  ↓
Phase 4.3 (Lumen Theme Override)
  ↓
Phase 5 (Ledger Plug-in — unchanged from v1.1)
```

---

## 4. File-by-file changes

### Phase 0 — Complete scaffold (resume from halt)

| Path | Action | Owner | Notes |
|---|---|---|---|
| `src/routes/dashboard.tsx` | CREATE (skeleton) | Marvin | Placeholder dashboard |
| `src/routes/editor.tsx` | CREATE (skeleton) | Marvin | Will be replaced in 4.2 |
| `src/routes/board.tsx` | CREATE (skeleton) | Marvin | Will be replaced in Phase 3 |
| `src/routes/forge.tsx` | CREATE (skeleton) | Marvin | Soulforge interview entry |
| `src/routes/settings.tsx` | CREATE (skeleton) | Marvin | Settings placeholder |
| `src/soulforge/groups.ts` | CREATE | Marvin | 8 question groups from Olympus contract |
| `src/test/setup.ts` | CREATE | Marvin | Vitest + RTL + msw handlers |
| `docs/mock-inspection.md` | CREATE | Iris + Marvin | Screen inventory, IDs, data shapes from mock |
| `npx tsc --noEmit` | VERIFY | Marvin | Must pass clean |

**Phase 0 gate:** `cd ~/projects/conductor-ui && npx tsc --noEmit` passes, all 5 routes render.

### Phase 3 — Kanban Hook (~8 tasks, starts immediately)

#### 3.1 — Wire API client (S)
| Path | Action | Owner |
|---|---|---|
| `src/api/kanban.ts` | REWRITE | Marvin |

Replace 17 stubbed methods with real `fetchJson` calls to `/api/plugins/kanban/...`. Base URL: `http://localhost:9119/api/plugins/kanban`. Reuse existing types from `src/ledger_client/types.ts`.

#### 3.2 — Board UI (M)
| Path | Action | Owner |
|---|---|---|
| `src/kanban/board.tsx` | CREATE | Marvin |
| `src/kanban/card.tsx` | CREATE | Marvin |

7-column board (`triage/todo/ready/running/blocked/done`). Task card with parent/child, god, status. Click-to-advance-status.

#### 3.3 — Live event stream (S)
| Path | Action | Owner |
|---|---|---|
| `src/kanban/events.ts` | CREATE | Marvin |

WebSocket subscriber to `ws://localhost:9119/api/plugins/kanban/events`. Reconnect loop. Patch local cache on event.

#### 3.4 — Task detail panel (M)
| Path | Action | Owner |
|---|---|---|
| `src/kanban/detail.tsx` | CREATE | Marvin |

Single task view: parent/child tree, run log, comments, audit timeline.

#### 3.5 — Create task form (S)
| Path | Action | Owner |
|---|---|---|
| `src/kanban/create.tsx` | CREATE | Marvin |

Modal form: title, body, assignee dropdown, priority, parent, workspace.

#### 3.6 — Dispatch controls (S)
| Path | Action | Owner |
|---|---|---|
| `src/kanban/controls.tsx` | CREATE | Marvin |

Claim, advance status, abort, retry buttons. Calls existing API methods.

#### 3.7 — Connector catalog filter (S)
| Path | Action | Owner |
|---|---|---|
| `src/kanban/connectors.tsx` | CREATE | Marvin |

Surface 14-connector catalog from Iris's mock as board filter/sidebar.

#### 3.8 — Editor ↔ Kanban cross-route (M, Phase 4 work)
| Path | Action | Owner | Blocked by |
|---|---|---|---|
| `src/editor/dispatch.tsx` | CREATE | Marvin | Phase 4.2 (SDK mounted) |

"Dispatch as kanban task" button in editor → POSTs to kanban API. "Open in editor" link on kanban task → navigates to `/editor/$id`.

### Phase 4 — SDK Adoption

#### 4.0 — api_server.py + Auth (M-L)
| Path | Action | Owner |
|---|---|---|
| `~/pantheon/conductor/v2/api_server.py` | CREATE | Marvin + Hephaestus (arch review) |

8 REST endpoints (per port-adapter-spec §4.4):
- `GET /api/workflows` — list
- `GET /api/workflows/{id}` — read
- `PUT /api/workflows/{id}` — write
- `DELETE /api/workflows/{id}` — delete
- `POST /api/workflows/{id}/validate` — validate against workflow_validator.py
- `POST /api/workflows/{id}/run` — trigger execution
- `GET /api/workflows/{id}/runs` — run history
- `GET /api/workflows/{id}/runs/{run_id}/events` — SSE live state

Bearer token auth (`CONDUCTOR_API_KEY` env var). Auth also added to existing `webhook.py` and `live_stream.py`.

**Kill criterion:** If engine can't reload a PUT'd workflow at runtime, or validator rejects visually-valid graphs, stop and reassess.

#### 4.1 — Node Vocabulary + Translator (M)
| Path | Action | Owner |
|---|---|---|
| `src/conductor-ui/editor/nodes/god-call/` | CREATE | Iris (label/copy/icons) + Marvin (code) |
| `src/conductor-ui/editor/nodes/nats-publish/` | CREATE | Iris + Marvin |
| `src/conductor-ui/editor/nodes/decision/` | CREATE | Iris + Marvin |
| `src/conductor-ui/editor/nodes/parallel-fanout/` | CREATE | Iris + Marvin |
| `src/conductor-ui/editor/nodes/join/` | CREATE | Iris + Marvin |
| `src/conductor-ui/editor/nodes/human-approval/` | CREATE | Iris + Marvin |
| `src/conductor-ui/editor/translate/toConductor.ts` | CREATE | Marvin |
| `src/conductor-ui/editor/translate/fromConductor.ts` | CREATE | Marvin |

Per kind: `node.ts` (PaletteItem), `schema.ts` (JSON Forms schema), `uischema.ts` (layout), `icon.tsx` (palette icon). Translator handles `input_from` multi-input flattening.

#### 4.2 — UI Integration (S)
| Path | Action | Owner |
|---|---|---|
| `src/routes/editor.tsx` | REWRITE | Marvin + Iris (design review) |

Mount `<WorkflowBuilder.Root>` in `/editor/$id`. Wire persistence (`api` strategy → api_server.py). Wire SSE relay. Add "Forge New Node" button → navigates to `/forge?from=editor&node-kind={kind}`. Flip feature flag: `VITE_FEATURE_SYNERGY_WB=true` default. Remove `/editor-spike` placeholder. Iris reviews against her mock: does the SDK chrome work in her visual language?

#### 4.3 — Lumen Theme Override (S-M)
| Path | Action | Owner |
|---|---|---|
| `src/conductor-ui/editor/theme/overrides.css` | CREATE | Iris (lead) + Marvin (impl) |

Override `--wb-*` tokens (SDK top-level) and `--ax-*` tokens (Overflow UI design system) to map to Lumen scale. Override font family. Iris reviews: does it feel like her mock or a bolted-on foreign body? Can skip/defer if bigger than M.

### Phase 5 — Ledger Plug-in (unchanged from v1.1)

See `conductor-ui-build-plan.md` v1.1 §Phase 5. The data seam (`LedgerAdapter` swap) is the deliverable. The UI seam (mounting inside Ledger operator UI) is not in v1 per Konan's decision 11.6.

---

## 5. Tests + verification gates

| Phase | Gate | Command |
|---|---|---|
| **Phase 0** | Scaffold complete, tsc clean, all 5 routes render | `cd ~/projects/conductor-ui && npx tsc --noEmit && npm run test:run` |
| **Phase 3** | Kanban board renders, API returns real data, live events update | `npm run test:run` + manual: board shows tasks from real kanban.db |
| **4.0** | All 8 endpoints respond, auth rejects unauthenticated, PUT+reload roundtrip | `pytest conductor/v2/tests/test_api_server.py` |
| **4.1** | All 6 node kinds render in palette, translator roundtrips, validator accepts output | `npm run test:run` + manual: drag node → configure → translate → validate |
| **4.2** | Editor route mounts SDK, save/load works, "Forge New Node" navigates to /forge | `npm run test:run` + manual: create workflow → add nodes → save → reload → verify |
| **4.3** | Iris signs off: "this looks like my design language" | Iris design review |
| **Phase 5** | LedgerAdapter swap test passes | `npm run test:run` + `npm run test:integration` |

---

## 6. Decisions applied

| # | Decision | Effect |
|---|---|---|
| **D1** | Adopt SDK (8.1 YES) | Phase 4 uses `@workflowbuilder/sdk@2.1.0` — no from-scratch React Flow |
| **D2** | Ship api_server first (8.2 YES) | 4.0 is the first sub-phase — gated on nothing |
| **D3** | Soulforge sibling route (8.3a) | `/forge` is a separate route; editor has "Forge New Node" button |
| **D4** | Pin SDK exact (8.4 YES) | `@workflowbuilder/sdk@2.1.0` pinned, no caret range |
| **D5** | Lumen theme (8.5 YES) | 4.3 ships theme override; can skip if > M effort |
| **D6** | Ledger UI-seam not in v1 (11.6 NO) | Phase 5 is data seam only; UI mounting is future |
| **D7** | Two-tier QA (operator-locked 2026-06-17) | Hephaestus tier-1 verify → Thoth tier-2 final QA on all code |
| **D8** | No time estimates | Scope described as T-shirt sizes (S/M/L), not calendar durations |
| **D9** | Feature flag kill-switch | `VITE_FEATURE_SYNERGY_WB` controls SDK; can flip off in 1 command |

---

## 7. Phase scope

| Phase | Tasks | Owner(s) | Size | Blocked by |
|---|---|---|---|---|
| Phase 0 | ~9 files | Marvin + Iris | M | None (resume from halt) |
| Phase 3 | ~8 tasks | Marvin | M-L | Phase 0 |
| 4.0 | 1 file + auth hardening | Marvin + Hephaestus | M-L | Phase 0 |
| 4.1 | 6 node dirs + 2 translators | Iris + Marvin | M | 4.0 |
| 4.2 | 1 rewrite + SSE wire + button | Iris + Marvin | S | 4.0, 4.1 |
| 4.3 | 1 CSS file | Iris + Marvin | S-M | 4.2 |
| 3.8 | 1 file (cross-route) | Marvin | M | 4.2 |
| Phase 5 | Per v1.1 | Marvin + Hephaestus | S-M | 4.3 |

**Critical path:** Phase 0 → 4.0 → 4.1 → 4.2 → 3.8 → 4.3 → Phase 5
**Parallel paths:** Phase 3 (kanban) can run concurrent with 4.0/4.1

**QA overhead:** Every code deliverable gets tier-1 (Hephaestus) + tier-2 (Thoth) review. ~20 review checkpoints across all phases.

---

## 8. Pitfalls

- **OOM on 8GB.** Phase 0 crashed 5 times likely due to memory. Run Phase 0 tasks with smaller scope, avoid `npx tsc --noEmit` in the same process as `npm install`. Consider adding swap.
- **SDK version churn.** Synergy Codes has rewritten the entry point 3 times in 12 months. Pin `@2.1.0` exactly. Budget recurring upgrade slot.
- **api_server.py auth gap.** Existing `webhook.py` and `live_stream.py` bind `0.0.0.0` with no auth. Adding `CONDUCTOR_API_KEY` to all three is part of 4.0 — don't ship api_server with auth while the other two are open.
- **Node vocabulary mismatch.** Conductor v2 step kinds (god-call, nats-publish, etc.) are not 1:1 with SDK PaletteItems. The translator is the seam — test roundtrip exhaustively.
- **Overflow UI theme is beta.** The `@synergycodes/overflow-ui` design system that the SDK uses may change. Our theme overrides (`overrides.css`) need to be resilient to upstream CSS variable changes.
- **Kanban plugin token auth.** The plugin uses session-token auth (`/api/plugins/kanban` is gated). The Conductor UI needs to pass the operator's token. Use the same auth pattern as the WebUI.

---

## 9. Post-build

When all phases ship:
1. Iris signs off: visual language matches her mock
2. Konan runs end-to-end: create workflow → add nodes → validate → save → run → view kanban task
3. Feature flag kill-switch verified (flip `VITE_FEATURE_SYNERGY_WB=false` → editor restores placeholder)
4. Decision log updated
5. Phase 5 (Ledger plug-in) queued
6. SDK upgrade policy documented

---

## 10. Sign-off

**Operator checklist:**
- [ ] Phase 4 structure matches signed-off decisions (8.1-8.5, 11.6)
- [ ] Phase 3 kanban tasks are concrete and shippable
- [ ] Two-tier QA enforced on all code
- [ ] Feature flag kill-switch preserved
- [ ] No time estimates (T-shirt sizes only)
- [ ] Build path convention followed

Reply `approved` to dispatch, or `change: <what>` to revise.
