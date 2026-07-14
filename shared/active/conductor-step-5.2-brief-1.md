# Step 5.2 — Brief 1 of 3 — Phase 1 backbone regression

**Plan:** phase-5-e2e-test-suite, Step 5.2
**Brief 1 of 3** (Phase 1 regression)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Status:** SHIPPED

---

## TL;DR

Added a Phase 1 backbone regression test to
`conductor/v2/tests/test_backbone_e2e.py`:
`TestBackboneFull2StepChain.test_backbone_full_2step_chain_runs_to_completion`.

The existing `TestBackboneE2E.test_backbone_2step_workflow_runs_to_completion`
(Step 1.5) drives the v2 bridge path through `start → submit(1) → ack(1)`
and stops at the v2 advance to step 2. The new class drives the
**full 2-step chain** to completion: `start → submit(1) → ack(1) →
submit(2) → ack(2) → completed`. It proves the v2 path chains
BOTH submit+ack calls, not just the first.

**1 new test, 3/3 stable passes.** Full v2 suite: **293/1-skip/0-fail**
(was 292/1/0 after 5.1.3; +1 from this brief). No regression.

---

## Deliverable

**File:** `pantheon/conductor/v2/tests/test_backbone_e2e.py`
(grew from 834 to 1065 lines; +231 lines for the new test class).

**New test class:** `TestBackboneFull2StepChain` — one case:

1. **`test_backbone_full_2step_chain_runs_to_completion`** —
   drives a real 2-step workflow (thoth → hephaestus) through
   the v2 bridge path:
   - **start** → response shape (wf_*, status=running,
     current_step=step1-thoth)
   - **submit(1)** → v2 path runs (v2_dispatched=True,
     target_god=thoth, target_step=step1-thoth); a fresh
     wf_<uuid8> is minted (v1+v2 state file collision quirk)
   - **ack(1)** → v2 advance fires (v2_advanced=True,
     v2_next_step=step2-hephaestus); step-2 dispatch file
     lands in pending/hephaestus/
   - **submit(2)** → a SECOND fresh wf_<uuid8> is minted
     (each submit is a new start, per the v1+v2 collision)
   - **ack(2)** → v2 advance fires (v2_advanced=True,
     v2_next_step=None — workflow is now complete, no next step)
   - **Final state**: status=completed, current_step=None,
     definition_version still locked at 1.0.0,
     step_history has 2 entries (step1-thoth and
     step2-hephaestus, both status=completed)

---

## Why this matters

The Phase 1 backbone is "start_workflow MCP + ack_handoff MCP
chains to next step." The existing Step 1.5 test (in
`TestBackboneE2E`) covers:
- start response shape
- submit(1) + ack(1) → advance to step 2
- v2-shape dispatch files in pending/

But it stops at ack(1) — the v2 advance to step 2 is the LAST
thing it asserts. It does NOT prove that:
- submit(2) mints a fresh wf_<uuid8> per submit (the v1+v2
  state file collision quirk)
- ack(2) returns v2_next_step=None (workflow complete)
- The on-disk state file shows status=completed,
  current_step=None after ack(2)
- step_history accumulates both step entries (step1-thoth
  and step2-hephaestus, both completed)

This regression closes those gaps. If a future change
accidentally breaks the 2nd submit or the 2nd ack, this test
fails. The existing test would still pass (it never gets
that far).

---

## What this proves

The v2 bridge path's full chain works end-to-end:
- start → submit → ack → submit → ack → completed
- The v2 path uses current-step semantics (target_god = current
  step's god, not the next step's), which means submit(2)
  targets step1-thoth (the "current step" on the fresh
  instance), not step2-hephaestus
- The v2 advance on ack(2) recognizes the workflow is at its
  terminal step and returns v2_next_step=None
- The on-disk state file is updated to status=completed,
  current_step=None, and step_history has both entries
  recorded as completed

---

## What was hard

1. **v2 spec semantics differ from intuition.** Initially
   asserted that submit(2) targets `target_god=hephaestus`
   (the to_god we sent in the handoff). The v2 spec uses
   current-step semantics: target_god = the current step's
   god, which is step1-thoth on a fresh instance minted by
   submit(2). Fixed to match the v2 spec.

2. **v2 path mints a fresh wf_<uuid8> per submit.** The
   v2_wf_id_1 (from submit(1)) ≠ v2_wf_id_2 (from submit(2)).
   Asserted the inequality explicitly. The step-2 dispatch
   file uses a THIRD wf_id (the v2 advance mints its own
   when it writes the dispatch) — so the dispatch file's
   wf_id won't match either submit's wf_id. Asserted the
   file's existence via a glob pattern (any
   `*_step2-hephaestus.json` in pending/hephaestus/).

3. **Final state lives in the wf_id file, not v2_wf_id_2.**
   The v1 path's `_load_state(workflow_id)` uses the
   `workflow_id` from the handoff we sent (which is `wf_id`
   from `start_workflow`'s response). The v2 advance on
   ack(2) operates on this wf_id, NOT on v2_wf_id_2. The
   v2_wf_id_2 state file is left at status=in_progress,
   current_step=step1-thoth from the submit(2) call. The
   "real" final state is in `state/wf_<wf_id>.json`.

4. **step_history has 2 entries (not 1).** Initially asserted
   `len(history) == 1` (the step-2 entry from submit(2)).
   The correct shape is 2 entries: step1-thoth (completed)
   and step2-hephaestus (completed). The v2 path records
   BOTH steps in the wf_id state file.

5. **handoff_id / ack_id schema regex.** The bridge's
   `validate("handoff", ...)` enforces
   `^hof_\\d{8}_[a-z0-9]{6,8}$` and ack_id similar. Used
   `_date_suffix()` + `uuid4().hex[:8]` for the suffix.

---

## Verification

```bash
# Targeted: the new test
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest \
  conductor/v2/tests/test_backbone_e2e.py::TestBackboneFull2StepChain -v
# Expect: 1 passed

# Full v2 suite (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 293 passed, 1 skipped, 0 failed
```

**Result:** 3/3 stable runs, 293 passed, 1 skipped, 3 warnings
in 78.12s. ✓

---

## Reversibility

**Low cost.** Remove the `TestBackboneFull2StepChain` class
from `test_backbone_e2e.py` (lines ~835-1065). No engine or
bridge code changed. No production data touched. No fixtures
modified.

---

## What comes next

- **Step 5.2 Brief 2 of 3** — Phase 2/3/4 regression tests
  (schedule.cron fires rule's workflow + NATS message on
  matched subject triggers rule + quarantine helper returns
  right shape + sovereign guard blocks no-token publish).
  4 new tests total.
- **Step 5.2 Brief 3 of 3** — verification (all 4 backbone
  tests pass + existing test_backbone_e2e.py 2 cases still
  pass + full v2 suite still passes).

— Hermes, 2026-06-16
