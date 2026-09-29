# 2026-09-16 — Marvin: Dojo sweep #50 decisions

Run: `skill-crystallization-20260916T070200Z-zero-create-whole-session-skill-document-reingest-fragment-pool`
(marvin profile, sweep clock `18:00:39Z`). **Exact frozen-pool replay for the 11th consecutive
sweep** — finder returned the unchanged cohort `2350730, 2350729, 2350728, 2350727, 2350726,
2350725, 2350724, 2350723, 2350618, 2350617`; gate `verify_frozen_pool_replay.py --days 1` →
**11/11, REAL exit 0**. Zero-create: 0 skills created, 0 patched, no Dojo sink write.

**Decision 1 — CARRY OUT the N=11 collapse that #49 budgeted, rather than defer it a second time.**
Rationale: the byte criterion fired at N=9 (34,559 chars at N=11 = **1.52×** the trigger's own
old-calibration unit `12 × ~1.9 KB ≈ 22,800`), the entry count reached the **terminated predecessor
block's own length** (N=11 — the convention's literal calibration), and the block is expected to
terminate only at the ~`2026-09-17 06:07Z` distinct-pool sweep, i.e. ~12 more entries away without a
collapse. Alternatives considered: (a) append an 11th line and defer again — rejected, it reproduces
exactly the incident-dump growth the convention exists to prevent; (b) wait for termination to make
the collapse moot — rejected, the block survives termination as a closed block and would then carry
~23 entries. Cost accepted: the collapse replaces the per-entry freeze snapshots this record has been
relying on (the per-entry global-max-id progression now lives in the run-state doc and the roll-off
archives). Evidence: pre-collapse block 10 entries / 34,559 chars / 12 lines; sink
`187,880 → 155,922` bytes, `407 → 398` lines, `delta=-31,958`; `COLLAPSE_OK`; `--verify-only`
`VERIFIED_OK`; re-`--commit` exit **3** `delta=0`. Reversibility: LOW — the sink is append-only with
a one-write budget and no `--force`; a pre-image backup was taken
(`/tmp/marvin-skill-crystallization.pre-collapse-20260916T1800Z.md`, sha256 `6d1856fb…`) and the
numbers are preserved as `## History rolled off` entry 11 in the run-state doc.

**Decision 2 — widen the collapse guard's `REPLAY_RE` a THIRD time (and pin the shape set in the
contract test), rather than treat the refusal as a data problem.**
Rationale: the guard refused on the first attempt (exit 2) because the 2026-09-15 pattern required the
bullet bold to close immediately after the digits, while this block's appender writes the cohort name
*inside* it (`- **<ts> — recurrence 1 of the new cohort** (marvin): …`). A probe measured **3/10
matched, 7 refused** — all genuine replay lines — and the refusal message again accused them of being a
"distinct-pool record". This is the **third instance of the class in two days, one per block**, so
fixing the regex without pinning would invite a fourth. Alternatives: hand-repair the block (rejected —
that is the drift the pinned scripts exist to prevent); `--force` (forbidden — would re-collapse a
1-line block and destroy the audit line's provenance); leave the guard and hand-collapse (rejected —
same hand-rolled drift). Evidence: `scripts/collapse_recurrence_block.py` bullet alternative widened to
`— recurrence \d+[^*]*\*\*` plus a dated docstring provenance entry;
`scripts/verify_collapse_recurrence_block.py` gained check group 10 (a live-shape matrix run *through
the tool*: 4 accepted shapes, 4 distinct-pool shapes that must still refuse); contract now **27/27**
`COLLAPSE_CONTRACT_PASS`. Reversible: HIGH (a widening whose refusal semantics are asserted unchanged).

**Decision 3 — record and fix TWO defects in the guard's own contract test instead of working around
them.**
Rationale: both surfaced on the first run and neither was evidence about the sink. (a) The
`OLD_RE` negative control (`removal matcher fires on the pre-image`) had been **RED on a correct
artifact** since the fixture changed — `OLD_RE` required an ordinal (`\(\w+ recurrence`, e.g. "(2nd
recurrence") while the fixture writes "(recurrence of the new cohort)". Fixed by loosening `OLD_RE`
to `\((?:[\w-]+ )?recurrence`, **not** by changing the fixture, because the control's purpose is
"does the removal matcher fire at all". (b) The first draft of check 10 expected a **refusal** for a
`## <ts> — sweep …` line, but a `## `-prefixed line is a **section boundary**, not a block line, so
it can never sit inside the open block and the collapse legitimately succeeded. Reframed and asserted
as such; a bullet-shaped distinct-pool record (`- **<ts> — sweep #N**`) was added as the real refusal
probe for that class. Per the checker-defect discipline: a checker bug is not ledger evidence —
correct the disposable checker, rerun against the same persisted evidence, and report the defect
count and class. Reversible: HIGH.

**Decision 4 — pin the new ordering rule: for a COLLAPSE sweep, the pre-compose scan must include the
collapse tool's own `--dry-run`.**
Rationale: point 7 of the replay-verifier contract mandates scan-before-compose, but the payload here
was composed before the tool ran, so the dry run's refusal was discovered *after* the payload was
written — and a guard refusal is itself a scan outcome. Consequence observed: the committed collapsed
line's write-set field under-names the sweep (it names the collapse and the state-doc sync, not the
two script fixes), which is point 8(b)'s "composition-time claim" hit at the composition step rather
than after the append; the sink's one-write budget meant it could not be repaired. Landed as rule 7 of
`references/2026-09-15-collapse-guard-format-drift.md` §Gap 3 and recorded in §4b of the
collapse-budget reference. Reversible: HIGH (documentation only).

**Decision 5 — run roll-off 11 in the same pass, with `--date 2026-09-16i`.**
Rationale: the #50 head sync added **+9,366 chars** (a new high for the recorded sync band, because
this sweep's sync was a collapse+delta sync rather than a replay append), taking the run-state doc to
89,708 chars — 10,292 chars of headroom, **below** the ~10,416-char distinct-pool binding unit, so a
distinct-pool sync would have been refused. This **FALSIFIED #49's trigger-half forecast** ("roll-off
11 is NOT expected"), for the second consecutive sweep and for the same root cause: extrapolating a
band *edge* rather than the pessimistic *high* — and here the band itself did not apply, because the
sync class changed. New rule pinned in the doc: **the sync-size band is conditioned on the sync
CLASS**; a collapse sweep must be budgeted at or above the highest observed value. `--date 2026-09-16i`
was correct because the `h` stamp was burned by roll-off 10, and the archive destination was
`ls`-checked absent before the write. Removed the sweep-#44/#43 sections (13,845 chars) to 75,863 chars
/ 24,137 headroom, archiving them byte-exact first
(`references/run-state-archive-2026-09-16i.md`, 14,327 chars). Reversible; archive preserved.

**Verification (final, all read-only after the writes):** gate **11/11 exit 0**;
`verify_crystallization_log_entry.py --tail 1 --expected-date 2026-09-16 --expected-convergence-min 0`
exit 0 (consec 29, convergence 0); `verify_sweep_entry_flat.py --tail 1` exit 0 (its convergence-0
per-candidate NOTE is the known advisory); collapse contract test **27/27 exit 0**; Dojo sinks
unchanged at **2296 / 703 / 126** lines with mtimes `2026-09-16T07:20:51Z` (all predating the sweep
clock) and the anchor artifact still the newest by mtime.
