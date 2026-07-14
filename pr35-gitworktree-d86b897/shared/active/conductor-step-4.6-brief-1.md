# Step 4.6 — YAML guardrails + workflow validator

**Plan:** phase-4-quarantine-sovereign.yaml, Step 4.6
**Brief 1 of 3** (Brief 2 = validator module; Brief 3 = verification + closure)
**Owner god:** hephaestus (per plan; this is a small targeted change)
**QA god:** thoth
**Date:** 2026-06-16
**Context:** Step 4.6 was originally marked "deferrable" — the engine regex already catches the sovereign-outbound breach shape at runtime. Operator (Konan) un-deferred it on 2026-06-16 as part of the substrate-hardening sequence (4.6 → 4.9 → 4.final). This is defense-in-depth: the workflow YAML contract now requires the same guard the engine enforces at runtime.

---

## TL;DR

The 2026-06-15 sovereign-NATS breach (2 fabricated messages published to `subspace.konan.outgoing.tallon` from `wf_8a0b5f28` and `wf_f26885f8`) was caught at runtime by `_exec_nats_publish` (Step 4.1 shipped the regex guard). **Step 4.6 is defense-in-depth at the workflow YAML layer** — make it impossible to *load* a workflow that would fail the runtime guard.

Two pieces:
1. **Brief 1 (this brief):** Add `operator_approval_required: true` to `deploy-feature.yaml:notify-enterprise` so the contract is explicit at the workflow layer.
2. **Brief 2:** Add a load-time validator (`pantheon/conductor/v2/workflow_validator.py`) that hard-fails on any workflow with a sovereign subject + no `operator_approval_required`. Tested in Brief 3.

---

## Brief 1 deliverable (this brief, very small)

**Add `operator_approval_required: true` to the `notify-enterprise` step in `deploy-feature.yaml`.**

**Current state** (`~/pantheon/conductor/workflows/deploy-feature.yaml`):
```yaml
    - id: notify-enterprise
      type: nats_publish
      subject: "subspace.konan.outgoing.tallon"
      input_from: review
      message: "Feature ${workflow_id} implemented and reviewed, ready for Enterprise deploy"
```

**Target state** (one new line, indented under the step):
```yaml
    - id: notify-enterprise
      type: nats_publish
      subject: "subspace.konan.outgoing.tallon"
      input_from: review
      operator_approval_required: true   # NEW: locks the contract at the workflow layer
      message: "Feature ${workflow_id} implemented and reviewed, ready for Enterprise deploy"
```

**That's it for this brief.** The change is 1 line.

### Why this is Brief 1 instead of Brief 2

The 3-brief shape is:
- **Brief 1:** Lock the existing workflow (the one that breached) to match the runtime contract. This is the "we did the right thing in the workflow YAML" pass.
- **Brief 2:** Build the load-time validator that prevents future workflows from being loaded with the same gap.
- **Brief 3:** Verify the validator catches crafted bypasses + full suite green.

Brief 1 is intentionally tiny because the validator in Brief 2 needs the field name (`operator_approval_required`) defined and used. Locking the existing workflow first means Brief 2's tests have a known-good shape to test against.

### Validation (your exit criteria)

```bash
# 1. deploy-feature.yaml parses cleanly (existing test pattern)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 234/1-skip/0-fail (no regressions; this brief doesn't add tests)

# 2. deploy-feature.yaml has the new field
grep "operator_approval_required" /home/konan/pantheon/conductor/workflows/deploy-feature.yaml
# Expect: one line match, indented under notify-enterprise

# 3. The runtime engine still treats it the same way
# (Brief 1 doesn't change engine behavior, just makes the workflow contract explicit.
#  Brief 2 will add the load-time check. Brief 3 will test bypasses.)
```

### Reversibility

Trivial. Revert the 1-line addition to `deploy-feature.yaml`. No engine change. No state change.

### What comes after this brief

**Brief 2 of 3** (Hephaestus continues):
- Build `pantheon/conductor/v2/workflow_validator.py` — a load-time check that:
  - Walks every workflow in `conductor/workflows/*.yaml` (skipping `bridge-test-*.yaml`)
  - For each `type: nats_publish` step with a sovereign subject (matching the existing `SOVEREIGN_OUTBOUND_RE` pattern), require `operator_approval_required: true`
  - Hard-fail on any workflow that has the gap, with a clear error message naming the step id and the missing field
  - Wire it into the engine's workflow loader (`WorkflowRegistry` / `Workflow.from_dict` hook) OR into a one-shot `scripts/validate-workflows.sh` cron-friendly entry point
- Add `tests/test_workflow_validator.py` with positive + negative cases

**Brief 3 of 3** (verification):
- Craft a workflow that bypasses the runtime regex (different subject shape) → load via validator → expect hard fail
- Run the full v2 suite → expect 246+/1-skip/0-fail (was 234/1/0 after 4.8; +12 from validator tests)
- Plan YAML flip: Step 4.6 → DONE

---

## Reference files

- **Plan YAML:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (Step 4.6 in_progress, header current_step: "4.6.briefs.brief_1_of_3")
- **deploy-feature.yaml:** `~/pantheon/conductor/workflows/deploy-feature.yaml` (the file to edit)
- **Engine regex pattern:** `~/pantheon/conductor/v2/engine.py` (search for `SOVEREIGN_OUTBOUND_RE` to find the exact pattern the runtime check uses — Brief 2 needs the same pattern in the load-time check)
- **Operator decisions log:** `~/pantheon/shared/decisions/2026-06-16-step-4.8.md` (broader context; the substrate-first discipline that put 4.6 in scope)
- **Engine guard implementation:** `~/pantheon/conductor/v2/engine.py` `_exec_nats_publish` (~line 914, the sovereign-outbound guard that runs at runtime — Brief 2's validator mirrors this logic at load time)

## Open questions for Hephaestus (resolve during Brief 2, not this brief)

1. **Where does the validator hook in?** Two options: (a) `Workflow.from_dict` raises on invalid workflows; (b) a one-shot `scripts/validate-workflows.sh` that runs at startup. Option (a) is stricter (catches at load time, no bypass possible). Option (b) is more permissive (existing workflows can load, validation is operator-triggered). My recommendation: option (a) with a one-shot script that calls the same validation function for cron-friendly pre-flight checks.

2. **Skip list:** should `bridge-test-*.yaml` be exempt? They exist in `conductor/workflows/` as test fixtures, not real workflows. The brief assumes yes; confirm in Brief 2.

## Out of scope (deferred to other steps)

- **WebSocket live-observability stream** (Step 4.9+ / Phase 2 of cli-orchestration spec)
- **Conductor GUI integration** (Iris, Phase 5+)
- **Worked-example workflows** (Thoth, Phase 6 of cli-orchestration spec)
- **Forge Autoresearch** (separate brief, unblocks after Step 4.7 SHIPped cleanly — which it has)
- **Step 4.final** (Phase 4 closure review, runs after 4.6 + 4.9 both SHIP)
