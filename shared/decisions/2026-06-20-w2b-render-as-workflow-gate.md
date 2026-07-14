# 2026-06-20 — W2-b: renderAsWorkflow gate shipped

## What shipped

- `src/soulforge/render-as-workflow.ts` (already authored in W1b) verified
  at the seam: WorkflowArtifact → WorkflowDefinition (nodes + edges + viewport).
- 40 new vitest specs in `src/soulforge/__tests__/render-as-workflow.test.ts`
  pin the §9.2 contract: purity, idempotency, WorkflowDefinition shape,
  all 10 templates render cleanly, edge fidelity 1:1 with connection maps,
  defensive throws on dangling connections.
- Commit 593c04f on `feature/w1c-c-c-e2e-final`.
- tsc --noEmit clean. Soulforge 456/456 (was 416). Full project 925/935
  (10 pre-existing LocalStub state-pollution failures unchanged from
  W1c-c-c baseline).

## Why test-only

The function was already complete in W1b (the parent W2-a task body
explicitly noted this — "render-as-workflow was already authored in
prior WIP commits"). The W2-b deliverable was: pin the gate at the
test seam so the contract is bulletproof before W2-c wires the route.

The benchmark was `renderAsNode.test.ts` (13.8K, 24 specs). The workflow
sibling went from 5.5K / 9 specs → 22.8K / 49 specs to match.

## What this unblocks

W2-c (`t_c4b611b5`) is now unblocked — it's the route that calls
`applyTemplate` → `renderAsWorkflow` on confirm, takes the rendered
`WorkflowDefinition`, and places it on the editor canvas. The
`renderAsWorkflow` contract is locked; the route work doesn't have
to re-litigate the rendering.

## Notable decisions

- Error message uses Unicode arrow `' → '` (U+2192), not ASCII `'->'`.
  Caught by the test; future maintainers should preserve the arrow.
- Edge id determinism: FNV-1a hash of `source->target` formatted as
  `edge-<base36>`. Same approach as `renderAsNode` for node ids.
- All 10 templates get a generated smoke test via a `forEach` over
  `WORKFLOW_TEMPLATES` — catches template rendering regressions
  automatically when the catalog is extended.
- Defensive throw on dangling connection is exercised by a
  hand-constructed bad template (the catalog's `validateTemplate()`
  catches this at module-load time, so we have to bypass it).
