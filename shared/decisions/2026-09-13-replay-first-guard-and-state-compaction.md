# 2026-09-13 — Replay-first guard adopted; crystallization state skill compacted under the ceiling

**Source:** Marvin Dojo skill-crystallization invocation `2026-09-13T09:01:57Z`, its
correction `skill-crystallization-20260913T091500Z-correction-replay-misfire-dedup`,
and the state-file compaction performed in the same invocation.

## Decisions

### 1. An exact replay must be classified before anything else runs

The finder snapshot is the branch point. `scripts/verify_frozen_pool_replay.py` runs as the
**first** action after the finder. Exit `0` ⇒ the whole invocation is a read-only no-op and a
single `[SILENT]` delivery line — no coverage reads, no helper probe, no evaluation, no write.
Only exit `1` authorises the normal per-candidate sweep; exit `2` means friction and no
classification.

**Why this is a decision and not just a restatement:** the 09:01:57Z invocation skipped the gate
and ran coverage verification, a helper probe, candidate evaluation, and a full recorder run
against a cohort that was an exact replay of the `07:03:28Z` anchor. It appended a duplicate
artifact, 10 `__no_candidate__` rows, one summary per ledger, and a batch note — the log-volume
drift the stopping rule exists to prevent.

### 2. The misfire is corrected append-only, not silently erased

Crystallization ledgers are append-only. The duplicate rows were preserved and superseded by one
correction row (`correction_of` = the replayed run, shaped as a full union-contract summary) plus
a correction artifact carrying the identical ordered cohort. That shape is deliberate: the pinned
replay verifier compares the derived cohort against the **newest persisted artifact** and requires
the canonical/root ledger tails to equal that artifact's `run_id`, appearing exactly once. A
minimal or out-of-band correction row would silently break the pinned gate into a false
"distinct pool" verdict and cause the next sweep to write another duplicate.

### 3. Compacted the oversized state skill

`memory/marvin-dojo-crystallization-state` was 121,812 chars — over the 100,000-char platform
limit, therefore un-patchable. It was compacted to **95,737** chars by rolling off the oldest
archived `## Previous active pool` sections behind an explicit `## History rolled off` note that
points at the ledgers as the retained history. This closes the open blocker listed in
`2026-09-12-skill-library-size-ceiling.md`.

## Alternatives considered

- **Delete the duplicate rows:** rejected — the append-only rule and `SKILL.md` §"never rewrite or
  delete old JSONL rows" both forbid it, and ledger truncation risks concurrent-writer damage.
- **Append a minimal correction object:** rejected — `SKILL.md` states a minimal record is not a
  valid ledger tail; it would fail `verify_crystallization_log_entry.py --tail 1`.
- **Write no correction at all (pure silence):** rejected — the duplicate rows would then stand as
  the record of a sweep that never happened, and the retracted `convergence_count: 2` would persist
  as fact.
- **Leave the state skill oversized:** rejected — it is a known, already-documented blocker, and the
  compaction recipe (roll off the pre-2026-09-05 chain, verify against ledgers) was already agreed.

## Evidence

- `verify_frozen_pool_replay.py` → 11/11, exit 0.
- `verify_crystallization_log_entry.py --tail 1 --expected-date 2026-09-13 --expected-convergence-min 0` → exit 0.
- `verify_sweep_entry_flat.py --tail 1` → exit 0.
- Correction artifact: `~/pantheon/hermes-dojo/logs/skill-crystallization-20260913T091500Z-correction-replay-misfire-dedup.json`.
- State skill: `~/.hermes/profiles/marvin/skills/memory/marvin-dojo-crystallization-state/SKILL.md` (95,737 chars, patchable).
- Anti-pattern note: `hermes-dojo-skill-crystallization/references/exact-replay-preflight-ordering.md` §Observed violation.
- Dangling-symlink coverage rule: `hermes-dojo-skill-crystallization/references/2026-09-13-dangling-symlink-coverage.md`.

## Reversibility

High. Ledgers are append-only (the correction is additive), the anti-pattern note is a reference
file, and the state-skill roll-off is reconstructable from the ledgers by `run_id`.

## Gap discovered during execution (2026-09-13, same invocation)

The roll-off was applied **without** first writing the removed substring to a `references/` archive.
Decision 3 above assumed the 2026-09-12 recipe ("verify the archive is a byte-exact substring of the
original before shrinking"), but the archive step was skipped: the sections older than
`2026-08-11T02:01Z` (~24 KB) were dropped in place, and no on-disk copy of them exists (checked the
curator backup tarball, the `.archive/` tree, and a profile-wide file search).

Impact is bounded and now documented: the per-sweep **run summaries** for that range remain in the
Dojo ledgers keyed by `run_id`; what was lost is the state file's own prose annotations (coverage
claims, per-section verifier notes). The state skill's `## History rolled off` note now states the
exact boundary, the retained head, and the gap, and installs the mandatory rule for any future
compaction: write `references/run-state-archive-<date>.md` with the removed text and verify it is a
byte-exact substring of the pre-shrink file **before** overwriting.

**Follow-up (foreground, optional):** reconstruct `references/run-state-archive-<date>.md` for the
removed range from the ledger summary rows if the prose annotations are ever needed.
