# Step 4.8 — Step 4.7 Fix-Up Brief

**Plan:** phase-4-quarantine-sovereign.yaml, Step 4.8
**Brief 1 of 2** (Brief 2 = verification + plan YAML flip)
**Owner god:** Marvin
**QA god:** Thoth
**Date:** 2026-06-16
**Status context:** Step 4.7 Brief 1 partial-ship — engine landed, 3 tests failing, test_merge.py missing, handoff not dropped, DECISIONS.md not updated, parallel-build-plan.md not superseded
**Operator decisions:** see `~/pantheon/shared/decisions/2026-06-16-step-4.8.md`

---

## TL;DR

Step 4.7 Brief 1 was a partial ship. The engine code is correct (745 LOC added, 13/16 parallel tests pass, 298 LOC of merge.py is real). The gap is **test wiring + procedural misses**. This brief is a 5-item fix-up checklist that closes the gap without re-doing the engine work.

**The shape:** tests + handoff + doc discipline + supersession sidecar. ~150 LOC test fixes + 200 LOC new test_merge.py + 4 procedural items.

---

## Deliverables (this brief)

### 1. Fix 3 failing tests in `pantheon/conductor/v2/tests/test_parallel.py`

```
FAILED tests/test_parallel.py::TestParallelExecution::test_fail_mode_fast_first_failure_raises
FAILED tests/test_parallel.py::TestParallelExecution::test_max_concurrency_caps_simultaneous_branches
FAILED tests/test_parallel.py::TestParallelExecution::test_nested_parallel_two_levels_dispatches
```

**Test 1 (`test_fail_mode_fast_first_failure_raises`):** The fast-mode cancel logic is in the engine but the test fixture doesn't trigger it end-to-end. Read the test, see what cancellation primitive it expects, verify the engine provides it, fix the test fixture (not the engine).

**Test 2 (`test_max_concurrency_caps_simultaneous_branches`):** The semaphore cap (max_concurrency: N) limits concurrent branches. The test sets max_concurrency=2 with 4 branches but the assertion doesn't fire — likely the branches complete too fast to observe the cap. Either:
- Add artificial sleep to the mock branches so concurrency is observable, OR
- Use a counter-based assertion (count max concurrent in-flight)

**Test 3 (`test_nested_parallel_two_levels_dispatches`):** The inner sub-aggregate returns a string when the test expects a dict. Engine.py line 1271 builds the inner workflow as `steps=list(step.branches)`. The inner parallel step's output is what becomes the leaf1's value in the outer map. If the inner parallel's `output` field is missing, the engine uses string fallback. **Fix:** set `output: <name>` on the inner parallel step in the test fixture (or in the engine's aggregation logic if it should default to a map).

### 2. Write `pantheon/conductor/v2/tests/test_merge.py` (NEW)

**Mirror the test_parallel.py pattern.** The 4 non-LLM strategies in `merge.py` (concat, first, diff, vote) have ZERO test coverage. Write ≥6 tests:

| # | Test | What it covers |
|---|---|---|
| 1 | `test_concat_two_strings_joins_with_headers` | `concat` strategy on 2 string inputs |
| 2 | `test_concat_three_strings_preserves_order` | `concat` on 3 inputs, order matters |
| 3 | `test_first_returns_first_successful` | `first` on inputs [success, success] → returns inputs[0] |
| 4 | `test_first_skips_failed_inputs` | `first` on inputs [failed, success] → returns inputs[1] |
| 5 | `test_diff_two_dicts_shows_structured_diff` | `diff` on 2 dicts returns unified diff |
| 6 | `test_vote_majority_winner` | `vote` on 3 inputs (2 same, 1 different) → returns majority |
| 7 | `test_vote_tie_broken_by_order` | `vote` on 2 same + 2 same (4 inputs, 2-2 tie) → first in inputs order wins |

**Use the same `from v2.tests import fixtures as cf` import pattern as test_parallel.py.**

### 3. Add `pantheon/shared/active/conductor-parallel-build-plan.SUPERSEDED.md`

**This sidecar is already written** — copy it from `~/pantheon/shared/decisions/2026-06-16-step-4.8.md` directory or recreate it. The full plan at `conductor-parallel-build-plan.md` stays on disk (no destructive delete). The sidecar points to the operator-scoped decision log.

### 4. Update `athenaeum/Codex-Pantheon/DECISIONS.md` with 3 mid-task decisions

Marvin flagged these in his self-report — they're real design decisions that deserve a log entry:

1. **Reimplemented the parallel executor mid-task** to fix a double-execution bug
2. **Chose single-branch sub-workflow pattern** over `_execute_step` recursion
3. **Added a `declared_output` parameter** to `_latest_branch_output` rather than keying on the branch id alone

**Format for DECISIONS.md:**
```markdown
## 2026-06-16 — Step 4.7 mid-task design decisions

1. **Parallel executor reimplementation**: ...
2. **Single-branch sub-workflow pattern**: ...
3. **`declared_output` parameter on `_latest_branch_output`**: ...
```

If `DECISIONS.md` doesn't exist yet, create it. If it does, append.

### 5. Drop handoff message in `pantheon/gods/messages/hermes/`

**File:** `pantheon/gods/messages/hermes/msg_<timestamp>_hermes.json`

**Subject:** `[conductor/step-4.7/brief-1] parallel + merge SHIP`

**Body (template, fill in the actuals):**
```json
{
  "status": "complete",
  "test_count_parallel": 16,
  "test_count_merge": 6,
  "test_pass_total": "<actual>",
  "test_fail_total": 0,
  "loc_engine_added": 745,
  "loc_merge_module": 298,
  "loc_test_parallel": 506,
  "loc_test_merge_new": "<actual>",
  "full_suite": "<actual> passed, 1 skipped, 0 failed",
  "deviations": "<none, or list>",
  "open_questions": "<none, or list>"
}
```

**Use the standard handoff message format that other god messages use** (check `pantheon/gods/messages/hermes/` for examples — `msg_20260616_040825_hermes.json` from the Step 4.5 Brief 3 closure is a good template).

---

## File changes planned

| File | Change | LOC est |
|---|---|---|
| `pantheon/conductor/v2/tests/test_parallel.py` | Fix 3 failing tests (modify, not rewrite) | ~50 |
| `pantheon/conductor/v2/tests/test_merge.py` (NEW) | 4 non-LLM strategies, ≥6 tests | ~200 |
| `pantheon/shared/active/conductor-parallel-build-plan.SUPERSEDED.md` (NEW) | Sidecar, pointer to decision log | ~30 |
| `athenaeum/Codex-Pantheon/DECISIONS.md` | Append 3 mid-task decisions | ~30 |
| `pantheon/gods/messages/hermes/msg_<ts>_hermes.json` (NEW) | Standard handoff format | ~30 |
| **Total** | | **~340 LOC** |

**Engine code (engine.py, merge.py): ZERO changes.** The existing code is correct per the passing tests.

---

## Validation (your exit criteria)

```bash
# Targeted: the 3 failing tests now pass
cd ~/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_parallel.py -v
# Expect: 16/16 pass

# New: test_merge.py tests pass
cd ~/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_merge.py -v
# Expect: ≥6 tests pass

# Regression: existing 200 tests still pass
cd ~/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest tests/ conductor/v2/tests/ -q
# Expect: 220+/1-skip/0-fail

# Hand-test: 6 existing workflows still load
python3 -c "from pathlib import Path; from conductor.v2.engine import Workflow; import yaml; 
for p in Path('/home/konan/pantheon/conductor/workflows').glob('*.yaml'):
    if not p.name.startswith('bridge-test'):
        d = yaml.safe_load(p.read_text())
        wf = Workflow.from_dict(d, p)
        print(f'{p.name}: {len(wf.steps)} steps, OK')"
# Expect: 6 workflows load with no errors (deploy-feature, bug-fix, cross-pantheon-deploy, morning-briefing, sovereign-publish-tallon-correction)

# Check handoff landed
ls -la ~/pantheon/gods/messages/hermes/msg_*hermes.json | tail -1
# Expect: most recent file is the Step 4.7 SHIP handoff
```

## Verification (Brief 2 will run)

- All 16 parallel tests + all 6+ merge tests pass
- Full suite green at 220+/1-skip/0-fail
- 6 existing workflows load and parse without error
- Handoff message exists in `gods/messages/hermes/`
- `DECISIONS.md` has the 3 mid-task decisions logged
- `SUPERSEDED.md` sidecar is in place next to the parallel-build-plan
- Plan YAML flip: Step 4.7 + 4.8 → DONE, 4.final trigger updates to "All 4.1-4.8 DONE"

---

## Reversibility

**Very low cost.** Revert the test fixes (3 small edits) + delete `test_merge.py`. Drop the SUPERSEDED.md sidecar (it's just a markdown note). Delete the handoff message (or move it to a `processed/` subdir). Reverse the DECISIONS.md append (or leave it — it documents real decisions).

**Zero impact on engine.py or merge.py.** Those are already correct.

---

## Reference files

- **Step 4.7 Brief 1 (the partial ship):** `~/pantheon/shared/active/conductor-step-4.7-brief-1.md` (10.8K)
- **Step 4.7 decision log:** `~/pantheon/shared/decisions/2026-06-16-step-4.7.md` (operator-scoped decisions)
- **Step 4.8 decision log (this brief's scope):** `~/pantheon/shared/decisions/2026-06-16-step-4.8.md`
- **Plan YAML:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (Step 4.8 added, header flipped)
- **Marvin's off-script plan (the one being superseded):** `~/pantheon/shared/active/conductor-parallel-build-plan.md` (26.5K)
- **Engine code (correct, do not touch):** `~/pantheon/conductor/v2/engine.py` (2,574 lines, +745 from Step 4.7)
- **merge module (correct, do not touch):** `~/pantheon/conductor/v2/merge.py` (298 lines)
- **Failing tests:** `~/pantheon/conductor/v2/tests/test_parallel.py` (3 tests to fix)
- **Test fixture pattern:** mirror `test_parallel.py` (uses `from v2.tests import fixtures as cf` and the `MockRun` / `queue_run` pattern)
- **Handoff template:** `pantheon/gods/messages/hermes/msg_20260616_040825_hermes.json` (Step 4.5 Brief 3 closure)

## What comes after this brief

**Brief 2 of 2** (verification + closure):
- Run the full validation suite
- Confirm all 5 deliverables landed
- Flip Step 4.7 + 4.8 to DONE in plan YAML
- Update `4.final` trigger to "All 4.1-4.8 DONE"
- Decision log entry: closure + measured test count + whether the parallel+merge speedup is observable in a real workflow
- The handoff pattern itself (ship → inbox message → inbox pointer triggers next step if we add the inbox watcher) is the prototype for the Step "inbox watcher as webhook" pattern

## Open questions for Marvin (resolve before/during implementation)

1. **Did you actually reimplement the parallel executor, or was the self-report wrong?** The engine.py diff shows 745 insertions but the pattern looks like the original implementation with added fields. If the reimplementation is real, the diff stats will show the change. If not, the DECISIONS.md log entry should reflect what actually happened.

2. **What's the current behavior of `_latest_branch_output`?** The 3rd decision ("added a declared_output parameter") implies a function name. If you grep engine.py for that name, what does it show? This is the audit trail for the doc discipline fix.

3. **Test 3 fixture detail:** what does the inner `parallel` step look like in the test? Does it have an `output` field? If not, that's the fix — add `output: <name>` to the inner step.
