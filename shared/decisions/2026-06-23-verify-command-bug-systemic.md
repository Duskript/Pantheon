# 2026-06-23 — verify-command bug confirmed systemic across the conductor-ui build

**Decision:** Treat the card-spec verify command `npx tsc --noEmit <single-file>` as broken. Workers should default to `npx tsc --noEmit` (no args, project-level check) for verification and document the override in their handoff.

**Rationale:** Three separate build cards in this chain hit the same misconfigured command:

1. **t_96ed2a4d** (the parent task that first documented the bug) — 30+ spurious errors per JSX file.
2. **t_cf54d892** (P016 — View Runs link) — second occurrence, root-caused to `tsc --noEmit <file>` bypassing `tsconfig.json`.
3. **t_b9abe635** (P048 — Dispatch button, this run) — third occurrence, same root cause. The single-file tsc returns 30+ spurious errors while project-level tsc shows 0 errors in `src/editor/dispatch.tsx`.

The single-file command is technically valid TypeScript syntax but evaluates the file in isolation — no `jsx`, no `paths`, no `lib`, no `target`. Every JSX file fails immediately because `<div>` isn't recognized without the project's `jsx: "react-jsx"` setting from `tsconfig.json`.

**Alternatives considered:**
- Patch each card's verify command individually. Rejected — the card contract is read-only at dispatch time, and operators don't want to re-author cards to fix a tooling smell.
- Add a Makefile target `make verify-<card>` that wraps the correct command. Rejected — too much scaffolding for a 1-line fix.
- Default to project-level `tsc --noEmit` in worker discipline. **Chosen.** The verify command is informational in the card body, not contractual. Workers that follow the spec literally produce noise.

**Evidence:**
- `npx tsc --noEmit src/editor/dispatch.tsx` → exit 2, 30+ spurious JSX errors
- `npx tsc --noEmit` → 0 errors in `src/editor/dispatch.tsx`, errors only in unrelated files (kanban/__tests__/card-block-reason.test.tsx, drawer-controls.tsx, MobileBoard.tsx)

**Reversibility:** Add a `verify.command.allow_file_override` flag to the contract schema (separately, as its own dispatch card) and revert workers to the spec-literal path. Until that lands, the workaround stands.

**Follow-up:** When Hephaestus re-issues the conductor-ui Phase 8 acceptance sweep, fix the card-authoring template so verify commands default to `npx tsc --noEmit` (project-level) for any TS/TSX card. Filed for next planning cycle.