# Phase 4: Demeter — Specification

**Created:** 2026-04-24
**Ambiguity score:** 0.18
**Requirements:** 4 locked

## Goal

Implement Demeter as a background service within `_athenaeum` that watches live Codex paths for file changes, batches events through a 5-second settle window, regenerates indexes, and schedules nightly Underworld maintenance jobs.

## Background

After Phase 3, all Underworld operations work but nothing triggers them automatically. Index regeneration in Phase 1 is synchronous and fires inline with `save()` — it cannot detect external file changes and blocks the write path. File changes made outside agent-zero (vault migrations, manual edits, bulk imports) are invisible to the system. Demeter fixes all three: she watches the filesystem with watchdog, debounces events through a settle window, regenerates only affected indexes, re-triggers Mnemosyne embedding, and owns the cron scheduler that fires Hades and Fates nightly.

## Requirements

1. **File watcher with settle window**: Demeter watches live Codex paths and batches file events into single index regeneration jobs.
   - Current: Index regeneration is synchronous within `save()` and does not respond to external file changes
   - Target: `helpers/demeter.py` starts a watchdog file observer on all live Codex paths; file create/modify/move events are queued; after 5 seconds of inactivity (settle window), all queued paths are processed in a single index regeneration pass; `archive/` and `Staging/` paths are excluded from watching
   - Acceptance: Creating 5 files in quick succession triggers exactly 1 index regeneration job (not 5); a file created by an external process triggers index regeneration; a file in `archive/` does NOT trigger regeneration

2. **Index regeneration with Mnemosyne notify**: After the settle window, Demeter regenerates affected INDEX.md files and triggers Mnemosyne re-embedding for changed files.
   - Current: Synchronous index regeneration in Phase 1 called inline from `save()`; no file watcher
   - Target: Demeter's regeneration job receives the list of changed paths, computes the minimal set of affected indexes (file's folder + all ancestors to Athenaeum root), regenerates each; then calls Mnemosyne to re-embed any new or modified files; if regeneration fails, the last good INDEX.md is preserved and a warning is logged
   - Acceptance: After Demeter processes a batch, all affected INDEX.md files reflect the new state; a simulated regeneration failure leaves the previous INDEX.md intact; Mnemosyne receives a re-embed call for each changed file

3. **Bulk operation pause/resume**: External scripts can signal Demeter to pause watching during bulk operations.
   - Current: No pause mechanism — bulk imports would trigger cascading regeneration jobs
   - Target: `DemeterClient.pause()` and `DemeterClient.resume()` signal Demeter via a local file flag; while paused, events are queued but not processed; on resume, all queued events are processed as one batch
   - Acceptance: Calling `pause()`, creating 20 files, then calling `resume()` produces exactly 1 index regeneration job covering all 20 files; no regeneration occurs between `pause()` and `resume()`

4. **Nightly cron scheduler**: Demeter triggers Hades distillation and Fates TTL evaluation on a configurable nightly schedule.
   - Current: Hades and Fates exist (Phase 3) but are never called automatically
   - Target: `default_config.yaml` has `scheduler.hades_cron` (default: `0 2 * * *`) and `scheduler.fates_cron` (default: `0 3 * * *`); Demeter's scheduler fires these jobs at configured times; schedule cannot be set faster than nightly (enforced at config load)
   - Acceptance: With cron set to a 1-minute test interval, Hades and Fates are both called within 2 minutes; resetting to nightly interval, neither fires again until the next scheduled window

## Boundaries

**In scope:**
- `helpers/demeter.py` — watchdog observer, settle window, index regeneration trigger, Mnemosyne re-embed call, pause/resume
- `DemeterClient` helper for pause/resume signaling (file flag based)
- Nightly cron scheduler for Hades and Fates (APScheduler or equivalent)
- Failure handling: preserve last good INDEX.md on regeneration failure; log warning (Iris stub)
- Removing inline synchronous index regeneration from `AthenaeumMemory.save()` (Phase 1 code replaced)

**Out of scope:**
- Full Iris notification system — stub as log warning; Iris integration is a future Pantheon phase
- Backup scheduling — separate backlog item
- Demeter as a separate daemon process — runs as background thread within agent-zero's process

## Constraints

- `watchdog` library must be used for cross-platform file watching — no OS-specific inotify calls
- Settle window is configurable (`watcher.settle_seconds`, default: 5) but must be ≥ 1 second; enforced at config load
- Demeter runs as a background thread within agent-zero's process — not a subprocess or daemon
- Scheduler cannot be configured faster than nightly (86400 second minimum interval) — enforced at config load with clear error

## Acceptance Criteria

- [ ] Demeter starts automatically when `_athenaeum` plugin loads
- [ ] 5 rapid file creates in a live Codex path trigger exactly 1 index regeneration job
- [ ] A file created externally (not via `save()`) triggers index regeneration
- [ ] A file in `archive/` or `Staging/` does NOT trigger regeneration
- [ ] Failed index regeneration preserves the previous INDEX.md and logs a warning
- [ ] Mnemosyne re-embed is called for each file in the settled batch
- [ ] `DemeterClient.pause()` + bulk writes + `DemeterClient.resume()` = exactly 1 regeneration job
- [ ] Hades is called at the configured cron schedule
- [ ] Fates is called at the configured cron schedule
- [ ] A scheduler interval faster than nightly raises a clear config error at startup

## Ambiguity Report

| Dimension           | Score | Min  | Status | Notes |
|---------------------|-------|------|--------|-------|
| Goal Clarity        | 0.85  | 0.75 | ✓      | |
| Boundary Clarity    | 0.88  | 0.70 | ✓      | Iris stub explicit; daemon vs thread clarified |
| Constraint Clarity  | 0.87  | 0.65 | ✓      | watchdog pinned, settle window bounds, thread model |
| Acceptance Criteria | 0.82  | 0.70 | ✓      | 10 pass/fail criteria |
| **Ambiguity**       | 0.18  | ≤0.20| ✓      | |

## Interview Log

| Round | Perspective      | Question summary                          | Decision locked |
|-------|------------------|-------------------------------------------|----------------|
| 1     | Researcher       | What triggers index regeneration today?   | Inline in `save()` — synchronous, no external change detection |
| 2     | Simplifier       | Minimum viable Demeter?                   | Watcher + settle window + cron — Iris is a log stub |
| 3     | Boundary Keeper  | Does Demeter re-embed or just re-index?   | Both — after index regen, Demeter calls Mnemosyne re-embed |
| 4     | Failure Analyst  | What if cron job fails mid-distillation?  | Hades has its own rollback; Demeter logs failure and continues |

---

*Phase: 04-demeter*
*Spec created: 2026-04-24*
*Next step: /gsd:discuss-phase 4 — implementation decisions (watchdog observer type, settle window mechanism, cron library selection)*
