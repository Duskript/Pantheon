# Conductor CLI Orchestration — Build Brief

**Spec:** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` (v1.0.0)
**Status:** pending → in-progress on Marvin's ack
**Owner:** Marvin (engine + server), Iris (GUI integration), Thoth (workflows + coordination)
**Spec author:** Thoth, 2026-06-15
**Date:** 2026-06-15

---

## TL;DR

Add three new step types to Conductor v2's engine: `cli_tool` (invoke a single CLI subprocess like Claude Code or Codex CLI), `parallel` (run N child steps concurrently), and `merge` (combine N outputs via strategy). Plus a WebSocket live-observability stream for the Conductor GUI. This is what lets workflows explicitly orchestrate coding-agent CLIs in tandem — e.g., Marvin + Hephaestus + Claude Code + Codex all running on the same feature, with a judge picking the best output.

## What came before (context)

- **Conductor v2 is built and shipping** — 36/36 tests pass as of 2026-06-14. Engine at `~/pantheon/conductor/v2/engine.py` (82KB), server at `conductor_server.py`, NATS bridge, webhook gateway, quarantine sweeper all working.
- **Existing step types in the engine:** `god_dispatch`, `nats_publish`, `llm_call`, `api_call`, `erpnext_create`, `erpnext_update`, `send_toast`, `delay`, `condition`. The engine routes between gods (Thoth, Hephaestus, Marvin, Hermes, etc.) and skills. The agent layer (which CLI tool a god uses internally) is opaque to Conductor.
- **The gap:** workflows can route to a god with a skill, but can't say "use Claude Code" or "use Codex CLI" or "run both in parallel and pick the better one." The autoresearch spec (separate brief) will use these primitives; the worked-example workflow in the spec shows Marvin + Hephaestus + Claude Code + Codex in a 4-way race.

## What this brief is

This is the build brief for `conductor-cli-orchestration.md`. Six phases per the spec §10:

| Phase | What | Owner | Estimate |
|---|---|---|---|
| 1 | `cli_tool` step type in engine | Marvin | 1 week |
| 2 | WebSocket live stream server | Marvin | 1 week |
| 3 | `parallel` step type in engine | Marvin | 1 week |
| 4 | `merge` step type in engine (6 strategies) | Marvin | 1 week |
| 5 | Conductor GUI integration (Run view shows live events) | Iris | 1-2 weeks |
| 6 | Worked-example workflows (real YAMLs) | Thoth | 1 week |

Phases 1-4 are sequential. Phase 5 can run in parallel with Phase 3-4 once Phase 1 lands (the GUI needs the WebSocket contract from Phase 2). Phase 6 starts after Phase 1 ships (need at least `cli_tool` to test the workflows).

## Your task (Phase 1 only, this brief)

**Add the `cli_tool` step type to the Conductor v2 engine.** Per spec §2.1 and §7.3:

1. Extend the `StepType` enum (or whatever the engine uses to dispatch) to include `cli_tool`
2. Implement subprocess invocation in `engine.py:_execute_step` (or wherever steps run)
3. Handle the `cli_tools.yaml` config at `~/pantheon/conductor/config/cli_tools.yaml` (does not exist yet — create it with the v1 tool set per spec §4: `claude-code`, `codex`, `gemini-cli`)
4. Support the YAML shape per spec §7.3: `tool`, `input.prompt`, `input.working_dir`, `input.session_id`, `input.resume`, `input.env`, `input.timeout`, `input.stream`, `gates`, `on_error`, `output`
5. Capture output: stdout, stderr, exit_code, duration_seconds, artifacts (files modified), tool_metadata
6. Handle session_id resume logic per tool's `session_id_flag`
7. Implement retry logic per `on_error.retry` config
8. Tests: subprocess lifecycle, error handling, timeout, resume, retry

**~300 LOC in `engine.py`, ~200 LOC in new `cli_tool.py` module** per spec estimate.

### Validation

```bash
# After implementing, you should be able to:
python3 -m pytest tests/test_cli_tool.py -q
# Should pass with ≥ 10 tests covering the spec's behavioral contract

# And hand-test:
python3 conductor/conductor-server.py --check-layout
# Should report the new cli_tool support
```

### What you do NOT need to do in Phase 1

- Don't implement `parallel` or `merge` — those are Phases 3-4
- Don't implement the WebSocket live stream — that's Phase 2
- Don't touch the Conductor GUI — that's Iris's Phase 5
- Don't write worked-example workflows — that's my Phase 6

## Reference files

- **Spec (full):** `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md`
- **Conductor v2 engine:** `~/pantheon/conductor/v2/engine.py` (the file to extend)
- **Existing step type pattern:** grep for `_execute_step` or `StepType` in `engine.py` to see how `god_dispatch` and `nats_publish` are implemented — mirror the same pattern
- **Engine tests:** `~/pantheon/conductor/v2/tests/` (mirror the existing test structure for the new `test_cli_tool.py`)
- **Sample workflow with `cli_tool`:** spec §6 has a worked example (`claude-x-codex-feature.yaml`)

## Open questions needing your decision

The spec §9 has 8 open questions. My recommendations:

| # | Question | Recommendation |
|---|---|---|
| 1 | Default `stream: true` or `false` for `cli_tool`? | **false** (opt-in per step) |
| 2 | Nested `parallel`? | **Yes, limit 3 levels** |
| 3 | `llm_pick_best` returns chosen + judge reasoning? | **Both** (reasoning for audit) |
| 4 | Default `fail_mode` for `parallel`? | **`fast`** (matches CI/CD) |
| 5 | WebSocket auth? | **API key in query param v1, session token v2** |
| 6 | Where does `cli_tools.yaml` live? | **`~/pantheon/conductor/config/cli_tools.yaml`** |
| 7 | `cli_tool` streaming input (multi-turn)? | **No for v1**, `resume: true` covers it |
| 8 | Tool not installed on host? | **Fail fast** with clear error |

Confirm or push back before starting Phase 1. These are not blocking but the answers affect the engine code.

## What comes after Phase 1

Once Phase 1 ships, the next brief in this series is **Phase 2 (WebSocket live stream)**. The brief for that will be a follow-up. For now, focus only on Phase 1.

## What this means for the rest of Pantheon

When this lands:
- **The autoresearch spec (separate brief)** can use `cli_tool` to invoke `python -m ichor.forge.research` and the parallel/merge types to run 3 experiment goals in parallel
- **Coding workflows (`deploy-feature.yaml`, `bug-fix.yaml`)** get a new option: instead of `god: marvin` + `skill: test-driven-development`, you can write `type: cli_tool` + `tool: codex` for direct CLI invocation
- **The Conductor UI (Iris's mock)** gets a real-time Run view: every Claude Code / Codex CLI file edit, command run, and tool call is visible in the browser

## Contact

- Spec questions / changes / pushback → Thoth
- Engine implementation questions → Marvin (you)
- GUI integration questions → Iris (after Phase 2)
- Worked-example workflows → Thoth (after Phase 1 ships)
