# Step 5.1 — Brief 2 of 3 — Parallel / merge / cli_tool coverage

**Plan:** phase-5-e2e-test-suite, Step 5.1
**Brief 2 of 3** (Phase 4 substrate coverage)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Status:** SHIPPED

---

## TL;DR

Extended `conductor/v2/tests/test_real_engine_e2e.py` with a new
test class `TestRealEngineParallelMergeE2E` that drives the **3 new
step types** from Phase 4 (parallel, merge, cli_tool) end-to-end
through a real ConductorEngine + real GatewayClient (via
FakeHttpBackend). The class uses `engine.start_workflow()` (the
async variant) so the engine's `_execute_step` actually runs each
step type — the bridge's `submit_handoff` path is for inter-god
handoffs and does NOT exercise parallel/merge/cli_tool (those go
through the daemon's `_execute_step` path).

**3 new tests, all pass.** Full v2 suite: **291/1-skip/0-fail**
(was 288/1/0 after Brief 1; +3 from Brief 2). No regression.

---

## Deliverable

**File:** `pantheon/conductor/v2/tests/test_real_engine_e2e.py`
(grew from 766 to 1171 lines; +405 lines for the new test class
plus 2 workflow YAML builders).

**New test class:** `TestRealEngineParallelMergeE2E` — three cases:

1. **`test_parallel_branches_all_call_real_gateway`** — 3-branch
   parallel (thoth, hephaestus, marvin) hitting the FakeHttpBackend
   through a real GatewayClient. Asserts:
   - workflow completes (status=completed)
   - FakeHttpBackend recorded ≥3 POST /v1/runs and ≥3 GET /v1/runs/{id}
   - context_bag["parallel-outputs"] has all 3 branch outputs
     (keyed by branch id: "branch-thoth", "branch-hephaestus",
     "branch-marvin")
   - context_bag["merged_out"] is a dict with strategy="concat"
     and a non-empty merged_value

2. **`test_merge_concat_combines_branch_outputs`** — 2-branch
   parallel → merge (concat strategy). Asserts:
   - workflow completes
   - merged_value contains BOTH branch outputs
   - terminal step_history entry is status=completed

3. **`test_cli_tool_step_runs_subprocess_and_writes_state`** —
   1-step workflow: cli_tool referencing `_mock_echo`. The real
   engine's `_exec_cli_tool` invokes the `echo` subprocess with
   the prompt as the arg, captures stdout, and writes the result
   to context_bag. Asserts:
   - workflow completes
   - context_bag["echo_out"] contains the prompt text
   - step_history entry has `status=completed` and
     `god="_mock_echo"` (engine sets `god` to the tool name for
     audit clarity — see engine.py line 1307-1309)

---

## What this proves

The Phase 4 substrate earns its keep end-to-end:

- **`parallel` step type** can run N branches concurrently, each
  calling the real gateway, and the results land in
  `context_bag["<parallel-output-key>"]` keyed by branch id.
- **`merge` step type** with the `concat` non-LLM strategy works
  without needing an LLM API key, and the output shape is the
  documented `{strategy, merged_value, sources}` dict.
- **`cli_tool` step type** can invoke a real subprocess (the
  `_mock_echo` fixture, which is `echo {prompt}`) through the
  engine, and the captured stdout is written to `context_bag`.

The tests use the same real-engine + real-gateway (FakeHttpBackend)
wiring as Brief 1, so a regression where the engine stops calling
the gateway for parallel branches, or the merge step loses its
input resolution, or the cli_tool subprocess invocation breaks,
shows up as a failed assertion rather than silently passing on
mocks.

---

## Architecture difference from Brief 1

Brief 1 used the bridge's `submit_handoff` / `ack_handoff` path
(operator-side MCP call). That path works for the basic 2-step
god-dispatch workflow but does NOT exercise parallel/merge/cli_tool
because those step types are dispatched by the engine's
`_execute_step` (which is the daemon's responsibility).

Brief 2 uses `engine.start_workflow()` (the async variant) which
schedules `_execute_step` as a background task. This is the path
the production cron-triggered daemon uses, so the tests exercise
the same code path as production.

**Why not the bridge path for everything?** The bridge's
`submit_handoff` is for inter-god handoffs in an already-running
workflow. It does NOT handle cli_tool steps (which are not god
dispatches) and does NOT handle the parallel/merge executor
recursion. The daemon's `awatch` loop is the dispatcher for
parallel/merge/cli_tool steps.

---

## What was hard

1. **Parallel step's `parallel-outputs` is keyed by branch id, not
   branch god.** Initially I assumed it was keyed by short id
   (e.g. "t", "h", "m") but it's actually keyed by the full branch
   id from the YAML (e.g. "branch-thoth"). The test was wrong, not
   the engine. The first patch made it "t" which then failed; the
   correct key is "branch-thoth" (the full branch id).

2. **Merge's `concat` output is a dict, not a string.** The
   `run_merge` function returns `{"strategy": "concat",
   "merged_value": "...", "sources": [...]}`. The first patch
   asserted `isinstance(merged, str)` which failed. The correct
   assertion is to read `merged["merged_value"]` and assert on
   that.

3. **Engine module's `WORKFLOWS_DIR` is shared across tests.**
   The engine reads from `eng.WORKFLOWS_DIR` at construction time
   (per the Step 1.6 lazy fix). The test seeds the workflow YAML
   into both `tmp.workflows_dir` (for the per-test bridge) and
   `eng.WORKFLOWS_DIR` (for the engine direct). The test calls
   `self.engine.workflows.reload()` after writing to pick up the
   new file. Without the reload, the WorkflowRegistry has a stale
   view and the workflow won't be found.

4. **`start_workflow` is async.** Polling for completion requires
   `asyncio.sleep(0.02)` in a loop. The test uses
   `IsolatedAsyncioTestCase` (not the regular `unittest.TestCase`)
   so the asyncio loop is available.

---

## Verification

```bash
# Targeted: the 3 new tests
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_real_engine_e2e.py::TestRealEngineParallelMergeE2E -v
# Expect: 3 passed

# Full v2 suite (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 291 passed, 1 skipped, 0 failed (was 288/1/0 after Brief 1; +3)
```

**Result:** 291 passed, 1 skipped, 3 warnings in 78.58s. ✓

---

## Reversibility

**Low cost.** Remove the `TestRealEngineParallelMergeE2E` class
from `test_real_engine_e2e.py` (lines ~795-1171) plus the
`_build_parallel_workflow_yaml` and `_build_cli_tool_workflow_yaml`
helpers. No engine or gateway code changed. No production data
touched. No fixtures modified.

---

## What comes next

- **Step 5.1 Brief 3 of 3** — harden the regression tripwire.
  Brief 1's tripwire is focused on the basic 2-step god-dispatch
  (asserts the gateway client can talk to the backend). Brief 3
  will exercise the engine's `_execute_step` path (where the
  engine actually calls `submit_run`, dispatches parallel branches,
  runs cli_tool subprocesses, etc.) so the tripwire fires when
  the engine itself drops a `gateway_client.submit_run()` call,
  not just when the gateway client is broken.
- **Step 5.2 Brief 1 of 3** — Phase 1 regression test
  (start_workflow MCP + ack_handoff MCP chains to next step).
- **Step 5.2 Brief 2 of 3** — Phase 2/3/4 regression tests
  (schedule.cron, NATS message, quarantine helper, sovereign guard).
- **Step 5.2 Brief 3 of 3** — verification (all 4 backbone tests
  pass + existing test_backbone_e2e.py 2 cases still pass + full
  v2 suite still 193+ pass).

— Hermes, 2026-06-16
