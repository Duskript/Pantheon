# Test-board routing for kanban validation work

When a task involves running validation tests (workflows, kanban patterns, reaction rules, skill bodies), the worker assigned often resolves "avoid polluting the production board" by **not running the test at all**. This is a real failure mode I hit on 2026-06-16 with `t_bbe6e8b5` Brief 3 closure — Marvin skipped the kanban pattern end-to-end run because the default board has live workers, even though the test was scoped to patterns.

## The fix

Name the test surface explicitly in the dispatch body. The right options, in order of preference:

1. **`test_board_xyz`** — empty board in the default install. Visible via `hermes kanban boards list`. Switch with `hermes kanban boards switch test_board_xyz` or pass `--board test_board_xyz` per-call.
2. **`--workspace scratch:<abs-path>`** — keeps the work on the default board but in a fully-isolated scratch dir, so a crashed run can't damage production workspace state.
3. **`--tenant <name>`** — namespaces the task to a tenant (e.g. `--tenant brief3-closure`) so the kanban history is partitioned but workers run on the default board. Good for "this work belongs together" scenarios.

The bad option: dispatch the test on the default production board with no surface flag and trust the worker to figure it out. They'll either run it (risky) or skip it (lossy). Don't.

## How to encode it in the dispatch body

In the body of the kanban task, include a line like:

> **Test surface:** `--board test_board_xyz` (or `--workspace scratch:<path>` per call). Do NOT use the default board. This task is validation; production workers should not see it.

If the task creates child tasks, the children need the same flag — and you may need to verify after the run that nothing landed on the default board. A `hermes kanban list --board default` filter right after the validation run catches any leaks.

## Detection of the failure mode

If a task comes back with `result: SHIP` but the body says "verification deferred to avoid polluting default board" or "end-to-end execution deliberately deferred", that's this failure mode. The right response:

- **Don't accept the deferral.** The whole point of the test was to run it.
- **Re-dispatch** with the test surface flag explicit in the body.
- **If the worker can name a specific blocker** (e.g., "test_board_xyz doesn't have fixtures installed"), solve that blocker, don't blame the worker for not running.

## Why this is a class-level skill, not a one-off note

Any task that's *verifying* something — a workflow, a reaction rule, a CLI tool, a UI flow, a skill body — needs a test surface. The dispatcher will keep spawning workers; the workers will keep facing the same production-board pressure. Without an explicit test-surface flag in the body, every verification task is at risk of being silently dropped.

## Related

- `build-plan-orchestrator/references/hermes-kanban-cli-verified.md` — the working CLI surface, including the `--board` and `--workspace` flags
- `kanban-orchestrator` skill — the dispatch playbook
