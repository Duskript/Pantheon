# 2026-06-20 — Conductor UI Phase W2-a: §7.1 load gate pinned at component level

## Context

Kanban task `t_2cc561dc` (Phase W2-a: Template picker UI + workflow question
groups). Parent task `t_bc7c2bda` (W1c-c-c-c) shipped earlier the same day.

## What shipped

Two new component-level test files. No source code changes (the data +
components were already in place from prior partial-work commits; the gap
was test coverage at the render seam).

- `src/soulforge/__tests__/WorkflowInterview.test.tsx` (18 specs, +456 LOC)
- `src/soulforge/__tests__/WorkflowReviewStep.test.tsx` (13 specs, +243 LOC)

Commit `52d1fb9` on `feature/w1c-c-c-e2e-final`.

## Gate verification

The §7.1 gate is **"picker renders, question groups load with correct
fields per group"**.

| Surface                                            | Coverage     |
|----------------------------------------------------|--------------|
| `workflow-templates.ts` catalog shape               | 10 specs ✓   |
| `workflow-groups.ts` catalog shape + required flags | 12 specs ✓  |
| `apply-template.ts` pipeline                       | 8 specs ✓    |
| `workflow-artifact.ts` mapper                      | 14 specs ✓   |
| `render-as-workflow.ts` pipeline                   | 12 specs ✓   |
| `TemplatePicker.tsx` (renders 10 templates)        | 13 specs ✓   |
| `WorkflowInterview.tsx` (walks 6 groups)           | 18 specs ✓ (NEW) |
| `WorkflowReviewStep.tsx` (renders 6 group rows)    | 13 specs ✓ (NEW) |

**W2-a test total: 118/118 passing.** Full project: 885/895 pass; the 10
failures are the pre-existing LocalStub state-pollution + palette CSS-import
flakes from the W1c-c-c-c baseline (neither touched by W2-a).

`npx tsc --noEmit` clean.

## What W2-a does NOT cover (deferred to W2-b / W2-c)

- W2-b: `renderAsWorkflow` already exists at `src/soulforge/render-as-workflow.ts`
  with 12 tests. The Phase W2-b card is for forward-progress tracking and
  verification — the function itself was authored in an earlier WIP commit.
- W2-c: Route wiring (Workforge → /workforge?from=new-workflow, or similar)
  + end-to-end picker → render → canvas round-trip. Not in scope of W2-a.

## Files for downstream workers

- `src/soulforge/workflow-templates.ts` — 10 templates (client intake, tax
  review, collections follow-up, audit findings, post-meeting, quarterly
  review, engagement letter, monthly close, compliance review, invoice
  generation) + START_FROM_SCRATCH pseudo-template.
- `src/soulforge/workflow-groups.ts` — 6 workflow-level groups (Identity,
  Inputs, Outputs, Behaviors, Configuration, Review) with the required flags
  and enum options the §7.1 spec demands.
- `src/soulforge/TemplatePicker.tsx` — UI that renders the catalog.
- `src/soulforge/WorkflowInterview.tsx` — UI that walks the 6 groups.
- `src/soulforge/WorkflowReviewStep.tsx` — UI that summarizes the walk.
- `src/soulforge/apply-template.ts` — pure helper picker→artifact.
- `src/soulforge/render-as-workflow.ts` — pure helper artifact→definition.

W2-c needs to wire the route (probably `/workforge/new` or similar) and
complete the picker→render→canvas round-trip.

## Decision log

See `~/athenaeum/Codex-God-marvin/DECISIONS.md` 2026-06-20 entry "W2-a: pin
the §7.1 load gate with component-level tests" for rationale + alternatives.
