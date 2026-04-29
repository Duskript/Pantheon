# Phase 3: Underworld — Specification

**Created:** 2026-04-24
**Ambiguity score:** 0.17
**Requirements:** 4 locked

## Goal

Implement Hades (nightly distillation), Charon (archive file moves), and the Fates (TTL purge) as helpers within `_athenaeum`, giving the knowledge system a self-maintaining lifecycle that prevents indefinite accumulation.

## Background

After Phase 2, the Athenaeum accumulates files indefinitely. Raw session logs, redundant notes, and outdated content pile up in live Codices. The Pantheon design specifies three cleanup mechanisms: Hades consolidates and distills redundant content; Charon physically moves source files to tiered archive (Asphodel/Elysium/Tartarus); the Fates evaluate TTL and condemn expired content. This phase builds all three as Python helpers. Scheduling (nightly runs) is wired in Phase 4 via Demeter.

## Requirements

1. **Hades distillation**: Hades consolidates related source files in a Codex into a single distilled markdown file.
   - Current: No distillation exists; Athenaeum files accumulate without consolidation
   - Target: `helpers/hades.py` — `Hades.distill(codex, subfolder)` reads all non-distilled files in the target subfolder, produces a consolidated `.md` file written to `{Codex}/{subfolder}/distilled/`, then instructs Charon to archive the source files to Asphodel
   - Acceptance: Running `Hades.distill("General", "notes")` with 3 source files produces 1 distilled file in `distilled/`; all 3 source files move to `archive/asphodel/`; `ARCHIVE_INDEX.md` records each move

2. **Charon archive moves**: Charon executes all physical file moves between live Codex and archive tiers; no other code moves files.
   - Current: No archive system exists; files never move after being written
   - Target: `helpers/charon.py` — `Charon.to_asphodel(file_path, replaced_by)`, `Charon.to_elysium(file_path, replaced_by)`, `Charon.condemn(file_path)` move files to the correct archive tier and update `ARCHIVE_INDEX.md`; Charon notifies Mnemosyne to remove stale vectors after any move
   - Acceptance: `Charon.to_asphodel(path, replaced_by)` moves the file to `archive/asphodel/`; `ARCHIVE_INDEX.md` gains a new row with File, Tier, Replaced By, and Archived timestamp; the archived file's content returns no results from `search_similarity_threshold()`

3. **ARCHIVE_INDEX.md maintenance**: Every Codex's `archive/` contains an `ARCHIVE_INDEX.md` written and maintained only by Charon.
   - Current: No `ARCHIVE_INDEX.md` exists
   - Target: `archive/ARCHIVE_INDEX.md` is created by Charon on first archive move; subsequent moves append rows; rollback operations update the tier column; the file is never written by any code other than Charon
   - Acceptance: After 3 archive operations, `ARCHIVE_INDEX.md` contains exactly 3 data rows plus header; a rollback changes the source file's record to reflect restoration and moves the distilled version to Elysium

4. **Fates TTL evaluation**: The Fates evaluate archive tiers and condemn or purge expired content on demand.
   - Current: No TTL or purge mechanism exists
   - Target: `helpers/fates.py` — `Fates.evaluate(codex)` scans `ARCHIVE_INDEX.md`; Asphodel entries older than 6 months are moved to Tartarus via Charon; Tartarus entries older than 3 months are permanently deleted via Charon; Elysium entries have no TTL unless explicitly condemned by Hades
   - Acceptance: An Asphodel file with archived timestamp 7 months ago is moved to Tartarus after `evaluate()`; a Tartarus file with timestamp 4 months ago is permanently deleted; an Elysium file 8 months old is NOT touched

## Boundaries

**In scope:**
- `helpers/hades.py` — distillation logic (LLM-assisted consolidation via agent-zero's model config)
- `helpers/charon.py` — file move executor, `ARCHIVE_INDEX.md` writer, Mnemosyne stale vector cleanup
- `helpers/fates.py` — TTL evaluation against `ARCHIVE_INDEX.md`
- Rollback: `Charon.rollback(distilled_file)` restores source from Asphodel, moves distilled to Elysium
- `ARCHIVE_INDEX.md` schema and maintenance

**Out of scope:**
- Scheduling nightly runs — Phase 4 (Demeter's cron scheduler)
- Staging inbox classification — not part of Underworld
- Backup — separate backlog item

## Constraints

- Charon is the only code that moves or deletes files in the Athenaeum — no other helper, tool, or plugin may call `os.rename()`, `shutil.move()`, or `os.remove()` on Athenaeum paths
- Tartarus purge is the only place permanent deletion occurs — no other operation deletes files
- Hades uses agent-zero's existing model configuration for LLM-assisted consolidation — no hardcoded model name
- `ARCHIVE_INDEX.md` is append-and-update only — rows are never removed, only updated with new tier or rollback status

## Acceptance Criteria

- [ ] `Hades.distill()` produces a distilled file and triggers Charon to move sources to Asphodel
- [ ] `Charon.to_asphodel()` moves file and updates `ARCHIVE_INDEX.md` with correct row
- [ ] `Charon.to_elysium()` moves file and updates `ARCHIVE_INDEX.md` with correct row
- [ ] `Charon.condemn()` moves file to Tartarus and updates `ARCHIVE_INDEX.md`
- [ ] After any Charon move, the archived file's content is absent from Mnemosyne search results
- [ ] `Fates.evaluate()` moves Asphodel files older than 6 months to Tartarus
- [ ] `Fates.evaluate()` permanently deletes Tartarus files older than 3 months
- [ ] Elysium files are NOT purged by `Fates.evaluate()` regardless of age
- [ ] `Charon.rollback()` restores source file to live Codex and moves distilled to Elysium
- [ ] No file is ever moved or deleted by code outside `charon.py`

## Ambiguity Report

| Dimension           | Score | Min  | Status | Notes |
|---------------------|-------|------|--------|-------|
| Goal Clarity        | 0.87  | 0.75 | ✓      | |
| Boundary Clarity    | 0.88  | 0.70 | ✓      | Scheduling explicitly deferred to Phase 4 |
| Constraint Clarity  | 0.90  | 0.65 | ✓      | Charon monopoly on file moves is a hard rule |
| Acceptance Criteria | 0.83  | 0.70 | ✓      | 10 pass/fail criteria |
| **Ambiguity**       | 0.17  | ≤0.20| ✓      | |

## Interview Log

| Round | Perspective      | Question summary                        | Decision locked |
|-------|------------------|-----------------------------------------|----------------|
| 1     | Researcher       | Who moves files in Pantheon design?     | Charon exclusively — hard rule from KNOWLEDGE.md |
| 2     | Simplifier       | Minimum viable Underworld?              | Hades + Charon + Fates; scheduling deferred to Phase 4 |
| 3     | Boundary Keeper  | Does Hades use the configured LLM?      | Yes — agent-zero's model config; no hardcoded model |
| 4     | Failure Analyst  | What if distillation produces bad output? | Rollback via Charon — restores source from Asphodel |

---

*Phase: 03-underworld*
*Spec created: 2026-04-24*
*Next step: /gsd:discuss-phase 3 — implementation decisions (distillation prompt design, ARCHIVE_INDEX schema, TTL evaluation strategy)*
