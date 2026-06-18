# Step 4.7 — `parallel` + `merge` step types (operator-approved scope cut)

**Plan:** phase-4-quarantine-sovereign.yaml, new entry 4.7
**Brief 1 of 2** (Brief 2 = verification/closure)
**Owner god:** marvin (engine + tests)
**QA god:** thoth
**Operator calls made:** 2026-06-16 (see §9 of spec)
**Date:** 2026-06-16
**Spec reference:** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` v1.0.0 (Thoth, 2026-06-15)

---

## TL;DR

Add **two** new step types to Conductor v2's engine — `parallel` (run N child steps concurrently) and `merge` (combine N outputs via strategy). Defer `cli_tool` and the WebSocket live-observability stream (Phases 1+2 of the spec). The LLM-judge strategies (`llm_summarize`, `llm_pick_best`) reuse the engine's existing `llm_call` path — no new dependency on the not-yet-built `cli_tool` step.

**The speedup:** workflows that today run linearly (research → architect → implement → review) can now run the `architect` and `implement` steps in parallel, with `merge.llm_pick_best` choosing the better output. Wall-clock savings: roughly N/M where N is parallel-eligible steps and M is the longest branch, instead of the sum.

**Scope cut rationale:** the operator asked to "manually load" the speedup rather than wait for the full 6-week Thoth plan. `parallel` + `merge` are the speedup, decoupled from `cli_tool` and WebSocket.

---

## What's in scope (this brief)

1. **`parallel` step type** in `engine.py:_execute_step`
   - Add `branches: list[WorkflowStep]`, `fail_mode: str = "fast"`, `max_concurrency: int = 0` (0 = unlimited), `timeout: str = "24h"` to the `WorkflowStep` dataclass
   - Implement concurrent child execution via `asyncio.gather` (Python's `asyncio.Semaphore` for `max_concurrency`)
   - `fail_mode`:
     - `fast` (default): cancel siblings on first failure, mark parallel step as failed
     - `slow`: let running siblings finish, mark parallel step as failed
     - `ignore`: log failures, parallel succeeds if ≥1 child succeeded
   - Children run as full step specs — any existing step type, including nested `parallel` (limit: 3 levels deep per spec §9)
   - Aggregate child outputs into a `map[branch_id] → child_output`
2. **`merge` step type** — new module `v2/merge.py`
   - Add `inputs: list[str]`, `strategy: str`, `strategy_config: dict`, `output: str` to `WorkflowStep`
   - **6 strategies** (per spec §2.3):
     - `concat` — concatenate inputs in order, separated by headers (no LLM)
     - `first` — first successful input (no LLM)
     - `diff` — structured diff between inputs (no LLM, requires ≥2 inputs)
     - `vote` — majority result on structured data, ties broken by `inputs` order (no LLM)
     - `llm_summarize` — LLM judge with summary prompt (reuses engine's `llm_call` path)
     - `llm_pick_best` — LLM judge with pick-best prompt, returns chosen + reasoning (reuses `llm_call`)
3. **Engine dispatch** — extend `_execute_step` (line 867) with the new step types
4. **WorkflowStep dataclass** — add the new fields (line 489) without breaking existing step types
5. **Tests** — new `v2/tests/test_parallel.py` and `v2/tests/test_merge.py` mirroring the existing test_engine.py pattern

## What's out of scope (deferred per operator)

- ❌ `cli_tool` step type (spec §2.1, Phase 1) — Marvin already handles that in a prior brief; covered by the cli_tools.yaml config the prior brief creates
- ❌ WebSocket live-observability stream (spec §3, Phase 2)
- ❌ `cli_tools.yaml` config — already exists at `~/pantheon/conductor/config/cli_tools.yaml` (or will, after the prior `cli_tool` brief ships)
- ❌ GUI integration (Phase 5, Iris)
- ❌ Worked-example workflows (Phase 6, Thoth) — can be authored after `parallel` + `merge` land

---

## File changes planned

| File | Change | LOC est |
|---|---|---|
| `pantheon/conductor/v2/engine.py` | Add `parallel`, `merge` to `WorkflowStep` dataclass; add `_exec_parallel`, `_exec_merge` methods; extend `_execute_step` dispatch (line 867) | ~250 |
| `pantheon/conductor/v2/merge.py` (NEW) | The 4 non-LLM `merge` strategies (`concat`, `first`, `diff`, `vote`) | ~150 |
| `pantheon/conductor/v2/tests/test_parallel.py` (NEW) | Concurrent execution, fail_mode (fast/slow/ignore), max_concurrency, nested parallel, error propagation | ~200 |
| `pantheon/conductor/v2/tests/test_merge.py` (NEW) | All 6 strategies on representative inputs, edge cases (empty, single, tie, malformed) | ~200 |
| `pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` | Add Step 4.7 entry below 4.6 | ~25 |

**Total: ~825 LOC**, of which ~400 is tests.

---

## Step type YAML shapes (canonical reference, copy from spec §7.4-7.5)

```yaml
# parallel
- id: parallel-implement
  type: parallel
  fail_mode: fast                # fast (default) | slow | ignore
  max_concurrency: 0             # 0 = unlimited
  timeout: 24h
  branches:
    - id: hephaestus-impl
      god: hephaestus
      skill: architecture-design
      input: spec
    - id: marvin-impl
      god: marvin
      skill: test-driven-development
      input: spec
  output: parallel-outputs
```

```yaml
# merge
- id: pick-best
  type: merge
  inputs: [hephaestus-impl, marvin-impl]
  strategy: llm_pick_best        # concat | first | diff | vote | llm_summarize | llm_pick_best
  strategy_config:
    judge_tool: llm_call         # Reuses engine's llm_call (no new dep)
    judge_prompt_template: |
      Compare these two implementations.
      Pick the one that is more correct, more idiomatic, and better-tested.
      Return the chosen implementation's full output verbatim.
    timeout: 30m
  output: best-impl
```

---

## Validation (your exit criteria)

```bash
# Unit tests
cd ~/pantheon/conductor/v2 && ~/.hermes/hermes-agent/venv/bin/pytest tests/test_parallel.py tests/test_merge.py -v
# Expect: all green, ≥20 tests across both files

# Regression: existing workflows still load
~/.hermes/hermes-agent/venv/bin/pytest tests/test_engine.py -v
# Expect: all green, no new failures

# Full suite (lock-in for Phase 4 closure)
cd ~/pantheon && ~/.hermes/hermes-agent/venv/bin/pytest tests/ conductor/v2/tests/ -q
# Expect: 220/220+ pass (was 200/1-skip/0-fail before this brief)

# Hand-test: load a workflow that uses parallel + merge
python3 -c "from conductor.v2.engine import Workflow; Workflow.from_dict({'workflow': {'id': 'test', 'name': 'test', 'version': '1.0.0', 'steps': [...]}}, Path('test.yaml'))"
# Expect: parses without error
```

## Verification (Brief 2 will run)

- A workflow YAML using `parallel` + `merge` parses and dispatches correctly
- Three existing workflows (`deploy-feature.yaml`, `bug-fix.yaml`, `cross-pantheon-deploy.yaml`) still load and dispatch (no breaking change)
- All 4 `parallel` `fail_mode` values tested
- All 6 `merge` strategies tested with deterministic inputs
- `max_concurrency` enforced (test with 4 branches, cap=2, verify ≤2 concurrent)
- Nested `parallel` (2 levels) works
- Deep nested `parallel` (>3 levels) raises a clear error at parse time
- LLM-merge strategies call the engine's existing `llm_call` path (verify with mock or test fixture)

---

## Reversibility

**Low cost, fully reversible.** If `parallel` or `merge` ship broken:

1. Revert the `WorkflowStep` dataclass additions (remove the 4 new fields)
2. Revert the `_execute_step` dispatch extension (remove the new `elif` branches)
3. Delete `merge.py` and the two test files
4. No existing workflow uses the new step types, so no YAML reverts needed
5. No data state changes (the engine is stateless across step types)

**Data state impact:** zero. The engine writes workflow state files (`state/<wf_id>.json`); the new step types write the same format with new `step_history` entries. No schema migration.

---

## Operator decisions recorded (your "C" call, locked 2026-06-16)

1. **Scope cut:** Build `parallel` + `merge` only. Defer `cli_tool`, WebSocket, GUI integration, worked-example workflows to separate briefs.
2. **Default `fail_mode` for `parallel`:** `fast` (cancel siblings on first failure, matches CI/CD behavior).
3. **`merge.llm_pick_best` output:** Return both `chosen_source` (which input was chosen) AND `judge_output` (the LLM's reasoning). The reasoning is useful for audit and learning.
4. **LLM-merge implementation:** Reuse the engine's existing `llm_call` path via the `_exec_llm` (or equivalent) method. No new dependency on the not-yet-built `cli_tool` step. If `llm_call` is currently broken/missing, fall back to a subprocess invocation of `~/.hermes/hermes-agent/venv/bin/python -c "import openai..."` with a clear error path.
5. **Nesting limit:** 3 levels deep for nested `parallel` (prevents infinite recursion, per spec §9 Q2).
6. **Step 4.6 status:** Stays `pending, deferrable`. Step 4.7 is independent of 4.6 and can run before or after.

---

## Reference files

- **Spec (full):** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` (26.5K, Thoth 2026-06-15)
- **Prior brief (cli_tool, Phase 1):** `~/pantheon/shared/active/conductor-cli-orchestration-brief.md` (6.6K) — out of scope here, but worth reading for the engine's design context
- **Engine:** `~/pantheon/conductor/v2/engine.py` (1,847 lines)
  - `WorkflowStep` dataclass: line 489
  - `_execute_step` dispatch: line 867
  - `_exec_god_dispatch`: line 879
  - `_exec_nats_publish`: line 914 (sovereign-outbound guard example)
- **Workflow loader:** `Workflow.from_dict` line 519 (extend with new fields)
- **Test pattern:** `~/pantheon/conductor/v2/tests/test_engine.py` (43.5K, 193 tests)
- **Plan YAML:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (12.0K, add Step 4.7 below 4.6)

## Open questions for Marvin (resolve before/during implementation)

1. **Where does `_exec_llm` live today?** If it doesn't exist, what's the path to call an LLM? (I need to know if `llm_summarize` / `llm_pick_best` can be a 5-LOC wrapper or need a new `_exec_llm` method.)
2. **Test fixture strategy for `parallel`:** real subprocesses or mocked `asyncio.gather` calls? The `test_engine.py` pattern uses real workflows against tmp dirs; mirror that.
3. **Backwards-compat check:** does the `WorkflowStep.from_dict` loader need to handle existing workflows that don't have `branches` / `inputs` fields? (Answer: yes, default to empty list / step type discriminator must be present.)

## What comes after this brief

**Brief 2 of 2** (verification + closure):
- Run all 4.7 tests + the full suite
- Verify the existing 6 workflows still load + dispatch (no regression)
- Hand-test a real `parallel` + `merge` workflow against a live NATS bridge (or mock if NATS is unavailable)
- Update plan YAML: Step 4.7 → DONE
- Decision log entry: closure + measured wall-clock savings on a parallel-eligible step
