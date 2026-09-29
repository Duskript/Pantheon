# 2026-08-06 — Skill crystallization: pool 403017-403090 equilibrium

## Decision

Pool 403017-403090 has reached equilibrium in the Hermes Dojo skill
crystallization pipeline. Suppress from future mining. Don't re-evaluate
on subsequent ticks.

## Context

- Pool surfaced at 2026-08-05 22:05Z (1st tick, marvin profile)
- Equilibrium declared at 2026-08-06 00:01Z (3rd tick, 3-of-3 same verdict)
- Confirmed in 2 post-equilibrium runs (01:04Z, 02:01Z)
- Pool signature: 10 IDs (403017, 403028, 403034, 403045, 403068, 403069,
  403071, 403084, 403089, 403090), all `god_name=default`, 7× commitment
  + 3× insight, importance 80.0, raw_text truncated 90-181 chars,
  created_at burst 2026-08-05 20:29:41–20:29:52 (11 seconds)
- Session: `20260805_101022_337136`
- All 10 candidates fail the 3-criteria test (general pattern? future
  time-saver? 5-15 step workflow?). All have existing skill homes.

## Rationale

Per the equilibrium protocol documented in the marvin Dojo
crystallization skill, 3 consecutive ticks of the same ID set with the
same zero-skill verdict is the suppression signal. The pool is now 5
ticks deep with the same verdict each time, which is well past the
threshold.

## Out-of-scope findings (still open, deferred)

1. **Ichor retrieval bug pointer** — Ichor's 4/4 health gate is supposed
   to enable memory search but doesn't. Some of the pool's
   chat-fragments referenced this. Eventual patch:
   `devops/pantheon-memory-system`. Requires full conversation context
   (raw_text truncated).
2. **Cron-overlap at midnight** — multiple tasks scheduled at
   `0 0 * * *` (Hades Nightly Consolidation + others). Some of the
   pool's chat-fragments referenced this. Eventual patch:
   `devops/recurring-task-reliability`. Requires full conversation
   context.

Neither is applied here because the data needed to write an honest
patch (full raw_text beyond the 300-char truncation) is not accessible
without re-opening the source session.

## Drift observations (also still open)

The 01:04Z tick introduced a rich sweep-entry log format that:
- Uses the singular key `consecutive_no_create_estimate` instead of
  the expected plural `consecutive_no_create_runs` (per
  `references/cron-instructions-drift.md` Trap 3)
- Coexists with the simple `__no_candidate__` row format in the same
  file, with no schema-level disambiguation
- Contains a `reason` field with an off-by-one in the tick number
  ("3rd_sweep" when it was the 4th)
- Has a clock-skew reference ("02:00Z run" when the run was at 01:04Z)

If the verifier accepted the 01:04Z entry silently, the verifier may be
missing the key-name check, or the key-name check has been silently
relaxed. Worth a targeted audit.

## References

- Equilibrium declaration: `~/.hermes/profiles/marvin/skills/hermes-dojo-skill-crystallization/references/2026-08-06-0001-equilibrium-completed-pool-403017-403090.md`
- Rich sweep-entry reference: `~/.hermes/profiles/marvin/skills/hermes-dojo-skill-crystallization/references/2026-08-06-0104-rich-sweep-entry-format-pool-403017-403090.md`
- Drift traps: `~/.hermes/profiles/marvin/skills/hermes-dojo-skill-crystallization/references/cron-instructions-drift.md`
- State skill: `~/.hermes/profiles/marvin/skills/memory/marvin-dojo-crystallization-state/SKILL.md`
- This run's batch note: `~/pantheon/hermes-dojo/logs/batch-notes-2026-08-06-0201-crystallization-marvin.md`
- Thoth 01:00Z digest noting the crystallization job is now `enabled: false`: `~/pantheon/shared/athenaeum-writes.md`
