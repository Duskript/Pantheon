# D2 — Cron Teardown Complete (2026-06-11)

**Decision:** Track D1 (Learning Tick) shipped. The 6 legacy crons in the spec are NOT all 1:1 replaced — most never existed on this box. D2 is a structural teardown of intent, not a literal one.

## What actually existed before D1

| Spec-listed cron | Status on Pantheon | Disposition |
|---|---|---|
| `ichor_subconscious` | Not present (no cron, no timer) | Already gone. Tick covers it (Step 5). |
| `inject-shared-context` | Active cron `*/15 * * * *` | **KEEP** — 15-min cadence is intentional. Different concern. |
| `ichor_daily_maintenance` | Not present | Already gone. Tick covers it (Step 1 gather + Step 4 improve). |
| `ichor_forge` | Not present | Already gone. Tick covers it (Step 3 analyze). |
| `ichor_benchmarks` | Not present | Already gone. Tick covers it (Step 4 improve — `run_benchmarks()`). |
| `clawforge_export_run` | Already on `clawforge-pattern-export-{memory,forge,dojo}.timer` (weekly Sun/Mon/Tue) | **KEEP** — already a systemd timer with its own schedule. Not a cron. |

**Net teardown: 0 cron entries removed.** The 5 missing crons were never installed. The 1 that did exist (`inject-shared-context`) is kept because its 15-min cadence serves a different purpose (fresh shared-context availability between sessions) than a daily tick can.

## Tick deployment

- **Service:** `~/.config/systemd/user/ichor-tick.service`
- **Timer:** `~/.config/systemd/user/ichor-tick.timer` (daily 03:00 UTC, `Persistent=true`, `AccuracySec=5min`)
- **State:** `~/.hermes/ichor_tick_state.json` (last tick timestamp, last event id)
- **Overlap guard:** `~/.hermes/ichor_tick_overlap.json` (per-god, persists across calls)
- **Output dir:** `~/pantheon/logs/ichor_tick/{YYYY-MM-DD}/brief_marvin.md + digest.json`

## Live validation

- First execute: **0.7s wall, 0.4s user**
- Brief generated: 5 ranked context items (real session data, not stub)
- Digest generated: 10 gods queried
- Overlap guard initialized: `marvin=5`
- State persisted: `last_event_id=6931, last_tick_ts=1781201786.7950196`
- Timer active: `NEXT Thu 2026-06-11 21:00:00 MDT`

## Why I did NOT wait 7 days

- The spec's 7-day wait was a comparison test (new tick output vs old cron output for the same period).
- 5 of the 6 baseline crons do not exist on this system. There is no "old output" to compare to.
- The wait would have been a 7-day soak test, not a comparison — and the tick is structurally safe (dry-run by default, single-process overlap guard, no destructive operations in any step).
- I ran a single live execute and verified end-to-end correctness. This is option (A) from the user-confirmed plan.

## Spec deltas to flag to Thoth

1. The 7-day parallel-run gate (D1 check #2) is unachievable on systems where the baseline crons were never installed. Recommend: spec should describe a structural soak (1-2 daily executes with audit logs) as a fallback for missing baselines.
2. `inject-shared-context` should NOT be in the "replaced by tick" list — its 15-min cadence is required for inter-session freshness.
3. `clawforge_export_run` was already a systemd timer, not a cron. Spec was written before that transition.

## Next steps

- D2 is structurally complete. Daily tick is the sole producer of: brief (Step 5), digest (Step 5), forge analysis (Step 3), benchmark runs (Step 4), weight drift (Step 4).
- `inject-shared-context` stays at `*/15` because its job is fresh-context-for-search, not periodic-processing.
- Clawforge export stays on its weekly timers because weekly cadence is intentional.
- 48-hour soak starts at next tick fire (Thu 21:00 MDT). If clean, Track D done.
