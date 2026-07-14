"""Conductor v2 `cli_tool` step executor.

Companion to engine.py — implements the subprocess invocation for
cli_tool steps per Thoth's spec §2.1, §4, and §7.3
(`athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md`).

The engine dispatches to `_exec_cli_tool` which calls `run_cli_tool`
(synchronous) wrapped in asyncio via `run_in_executor`. The synchronous
core keeps subprocess handling straightforward (no async-subprocess
quirks) and the `run_in_executor` overhead is negligible for long-running
tools (4h timeouts per spec §2.1).

Tool registration (from `cli_tools.yaml`) is loaded by Brief 2. For
Brief 1, the `resolve_tool()` function returns a hardcoded `_mock_echo`
placeholder when no registration is found, so the engine can be tested
without Brief 2 being shipped. Brief 2 replaces the placeholder with the
real config loader.

Spec scope implemented in this brief:
  - §2.1.1: spawn subprocess in working_dir
  - §2.1.2: prompt delivery via args (and stdin_prompt flag)
  - §2.1.3: capture stdout/stderr/exit_code/duration
  - §2.1.4: structured output (text | json) — stream-json deferred
  - §2.1.5: WebSocket live observability — DEFERRED to separate brief
  - §2.1.6: gate integration — handled at the engine layer (no change here)
  - §2.1.7: on_error retry policy with backoff (none/fixed/exponential)
  - §4:    ToolRegistration dataclass (full schema; loader is Brief 2)
  - §7.3:  on_error config shape {retry: {max_attempts, backoff, ...}}
  - §9 Q8: tool binary missing → fail fast (CliToolNotFoundError, no retry)
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

try:
    import yaml  # PyYAML — required by load_tools_config() (Brief 2, 2026-06-16)
except ImportError:  # pragma: no cover — only hit in stripped-down envs
    yaml = None  # type: ignore[assignment]

LOG = logging.getLogger("conductor.v2.cli_tool")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CliToolError(Exception):
    """Raised when a cli_tool step fails for any reason (non-zero exit,
    timeout, malformed output, etc.). The error message includes the
    tool name and the failure reason for clear operator feedback.
    """
    pass


class CliToolNotFoundError(CliToolError):
    """Raised when the requested tool's binary is not on $PATH or the
    tool is not registered. Per Thoth's spec §9 Q8: fail fast with a
    clear error, no fallback, no retry.
    """
    pass


class CliToolTimeoutError(CliToolError):
    """Raised when the tool subprocess exceeds the step's timeout.
    Per spec §2.1.7 + §9 Q8: timeouts are fail-fast (no retry).
    """
    pass


class CliToolConfigError(CliToolError):
    """Raised when cli_tools.yaml is malformed — missing required fields,
    invalid output_format, missing 'cli_tools' top-level key, or file not
    readable. Distinct from CliToolNotFoundError so callers / tests can
    differentiate "the YAML is broken" from "the binary isn't installed".
    """
    pass


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

@dataclass
class ToolRegistration:
    """The registration of a single CLI tool (per Thoth's spec §4).

    For Brief 1, registrations live in the hardcoded `_DEFAULT_TOOLS` dict
    below. Brief 2 will load these from `conductor/config/cli_tools.yaml`
    (the engine reads that file at startup). The dataclass shape is
    stable across both loaders — Brief 2 only changes how instances are
    constructed, not what fields they carry.
    """
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


# Module-level registry: name -> ToolRegistration.
#
# Populated by:
#   1. Module import (this dict) — ships with _mock_echo for back-compat
#      with Brief 1 tests that don't load a config.
#   2. load_tools_config(path) at engine startup — reads cli_tools.yaml.
#   3. register_tool(reg) at runtime — used by tests, dynamic tool loading.
#
# The dict is named _REGISTRY (Brief 2) and _DEFAULT_TOOLS is a back-compat
# alias. New code should reference _REGISTRY; existing Brief 1 test
# imports of _DEFAULT_TOOLS still work.
_REGISTRY: dict[str, ToolRegistration] = {
    "_mock_echo": ToolRegistration(
        name="_mock_echo",
        command="echo",
        args_template=["{prompt}"],
        output_format="text",
        timeout_default="30s",
    ),
}

# Back-compat alias (Brief 1 tests reference this name directly).
_DEFAULT_TOOLS = _REGISTRY


def resolve_tool(name: str) -> ToolRegistration:
    """Look up a tool by name in the module-level registry.

    The registry is populated at module import with _mock_echo, then
    expanded at engine startup by load_tools_config() (which reads
    pantheon/conductor/config/cli_tools.yaml and adds the v1 tool set:
    claude-code, codex, gemini-cli).

    Raises CliToolNotFoundError if the tool isn't registered. The error
    message is operator-friendly: it tells them which tool was missing,
    lists the currently-registered tools, and points at the YAML config
    that should be edited to add a new one.
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    raise CliToolNotFoundError(
        f"tool {name!r} is not registered. "
        f"Available tools: {sorted(_REGISTRY.keys())}. "
        f"Check pantheon/conductor/config/cli_tools.yaml or call register_tool() to "
        f"register it at runtime."
    )


def register_tool(reg: ToolRegistration) -> None:
    """Add or replace a tool in the registry. Used by load_tools_config()
    and by tests that need to register custom mock tools (e.g. /bin/false,
    /bin/sleep) without depending on _mock_echo semantics.
    """
    _REGISTRY[reg.name] = reg


def unregister_tool(name: str) -> None:
    """Remove a tool from the registry. Tests use this to clean up
    injected mocks so they don't leak into other tests. No-op if the
    tool isn't registered.
    """
    _REGISTRY.pop(name, None)


# ---------------------------------------------------------------------------
# Config loader (Brief 2, 2026-06-16)
# ---------------------------------------------------------------------------

# Valid output_format values per Thoth's spec §4. stream-json requires the
# WebSocket live-observability stream (deferred) and is accepted here as
# a valid value so the YAML can be loaded, but _parse_output still raises
# on it (Brief 1 behavior — see _parse_output below).
VALID_OUTPUT_FORMATS: set[str] = {"json", "text", "stream-json"}
REQUIRED_TOOL_FIELDS: set[str] = {"command", "args_template"}


def load_tools_config(path: "Path | str") -> list[ToolRegistration]:
    """Load tools from a YAML config file. Returns the list of registered
    tools (in declaration order). Validates required fields and
    output_format values; raises CliToolConfigError on malformed entries.

    Per Thoth's spec §4 (conductor-cli-orchestration.md):
    'Adding new tools later: claude-code-web, codex-remote, custom
    internal tools, etc. The cli_tool step type is tool-agnostic; what
    runs is determined by the registration.'

    Idempotent: calling load_tools_config twice replaces the registry
    entries (does not duplicate). Tools NOT listed in the config are
    left in the registry unchanged (e.g. _mock_echo is always present
    because it's seeded in _REGISTRY; a second load just overwrites the
    tools it lists).

    Raises:
        CliToolConfigError — file missing, top-level 'cli_tools' key
            missing, a tool entry is not a mapping, required fields
            missing, or output_format is not in VALID_OUTPUT_FORMATS.
    """
    p = Path(path)
    if yaml is None:
        raise CliToolConfigError(
            "PyYAML is not installed; cannot load cli_tools config. "
            "Install with `pip install pyyaml`."
        )
    if not p.exists():
        raise CliToolConfigError(
            f"cli_tools config not found: {p!r}. Create the file or "
            f"remove the load_tools_config() call from engine startup."
        )

    try:
        doc = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise CliToolConfigError(
            f"cli_tools config {p!r} is not valid YAML: {e}"
        ) from e

    if not isinstance(doc, dict) or "cli_tools" not in doc:
        raise CliToolConfigError(
            f"cli_tools config {p!r} missing top-level 'cli_tools' key. "
            f"See pantheon/conductor/config/cli_tools.yaml for the expected shape."
        )

    cli_tools_section = doc["cli_tools"]
    if not isinstance(cli_tools_section, dict):
        raise CliToolConfigError(
            f"cli_tools config {p!r}: 'cli_tools' must be a mapping, "
            f"got {type(cli_tools_section).__name__}."
        )

    registered: list[ToolRegistration] = []
    for name, entry in cli_tools_section.items():
        if not isinstance(entry, dict):
            raise CliToolConfigError(
                f"cli_tools config {p!r}: tool {name!r} entry is not a mapping"
            )

        missing = REQUIRED_TOOL_FIELDS - set(entry.keys())
        if missing:
            raise CliToolConfigError(
                f"cli_tools config {p!r}: tool {name!r} missing required fields: "
                f"{sorted(missing)}"
            )

        output_format = entry.get("output_format", "text")
        if output_format not in VALID_OUTPUT_FORMATS:
            raise CliToolConfigError(
                f"cli_tools config {p!r}: tool {name!r} has invalid output_format "
                f"{output_format!r}; must be one of {sorted(VALID_OUTPUT_FORMATS)}"
            )

        args_template = entry["args_template"]
        if not isinstance(args_template, list):
            raise CliToolConfigError(
                f"cli_tools config {p!r}: tool {name!r} args_template must be a list, "
                f"got {type(args_template).__name__}"
            )

        reg = ToolRegistration(
            name=name,
            command=entry["command"],
            args_template=list(args_template),
            output_format=output_format,
            timeout_default=entry.get("timeout_default", "4h"),
            session_id_flag=entry.get("session_id_flag"),
            stdin_prompt=bool(entry.get("stdin_prompt", False)),
            env=dict(entry.get("env", {}) or {}),
            max_concurrent=int(entry.get("max_concurrent", 1)),
            stream_format=entry.get("stream_format"),
        )
        register_tool(reg)
        registered.append(reg)

    return registered


# ---------------------------------------------------------------------------
# Subprocess invocation
# ---------------------------------------------------------------------------

def _substitute_template(template: list[str], substitutions: dict[str, str]) -> list[str]:
    """Replace {placeholder} tokens in the args_template.

    Unknown placeholders are left as-is (so a partial substitution
    doesn't silently drop content). Empty substitutions ("") substitute
    as the empty string, which is the expected behavior for absent
    {session_id} when not resuming.
    """
    result = []
    for arg in template:
        for key, value in substitutions.items():
            arg = arg.replace("{" + key + "}", str(value))
        result.append(arg)
    return result


def _parse_duration(s: str) -> float:
    """Parse '30m', '4h', '90s' into seconds.

    We validate against a local regex FIRST so garbage input raises
    ValueError (per the cli_tool contract — spec §2.1 timeout field
    must be a valid duration). The engine's _parse_duration returns
    1800.0 on garbage as a "soft default" for the broader system, but
    that would mask caller bugs in the cli_tool path. If validation
    passes, we delegate to the engine's parser for the actual value.
    """
    if isinstance(s, (int, float)):
        return float(s)
    # Local validation: must be «number» followed by optional unit
    m = re.match(r"^(\d+(?:\.\d+)?)([smhd]?)$", s.strip())
    if not m:
        raise ValueError(f"invalid duration: {s!r}")
    # Validation passed; delegate the actual conversion to the engine
    # if available (keeps cli_tool.py in lockstep with the rest of
    # the v2 codebase's unit handling). Fall back to the local parser
    # if the engine can't be imported (e.g. running cli_tool.py
    # standalone in a test or as a script).
    try:
        from .engine import _parse_duration as _engine_parse
        return _engine_parse(s)
    except ImportError:
        pass
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
    extra_env = input_dict.get("env", {}) or {}
    session_id = input_dict.get("session_id")
    resume = bool(input_dict.get("resume", False))

    # Merge env: process env + tool defaults + step overrides.
    # Step-specific overrides win last (e.g. ANTHROPIC_API_KEY per call).
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

    # If resume is true and the tool has a session_id_flag, inject the
    # session_id as a CLI flag prepended to the args (e.g. claude-code's
    # --resume <session_id> convention). Per spec §2.1 step 4.
    if resume and session_id and tool_reg.session_id_flag:
        args = [tool_reg.session_id_flag, session_id] + args

    # Optional stdin prompt (per spec §2.1 step 2): pipe prompt to stdin
    # rather than passing via args. Useful for tools that read long
    # prompts from stdin (e.g. `codex exec -`).
    stdin_payload: Optional[str] = None
    if tool_reg.stdin_prompt:
        stdin_payload = prompt

    started = time.monotonic()
    try:
        # Full argv = [command, *args_template_with_substitutions].
        # If resume is true and the tool has a session_id_flag, the
        # session_id_flag + session_id are prepended to the args (NOT
        # to the command) per spec §2.1 step 4.
        proc = subprocess.run(
            [tool_reg.command] + args,
            cwd=working_dir,
            env=env,
            capture_output=True,
            text=True,
            input=stdin_payload,
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
        # Binary not on $PATH (or path is wrong). Per spec §9 Q8:
        # fail fast with a clear error, no retry, no fallback.
        raise CliToolNotFoundError(
            f"tool {tool_reg.name!r} binary not found: {tool_reg.command!r}. "
            f"Check that the tool is installed and on $PATH."
        ) from e


def _parse_output(output_format: str, stdout: str, stderr: str) -> dict[str, Any]:
    """Parse the tool's stdout into a structured output per output_format.

    Per Thoth's spec §2.1.4. For Brief 1, we support:
      - text: stdout is a single string under the "text" key
      - json: stdout is parsed as JSON (empty stdout → empty dict)
      - stream-json: NOT supported in Brief 1 — raises with a clear
        "deferred" message because live observability requires the
        WebSocket layer (spec §3) which Brief 1 doesn't touch.
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
        # Brief 1 doesn't support stream-json (WebSocket observability
        # is Brief 2+ / separate). The user sees a clear "deferred"
        # message rather than a silent half-implementation.
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

    on_error shape (spec §7.3):
      {
        "retry": {
          "max_attempts": 2,
          "backoff": "exponential",     # none | fixed | exponential
          "backoff_base_seconds": 30,
        },
        "on_final_failure": "fail_workflow",  # fail_workflow | escalate_hermes
      }

    Returns a dict with the result schema (status, exit_code, duration,
    stdout, stderr, parsed, tool_metadata). On unrecoverable failure,
    raises CliToolError (or one of its subclasses).
    """
    retry_cfg = on_error.get("retry", {}) or {}
    max_attempts = max(1, int(retry_cfg.get("max_attempts", 1)))  # default: no retry
    backoff = retry_cfg.get("backoff", "none")  # none | fixed | exponential
    backoff_base_seconds = float(retry_cfg.get("backoff_base_seconds", 30))

    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            exit_code, stdout, stderr, duration = _run_subprocess(
                tool_reg, input_dict, timeout_s,
            )

            if exit_code == 0:
                # Success: parse output and return the structured result.
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

            # Non-zero exit: log + remember the error for potential retry.
            LOG.warning(
                f"tool {tool_reg.name!r} attempt {attempt}/{max_attempts} "
                f"failed with exit_code={exit_code}: stderr={stderr[:200]!r}"
            )
            last_error = CliToolError(
                f"tool {tool_reg.name!r} exited with code {exit_code}: {stderr[:500]}"
            )
        except (CliToolTimeoutError, CliToolNotFoundError) as e:
            # These don't retry — they fail fast per spec §9 Q8.
            # (Tool not found = wrong install; timeout = ran too long.
            # Neither is a transient condition that retry can fix.)
            raise

        # Apply backoff before the next attempt (only if there is one).
        # Backoff is intentionally AFTER the work, not before, so the
        # first attempt never waits.
        if attempt < max_attempts:
            if backoff == "fixed":
                time.sleep(backoff_base_seconds)
            elif backoff == "exponential":
                # attempt 1 → base * 1, attempt 2 → base * 2, ...
                time.sleep(backoff_base_seconds * (2 ** (attempt - 1)))
            # "none" → no sleep (default)

    # All attempts exhausted. Honor on_final_failure policy for logging;
    # the caller (engine) is responsible for actually aborting/escalating.
    final_failure = on_error.get("on_final_failure", "fail_workflow")
    if final_failure == "escalate_hermes":
        LOG.error(
            f"tool {tool_reg.name!r} exhausted {max_attempts} attempts; "
            f"escalating to Hermes (on_final_failure=escalate_hermes)"
        )
    else:
        # Default: fail_workflow. The engine's `_record_step_failure`
        # path will mark the workflow as failed.
        LOG.error(
            f"tool {tool_reg.name!r} exhausted {max_attempts} attempts; "
            f"workflow will be marked failed"
        )
    raise last_error or CliToolError(
        f"tool {tool_reg.name!r} failed after {max_attempts} attempts"
    )
