# 2026-06-18 — Harness-Adapter Phase 1: Interface + Conformance Suite SHIPPED

**Decision:** SHIP Phase 1 of the harness-adapter build plan. The substrate-agnostic contract (`HarnessAdapter` ABC + 9 mixin Protocols + JSON Schema + conformance suite) is on disk at `~/projects/harness-adapter/`, committed as `21fa3c7`. mypy --strict passes, 25/25 conformance tests pass, schema meta-validates. Phase 2 (HermesAdapter) is unblocked.

**Rationale:**

The Phase 1 deliverables per build plan §4 are 7 items. All 7 shipped in a single commit:

1. `interface/schema.json` — JSON Schema (Draft 2020-12) for `AdapterConfig`. Schema describes the v1.4 seam's `harness` attribute shape: name, version, harness_kind, capabilities (subset of 9 concerns), policy_defaults (cost / security / error_policy). Meta-validates against the 2020-12 meta-schema.
2. `interface/types.py` — TypedDict/dataclass/Enum types for every method signature across the 9 concerns. NewType wrappers on `SessionId`, `RoleId`, etc. prevent silent mixing of distinct id kinds.
3. `interface/base.py` — `HarnessAdapter` ABC, inherits from all 9 mixin Protocols, `@abstractmethod` enforces "implement all 9" at class definition.
4. 9 mixin Protocol files (session, messaging, tools, persona, calibration, eval, error_policy, cost, security). Each is `@runtime_checkable` so adapter discovery is possible at runtime.
5. `interface/conformance.py` — 25 pytest cases + `ReferenceAdapter` fixture. ReferenceAdapter implements every mixin in-memory; no external services needed for the contract to be exercised.
6. `pyproject.toml` — mypy --strict + pytest-asyncio (mode=auto) config.
7. `README.md` — overview, layout, install, stability rules.

**Acceptance criteria from build plan §4 Phase 1:**
- [x] mypy strict passes on all interface files (13 source files, 0 issues)
- [x] Schema validates against itself (Draft202012Validator.check_schema passes)
- [x] Conformance suite has 15+ test cases covering all 9 concerns (25 cases; 2-3 per concern)
- [x] Every ABC abstract method has a docstring with the contract

**Non-obvious design decisions worth recording:**

1. **Protocols + ABC, not pure ABC.** The 9 mixins are split into separate Protocol files so an adapter author reads only the relevant concern's contract at a time. The ABC combines them with `@abstractmethod` for runtime enforcement. This is the Pythonic version of "split interfaces" (Go-style) without sacrificing the ABC's instantiation-time check.

2. **`runtime_checkable` on Protocols.** Each mixin Protocol is decorated with `@runtime_checkable`. This lets the Conductor UI registry do `isinstance(adapter, SessionLifecycleProtocol)` checks for partial adapters (v1.4 may declare a capability subset rather than the full 9).

3. **`NewType` on all ids.** `SessionId`, `RoleId`, `NodeId`, `PersonaSliceId`, `ToolName`, `ToolCallId`, `EvalSuiteId`. Prevents the common bug of passing a role_id where a session_id is expected — mypy catches it at the call site.

4. **ReferenceAdapter is in the conformance file, not a separate test fixture module.** The conformance suite is self-contained: `pytest interface/conformance.py -v` works with no `conftest.py`, no fixtures directory. Future adapters (Phase 2-5) just need to subclass `HarnessAdapter` and pass the same suite.

5. **Cost tracking charges via `send_message` + `invoke_tool`** (not its own method). The cost mixin has `get_session_cost` (read) and `set_cost_policy` (write); the actual cost accumulation happens implicitly inside the message/tool entry points. Conformance test `test_set_cost_policy_then_get_session_cost_reflects_traffic` validates the read path; the write path is the policy itself (validated separately by `test_set_cost_policy_*` style tests if added later).

6. **Schema describes `AdapterConfig`, not `HarnessAdapter`.** The interface itself is a Python type; the JSON Schema describes the *configuration block* Conductor UI workflow nodes pass when instantiating an adapter. This matches the v1.4 seam — the `harness` attribute on a workflow node is an `AdapterConfig`, which the engine resolves to a concrete `HarnessAdapter` instance.

7. **ABC abstract methods redeclare typed signatures, not `object` placeholders.** First draft used `object` to avoid import churn, but that violated LSP — mypy flagged 36 override-incompatibility errors. Fix: import the real types from `.types` in `base.py` and use them in the `@abstractmethod` declarations. The mixin Protocols already have the typed signatures; the ABC re-declares them so the @abstractmethod decorator has a signature to attach to.

**Alternatives considered:**
- *Use Pydantic for runtime type validation.* Rejected — keeps the dep surface minimal. TypedDict + dataclass(frozen=True, slots=True) give mypy-time checking without runtime cost.
- *Single big interface file with all 9 concerns.* Rejected — the build plan specifies 9 separate mixin files for the per-concern separation.
- *Generic `HarnessAdapter[TMessage, TEvent, ...]` parameterized by substrate.* Deferred to Phase 2+ once we see real substrate-specific event shapes (e.g., Anthropic's content-block model).
- *Subclass `typing.Protocol` directly for `HarnessAdapter` instead of `ABC`.* Rejected — Protocol doesn't enforce "implement all" at class-definition time. ABC gives the runtime check we need.

**Evidence:**
- `cd ~/projects/harness-adapter && uv run mypy interface/` → "Success: no issues found in 13 source files"
- `cd ~/projects/harness-adapter && uv run pytest interface/conformance.py -v` → "25 passed in 0.19s"
- `cd ~/projects/harness-adapter && git log --oneline` → `21fa3c7 feat(harness-adapter): Phase 1 — interface + conformance suite`
- `cd ~/projects/harness-adapter && uv run python -c "from jsonschema import Draft202012Validator; ..."` → schema meta-validates + accepts minimal + full configs

**Reversibility:** soft. Phase 2 (HermesAdapter) depends on this contract being stable; reversing it now means a Phase 2 rewrite. Cost of reversing after Phase 5 ships = high (4 adapters would need migration).

**Next:** Hephaestus Tier-1 verification (kanban task `t_9bee3e3e`). Acceptance for Tier-1: mypy strict passes (DONE), conformance suite 15+ cases (DONE — 25), JSON Schema validates (DONE), all ABC methods have docstrings (DONE). Phase 1 should pass Tier-1 cleanly. Then Ponytail Tier-2 (kanban task `t_34dd686d`).

— Marvin, 2026-06-18 (harness-adapter Phase 1, kanban task `t_460c2f11`)
