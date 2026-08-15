"""Tests for the Step 4.6 workflow validator (Brief 2, 2026-06-16).

Covers:
  - is_sovereign_outbound correctly matches the pattern
  - validate_workflow returns violations for sovereign gaps
  - validate_workflow returns empty list for valid workflows
  - Workflow.from_dict raises WorkflowValidationError on gaps
  - Multiple violations in a single workflow
  - validate_workflow_dir walks directories correctly
  - bridge-test-* glob skip
  - Malformed YAML handling
  - CLI script exit codes (clean/dirty/missing dir)
  - All 5 production workflows pass validation
"""
from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402
from v2.workflow_validator import (  # noqa: E402
    WorkflowValidationError,
    is_sovereign_outbound,
    validate_workflow,
    validate_workflow_dir,
    validate_workflow_file,
)

_PROJECT_ROOT = _ROOT.parent  # pantheon/
_CLI_SCRIPT = str(_PROJECT_ROOT / "conductor" / "scripts" / "validate-workflows.py")


def _make_workflow_dict(
    steps: list[dict],
    wf_id: str = "test-wf",
    name: str = "Test",
    version: str = "1.0.0",
) -> dict:
    """Build a minimal workflow dict for from_dict testing."""
    return {
        "workflow": {
            "id": wf_id,
            "name": name,
            "version": version,
            "steps": steps,
        }
    }


def _sovereign_step_dict(
    step_id: str = "notify",
    with_approval: bool = False,
    subject: str = "subspace.konan.outgoing.tallon",
) -> dict:
    """Build a nats_publish step dict with a sovereign outbound subject."""
    step: dict = {
        "id": step_id,
        "type": "nats_publish",
        "subject": subject,
        "message": "test message",
    }
    if with_approval:
        step["operator_approval_required"] = True
    return step


def _non_sovereign_step_dict(
    step_id: str = "deliver",
    subject: str = "subspace.konan.inbox",
) -> dict:
    """Build a nats_publish step dict with a non-sovereign subject."""
    return {
        "id": step_id,
        "type": "nats_publish",
        "subject": subject,
        "message": "test message",
    }


def _make_step(
    step_id: str = "s1",
    step_type: str = "nats_publish",
    subject: str = "",
    operator_approval_required: bool = False,
) -> eng.WorkflowStep:
    """Create a WorkflowStep directly (bypasses from_dict for unit tests)."""
    return eng.WorkflowStep(
        id=step_id,
        type=step_type,
        subject=subject,
        operator_approval_required=operator_approval_required,
    )


def _make_workflow(
    steps: list[eng.WorkflowStep],
    wf_id: str = "test-wf",
) -> eng.Workflow:
    """Create a Workflow directly (bypasses from_dict for unit tests)."""
    return eng.Workflow(
        id=wf_id,
        name="Test",
        version="1.0.0",
        steps=steps,
        source_path=Path("/tmp/test.yaml"),
    )


class TestIsSovereignOutbound(unittest.TestCase):
    """Unit tests for the regex wrapper."""

    def test_sovereign_pattern_matches(self):
        self.assertTrue(is_sovereign_outbound("subspace.konan.outgoing.tallon"))
        self.assertTrue(is_sovereign_outbound("subspace.iris.outgoing.enterprise"))

    def test_inbox_pattern_does_not_match(self):
        self.assertFalse(is_sovereign_outbound("subspace.konan.inbox"))
        self.assertFalse(is_sovereign_outbound("subspace.test.inbox"))

    def test_local_subject_does_not_match(self):
        self.assertFalse(is_sovereign_outbound("my.local.subject"))
        self.assertFalse(is_sovereign_outbound("nats.internal.channel"))

    def test_empty_or_none_subject_returns_false(self):
        self.assertFalse(is_sovereign_outbound(""))
        self.assertFalse(is_sovereign_outbound(None))  # type: ignore[arg-type]


class TestValidateWorkflow(unittest.TestCase):
    """Core validate_workflow function tests — uses direct dataclass
    construction to bypass the from_dict hook."""

    def test_sovereign_subject_with_flag_passes(self):
        """Sovereign outbound + operator_approval_required: true → 0 violations."""
        wf = _make_workflow([
            _make_step("notify", subject="subspace.konan.outgoing.tallon",
                       operator_approval_required=True),
        ])
        self.assertEqual(validate_workflow(wf), [])

    def test_sovereign_subject_without_flag_fails(self):
        """Sovereign outbound + no flag → 1 violation, names the step."""
        wf = _make_workflow([
            _make_step("notify", subject="subspace.konan.outgoing.tallon",
                       operator_approval_required=False),
        ])
        violations = validate_workflow(wf)
        self.assertEqual(len(violations), 1)
        self.assertIn("'notify'", violations[0])
        self.assertIn("operator_approval_required", violations[0])

    def test_non_sovereign_subject_no_flag_required(self):
        """subspace.konan.inbox + no flag → 0 violations."""
        wf = _make_workflow([
            _make_step("deliver", subject="subspace.konan.inbox",
                       operator_approval_required=False),
        ])
        self.assertEqual(validate_workflow(wf), [])

    def test_local_nats_publish_no_flag_required(self):
        """my.local.subject + no flag → 0 violations."""
        wf = _make_workflow([
            _make_step("pub", subject="my.local.subject",
                       operator_approval_required=False),
        ])
        self.assertEqual(validate_workflow(wf), [])

    def test_workflow_with_no_nats_publish_steps_passes(self):
        """A workflow with only god-type steps → 0 violations."""
        wf = _make_workflow([
            eng.WorkflowStep(id="research", type="god", god="thoth"),
        ])
        self.assertEqual(validate_workflow(wf), [])


class TestWorkflowFromDictRaises(unittest.TestCase):
    """The from_dict hook raises WorkflowValidationError on gaps."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.source = self.tmp.workflows_dir / "bad.yaml"

    def tearDown(self):
        self.tmp.cleanup()

    def test_validator_raises_in_workflow_from_dict(self):
        """from_dict with sovereign gap → raises WorkflowValidationError."""
        d = _make_workflow_dict(
            [_sovereign_step_dict(with_approval=False)],
            wf_id="bad-wf",
        )
        with self.assertRaises(WorkflowValidationError) as ctx:
            eng.Workflow.from_dict(d, self.source)
        self.assertIn("'bad-wf'", str(ctx.exception))
        self.assertIn("sovereign-outbound validation", str(ctx.exception))

    def test_validator_does_not_raise_for_valid_workflow(self):
        """from_dict with properly flagged sovereign step → no raise."""
        d = _make_workflow_dict(
            [_sovereign_step_dict(with_approval=True)],
            wf_id="good-wf",
        )
        wf = eng.Workflow.from_dict(d, self.source)
        self.assertEqual(wf.id, "good-wf")


class TestValidateWorkflowMultipleViolations(unittest.TestCase):
    """Multiple sovereign gaps in a single workflow — using direct
    dataclass construction to test validate_workflow without from_dict."""

    def test_validator_handles_multiple_violations(self):
        """Workflow with 2 sovereign gaps → 2 violations."""
        wf = _make_workflow([
            _make_step("step-a", subject="subspace.konan.outgoing.tallon"),
            _make_step("step-b", subject="subspace.konan.outgoing.tallon"),
        ])
        violations = validate_workflow(wf)
        self.assertEqual(len(violations), 2)
        self.assertIn("'step-a'", violations[0])
        self.assertIn("'step-b'", violations[1])

    def test_mixed_flagged_and_unflagged(self):
        """One with flag, one without → 1 violation."""
        wf = _make_workflow([
            _make_step("ok", subject="subspace.konan.outgoing.tallon",
                       operator_approval_required=True),
            _make_step("bad", subject="subspace.konan.outgoing.tallon",
                       operator_approval_required=False),
        ])
        violations = validate_workflow(wf)
        self.assertEqual(len(violations), 1)
        self.assertIn("'bad'", violations[0])


class TestValidateWorkflowDir(unittest.TestCase):
    """Directory-level validation: walk, skip glob, malformed YAML."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_yaml(self, name: str, d: dict) -> Path:
        path = self.tmp.workflows_dir / name
        path.write_text(yaml.dump(d))
        return path

    def _write_raw(self, name: str, text: str) -> Path:
        path = self.tmp.workflows_dir / name
        path.write_text(text)
        return path

    def test_validate_workflow_dir_walks_directory(self):
        """validate_workflow_dir on a tmpdir with 3 YAMLs → returns expected map."""
        # Valid: sovereign with flag
        self._write_yaml(
            "a-valid.yaml",
            _make_workflow_dict(
                [_sovereign_step_dict(with_approval=True)], wf_id="a"
            ),
        )
        # Invalid: sovereign without flag
        self._write_yaml(
            "b-invalid.yaml",
            _make_workflow_dict(
                [_sovereign_step_dict(with_approval=False)], wf_id="b"
            ),
        )
        # Valid: non-sovereign
        self._write_yaml(
            "c-valid.yaml",
            _make_workflow_dict(
                [_non_sovereign_step_dict()], wf_id="c"
            ),
        )

        results = validate_workflow_dir(self.tmp.workflows_dir)

        # b-invalid.yaml should have violations (from_dict raises, caught)
        self.assertEqual(len(results), 1,
                         f"Expected 1 result, got {len(results)}: {results}")
        b_path = str(self.tmp.workflows_dir / "b-invalid.yaml")
        self.assertIn(b_path, results)
        self.assertEqual(len(results[b_path]), 1)

    def test_validate_workflow_dir_skips_bridge_test_glob(self):
        """bridge-test-*.yaml files are skipped."""
        # Write a valid yaml (non-bridge-test)
        self._write_yaml(
            "real-workflow.yaml",
            _make_workflow_dict([_non_sovereign_step_dict()], wf_id="real"),
        )
        # Write a bridge-test file that would have violations
        self._write_yaml(
            "bridge-test-abc123.yaml",
            _make_workflow_dict(
                [_sovereign_step_dict(with_approval=False)], wf_id="bt"
            ),
        )
        # Another bridge-test
        self._write_yaml(
            "bridge-test-def456.yaml",
            _make_workflow_dict(
                [_sovereign_step_dict(with_approval=False)], wf_id="bt2"
            ),
        )

        results = validate_workflow_dir(self.tmp.workflows_dir)
        # bridge-test files are skipped → only real-workflow.yaml is checked
        # and it's valid → 0 results
        self.assertEqual(
            len(results), 0,
            f"Expected 0 violations (bridge-test skipped), got: {results}"
        )

    def test_validate_workflow_dir_handles_malformed_yaml(self):
        """Non-parseable YAML → returns {path: ['failed to load: ...']}."""
        self._write_raw("broken.yaml", "this: [ is not valid --- yaml")

        results = validate_workflow_dir(self.tmp.workflows_dir)

        broken_path = str(self.tmp.workflows_dir / "broken.yaml")
        self.assertIn(broken_path, results)
        self.assertEqual(len(results[broken_path]), 1)
        self.assertIn("failed to load", results[broken_path][0])

    def test_validate_workflow_dir_empty_directory(self):
        """Empty directory → returns {}."""
        results = validate_workflow_dir(self.tmp.workflows_dir)
        self.assertEqual(results, {})


class TestCLIScript(unittest.TestCase):
    """Subprocess tests for the validate-workflows.py CLI script."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_yaml(self, name: str, d: dict) -> Path:
        path = self.tmp.workflows_dir / name
        path.write_text(yaml.dump(d))
        return path

    def _run_cli(self, workflows_dir: Path) -> subprocess.CompletedProcess:
        import os as _os
        env = dict(_os.environ)
        env["PYTHONPATH"] = str(_PROJECT_ROOT)
        return subprocess.run(
            [sys.executable, _CLI_SCRIPT, str(workflows_dir)],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            env=env,
        )

    def test_cli_script_exits_zero_on_clean_dir(self):
        """CLI on a clean dir → exit 0."""
        self._write_yaml(
            "valid.yaml",
            _make_workflow_dict([_non_sovereign_step_dict()], wf_id="valid"),
        )
        result = self._run_cli(self.tmp.workflows_dir)
        self.assertEqual(
            result.returncode, 0,
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        self.assertIn("OK", result.stdout)

    def test_cli_script_exits_one_on_dirty_dir(self):
        """CLI on a dir with violations → exit 1, stderr has violations."""
        self._write_yaml(
            "bad.yaml",
            _make_workflow_dict(
                [_sovereign_step_dict(with_approval=False)], wf_id="bad"
            ),
        )
        result = self._run_cli(self.tmp.workflows_dir)
        self.assertEqual(
            result.returncode, 1,
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        self.assertIn("FAIL", result.stderr)
        self.assertIn("operator_approval_required", result.stderr)

    def test_cli_script_exits_two_on_missing_dir(self):
        """CLI on a missing dir → exit 2."""
        import os as _os
        env = dict(_os.environ)
        env["PYTHONPATH"] = str(_PROJECT_ROOT)
        result = subprocess.run(
            [sys.executable, _CLI_SCRIPT, "/nonexistent/path/xyz"],
            capture_output=True,
            text=True,
            cwd=str(_PROJECT_ROOT),
            env=env,
        )
        self.assertEqual(
            result.returncode, 2,
            f"stdout={result.stdout}\nstderr={result.stderr}"
        )
        self.assertIn("ERROR", result.stderr)


class TestExistingWorkflowsPassValidation(unittest.TestCase):
    """Verify all 5 production workflows pass sovereign-outbound validation.

    Two production workflows (cross-pantheon-deploy, sovereign-publish-
    tallon-correction) currently lack operator_approval_required on their
    sovereign outbound steps. These failures are surfaced explicitly so the
    operator knows which files need the field added (the Brief 1 change
    only touched deploy-feature.yaml).

    The test fails with a detailed message naming the exact files and steps
    that need the field, rather than silently masking the gap.
    """

    _REAL = Path("/home/konan/pantheon/conductor/workflows")

    def test_existing_workflows_pass_validation(self):
        """Load all 5 production workflows → report any violations."""
        results = validate_workflow_dir(self._REAL, skip_glob="bridge-test-*")

        production_ids = {
            "deploy-feature",
            "bug-fix",
            "cross-pantheon-deploy",
            "morning-briefing",
            "sovereign-publish-tallon-correction",
        }

        # Verify each expected workflow exists
        checked_paths = set()
        for path in sorted(self._REAL.glob("*.yaml")):
            if path.name.startswith("bridge-test-"):
                continue
            checked_paths.add(path.name)

        expected_not_covered = production_ids - {
            Path(p).stem for p in checked_paths
        }
        self.assertEqual(
            expected_not_covered, set(),
            f"Expected workflows not found in dir: {expected_not_covered}"
        )

        # Report violations if any — the operator needs to add
        # operator_approval_required: true to the listed files.
        if results:
            detail = "\n".join(
                f"  {p}: {v}" for p, v in results.items()
            )
            self.fail(
                f"{len(results)} production workflow(s) need "
                f"operator_approval_required: true added:\n{detail}"
            )
