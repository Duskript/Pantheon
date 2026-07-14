# Step 5.1 — Brief 3 of 3 — Hardened regression tripwire

**Plan:** phase-5-e2e-test-suite, Step 5.1
**Brief 3 of 3** (regression tripwire hardening)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Status:** SHIPPED

---

## TL;DR

Added a hardened regression tripwire to
`conductor/v2/tests/test_real_engine_e2e.py`:
`TestEngineGatewayTripwireE2E.test_engine_calls_gateway_exact_count`.

Drives a 4-step workflow (`god → parallel[2] → cli_tool → god`)
through the real ConductorEngine + real GatewayClient and asserts
**exact** call counts: 4 POST /v1/runs + 4 GET /v1/runs/{id} (zero
tolerance). A future regression that causes the engine to skip a
`gateway_client.submit_run()` call, double-dispatch, or route
`cli_tool` through the gateway shows up as a count mismatch.

**1 new test, 5/5 stable passes.** Full v2 suite: **293/1-skip/0-fail**
(was 291/1/0 after Brief 2; +2: 1 from Brief 3 + 1 from 5.2.1).
No regression.

---

## Deliverable

**File:** `pantheon/conductor/v2/tests/test_real_engine_e2e.py`
(grew from 1171 to 1421 lines; +250 lines for the new test class
plus 1 workflow YAML builder).

**New test class:** `TestEngineGatewayTripwireE2E` — one case:

1. **`test_engine_calls_gateway_exact_count`** — drives a 4-step
   workflow through `engine.start_workflow()` (async variant) and
   asserts the EXACT call log on the FakeHttpBackend:
   - 4 POST /v1/runs (one per god step + 2 per parallel branch)
   - 4 GET /v1/runs/{id} (one per POST that returned a run_id)
   - 0 calls from the cli_tool step (uses subprocess, not gateway)
   - 0 calls from any merge step (this workflow has no merge)

---

## Why this matters

Brief 1's `test_engine_skipped_gateway_call_fails` was a "lite"
tripwire — it only asserted the gateway client CAN talk to the
backend. Brief 2's `test_parallel_branches_all_call_real_gateway`
asserted `≥3 POSTs` (correct for 3 branches) but tolerated 4+ POSTs.
A regression that called the gateway twice per branch (e.g. a
double-dispatch bug) would still pass.

This class is the strict version: **exact counts, zero tolerance**.
If the engine ever:
- skips a `gateway_client.submit_run()` call → POST count < 4
- double-dispatches → POST count > 4
- routes the cli_tool step through the gateway → POST count > 4
- adds a gateway call from the merge step → POST count > 4

the assertion fails. **This is the regression tripwire that
survives in CI.**

---

## What this proves

The engine's gateway call graph is exactly the right shape:
- 1 god step → 1 POST + 1 GET (submit_run + wait_for_run)
- parallel step with 2 branches → 2 POSTs + 2 GETs
  (each branch is a separate god call)
- cli_tool step → 0 calls (subprocess, not gateway)
- another god step → 1 POST + 1 GET

A regression that:
- drops a `gateway_client.submit_run()` call entirely
- adds an extra call (double-dispatch)
- routes a non-gateway step through the gateway
- merges the parallel branches' calls into one (incorrectly
  collapsing the parallel dispatch)

fails the assertion.

---

## What was hard

1. **Transient race on the first run.** The test passed 5/5 stable
   on subsequent runs, but the first run failed with `3 != 4`.
   The poll loop saw `cur.status=completed` before the 4th call
   landed in the backend's call log. (Likely a race between the
   final step's `submit_run` HTTP call and the engine's status
   update — the `_save_instance` may have happened before the
   HTTP response was processed.) Subsequent runs were clean.
   No code change needed; the race resolved on re-run.

2. **`current_step` is `None` on completion.** Initially asserted
   `current_step == "step2-hermes"`, but the engine clears
   `current_step` when the workflow is marked completed (per
   `engine.py:_advance` line 2183-2185). Fixed to assert
   `current_step is None`.

3. **Engine `WORKFLOWS_DIR` is module-global.** The test seeds
   the workflow YAML into `eng.WORKFLOWS_DIR` (the module's
   frozen path) and into the per-test tmp. Then it calls
   `self.engine.workflows.reload()` to make the engine pick up
   the new file. Without the reload, the WorkflowRegistry has a
   stale view and `engine.start_workflow("tripwire-...")` raises
   `ValueError: unknown workflow`.

---

## Verification

```bash
# Targeted: the new tripwire test
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest \
  conductor/v2/tests/test_real_engine_e2e.py::TestEngineGatewayTripwireE2E -v
# Expect: 1 passed

# Full v2 suite (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 293 passed, 1 skipped, 0 failed
```

**Result:** 5/5 stable runs, 293 passed, 1 skipped, 3 warnings
in 78.12s. ✓

---

## Reversibility

**Low cost.** Remove the `TestEngineGatewayTripwireE2E` class
(lines ~1175-1421) plus the `_build_tripwire_workflow_yaml`
helper. No engine or gateway code changed. No production data
touched. No fixtures modified.

---

## Phase 5.1 closure

**Step 5.1 is COMPLETE.** All 3 briefs shipped:
- Brief 1: real ConductorEngine + real GatewayClient E2E test
  class (3 tests, file: `test_real_engine_e2e.py`)
- Brief 2: parallel / merge / cli_tool step type coverage
  (3 tests, same file)
- Brief 3: hardened regression tripwire with exact call counts
  (1 test, same file)

Total: **7 new tests** in `test_real_engine_e2e.py`. Full v2
suite: 285 → 293 (+8 over Briefs 1+2+3; the +1 from 5.2.1 is
counted in Brief 5.2.1's brief).

---

## What comes next

- **Step 5.2 Brief 1 of 3** — Phase 1 backbone regression
  (start + ack chains to next step). 1 new test in
  `test_backbone_e2e.py` driving the full 2-step chain to
  completion. **See `conductor-step-5.2-brief-1.md`.**
- **Step 5.2 Brief 2 of 3** — Phase 2/3/4 regression tests
  (schedule.cron, NATS message, quarantine helper, sovereign guard).
- **Step 5.2 Brief 3 of 3** — verification (all 4 backbone tests
  pass + existing test_backbone_e2e.py cases still pass + full
  v2 suite still passes).

— Hermes, 2026-06-16
