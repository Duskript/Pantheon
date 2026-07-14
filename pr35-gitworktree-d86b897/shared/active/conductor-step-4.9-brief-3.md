# Step 4.9 — Closure verification + plan flip

**Plan:** phase-4-quarantine-sovereign.yaml, Step 4.9
**Brief 3 of 3** (the closure brief — verifies Briefs 1+2, flips plan YAML, writes decision log)
**Owner god:** marvin
**QA god:** thoth
**Date:** 2026-06-16
**Status context:** Brief 1 SHIPped (cli_tool.py + test_cli_tool.py + engine.py wiring). Brief 2 SHIPped (cli_tools.yaml + load_tools_config + 6 new config tests). 30/30 cli_tool tests pass. 285/1-skip/0-fail on v2 suite. Brief 3 closes Step 4.9.

**Operator instruction (locked 2026-06-16):** "go through 2, 3, 4 in sequence. If you hit a blocker, notify in morning brief. Otherwise just get it done." This brief is mostly paperwork — no new code, no new tests. Just verification + plan flip + decision log.

---

## TL;DR

This is the closure brief. Run the full validation suite to confirm Briefs 1+2 work together end-to-end, hand-test the resolved tool set works against the real `cli_tools.yaml`, flip Step 4.9 to DONE in the plan YAML, write a decision log entry, and confirm the substrate is ready for 4.final.

**Smaller scope than Step 4.6's closure — Brief 1 was clean, Brief 2 was clean, no discrepancies caught, no unauthorized fixes.** Just verification + paperwork + plan flip.

---

## Deliverables (this brief)

### 1. Run the full validation suite (operator-quality check)

```bash
# Targeted: 30 cli_tool tests still pass
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/test_cli_tool.py -v
# Expect: 30/30 pass (24 from Brief 1 + 6 from Brief 2)

# Full v2 suite (regression check)
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 285/1-skip/0-fail (Brief 2 baseline; was 255/1/0 before Step 4.9; +30 cli_tool tests)
```

### 2. Hand-test the 4-agent worked-example workflow shape

**The point of cli_tool is the "best of N agents" workflow.** Validate the YAML parses (even if the actual CLI tools can't run end-to-end without binaries installed):

```bash
python3 -c "
from pathlib import Path
from conductor.v2.engine import Workflow
import yaml
demo_yaml = yaml.safe_load('''
workflow:
  id: claude-x-codex-marvin-hephaestus-feature
  name: 'Feature Implementation (4 Agents in Tandem)'
  version: '1.0.0'
  steps:
    - id: spec
      god: thoth
      skill: deep-research
      input: user_request
      output: spec
      timeout: 30m
    - id: parallel-implement
      type: parallel
      fail_mode: slow
      max_concurrency: 4
      branches:
        - id: marvin-impl
          god: marvin
          skill: test-driven-development
          input_from: spec
          timeout: 4h
        - id: hephaestus-impl
          god: hephaestus
          skill: architecture-design
          input_from: spec
          timeout: 4h
        - id: claude-impl
          type: cli_tool
          tool: claude-code
          tool_input:
            prompt: 'Implement feature per spec. TDD. Write tests first.'
            working_dir: /home/konan/workspace/project
          timeout: 4h
        - id: codex-impl
          type: cli_tool
          tool: codex
          tool_input:
            prompt: 'Implement feature per spec. TDD. Write tests first.'
            working_dir: /home/konan/workspace/project
          timeout: 4h
      output: four-impls
    - id: pick-best
      type: merge
      inputs: [marvin-impl, hephaestus-impl, claude-impl, codex-impl]
      strategy: llm_pick_best
      strategy_config:
        judge_tool: claude-code
        judge_prompt_template: |
          Compare these four implementations.
          Pick the most correct, most idiomatic, best-tested.
          Return verbatim + 3-bullet summary of why.
        timeout: 30m
      output: winning-impl
''')
wf = Workflow.from_dict(demo_yaml, Path('test.yaml'))
print(f'OK: workflow {wf.id} loaded with {len(wf.steps)} steps')
for step in wf.steps:
    print(f'  - {step.id}: type={step.type}', end='')
    if step.type == 'parallel':
        print(f', branches={[b.id for b in step.branches]}, fail_mode={step.fail_mode}')
    elif step.type == 'merge':
        print(f', strategy={step.strategy}, inputs={step.inputs}')
    elif step.type == 'cli_tool':
        print(f', tool={step.tool!r}')
    else:
        print(f', god={step.god!r}')
"
# Expect: 3 steps (spec, parallel-implement, pick-best) all parse cleanly
# Expect: parallel-implement has 4 branches (2 god_dispatch, 2 cli_tool)
# Expect: pick-best has strategy=llm_pick_best, inputs=[4 branch ids]
```

**This is the moment of proof that the substrate earns its keep.** A 4-agent workflow — Marvin + Hephaestus + Claude Code + Codex CLI in parallel, with a judge picking the best — parses cleanly. The actual end-to-end run requires the `claude` and `codex` binaries to be installed, but the YAML contract is now real.

### 3. Decision log entry

**Append to `~/pantheon/shared/decisions/2026-06-16-step-4.9.md`** (NEW file — neither Brief 1 nor Brief 2 wrote one, and the operator wants a single decision log entry per step):

```markdown
# 2026-06-16 — Step 4.9 closure (cli_tool step type — best-of-N with external CLIs)

**Context:** Step 4.9 was added to the Phase 4 plan on 2026-06-16 as the operator's response to "we need to do the CLI." It builds on Step 4.7+4.8 (parallel + merge step types SHIPped) and unlocks the third primitive from Thoth's `conductor-cli-orchestration.md` spec v1.0.0: workflows that invoke external CLI subprocesses (Claude Code, Codex CLI, gemini-cli) as named steps.

## What shipped

3 briefs, all SHIP'd:

### Brief 1 (cli_tool step type — partial ship, completed in Brief 2)
- pantheon/conductor/v2/cli_tool.py (NEW, 16.7K → 22.1K by Brief 2, 361+ lines)
  - Exceptions: CliToolError, CliToolNotFoundError, CliToolTimeoutError
  - ToolRegistration dataclass (per Thoth spec §4): name, command, args_template, output_format, timeout_default, session_id_flag, stdin_prompt, env, max_concurrent, stream_format
  - resolve_tool(name) → ToolRegistration or CliToolNotFoundError
  - register_tool(reg) / unregister_tool(name) — runtime tool registration
  - _substitute_template(template, substitutions) — replace {prompt}, {working_dir}, {session_id} placeholders
  - _parse_duration(s) — "30s"/"5m"/"1h"/"1d" → seconds (delegates to engine._parse_duration if available)
  - _run_subprocess(tool_reg, input_dict, timeout_s) — spawn subprocess, capture output, raise on timeout/not-found
  - _parse_output(output_format, stdout, stderr) — text: {text: ...}, json: parsed dict, stream-json: raise with "deferred" message
  - run_cli_tool(tool_reg, input_dict, on_error, timeout_s) — synchronous entry point, handles retry (none/fixed/exponential)
  - _REGISTRY module-level dict (Brief 1's _DEFAULT_TOOLS, replaced in Brief 2 with the config-loader-backed registry)
- pantheon/conductor/v2/engine.py — added 3 things:
  - WorkflowStep fields: `tool: Optional[str] = None`, `tool_input: dict = field(default_factory=dict)`, `on_error: dict = field(default_factory=dict)` (line ~645)
  - _step_from_dict loader reads the 3 new fields with defaults
  - _execute_step dispatch: `elif step.type == "cli_tool": await self._exec_cli_tool(inst, wf, step)` (line ~983)
  - NEW: _exec_cli_tool method (lines 1273-1310) — thin orchestrator, lazy import from cli_tool.py, run_in_executor wrapping sync run_cli_tool
- pantheon/conductor/v2/tests/test_cli_tool.py (NEW, 29.9K, 758 lines, 30 tests, all pass)
  - 24 tests from Brief 1: subprocess lifecycle (5), parse output (4), retry policy (4), template substitution (2), duration parsing (2), end-to-end (2), WorkflowStep dataclass (2), resolve_tool (2), edge cases (1)
  - 6 NEW tests from Brief 2: load_tools_config reads yaml, validate required fields, validate output_format, register/unregister round-trip, missing file raises CliToolConfigError, malformed config raises

### Brief 2 (cli_tools.yaml config + real tool registration)
- pantheon/conductor/config/cli_tools.yaml (NEW, 3.2K)
  - v1 tool set: claude-code (Anthropic), codex (OpenAI), gemini-cli (Google), _mock_echo (test fixture)
  - Per Thoth's spec §4: each tool has command, args_template, output_format, timeout_default, session_id_flag, stdin_prompt, env, max_concurrent, stream_format
- pantheon/conductor/v2/cli_tool.py — added:
  - CliToolConfigError (extends CliToolError) — distinct exception for config-loading failures
  - load_tools_config(path) — reads YAML, validates required fields (command, args_template), validates output_format, registers each tool
  - Replaced _DEFAULT_TOOLS with _REGISTRY (idempotent reload, register_tool/unregister_tool work)
  - Added `import yaml` at top of file
- 6 NEW tests in test_cli_tool.py covering the config loader

### Brief 3 (this brief — verification + closure + plan flip)
- All deliverables verified: 30/30 cli_tool tests pass, 285/1-skip/0-fail on v2 suite (was 255/1/0 after 4.6; +30)
- 4 hand-tests pass: load_tools_config, resolve_tool after load, malformed config raises, missing file raises
- 4-agent worked-example workflow parses cleanly (Marvin + Hephaestus + Claude Code + Codex CLI in parallel + llm_pick_best merge)
- Plan YAML flipped: Step 4.9 → DONE, header current_step → 4.final
- 5 production workflows still load (deploy-feature, bug-fix, cross-pantheon-deploy, morning-briefing, sovereign-publish-tallon-correction)

## Discrepancy caught + how

**Brief 1 looked like a partial ship on the first read** (test_cli_tool.py was not visible in `ls` at one point, handoff was missing from my inbox). The actual state was: cli_tool.py + test_cli_tool.py + engine.py wiring all shipped, 24 cli_tool tests passed. The transient `ls` failure was a race between Brief 1's commits and the test file's mtime update. **Lesson: always background-run the test suite to get a clean read, don't trust transient `ls` output during in-flight processes.** Cited for 4.final review (section 1_holes: implicit assumptions about file state).

## The 4-agent proof

The worked-example workflow YAML (per Thoth's spec §6) parses cleanly with the new primitives. A workflow that runs Marvin + Hephaestus + Claude Code + Codex CLI in parallel, with a judge picking the best, is now a valid YAML construct. The actual end-to-end run requires `claude` and `codex` binaries installed; the YAML contract is real. **This is the canonical proof that the parallel-work primitive works for external CLIs, not just for god-vs-god.**

## Reversibility

**Low cost.** Delete `cli_tools.yaml` + `test_cli_tool.py`. Revert cli_tool.py:resolve_tool to use _DEFAULT_TOOLS (the Brief 1 placeholder). Revert engine.py changes (WorkflowStep fields, _exec_cli_tool method, dispatch extension). **Zero data state changes. No existing workflows use the cli_tool step type.**

## What comes next

- **Step 4.final (Phase 4 closure review)** — runs immediately after this brief lands. 5-section review at `reviews/phase-4-quarantine-sovereign-final-review.md`. The two latent engine bugs from Step 4.8 (declared_output parameter + single-branch sub-workflow premature status) get fixed or explicitly deferred in 4.final.
- **After 4.final:** the substrate is fully operational. Forge Autoresearch, WebSocket live-observability, Conductor GUI integration, and Pantheon Notebook all become safe to dispatch in parallel — each gated by the now-trustworthy Conductor.
```

### 4. Flip Step 4.9 to DONE in plan YAML

**Edit `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml`:**

- Change Step 4.9 entry:
  - `status: pending` → `status: DONE`
  - `deferral_reason: null` (no change)
  - Add `completed_at: "2026-06-16"`
  - Add `verdict: SHIP`
  - Update `brief_1_of_3`, `brief_2_of_3`, `brief_3_of_3` to mark each as SHIPPED with the verification output
  - Update `success_criteria` to mark each as VERIFIED
- Update header:
  - `current_step: "4.9.briefs.brief_3_of_3"` → `current_step: "4.final"`
  - `next_step: "4.9.briefs.brief_3_of_3"` → `next_step: null` (4.final is the final step)
  - `steps_done: 8` → `steps_done: 9`
  - `steps_pending: 2` → `steps_pending: 1`
- Update the Steps overview table (around line 282): "4.9" row status changes from "pending" to "DONE"
- No change to 4.final trigger (it was already "All 4.1-4.9 DONE")

**Verify with:**

```bash
python3 -c "
import yaml
doc = yaml.safe_load(open('/home/konan/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml'))
for s in doc['steps']:
    print(f\"  {s['id']:6s} {s['status']:12s} {s['title'][:60]}\")
print(f\"header: total={doc['steps_total']} done={doc['steps_done']} pending={doc['steps_pending']} current={doc['current_step']}\")
"
# Expect: 4.1-4.9 all DONE, 4.final pending
# header: total=10 done=9 pending=1 current=4.final
```

### 5. Commit + drop handoff

```bash
cd /home/konan/pantheon && git add -A plans/conductor-v2/phase-4-quarantine-sovereign.yaml shared/decisions/2026-06-16-step-4.9.md conductor/v2/ conductor/config/ 2>/dev/null
git -c user.email=hermes@pantheon.local -c user.name=Hermes commit -m "Phase 4 Step 4.9 SHIP — cli_tool step type + cli_tools.yaml + 30 new tests

- cli_tool.py (NEW, 22.1K) — ToolRegistration, resolve_tool, _substitute_template,
  _parse_duration, _run_subprocess, _parse_output, run_cli_tool, load_tools_config,
  register_tool, unregister_tool, _REGISTRY dict, CliToolConfigError
- test_cli_tool.py (NEW, 29.9K, 758 lines, 30 tests, all pass)
- cli_tools.yaml (NEW, 3.2K) — v1 tool set: claude-code, codex, gemini-cli, _mock_echo
- engine.py: WorkflowStep gets tool/tool_input/on_error fields, _execute_step
  dispatch gets cli_tool branch, _exec_cli_tool method
- 285/1-skip/0-fail verified (was 255/1/0 after 4.6; +30 cli_tool tests)
- 4-agent worked-example workflow parses cleanly (the proof)

4-agent proof: a workflow that runs Marvin + Hephaestus + Claude Code + Codex
CLI in parallel, with a judge picking the best, is now a valid YAML construct.
The actual end-to-end run requires claude/codex binaries; the YAML contract
is real.

Substrate sequence status:
- 4.1-4.9: SHIPped
- 4.final: pending (Phase 4 closure review, 5-section)

Test count progression:
- baseline: 200/1/0
- after 4.6: 255/1/0
- after 4.9: 285/1/0 (current)
- after 4.final: 285/1/0 (closure review doc, no tests)

Latent engine bugs queued for 4.final:
- _latest_branch_output's declared_output parameter (1-line fix)
- single-branch sub-workflow premature status=completed (bigger refactor)

Reversibility: low cost. Delete cli_tools.yaml + test_cli_tool.py. Revert
cli_tool.py to _DEFAULT_TOOLS. Revert engine.py additions. Zero state changes."
```

**Handoff message at `~/pantheon/gods/messages/hermes/`:**

```json
{
  "to": "hermes",
  "subject": "[conductor/step-4.9/brief-3] Step 4.9 SHIP — cli_tool working, 285/1/0, plan YAML flipped, 4.final next",
  "body": "Step 4.9 SHIP. All 3 briefs landed. 285/1-skip/0-fail verified. 4-agent worked-example workflow parses cleanly. Plan YAML Step 4.9 → DONE. Substrate ready for Step 4.final.\n\nStatus: complete\nTest count (cli_tool): 30/30 pass (24 from Brief 1 + 6 from Brief 2)\nFull v2 suite: 285/1-skip/0-fail (was 255/1/0 after 4.6; +30)\n4-agent worked-example: parses cleanly (Marvin + Hephaestus + Claude Code + Codex CLI in parallel + llm_pick_best merge)\n4 production workflows + 5 production workflows (5 of them) all load: bug-fix, cross-pantheon-deploy, deploy-feature, morning-briefing, sovereign-publish-tallon-correction\n\nLatent bugs logged for 4.final: still the 4.7/4.8 bugs (declared_output parameter + single-branch sub-workflow premature status), nothing new from Step 4.9.\n\nNext action: dispatch Step 4.final (Phase 4 closure review) to Hermes (me, meta-step)."
}
```

---

## Validation (your exit criteria)

```bash
# 1. Full v2 suite green
cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon ~/.hermes/hermes-agent/venv/bin/pytest conductor/v2/tests/ -q
# Expect: 285/1-skip/0-fail

# 2. 4-agent worked-example workflow parses
[hand-test above]
# Expect: 3 steps, parallel-implement has 4 branches, pick-best has llm_pick_best

# 3. 5 production workflows load
python3 -c "
from pathlib import Path
from conductor.v2.engine import Workflow
import yaml
ws = Path('/home/konan/pantheon/conductor/workflows')
ok = 0
for p in sorted(ws.glob('*.yaml')):
    if p.name.startswith('bridge-test'):
        continue
    d = yaml.safe_load(p.read_text())
    wf = Workflow.from_dict(d, p)
    ok += 1
print(f'OK: {ok} production workflows load')
"
# Expect: OK: 5 production workflows load

# 4. Plan YAML flip verified
[python verification above]
# Expect: 4.1-4.9 all DONE, 4.final pending, current=4.final

# 5. Commit + handoff landed
git log --oneline -1 main
# Expect: new commit with "Phase 4 Step 4.9 SHIP"
ls -lat ~/pantheon/gods/messages/hermes/msg_*.json | head -1
# Expect: newest message is the Step 4.9 Brief 3 closure
```

## Verification (no separate brief — this IS the verification)

- All deliverables landed
- Plan YAML flipped
- Decision log entry written
- Commit on main
- Handoff in my inbox
- **Step 4.9 closed**

## Reversibility

Trivial. `git revert` the Step 4.9 commit. Reverts all 4.9 deliverables in one shot (cli_tools.yaml + test_cli_tool.py + cli_tool.py:load_tools_config + engine.py additions + 3 production workflow edits if any). 0 state changes.

## Reference files

- **Plan YAML (the one to flip):** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml`
- **Decision log (the one to write):** `~/pantheon/shared/decisions/2026-06-16-step-4.9.md` (NEW file)
- **Brief 1 evidence:** `~/pantheon/gods/messages/hermes/msg_20260616_*` (Marvin's Brief 1 + 2 handoffs)
- **Brief 2 evidence:** Same — Marvin's SHIP handoff confirmed 30/30 tests + 285/1/0
- **cli_tool module (real, no changes):** `~/pantheon/conductor/v2/cli_tool.py` (22.1K, 361+ lines)
- **CLI tool config (real, no changes):** `~/pantheon/conductor/config/cli_tools.yaml` (3.2K)
- **Test file (real, no changes):** `~/pantheon/conductor/v2/tests/test_cli_tool.py` (29.9K, 30 tests, all pass)
- **Engine wiring (real, no changes):** `~/pantheon/conductor/v2/engine.py` (WorkflowStep fields, _exec_cli_tool method, dispatch extension)

## Open questions for Marvin (resolve before/during verification)

1. **Are there any other `cli_tool` step types anywhere in the codebase** (e.g. in handoff files, in operator-supplied YAMLs outside `conductor/workflows/`)? The validator only checks `conductor/workflows/*.yaml`. If handoffs or webhooks can have cli_tool steps, those need a separate check. My read: those go through the engine's runtime guard, not the workflow validator — the validator is for `conductor/workflows/*.yaml` only. Confirm.

2. **The discrepancy caught in Brief 1 (the partial-ship appearance) — does this surface as a 4.final review item?** Yes, it's in the decision log under "Discrepancy caught" and explicitly cited as a 4.final `section_1_holes` candidate (implicit assumptions about file state). The lesson: always background-run the test suite to get a clean read, don't trust transient `ls` output during in-flight processes.

3. **Should the 4-agent worked-example workflow YAML be committed as a real file in `conductor/workflows/`?** My recommendation: NO. The hand-test validates the YAML contract is real, but committing a workflow that references `claude-code` and `codex` tools means future engine starts will try to invoke those binaries (and fail if they're not installed). The YAML is a proof-of-concept, not a production workflow. If the operator wants it committed, that's a separate decision.

## What comes after this brief

**Step 4.final (Phase 4 closure review)** runs immediately. 5-section review at `reviews/phase-4-quarantine-sovereign-final-review.md`. The two latent engine bugs from Step 4.8 (declared_output parameter + single-branch sub-workflow premature status) get fixed or explicitly deferred in 4.final. After 4.final, the substrate is fully operational and Forge Autoresearch / WebSocket / GUI / Notebook can be safely parallel-dispatched.
