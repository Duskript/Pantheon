# Conductor UI — Build Plan v1.3 (n8n Expansion)

> **Status:** OPERATOR-LOCKED — Konan sign-off 2026-06-18 09:30Z
> **Date:** 2026-06-18
> **Author:** Hephaestus (from Thoth's Phase 4 n8n addendum + v1.2 deltas)
> **Project root:** `/home/konan/projects/conductor-ui/`
> **Supersedes:** `conductor-ui-build-plan-v1.2.md` — Phases 4.4-4.7 added per n8n addendum
> **Governing addendum:** `~/pantheon/shared/active/conductor-ui-phase-4-n8n-addendum-2026-06-18.md` (operator-locked v1.3)
> **Blueprint:** `~/pantheon/shared/active/conductor-ui-phase-4-blueprint.md` (unchanged — addendum extends, doesn't modify)

---

## 0. Provenance

| Source | What it told us |
|---|---|
| **Thoth's Phase 4 blueprint (2026-06-17)** | Adopt `@workflowbuilder/sdk` as visual editor engine. SDK handles canvas mechanics; we build Conductor v2 integration, node vocabulary, Lumen theme. Soulforge stays as sibling route at `/forge`. |
| **Thoth's n8n addendum (2026-06-18)** | Extend Phase 4 with 4 new sub-phases: live-execution dashboard (4.4), credentials store (4.5), n8n surface with triggers/sub-workflow/error policy (4.6), connector library (4.7). Operator-locked 2026-06-18 09:30Z. |
| **Marvin's spike (2026-06-17)** | SDK validated — 134 npm packages, live embed at `/editor-spike`, 11/11 acceptance criteria met. |
| **Fit assessment** | `synergy-wb-fit-assessment.md` (16.5K) — 5 risks with mitigations. |
| **Port adapter spec** | `synergy-wb-port-adapter-spec.md` (20.9K) — 8 endpoints, SSE relay design, auth placement. |
| **Konan's decisions (2026-06-17)** | Adopt SDK ✅, api_server first ✅, Soulforge sibling route ✅, pin SDK exact ✅, Lumen theme ✅, Ledger UI-seam not in v1 ✅ |
| **Konan's decisions (2026-06-18)** | 5 NEW decisions signed off: adopt 4.5/4.6/4.7 ✅, encrypted SQLite creds ✅, 12-connector starting point ✅, custom triggers as TypeScript ✅, per-node error policy 4-option ✅ |
| **Existing scaffold** | Phase 0 scaffold at `~/projects/conductor-ui/` — complete. 5 routes render, tsc clean. |
| **Existing kanban** | Hermes kanban plugin — 11+ REST endpoints, WebSocket events, 6-table SQLite. Live, in use. |

---

## 1. Tier routing summary

**Tools:** `cli_tool` (api_server.py), `direct_session` (TypeScript/React dev), `kanban_task` (dispatch)

**Pattern:** Hybrid — sequential milestone chain (4.4 → 4.5 → 4.6+4.7) with parallel branches within Phase 4.6 (7 trigger kinds) and Phase 4.7 (12 connector implementations).

**Specialists:**
- **Marvin** — primary coder (all `Action: CREATE` / `Action: MODIFY`)
- **Iris** — design review against her mock, node-type labels/icons/copy, dashboard mock, trigger icons
- **Hephaestus** — architecture review, api_server.py co-design, dispatches, tier-1 verify
- **Thoth** — tier-2 QA on all code deliverables (QA gate rule)
- **Konan** — operator sign-off at plan approval + phase boundaries

**Complexity:** Very High — SDK integration + REST API + node vocabulary + theming + kanban hook + credentials crypto + 7 trigger kinds + sub-workflow + connector library

---

## 2. Foundation — what exists

| Asset | Status |
|---|---|
| Phase 0 scaffold (23 files, 100% complete) | ✅ Done — 5 routes, tsc clean |
| Phase 3 kanban (3.1–3.7, 8 sub-phases) | ✅ Shipped — 171 kanban tests pass |
| Phase 4.0 api_server.py + Auth | ✅ Shipped — 8 endpoints, auth on 3 surfaces, 55 tests |
| Phase 4.1 Node Vocabulary (6 kinds + translator) | ✅ Shipped — 23 translator tests |
| Phase 4.2 Theme Tokens (CSS source-of-truth + generator) | ✅ Shipped — tsc clean, build green |
| Phase 4.3 Lumen Theme Override | 🔍 In QA — Tier-2: PASS_WITH_NOTES, Iris sign-off pending |
| SDK spike (`editor-spike.tsx`, live embed) | ✅ Validated |
| Conductor v2 engine (workflows, validators, CLI tools) | ✅ Live |
| Hermes kanban plugin (11+ REST endpoints, WebSocket events) | ✅ Live |
| Kanban API client (`src/api/kanban.ts`, 31 tests) | ✅ Wired |
| Soulforge interview design (`docs/conductor-soulforge-interview-design.md`, 32K) | ✅ Signed off |
| Ledger-shaped day-1 (`ledger_client/` interface + LocalStub) | ✅ Shipped (10 pre-existing test isolation failures, known) |
| 12-connector catalog (from Iris's mock) | ✅ Identified (see §4.7 for full list) |

---

## 3. Phased implementation plan (updated)

```
Phase 0 (Foundation)                    ──── ✅ DONE
  ↓
Phase 3 (Kanban Hook, 3.1–3.7)         ──── ✅ DONE
  ↓
Phase 4.0 (api_server.py + Auth)        ──── ✅ DONE
  ↓
Phase 4.1 (Node Vocabulary)             ──── ✅ DONE
  ↓
Phase 4.2 (UI Integration / Theme)      ──── ✅ DONE
  ↓
Phase 4.3 (Lumen Theme Override)        ──── 🔍 IN QA (PASS_WITH_NOTES)
  ↓
Phase 4.4 (Live-Execution Dashboard)    ──── ⏳ NEW — NOT STARTED
  ↓
Phase 4.5 (Credentials Store)           ──── ✅ DONE (kanban t_07c48241, 117 tests passing, 2026-06-22)
  ├──────────────────────────┐
  ↓                          ↓
Phase 4.6 (n8n Surface)     Phase 4.7 (Connector Library)
  │                          │
  └──────────┬───────────────┘
             ↓
Phase 3.8 (Editor↔Kanban cross-route)   ──── ⏳ Blocked on 4.2 (now unblocked)
             ↓
Phase 5 (Ledger Plug-in)               ──── ⏳ NOT STARTED
```

**Critical path:** 4.4 → 4.5 → 4.6 → 3.8 → 5.0
**Parallel paths:** 4.6 + 4.7 after 4.5; 3.8 can run concurrent with 4.6/4.7

**Sequencing rules:**
- 4.4 (dashboard) depends on 4.2/4.3 for shell + theme
- 4.5 (credentials) is foundational — 4.6 and 4.7 both consume it
- 4.6 and 4.7 can run in parallel after 4.5 (different code paths, different owners)
- Kill criterion at 4.5: if OS keyring integration or Argon2 key derivation is unworkable on the target platform, stop and reassess

---

## 4. File-by-file changes

### Phase 0 — Complete scaffold ✅ DONE

All 5 routes render. `tsc --noEmit` clean. Soulforge `groups.ts`, test `setup.ts`, mock inspection — all done.

### Phase 3 — Kanban Hook ✅ DONE (3.1–3.7)

| Sub-phase | Deliverable | Tests | Status |
|---|---|---|---|
| 3.1a | API client wired (`src/api/kanban.ts`) | 32 pass | ✅ Shipped |
| 3.1b | API client extended | — | ✅ Shipped |
| 3.2 | Board + Card UI | 39 pass | ✅ Shipped |
| 3.3 | WebSocket events (SSE live) | 13 pass | ✅ Shipped |
| 3.4 | Task detail panel | 23 pass | ✅ Shipped |
| 3.5 | Create task form | — | ✅ Shipped |
| 3.6 | Dispatch controls | — | ✅ Shipped |
| 3.7 | Connector catalog (12 connectors) | 171 pass kanban suite | ✅ Shipped |

### Phase 4.0 — api_server.py + Auth ✅ DONE

8 REST endpoints live in `~/pantheon/conductor/v2/api_server.py`. Auth on all 3 surfaces (api_server, webhook, live_stream). Single `CONDUCTOR_API_KEY` env var. 55 tests pass.

### Phase 4.1 — Node Vocabulary + Translator ✅ DONE

6 node kinds: god-call, nats-publish, decision, parallel-fanout, join, human-approval. Translator round-trips (toConductor/fromConductor). 23 translator tests pass. QA validator integration tests pass.

### Phase 4.2 — UI Integration / Theme Tokens ✅ DONE

CSS as single source of truth. Token generator (`generate-theme-tokens.mjs`). `tokens.generated.ts` (gitignored). Hand-written `tokens-helpers.ts`. Build green (12.66s).

### Phase 4.3 — Lumen Theme Override 🔍 IN QA

| Path | Action | Owner |
|---|---|---|
| `src/conductor-ui/editor/theme/overrides.css` | CREATE | Iris (lead) + Marvin (impl) |

Override `--wb-*` and `--ax-*` tokens to Lumen scale. Iris design review pending. Tier-2 QA: PASS_WITH_NOTES.

### Phase 4.4 — Live-Execution Dashboard ⏳ NEW

| Path | Action | Owner |
|---|---|---|
| `src/routes/runs.tsx` | CREATE — route registration | Marvin |
| `src/runs/dashboard.tsx` | CREATE — run list view | Marvin |
| `src/runs/detail.tsx` | CREATE — single-run SSE view | Marvin |
| `src/editor/dispatch.tsx` | MODIFY — add "View Runs" link in editor top bar | Marvin |

**Goal:** New `/runs` route showing currently-running and recently-completed workflows. Each row: workflow name, started-at, elapsed time, current node, progress bar. Click into a run for live SSE event stream. 6th route in the AppShell (was 5-route shell).

**Size:** M
**Owner:** Iris (dashboard mock) + Marvin (route, components, SSE consumption) + Thoth (QA gate)
**Blocked by:** 4.2 (shell extension), 4.3 (Lumen theme for chrome match)
**Out of scope:** Historical analytics ("runs per day", "failure rate by workflow")
**Gate:** Dashboard renders, shows real runs from kanban plugin, SSE events update live.

### Phase 4.5 — Credentials Store ⏳ NEW

**New subsystem:** `~/pantheon/conductor/credentials/`

| Path | Action | Owner |
|---|---|---|
| `~/pantheon/conductor/credentials/interface.ts` | CREATE — `Client` interface (~15 methods) | Marvin |
| `~/pantheon/conductor/credentials/types.ts` | CREATE — domain types | Marvin |
| `~/pantheon/conductor/credentials/encrypted_sqlite_impl.ts` | CREATE — production impl | Marvin |
| `~/pantheon/conductor/credentials/local_stub.ts` | CREATE — JSON-file-backed stub for tests | Marvin |
| `~/pantheon/conductor/credentials/__tests__/` | CREATE — roundtrip + encryption + access-control tests | Marvin |
| `~/pantheon/conductor/v2/api_server.py` | MODIFY — add 8 credential endpoints | Marvin + Hephaestus |

**Design:**
- Encrypted SQLite (`better-sqlite3-multiple-ciphers`) with AES-256
- Key derivation: Argon2id from operator passphrase
- Key caching: OS keyring (libsecret on Linux) for session, re-auth for writes
- Fallback: `chmod 600` file for headless/containerized deployments
- Schema: `credentials(id, name, type, encrypted_value, metadata_json, created_at, updated_at, last_used_at, rotation_policy_json)`

**REST surface (extends api_server.py):**
- `GET /api/credentials` — list (names + metadata only, no values)
- `GET /api/credentials/{id}` — read (name + metadata, no value)
- `POST /api/credentials` — create
- `PUT /api/credentials/{id}` — update
- `DELETE /api/credentials/{id}` — delete
- `POST /api/credentials/{id}/rotate` — rotate
- `POST /api/credentials/unlock` — submit passphrase to unlock session key
- All write operations require unlocked session

**Size:** L
**Owner:** Marvin (code) + Hephaestus (architecture review) + Thoth (QA gate)
**Blocked by:** 4.0 (api_server.py for the REST surface)
**Kill criterion:** If OS keyring integration or Argon2 key derivation is unworkable on the target platform, stop and reassess.
**Gate:** Credential roundtrip works (create → reference in workflow → runtime resolves → agent never sees raw value).

### Phase 4.6 — n8n Surface ⏳ NEW

#### 4.6.1 — 7 Trigger Kinds

| Kind | Needs credentials? | Notes |
|---|---|---|
| `manual-trigger` | No | "Run" button in editor |
| `webhook-trigger` | Optional | `POST /api/webhooks/{workflow_id}`, body becomes context |
| `cron-trigger` | No | Cron expression, runtime registers schedule |
| `nats-trigger` | No | Subscribes to NATS subject, inbound message becomes context |
| `email-trigger` | Yes (IMAP) | Polls IMAP server, fires on filter match |
| `polling-trigger` | Yes (HTTP auth) | Polls HTTP endpoint every N min, fires on condition match |
| `custom-trigger` | Optional | References registered trigger definition (TypeScript plugin) |

Each trigger is a PaletteItem kind with its own `node.ts`, `schema.ts`, `uischema.ts`, `icon.tsx`.

#### 4.6.2 — Sub-workflow Node

| Path | Action | Owner |
|---|---|---|
| `src/editor/nodes/sub-workflow/` | CREATE (6 files) | Marvin + Iris |

`workflow_ref` + `payload_mapping` + `join_policy`. Runtime calls `POST /api/workflows/{ref}/run`, joins on SSE. Inherits caller's credential session. Cycle detection at save time.

#### 4.6.3 — Per-node Error Policy

Property on every node kind (not a new kind):
- `fail-fast` (default) — abort workflow on failure
- `retry-with-backoff` — N retries, exponential (1s–60s cap)
- `continue-and-log` — log failure, continue
- `branch-to-error-handler` — route to sibling sub-workflow error handler

Total retry budget per workflow: 10 minutes wall-clock. After exhausted → marked failed, operator notified.

#### 4.6.4 — Conditional Execution (`when:`)

`when:` property on every node: sandboxed expression language (`$`, `==`, `!=`, `&&`, `||`, `>`, `<`). Evaluates before node runs. Skip without adding a `decision` branch.

#### 4.6.5 — Archon Patterns

- `trigger_rule: all_success | one_success | none_failed_min_one_success | all_done` on `join` nodes
- `context: fresh | continue` on every node (session isolation)
- `when:` conditional on every node

#### 4.6.6 — Test-Workflow Mode

| Path | Action | Owner |
|---|---|---|
| `~/pantheon/conductor/v2/api_server.py` | MODIFY — add `POST /api/workflows/{id}/test-run` | Marvin |
| `src/editor/test-run-panel.tsx` | CREATE — dry-run trace viewer | Marvin + Iris |

Dry-run mode: exercises full DAG but routes all external I/O through recorder. No writes to external systems. Trace is exportable JSON. "Test Workflow" button in editor top bar next to "Run."

**Size:** L (7 PaletteItem kinds, 1 property on every kind, runtime support, UI)
**Owner:** Iris (trigger icons, sub-workflow inspector) + Marvin (code) + Thoth (QA)
**Blocked by:** 4.5 (credentials), 4.0 (api_server.py)
**Gate:** Workflow with webhook trigger + god-call + connector-library step + sub-workflow runs deterministically with error policies in effect.

### Phase 4.7 — Connector Library ⏳ NEW

**12 starting connectors (from Iris's mock, screen 5 — SETTINGS / INTEGRATIONS):**

| # | Connector | Mock state |
|---|---|---|
| 1 | NATS | Active |
| 2 | Slack | Active |
| 3 | GitHub | Active |
| 4 | Discord | Not connected |
| 5 | Telegram | Active |
| 6 | Mercer CRM | Active |
| 7 | Email (SMTP) | Active |
| 8 | Linear | 401 unauthorized |
| 9 | Ichor (memory) | Active |
| 10 | PostgreSQL | Off |
| 11 | Webhook (generic) | Off |
| 12 | Anthropic API | Off |

**Connector definition format (YAML):**

```yaml
name: sendgrid-email
version: 1
type: integration
description: "Send transactional email via SendGrid"
credential_ref: sendgrid_api_key
operations:
  - id: send
    label: "Send Email"
    schema: { to: string, from: string, subject: string, body_html: string }
triggers: []
```

**Runtime:** Reads `connectors/*.yaml` at startup. Each operation becomes a PaletteItem kind. Schema validation via JSON Schema. Credential resolution at execution time.

**Operator extension:** Drop a new YAML file in `connectors/` → picked up on next start, no code changes.

**Ship requirement:** At least 3 working connectors (e.g., sendgrid-email, slack-post, http-request) as proof. The other 9 authored in parallel.

**Size:** M
**Owner:** Iris (connector picker design) + Marvin (engine code) + Konan (connector authoring)
**Blocked by:** 4.5 (credentials), 4.0 (api_server.py)
**Gate:** Connector YAML format documented, 3+ connectors working, operator-extensible validated.

### Phase 3.8 — Editor↔Kanban Cross-route ⏳

| Path | Action | Owner | Blocked by |
|---|---|---|---|
| `src/editor/dispatch.tsx` | CREATE | Marvin | 4.2 (now unblocked) |

"Dispatch as kanban task" button in editor → POSTs to kanban API. "Open in editor" link on kanban task → navigates to `/editor/$id`.

### Phase 5 — Ledger Plug-in ⏳ (unchanged from v1.1)

Data seam only. `LedgerAdapter` swap from `LocalStub`. UI mounting in Ledger operator UI is post-v1.

---

## 5. Tests + verification gates

| Phase | Gate | Command |
|---|---|---|
| **4.3** | Iris signs off: "this looks like my design language" | Iris design review |
| **4.4** | Dashboard renders, live SSE events update | `npm run test:run` + manual: view `/runs` with real workflows |
| **4.5** | Credential roundtrip: create → reference → resolve, agent never sees raw | `cd ~/pantheon && pytest conductor/credentials/tests/` |
| **4.6** | 7 triggers + sub-workflow + error policy + `when:` + test mode | `npm run test:run` + manual: trigger → god-call → connector → sub-workflow |
| **4.7** | 3+ connectors working, YAML format validated, operator-extensible | `npm run test:run` + manual: drop new YAML → engine picks it up |
| **3.8** | "Dispatch as kanban" creates real task, "Open in editor" navigates correctly | `npm run test:run` + manual: round-trip |
| **Phase 5** | LedgerAdapter swap test passes | `npm run test:run` + `npm run test:integration` |

---

## 6. Decisions applied

| # | Decision | Effect |
|---|---|---|
| **D1** | Adopt SDK | Phase 4 uses `@workflowbuilder/sdk@2.1.0` |
| **D2** | Ship api_server first | 4.0 is the first sub-phase |
| **D3** | Soulforge sibling route | `/forge` is separate; editor has "Forge New Node" button |
| **D4** | Pin SDK exact | `@workflowbuilder/sdk@2.1.0` pinned, quarterly upgrade slot |
| **D5** | Lumen theme | 4.3 ships theme override; can skip if > M |
| **D6** | Ledger UI-seam not in v1 | Phase 5 is data seam only |
| **D7** | Two-tier QA (op-locked 2026-06-17) | Hephaestus tier-1 → Thoth tier-2 on all code |
| **D8** | No time estimates | T-shirt sizes (S/M/L), not calendar durations |
| **D9** | Feature flag kill-switch | `VITE_FEATURE_SYNERGY_WB` controls SDK |
| **D10** | Adopt 4.5/4.6/4.7 (2026-06-18) | n8n expansion as 3 new sub-phases |
| **D11** | Encrypted SQLite creds (2026-06-18) | `better-sqlite3-multiple-ciphers` + Argon2 + OS keyring |
| **D12** | 12-connector starting point (2026-06-18) | From Iris's mock, operator-extensible |
| **D13** | Custom triggers as TypeScript (2026-06-18) | Developer surface, sandboxed execution |
| **D14** | 4-option error policy (2026-06-18) | `fail-fast` default, opt-in flexibility |

---

## 7. Phase scope (updated)

| Phase | Tasks | Owner(s) | Size | Status | Blocked by |
|---|---|---|---|---|---|
| Phase 0 | ~9 files | Marvin + Iris | M | ✅ DONE | — |
| Phase 3.1–3.7 | ~12 tasks | Marvin | M-L | ✅ DONE | — |
| 4.0 | 1 file + auth | Marvin + Hephaestus | M-L | ✅ DONE | — |
| 4.1 | 6 node dirs + 2 translators | Iris + Marvin | M | ✅ DONE | — |
| 4.2 | 1 rewrite + SSE + button | Iris + Marvin | S | ✅ DONE | — |
| 4.3 | 1 CSS file | Iris + Marvin | S-M | 🔍 QA | — |
| **4.4** | **1 route + 3 components** | **Iris + Marvin + Thoth** | **M** | ⏳ NEW | 4.2, 4.3 |
| **4.5** | **New credentials subsystem + 8 REST endpoints** | **Marvin + Hephaestus + Thoth** | **L** | ⏳ NEW | 4.0 |
| **4.6** | **7 trigger kinds + sub-workflow + error policy + when: + test mode** | **Iris + Marvin + Thoth** | **L** | ⏳ NEW | 4.5, 4.0 |
| **4.7** | **12 connector YAMLs + engine + connector picker** | **Iris + Marvin + Konan** | **M** | ⏳ NEW | 4.5, 4.0 |
| 3.8 | 1 file (cross-route) | Marvin | M | ⏳ | 4.2 |
| Phase 5 | Per v1.1 | Marvin + Hephaestus | S-M | ⏳ | 4.3, 3.8 |

---

## 8. Pitfalls

### Pre-existing (from v1.2)

- **OOM on 8GB.** Phase 0 crashed 5 times. Run tasks with smaller scope. Consider adding swap.
- **SDK version churn.** Pin `@2.1.0` exactly. Budget quarterly upgrade slot.
- **Node vocabulary mismatch.** Translator is the seam — test roundtrip exhaustively.
- **Overflow UI theme is beta.** Theme overrides must be resilient to upstream CSS variable changes.
- **Kanban plugin token auth.** Conductor UI must pass operator's token to `/api/plugins/kanban`.

### New (from v1.3 addendum)

| # | Risk | Mitigation | Owner |
|---|---|---|---|
| 1 | **OS keyring fails in headless deployments** | Fallback: `chmod 600` file, env var override, or explicit re-auth | Marvin |
| 2 | **Transitive sub-workflow cycles hang runtime** | Save-time cycle detection + runtime parent_run_id check | Marvin |
| 3 | **Retry-with-backoff + permanent failure = unbounded loop** | Cap total retry budget at 10 min wall-clock, notify operator | Marvin + Iris |
| 4 | **Custom triggers = unbounded attack surface** | Sandboxed execution: separate Node.js process with restricted access | Marvin |
| 5 | **Live dashboard has no historical analytics** | v1 is polling + SSE only; metrics are post-pilot | Iris + Marvin |
| 6 | **Test-workflow mode may give false confidence** | Dry-run recorder validates response *type* but doesn't commit; operator reviews trace | Marvin + Thoth |
| 7 | **0 connectors in palette on first impression** | Ship runtime with 3+ working connectors as proof | Iris + Konan + Marvin |

---

## 9. Guardrails (from addendum §11)

The v1.3 build plan MUST NOT:
- ✅ Modify Iris's mock (design source of truth, read-only)
- ✅ Re-design the 5-route shell, AppShell, Lumen scale, or per-god glow
- ✅ Re-design the Workforge interview (Thoth-authored, Konan-signed)
- ✅ Re-design the 12-connector catalog or right-rail inspector pattern
- ✅ Introduce new dependencies outside `@workflowbuilder/sdk@2.1.0` + standard sqlite/argon2/keyring libs
- ✅ Ship a custom editor alongside the SDK
- ✅ Add new kanban infrastructure (4.5/4.6/4.7 do not add kanban surfaces)
- ✅ Modifying existing Phase 0/1/2/3/4.0-4.3 deliverables

---

## 10. Post-build

When all phases ship:
1. Iris signs off: visual language matches her mock, dashboard chrome matches shell
2. Konan runs end-to-end: create workflow → add nodes → validate → save → run → view kanban task → view live dashboard
3. Feature flag kill-switch verified
4. Decision log updated
5. Phase 5 (Ledger plug-in) queued
6. SDK upgrade policy documented
7. Credentials backup procedure documented
8. Connector YAML format documented for operator extension

---

## 11. Current test baseline

```
conductor-ui: 266 pass / 10 fail (96.4%)
  - 10 failures all in local_stub.test.ts (cacheDir isolation bug, pre-existing)
  - Kanban suite: 171/171 pass
  - Translator suite: 23/23 pass
  - API client: 32/32 pass
  - Build: green (12.66s)

pantheon/conductor: 55/55 pass (api_server + auth + engine)
```

---

## 12. Sign-off

**Operator checklist:**
- [x] Phase 4 structure matches signed-off decisions (D1-D14)
- [x] Phase 3 kanban tasks are concrete and shippable — all 8 shipped
- [x] Two-tier QA enforced on all code
- [x] Feature flag kill-switch preserved
- [x] No time estimates (T-shirt sizes only)
- [x] Build path convention followed
- [x] n8n addendum §11 guardrails applied
- [x] 12-connector list from mock documented (§4.7)
- [x] Kill criterion at 4.5 defined
- [x] Phase 4.4 (dashboard) and 4.6.6 (test mode) folded in

**Operator-locked v1.3, 2026-06-18 09:30Z.**
