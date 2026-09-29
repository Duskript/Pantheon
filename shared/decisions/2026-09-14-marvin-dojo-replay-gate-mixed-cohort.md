# 2026-09-14 — Dojo replay gate: mixed-source cohorts can now reach an exact-replay verdict

**Decision (Marvin, Dojo skill-crystallization cron, 2026-09-14T15:00Z):**
`scripts/verify_frozen_pool_replay.py` no longer requires `all candidates share one source session`
when the pool is mixed on **both** sides (the live cohort and the prior artifact's cohort).

## Rationale

The first mixed bulk-ingestion cohort (sweep #21, `2026-09-14T14:05Z`) proved the cohort class can
freeze like any other. Its successor sweep returned the identical ordered pool, but the gate printed
`11/12 exit 1` + `VERDICT: DISTINCT POOL` **while `ordered-ID equality` PASSED**.

Root cause: the singleton predicate is a pure function of the live cohort — it consumes no `prior`
input — so it fails on *every* sweep over a mixed cohort, an exact replay included. Exit `0` was
therefore structurally unreachable for that class, and the gate's own dedupe path could never fire.

Consequence of obeying the printed verdict: a duplicate sweep — 10 helper rows + a duplicate summary
in both ledgers + a duplicate batch note — for a byte-identical pool.

## Alternatives considered

1. **Document-only** (leave the script; teach the operator to override). Rejected: the same sweep
   line already caused duplicate rows on 2026-09-13T09:01Z when an operator followed a printed
   verdict literally.
2. **Drop the singleton check entirely.** Rejected: it is a genuine shape fact for single-session
   cohorts and cheap to keep in the report.
3. **Require session equality against the prior cohort's multiset.** Chosen, in its simplest form:
   waive only when both sides are mixed.

## Safety argument

`same_order` (ordered-ID equality) remains the verdict's first conjunct, so a genuinely distinct
pool still exits `1` through it. Fail-safe preserved: an unexpected error still degrades to exit `2`,
never to a wrong verdict.

## Evidence

Fresh ad-hoc harness retained at `/tmp/hermes-verify-ybajrAj2/`
(`RESULT-mixed-cohort-waiver.txt`, `verifier-mixed-cohort-waiver.py`): **23/23 PASS**, exit 0.
Cases: mixed replay → 0; distinct pool → 1 (regression witness); missing DB → 2 with no verdict;
single-session replay → `11/11` exit 0 with the waiver absent; mixed live + unknown prior shape →
waiver must NOT fire. Production invariant asserted in-run: both Dojo ledgers, the 14:05Z artifact,
and the shared sink byte-identical before/after.

## Reversibility

Single-file change, two boolean lines plus one read-only helper. Revert the `both_mixed` clause to
restore the previous (over-strict) behaviour. Reference documentation: same commit —
`references/2026-09-14-mixed-bulk-ingestion-cohort.md` §2/§5,
`references/pinned-replay-verifier-contract.md`.
