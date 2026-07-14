"""Conductor v2 workflow YAML validator — load-time contract check.

Defense-in-depth for the 2026-06-15 sovereign-NATS breach pattern.
The engine's runtime guard (`_exec_nats_publish` in engine.py:~1017)
catches the breach at publish time. This module catches it at workflow
LOAD time — before the workflow is even instantiated — so the gap
between "workflow written" and "workflow first run" doesn't leave
a sovereignty hole.

Contract:
    Every `type: nats_publish` step whose `subject` matches
    `SOVEREIGN_OUTBOUND_RE` (^subspace\\.[^.]+\\.outgoing\\..+$) MUST have
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
    Pattern: ^subspace\\.[^.]+\.outgoing\\..+$
    """
    return bool(SOVEREIGN_OUTBOUND_RE.match(subject or ""))


def validate_workflow(workflow: Workflow) -> list[str]:
    """Returns a list of human-readable violations. Empty list = valid.

    Non-empty list = the workflow has at least one gap.
    Does NOT raise — the caller decides whether to raise or just report.
    """
    violations: list[str] = []
    # Structural checks first — these short-circuit before the
    # nats_publish loop so a malformed workflow doesn't get
    # "approved" by the sovereign-outbound check just because it
    # has no nats_publish steps. The api_server's PUT handler
    # relies on this to reject zero-step workflows BEFORE the
    # file is written (see test_put_rejects_invalid_workflow).
    if not workflow.steps:
        violations.append(
            f"workflow {workflow.id!r} has zero steps — at least one step is required"
        )
        # No point checking steps if there are none.
        return violations
    for step in workflow.steps:
        # Only nats_publish steps with a subject are relevant
        if step.type != "nats_publish" or not step.subject:
            continue
        if not is_sovereign_outbound(step.subject):
            continue
        # Sovereign outbound — must have operator_approval_required: true
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


def validate_workflow_dir(
    dirpath: Path, skip_glob: str = "bridge-test-*"
) -> dict[str, list[str]]:
    """Walk a workflows directory and return {path: violations} for each
    workflow. Skips files matching `skip_glob` (default: bridge-test-*
    fixtures, which are not real workflows).
    """
    results: dict[str, list[str]] = {}
    for path in sorted(dirpath.glob("*.yaml")):
        # Skip bridge-test fixtures (glob prefix match).
        if path.name.startswith(skip_glob.rstrip("*")):
            continue
        try:
            violations = validate_workflow_file(path)
        except Exception as e:
            violations = [f"failed to load: {e}"]
        if violations:
            results[str(path)] = violations
    return results
