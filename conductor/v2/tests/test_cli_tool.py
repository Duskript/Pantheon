"""Tests for Step 4.9 (Brief 1, 2026-06-16) — `cli_tool` step type.

22 tests covering:
  1.  test_run_subprocess_spawns_echo
  2.  test_run_subprocess_working_dir
  3.  test_run_subprocess_env_merge
  4.  test_run_subprocess_timeout_raises
  5.  test_run_subprocess_nonzero_exit
  6.  test_run_subprocess_binary_not_found
  7.  test_resolve_tool_returns_mock_echo
  8.  test_resolve_tool_unknown_raises
  9.  test_parse_output_text
  10. test_parse_output_json_valid
  11. test_parse_output_json_invalid_raises
  12. test_parse_output_stream_json_raises
  13. test_retry_no_retry_default
  14. test_retry_max_attempts_2_succeeds_on_2nd
  15. test_retry_exponential_backoff
  16. test_retry_fixed_backoff
  17. test_substitute_template_replaces_placeholders
  18. test_substitute_template_unknown_placeholder_kept
  19. test_parse_duration_known_units
  20. test_parse_duration_invalid_raises
  21. test_run_cli_tool_full_success_path
  22. test_run_cli_tool_with_session_id_resume
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402
from v2 import engine as eng  # noqa: E402
from v2 import cli_tool as ct  # noqa: E402


# ---------------------------------------------------------------------------
# 1-6: _run_subprocess lifecycle
# ---------------------------------------------------------------------------

class TestRunSubprocess(unittest.TestCase):
    """The synchronous subprocess layer (steps 1-6 of the brief)."""

    def setUp(self):
        # A clean tmp dir for tests that need working_dir behavior
        self.tmp = cf.TmpConductor.create()

    def tearDown(self):
        self.tmp.cleanup()
        # Remove any test-injected tool registrations
        ct.unregister_tool("_test_failing")
        ct.unregister_tool("_test_slow")

    def test_run_subprocess_spawns_echo(self):
        """Test 1: _mock_echo tool spawns echo "{prompt}" and captures stdout."""
        tool_reg = ct.resolve_tool("_mock_echo")
        exit_code, stdout, stderr, duration = ct._run_subprocess(
            tool_reg,
            input_dict={"prompt": "hello"},
            timeout_s=5.0,
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.strip(), "hello")
        self.assertEqual(stderr, "")
        self.assertGreaterEqual(duration, 0.0)

    def test_run_subprocess_working_dir(self):
        """Test 2: working_dir is honored (echo $PWD)."""
        tool_reg = ct.ToolRegistration(
            name="_pwd_echo",
            command="sh",
            args_template=["-c", "pwd"],
            output_format="text",
            timeout_default="5s",
        )
        ct.register_tool(tool_reg)
        try:
            exit_code, stdout, stderr, _ = ct._run_subprocess(
                tool_reg,
                input_dict={"prompt": "", "working_dir": str(self.tmp.root)},
                timeout_s=5.0,
            )
            self.assertEqual(exit_code, 0)
            # Resolve symlinks for the assertion (macOS /tmp is a symlink)
            self.assertEqual(
                Path(stdout.strip()).resolve(),
                self.tmp.root.resolve(),
            )
        finally:
            ct.unregister_tool("_pwd_echo")

    def test_run_subprocess_env_merge(self):
        """Test 3: tool_reg.env + tool_input.env merged correctly.

        Verifies:
          - tool_reg.env defaults are present
          - tool_input.env overrides win
          - process env stays (PATH etc.) so the binary can run
        """
        tool_reg = ct.ToolRegistration(
            name="_env_echo",
            command="sh",
            args_template=["-c", "echo $TOOL_DEFAULT; echo $STEP_OVERRIDE; echo $UNRELATED"],
            output_format="text",
            timeout_default="5s",
            env={"TOOL_DEFAULT": "from-tool", "UNRELATED": "from-tool-too"},
        )
        ct.register_tool(tool_reg)
        try:
            exit_code, stdout, stderr, _ = ct._run_subprocess(
                tool_reg,
                input_dict={
                    "prompt": "",
                    # Override one, set a new one. The tool default for
                    # UNRELATED should survive; STEP_OVERRIDE is new.
                    "env": {"STEP_OVERRIDE": "from-step", "UNRELATED": "from-step-wins"},
                },
                timeout_s=5.0,
            )
            self.assertEqual(exit_code, 0)
            lines = stdout.strip().split("\n")
            self.assertEqual(lines[0], "from-tool")        # untouched
            self.assertEqual(lines[1], "from-step")        # new from step
            self.assertEqual(lines[2], "from-step-wins")   # step overrides tool
            self.assertEqual(stderr, "")
        finally:
            ct.unregister_tool("_env_echo")

    def test_run_subprocess_timeout_raises(self):
        """Test 4: timeout=0.1s with a slow tool → CliToolTimeoutError."""
        # /bin/sleep 5 is universally available on POSIX; with timeout=0.1
        # it must be killed and raise CliToolTimeoutError.
        tool_reg = ct.ToolRegistration(
            name="_test_slow",
            command="/bin/sleep",
            args_template=["5"],
            output_format="text",
            timeout_default="10s",
        )
        ct.register_tool(tool_reg)
        try:
            with self.assertRaises(ct.CliToolTimeoutError) as ctx:
                ct._run_subprocess(
                    tool_reg,
                    input_dict={"prompt": ""},
                    timeout_s=0.1,
                )
            self.assertIn("timed out", str(ctx.exception))
            self.assertIn("0.1", str(ctx.exception))
        finally:
            ct.unregister_tool("_test_slow")

    def test_run_subprocess_nonzero_exit(self):
        """Test 5: /bin/false (always exits 1) → non-zero exit, no exception.

        _run_subprocess itself only raises on timeout / not-found.
        Non-zero exit is the caller's concern (run_cli_tool turns it
        into a CliToolError after retries)."""
        tool_reg = ct.ToolRegistration(
            name="_test_failing",
            command="/bin/false",
            args_template=[],
            output_format="text",
            timeout_default="5s",
        )
        ct.register_tool(tool_reg)
        try:
            exit_code, stdout, stderr, _ = ct._run_subprocess(
                tool_reg,
                input_dict={"prompt": ""},
                timeout_s=5.0,
            )
            self.assertEqual(exit_code, 1)
        finally:
            ct.unregister_tool("_test_failing")

    def test_run_subprocess_binary_not_found(self):
        """Test 6: nonexistent binary → CliToolNotFoundError (fail fast)."""
        tool_reg = ct.ToolRegistration(
            name="_ghost_tool",
            command="/nonexistent/binary/path/that/does/not/exist",
            args_template=[],
            output_format="text",
            timeout_default="5s",
        )
        ct.register_tool(tool_reg)
        try:
            with self.assertRaises(ct.CliToolNotFoundError) as ctx:
                ct._run_subprocess(
                    tool_reg,
                    input_dict={"prompt": ""},
                    timeout_s=5.0,
                )
            self.assertIn("not found", str(ctx.exception))
            self.assertIn("_ghost_tool", str(ctx.exception))
        finally:
            ct.unregister_tool("_ghost_tool")


# ---------------------------------------------------------------------------
# 7-8: resolve_tool
# ---------------------------------------------------------------------------

class TestResolveTool(unittest.TestCase):

    def test_resolve_tool_returns_mock_echo(self):
        """Test 7: resolve_tool('_mock_echo') returns the placeholder."""
        reg = ct.resolve_tool("_mock_echo")
        self.assertIsInstance(reg, ct.ToolRegistration)
        self.assertEqual(reg.name, "_mock_echo")
        self.assertEqual(reg.command, "echo")
        self.assertEqual(reg.output_format, "text")

    def test_resolve_tool_unknown_raises(self):
        """Test 8: resolve_tool('not-a-real-tool') → CliToolNotFoundError."""
        with self.assertRaises(ct.CliToolNotFoundError) as ctx:
            ct.resolve_tool("not-a-real-tool")
        self.assertIn("not-a-real-tool", str(ctx.exception))
        self.assertIn("Brief 2", str(ctx.exception))  # operator-friendly hint


# ---------------------------------------------------------------------------
# 9-12: _parse_output
# ---------------------------------------------------------------------------

class TestParseOutput(unittest.TestCase):

    def test_parse_output_text(self):
        """Test 9: output_format='text' → {'text': '...'}."""
        result = ct._parse_output("text", "hello world\n", "")
        self.assertEqual(result, {"text": "hello world\n"})

    def test_parse_output_json_valid(self):
        """Test 10: output_format='json' with valid JSON stdout → parsed dict."""
        result = ct._parse_output("json", json.dumps({"k": "v", "n": 42}), "")
        self.assertEqual(result, {"k": "v", "n": 42})

    def test_parse_output_json_invalid_raises(self):
        """Test 11: output_format='json' with non-JSON stdout → CliToolError."""
        with self.assertRaises(ct.CliToolError) as ctx:
            ct._parse_output("json", "not json {at all", "")
        self.assertIn("not valid JSON", str(ctx.exception))

    def test_parse_output_stream_json_raises(self):
        """Test 12: output_format='stream-json' → CliToolError with deferred msg."""
        with self.assertRaises(ct.CliToolError) as ctx:
            ct._parse_output("stream-json", "{}", "")
        self.assertIn("stream-json", str(ctx.exception))
        self.assertIn("deferred", str(ctx.exception))


# ---------------------------------------------------------------------------
# 13-16: retry / backoff (run_cli_tool)
# ---------------------------------------------------------------------------

class TestRetry(unittest.TestCase):

    def setUp(self):
        # Register a tool that always fails (1 attempt = 1 /bin/false call)
        self.fail_tool = ct.ToolRegistration(
            name="_always_fail",
            command="/bin/false",
            args_template=[],
            output_format="text",
            timeout_default="5s",
        )
        ct.register_tool(self.fail_tool)

    def tearDown(self):
        ct.unregister_tool("_always_fail")
        ct.unregister_tool("_succeed_on_second")

    def test_retry_no_retry_default(self):
        """Test 13: on_error={} with failing tool → 1 attempt, raises."""
        with self.assertRaises(ct.CliToolError) as ctx:
            ct.run_cli_tool(
                tool_reg=self.fail_tool,
                input_dict={"prompt": ""},
                on_error={},
                timeout_s=5.0,
            )
        self.assertIn("exited with code 1", str(ctx.exception))
        self.assertIn("_always_fail", str(ctx.exception))

    def test_retry_max_attempts_2_succeeds_on_2nd(self):
        """Test 14: max_attempts=2 with a tool that fails then succeeds.

        Uses a one-shot tool registered in setUp: first call exits 1,
        second call (via a stateful wrapper) exits 0. We patch
        `time.sleep` so the test is fast.
        """
        call_count = {"n": 0}

        def fake_run_subprocess(tool_reg, input_dict, timeout_s):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return (1, "", "first call fails", 0.01)
            return (0, "second call succeeds", "", 0.01)

        with patch.object(ct, "_run_subprocess", side_effect=fake_run_subprocess), \
             patch.object(ct.time, "sleep"):  # no real sleep in backoff
            result = ct.run_cli_tool(
                tool_reg=self.fail_tool,
                input_dict={"prompt": ""},
                on_error={"retry": {"max_attempts": 2, "backoff": "fixed", "backoff_base_seconds": 1}},
                timeout_s=5.0,
            )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "second call succeeds")
        self.assertEqual(result["tool_metadata"]["attempts"], 2)
        self.assertEqual(call_count["n"], 2)

    def test_retry_exponential_backoff(self):
        """Test 15: exponential backoff → sleep is called with the right multipliers.

        3 attempts, all fail. Backoff base = 1.0s, exponential.
        Expected sleeps: 1 * 2^0 = 1.0 (after attempt 1),
                         1 * 2^1 = 2.0 (after attempt 2).
        No sleep after attempt 3 (loop exits).
        """
        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        # All-attempts-fail tool
        with patch.object(ct, "_run_subprocess",
                          return_value=(1, "", "fail", 0.01)), \
             patch.object(ct.time, "sleep", side_effect=fake_sleep):
            with self.assertRaises(ct.CliToolError):
                ct.run_cli_tool(
                    tool_reg=self.fail_tool,
                    input_dict={"prompt": ""},
                    on_error={"retry": {
                        "max_attempts": 3,
                        "backoff": "exponential",
                        "backoff_base_seconds": 1.0,
                    }},
                    timeout_s=5.0,
                )
        self.assertEqual(sleep_calls, [1.0, 2.0])

    def test_retry_fixed_backoff(self):
        """Test 16: fixed backoff → sleep is called with the same delay each time."""
        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)

        with patch.object(ct, "_run_subprocess",
                          return_value=(1, "", "fail", 0.01)), \
             patch.object(ct.time, "sleep", side_effect=fake_sleep):
            with self.assertRaises(ct.CliToolError):
                ct.run_cli_tool(
                    tool_reg=self.fail_tool,
                    input_dict={"prompt": ""},
                    on_error={"retry": {
                        "max_attempts": 3,
                        "backoff": "fixed",
                        "backoff_base_seconds": 7.5,
                    }},
                    timeout_s=5.0,
                )
        self.assertEqual(sleep_calls, [7.5, 7.5])


# ---------------------------------------------------------------------------
# 17-18: _substitute_template
# ---------------------------------------------------------------------------

class TestSubstituteTemplate(unittest.TestCase):

    def test_substitute_template_replaces_placeholders(self):
        """Test 17: known placeholders are replaced."""
        template = ["--prompt", "{prompt}", "--cwd", "{working_dir}", "--resume", "{session_id}"]
        out = ct._substitute_template(template, {
            "prompt": "hello",
            "working_dir": "/tmp/x",
            "session_id": "sess-1",
        })
        self.assertEqual(out, ["--prompt", "hello", "--cwd", "/tmp/x", "--resume", "sess-1"])

    def test_substitute_template_unknown_placeholder_kept(self):
        """Test 18: unknown {placeholder} tokens are kept as-is."""
        template = ["{prompt}", "{unknown}", "{working_dir}"]
        out = ct._substitute_template(template, {"prompt": "x", "working_dir": "/y"})
        self.assertEqual(out, ["x", "{unknown}", "/y"])


# ---------------------------------------------------------------------------
# 19-20: _parse_duration
# ---------------------------------------------------------------------------

class TestParseDuration(unittest.TestCase):

    def test_parse_duration_known_units(self):
        """Test 19: s/m/h/d units parse to expected seconds."""
        self.assertEqual(ct._parse_duration("30s"), 30.0)
        self.assertEqual(ct._parse_duration("5m"), 300.0)
        self.assertEqual(ct._parse_duration("1h"), 3600.0)
        self.assertEqual(ct._parse_duration("1d"), 86400.0)
        self.assertEqual(ct._parse_duration("2.5h"), 9000.0)

    def test_parse_duration_invalid_raises(self):
        """Test 20: garbage input → ValueError."""
        with self.assertRaises(ValueError):
            ct._parse_duration("garbage")
        with self.assertRaises(ValueError):
            ct._parse_duration("30x")


# ---------------------------------------------------------------------------
# 21-22: run_cli_tool end-to-end
# ---------------------------------------------------------------------------

class TestRunCliToolEndToEnd(unittest.TestCase):

    def test_run_cli_tool_full_success_path(self):
        """Test 21: end-to-end happy path → result dict with all expected fields."""
        tool_reg = ct.resolve_tool("_mock_echo")
        result = ct.run_cli_tool(
            tool_reg=tool_reg,
            input_dict={"prompt": "from-test"},
            on_error={},
            timeout_s=5.0,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"].strip(), "from-test")
        self.assertEqual(result["parsed"], {"text": result["stdout"]})
        self.assertEqual(result["tool_metadata"]["tool"], "_mock_echo")
        self.assertEqual(result["tool_metadata"]["command"], "echo")
        self.assertEqual(result["tool_metadata"]["attempts"], 1)
        self.assertGreaterEqual(result["duration_seconds"], 0.0)

    def test_run_cli_tool_with_session_id_resume(self):
        """Test 22: resume=true + session_id → session_id_flag prepended to args.

        Calls _run_subprocess directly (not run_cli_tool) so we observe
        the actual args the subprocess would receive. The session_id_flag
        injection happens inside _run_subprocess itself.
        """
        tool_reg = ct.ToolRegistration(
            name="_resume_echo",
            command="/bin/echo",
            args_template=["prompt={prompt}"],
            output_format="text",
            timeout_default="5s",
            session_id_flag="--resume",
        )
        ct.register_tool(tool_reg)
        try:
            exit_code, stdout, stderr, _ = ct._run_subprocess(
                tool_reg,
                input_dict={
                    "prompt": "x",
                    "session_id": "sess-42",
                    "resume": True,
                },
                timeout_s=5.0,
            )
            # echo prints all its args space-separated. With the
            # session_id_flag prepended, the output should contain
            # --resume, sess-42, and the substituted prompt arg.
            self.assertEqual(exit_code, 0)
            self.assertIn("--resume", stdout)
            self.assertIn("sess-42", stdout)
            self.assertIn("prompt=x", stdout)
        finally:
            ct.unregister_tool("_resume_echo")


# ---------------------------------------------------------------------------
# WorkflowStep dataclass + engine integration smoke (Step 4.9 Back-compat)
# ---------------------------------------------------------------------------

class TestWorkflowStepDataclassStep49(unittest.TestCase):
    """Verify the new cli_tool fields exist on WorkflowStep with correct
    defaults and that the engine can construct a cli_tool step from YAML."""

    def test_cli_tool_fields_have_correct_defaults(self):
        s = eng.WorkflowStep(id="c")
        self.assertIsNone(s.tool)
        self.assertEqual(s.tool_input, {})
        self.assertEqual(s.on_error, {})

    def test_cli_tool_step_loads_from_yaml(self):
        wf_dict = {
            "workflow": {
                "id": "ct1",
                "name": "ct1",
                "version": "1.0.0",
                "steps": [{
                    "id": "s1",
                    "type": "cli_tool",
                    "tool": "_mock_echo",
                    "tool_input": {"prompt": "hello"},
                    "on_error": {"retry": {"max_attempts": 2}},
                    "timeout": "30s",
                    "output": "out1",
                }],
            }
        }
        tmp = cf.TmpConductor.create()
        try:
            wf = eng.Workflow.from_dict(wf_dict, tmp.workflows_dir / "ct1.yaml")
            s = wf.steps[0]
            self.assertEqual(s.type, "cli_tool")
            self.assertEqual(s.tool, "_mock_echo")
            self.assertEqual(s.tool_input, {"prompt": "hello"})
            self.assertEqual(s.on_error, {"retry": {"max_attempts": 2}})
            self.assertEqual(s.output, "out1")
            self.assertEqual(s.timeout, "30s")
        finally:
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
