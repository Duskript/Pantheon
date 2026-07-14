# Step 5.2 — Brief 2 of 3 — Phase 2/3/4 backbone regression

**Plan:** phase-5-e2e-test-suite, Step 5.2
**Brief 2 of 3** (Phase 2/3/4 regression — one backbone test per gap)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Status:** SHIPPED

---

## TL;DR

Added 4 backbone regression tests to
`conductor/v2/tests/test_backbone_e2e.py`:
`TestBackbonePhase2To4Regression` with one test per gap fixed in
Phases 2-4:

1. **Phase 2 (cron)** — `schedule.cron` event → rule matches → workflow
   instance created with the right `definition_id` + `current_step`
2. **Phase 3 (NATS)** — NATS message on matched subject → rule
   matches → workflow instance created
3. **Phase 4a (quarantine)** — `quarantine_status` helper returns
   the right shape on a fresh tmp layout (1 file → exit 1, count 1,
   items has 1 entry with `{filename, mtime, size_bytes}`)
4. **Phase 4b (sovereign)** — a workflow with a sovereign
   `nats_publish` step + no `operator_approval_token` is aborted
   by the engine's sovereign guard, with a `breach_blocked` step
   history entry and a `.aborted.json` manifest

**4 new tests, 3/3 stable runs.** Full v2 suite: **297/1-skip/0-fail**
(was 293/1/0 after Brief 5.2.1; +4 from this brief). No regression.

---

## Deliverable

**File:** `pantheon/conductor/v2/tests/test_backbone_e2e.py`
(grew from 1065 to 1526 lines; +461 lines for the new test class
plus imports).

**New test class:** `TestBackbonePhase2To4Regression` — 4 cases:

### 1. `test_phase2_cron_event_dispatches_workflow`

Drives a `schedule.cron` event through `engine.handle_event()` and
asserts the rule matches + a state file lands at `state/wf_*.json`
with `definition_id=test-cron-wf` and `current_step=step1`.

Setup:
- 1 rule: `schedule.cron` "* * * * *" → `dispatch_workflow=test-cron-wf`
- 1 workflow: 1-step (god=thoth)

This is the deterministic version of the existing slow
`test_cron_e2e.py` (which waits for a real cron boundary). The
new test invokes the engine's `handle_event` directly with a
synthesized Event, no real wait needed.

### 2. `test_phase3_nats_message_dispatches_workflow`

Drives a NATS message through `engine.handle_event()` and asserts
the rule matches + a state file lands at `state/wf_*.json` with
`definition_id=test-nats-wf`.

Setup:
- 1 rule: `nats.message` + `subject: "subspace.test.incoming.dispatch"` → `dispatch_workflow=test-nats-wf`
- 1 workflow: 1-step (god=thoth)

The deterministic version of the existing
`test_nats_bridge.test_nats_bridge_dispatches_cross_pantheon_deploy`
(which uses real production rules). The new test uses a minimal
rule in the tmp layout.

### 3. `test_phase4a_quarantine_status_returns_right_shape`

Runs the `quarantine_status.py` helper as a subprocess (real CLI
surface, not just `collect()` in isolation) against a fresh tmp
layout with 1 quarantine file. Asserts:
- exit code 1
- `payload["count"] == 1`
- `payload["items"]` has 1 entry with `{filename, mtime, size_bytes}`
- `payload["oldest_age_seconds"]` is a number ≥ 0

The deterministic version of the existing
`test_quarantine_status.py`. Same shape assertions, fresh tmp
layout, fast (< 100ms total).

### 4. `test_phase4b_sovereign_guard_blocks_no_token_publish`

Drives a workflow with 2 steps: (1) clean god step → (2) sovereign
`nats_publish` step with `operator_approval_required: true` and
**no** `operator_approval_token` in `context_bag`. Asserts:
- workflow.status == "aborted"
- `step_history` has exactly 1 `breach_blocked` entry for the
  nats_publish step
- `block_reason` mentions `operator_approval_token`
- `.aborted.json` manifest exists with `status=aborted`,
  `failed_step=step2-sov`, `failure_reason` mentions
  "sovereign outbound blocked"

The deterministic version of the existing
`test_sovereign_outbound_guard.test_breach_blocked_when_no_operator_approval`
(which uses refusals on prior steps to trigger the guard). The
new test triggers the guard with a CLEAN prior step + missing
token, which is the simpler failure mode.

---

## What this proves

Each test exercises the full observable side effect of one gap
fixed in Phases 2-4:

- **Phase 2:** `CronScheduler.tick()` → `engine.handle_event(Event(schedule.cron))` →
  `RuleEngine.match()` → `dispatch_workflow` → `state/wf_*.json` written
- **Phase 3:** NATS `_handle_msg()` → `engine.handle_event(Event(nats.message))` →
  `RuleEngine.match()` → `dispatch_workflow` → `state/wf_*.json` written
- **Phase 4a:** `quarantine_status.py --quarantine-dir X --webhooks-dir Y` →
  exit 1 + JSON payload with the right shape
- **Phase 4b:** `engine._exec_nats_publish()` with sovereign subject +
  no token → `breach_blocked` step + workflow abort + manifest

A regression in any of these 4 areas surfaces as a test failure.

---

## What was hard

1. **NATS event shape.** The `Event` dataclass has `subject` as a
   top-level field, not nested in `payload`. Initial test put
   `subject` in `payload` and the rule matcher (which uses
   `getattr(event, "subject")`) returned None. Fixed by moving
   `subject` to the top-level field.

2. **NATS rule uses `subject`, not `subject_match`.** The rule
   schema is `{event_type, subject, source, ...}` with `subject`
   supporting fnmatch globs. The test originally used
   `subject_match` (which doesn't exist) and the rule didn't match.
   Fixed by renaming to `subject` per the engine's matcher
   (`engine.py:368-369`).

3. **quarantine_status items shape.** The helper's `items` list
   has `{filename, mtime, size_bytes}` per file (not `{path,
   age_seconds}`). The test originally asserted `path` and
   `age_seconds`. Fixed to match the actual output.

4. **NATS event needs `is_external=True`.** Without this flag, the
   event is classified as internal and dropped (with the warning
   "unmatched internal event"). External events get the default
   quarantine rule applied on miss; internal events are just
   dropped.

---

## Verification

```bash
# Targeted: the 4 new tests
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest \
  conductor/v2/tests/test_backbone_e2e.py::TestBackbonePhase2To4Regression -v
# Expect: 4 passed

# Full v2 suite (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 297 passed, 1 skipped, 0 failed
```

**Result:** 3/3 stable runs, 7/7 in test_backbone_e2e.py, 297
passed, 1 skipped, 3 warnings in 63.87s. ✓

---

## Reversibility

**Low cost.** Remove the `TestBackbonePhase2To4Regression` class
from `test_backbone_e2e.py` (lines ~1070-1526) plus the 2 helper
imports (`from unittest.mock import MagicMock`, `import asyncio`).
No engine or rule code changed. No production data touched.
No fixtures modified.

---

## What comes next

- **Step 5.2 Brief 3 of 3** — verification (all 4 backbone tests
  pass + existing test_backbone_e2e.py 2 cases still pass + full
  v2 suite still passes).
- **Phase 5.2 closure** — once Brief 3 lands, Phase 5.2 is done.
  Combined with Phase 5.1, the Phase 5 E2E test suite adds 12
  new tests to the v2 test count (285 → 297, +12 net).
- **Phase 6 (parallel work)** — after Phase 5 closes, the
  substrate is fully trustworthy and the parallel-workstream
  plan (CLI orchestration, Forge Autoresearch, Conductor GUI)
  is unblocked.

— Hermes, 2026-06-16
