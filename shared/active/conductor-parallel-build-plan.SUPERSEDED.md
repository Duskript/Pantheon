# SUPERSEDED — Conductor Parallel Work Build Plan (v1.0, Marvin, 2026-06-16)

**This document is superseded as of 2026-06-16T04:50Z.**

The build plan at `~/pantheon/shared/active/conductor-parallel-build-plan.md` (26.5K, written by Marvin during Step 4.7 Brief 1) describes a **5-week, 3-workstream implementation** of the full `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` v1.0.0 spec:

- **Stream A** — CLI Orchestration (cli_tool + parallel + merge + WebSocket + cli_tools.yaml)
- **Stream B** — Forge Autoresearch (the consumer)
- **Stream C** — Conductor GUI (the visibility)

## Why superseded

The operator's call on 2026-06-16 (option "C") was: **build `parallel` + `merge` only, defer `cli_tool` + WebSocket + GUI + worked-example workflows to separate briefs.** The full 5-week, 3-workstream plan in this document is not the operator-scoped Step 4.7 work.

**Operator decision log:** `~/pantheon/shared/decisions/2026-06-16-step-4.7.md` (6 decisions recorded, all locked).

**Fix-up scope log:** `~/pantheon/shared/decisions/2026-06-16-step-4.8.md` (Step 4.8 = test fixes + this sidecar + DECISIONS.md update + handoff drop).

## What IS in scope (current Step 4.7 work)

- `parallel` step type in `engine.py:_execute_step` — branches run concurrently, `fail_mode` (fast/slow/ignore), `max_concurrency` enforced, nested up to 3 levels
- `merge` step type — 6 strategies (concat, first, diff, vote, llm_summarize, llm_pick_best); LLM strategies reuse engine's existing `llm_call` path
- Backwards compat with existing 6 workflows
- ≥20 new tests across `test_parallel.py` + `test_merge.py`

## What is NOT in scope (still deferred)

- `cli_tool` step type (Thoth's spec §2.1) — separate brief if/when wanted
- WebSocket live-observability stream (Thoth's spec §3) — separate brief
- Conductor GUI integration (Iris's mock at `http://100.68.106.59:8889/`) — separate Phase 5+ work
- 4-agent worked-example workflow (`claude-x-codex-marvin-hephaestus-feature.yaml`) — separate brief after `cli_tool` ships
- Forge Autoresearch (Stream B) — separate brief, unblocked once Step 4.7 SHIPs cleanly
- The 15 open questions in §5 of the superseded plan — most are answered in `2026-06-16-step-4.7.md` for the parallel+merge subset. The cli_tool-specific questions (cli_tools.yaml location, WebSocket auth, tool-not-installed behavior) are not relevant until cli_tool work is dispatched.

## If you want to pick this plan back up

1. The full 26.5K build plan is preserved verbatim at `~/pantheon/shared/active/conductor-parallel-build-plan.md` (no destructive edit)
2. The Thoth spec is at `~/athenaeum/Codex-Pantheon/specs/conductor-cli-orchestration.md` (26.5K) and is the authoritative contract
3. The relevant Athenaeum specs and briefs linked in the plan are all still on disk
4. Open a new Phase 6 plan (or whatever number) in `~/pantheon/plans/conductor-v2/` and start with Step 6.1 = `cli_tool` per Phase 1 of Stream A

## What Marvin got right

The build plan structure (3 streams, 5 weeks, dependency graph, week-by-week plan, success criteria, risks) is **solid planning work** — it's the right shape for the full spec. The error was scope (operator said "C", plan wrote "A+B+C"). Not a quality problem with the plan itself.

— Hermes, 2026-06-16T04:50Z
