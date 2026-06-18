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
        # A.2 (2026-06-16): stream-json is now unlocked for the
        # NON-streaming path. The streaming path (_run_cli_tool_streaming)
        # builds `parsed` itself from collected events; this branch
        # is hit when a tool with output_format=stream-json runs
        # WITHOUT `stream=True` — in that case the captured stdout
        # IS a JSON document (the tool's last emission), so we
        # parse it as such. If it's not valid JSON, we surface the
        # exact first-200-chars for debugging.
        try:
            return {"stream_json": json.loads(stdout) if stdout.strip() else {}}
        except json.JSONDecodeError as e:
            raise CliToolError(
                f"output_format=stream-json but stdout is not valid JSON: {e}. "
                f"Either the tool is not emitting stream-json OR you forgot "
                f"to pass stream=True to run_cli_tool. "
                f"First 200 chars: {stdout[:200]!r}"
            ) from e
    raise CliToolError(f"unknown output_format: {output_format!r}")


def run_cli_tool(
    tool_reg: ToolRegistration,
    input_dict: dict[str, Any],
    on_error: dict[str, Any],
    timeout_s: float,
    *,
    live_stream: Optional["LiveStreamServer"] = None,
    workflow_id: Optional[str] = None,
    step_id: Optional[str] = None,
    stream: bool = False,
    host: str = "0.0.0.0",
    port: int = 7700,
) -> dict[str, Any]:
    """Run a cli_tool step. Synchronous (called from engine via run_in_executor).

    Per Thoth's spec §2.1:
      1. Spawn subprocess
      2. Capture output
      3. Parse output per output_format
      4. If exit non-zero, apply on_error.retry policy
      5. Return the structured output (or raise on final failure)

    A.2 streaming params (all keyword-only, all optional):
      - live_stream: LiveStreamServer instance. When set AND `stream=True`,
        line-buffered output is broadcast as StreamEvent messages during
        the run. When None or stream=False, the synchronous
        `_run_subprocess` path is used unchanged (full back-compat).
      - workflow_id / step_id: routing keys for the live_stream fan-out
        (only used when streaming).
      - stream: explicit opt-in to the streaming path. Defaults False so
        non-streaming tools are zero-overhead.
      - host / port: used to build the `stream_url` field in the result
        when streaming is enabled. Lets the GUI subscribe without
        needing to know the server's bind address (default: 0.0.0.0:7700
        per spec §3; tests pass 127.0.0.1 + a random port).

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
    stdout, stderr, parsed, tool_metadata, [stream_url]). On unrecoverable
    failure, raises CliToolError (or one of its subclasses).
    """
    retry_cfg = on_error.get("retry", {}) or {}
    max_attempts = max(1, int(retry_cfg.get("max_attempts", 1)))  # default: no retry
    backoff = retry_cfg.get("backoff", "none")  # none | fixed | exponential
    backoff_base_seconds = float(retry_cfg.get("backoff_base_seconds", 30))

    # A.2 (2026-06-16): streaming dispatch. When the caller passes
    # `stream=True` AND a `live_stream` server, we take the async
    # streaming path that broadcasts each NDJSON line as a StreamEvent.
    # Otherwise we use the synchronous _run_subprocess path (the
    # Brief 1/2 behavior) — zero overhead for the 99% of tools that
    # don't stream.
    #
    # `_run_subprocess_stream` is async-only; we run it on the same
    # default ThreadPoolExecutor that wraps this synchronous function.
    # The engine calls run_cli_tool via loop.run_in_executor, so the
    # executor thread is already detached from the event loop — we
    # cannot `await` directly. We bridge with asyncio.run_coroutine_threadsafe
    # on a captured loop, or fall back to a fresh asyncio.run if
    # no loop is set (e.g. tests that call run_cli_tool directly
    # without a running engine).
    if stream and live_stream is not None and workflow_id and step_id:
        return _run_cli_tool_streaming(
            tool_reg, input_dict, on_error, timeout_s,
            live_stream=live_stream,
            workflow_id=workflow_id,
            step_id=step_id,
            host=host,
            port=port,
            max_attempts=max_attempts,
            backoff=backoff,
            backoff_base_seconds=backoff_base_seconds,
        )

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


# ---------------------------------------------------------------------------
# A.2 (2026-06-16): NDJSON streaming path
# ---------------------------------------------------------------------------
#
# When the caller passes `stream=True` and a `live_stream` server,
# run_cli_tool dispatches to `_run_cli_tool_streaming` (below), which
# in turn awaits `_run_subprocess_stream` on a fresh asyncio loop.
# Each line of stdout is parsed as NDJSON; the resulting dict is
# mapped to a StreamEvent (via `_ndjson_to_event`) and broadcast on
# the live_stream server. The final aggregated stdout is also parsed
# as JSON for the `parsed` field in the result.
#
# Spec reference: conductor-cli-orchestration.md §3 (event table) +
# §2.1.4 (stream-json output format).
#
# Design constraint (from the brief): streaming MUST NOT block the
# synchronous _run_subprocess path. The two paths share ZERO code
# (different functions, different process models) — non-streaming
# tools use _run_subprocess unchanged.

# Map a tool's stream_format to a parser. The parsers convert one
# NDJSON line into a (event, data) tuple, where event is one of the
# 8 spec §3 event types and data is the event-specific payload dict.
#
# When stream_format is None or unknown, we fall back to `_ndjson_passthrough`
# which accepts any NDJSON line with a "type" or "event" field and
# broadcasts it as-is. This is the "generic NDJSON" path that
# custom tools (e.g. a custom test-runner script) can use without
# registering a specific stream_format.
_STREAM_PARSERS: dict[str, str] = {
    "claude-stream-json": "_ndjson_from_claude",
    "codex-stream-json": "_ndjson_from_codex",
}


def _ndjson_passthrough(line: dict) -> tuple[str, dict]:
    """Generic NDJSON → (event, data) for tools without a known stream_format.

    Accepts:
      - {"type": "<event>", ...data} → (type, data)  (claude style)
      - {"event": "<event>", ...data} → (event, data)  (our style)
      - {"msg": "<text>"} → ("output", {"text": msg, "is_final": False})

    The result always fits the spec §3 event-type vocabulary. Unknown
    event types are coerced to "output" with the whole dict as data.
    """
    if not isinstance(line, dict):
        return ("output", {"text": str(line), "is_final": False})
    # Prefer "type" (claude/codex style), fall back to "event" (ours)
    ev = line.get("type") or line.get("event") or "output"
    if ev not in EVENT_TYPES:
        ev = "output"
    data = {k: v for k, v in line.items() if k not in ("type", "event")}
    return (ev, data)


def _ndjson_from_claude(line: dict) -> tuple[str, dict]:
    """Parse one line of claude-code's stream-json output.

    Claude's stream-json format (per Anthropic's CLI docs):
      {"type": "content_block_start", ...}
      {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
      {"type": "content_block_stop", ...}
      {"type": "message_start", ...}
      {"type": "message_delta", "delta": {"stop_reason": "..."}}
      {"type": "message_stop", ...}
      {"type": "tool_use", "name": "Bash", "input": {...}}

    We map:
      - content_block_delta with text_delta → ("output", {text, is_final=False})
      - tool_use → ("tool_call", {tool_name, args})
      - message_stop → ("done", {status: "success"})
      - other → ("thinking", {text: "<the line as text>"})
    """
    if not isinstance(line, dict):
        return _ndjson_passthrough(line)
    t = line.get("type", "")
    if t == "content_block_delta":
        delta = line.get("delta") or {}
        if delta.get("type") == "text_delta":
            return ("output", {
                "text": delta.get("text", ""),
                "is_final": False,
            })
        return ("thinking", {"text": json.dumps(line)})
    if t == "tool_use":
        return ("tool_call", {
            "tool_name": line.get("name", "unknown"),
            "args": line.get("input") or {},
            "duration_ms": 0,
            "result": None,
        })
    if t == "message_stop":
        return ("done", {
            "status": "success",
            "stop_reason": (line.get("message") or {}).get("stop_reason"),
        })
    if t == "error":
        return ("error", {
            "message": line.get("error", {}).get("message", str(line)),
            "recoverable": False,
        })
    # Default: thinking
    return ("thinking", {"text": json.dumps(line)})


def _ndjson_from_codex(line: dict) -> tuple[str, dict]:
    """Parse one line of codex's stream-json output.

    Codex's stream-json format (per OpenAI's CLI docs):
      {"type": "thread.started", "thread_id": "..."}
      {"type": "turn.started"}
      {"type": "item.created", "item": {"type": "command_execution", "command": "..."}}
      {"type": "item.updated", "item": {...}}
      {"type": "item.completed", "item": {...}}
      {"type": "turn.completed", "usage": {...}}

    We map:
      - item.created/updated/completed with command_execution → command_run
      - turn.completed → done
      - other → thinking
    """
    if not isinstance(line, dict):
        return _ndjson_passthrough(line)
    t = line.get("type", "")
    if t == "turn.completed":
        return ("done", {"status": "success"})
    if t in ("item.created", "item.updated", "item.completed"):
        item = line.get("item") or {}
        item_type = item.get("type", "")
        if item_type == "command_execution":
            cmd = item.get("command") or ""
            return ("command_run", {
                "command": " ".join(cmd) if isinstance(cmd, list) else str(cmd),
                "exit_code": item.get("exit_code"),
                "stdout_preview": (item.get("output") or "")[:500],
                "stderr_preview": "",
                "duration_ms": item.get("duration_ms", 0),
            })
        if item_type == "file_edit":
            return ("file_edit", {
                "path": item.get("path", ""),
                "diff_summary": item.get("diff", "")[:200],
                "lines_changed": item.get("lines_changed", 0),
            })
        if item_type == "file_create":
            return ("file_create", {
                "path": item.get("path", ""),
                "size_bytes": item.get("size_bytes", 0),
            })
        return ("thinking", {"text": json.dumps(line)})
    if t in ("thread.started", "turn.started"):
        return ("thinking", {"text": t})
    if t == "error":
        return ("error", {
            "message": line.get("message", str(line)),
            "recoverable": False,
        })
    return ("thinking", {"text": json.dumps(line)})


def _ndjson_to_event(tool_reg: ToolRegistration, line: dict) -> "StreamEvent":
    """Convert one parsed NDJSON line into a StreamEvent.

    Selects the parser based on `tool_reg.stream_format`. If unset
    or unknown, uses `_ndjson_passthrough` so any tool emitting NDJSON
    with a "type" or "event" field just works.
    """
    fmt = tool_reg.stream_format
    if fmt == "claude-stream-json":
        event, data = _ndjson_from_claude(line)
    elif fmt == "codex-stream-json":
        event, data = _ndjson_from_codex(line)
    else:
        event, data = _ndjson_passthrough(line)
    # ts is filled by the broadcast path; we still set it here so
    # standalone uses (e.g. tests) have a reasonable timestamp.
    from .live_stream import StreamEvent
    from datetime import datetime, timezone
    return StreamEvent(
        ts=datetime.now(timezone.utc).isoformat(),
        workflow_id="",  # filled by the caller
        step_id="",      # filled by the caller
        event=event,
        data=data,
    )


async def _run_subprocess_stream(
    tool_reg: ToolRegistration,
    input_dict: dict,
    timeout_s: float,
    on_line,
) -> tuple[int, str, str, float]:
    """Async line-buffered subprocess invocation.

    Returns (exit_code, accumulated_stdout, accumulated_stderr, duration).
    For each line of stdout, calls `on_line(line: str)` — the caller
    is responsible for parsing and broadcasting. The line is passed
    WITHOUT the trailing newline.

    Differs from _run_subprocess:
      - Uses asyncio.create_subprocess_exec (not subprocess.run)
      - Reads stdout line-by-line via streams[0].readline() (not capture)
      - Honors the same timeout via asyncio.wait_for
      - Returns the full accumulated stdout/stderr (so the caller can
        also parse the final state for the `parsed` field in the result)

    Errors (binary not found, timeout) map to the same exceptions as
    _run_subprocess — CliToolNotFoundError, CliToolTimeoutError. This
    keeps the engine's _exec_cli_tool error handling uniform.
    """
    import asyncio
    prompt = input_dict.get("prompt", "")
    working_dir = input_dict.get("working_dir", os.getcwd())
    extra_env = input_dict.get("env", {}) or {}
    session_id = input_dict.get("session_id")
    resume = bool(input_dict.get("resume", False))

    env = dict(os.environ)
    env.update(tool_reg.env)
    env.update(extra_env)

    substitutions = {
        "prompt": prompt,
        "working_dir": working_dir,
        "session_id": session_id or "",
    }
    args = _substitute_template(tool_reg.args_template, substitutions)
    if resume and session_id and tool_reg.session_id_flag:
        args = [tool_reg.session_id_flag, session_id] + args

    stdin_payload: Optional[str] = None
    if tool_reg.stdin_prompt:
        stdin_payload = prompt

    started = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            tool_reg.command, *args,
            cwd=working_dir,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            stdin=asyncio.subprocess.PIPE if stdin_payload else None,
        )
    except FileNotFoundError as e:
        raise CliToolNotFoundError(
            f"tool {tool_reg.name!r} binary not found: {tool_reg.command!r}. "
            f"Check that the tool is installed and on $PATH."
        ) from e

    # Write stdin if needed, then close it so the subprocess can read EOF.
    if stdin_payload is not None and proc.stdin is not None:
        try:
            proc.stdin.write(stdin_payload.encode("utf-8"))
        finally:
            proc.stdin.close()

    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []

    async def drain(stream, sink):
        """Read one stream line-by-line, accumulate, call on_line per line."""
        if stream is None:
            return
        while True:
            raw = await stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            sink.append(line)
            try:
                on_line(line)
            except Exception as e:  # don't let one bad line kill the run
                LOG.debug(f"on_line handler raised: {e}")

    try:
        # Wait for both streams to drain + the process to exit, all
        # bounded by the overall timeout. If timeout fires, kill the
        # process and raise.
        await asyncio.wait_for(
            asyncio.gather(
                drain(proc.stdout, stdout_chunks),
                drain(proc.stderr, stderr_chunks),
                proc.wait(),
            ),
            timeout=timeout_s,
        )
        exit_code = await proc.wait()
    except asyncio.TimeoutError as e:
        proc.kill()
        try:
            await proc.wait()
        except Exception:
            pass
        duration = time.monotonic() - started
        raise CliToolTimeoutError(
            f"tool {tool_reg.name!r} timed out after {timeout_s}s"
        ) from e

    duration = time.monotonic() - started
    return (exit_code, "\n".join(stdout_chunks), "\n".join(stderr_chunks), duration)


def _run_cli_tool_streaming(
    tool_reg: ToolRegistration,
    input_dict: dict,
    on_error: dict,
    timeout_s: float,
    *,
    live_stream,
    workflow_id: str,
    step_id: str,
    host: str,
    port: int,
    max_attempts: int,
    backoff: str,
    backoff_base_seconds: float,
) -> dict:
    """Sync wrapper around the async streaming path.

    Called from the synchronous `run_cli_tool` (which is itself
    called from the engine via run_in_executor on a thread). We
    need an event loop to drive the async streaming coroutine.
    Strategy: try to use the running loop if there is one
    (`asyncio.get_running_loop`); if not, create a fresh one via
    `asyncio.new_event_loop()` and tear it down on exit. The
    latter case is the common one for engine-orchestrated runs.
    """
    import asyncio
    from .live_stream import StreamEvent, stream_url

    url = stream_url(host, port, workflow_id, step_id)

    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        # Each attempt gets a fresh per-step list of events for
        # the final `parsed` aggregation. Per-line events flow to
        # the live_stream live; the aggregated list is the final
        # result (mirrors how _parse_output collects text).
        collected_events: list[StreamEvent] = []

        def on_line(line: str) -> None:
            """Parse one NDJSON line, broadcast it, append to collected."""
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Not NDJSON — treat as a thinking event so the GUI
                # sees raw output even if the tool forgot to format
                # it. Per spec §3 "thinking" is between-tool-calls.
                ev = StreamEvent.now(
                    workflow_id, step_id, "thinking",
                    {"text": line},
                )
            else:
                ev = _ndjson_to_event(tool_reg, obj)
                # Re-stamp the workflow/step ids (the parser returns
                # empty strings; the broadcast path needs them).
                ev.workflow_id = workflow_id
                ev.step_id = step_id
            collected_events.append(ev)
            # Schedule broadcast on the loop. We can't await here
            # (on_line is sync), so use broadcast_sync which handles
            # the no-loop case gracefully.
            live_stream.broadcast_sync(ev)

        try:
            # Drive the async streaming coroutine. We use a fresh
            # event loop if there isn't one already running on this
            # thread (the common case — run_cli_tool is called from
            # run_in_executor, which is a worker thread).
            try:
                asyncio.get_running_loop()
                # If we get here, we're inside an async context. We
                # can't `await` (we're sync), so fall through to the
                # new-loop path.
                own_loop = True
            except RuntimeError:
                own_loop = False

            if own_loop:
                # Shouldn't happen in practice — run_in_executor runs
                # on a thread without a loop. If it does, we'd need
                # nest_asyncio or similar. For now, raise a clear
                # error so the bug is obvious.
                raise CliToolError(
                    "run_cli_tool_streaming called from inside a running "
                    "event loop; this is a bug (the streaming path "
                    "requires a fresh loop)"
                )

            loop = asyncio.new_event_loop()
            try:
                exit_code, stdout, stderr, duration = loop.run_until_complete(
                    _run_subprocess_stream(tool_reg, input_dict, timeout_s, on_line)
                )
            finally:
                loop.close()

            if exit_code == 0:
                # Build the parsed field from collected events. For
                # stream-json output_format, we use the event list
                # itself (the spec asks for "streamed events", not
                # a final JSON object). For text/json, the captured
                # stdout is the source of truth.
                if tool_reg.output_format == "stream-json":
                    parsed = {
                        "events": [e.to_json() for e in collected_events],
                        "streamed": True,
                    }
                elif tool_reg.output_format == "json":
                    try:
                        parsed = json.loads(stdout) if stdout.strip() else {}
                    except json.JSONDecodeError as e:
                        raise CliToolError(
                            f"tool output is not valid JSON: {e}. "
                            f"First 200 chars: {stdout[:200]!r}"
                        ) from e
                else:
                    parsed = {"text": stdout}

                return {
                    "status": "success",
                    "exit_code": exit_code,
                    "duration_seconds": duration,
                    "stdout": stdout,
                    "stderr": stderr,
                    "parsed": parsed,
                    "stream_url": url,
                    "tool_metadata": {
                        "tool": tool_reg.name,
                        "command": tool_reg.command,
                        "attempts": attempt,
                        "streamed": True,
                    },
                }

            LOG.warning(
                f"tool {tool_reg.name!r} attempt {attempt}/{max_attempts} "
                f"failed with exit_code={exit_code}: stderr={stderr[:200]!r}"
            )
            last_error = CliToolError(
                f"tool {tool_reg.name!r} exited with code {exit_code}: {stderr[:500]}"
            )
        except (CliToolTimeoutError, CliToolNotFoundError) as e:
            raise

        # Backoff (same semantics as the sync path)
        if attempt < max_attempts:
            if backoff == "fixed":
                time.sleep(backoff_base_seconds)
            elif backoff == "exponential":
                time.sleep(backoff_base_seconds * (2 ** (attempt - 1)))

    final_failure = on_error.get("on_final_failure", "fail_workflow")
    if final_failure == "escalate_hermes":
        LOG.error(
            f"tool {tool_reg.name!r} exhausted {max_attempts} attempts; "
            f"escalating to Hermes"
        )
    else:
        LOG.error(
            f"tool {tool_reg.name!r} exhausted {max_attempts} attempts; "
            f"workflow will be marked failed"
        )
    raise last_error or CliToolError(
        f"tool {tool_reg.name!r} failed after {max_attempts} attempts"
    )


# Resolve the forward reference: cli_tool imports from live_stream at
# the bottom of this module to avoid a circular import (live_stream
# doesn't import cli_tool). The `from __future__ import annotations`
# at the top of this file means the `Optional["LiveStreamServer"]`
# hint in run_cli_tool's signature is never evaluated, so this
# import is just for the type-checking convenience.
from .live_stream import LiveStreamServer  # noqa: E402
