# Step 4.9 — cli_tools.yaml config + real tool registration

**Plan:** phase-4-quarantine-sovereign.yaml, Step 4.9
**Brief 2 of 3** (Brief 3 = verification + closure; **also includes a fix-up for Brief 1's missing test_cli_tool.py**)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Brief 1 status context:** cli_tool.py SHIPped (16.7K, 361+ lines, full module structure: ToolRegistration, resolve_tool, _substitute_template, _parse_duration, _run_subprocess, _parse_output, run_cli_tool). engine.py got WorkflowStep fields + _exec_cli_tool method + dispatch extension. **MISSING:** test_cli_tool.py was not written. This brief ships it as the first deliverable (fix-up), then builds the cli_tools.yaml config and the real tool registration on top.

**Operator instruction (locked 2026-06-16):** "go through 2, 3 and 4 in sequence" — this brief is the fix-up + cli_tools.yaml work combined, so Brief 2 doesn't ship a known gap. Brief 3 stays small (verification + plan flip).

---

## TL;DR

Three deliverables in this brief, all interlocking:

1. **MISSING from Brief 1 — write it now:** `pantheon/conductor/v2/tests/test_cli_tool.py` (22 tests, ~400 LOC). This is the Brief 1 carry-over. Without it, the v2 suite has 0 coverage for cli_tool. Brief 1 listed 22 specific tests; the brief is the contract.

2. **NEW: `pantheon/conductor/config/cli_tools.yaml`** — the v1 tool set registration per Thoth's spec §4. Three tools: `claude-code`, `codex`, `gemini-cli`. Each with `command`, `args_template`, `output_format`, `session_id_flag`, `env`, `timeout_default`, `max_concurrent`. Loaded at engine startup.

3. **MODIFY: `pantheon/conductor/v2/cli_tool.py:resolve_tool`** — replace the hardcoded `_mock_echo` placeholder with a real config loader that reads `cli_tools.yaml` at engine startup. Add `register_tool`, `unregister_tool` (already in the file from Brief 1, verify they work). Add a `load_tools_config(path)` function.

**Why bundled into one brief:** Brief 1's gap (missing tests) and Brief 2's main work (config loader) are tightly coupled — the tests need to verify the config loader. Splitting them creates a Brief 1.5 fix-up that doesn't add value. Operator instruction was "just get it done" — this brief does both.

---

## Deliverable 1: NEW `pantheon/conductor/v2/tests/test_cli_tool.py` (Brief 1 carry-over)

**22 tests as listed in Brief 1.** Mirror `test_parallel.py` and `test_workflow_validator.py` patterns. Use `unittest.mock.patch("time.sleep")` for the backoff tests. Use `from v2.tests import fixtures as cf` for shared fixtures.

| # | Test | What it covers |
|---|---|---|
| 1 | `test_run_subprocess_spawns_echo` | _mock_echo tool: spawns echo "{prompt}", captures stdout |
| 2 | `test_run_subprocess_working_dir` | working_dir is honored |
| 3 | `test_run_subprocess_env_merge` | tool_reg.env + tool_input.env merged correctly |
| 4 | `test_run_subprocess_timeout_raises` | timeout=0.1s with slow tool → CliToolTimeoutError |
| 5 | `test_run_subprocess_nonzero_exit` | /bin/false → CliToolError with stderr in message |
| 6 | `test_run_subprocess_binary_not_found` | tool_reg.command="/nonexistent" → CliToolNotFoundError |
| 7 | `test_resolve_tool_returns_mock_echo` | resolve_tool("_mock_echo") returns the placeholder (Brief 1 default) |
| 8 | `test_resolve_tool_unknown_raises` | resolve_tool("not-a-real-tool") → CliToolNotFoundError |
| 9 | `test_parse_output_text` | output_format="text" → {"text": "..."} |
| 10 | `test_parse_output_json_valid` | output_format="json" with valid JSON → parsed dict |
| 11 | `test_parse_output_json_invalid_raises` | output_format="json" with non-JSON → CliToolError |
| 12 | `test_parse_output_stream_json_raises` | output_format="stream-json" → CliToolError with "deferred" message |
| 13 | `test_retry_no_retry_default` | on_error={} with failing tool → 1 attempt, raises |
| 14 | `test_retry_max_attempts_2_failing_tool` | on_error={retry: {max_attempts: 2}} with /bin/false → 2 attempts, then raises |
| 15 | `test_retry_exponential_backoff` | mock time.sleep, verify exponential multiplier (1, 2, 4, 8 × base) |
| 16 | `test_retry_fixed_backoff` | mock time.sleep, verify fixed delay (3 × base) |
| 17 | `test_substitute_template_replaces_placeholders` | _substitute_template with {prompt}, {working_dir}, {session_id} |
| 18 | `test_substitute_template_unknown_placeholder_kept` | _substitute_template with {unknown} → kept as-is |
| 19 | `test_parse_duration_known_units` | "30s"=30, "5m"=300, "1h"=3600, "1d"=86400 |
| 20 | `test_parse_duration_invalid_raises` | "garbage" → ValueError |
| 21 | `test_run_cli_tool_full_success_path` | End-to-end: _mock_echo + output_format=text → result dict |
| 22 | `test_run_cli_tool_with_session_id_resume` | resume=true + session_id → args get session_id_flag prepended |

**Plus 4-6 NEW tests specific to Brief 2 (config loading):**

| # | Test | What it covers |
|---|---|---|
| 23 | `test_load_tools_config_reads_yaml` | load_tools_config(path) parses a real YAML with 2 tools |
| 24 | `test_load_tools_config_validates_required_fields` | missing `command` or `args_template` → CliToolConfigError |
| 25 | `test_load_tools_config_validates_output_format` | unknown output_format → CliToolConfigError |
| 26 | `test_resolve_tool_after_config_load_returns_registered` | After load_tools_config(cli_tools.yaml), resolve_tool("claude-code") returns the registered tool |
| 27 | `test_register_tool_and_unregister_tool_round_trip` | register_tool(reg) → resolve_tool(name) works; unregister_tool(name) → resolve_tool raises |
| 28 | `test_load_tools_config_handles_missing_file` | load_tools_config(Path("/nonexistent")) → CliToolConfigError with clear message |

**Total: 28 tests in test_cli_tool.py.**

## Deliverable 2: NEW `pantheon/conductor/config/cli_tools.yaml`

**Per Thoth's spec §4. v1 tool set: claude-code, codex, gemini-cli.**

```yaml
# Conductor v2 cli_tools registration
# 
# Per Thoth's spec §4 (~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md).
# Loaded at engine startup by load_tools_config(). New tools can be added
# by appending a tool entry below — no code change required.
#
# Fields per tool:
#   command:        Executable name (resolved via $PATH) or absolute path
#   args_template:  Argument template, with {prompt}, {working_dir}, {session_id} placeholders
#   output_format:  json | text | stream-json (json/text supported, stream-json deferred)
#   timeout_default: ISO duration (30s, 5m, 1h, 4h, 1d)
#   session_id_flag: Flag to pass session_id for resume (e.g. --resume for Claude Code)
#   stdin_prompt:   If true, prompt is piped to stdin instead of via args
#   env:            Default env vars (merged with step-level env; step wins)
#   max_concurrent: Per-workflow concurrency cap (1 = serial, 4 = up to 4 branches)
#   stream_format:  none | claude-stream-json | codex-stream-json (none for v1)

cli_tools:
  # Anthropic's Claude Code CLI
  # Usage: claude --prompt "..." --cwd <dir> or claude --resume <session_id> --prompt "..."
  claude-code:
    command: "claude"
    args_template: ["--prompt", "{prompt}", "--cwd", "{working_dir}"]
    output_format: "json"
    timeout_default: "4h"
    session_id_flag: "--resume"
    stdin_prompt: false
    env: {}
    max_concurrent: 2
    stream_format: "claude-stream-json"

  # OpenAI's Codex CLI
  # Usage: codex exec --prompt "..." --working-dir <dir> or codex exec --session <id> --prompt "..."
  codex:
    command: "codex"
    args_template: ["exec", "--prompt", "{prompt}", "--working-dir", "{working_dir}"]
    output_format: "stream-json"
    timeout_default: "4h"
    session_id_flag: "--session"
    stdin_prompt: false
    env: {}
    max_concurrent: 2
    stream_format: "codex-stream-json"

  # Google's Gemini CLI (if/when it supports a CLI invocation we want)
  # Usage: gemini -p "..."
  # Note: output_format is "text" (not json/stream-json) since Gemini CLI's
  # output format is not standardized.
  gemini-cli:
    command: "gemini"
    args_template: ["-p", "{prompt}"]
    output_format: "text"
    timeout_default: "2h"
    session_id_flag: null
    stdin_prompt: false
    env: {}
    max_concurrent: 1
    stream_format: "none"

  # Mock tool for tests (POSIX-builtin echo, always available)
  # Used by the test suite to verify subprocess invocation without
  # requiring real Claude Code or Codex CLI binaries.
  _mock_echo:
    command: "echo"
    args_template: ["{prompt}"]
    output_format: "text"
    timeout_default: "30s"
    session_id_flag: null
    stdin_prompt: false
    env: {}
    max_concurrent: 4
    stream_format: "none"
```

**Important:** the `_mock_echo` entry stays in the production config because tests use it. The skip_glob in the production config is the caller's responsibility (e.g. tests use a tmpdir copy of this config without `_mock_echo`).

## Deliverable 3: MODIFY `pantheon/conductor/v2/cli_tool.py:resolve_tool`

**Replace the hardcoded `_DEFAULT_TOOLS` dict with a real config loader.** The Brief 1 version had:

```python
_DEFAULT_TOOLS: dict[str, ToolRegistration] = {
    "_mock_echo": ToolRegistration(...),
}

def resolve_tool(name: str) -> ToolRegistration:
    if name in _DEFAULT_TOOLS:
        return _DEFAULT_TOOLS[name]
    raise CliToolNotFoundError(...)
```

**Brief 2 replaces this with:**

```python
# Module-level registry: name → ToolRegistration
# Populated by load_tools_config() at engine startup.
# Default: contains only _mock_echo (the test fixture) for backwards
# compat with Brief 1 tests that don't load a config.
_REGISTRY: dict[str, ToolRegistration] = {
    "_mock_echo": ToolRegistration(
        name="_mock_echo",
        command="echo",
        args_template=["{prompt}"],
        output_format="text",
        timeout_default="30s",
    ),
}

def register_tool(reg: ToolRegistration) -> None:
    """Add or replace a tool in the registry. Used by load_tools_config()
    and by tests that need to register custom tools."""
    _REGISTRY[reg.name] = reg

def unregister_tool(name: str) -> None:
    """Remove a tool from the registry. Used by tests for cleanup."""
    _REGISTRY.pop(name, None)

def resolve_tool(name: str) -> ToolRegistration:
    """Look up a tool by name. Returns the registered ToolRegistration
    or raises CliToolNotFoundError if not registered.
    
    The registry is populated by:
    1. Brief 1 default: _mock_echo (always present)
    2. load_tools_config(path) at engine startup (operator-supplied)
    3. register_tool(reg) at runtime (tests, dynamic tool loading)
    """
    if name in _REGISTRY:
        return _REGISTRY[name]
    raise CliToolNotFoundError(
        f"tool {name!r} is not registered. Available tools: {sorted(_REGISTRY.keys())}. "
        f"Check pantheon/conductor/config/cli_tools.yaml or call register_tool() to "
        f"register it at runtime."
    )

def load_tools_config(path: Path) -> list[ToolRegistration]:
    """Load tools from a YAML config file. Returns the list of registered
    tools. Validates required fields and output_format values; raises
    CliToolConfigError on malformed entries.
    
    Per Thoth's spec §4: 'Adding new tools later: claude-code-web,
    codex-remote, custom internal tools, etc. The cli_tool step type
    is tool-agnostic; what runs is determined by the registration.'
    
    Idempotent: calling load_tools_config twice replaces the registry
    entries (does not duplicate).
    """
    if not path.exists():
        raise CliToolConfigError(
            f"cli_tools config not found: {path!r}. Create the file or "
            f"remove the load_tools_config() call from engine startup."
        )
    
    doc = yaml.safe_load(path.read_text())
    if not isinstance(doc, dict) or "cli_tools" not in doc:
        raise CliToolConfigError(
            f"cli_tools config {path!r} missing top-level 'cli_tools' key. "
            f"See pantheon/conductor/config/cli_tools.yaml for the expected shape."
        )
    
    registered: list[ToolRegistration] = []
    VALID_OUTPUT_FORMATS = {"json", "text", "stream-json"}
    REQUIRED_FIELDS = {"command", "args_template"}
    
    for name, entry in doc["cli_tools"].items():
        if not isinstance(entry, dict):
            raise CliToolConfigError(
                f"cli_tools config {path!r}: tool {name!r} entry is not a mapping"
            )
        missing = REQUIRED_FIELDS - set(entry.keys())
        if missing:
            raise CliToolConfigError(
                f"cli_tools config {path!r}: tool {name!r} missing required fields: {sorted(missing)}"
            )
        output_format = entry.get("output_format", "text")
        if output_format not in VALID_OUTPUT_FORMATS:
            raise CliToolConfigError(
                f"cli_tools config {path!r}: tool {name!r} has invalid output_format "
                f"{output_format!r}; must be one of {sorted(VALID_OUTPUT_FORMATS)}"
            )
        
        reg = ToolRegistration(
            name=name,
            command=entry["command"],
            args_template=list(entry["args_template"]),
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
```

**Add `CliToolConfigError` exception class** (extends `CliToolError`):

```python
class CliToolConfigError(CliToolError):
    """Raised when cli_tools.yaml is malformed (missing required fields,
    invalid output_format, missing 'cli_tools' top-level key, etc.).
    Distinct from CliToolNotFoundError so tests can differentiate."""
    pass
```

**Add `yaml` import** at the top of cli_tool.py (Brief 1 didn't import it because there was no YAML loading).

## File changes planned

| File | Change | LOC est |
|---|---|---|
| `pantheon/conductor/v2/tests/test_cli_tool.py` (NEW) | 28 tests | ~500 |
| `pantheon/conductor/config/cli_tools.yaml` (NEW) | v1 tool set registration | ~80 |
| `pantheon/conductor/v2/cli_tool.py` (modify) | Add CliToolConfigError, load_tools_config, replace _DEFAULT_TOOLS with _REGISTRY, add yaml import | ~80 net new |
| **Total** | | **~660 LOC** |

**Engine code change: zero.** The engine already calls `cli_tool.resolve_tool(step.tool)` — Brief 2 just makes the function real.

---

## Validation (your exit criteria)

```bash
# 1. Targeted: 28 new tests pass
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_cli_tool.py -v
# Expect: 28/28 pass

# 2. Full v2 suite still green (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 283/1-skip/0-fail (was 255/1/0 after 4.6; +28 cli_tool tests)

# 3. Config loading works against the real cli_tools.yaml
python3 -c "
from pathlib import Path
from conductor.v2.cli_tool import load_tools_config, resolve_tool, _REGISTRY
config_path = Path('/home/konan/pantheon/conductor/config/cli_tools.yaml')
tools = load_tools_config(config_path)
print(f'OK: loaded {len(tools)} tools from {config_path.name}')
for t in tools:
    print(f'  - {t.name}: command={t.command!r}, output_format={t.output_format!r}, max_concurrent={t.max_concurrent}')
print()
# Resolve a real tool
cc = resolve_tool('claude-code')
print(f'OK: resolve_tool(\"claude-code\") returned: {cc.name}, {cc.command}, {cc.args_template}')
"
# Expect: 4 tools loaded (claude-code, codex, gemini-cli, _mock_echo)
# Expect: claude-code resolves with command='claude' and args_template starting with ['--prompt', '{prompt}', ...]

# 4. Malformed config raises CliToolConfigError
python3 -c "
from pathlib import Path
import tempfile, yaml
from conductor.v2.cli_tool import load_tools_config
with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as f:
    yaml.safe_dump({'cli_tools': {'bad-tool': {'command': 'echo'}}}, f)  # missing args_template
    p = Path(f.name)
try:
    load_tools_config(p)
    print('FAIL: should have raised')
except Exception as e:
    print(f'OK: {type(e).__name__}: {e}')
"
# Expect: OK: CliToolConfigError: cli_tools config .../bad.yaml: tool 'bad-tool' missing required fields: ['args_template']
```

## Verification (Brief 3 will run)

- All 28 tests pass
- Full v2 suite: 283/1-skip/0-fail
- The 4 hand-tests above work as expected
- All 5 production workflows still load and dispatch (no regression)
- Plan YAML flip: Step 4.9 → DONE (Brief 3)

## Reversibility

**Low cost.** Delete `test_cli_tool.py`. Delete `cli_tools.yaml`. Revert `cli_tool.py:resolve_tool` to use `_DEFAULT_TOOLS` (the Brief 1 placeholder). **Zero data state changes.**

---

## Reference files

- **Plan YAML:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (Step 4.9 pending, current_step: 4.9.briefs.brief_2_of_3)
- **Brief 1 (the one that partial-shipped):** `~/pantheon/shared/active/conductor-step-4.9-brief-1.md` (24.5K)
- **Brief 1 spec:** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` §2.1, §4, §7.3, §9
- **Existing cli_tool.py (Brief 1 work):** `~/pantheon/conductor/v2/cli_tool.py` (16.7K, 361+ lines)
- **Engine _exec_cli_tool:** `~/pantheon/conductor/v2/engine.py:1273-1310` (Brief 1's wiring, real)
- **WorkflowStep cli_tool fields:** `~/pantheon/conductor/v2/engine.py:645` (Brief 1's dataclass additions, real)
- **Test fixture pattern:** mirror `test_parallel.py` (uses `from v2.tests import fixtures as cf` + `MockRun` / `queue_run`)
- **Operator decisions:** `~/pantheon/shared/decisions/2026-06-16-step-4.7.md` (Q1-Q8 from spec §9 all locked)

## Open questions for Marvin (resolve before/during implementation)

1. **Should the test for `load_tools_config` use a real tmpdir YAML file, or mock the file I/O?** My recommendation: real tmpdir (cleaner test, exercises the full path). The `tempfile.NamedTemporaryFile` + `yaml.safe_dump` pattern is well-established in the existing test suite.

2. **Should the `_mock_echo` entry in cli_tools.yaml be wrapped in a "test-only" section, or kept as a first-class tool?** My recommendation: keep it as a first-class tool in the YAML but document it as "test-only — production workflows should not reference _mock_echo." This matches how the workflow_validator skips `bridge-test-*.yaml` — explicit allowlist at the consumer, not the producer.

3. **What happens if a workflow YAML references a tool that isn't in cli_tools.yaml?** The engine's `_exec_cli_tool` calls `resolve_tool(step.tool)`, which raises `CliToolNotFoundError`. The brief's "Tool binary not installed" answer from spec §9 Q8 says "fail fast with a clear error." Confirm this is the right behavior for an unknown tool (vs. a missing binary, which is the same error class).

4. **The `claude-code` config has `output_format: "json"` and `stream_format: "claude-stream-json"`. Brief 1 raises on `stream-json` output_format. Should Brief 2 keep the same raise-on-stream-json behavior, or now allow it for tools that explicitly set `stream_format: "claude-stream-json"`?** My recommendation: KEEP the raise. stream-json output_format requires the WebSocket live-observability stream, which is deferred. Even if a tool is registered with stream_format, the engine can't consume it without the WebSocket. Document this in the cli_tools.yaml comment.

## What comes after this brief

**Brief 3 of 3** (verification + closure):
- Run full v2 suite, expect 283/1-skip/0-fail
- Hand-test the 4-agent worked-example workflow shape (real `claude-x-codex-marvin-hephaestus-feature.yaml`) — even if the CLI tools can't actually run end-to-end, validate the YAML parses
- Plan YAML flip: Step 4.9 → DONE, header current_step → 4.final
- Decision log entry: closure + measured test count + acknowledge Brief 1's missing test_cli_tool.py was shipped in Brief 2

**After Step 4.9 closes:** Step 4.final (Phase 4 closure review) runs immediately. 5-section review at `reviews/phase-4-quarantine-sovereign-final-review.md`. The two latent engine bugs from Step 4.8 (declared_output parameter + single-branch sub-workflow premature status) get fixed or explicitly deferred in 4.final.
