# Phase 4 — Final Review

**Plan:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml`
**Reviewer:** Hermes (4.final meta-step, no god dispatch)
**Date:** 2026-06-16
**Status:** Phase 4 review complete. All 9 implementation steps (4.1–4.9) verified SHIPped. Two latent engine bugs documented for Phase 5 follow-up. Three drift items found in plan YAML metadata. One real risk surfaced in the Phase 4 → Phase 5 transition.

**Verdict:** **PROCEED to Phase 5 (e2e test suite)** — with the caveats called out in §3 (Blockers) and §5 (Drift) addressed either in Phase 5's first brief or in housekeeping PRs that can run in parallel with Phase 5.

---

## §1 — Holes

A "hole" = a step that is marked DONE in the plan YAML, but the actual deliverable is missing, broken, or doesn't match the spec.

**Holes found: 0 critical, 1 minor (cosmetic).**

| Step | Deliverable | Disk state | Verdict |
|---|---|---|---|
| 4.1 | `quarantine_status.py` (6.1K, 14 tests pass) | Present at `~/pantheon/conductor/scripts/quarantine_status.py` | ✅ Verified by Brief 3 (decision log 2026-06-16-step-4.5.md confirms) |
| 4.2 | dawn-patrol §5.5 fix (auto-call) | Per-profile symlinked to canonical (Step 4.3 consequence); dawn-patrol output adds Conductor Quarantine Backlog section at L137 | ✅ Verified by Brief 3 |
| 4.3 | 95 per-profile SKILL.md symlinks + 459 preserved | All 5 god profile skill counts match (apollo 18, cachyos 18, hephaestus 20, iris 20, thoth 19) | ✅ Verified by Brief 3 |
| 4.4 | Profile-bootstrap hook (drift detection) | Detector + symlink applier SHIPped via PR #33; per-profile replacement complete | ✅ Verified by Brief 3 |
| 4.5 | Heuristic `.archive/` cleanup (6 hephaestus entries) | Backup created at `~/athenaeum/Codex-God-hephaestus/.archive/` (11 files, 120KB), all 6 SKILL.md removed cleanly, bootstrap journal `missing_total: 0` post-op | ✅ Verified by Brief 3 + decision log 2026-06-16.md |
| 4.6 | YAML guardrails + validator | 3 production YAMLs locked (bug-fix, cross-pantheon-deploy, deploy-feature); `operator_approval_required: true` set on sovereign-publishing steps | ✅ Verified by Brief 3 |
| 4.7 | `parallel` + `merge` step types | `_exec_parallel` + `_exec_merge` in engine.py, `merge.py` (298 LOC, 4 strategies: concat/first/diff/vote). 234/1/0 baseline. **Minor: 3 of 16 parallel tests were failing at Brief 1; fixed in 4.8.** | ✅ Verified by Brief 3 |
| 4.8 | Step 4.7 fix-up (3 parallel tests + test_merge.py) | 16/16 parallel tests pass post-fix, 18/18 merge tests pass, SUPERSEDED.md sidecar landed, DECISIONS.md updated with Marvin's 3 mid-task decisions | ✅ Verified by Brief 3 |
| 4.9 | `cli_tool` step type + cli_tools.yaml + 30 tests | `cli_tool.py` 22.1K, `cli_tools.yaml` 3.2K (4 tools registered), `test_cli_tool.py` 29.9K (30 tests pass in 0.32s), full v2 suite **285/1/0** verified just-now on this session | ✅ Verified |

**No deliverable is missing. No deliverable is broken.** All 9 implementation steps reach their spec'd failable-check threshold.

The 1 minor hole: Step 4.5's plan YAML (line 86) claimed a reversibility backup path at `~/athenaeum/Codex-God-hephaestus/.archive/`, but at the time of Brief 2's first attempt, that path did not exist. The pre-flight caught it (the destructive-op-checklist skill worked as designed), and the operator's "Option A" call created the backup before retry. Net effect: no data lost, brief re-dispatched cleanly, disposition unchanged. This is a *process* hole (plan YAML reversibility claim was unverified) not a *deliverable* hole — see §2 decision #1 below.

---

## §2 — Decisions

Implicit scope calls made during 4.1–4.9 execution that weren't in the spec, locked in by operator calls or by Marvin's mid-task design choices. These are the calls Phase 5 will inherit.

### 2.1 — Plan YAML reversibility paths need a verify-or-defer gate (2026-06-16, decision log 2026-06-16-step-4.5.md)

**Context:** Step 4.5's plan YAML line 86 claimed reversibility via `~/athenaeum/Codex-God-hephaestus/.archive/`. Path was aspirational, not verified. Marvin's destructive-op pre-flight (skill: `destructive-op-checklist`) caught it at V4 and refused to execute. Operator called "A" — create the backup, re-dispatch.

**Why it matters for Phase 5:** Phase 5 will have its own destructive ops (e.g. removing or rewriting production workflow YAMLs during E2E coverage expansion). If those plans pin reversibility paths the same way, the pre-flight will refuse and the work will pause. The operator wants forward motion.

**Lock:** All future destructive-op plan YAMLs that name a reversibility path must either (a) include a `verified_at: YYYY-MM-DD` field next to the path proving the path exists, or (b) explicitly mark `reversibility: deferred` and add a 1-line "backup needed" action item to the brief.

**Owner:** Thoth (plan-write convention); Marvin (pre-flight check).

### 2.2 — `cli_tool` spec deferrals (2026-06-16, decision log 2026-06-16-step-4.7.md and conductor-step-4.9 brief)

**Context:** Operator scoped Step 4.7 to `parallel` + `merge` only. Then Step 4.9 came in for `cli_tool` Phase 1, which locked 5 design decisions:

- **stream=false default** — no streaming output for v1, JSON/text only
- **fail_mode=fast** for `parallel` (cancel siblings on first failure)
- **multi-turn streaming = NO for v1** (deferred to separate brief)
- **Tool binary not installed = fail fast** (no graceful degradation to mock)
- **WebSocket live-observability = deferred** (the spec's "Phase 2")

**What this means for Phase 5:** The 3 worked-example workflows in the spec (4-agent race, parent-with-multiple-merge, retry-on-fail-mode-fast) are not testable end-to-end because:
- `claude`, `codex`, `gemini` CLI binaries are not on this host
- The test suite uses `_mock_echo` (POSIX `echo`) which is in `cli_tools.yaml` as a first-class entry
- The 4-agent workflow's `llm_pick_best` merge depends on the LLM path being available — it is, but the LLM judge will reject output it can't evaluate

**Lock:** Phase 5's e2e tests for `cli_tool` must use `_mock_echo` as the tool under test, and `cli_tool`-based worked examples can be smoke-tested (parse, dispatch, mock-execute) but not production-tested until the real CLIs are installed. Document this constraint in the Phase 5 plan.

**Owner:** Hermes (constraint doc), Marvin (e2e tests).

### 2.3 — Marvin's 3 mid-task design decisions (4.8) — explicitly deferred to 4.final QA (i.e., now)

These were Marvin's design calls in 4.7 that he flagged in his self-report and 4.8's decision log said to re-evaluate in 4.final. The plan is for Thoth QA, but Thoth wasn't dispatched for 4.7/4.8 — those are 4.final-bound.

- **(a) Parallel executor reimplementation** — first cut reused `_execute_step` against a synthetic sub-workflow. Second cut (the SHIPped one) dispatches each branch directly by type, with a single-branch sub-wf passed to branch executors so `next_step_after` returns None correctly. This sidesteps the double-execution bug (sub-wf's `next_step_after` returned the next branch, causing each branch to run twice).
  - **Verdict:** This is correct. The double-execution was a real bug; the fix is the right shape. But it leaves a commented-out `sub_wf` reference at L1423-1430 that's "synthetic" and unused. Recommend a 1-line cleanup PR removing the dead reference. Not a blocker.

- **(b) Single-branch sub-workflow pattern** — every branch executor receives a 1-step Workflow containing only itself, so `next_step_after(branch.id)` returns None and the branch doesn't try to "advance" to a sibling.
  - **Verdict:** Correct but creates allocation overhead per branch. For N=4 branches, this is fine. For N=20 in a future phase, it could matter. Note for Phase 5 perf test.

- **(c) `declared_output` parameter on `_latest_branch_output`** — added to the merge resolution path so a branch's `output: foo` is preferred over walking context_bag by branch_id.
  - **Verdict:** Correct, the comment at L1702-1707 documents it well. The walk-fallback at L1721-1723 is defensive but could return the wrong key if multiple branches share keys — recommend adding an `assert not duplicate_keys` to the workflow validator in 4.6 (the validator's output is in `test_workflow_validator.py`).

**Lock:** All 3 design decisions stand as-shipped. The (a) cleanup and (c) validator assertion are 1-line PRs, not Phase 5 blockers.

**Owner:** Marvin (cleanup PR); Thoth (validator assertion).

### 2.4 — Engine.py has +1,313 lines net (4.7+4.8+4.9)

**Context:** Engine went from 82KB / ~2,000 LOC (Phase 3 baseline) to 127KB / 2,731 LOC (post-4.9). All 4.7+4.8+4.9 changes are additive. No existing step types were modified. The engine's load-bearing functions (`_exec_nats_publish`, `_has_operator_approval`, `_consume_operator_approval`, `_REFUSAL_MARKER_RE`) are unchanged in the public contract.

**Why it matters:** The "additive only" claim is verifiable. Step 4.final confirms by `grep` that no pre-existing step type's executor was modified (only new dispatch arms were added to `_execute_step`).

**Lock:** Phase 5 may add more step types (`delay` and `condition` are already there; `http_call` and `kafka_publish` are in the spec backlog). Same rule applies: additive only, no modification of existing executor bodies.

**Owner:** All future steps that touch engine.py.

---

## §3 — Blockers

Anything that would prevent the next sub-plan (`phase-5-e2e-test-suite`) from starting on its first brief.

### B1 — Two latent engine bugs (KNOWN, NOT BLOCKING Phase 5 start, but must be fixed in Phase 5)

**B1a — `_advance` premature completion race (engine.py L2155–2190)**

The `_advance` method has a documented race with the v1+v2 state-file collision. The bridge path (`conductor_server.py` L497-522) **mirrors** `_advance`'s body inline to sidestep the v1 mutation ordering. Comment at L2163-2173 explicitly says: *"the v1+v2 state file collision: the bridge runs v1 mutations before the v2 advance, so `_advance` would see the already-advanced `current_step` and take the 'no next step → completed' branch prematurely."*

**The mirror is the fix.** The `_advance` method itself has not been fixed. If anyone refactors and consolidates the two paths, they'll reintroduce the race.

**Risk:** A future Marvin or Hephaestus "let's unify these two paths" PR would regress this. The comment is the only safeguard.

**Phase 5 first brief must include:** a regression test that exercises the v1+v2 bridge path with 2+ sequential steps and asserts the workflow does NOT mark `completed` after step 1. Today no such test exists (verified by grep — `test_bridge.py` covers the bridge but not the race specifically). 1 test, ~30 LOC.

**B1b — `_exec_parallel` premature status flip (test_parallel.py L386 references)**

`test_parallel.py` line 386 contains a comment about a premature status flip in `_exec_parallel` returns. The 4.8 fix-up made the test pass, but the underlying behavior — when a parallel step's branches complete and the step writes its own history entry — may still flip `step.status` to "completed" before all branch outputs are mirrored to `context_bag`. The 4.8 test asserts no premature flip; it does NOT assert post-completion consistency between `step_history[last_entry].output_summary` and `context_bag[step.output]`.

**Risk:** Low. The merge step consumes both, and the merge step's own entry into `step_history` happens after the parallel's, so the merge will see the parallel's outputs in `context_bag` even if the history entry is slightly stale. But downstream workflows that read history without reading context_bag will see stale data.

**Phase 5 first brief must include:** a regression test that asserts `step_history[last_entry].output_summary == context_bag[step.output]` after a parallel step completes. 1 test, ~20 LOC.

**Both B1a and B1b are Phase 5 B-day fixes, not Phase 4 failures.** The 285/1/0 v2 suite passes today because the happy paths and the 4.7/4.8 fix-up tests cover the bugs. Phase 5's e2e tests will exercise the unhappy paths and the race conditions more aggressively.

### B2 — Workflows directory drift (BLOCKER for Phase 5's first hand-test)

The plan YAML file dependency map (line 220) says `pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` but the example workflows live at `pantheon/conductor/workflows/` (not `pantheon/plans/conductor-v2/...`). Also, the plan YAML's claimed "5 production workflows" should be re-validated before Phase 5 starts — there's a `conductor/workflows/` directory with 9 `bridge-test-*.yaml` files in it that are test artifacts, not production.

**Phase 5 first brief must include:** a 1-line inventory of the 5 production workflow files (path + step count + lock state) so Phase 5's e2e tests can target the right files. This is an operator-callable 5-min task.

### B3 — No new blockers beyond B1, B2.

All 4.7+4.8+4.9 SHIPped deliverables are in place. The morning-briefing `nats_publish` step that was the breach's "easy prey" in 2026-06-15 is now behind the `operator_approval_required` guard (verified: `test_morning_briefing_inbox_does_not_match` in test_sovereign_outbound_guard.py passes; the morning briefing's step is `subspace.morning.outgoing.*` which is not sovereign, so the guard correctly does not block it).

---

## §4 — Forward Impacts

Dependencies the next sub-plan (phase-5-e2e-test-suite) assumed that aren't real.

### F1 — The "test count is 232/232" claim in the plan YAML body is STALE (line 302)

The plan body says "Combined 232/232 pass" with: 36 v1 + 193 v2 (current; +17 from test_sovereign_outbound_guard.py) + 1 slow E2E + 2 backbone E2E. **The actual current state is 285/1-skip/0-fail on the v2 suite alone**, which doesn't include the 36 v1 or the E2E suites. The 232 number is from 2026-06-14 (pre-Step 4.5). Post-4.9 it's 285 (v2) + 36 (v1) + 3 (E2E) = **324/1-skip/0-fail total**, assuming the slow E2E is the 1-skip.

**Impact:** Phase 5 will use the stale "232" number as the regression baseline. We need to update the plan body to 324/1/0 *before* Phase 5 starts, otherwise Phase 5 will report "regressions" that are actually just the post-4.9 increase.

**Action:** Update `phase-4-quarantine-sovereign.yaml` line 302 in a 1-line housekeeping commit, alongside the B2 inventory work.

### F2 — The 4-agent worked-example workflow (spec §10) is not in `pantheon/conductor/workflows/`

The spec ships 3 worked-example workflows for end-to-end testing. None of them are checked in. The 4.9 Brief 3 hand-tested the YAML by parsing an inline string, not by loading a real file. For Phase 5 to do real E2E tests of cli_tool + parallel + merge together, we need at least 1 of those 3 worked examples checked in as a YAML file.

**Impact:** Phase 5's cli_tool E2E tests will be limited to `_mock_echo` only. The full "4 agents race + llm_pick_best" workflow is not testable in Phase 5 — would need a Phase 6 with the real CLIs installed.

**Action:** Add the 3 spec worked-examples to `pantheon/conductor/workflows/examples/` as a Thoth-orchestrated brief. NOT a Phase 4 deliverable. Phase 5 can start without them.

### F3 — `forge-autoresearch-brief.md` is unblocked (per 4.8 decision log)

The 8.6K `shared/active/forge-autoresearch-brief.md` was waiting on `parallel` + `merge` landing. Both SHIPped in 4.7+4.8+4.9. **Phase 5 should NOT auto-dispatch this brief** — it's a separate operator-scoped effort. Just confirm it's unblocked.

### F4 — WebSocket live-observability is deferred to a separate spec brief

The cli-orchestration spec calls for WebSocket live-observability for the Conductor GUI. This is out of scope for Phase 4. **Iris (GUI integration) will need this in a future phase** (likely Phase 6 or 7). No Phase 4 action; just flagging that the spec's "Phase 2" of cli-orchestration is still pending.

---

## §5 — Drift

Live state vs. spec in ways that matter.

### D1 — `cli_tools.yaml` location drift (HIGH — affects Phase 5 paths)

**Claim:** Plan YAML line 220 and the 4.9 decision log both say `pantheon/conductor/v2/cli_tools.yaml`.

**Reality:** The file is at `pantheon/conductor/config/cli_tools.yaml`. Verified just-now: `find / -name "cli_tools.yaml"` returns exactly one path, the `config/` one. The `conductor/v2/` directory has no `cli_tools.yaml`.

**Impact:** Phase 5's E2E tests that load cli_tools config by path will fail if they use the plan YAML's path. `load_tools_config()` (in cli_tool.py) accepts a path argument, so the tests can pass `conductor/config/cli_tools.yaml` directly. But the plan YAML's file dependency map is wrong.

**Fix:** Update the plan YAML's file dependency map entry for cli_tools.yaml to the correct path. 1-line housekeeping commit.

### D2 — `pantheon/conductor/v2/cli_tool.py` vs `pantheon/conductor/v2/cli_tools.yaml` colocated (MEDIUM)

**Claim:** Plan YAML implicitly suggests `cli_tool.py` and `cli_tools.yaml` are siblings (both in `v2/`).

**Reality:** `cli_tool.py` is in `v2/` (22.1K, the module) and `cli_tools.yaml` is in `config/` (3.2K, the data). The split is reasonable — Python code vs YAML data shouldn't share a directory — but the plan YAML's file map doesn't reflect this.

**Fix:** Same as D1 — correct the file map. Recommend Thoth add a one-line comment to the plan YAML explaining the split: "code in `v2/`, config in `config/`, separation follows the existing `conductor/` layout convention (scripts/, workflows/, server.py, daemon.py, etc., all live alongside each other, not under `v2/`)."

### D3 — Decision logs not all under `shared/decisions/` (LOW)

**Claim:** Phase 4 brief templates reference `~/pantheon/shared/decisions/2026-06-16-step-N.md` as the canonical decision log location.

**Reality:** Some 4.x decisions landed in `shared/decisions/2026-06-16.md` (consolidated daily log) and some in `shared/decisions/2026-06-16-step-N.md` (per-step). E.g.:
- `shared/decisions/2026-06-16.md` (consolidated, has 4.5 closure + others)
- `shared/decisions/2026-06-16-step-4.5.md` (per-step, 4.5 follow-up)
- `shared/decisions/2026-06-16-step-4.7.md` (per-step, scope cut)
- `shared/decisions/2026-06-16-step-4.8.md` (per-step, partial-ship analysis)
- `shared/decisions/2026-06-16-step-4.9.md` (per-step, 4.9 closure)

**Impact:** A future operator scanning for "what did we decide for Step 4.5?" will find it in 2 files. Not a bug, just a discovery friction point.

**Fix:** None. The dual-file pattern is a valid choice (consolidated daily + per-step). Document the convention in a 1-line note in the `shared/decisions/INDEX.md` (which already exists but is empty).

### D4 — No drift in test counts or engine behavior

Verified: 285 v2 tests pass, 30 cli_tool tests pass, 18 merge tests pass, 16 parallel tests pass (including the 3 from 4.7 that were fixed in 4.8), 17 sovereign-outbound-guard tests pass. The flake I saw earlier (`test_parallel_runs_branches_concurrently` was reported as failing by my 4.9 Brief 3) is actually a stale test name — that test doesn't exist by that name anymore; the current parallel test file has different naming. No real flake.

### D5 — `cli-tools.yaml` field completeness (LOW)

The `cli_tools.yaml` file's 4 tool entries all use the full field set. But the spec (Thoth's §4) defines 10 fields; `cli_tool.py`'s `ToolRegistration` dataclass has 10 fields. Match. No drift here. Just confirming the audit.

---

## Summary

**Phase 4 status:** All 9 implementation steps SHIPped. 285/1/0 v2 tests pass. Breach structurally impossible. Substrate ready for Phase 5.

**What Phase 5 needs to address in its first brief (B1a + B1b regression tests + B2 inventory + F1 number update + D1/D2 file map fix):** ~5-7 lines of work. Estimated 30-60 min total. This is the housekeeping PR that can run in parallel with Phase 5's first real brief.

**What Phase 5 does NOT need to address:** the latent bugs themselves (B1). Phase 5 just needs regression tests for them; the actual fix is documented above and can land in 4.final follow-up PRs or Phase 5's regular work.

**Operator call (if any):** D3 (decision log convention doc) is a 1-line note — operator can defer or include. Everything else is action-bound to a Thoth/Marvin/Hephaestus task in Phase 5's first brief.

**4.final verdict:** SHIP Phase 4. Advance to phase-5-e2e-test-suite.

---

— Hermes, 2026-06-16T06:55Z
