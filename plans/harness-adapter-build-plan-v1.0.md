# Harness-Adapter Layer — Build Plan v1.0

> **Status:** OPERATOR-LOCKED — Konan sign-off 2026-06-19
> **Date:** 2026-06-19
> **Author:** Hephaestus (from Thoth's Omnigent absorption doc §10)
> **Project root:** `/home/konan/projects/harness-adapter/`
> **Governing spec:** `~/athenaeum/Codex-God-thoth/research/omnigent-absorption-2026-06-18.md` §10
> **Architecture:** `~/athenaeum/Codex-God-thoth/research/role-based-agent-architecture-pantheon-2026-06-18.md` §13
> **v1 seam:** `harness` attribute on all 14 Conductor UI workflow nodes (shipped 2026-06-19, `harness: 'hermes'`)

---

## 0. Provenance

| Source | What it told us |
|---|---|
| **Omnigent absorption doc §10 (2026-06-18)** | 5-step v2 harness-adapter build. Interface → Hermes adapter → Claude Code → Codex → Omnigent. Total: 5 adapters, Python project. |
| **Operator framework §13 (2026-06-18)** | Substrate-agnostic spec commitment. v1 declares `harness` field; v2 enforces the implementation. JSON Schemas for all formats. |
| **Conductor UI v1.4 addendum §4.6.0** | `harness` attribute on every workflow node. v1: only `"hermes"` legal. v2: adapter interface enables Claude Code / Codex / Omnigent runtimes. |
| **Konan directive (2026-06-18)** | "We can wrap anything." The wrap-external-harnesses mechanism is the v2 plan. Omnigent's runner pattern is the reference. |
| **Konan directive (2026-06-19)** | "Do this as a proper kanban project that does our normal code validation loop." |

---

## 1. Tier routing summary

**Pattern:** Pipeline — 5 sequential phases with parent-child gating. Phase 1 is the contract; Phases 2-5 implement against it.

**Specialists:** Marvin (build), Hephaestus (Tier-1 verify, architecture), Ponytail (Tier-2 QA)

**Workflow tools:** kanban_task (dispatch + track), conductor_yaml (build definition), cli_tool (test runner)

**Estimated complexity:** High. 5 adapters across 4 external harness SDKs. Interface design is the critical path — Phase 1 must be right before anything else ships.

**Catalog search terms:** adapter, harness, interface, python-sdk, multi-runtime, abstract-base-class

---

## 2. Catalog matches

| Workflow | Similarity | Relevance |
|---|---|---|
| conductor-ui v1.3 build | 0.82 | Same QA pipeline (Marvin → T1 → Ponytail), same project conventions |
| LedgerAdapter pattern (Phase 5) | 0.75 | Interface-first Python design with stub + real implementation swap |
| Ichor forge harness | 0.68 | Self-adjusting harness analysis — adjacent concept |

**Best UI/editor pattern:** Conductor UI v1.3 build (same pipeline, same specialists, same QA gates).

**Soulforge pattern match:** None — this is a pure Python SDK project, not a UI build.

---

## 3. Architecture

### 3.1 Project structure

```
~/projects/harness-adapter/
├── interface/              # Phase 1 — the contract
│   ├── __init__.py
│   ├── schema.json         # JSON Schema for the harness-adapter interface
│   ├── types.py            # TypedDict / dataclass types
│   ├── base.py             # ABC: HarnessAdapter (abstract base class)
│   ├── session.py          # SessionLifecycle mixin
│   ├── messaging.py        # MessageStream mixin
│   ├── tools.py            # ToolCallProtocol mixin
│   ├── persona.py          # PersonaLoad mixin
│   ├── calibration.py      # CalibrationWriteBack mixin
│   ├── eval.py             # EvalRun mixin
│   ├── error_policy.py     # ErrorPolicy mixin
│   ├── cost.py             # CostTracking mixin
│   ├── security.py         # SecurityPolicies mixin
│   └── conformance.py      # Conformance test suite (pytest)
├── adapters/
│   ├── hermes/             # Phase 2 — refactor current runtime
│   │   ├── __init__.py
│   │   ├── adapter.py      # HermesAdapter(HarnessAdapter)
│   │   └── __tests__/
│   ├── claude_code/        # Phase 3 — wrap Anthropic SDK
│   │   ├── __init__.py
│   │   ├── adapter.py      # ClaudeCodeAdapter(HarnessAdapter)
│   │   └── __tests__/
│   ├── codex/              # Phase 4 — wrap Codex CLI
│   │   ├── __init__.py
│   │   ├── adapter.py      # CodexAdapter(HarnessAdapter)
│   │   └── __tests__/
│   └── omnigent/           # Phase 5 — wrap Omnigent server
│       ├── __init__.py
│       ├── adapter.py      # OmnigentAdapter(HarnessAdapter)
│       └── __tests__/
├── __tests__/              # Cross-adapter conformance
│   ├── test_conformance.py
│   └── fixtures/
├── pyproject.toml
└── README.md
```

### 3.2 The interface contract

Per the absorption doc §10.3, the harness-adapter interface covers 9 concerns:

| Concern | Method signature | Phase |
|---|---|---|
| Session lifecycle | `start_session(role_id) → Session`, `end_session(session_id)`, `get_session_state(session_id) → SessionState` | 1 |
| Message stream | `send_message(session_id, message)`, `subscribe_events(session_id) → AsyncIterator[Event]` | 1 |
| Tool call protocol | `list_tools() → list[Tool]`, `invoke_tool(name, args) → ToolResult`, `tool_result_stream(tool_call_id) → AsyncIterator[ToolEvent]` | 1 |
| Persona load | `load_persona(session_id, persona_slice)`, `unload_persona(session_id)` | 1 |
| Calibration write-back | `record_correction(session_id, correction_event)`, `get_calibration_trail(role_id) → list[Correction]` | 1 |
| Eval run | `run_eval(role_id, eval_suite) → EvalResult` | 1 |
| Error policy | `on_node_error(node_id, error, policy) → ErrorAction` | 1 |
| Cost tracking | `get_session_cost(session_id) → CostSummary`, `set_cost_policy(session_id, policy)` | 1 |
| Security policies | `set_contextual_policy(session_id, policy)`, `enforce(session_id, action) → Allow \| Deny \| RequireApproval` | 1 |

### 3.3 Integration point with Pantheon

The Conductor UI workflow engine reads `node.harness` (currently `"hermes"`, the only legal value). The harness-adapter layer provides the runtime that executes the node on the declared substrate. v1 nodes route to HermesAdapter. v2 nodes route to ClaudeCodeAdapter / CodexAdapter / OmnigentAdapter based on the `harness` field value.

### 3.4 Language and dependencies

- **Language:** Python 3.11+
- **Type checking:** mypy (strict mode)
- **Testing:** pytest + pytest-asyncio
- **Schema validation:** jsonschema (validate adapter configs)
- **External SDKs:** anthropic (Claude Code), openai (Codex), omnigent-client (Omnigent — to be identified during Phase 5)

---

## 4. Phases

### Phase 1: Harness-Adapter Interface + Conformance Suite

**Size:** L
**Specialist:** Marvin
**Workspace:** `dir:/home/konan/projects/harness-adapter`

**Deliverables:**
- `interface/schema.json` — JSON Schema for all 9 concerns
- `interface/types.py` — TypedDict/dataclass types for every method signature
- `interface/base.py` — `HarnessAdapter` ABC with abstract methods for all 9 concerns
- `interface/session.py` through `interface/security.py` — 9 mixin files
- `interface/conformance.py` — pytest conformance suite that validates any adapter produces identical events to the reference
- `pyproject.toml` — project config, dependencies, mypy strict
- `README.md` — project overview

**Acceptance criteria:**
- mypy strict passes on all interface files
- Schema validates against itself (meta-schema)
- Conformance suite has 15+ test cases covering all 9 concerns
- Every ABC abstract method has a docstring with the contract

**Parent:** none (root phase)

---

### Phase 2: Hermes Adapter

**Size:** M
**Specialist:** Marvin
**Workspace:** `dir:/home/konan/projects/harness-adapter`

**Deliverables:**
- `adapters/hermes/adapter.py` — `HermesAdapter(HarnessAdapter)`, refactors current Pantheon runtime to implement the Phase 1 interface
- `adapters/hermes/__tests__/` — adapter-specific tests

**Acceptance criteria:**
- Passes the Phase 1 conformance suite
- Runs a real god profile (e.g., Thoth) end-to-end and produces correct events
- mypy strict passes

**Parent:** Phase 1

---

### Phase 3: Claude Code Adapter

**Size:** M
**Specialist:** Marvin
**Workspace:** `dir:/home/konan/projects/harness-adapter`

**Deliverables:**
- `adapters/claude_code/adapter.py` — `ClaudeCodeAdapter(HarnessAdapter)`, wraps the Anthropic SDK
- `adapters/claude_code/__tests__/` — adapter-specific tests

**Acceptance criteria:**
- Passes the Phase 1 conformance suite
- Wraps a Claude Code session and translates events to the interface contract
- mypy strict passes

**Parent:** Phase 2

---

### Phase 4: Codex Adapter

**Size:** M
**Specialist:** Marvin
**Workspace:** `dir:/home/konan/projects/harness-adapter`

**Deliverables:**
- `adapters/codex/adapter.py` — `CodexAdapter(HarnessAdapter)`, wraps the Codex CLI (JSON-RPC over stdio)
- `adapters/codex/__tests__/` — adapter-specific tests

**Acceptance criteria:**
- Passes the Phase 1 conformance suite
- Wraps a Codex session and translates JSON-RPC events to the interface contract
- mypy strict passes

**Parent:** Phase 3

---

### Phase 5: Omnigent Adapter

**Size:** M
**Specialist:** Marvin
**Workspace:** `dir:/home/konan/projects/harness-adapter`

**Deliverables:**
- `adapters/omnigent/adapter.py` — `OmnigentAdapter(HarnessAdapter)`, wraps the Omnigent server REST API
- `adapters/omnigent/__tests__/` — adapter-specific tests

**Acceptance criteria:**
- Passes the Phase 1 conformance suite
- Wraps an Omnigent server session and translates REST API responses to the interface contract
- mypy strict passes

**Parent:** Phase 4

---

## 5. QA Pipeline (per phase)

Every code-producing phase follows the operator-locked QA gate:

| Gate | Assignee | What |
|---|---|---|
| Tier-1 Verify | Hephaestus | mypy strict, conformance suite pass, code compiles, meets spec |
| Tier-2 Ponytail QA | Hephaestus (via `gpt55-ponytail-qa` skill) | Isolated GPT-5.5 review. ACCEPT / RETURN / ESCALATE |

Thoth is escalation only (per `2026-06-17-qa-gate-replaces-thoth-routine.md`).

---

## 6. Dependencies

```
Phase 1 (Interface)
    ↓
Phase 2 (Hermes Adapter)
    ↓
Phase 3 (Claude Code Adapter)
    ↓
Phase 4 (Codex Adapter)
    ↓
Phase 5 (Omnigent Adapter)
```

Sequential because each adapter builds on the Phase 1 contract. Phases 3-5 are independent of each other but gated sequentially for review throughput.

---

## 7. Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Phase 1 interface design is wrong | Conformance suite validates against real Hermes sessions. Any Phase 2+ adapter that fails conformance reveals interface gaps. Iterate on Phase 1 before proceeding. |
| 2 | Claude Code / Codex SDKs change during build | Pin SDK versions. Interface abstracts the SDK — changes only affect the adapter, not the contract. |
| 3 | Omnigent server API is undocumented or unstable | Phase 5 is last. By the time we reach it, Omnigent's API surface should be stable (Apache 2.0, 3.8k stars, Databricks-backed). |
| 4 | Beelink OOM on parallel Marvin workers | Phases are sequential (parent-gated). Only one adapter builds at a time. 12GB swap should handle Python projects. |
| 5 | External harness SDKs require paid access (Claude Code, Codex) | Phase 2 (Hermes) is free. Phases 3-4 use existing credentials from `~/.hermes/auth.json`. Phase 5 Omnigent is Apache 2.0. |
| 6 | Interface is over-designed for v1 needs | The interface covers 9 concerns but v1 only routes to Hermes. The conformance suite keeps the design honest — every method gets exercised. |
| 7 | No real Omnigent instance to test against in Phase 5 | Omnigent is Apache 2.0 — can run locally or against a hosted instance. Phase 5 scope includes identifying the client SDK. |

---

## 8. Build path

```
~/projects/harness-adapter/
```

Per the Build-Path Convention. Plans at `~/pantheon/plans/`. Build output at `~/projects/<name>/`.

---

## 9. Handoff chain

```
Hephaestus → Kanban dispatch (5 phase tasks + 10 QA tasks)
           → Marvin (build each phase)
           → Hephaestus (Tier-1 verify each phase)
           → Ponytail (Tier-2 QA each phase)
           → Konan (phase-complete report at each boundary)
```

---

## 10. Sign-off

- [x] Build plan reviewed and approved
- [x] Phase 1-5 scope confirmed
- [x] QA pipeline (Marvin → T1 → Ponytail) confirmed
- [x] Project root `~/projects/harness-adapter/` confirmed
- [x] Sequential gating (Phase N+1 blocked on Phase N) confirmed

**Date:** 2026-06-19
**Operator:** Konan

---

## 11. Deferred

- Harness routing (`harness_options.fallback_order`) — v2.1, needs the adapter registry first
- Cross-harness comparison (eval suite against all adapters) — v2.2, needs all adapters built
- v1.4 addendum §4.5.x (contextual security policies) — separate build, not part of this project
- v1.4 addendum §4.4.x (per-session cost policies) — separate build, not part of this project

---

## 12. Decisions log

| Date | Decision | Locked by |
|---|---|---|
| 2026-06-19 | Scope: 5-phase harness-adapter build per Omnigent absorption doc §10.2 | Konan |
| 2026-06-19 | Pipeline: Marvin → Tier-1 → Ponytail per normal code validation loop | Konan |
| 2026-06-18 | v2 is the wrap-external-harnesses mechanism; v1 declares the spec | Konan |
