---
title: "Conductor UI — Phase 4 n8n-Shaped Expansion Addendum"
created: 2026-06-18
type: blueprint-addendum
status: proposal — awaiting Konan sign-off
extends: ~/pantheon/shared/active/conductor-ui-phase-4-blueprint.md
author: thoth
synthesis-from:
  - ~/athenaeum/Codex-God-thoth/research/conductor-ui-deterministic-workflow-positioning-2026-06-18.md
  - ~/athenaeum/Codex-God-thoth/research/archon-21-workflows-classification-2026-06-18.md
sign-off-criteria: see §10
---

# Conductor UI — Phase 4 n8n-Shaped Expansion Addendum

> **Purpose:** Extend the operator-locked Phase 4 blueprint with the n8n-shaped features Konan called for (2026-06-17 Telegram). The Workforge / Ledger / kanban relationship is preserved; the **surface** grows. This is an addendum, not a replacement — the original blueprint is referenced, not modified.

## TL;DR

Conductor UI is rescoping from "internal multi-god engine editor" to "the workflow builder where every step either runs or fails explicitly — n8n-shaped surface on a deterministic substrate." Phase 4 splits into 4.0 (current — SDK adoption) + **4.5 (credentials store, foundational)** + **4.6 (n8n surface: triggers, sub-workflow, error policy)** + **4.7 (connector library, starting at 14 from Iris's mock)**. **The substrate is unchanged** — Ichor gates + RALPH + operator-as-grader remain the differentiator vs n8n/Zapier/Automatisch. **The phase ordering changed from the prequel** — credentials is foundational, n8n surface consumes it, connector library builds on both.

## 1. What changes in the operator-locked blueprint (the deltas)

| Blueprint section | Original | Updated by this addendum |
|---|---|---|
| §2 "What the SDK does" | SDK gives the canvas + properties panel + drag/drop. It does NOT give us triggers, sub-workflow, error policy. | No change. The SDK is the canvas; the n8n surface is *workflow vocabulary*, not canvas. |
| §4 Milestone 2 (node vocabulary) | 4-6 PaletteItem kinds: god-call, nats-publish, decision, parallel-fanout, join, human-approval | No change. These are the *core step kinds*. The n8n surface adds *trigger kinds* and *integration kinds* as a separate vocabulary layer. |
| §5 Kanban hook | Phase 3 work, 5.3.1-5.3.8 | No change. |
| §6 Ledger plug-in path | Phase 5, data seam (`LedgerAdapter` swaps `LocalStub`) | No change. The credentials store (Phase 4.5) is a separate concern from the Ledger data seam. |
| §7.1 Adopt the SDK | YES | No change. |
| §7.2 Ship `api_server.py` in Milestone 1 | YES | No change. |
| §7.3 Keep Soulforge as sibling route | YES | No change. |
| §7.4 Pin the SDK version exactly | YES (`@workflowbuilder/sdk@2.1.0`) | **SOFTENED to:** Pin exact by default, with a deliberate quarterly upgrade slot. Justification: as the n8n surface grows, the SDK's PaletteItem / Persistence API surface will need to track upstream. Pinning exactly is still the right default; the upgrade policy is the change. |
| §7.5 Theme to Lumen | YES, S-to-M | No change. |
| §8 "The decisions to make now" | 5 decisions | **5 NEW decisions added** — see §9 below. |
| §10 "The end state" | 10 success criteria | **3 NEW success criteria added** — see §11 below. |
| §11 "Open questions" | 6 open questions | **5 NEW open questions added** — see §12 below. |
| (new) §13 | — | **The new phases 4.5, 4.6, 4.7 — added by this addendum.** |
| (new) §14 | — | **Substrate-agnostic spec commitment (added by v1.4 patch).** The Conductor UI workflow vocabulary, node attributes, and credential types are declared as portable JSON Schemas — substrate-agnostic, harness-agnostic, and operator-extensible. v1 ships Hermes-only enforcement; v2 ships the harness-adapter layer. See Operator framework `Codex-God-thoth/research/role-based-agent-architecture-pantheon-2026-06-18.md` §13. |

## 2. What does NOT change (the substrate is preserved)

- **Ichor gates + RALPH loop** are still the workflow's determinism substrate. Every step is a typed operation against a deterministic middleware layer. The n8n surface does not change the execution model.
- **Workforge interview** (Thoth-authored, Konan-signed 2026-06-16) is still the node-creation UX. The n8n surface does not introduce a second node-creation flow.
- **Ledger data seam** is still the "plug into Ledger" path (Phase 5). The credentials store is a *separate* subsystem with its own encryption + key management, following the same `ledger_client/` shape pattern.
- **Kanban surface** is still the operator's task dashboard. The n8n surface does not add a second task tracker.
- **5-route shell, AppShell, Lumen scale, per-god glow** are still Marvin-built scaffolding. Iris's design contribution is the mock and the right-rail inspector. No change.
- **14-connector catalog** is the starting point for the connector library (Phase 4.7). The catalog is operator-extensible — new connectors are added without modifying the engine.

## 3. The product claim (the spine for everything)

**Conductor UI is the workflow builder where every step in your automation either runs or fails explicitly — no silent drift, no skipped steps, no hallucinated completions.**

n8n (and Zapier, and Automatisch) treat the *workflow* as a sequence of *actions the agent took*. Conductor UI treats the *workflow* as **executable specification**. The YAML on disk is the source of truth. The runtime is the executor. The agent doesn't get to *decide* whether a step completed — the runtime returns success or it doesn't.

The Ichor gates are the substrate: Logic Gate catches a write to a file with bad syntax and returns the compiler error to the model privately before the human sees it; Handoff Gate requires git clean + tests green + state exported before a god can hand off; Phase Detection Gate swaps the system prompt and tool set per RALPH phase.

**This means the n8n-shaped surface (sub-workflows, credentials, triggers, error policies) does not change the execution model — it makes the *workflow vocabulary* richer while keeping the *workflow execution* deterministic.**

## 4. The new phases (4.5, 4.6, 4.7)

### 4.5 — Credentials Store (foundational)

**Goal:** Encrypted SQLite-backed credential store with passphrase-derived key. Workflows reference credentials by name; the runtime resolves the reference and injects the value at execution time. The agent never sees raw credential values.

**Why first:** Most n8n-shaped features (email trigger, polling trigger, OAuth-protected API triggers, connector library) need credentials. Shipping credentials first means the n8n surface and the connector library consume an already-stable primitive.

**Scope:**
- New subsystem: `~/pantheon/conductor/credentials/` (~300-500 LOC, follows the `ledger_client/` pattern)
  - `interface.ts` — `Client` interface, ~15 methods (list, get, create, update, delete, rotate, etc.)
  - `types.ts` — credential domain types (Credential, CredentialType, CredentialMetadata)
  - `encrypted_sqlite_impl.ts` — the production implementation
  - `local_stub.ts` — JSON-file-backed impl for tests
  - `__tests__/encrypted_sqlite_impl.test.ts` — roundtrip + encryption-at-rest + access-control tests
- SQLite binding: `better-sqlite3-multiple-ciphers` (or `@journeyapps/sqlcipher`) for AES-256 database encryption
- Key derivation: `argon2` (or `@node-rs/argon2`) from operator passphrase
- Key caching: OS keyring (libsecret on Linux, Keychain on macOS) for the session, with explicit re-auth required for credential *write* operations
- Schema:
  ```
  credentials(
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,        -- e.g. "sendgrid_api_key"
    type TEXT NOT NULL,                -- api_key | oauth_token | basic_auth | smtp | ssh_key | ...
    encrypted_value BLOB NOT NULL,     -- libsodium-secretbox ciphertext
    metadata_json TEXT,                -- unencrypted: {"host": "...", "port": 587, "scopes": [...]}
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_used_at TEXT,
    rotation_policy_json TEXT          -- optional: auto-rotation hints
  )
  ```
- REST surface (extends the `api_server.py` from Milestone 1):
  - `GET /api/credentials` — list (names + metadata only, no values)
  - `GET /api/credentials/{id}` — read (name + metadata, no value)
  - `POST /api/credentials` — create
  - `PUT /api/credentials/{id}` — update
  - `DELETE /api/credentials/{id}` — delete
  - `POST /api/credentials/{id}/rotate` — rotate
  - `POST /api/credentials/unlock` — submit passphrase to unlock the session key
  - All write operations require an unlocked session
- UI: credential picker in the properties panel for any node that accepts a `credential_ref` field
- Backup: the credentials DB is a separate file from Conductor v2's main DB. Backup procedure: export the encrypted DB (the encryption protects it at rest) and the key derivation salt separately.

**Sub-workflow composition note:** the sub-workflow node (Phase 4.6) inherits the caller's session key. The called workflow does not need its own credential unlock — it uses the credentials referenced in the calling workflow's context.

**Size:** M-L (new subsystem, crypto, OS keyring integration, API surface, UI)
**Owner:** Marvin (code) + Hephaestus (architecture review) + Thoth (QA gate)
**Blocked by:** Milestone 1 (api_server.py + auth)
**Out of scope:** Cloud HSM / Vault integration (the operator-passphrase model is the starting point; HSM is a future decision)
**Pattern:** sequential

### 4.6 — n8n Surface (triggers, sub-workflow, error policy)

**Goal:** Add the n8n-shaped workflow vocabulary on top of the existing 4-6 PaletteItem kinds (god-call, nats-publish, decision, parallel-fanout, join, human-approval). New node kinds: **7 trigger kinds** + **1 sub-workflow kind** + **per-node error policy** as a property of every kind.

**Why second:** Depends on 4.5 (credentials) for triggers that need auth. Independent of 4.7 (the connector library is typed operations that *use* the trigger vocabulary).

**Scope:**

**4.6.1 — Triggers (the 7 new kinds):**

| Kind | n8n equivalent | Needs credentials? | Notes |
|---|---|---|---|
| `manual-trigger` | Manual trigger | No | The "Run" button in the editor. Already in the design. |
| `webhook-trigger` | Webhook trigger | Optional (for auth on the inbound webhook) | Registers `POST /api/webhooks/{workflow_id}` on enable. Body becomes initial context. |
| `cron-trigger` | Cron trigger | No | Cron expression. Runtime registers the schedule. |
| `nats-trigger` | (custom) | No | Subscribes to a NATS subject. Inbound message becomes initial context. |
| `email-trigger` | Email trigger (IMAP) | **Yes** (IMAP credentials) | Polls IMAP server, fires on filter match. Polling interval configurable. |
| `polling-trigger` | (custom) | **Yes** (HTTP basic/bearer auth) | Polls an HTTP endpoint every N min, fires on condition match. |
| `custom-trigger` | (custom) | Optional | References a registered trigger definition (TypeScript plugin). User writes the trigger implementation. |

**4.6.0 — Substrate-agnostic node attribute (v1.4 NEW):** every node kind carries a `harness` attribute (default `"hermes"`). v1 enforces `harness: "hermes"`; v2 ships the harness-adapter layer (Hermes → Claude Code → Codex → Omnigent) per Operator framework §13. The data shape is correct in v1; the enforcement is the v2 build. **This is the spec-first commitment for the Conductor UI node vocabulary.**

**4.6.2 — Sub-workflow node kind:**
- `sub-workflow` PaletteItem takes: `workflow_ref` (the called workflow's ID), `payload_mapping` (how the parent's context maps to the child's initial context), `join_policy` (wait for child completion, return child's final context as the node's output)
- Runtime: `POST /api/workflows/{workflow_ref}/run` with the mapped payload, then join on the SSE event stream for the child run
- Cycle detection: at workflow save time, walk the sub-workflow graph and reject any cycle. The check is per-workflow and is cheap (a DFS from the saved workflow's sub-workflow nodes).
- The called workflow inherits the caller's credential session (no re-unlock required)

**4.6.3 — Per-node error policy (a property of every node kind, not a new kind):**
- `on_error: fail-fast` (default) — node failure aborts the workflow
- `on_error: retry-with-backoff` — node retries N times with exponential backoff (1s, 2s, 4s, 8s, 16s, capped at 60s)
- `on_error: continue-and-log` — node failure is logged, the workflow continues
- `on_error: branch-to-error-handler` — node failure routes to a sibling sub-workflow (the error handler is itself a separate workflow file)

**4.6.4 — Conditional execution (Archon `when:` pattern, additive to `decision`):**
- A `when:` property on every node kind: `when: "$node-id.output.field == 'value'"` evaluates before the node runs
- The expression is sandboxed (no shell, no arbitrary code) — a small expression language with `$`, `==`, `!=`, `&&`, `||`, `>`, `<`, string ops
- Operators can express "skip this node if the prior node returned X" without adding a `decision` branch

**4.6.5 — Three Archon patterns adopted as standard properties (from the spike report):**
- `trigger_rule: all_success | one_success | none_failed_min_one_success | all_done` on `join` nodes (parallel-join semantics)
- `context: fresh | continue` (default `fresh`) on every node (session isolation per step)
- `when:` conditional on every node (skip on prior output)

**Size:** L (7 new PaletteItem kinds, 1 new property on every kind, runtime support for each, UI for each in the editor)
**Owner:** Iris (mock-based design for the trigger icons + sub-workflow inspector) + Marvin (code) + Thoth (QA)
**Blocked by:** 4.5 (credentials), Milestone 1 (api_server.py + auth)
**Out of scope:** Cloud-event triggers (EventBridge / Pub/Sub) — these are post-pilot future work
**Pattern:** parallel_branches (7 trigger kinds can be implemented in parallel, sub-workflow + error policy + when: are sequential after)

### 4.7 — Connector Library (starting at 14, designed to grow)

**Goal:** A library of typed business operations ("Send Email via SendGrid", "Create Calendar Event in Google Calendar", "Update CRM Record in HubSpot", "Post to Slack Channel") that operators compose into workflows. **The library is operator-extensible** — new connectors are added without modifying the engine.

**Why third:** Consumes the credentials store (4.5) and uses the trigger vocabulary (4.6). Independent in the sense that 4.7 can start as soon as 4.5 ships, but the *most useful* connectors (email-trigger-driven workflows) need 4.6 too.

**Scope:**

**4.7.1 — The 14 starting connectors (from Iris's mock):**

**Important correction (2026-06-18, Konan sign-off on the 14-connector list):** The blueprint names "14-connector catalog" but **Iris's mock at `/home/konan/workspace/conductor-mock/index.html` (line 1598-1692, SCREEN 5 — SETTINGS / INTEGRATIONS) contains exactly 12 connector tiles, not 14.** The count discrepancy is real. The 12 are referenced, not redefined, here; the discrepancy is flagged for Konan to resolve (either accept 12 as the starting count, or specify which 2 additional connectors to add). The catalog design accommodates any starting count — the runtime reads YAML files from `connectors/` at startup.

**The 12 connectors, verbatim from the mock:**

| # | Connector | Mock state | Subtitle / endpoint | Notes |
|---|---|---|---|---|
| 1 | **NATS** | Active | Subspace messaging · relay-7:4222 | The runtime's own event bus. |
| 2 | **Slack** | Active | #theoforge · 3 channels | The primary team communication channel. |
| 3 | **GitHub** | Active | Duskript · 2 repos | Duskript is the consumer side; TheoForge is the producer side. |
| 4 | **Discord** | Not connected | (none) | Operator hasn't configured yet. |
| 5 | **Telegram** | Active | @theoforge · bot | The home channel. |
| 6 | **Mercer CRM** | Active | clawforge.theoforgesolutions.com | The sales CRM (Mercer is also a god — but here it's a connector, not the god role). |
| 7 | **Email (SMTP)** | Active | theoforgesolutions.com · 4 templates | The transactional email channel. |
| 8 | **Linear** | 401 unauthorized | 2m ago | Token is in the credentials store but the Linear account has revoked it. **Real failure mode captured in the mock.** |
| 9 | **Ichor (memory)** | Active | SQLite · 47,610 events | The memory substrate — Ichor-as-connector, not just a runtime. |
| 10 | **PostgreSQL** | Off | Not configured | Generic database connector. |
| 11 | **Webhook (generic)** | Off | Not configured | Outbound webhook (separate from Phase 4.6's `webhook-trigger` which is inbound). |
| 12 | **Anthropic API** | Off | Not configured | Direct Claude API access (separate from god-call, which is the higher-level interface). |

**The 14-vs-12 discrepancy, three possible explanations:**

1. **The blueprint's "14" is a count from an earlier version of the mock** — Iris may have removed 2 connectors in a revision. Need to check git history of the mock (if any) to confirm.
2. **The blueprint's "14" is operator memory, not design truth** — the actual design source of truth is the mock (12 connectors), and the blueprint was written from imprecise recollection. The mock wins.
3. **The blueprint's "14" includes 2 connectors that are not in the mock** — perhaps planned additions that were never rendered. Possible candidates: Google Calendar (for meeting booking, mentioned in the TheoForge lead-funnel context), SendGrid (for transactional email, possibly the underlying transport for the SMTP connector), or OpenAI API (mirror of Anthropic API).

**My recommendation:** treat the mock as the source of truth (12 connectors, not 14), and the discrepancy is *itself* a finding worth documenting. Phase 4.7 ships with the 12 from the mock. Additional connectors are added via the operator-extensible YAML format — drop a new file in `connectors/`, no code changes. **The "14" in the blueprint is corrected to "12 (from mock) + extensible."**

**4.7.2 — The connector definition format:**

```yaml
# Example: sendgrid-email connector
name: sendgrid-email
version: 1
type: integration
description: "Send transactional email via SendGrid"
credential_ref: sendgrid_api_key        # references credentials store
operations:
  - id: send
    label: "Send Email"
    schema: { to: string, from: string, subject: string, body_html: string, ... }
  - id: send_template
    label: "Send Template"
    schema: { to: string, template_id: string, dynamic_data: object, ... }
triggers: []                              # this is a sink, not a source
```

Each connector is a YAML file in `~/pantheon/conductor/connectors/{name}.yaml`. The engine reads the connector definitions at startup, validates the operations against the schema, and exposes them as node kinds in the editor's palette.

**4.7.3 — Operator extension:**
- Drop a new YAML file in `connectors/` → engine picks it up on next start, no code changes
- The schema validation is JSON Schema (the same library the SDK uses for the properties panel)
- The operator can author a new connector in 15 minutes if they know the API

**4.7.4 — The connector → node-kind binding:**
- Each connector operation becomes a node kind in the editor's palette
- The properties panel renders the JSON Schema for the operation
- The runtime resolves the `credential_ref` at execution time

**Size:** M (the runtime work to load + validate + execute connectors is M; the 14 starting connectors are mostly existing third-party API bindings the operator ports from documentation)
**Owner:** Iris (mock-based design for the connector picker) + Marvin (engine code) + Konan (the 14 starting connectors are operator-authored from the 14-connector catalog)
**Blocked by:** 4.5 (credentials), 4.6 (trigger vocabulary — connectors can be triggered by any of the 7 kinds)
**Pattern:** parallel_branches (the 14 connectors can be authored in parallel; the engine work is sequential)

### 4.4 — Live-Execution Dashboard (the "what's running" view)

**Goal:** A new sibling route at the AppShell level (`/runs`) that shows the operator a live list of currently-running and recently-completed workflows. Each row shows the workflow name, started-at, elapsed time, current node, node progress bar, and per-run live state. Click into a run to see the live SSE event stream for that workflow.

**Why this phase:** Konan sign-off (2026-06-18). The dashboard is the n8n-comparable "what's running" view that makes Conductor UI feel like a real workflow product, not a config editor. The dashboard reuses the SSE event relay work that 4.6 will need for the SDK mount — sharing the relay code is the dependency.

**Why between 4.3 and 4.5 (not later):** The dashboard chrome needs to match the rest of the shell (so 4.3 Lumen theme is the dependency), and the SSE relay work is shared with 4.6 (so 4.4 ships before 4.6 to define the relay's shape). It does not depend on credentials (4.5) because the dashboard reads run state, not credentials.

**Scope:**
- New route: `/runs` added to `src/router.tsx` (6th route in the AppShell, becomes `5-route shell → 6-route shell`)
- New component: `src/runs/dashboard.tsx` — the run list view, polling the existing `GET /api/plugins/kanban/events` WebSocket (or the new `GET /api/workflows/{id}/runs` SSE endpoint from Milestone 1)
- New component: `src/runs/detail.tsx` — single-run view with live SSE event stream, node progress bar, and per-node state
- New feature: a "View Runs" link in the editor's top bar (the existing `/editor/$id` view) that navigates to `/runs?workflow_id={id}` with the workflow context pre-loaded
- The dashboard works for **any** workflow that has a `workflow_id`, not just Conductor UI-authored ones — the kanban plugin's task runs (which are dispatched workflows) also show up
- Live updates: subscribe to `GET /api/workflows/{id}/runs/{run_id}/events` (the SSE endpoint from Milestone 1), update the dashboard in real time
- A "View Runs" link in the editor's top bar is the bridge from /editor → /runs

**Size:** M (new route, new components, SSE consumption, UI integration with the 5-route → 6-route shell)
**Owner:** Iris (mock-based design for the dashboard layout, the per-run card, the live event stream visualization) + Marvin (route, components, SSE consumption) + Thoth (QA gate)
**Blocked by:** 4.2 (UI integration — needs the existing 5-route shell + AppShell as a starting point), 4.3 (Lumen theme — dashboard chrome must match)
**Out of scope:** Historical analytics ("runs per day", "failure rate by workflow", "average node duration"). Those are post-pilot future work. The v1 dashboard is "what's running right now and what just finished."
**Pattern:** sequential

**Note on the n8n parity claim:** n8n has this dashboard as a first-class feature (the "Executions" view). Conductor UI's version differs in one specific way: the run state shown in the dashboard is the *runtime's* state, not the *agent's narrative about its state*. A node that "completed" in the dashboard is one the runtime confirmed as completed (e.g., the HTTP response was 200, the file was written and the write returned success, the god-call returned a typed result). **The dashboard is honest in a way n8n's is not, because the substrate is deterministic.** This is the product claim made visible.

### 4.6.6 — Test-Workflow execution mode (folded into 4.6)

**Goal:** A "Test Workflow" button in the editor's top bar (next to the existing "Run" button) that executes the workflow with sample data and **does not write to external systems**. The dry-run mode exercises the entire DAG structure (triggers, sub-workflow calls, error policies) but routes all external I/O through a dry-run adapter that records the intended action without committing it.

**Why in 4.6, not 4.5:** Test mode is meaningful only when there are triggers, sub-workflow nodes, error policies, and connector operations to test. 4.5 (credentials) doesn't add node kinds; 4.6 (n8n surface) does. Test mode is part of the n8n surface runtime work.

**Scope:**
- New API endpoint: `POST /api/workflows/{id}/test-run` (extends Milestone 1's `api_server.py`)
- New runtime mode: `dry_run: true` flag on workflow execution; when set, the runtime replaces the I/O layer with a recorder
- The dry-run recorder:
  - Captures every node's intended input and output
  - Replaces external HTTP calls with a recorded response (per-credential, per-operation, configurable)
  - Replaces file writes with no-ops (or writes to a temp directory)
  - Replaces NATS publishes with a recorded message log
  - Logs every step's decision (which branch was taken, which `when:` condition evaluated true/false, which error policy was applied)
- New UI: "Test Workflow" button in the editor's top bar (next to "Run"), with a results panel that shows the dry-run trace as a tree (same shape as the runtime's SSE event stream)
- The trace can be exported as JSON for offline debugging

**Size:** S-M (the runtime mode is a config flag + a recorder implementation; the UI is one button + one panel; the test infrastructure is the bulk of the work)
**Owner:** Marvin (runtime mode + recorder) + Iris (mock for the results panel) + Thoth (QA gate — test the dry-run trace against the runtime's actual event stream for parity)
**Blocked by:** 4.6.1-4.6.5 (the trigger vocabulary, sub-workflow, error policy, and `when:` are the things being tested)
**Out of scope:** Replay-mode (re-execute a recorded run for real). That's a future decision.
**Pattern:** sequential, after 4.6.5

**Note on the operator experience:** The test mode is the n8n "Test workflow" button. Conductor UI's version differs in two ways: (1) the dry-run trace is the *runtime's* trace, not a synthetic one — the runtime actually walks the DAG and exercises every step; (2) the trace is exportable, so an operator can attach a trace to a kanban task or a Telegram message for async debugging. Both are substrate wins.

## 5. The phase ordering and dependency graph

```
4.0 (api_server.py + auth)        ──── DONE in current Phase 4
4.1 (node vocabulary + translator) ──── DONE in current Phase 4
4.2 (UI integration)              ──── DONE in current Phase 4
4.3 (Lumen theme)                 ──── DONE in current Phase 4
              │
              ▼
4.4 (Live-Execution Dashboard)     ──── NEW, Konan sign-off 2026-06-18
              │
              ▼
4.5 (Credentials Store)            ──── NEW, foundational
              │
              ├──────────────────┐
              ▼                  ▼
4.6 (n8n Surface)              4.7 (Connector Library)
              │                  │
              └────────┬─────────┘
                       ▼
              5.0 (Ledger data seam — unchanged)
                       ▼
              5.1 (Ledger UI seam — post-Phase 5, future)
```

**Sequencing rules:**
- 4.5 ships before 4.6 and 4.7 (it's the dependency)
- 4.6 and 4.7 can run in parallel after 4.5 (different code paths, different owners)
- The kill criterion is at 4.5: if the OS keyring integration or Argon2 key derivation is unworkable on the target platform (e.g., libsecret unavailable), stop and reassess

**Total new effort:** L (Phase 4.5) + L (Phase 4.6) + M (Phase 4.7) = 3L, conservatively. No time estimates per the operator-locked rule.

## 6. The phase budget table (updated)

| Phase | Owner | Pattern | Size | Blocked by |
|---|---|---|---|---|
| 4.0 | Marvin + Hephaestus | sequential | M-L | (already done) |
| 4.1 | Iris + Marvin | parallel_branches | M | 4.0 |
| 4.2 | Iris + Marvin | sequential | S | 4.0, 4.1 |
| 4.3 | Iris + Marvin | sequential | M (or S to skip) | 4.2 |
| **4.4 (NEW)** | **Iris + Marvin + Thoth** | **sequential** | **M** | **4.2 (AppShell extension; adds a 6th route)** |
| **4.5 (NEW)** | **Marvin + Hephaestus + Thoth** | **sequential** | **L** | **4.0** |
| **4.6 (NEW)** | **Iris + Marvin + Thoth** | **parallel_branches** | **L** | **4.5, 4.0** |
| **4.7 (NEW)** | **Iris + Marvin + Konan** | **parallel_branches** | **M** | **4.5, 4.0** |
| 5.0 | Marvin + Hephaestus | sequential | S-M | 4.5 (for the data-seam swap) |
| 5.1 | TBD | TBD | TBD | post-5.0 |

**Note on phase 4.4 insertion:** Phase 4.4 (live-execution dashboard) is a sibling route at the AppShell level, not a sub-thing in `/editor/$id`. The current 5-route shell (Dashboard / Editor / Board / Forge / Settings) becomes a 6-route shell with "Runs" added. Phase 4.4 is sequenced after 4.3 (Lumen theme) so the dashboard chrome matches the rest of the shell, and before 4.5 (credentials) because the dashboard's "live execution" view consumes the same SSE event stream that 4.6 will rely on for the SDK mount — sharing the SSE relay code is the dependency.

**Note on phase 4.6.6 insertion:** The test-workflow button is a runtime feature (a `dry_run` mode that doesn't write to external systems), not a new PaletteItem kind. It folds into 4.6 because 4.6 is where the n8n surface runtime work lives. It's sequenced after 4.6.1-4.6.5 because the dry-run mode is meaningful only when there are triggers, sub-workflow nodes, and error policies to test.

**Note on n8n import/export:** Per Konan sign-off (2026-06-18), a **separate 1-day feasibility spike** is filed at `~/athenaeum/Codex-God-thoth/research/n8n-import-export-feasibility-spike-outline-2026-06-18.md`. The spike is research-only, returns a 1-2 page feasibility report. **No code is written until the spike is signed off.** The report answers: (a) can we export Conductor UI workflows to n8n's JSON format losslessly, (b) what n8n node types map to which Conductor v2 PaletteItem kinds (a mapping table), (c) can we import n8n workflows into Conductor UI (the harder problem, because n8n has 400+ node types and most have no Conductor v2 equivalent). The spike is independent of all phases — it can run any time.

## 7. The new risks

| # | Risk | Mitigation | Owner |
|---|---|---|---|
| 1 | **OS keyring integration** (libsecret on Linux, Keychain on macOS) is platform-specific and may not work in headless / containerized deployments. | Provide a fallback: passphrase cached to a file with `chmod 600` permissions, env var override, or disable keyring entirely with explicit re-auth on every restart. | Marvin |
| 2 | **Sub-workflow cycle detection** is per-workflow; the cross-workflow cycle check is the operator's responsibility. A workflow that calls itself transitively will hang the runtime. | At save time, walk the sub-workflow graph and reject any cycle *within the saved workflow*. At runtime, detect cycles via the run graph (a run can have a `parent_run_id`; reject if the parent is in the call chain). | Marvin |
| 3 | **Per-node error policy + sub-workflow composition** may produce unbounded retry loops if the retry policy is `retry-with-backoff` and the failure is permanent. | Cap the total retry budget per workflow (default 10 minutes wall-clock). After the budget is exhausted, the workflow is marked failed and an operator notification is sent. | Marvin + Iris |
| 4 | **Custom triggers** as a user-defined surface create an unbounded attack surface (the operator can run arbitrary TypeScript). | Sandboxed execution: custom triggers run in a separate Node.js process with restricted `child_process` and `fs` access. The execution context is passed in via a typed interface, not raw globals. | Marvin |
| **6** | **Live-execution dashboard (4.4)** ships with no historical analytics — only "what's running right now and what just finished." Operators may want "runs per day," "failure rate by workflow," "average node duration." | v1 dashboard is a polling + SSE view, not a metrics store. If metrics are wanted, that's a separate sub-phase post-pilot. | Iris + Marvin |
| **7** | **Test-workflow mode (4.6.6)** records but does not execute external I/O. A test that *should* have written a file may look like success when the integration is broken. | The dry-run recorder validates the *type* of the response (e.g., "the HTTP response was 200" is recorded as success, but the response body is shown for operator inspection). The operator reviews the trace, not just the success/fail indicator. | Marvin + Thoth |
| 5 | **The 14-connector catalog** is operator-locked in Iris's mock, but the connector *implementations* are not designed yet. Shipping the runtime (4.7.2 + 4.7.3 + 4.7.4) without 14 working connectors creates a "no integrations in the palette" first-impression failure mode. | Ship the runtime with at least 3 working connectors (e.g., sendgrid-email, slack-post, http-request) as proof. The other 11 are authored in 4.7.1 in parallel with the engine work. | Iris + Konan + Marvin |
| **8** | **Substrate lock-in (v1.4 NEW).** The Conductor UI workflow vocabulary, node attributes, and credential types are v1-specific to the Hermes runtime. If we ship v1 without declaring portable JSON Schemas, Pantheon 2.0 has to rewrite the node vocabulary, breaking every existing workflow. | **v1.4 mitigation:** declare all node kinds, attributes, and credential types as JSON Schemas in a sibling `schemas/` directory. v1 enforces Hermes-only; v2 ships the harness-adapter layer. See Operator framework §13 for the full spec. **The schemas are additive documentation, not breaking changes.** | Hephaestus + Thoth |
| **9** | **No harness-adapter layer (v1.4 NEW).** The 4.6 trigger vocabulary and the operator's role.json both declare `harness` but v1 only supports Hermes. If we don't ship the v2 harness-adapter layer, the schema promise is unfulfilled and the field becomes documentation debt. | **v1 mitigation:** the `harness` field is declared in the schema but constrained to `"hermes"` in v1. The v2 build is a separate 12-month project. **Defer the harness-adapter layer to v2; do not half-build it in v1.** | Hephaestus (v2 owner) |

## 8. The 5 NEW decisions to make (extends blueprint §8)

### 8.1 — Adopt Phase 4.5 / 4.6 / 4.7 as the n8n expansion (vs. defer or scope-down)

**Recommendation: YES.** Konan called for it (2026-06-17). The substrate is preserved. The build plan changes are bounded (3 new phases, no changes to 4.0-4.3 or Phase 5).

**Alternatives:**
- **(a) Adopt as proposed** — 3 new phases, ~3L effort *(my recommendation)*
- **(b) Scope down to just credentials + webhook/cron/manual triggers** — drops sub-workflow + custom triggers + connector library, ~2L effort
- **(c) Defer the n8n expansion post-Phase 5** — ship 4.0-4.3 first, validate the pilot, then add the n8n surface

### 8.2 — Credentials store: encrypted SQLite with passphrase + OS keyring (vs. alternatives)

**Recommendation: YES.** Per Konan (2026-06-17). Encrypted SQLite (better-sqlite3-multiple-ciphers or @journeyapps/sqlcipher) with Argon2id key derivation from operator passphrase, OS keyring caching for the session, re-auth for write operations. The fallback is a file with `chmod 600` permissions for headless deployments.

**Alternatives:**
- **(a) Encrypted SQLite + passphrase + OS keyring** — single-operator friendly, no infrastructure *(my recommendation)*
- **(b) HashiCorp Vault** — proper secrets management, but infra dependency
- **(c) OS keyring only (no DB encryption)** — simpler, but the on-disk credential is plaintext-encrypted with the OS keyring secret, which is platform-specific

### 8.3 — Connector library starts at 14, designed to grow (vs. closed library or empty library)

**Recommendation: YES.** Per Konan (2026-06-17). The 14 from Iris's mock are the starting point. The library is operator-extensible via the YAML format — drop a new file in `connectors/` and the engine picks it up.

**Alternatives:**
- **(a) 14 starting, operator-extensible** — matches Konan's direction *(my recommendation)*
- **(b) Empty library, operator-extensible** — engine ships with 0 connectors; operator authors the first ones
- **(c) Closed library** — 14 fixed connectors, no extension (anti-pattern, rejected)

### 8.4 — Custom triggers as user-defined TypeScript (vs. UI-only or code-only)

**Recommendation: TYPESCRIPT.** Custom triggers are a "developer-oriented" surface. The operator writes a small TypeScript file implementing the trigger interface, the runtime loads it, the editor shows it in the palette. This is the right shape for "every trigger we can get" — the trigger vocabulary is open.

**Alternatives:**
- **(a) TypeScript file implementing a typed interface** — developer-friendly, full expressivity *(my recommendation)*
- **(b) UI-only (operator configures a polling condition via the editor)** — more accessible, less expressive
- **(c) Both** — the engine supports both shapes; the operator picks

### 8.5 — Per-node error policy: 4 options, `fail-fast` is the default (vs. 2 options or different defaults)

**Recommendation: 4 OPTIONS, `fail-fast` default.** `fail-fast` is the safe default — failures abort the workflow, the operator investigates. The other 3 are opt-in for workflows that need them. The 4 options are: `fail-fast`, `retry-with-backoff`, `continue-and-log`, `branch-to-error-handler`.

**Alternatives:**
- **(a) 4 options, fail-fast default** — safe default, opt-in flexibility *(my recommendation)*
- **(b) 2 options (fail-fast, retry) only** — simpler, drops `continue-and-log` and `branch-to-error-handler`
- **(c) Different default (e.g., `continue-and-log`)** — anti-pattern, rejected (silent failures are the deterministic-substrate's failure mode)

## 9. The 3 NEW success criteria (extends blueprint §10)

**The pilot is done when:**

1. ✅ (existing) ... 10 success criteria
2. **An operator can create a credential in the credentials store via the editor, reference it in a workflow node, and the runtime resolves it at execution time. The agent never sees the raw value.**
3. **An operator can author a workflow that uses a webhook trigger, a god-call step, a connector-library step, and a sub-workflow call — and the workflow runs deterministically with per-node error policies in effect.**
4. **The connector library ships with at least 3 working connectors (e.g., sendgrid-email, slack-post, http-request) and the YAML format is documented for operator extension.**

## 10. The sign-off criteria (for Konan)

**Sign-off (2026-06-18 09:30Z, Konan):** All 5 NEW decisions in §8 accepted as proposed. The §12 open questions and §7 risks acknowledged. The 3 placements (4.4 dashboard, 4.6.6 test-workflow, n8n spike outline) accepted. The §12.1 open question resolved by reading the mock — **the mock has 12 connectors, not 14; the discrepancy is real and is documented in §4.7.1**. **The addendum is now operator-locked v1.3** pending Hephaestus writing the v1.2 → v1.3 build plan deltas per the 14-item handoff checklist in §11.

**v1.4 patch (2026-06-18, same session):** substrate-agnostic + harness-agnostic spec commitment per Konan "we can wrap anything." §1 deltas add row 14 (substrate-agnostic spec commitment), §4.6 adds 4.6.0 (substrate-agnostic node attribute — `harness` field declared, v1 ships Hermes-only, v2 ships the harness-adapter layer per Operator framework §13), §7 adds risks #8 (substrate lock-in) and #9 (no harness-adapter layer in v1). Cross-references the Operator framework v1.2 and the Omnigent absorption v1.1.

## Sign-off criteria

- [x] You have read §1-§9 and agree with the deltas
- [x] You have signed off on the 5 NEW decisions in §8
- [x] You have confirmed the phase ordering in §5 (4.5 → 4.6 + 4.7 → 5.0)
- [x] You have answered the 5 NEW open questions in §12 (all 5 deferred to build plan; the 14-connector list resolved by reading the mock)
- [x] You have acknowledged the 5 new risks in §7
- [x] You have accepted the 3 placements (4.4, 4.6.6, n8n spike outline)

**Operator-locked v1.3, 2026-06-18 09:30Z.**

## 11. The handoff checklist (for Hephaestus)

When this addendum is operator-locked, write the v1.2 → v1.3 build plan deltas. The deltas must include:

1. The 3 new phases (4.5, 4.6, 4.7) with: owner, pattern, size, blocked-by, deliverables, QA review task
2. The phase ordering and dependency graph from §5
3. The credentials store design from §4.5 (the only real new architecture)
4. The connector library design from §4.7 (the operator-extensible surface)
5. The trigger vocabulary and sub-workflow + error policy from §4.6
6. The 3 new success criteria from §9
7. The 5 new risks from §7
8. The kill criterion at 4.5: if OS keyring integration or Argon2 key derivation is unworkable on the target platform, stop and reassess
9. The "no Phase 0/1/2/3/4.0-4.3 modifications" guard — the n8n expansion adds new work, doesn't modify existing
10. The "no new kanban infrastructure" rule — Phase 4.5/4.6/4.7 do not add kanban surfaces
11. The "no new SDK dependencies" rule — the n8n surface is workflow vocabulary, not canvas
12. The QA gate: every sub-phase ships with a Thoth review follow-on (operator-locked 2026-06-16)
13. The no-absolute-time-estimates rule (operator-locked 2026-06-16)
14. The "extensibility-first" rule for the connector library — drop a new YAML file, no code changes

**What the v1.3 build plan must NOT do:**
- Modify Iris's mock (the design source of truth, read-only)
- Re-design the 5-route shell, AppShell, Lumen scale, or per-god glow (Marvin-built scaffolding, not Iris-owned)
- Re-design the Workforge interview (Thoth-authored, Konan-signed)
- Re-design the 14-connector catalog or the right-rail inspector pattern (Iris's mock)
- Introduce new dependencies outside `@workflowbuilder/sdk@2.1.0` + the standard sqlite/argon2/keyring libs
- Ship a custom editor alongside the SDK

## 12. The 5 NEW open questions (extends blueprint §11)

1. **The 14 connectors — what are they exactly?** The blueprint names "14-connector catalog" as Iris's design contribution, but the specific 14 are not enumerated in the shared/active blueprint. We need the full list before Phase 4.7 can start. **Konan to confirm or reference Iris's mock.**
2. **Custom trigger execution sandbox** — Node.js `vm` module? `isolated-vm`? A separate process with restricted `child_process`? The choice has security implications (see risk #4).
3. **Sub-workflow call semantics** — does the called workflow inherit the caller's session key (no re-unlock), or does it require a separate unlock? My proposal: inherit, but the operator can override per-workflow via a "requires_unlock: true" flag.
4. **Error policy `branch-to-error-handler` — where does the error handler live?** My proposal: a sibling sub-workflow (the error handler is itself a separate workflow file). Alternative: a sibling node in the same workflow. The choice affects the DAG semantics and the editor UX.
5. **Credentials store location** — same directory as Conductor v2's main DB, or separate `~/pantheon/conductor/credentials/`? The seam pattern suggests separate, but the operator may prefer co-located for backup simplicity.

## 13. Sources

- `~/pantheon/shared/active/conductor-ui-phase-4-blueprint.md` — the operator-locked Phase 4 design
- `~/athenaeum/Codex-God-thoth/research/conductor-ui-deterministic-workflow-positioning-2026-06-18.md` — the product claim and 11 n8n-shaped features
- `~/athenaeum/Codex-God-thoth/research/archon-21-workflows-classification-2026-06-18.md` — the 20-workflow classification and 3 patterns to borrow
- `~/.hermes/skills/pantheon/ichor-harness-engineering/SKILL.md` — the Ichor gates and RALPH pattern
- `~/wiki/concepts/ichor-harness-ralph-loop.md` — the wiki article
- `~/wiki/concepts/pantheon-loop-architecture-2026-06.md` — the 4-loop framework
- `~/athenaeum/Codex-God-hephaestus/forge-input-signal-survey-2026-06-17.md` — the Ichor Forge state
- `~/athenaeum/Codex-God-thoth/research/ichor-forge-improvement-report-2026-06-17.md` — the live Forge analysis
- Operator direction (2026-06-17 15:55Z Telegram + 2026-06-18 ~08:30Z): n8n replacement, 21 Archon workflows, sub-workflows, credentials, every trigger, custom triggers, deterministic
- User decisions (2026-06-18 ~08:35Z): 14-connector starting point with growth, encrypted SQLite, phase numbering OK

## 14. Date convention note

This addendum is dated 2026-06-18. Earlier artifacts in the same research thread (`conductor-ui-deterministic-workflow-positioning-2026-06-18.md` and `archon-21-workflows-classification-2026-06-18.md`) are also dated 2026-06-18. **Per Konan (2026-06-18 ~08:35Z): leave the earlier artifacts at their original dates (2026-06-17) for internal consistency; only new artifacts are dated 2026-06-18.** This note is included for future readers who may notice the date drift.
