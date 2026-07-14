# Step 4.6 — Workflow validator (load-time check)

**Plan:** phase-4-quarantine-sovereign.yaml, Step 4.6
**Brief 2 of 3** (Brief 3 = verification + closure)
**Owner god:** hephaestus
**QA god:** thoth
**Date:** 2026-06-16
**Status context:** Brief 1 SHIP'd (operator_approval_required added to deploy-feature.yaml:53, 234/1/0 verified). Brief 2 builds the load-time validator that enforces the same contract.
**Builds on:** the `SOVEREIGN_OUTBOUND_RE` pattern in `engine.py:163` and the `_is_sovereign_outbound` helper at `engine.py:175`.

---

## TL;DR

Build a load-time workflow validator that hard-fails on any workflow with a sovereign NATS subject that doesn't carry `operator_approval_required: true`. This mirrors the engine's runtime guard at the workflow YAML layer so the breach pattern is caught at load time, not just at publish time.

**Two integration points** (Brief 2 implements both):
1. **`Workflow.from_dict` hook** — the loader calls the validator after parsing each step. Invalid workflows raise `WorkflowValidationError` with a clear message naming the step id and the missing field.
2. **Standalone script** at `pantheon/conductor/scripts/validate-workflows.py` — cron-friendly one-shot that walks `conductor/workflows/*.yaml` and reports violations. Useful for pre-flight checks and CI.

---

## Why both integration points

- **Loader hook** (option 1) is the strict, always-on enforcement. Any code path that loads a workflow gets the check for free. Brief 3's bypass test depends on this.
- **Standalone script** (option 2) is the operator-friendly escape hatch. Useful for "let me see which workflows would fail" without breaking the engine. Also catches workflows that haven't been loaded yet (e.g. a YAML sitting in the dir waiting to be discovered).

Both share the same validation function so the contract is single-source-of-truth.

---

## Deliverables (this brief)

### 1. NEW: `pantheon/conductor/v2/workflow_validator.py`

**Single-source-of-truth validation function:**

```python
"""Conductor v2 workflow YAML validator — load-time contract check.

Defense-in-depth for the 2026-06-15 sovereign-NATS breach pattern.
The engine's runtime guard (`_exec_nats_publish` in engine.py:~1017)
catches the breach at publish time. This module catches it at workflow
LOAD time — before the workflow is even instantiated — so the gap
between "workflow written" and "workflow first run" doesn't leave
a sovereignty hole.

Contract:
    Every `type: nats_publish` step whose `subject` matches
    `SOVEREIGN_OUTBOUND_RE` (^subspace\.[^.]+\.outgoing\..+$) MUST have
    `operator_approval_required: true`. Otherwise the workflow fails
    to load with a clear error.

    Non-sovereign nats_publish steps (e.g. `subspace.konan.inbox`,
    `subspace.test.inbox`, local NATS publishes) are NOT required to
    have the field.

Two consumers:
    1. `Workflow.from_dict` calls `validate_workflow(wf)` after parsing.
    2. `scripts/validate-workflows.py` walks workflows/*.yaml and
       reports violations.
"""
from __future__ import annotations
import re
from pathlib import Path
from typing import Iterable
import yaml
from .engine import SOVEREIGN_OUTBOUND_RE, Workflow

class WorkflowValidationError(ValueError):
    """Raised when a workflow violates the sovereign-outbound contract."""
    pass

def is_sovereign_outbound(subject: str) -> bool:
    """True if subject matches the sovereign-outbound pattern.
    Thin wrapper around SOVEREIGN_OUTBOUND_RE.match for testability.
    """
    return bool(SOVEREIGN_OUTBOUND_RE.match(subject or ""))

def validate_workflow(workflow: Workflow) -> list[str]:
    """Returns a list of human-readable violations. Empty list = valid.
    Non-empty list = the workflow has at least one gap.
    Does NOT raise — the caller decides whether to raise or just report.
    """
    violations: list[str] = []
    for step in workflow.steps:
        # Only nats_publish steps with a subject are relevant
        if step.type != "nats_publish" or not step.subject:
            continue
        if not is_sovereign_outbound(step.subject):
            continue
        # Sovereign outbound — must have operator_approval_required: true
        # WorkflowStep dataclass doesn't have this field yet (Step 4.6 Brief 1
        # added it to the YAML; the dataclass field will be added in this brief
        # OR validated by raw dict inspection — see brief body).
        if not getattr(step, "operator_approval_required", False):
            violations.append(
                f"step {step.id!r} (subject={step.subject!r}) is a sovereign "
                f"outbound and MUST have `operator_approval_required: true`. "
                f"Add the field to the step (see deploy-feature.yaml:53 for shape)."
            )
    return violations

def validate_workflow_file(path: Path) -> list[str]:
    """Load + validate a single workflow YAML. Returns violations list."""
    doc = yaml.safe_load(path.read_text())
    wf = Workflow.from_dict(doc, path)
    return validate_workflow(wf)

def validate_workflow_dir(dirpath: Path, skip_glob: str = "bridge-test-*") -> dict[str, list[str]]:
    """Walk a workflows directory and return {path: violations} for each
    workflow. Skips files matching `skip_glob` (default: bridge-test-*
    fixtures, which are not real workflows).
    """
    results: dict[str, list[str]] = {}
    for path in sorted(dirpath.glob("*.yaml")):
        if path.name.startswith(skip_glob.rstrip("*")):
            continue
        try:
            violations = validate_workflow_file(path)
        except Exception as e:
            violations = [f"failed to load: {e}"]
        if violations:
            results[str(path)] = violations
    return results
```

**Key design decisions** (with rationale + reversibility):

| Decision | Rationale | Reversible? |
|---|---|---|
| `is_sovereign_outbound` wraps `SOVEREIGN_OUTBOUND_RE` | Single source of truth for the pattern (engine.py:163) | Yes — the function is a 1-line wrapper |
| `validate_workflow` returns list, doesn't raise | Caller decides raise-vs-report. Loader hooks raise; CLI reports. | Yes |
| `WorkflowValidationError` extends `ValueError` | Catches as a known error class without breaking the engine's existing exception handling | Yes |
| Skip `bridge-test-*` glob by default | Those are test fixtures, not real workflows | Yes — glob is a parameter |

### 2. Wire into `Workflow.from_dict` (engine.py:519 area)

**Add a single block at the end of `Workflow.from_dict`** (after the cls() call at line 542) that calls `validate_workflow(wf)` and raises on violations. Use lazy import to avoid circular import (validator imports engine, engine imports validator for the hook).

```python
@classmethod
def from_dict(cls, d: dict[str, Any], source: Path) -> "Workflow":
    # ... existing parsing ...
    wf = cls(...)
    # NEW: load-time sovereign-outbound contract check
    from .workflow_validator import validate_workflow
    violations = validate_workflow(wf)
    if violations:
        raise WorkflowValidationError(
            f"workflow {wf.id!r} (source={source}) failed sovereign-outbound validation:\n  "
            + "\n  ".join(violations)
        )
    return wf
```

**Important:** the lazy import `from .workflow_validator import ...` keeps the dependency one-way (validator → engine, not engine → validator for the imports; runtime hook is the only engine→validator reference).

### 3. NEW: `pantheon/conductor/scripts/validate-workflows.py`

Standalone CLI:

```python
#!/usr/bin/env python3
"""Validate all workflows in a directory against the sovereign-outbound contract.

Usage:
    python3 scripts/validate-workflows.py [workflows_dir]
    
Default workflows_dir: ~/pantheon/conductor/workflows

Exit codes:
    0 = all workflows valid
    1 = at least one workflow has violations (printed to stderr)
    2 = invalid usage / fatal error
"""
from __future__ import annotations
import sys
from pathlib import Path
from conductor.v2.workflow_validator import validate_workflow_dir

def main() -> int:
    workflows_dir = Path(sys.argv[1] if len(sys.argv) > 1 else
                         Path.home() / "pantheon" / "conductor" / "workflows")
    if not workflows_dir.is_dir():
        print(f"ERROR: {workflows_dir} is not a directory", file=sys.stderr)
        return 2
    results = validate_workflow_dir(workflows_dir)
    if not results:
        print(f"OK: all workflows in {workflows_dir} pass sovereign-outbound validation")
        return 0
    print(f"FAIL: {len(results)} workflow(s) have violations:", file=sys.stderr)
    for path, violations in results.items():
        print(f"\n  {path}:", file=sys.stderr)
        for v in violations:
            print(f"    - {v}", file=sys.stderr)
    return 1

if __name__ == "__main__":
    sys.exit(main())
```

### 4. NEW: `pantheon/conductor/v2/tests/test_workflow_validator.py` (≥12 tests)

| # | Test | What it covers |
|---|---|---|
| 1 | `test_sovereign_subject_with_flag_passes` | `subspace.konan.outgoing.tallon` + `operator_approval_required: true` → 0 violations |
| 2 | `test_sovereign_subject_without_flag_fails` | `subspace.konan.outgoing.tallon` + no flag → 1 violation, names the step |
| 3 | `test_non_sovereign_subject_no_flag_required` | `subspace.konan.inbox` + no flag → 0 violations |
| 4 | `test_local_nats_publish_no_flag_required` | `my.local.subject` + no flag → 0 violations |
| 5 | `test_validator_raises_in_workflow_from_dict` | Workflow.from_dict with sovereign gap → raises WorkflowValidationError |
| 6 | `test_validator_returns_empty_for_valid_workflow` | Valid workflow → empty violations list |
| 7 | `test_validator_handles_multiple_violations` | Workflow with 2 sovereign gaps → 2 violations |
| 8 | `test_validate_workflow_dir_walks_directory` | validate_workflow_dir on a tmpdir with 3 YAMLs → returns expected {path: violations} map |
| 9 | `test_validate_workflow_dir_skips_bridge_test_glob` | tmpdir with deploy-feature.yaml + bridge-test-*.yaml → only deploy-feature checked |
| 10 | `test_validate_workflow_dir_handles_malformed_yaml` | tmpdir with a non-parseable YAML → returns {path: ["failed to load: ..."]} |
| 11 | `test_cli_script_exits_zero_on_clean_dir` | Subprocess.run on the CLI script with a clean dir → exit 0 |
| 12 | `test_cli_script_exits_one_on_dirty_dir` | Subprocess.run on the CLI script with a dirty dir → exit 1, stderr has violations |
| 13 | `test_cli_script_exits_two_on_missing_dir` | Subprocess.run on the CLI script with a missing dir → exit 2 |
| 14 | `test_existing_workflows_pass_validation` | Load all 5 production workflows (deploy-feature, bug-fix, cross-pantheon-deploy, morning-briefing, sovereign-publish-tallon-correction) → 0 violations across all (because deploy-feature now has the flag and the others have non-sovereign nats_publish) |

**Use the same `from v2.tests import fixtures as cf` pattern as test_parallel.py.**

---

## File changes planned

| File | Change | LOC est |
|---|---|---|
| `pantheon/conductor/v2/workflow_validator.py` (NEW) | The 4 functions above (is_sovereign_outbound, validate_workflow, validate_workflow_file, validate_workflow_dir) + WorkflowValidationError class | ~120 |
| `pantheon/conductor/v2/engine.py` (modify) | Add lazy import + validation hook at end of `Workflow.from_dict` (~line 542) | ~15 |
| `pantheon/conductor/scripts/validate-workflows.py` (NEW) | CLI entry point | ~40 |
| `pantheon/conductor/v2/tests/test_workflow_validator.py` (NEW) | 14 tests | ~250 |
| **Total** | | **~425 LOC** |

---

## Validation (your exit criteria)

```bash
# Targeted: the 14 new tests pass
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_workflow_validator.py -v
# Expect: 14/14 pass

# Existing 234 tests still pass
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 248/1-skip/0-fail (was 234/1/0 baseline; +14 validator tests)

# The CLI script works
python3 ~/pantheon/conductor/scripts/validate-workflows.py
# Expect: "OK: all workflows in /home/konan/pantheon/conductor/workflows pass sovereign-outbound validation", exit 0

# Hand-test the bypass: a workflow with a sovereign subject + no flag fails to load
python3 -c "
from pathlib import Path
from conductor.v2.engine import Workflow
import yaml
bad = yaml.safe_load('''
workflow:
  id: bad-test
  name: Bad
  version: '1.0.0'
  steps:
    - id: leak
      type: nats_publish
      subject: subspace.konan.outgoing.tallon
      message: 'bypass attempt'
''')
try:
    Workflow.from_dict(bad, Path('test.yaml'))
    print('FAIL: should have raised')
except Exception as e:
    print(f'OK: {type(e).__name__}: {e}')
"
# Expect: OK: WorkflowValidationError: workflow 'bad-test' (source=test.yaml) failed sovereign-outbound validation: step 'leak' (subject='subspace.konan.outgoing.tallon') is a sovereign outbound and MUST have `operator_approval_required: true`...
```

## Verification (Brief 3 will run)

- All 14 new tests pass
- Full v2 suite 248+/1-skip/0-fail
- 5 production workflows load via `Workflow.from_dict` with no parse errors (Brief 1's deploy-feature.yaml:53 change makes this work)
- The bypass hand-test above raises `WorkflowValidationError` with a clear message
- The CLI script exits 0 on the real workflows dir
- Plan YAML flip: Step 4.6 → DONE, current_step → 4.9.briefs.brief_1_of_3

---

## Reversibility

**Low cost.**
- Revert the 5-line addition to `Workflow.from_dict` (engine.py:542)
- Delete `workflow_validator.py` + `validate-workflows.py` + `test_workflow_validator.py`
- Zero impact on existing workflows (they still have their YAML shape; the validator just doesn't check them)
- Zero data state changes

---

## Reference files

- **Plan YAML:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (Step 4.6 in_progress, current_step: 4.6.briefs.brief_2_of_3)
- **Brief 1 SHIP evidence:** `~/pantheon/gods/messages/hermes/msg_20260616_053906_hermes.json` (deploy-feature.yaml:53 has the field)
- **Engine pattern:** `~/pantheon/conductor/v2/engine.py:163` (`SOVEREIGN_OUTBOUND_RE`)
- **Engine helper:** `~/pantheon/conductor/v2/engine.py:175` (`_is_sovereign_outbound`)
- **Workflow loader:** `~/pantheon/conductor/v2/engine.py:519` (`Workflow.from_dict` — the hook point)
- **Test fixture pattern:** mirror `test_parallel.py` (uses `from v2.tests import fixtures as cf` + MockRun/queue_run)
- **Handoff template:** `pantheon/gods/messages/hermes/msg_20260616_053906_hermes.json` (Step 4.6 Brief 1 closure)

## Open questions for Hephaestus (resolve before/during implementation)

1. **Where exactly to add the hook in `Workflow.from_dict`?** Before or after the cls() call? My recommendation: AFTER, so the wf object is fully constructed before validation (easier to inspect in the error message).
2. **Should the CLI script default to color output?** If terminal supports it, color the FAIL output red. Optional, easy to add.
3. **Should the validator log to ichor?** Pro: audit trail of who ran validate-workflows. Con: extra complexity. My recommendation: skip for v1, add later if operators want audit.
4. **Does the engine's existing `_is_sovereign_outbound` helper do exactly the same check?** Yes (engine.py:182: `return bool(SOVEREIGN_OUTBOUND_RE.match(subject))`). Use it, don't reimplement.

## What comes after this brief

**Brief 3 of 3** (verification + closure):
- Run the full validation suite
- Confirm all 5 deliverables landed
- Hand-test the bypass scenario (the one in the Validation section above)
- Flip Step 4.6 → DONE in plan YAML
- Decision log entry: closure + measured test count
- After 4.6 SHIPs cleanly: dispatch Step 4.9 Brief 1 to Marvin (cli_tool step type)
