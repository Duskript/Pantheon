# Conductor UI Phase 5 — GPT-5.5 Ponytail QA Summary

**Date:** 2026-06-18T10:13:35-06:00
**Task:** `t_98400ba6`
**Scope:** LedgerAdapter + adapter swap test + migration framework
**Verdict:** FAIL
**Confidence:** high

## Must-fix findings

1. `LedgerAdapter.healthCheck()` reports `healthy: true` even when the backend request rejects. Evidence: temporary Ponytail probe against `src/ledger_client/__tests__/ponytail_health_probe.test.ts` expected `false` and received `true`. Root cause is `src/ledger_client/ledger_adapter.ts:361`, where `this.request(...).catch(() => null)` swallows the error before the outer catch can set `healthy = false`. This makes `SmokeProbe` and migration verification unable to detect a dead backend.
2. The migration smoke probe is documented as running on every apply / boot, but `MigrationRunner.apply()` skips any migration already present in state. `002_smoke_probe` is therefore one-shot after first success unless the state file is manually edited or a new version is minted.
3. Migration idempotency is weaker than the docs claim: `001_localstub_to_ledger_adapter` checks existing task IDs against source LocalStub IDs, but `createTask()` cannot preserve source IDs and the kanban backend assigns new target IDs. A partial rerun before state is recorded can duplicate tasks.

## Verification receipts

- `./node_modules/.bin/tsc --noEmit` → exit 0.
- `./node_modules/.bin/vitest run --reporter=verbose src/ledger_client/__tests__/adapter_swap.test.ts` → 5/5 pass; `/health` MSW warning reproduced.
- `./node_modules/.bin/vitest run` → 266/276 pass, 10 failures all in `local_stub.test.ts`.
- `npm run build` → exit 0; route-tree warning reproduced, Vite build succeeded.
- Temporary direct health probe → failed as expected, proving the health false-positive bug.

## Routing

Return to Marvin for a focused Phase 5 fix cycle before acceptance. Add regression tests for the health negative path and migration apply/rollback/status/idempotency paths.
