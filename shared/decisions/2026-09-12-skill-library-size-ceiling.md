# 2026-09-12 — Skill-library SKILL.md size ceiling blocks in-sweep state updates

**Source:** Marvin Dojo skill-crystallization sweep, run
`skill-crystallization-20260912T140259Z-zero-create-active-session-overlay-precedence-claim-falsified`.

## Decision

An oversized `SKILL.md` is treated as a **routing signal**, not a retry target. During the
2026-09-12 crystallization sweep, the patch to `memory/marvin-dojo-crystallization-state` was
refused (121,842 chars on disk; the attempted head swap would have produced 122,777 vs the
100,000-char limit). The patch was **not retried**, and **no reference file was written** under
that umbrella, because a support file without a pointer from its umbrella is orphaned.

The run's canonical evidence therefore lives in the per-run artifact, batch note, and the
`__no_candidate__` + summary rows across the five Dojo ledgers. The refusal is recorded in the
artifact (`skill_state_update`) and in a correction object (`correction_sequence=2`) so the
omission is auditable rather than silent.

## Rationale

- `skill-library-mutation-safety` §Oversized target requires exactly this: do not repeatedly retry
  `skill_manage`, and do not split the oversized original inside a scheduled sweep.
- The sweep's reusable lesson (a minimal `correction_of` object is not a valid ledger tail entry —
  the tail must satisfy the union of both ledger contracts) is **already documented** at
  `hermes-dojo-skill-crystallization/SKILL.md` line 300, so no duplicate patch was made.

## Blocker for follow-up (foreground maintenance, owner-directed)

Three skills are at or over the 100,000-char `SKILL.md` limit and can no longer be patched:

| Skill | chars |
|---|---|
| `memory/marvin-dojo-crystallization-state` | 121,842 |
| `pantheon/skill-library-curation` | 102,483 |
| `hermes-dojo-skill-crystallization` | 100,061 |

Compaction recipe (separate work): move the archived `## Previous active pool` chain
(pre-2026-09-05) out of `marvin-dojo-crystallization-state/SKILL.md` into
`references/run-state-archive-*.md`, keep SKILL.md to a current-head summary, and verify the
archive is a byte-exact substring of the original before shrinking.

## Alternatives considered

- **Compact in-sweep:** rejected — a 121KB memory blob rewrite inside an unattended hourly cron is
  too destructive for the benefit; the discipline assigns it to foreground maintenance.
- **Create a fresh state skill:** rejected — that is the prohibited duplicate-umbrella bypass.
- **Silently skip the state update:** rejected — the omission is now recorded in the artifact,
  batch note, and ledger correction.

**Reversibility:** high. The artifact and ledgers are append-only; compaction is additive.

## Correction (appended 2026-09-12T15:00Z — run `skill-crystallization-20260912T150048Z-zero-create-active-session-drift-forecast-validated`)

The blocker table above lists `hermes-dojo-skill-crystallization` at **100,061**. Measured in the unit the tool actually enforces (characters — `len(path.read_text())`), that skill was **99,887**. The 100,061 figure was the `wc -c` **byte** count. It was never over the ceiling, and the 15:00Z sweep patched it successfully: a new `references/2026-09-12-drift-forecast-validation.md` plus a body pointer, size-neutral after merging two duplicate "durable update" bullets (now **99,750** chars, 250 headroom).

Genuinely at/over the limit: `memory/marvin-dojo-crystallization-state` (121,812 chars) and `pantheon/skill-library-curation` (102,003 chars) only.

The generic byte-vs-character rule already lives at `skill-library-mutation-safety/references/2026-09-12-near-limit-target-self-overflow.md`; this note corrects the *instance* in the table above, not the rule. The table is preserved unmodified (append-only).
