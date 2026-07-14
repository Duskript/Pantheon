# Step 4.9 — `cli_tool` step type

**Plan:** phase-4-quarantine-sovereign.yaml, Step 4.9
**Brief 1 of 3** (Brief 2 = cli_tools.yaml config + tool registration; Brief 3 = verification + closure)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Status context:** Step 4.7+4.8 (parallel + merge) SHIP'd, Step 4.6 (validator) SHIP'd. Step 4.9 unlocks the third primitive from Thoth's cli-orchestration spec — workflows that invoke external CLI tools (Claude Code, Codex CLI) instead of just routing to gods.
**Operator decisions locked** (per the 2026-06-16-step-4.7 decision log):
- `stream: false` default (opt-in per step)
- Nested parallel: already limited to 3 levels (Brief 1 doesn't touch this)
- `llm_pick_best` returns chosen + reasoning (already done in 4.7)
- Default `fail_mode` for parallel: `fast` (already done in 4.7)
- WebSocket auth / `cli_tools.yaml` location: deferred to Brief 2
- Multi-turn streaming input: NO for v1 (use `resume: true` + `session_id`)
- Tool binary not installed: fail fast with clear error

**Spec reference:** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` §2.1, §4, §5, §7.3

---

## TL;DR

Add a `cli_tool` step type to the Conductor v2 engine. Workflows can now invoke registered CLI subprocesses (Claude Code, Codex CLI) from a step, capture their output, fail on non-zero exit, retry per `on_error` config, and resume a prior session. This unlocks the "best of N agents" workflow (Claude Code + Codex CLI + Marvin + Hephaestus in parallel) when combined with the existing `parallel` + `merge` step types.

**Three deliverables this brief** (all additive, all backwards-compatible):

1. **Engine change** — extend `WorkflowStep` dataclass with cli_tool fields; add `_exec_cli_tool` method; extend `_execute_step` dispatch
2. **NEW module** `cli_tool.py` — subprocess invocation, output parsing, session resume, retry logic
3. **NEW test file** `test_cli_tool.py` — ≥12 tests covering subprocess lifecycle, error handling, timeout, resume, retry, output parsing

**Brief 2 will** build the `cli_tools.yaml` config (v1 tool set: claude-code, codex, gemini-cli) and the engine's load-at-startup hook.

**Brief 3 will** verify, hand-test against a mock tool, and flip the plan YAML.

---

## Deliverables (this brief)

### 1. MODIFY: `pantheon/conductor/v2/engine.py` — WorkflowStep + dispatch

**WorkflowStep dataclass additions** (after the existing `operator_approval_required` field, ~line 530):

```python
# --- Step 4.9 (Brief 1, 2026-06-16): cli_tool step type ---
# `cli_tool` step fields: which registered tool to invoke, the input
# contract (prompt, working_dir, env, session_id, resume, timeout, stream),
# optional gates, and on_error config (retry policy + final-failure action).
# Per Thoth's spec §2.1 and §7.3. The actual subprocess invocation lives
# in cli_tool.py; the engine just dispatches and stores the output.
tool: Optional[str] = None  # which registered tool (claude-code, codex, etc.)
tool_input: dict[str, Any] = field(default_factory=dict)  # {prompt, working_dir, env, session_id, resume, timeout, stream}
on_error: dict[str, Any] = field(default_factory=dict)  # {retry: {max_attempts, backoff, backoff_base_seconds}, on_final_failure: <action>}
```

**Workflow.from_dict loader** (~line 581, `_step_from_dict`): read the new fields from the YAML dict, default to None / {}.

**`_execute_step` dispatch** (currently at ~line 952 with the if/else for `nats_publish` vs god_dispatch; `parallel` and `merge` are also handled):

```python
if step.type == "nats_publish":
    await self._exec_nats_publish(inst, step)
elif step.type == "parallel":
    await self._exec_parallel(inst, wf, step)
elif step.type == "merge":
    await self._exec_merge(inst, wf, step)
elif step.type == "cli_tool":
    await self._exec_cli_tool(inst, wf, step)
else:
    await self._exec_god_dispatch(inst, wf, step)
```

**NEW: `_exec_cli_tool` method** — a thin orchestrator that delegates to the `cli_tool.py` module:

```python
async def _exec_cli_tool(self, inst, wf, step) -> None:
    """Execute a `type: cli_tool` step (subprocess invocation).
    
    Per Thoth's spec §2.1. The actual subprocess work happens in
    `cli_tool.run_cli_tool` (synchronous). The engine wraps it with:
      1. Timeout enforcement
      2. Output capture + structured parsing
      3. Retry policy per on_error.retry
      4. Step history recording (in_progress → completed/failed)
      5. Output stored at workflow.context_bag[step.output] for downstream
    """
    from .cli_tool import run_cli_tool, CliToolError, CliToolNotFoundError
    
    if not step.tool:
        raise ValueError(f"cli_tool step {step.id!r} has no `tool` field")
    
    # Record start (existing pattern)
    inst.step_history.append({
        "step_id": step.id,
        "god": step.tool,  # use the tool name as the "god" for history
        "status": "in_progress",
        "started": utc_now(),
    })
    self._save_instance(inst)
    
    try:
        # Resolve the tool registration (loaded by Brief 2 from cli_tools.yaml)
        # If no registration exists yet (Brief 2 not shipped), the helper
        # raises a clear "tool not registered" error.
        from .cli_tool import resolve_tool
        tool_reg = resolve_tool(step.tool)
        
        # Run the subprocess (with timeout, retry, session resume)
        timeout_s = _parse_duration(step.timeout)
        result = await asyncio.get_event_loop().run_in_executor(
            None,  # default executor
            lambda: run_cli_tool(
                tool_reg=tool_reg,
                input_dict=step.tool_input,
                on_error=step.on_error,
                timeout_s=timeout_s,
            ),
        )
        
        # Record completion (existing pattern)
        self._record_step_completion(inst, step, result)
        
        # Continue the DAG
        await self._advance(inst, wf, step, result)
    except (CliToolError, CliToolNotFoundError) as e:
        LOG.exception(f"cli_tool step {step.id} failed in {inst.workflow_id}: {e}")
        self._record_step_failure(inst, step, str(e))
        self._save_instance(inst)
        if inst.abort_on_fail:
            self._abort_workflow(inst, f"cli_tool step {step.id!r} failed: {e}")
```

**Important:** the `resolve_tool()` function is imported from `cli_tool.py` (which Brief 1 creates as a stub returning a placeholder for unregistered tools; Brief 2 fills in the real cli_tools.yaml loader). This keeps Brief 1 shippable without Brief 2.

### 2. NEW: `pantheon/conductor/v2/cli_tool.py` — subprocess invocation module

**Single-source-of-truth module for cli_tool execution. ~300 LOC.**

```python
"""Conductor v2 `cli_tool` step executor.

Companion to engine.py — implements the subprocess invocation for
cli_tool steps per Thoth's spec §2.1, §4, and §7.3.

The engine dispatches to `_exec_cli_tool` which calls `run_cli_tool`
(synchronous) wrapped in asyncio. The synchronous core keeps the
subprocess handling straightforward (no async-subprocess quirks).

Tool registration (from cli_tools.yaml) is loaded by Brief 2. For
Brief 1, the `resolve_tool()` function returns a hardcoded placeholder
when no registration is found, so the engine can be tested without
Brief 2 being shipped. Brief 2 replaces the placeholder with the real
config loader.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger("conductor.v2.cli_tool")


# ---------- Exceptions ----------

class CliToolError(Exception):
    """Raised when a cli_tool step fails for any reason (non-zero exit,
    timeout, tool not installed, etc.). The error message includes the
    tool name and the failure reason for clear operator feedback.
    """
    pass

class CliToolNotFoundError(CliToolError):
    """Raised when the requested tool's binary is not on $PATH.
    Per Thoth's spec §9 Q8: fail fast with a clear error, no fallback.
    """
    pass

class CliToolTimeoutError(CliToolError):
    """Raised when the tool subprocess exceeds the step's timeout."""
    pass


# ---------- Tool registration (Brief 2 will fill this in from cli_tools.yaml) ----------

@dataclass
class ToolRegistration:
    """The registration of a single CLI tool (per Thoth's spec §4)."""
    name: str
    command: str  # Executable name (resolved via $PATH) or absolute path
    args_template: list[str]  # Argument template, with {prompt}, {working_dir}, {session_id} placeholders
    output_format: str = "text"  # json | text | stream-json
    timeout_default: str = "4h"
    session_id_flag: Optional[str] = None  # Flag to pass session_id for resume (e.g. --resume for Claude Code)
    stdin_prompt: bool = False  # If true, prompt is piped to stdin instead of via args
    env: dict[str, str] = field(default_factory=dict)  # Default env vars
    max_concurrent: int = 1  # Per-workflow concurrency cap
    stream_format: Optional[str] = None  # none | claude-stream-json | codex-stream-json


# Brief 1 placeholder: a default tool registration so the engine can
# dispatch a cli_tool step without Brief 2 being shipped. The test
# suite uses a MOCK tool (see test_cli_tool.py) — Brief 1 does NOT
# need to invoke real Claude Code or Codex CLI binaries.
_DEFAULT_TOOLS: dict[str, ToolRegistration] = {
    "_mock_echo": ToolRegistration(
        name="_mock_echo",
        command="echo",  # Built into every POSIX system
        args_template=["{prompt}"],
        output_format="text",
        timeout_default="30s",
    ),
}


def resolve_tool(name: str) -> ToolRegistration:
    """Look up a tool by name. For Brief 1, returns the _mock_echo
    placeholder. Brief 2 will replace this with a cli_tools.yaml loader.
    
    Raises CliToolNotFoundError if the tool isn't registered.
    """
    if name in _DEFAULT_TOOLS:
        return _DEFAULT_TOOLS[name]
    # Brief 2 will populate this from cli_tools.yaml
    raise CliToolNotFoundError(
        f"tool {name!r} is not registered. Brief 1 ships with only "
        f"the _mock_echo placeholder; Brief 2 adds the cli_tools.yaml "
        f"config loader with the v1 tool set (claude-code, codex, gemini-cli)."
    )


# ---------- Subprocess invocation ----------

def _substitute_template(template: list[str], substitutions: dict[str, str]) -> list[str]:
    """Replace {placeholder} tokens in the args_template.
    Unknown placeholders are left as-is (so a partial substitution
    doesn't silently drop content).
    """
    result = []
    for arg in template:
        for key, value in substitutions.items():
            arg = arg.replace("{" + key + "}", str(value))
        result.append(arg)
    return result


def _parse_duration(s: str) -> float:
    """Parse '30m', '4h', '90s' into seconds. Delegates to engine.py's
    _parse_duration if available; otherwise implements a simple parser.
    """
    # Try to use the engine's helper
    try:
        from .engine import _parse_duration as _engine_parse
        return _engine_parse(s)
    except ImportError:
        pass
    # Fallback simple parser
    m = re.match(r"^(\d+(?:\.\d+)?)([smhd]?)$", s.strip())
    if not m:
        raise ValueError(f"invalid duration: {s!r}")
    value = float(m.group(1))
    unit = m.group(2) or "s"
    return value * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _run_subprocess(
    tool_reg: ToolRegistration,
    input_dict: dict[str, Any],
    timeout_s: float,
) -> tuple[int, str, str, float]:
    """Spawn the tool subprocess, capture output, return (exit_code, stdout, stderr, duration_seconds).
    
    Per Thoth's spec §2.1.1-3:
    1. Build args from args_template + input_dict
    2. Set working_dir from input_dict (default: cwd)
    3. Merge env: tool_reg.env + input_dict['env']
    4. Spawn subprocess
    5. Wait with timeout
    6. Capture stdout/stderr
    7. Return exit_code + outputs + duration
    """
    prompt = input_dict.get("prompt", "")
    working_dir = input_dict.get("working_dir", os.getcwd())
    extra_env = input_dict.get("env", {})
    session_id = input_dict.get("session_id")
    resume = input_dict.get("resume", False)
    
    # Merge env: process env + tool defaults + step overrides
    env = dict(os.environ)
    env.update(tool_reg.env)
    env.update(extra_env)
    
    # Build args: substitute placeholders
    substitutions = {
        "prompt": prompt,
        "working_dir": working_dir,
        "session_id": session_id or "",
    }
    args = _substitute_template(tool_reg.args_template, substitutions)
    
    # If resume is true and the tool has a session_id_flag, inject session_id
    if resume and session_id and tool_reg.session_id_flag:
        args = [tool_reg.session_id_flag, session_id] + args
    
    started = time.monotonic()
    try:
        proc = subprocess.run(
            args,
            cwd=working_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,  # we handle non-zero exit ourselves
        )
        duration = time.monotonic() - started
        return (proc.returncode, proc.stdout, proc.stderr, duration)
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - started
        raise CliToolTimeoutError(
            f"tool {tool_reg.name!r} timed out after {timeout_s}s"
        ) from e
    except FileNotFoundError as e:
        raise CliToolNotFoundError(
            f"tool {tool_reg.name!r} binary not found: {tool_reg.command!r}. "
            f"Check that the tool is installed and on $PATH."
        ) from e


def _parse_output(output_format: str, stdout: str, stderr: str) -> dict[str, Any]:
    """Parse the tool's stdout into a structured output per output_format.
    
    Per Thoth's spec §2.1.4. For Brief 1, we support:
    - text: stdout is a single string
    - json: stdout is parsed as JSON
    - stream-json: NOT supported in Brief 1 (no live observability)
    """
    if output_format == "text":
        return {"text": stdout}
    if output_format == "json":
        try:
            return json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError as e:
            raise CliToolError(
                f"tool output is not valid JSON: {e}. "
                f"First 200 chars: {stdout[:200]!r}"
            ) from e
    if output_format == "stream-json":
        # Brief 1 doesn't support stream-json (WebSocket observability is Brief 2+ / separate)
        raise CliToolError(
            "output_format=stream-json requires the WebSocket live-observability "
            "stream (Thoth spec §3), which is deferred to a separate brief. "
            "For Brief 1, use output_format=text or output_format=json."
        )
    raise CliToolError(f"unknown output_format: {output_format!r}")


def run_cli_tool(
    tool_reg: ToolRegistration,
    input_dict: dict[str, Any],
    on_error: dict[str, Any],
    timeout_s: float,
) -> dict[str, Any]:
    """Run a cli_tool step. Synchronous (called from engine via run_in_executor).
    
    Per Thoth's spec §2.1:
    1. Spawn subprocess
    2. Capture output
    3. Parse output per output_format
    4. If exit non-zero, apply on_error.retry policy
    5. Return the structured output (or raise on final failure)
    """
    retry_cfg = on_error.get("retry", {}) or {}
    max_attempts = int(retry_cfg.get("max_attempts", 1))  # default: no retry
    backoff = retry_cfg.get("backoff", "none")  # none | fixed | exponential
    backoff_base_seconds = float(retry_cfg.get("backoff_base_seconds", 30))
    
    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            exit_code, stdout, stderr, duration = _run_subprocess(
                tool_reg, input_dict, timeout_s,
            )
            
            if exit_code == 0:
                # Success
                parsed = _parse_output(tool_reg.output_format, stdout, stderr)
                return {
                    "status": "success",
                    "exit_code": exit_code,
                    "duration_seconds": duration,
                    "stdout": stdout,
                    "stderr": stderr,
                    "parsed": parsed,
                    "tool_metadata": {
                        "tool": tool_reg.name,
                        "command": tool_reg.command,
                        "attempts": attempt,
                    },
                }
            
            # Non-zero exit: log + retry if configured
            LOG.warning(
                f"tool {tool_reg.name!r} attempt {attempt}/{max_attempts} "
                f"failed with exit_code={exit_code}: stderr={stderr[:200]!r}"
            )
            last_error = CliToolError(
                f"tool {tool_reg.name!r} exited with code {exit_code}: {stderr[:500]}"
            )
        except (CliToolTimeoutError, CliToolNotFoundError) as e:
            # These don't retry — they fail fast
            raise
        
        # Apply backoff before next attempt (if there is one)
        if attempt < max_attempts:
            if backoff == "fixed":
                time.sleep(backoff_base_seconds)
            elif backoff == "exponential":
                time.sleep(backoff_base_seconds * (2 ** (attempt - 1)))
            # "none" → no sleep
    
    # All attempts exhausted
    final_failure = on_error.get("on_final_failure", "fail_workflow")
    if final_failure == "escalate_hermes":
        LOG.error(f"tool {tool_reg.name!r} exhausted {max_attempts} attempts; escalating to Hermes")
    raise last_error or CliToolError(f"tool {tool_reg.name!r} failed after {max_attempts} attempts")
```

**Key design decisions** (with rationale + reversibility):

| Decision | Rationale | Reversible? |
|---|---|---|
| Synchronous `run_cli_tool` wrapped in `run_in_executor` | Subprocess handling is straightforward sync; async-subprocess adds quirks for no benefit | Yes — swap to asyncio.create_subprocess_exec if needed |
| `resolve_tool` returns a hardcoded `_mock_echo` for Brief 1 | Brief 1 shippable without Brief 2's cli_tools.yaml loader; tests use the mock | Yes — Brief 2 replaces the placeholder |
| `stream-json` raises with a clear error | WebSocket observability is a separate brief; don't silently half-implement | Yes |
| `CliToolNotFoundError` and `CliToolTimeoutError` don't retry | Per Thoth's spec §9 Q8: fail fast on missing tool, no fallback | Yes |
| `on_error.retry.backoff` supports none/fixed/exponential | Per Thoth's spec §2.1 example: `backoff: exponential, backoff_base_seconds: 30` | Yes |
| `tool_input.env` merges on top of `tool_reg.env` | Step-specific overrides win (e.g. ANTHROPIC_API_KEY per call) | Yes |

### 3. NEW: `pantheon/conductor/v2/tests/test_cli_tool.py` (≥12 tests)

| # | Test | What it covers |
|---|---|---|
| 1 | `test_run_subprocess_spawns_echo` | _mock_echo tool: spawns echo "{prompt}", captures stdout "hello" |
| 2 | `test_run_subprocess_working_dir` | working_dir is honored (echo $PWD) |
| 3 | `test_run_subprocess_env_merge` | tool_reg.env + tool_input.env merged correctly (process env stays out) |
| 4 | `test_run_subprocess_timeout_raises` | timeout=0.1s with a slow tool → CliToolTimeoutError |
| 5 | `test_run_subprocess_nonzero_exit` | /bin/false (always exits 1) → CliToolError with stderr in message |
| 6 | `test_run_subprocess_binary_not_found` | tool_reg.command="/nonexistent/binary" → CliToolNotFoundError |
| 7 | `test_resolve_tool_returns_mock_echo` | resolve_tool("_mock_echo") returns the placeholder |
| 8 | `test_resolve_tool_unknown_raises` | resolve_tool("not-a-real-tool") → CliToolNotFoundError |
| 9 | `test_parse_output_text` | output_format="text" → {"text": "..."} |
| 10 | `test_parse_output_json_valid` | output_format="json" with valid JSON stdout → parsed dict |
| 11 | `test_parse_output_json_invalid_raises` | output_format="json" with non-JSON stdout → CliToolError |
| 12 | `test_parse_output_stream_json_raises` | output_format="stream-json" → CliToolError with clear "deferred" message |
| 13 | `test_retry_no_retry_default` | on_error={} with failing tool → 1 attempt, raises |
| 14 | `test_retry_max_attempts_2_succeeds_on_2nd` | on_error={retry: {max_attempts: 2}} with /bin/false (always fails) → 2 attempts, then raises |
| 15 | `test_retry_exponential_backoff` | mock time.sleep, verify exponential multiplier |
| 16 | `test_retry_fixed_backoff` | mock time.sleep, verify fixed delay |
| 17 | `test_substitute_template_replaces_placeholders` | _substitute_template with {prompt}, {working_dir}, {session_id} |
| 18 | `test_substitute_template_unknown_placeholder_kept` | _substitute_template with {unknown} → kept as-is |
| 19 | `test_parse_duration_known_units` | "30s"=30, "5m"=300, "1h"=3600, "1d"=86400 |
| 20 | `test_parse_duration_invalid_raises` | "garbage" → ValueError |
| 21 | `test_run_cli_tool_full_success_path` | End-to-end: _mock_echo + output_format=text → result dict with status=success, parsed.text, tool_metadata |
| 22 | `test_run_cli_tool_with_session_id_resume` | resume=true + session_id → args get the session_id_flag prepended |

**Use the same `from v2.tests import fixtures as cf` pattern as test_parallel.py / test_workflow_validator.py.** Use `unittest.mock.patch("time.sleep")` for the backoff tests.

---

## File changes planned

| File | Change | LOC est |
|---|---|---|
| `pantheon/conductor/v2/engine.py` (modify) | WorkflowStep cli_tool fields (3 lines + docstring); _step_from_dict loader (3 lines); _execute_step dispatch (3 lines: elif cli_tool); _exec_cli_tool method (~50 lines) | ~60 |
| `pantheon/conductor/v2/cli_tool.py` (NEW) | Exceptions (3 classes), ToolRegistration dataclass, resolve_tool + _substitute_template + _parse_duration + _run_subprocess + _parse_output + run_cli_tool | ~300 |
| `pantheon/conductor/v2/tests/test_cli_tool.py` (NEW) | 22 tests | ~400 |
| **Total** | | **~760 LOC** |

**Engine code change is small (~60 LOC, additive). The bulk is the new cli_tool.py module + tests.**

---

## Validation (your exit criteria)

```bash
# 1. Targeted: 22 new tests pass
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_cli_tool.py -v
# Expect: 22/22 pass

# 2. Full v2 suite still green (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 277/1-skip/0-fail (was 255/1/0 after 4.6; +22 cli_tool tests)

# 3. Hand-test: a workflow with a cli_tool step loads and dispatches (against the mock tool)
python3 -c "
from pathlib import Path
from conductor.v2.engine import Workflow
import yaml
wf_yaml = yaml.safe_load('''
workflow:
  id: cli-test
  name: CLI Test
  version: '1.0.0'
  steps:
    - id: mock-run
      type: cli_tool
      tool: _mock_echo
      tool_input:
        prompt: 'hello-from-cli'
      timeout: 30s
      output: cli-output
''')
wf = Workflow.from_dict(wf_yaml, Path('test.yaml'))
print(f'OK: workflow {wf.id} loaded with {len(wf.steps)} steps')
print(f'  step {wf.steps[0].id!r}: type={wf.steps[0].type}, tool={wf.steps[0].tool!r}, input={wf.steps[0].tool_input}')
"
# Expect: OK: workflow cli-test loaded with 1 steps
#         step 'mock-run': type=cli_tool, tool='_mock_echo', input={'prompt': 'hello-from-cli'}

# 4. Hand-test: unknown tool raises CliToolNotFoundError
python3 -c "
from conductor.v2.cli_tool import resolve_tool
try:
    resolve_tool('claude-code')
    print('FAIL: should have raised')
except Exception as e:
    print(f'OK: {type(e).__name__}: {e}')
"
# Expect: OK: CliToolNotFoundError: tool 'claude-code' is not registered. Brief 1 ships with only the _mock_echo placeholder...
```

## Verification (Brief 3 will run)

- All 22 tests pass
- Full v2 suite: 277/1-skip/0-fail (was 255/1/0 after 4.6; +22)
- The 3 hand-tests above work as expected
- Existing 5 production workflows still load and dispatch (no regression on `god_dispatch` or `nats_publish` paths)
- Plan YAML flip: Step 4.9 → DONE (Brief 3)

## Reversibility

**Low cost.** Revert the WorkflowStep cli_tool fields + _step_from_dict loader + _execute_step dispatch + delete `_exec_cli_tool` method. Delete `cli_tool.py`. Delete `test_cli_tool.py`. **Zero data state changes. No existing workflows use the new step type.**

---

## Reference files

- **Plan YAML:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (Step 4.9 pending, current_step: 4.9.briefs.brief_1_of_3)
- **Spec (full):** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` (26.5K, Thoth v1.0.0)
- **Spec §2.1:** `cli_tool` step type YAML shape
- **Spec §4:** Tool registration (cli_tools.yaml format — Brief 2 will build this)
- **Spec §7.3:** Step spec — `cli_tool` field reference
- **Spec §9:** 8 open questions (all locked per the 2026-06-16-step-4.7 decision log)
- **Engine WorkflowStep:** `~/pantheon/conductor/v2/engine.py:496-512` (mirror the existing field pattern)
- **Engine _execute_step dispatch:** `~/pantheon/conductor/v2/engine.py:952-958` (the if/elif/else)
- **Engine _exec_nats_publish:** `~/pantheon/conductor/v2/engine.py:980-1020` (reference pattern for error handling + state record)
- **Engine _parse_duration:** grep for `_parse_duration` in engine.py (reuse the existing helper for timeouts)
- **Test fixture pattern:** mirror `test_parallel.py` (uses `from v2.tests import fixtures as cf` + `MockRun` / `queue_run`)
- **Operator decisions:** `~/pantheon/shared/decisions/2026-06-16-step-4.7.md` (locked Q1-Q8 from spec §9)

## Open questions for Marvin (resolve before/during implementation)

1. **Should `_exec_cli_tool` use `asyncio.create_subprocess_exec` directly instead of `run_in_executor` wrapping sync `run_cli_tool`?** My recommendation: stick with the sync wrapper (simpler, easier to test, no async-subprocess quirks). The `run_in_executor` overhead is negligible for long-running tools (4h timeouts).

2. **Should the `_mock_echo` placeholder be more sophisticated?** For tests that need multiple steps, a `_mock_sequential` tool that captures output to a file would be useful. My recommendation: keep `_mock_echo` simple for Brief 1; Brief 2 can add more sophisticated mocks when needed for the tool registration tests.

3. **The `tool_input` field name vs `input` field name** — Thoth's spec uses `input: prompt: ...` but the engine's existing `WorkflowStep.input` field is for god_dispatch (it's a different concept). I propose `tool_input` to avoid collision. Brief 2's `cli_tools.yaml` registration can use the spec's `input: prompt: ...` form at the workflow YAML level; the engine just maps it to `step.tool_input` internally. Confirm or push back.

4. **What happens if a cli_tool step has `gates` defined?** Per the spec, the engine runs the gates against the parsed output. For Brief 1, I'll wire the existing gate runner; if any gate fails, the step is marked failed and on_error.retry is consulted. Document this in the test for `test_run_cli_tool_with_gate_failure` (test #23, beyond the 12 minimum).

## What comes after this brief

**Brief 2 of 3** (Marvin continues):
- Build `pantheon/conductor/config/cli_tools.yaml` with v1 tool set (claude-code, codex, gemini-cli)
- Replace the `_mock_echo` placeholder in `cli_tool.py:resolve_tool` with a real config loader
- Add config-loading tests (≥6 tests)
- Hand-test against a real `claude` binary if available, otherwise a mock script

**Brief 3 of 3** (verification + closure):
- Run full v2 suite, expect 283+/1-skip/0-fail
- Hand-test the 4-agent worked-example workflow shape (real `claude-x-codex-marvin-hephaestus-feature.yaml`) — even if the CLI tools can't actually run end-to-end, validate the YAML parses
- Plan YAML flip: Step 4.9 → DONE, header current_step → 4.final
- Decision log entry: closure + measured test count

**Step 4.final** (Phase 4 closure review) — runs after 4.9 SHIPs cleanly. 5-section review at `reviews/phase-4-quarantine-sovereign-final-review.md`. The two latent engine bugs from Step 4.8 (declared_output parameter + single-branch sub-workflow premature status) get fixed or explicitly deferred.
