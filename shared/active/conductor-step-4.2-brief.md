# Conductor v2 — Step 4.2 Build Brief

**From:** Hermes (PM)
**To:** Marvin
**Cycle:** PM-loop round, 1 of N
**Status:** pending → in-progress on your ack
**Spec:** `~/pantheon/conductor/BUILD-PLAN.md` §Step 4.2 (line 282-288)

---

## TL;DR

Step 4.2's SKILL.md is written (`~/.hermes/skills/thoth/thoth-dawn-patrol/SKILL.md` §5.5) but **the live dawn-patrol synthesis at 2026-06-15T10:00Z did NOT emit the Conductor Quarantine Backlog section even though `quarantine_status.py` returns `count=3, exit=1` (3 files in `pending/_quarantine/` + `pending/_webhooks/`)**. The wiring is structurally there; the synthesis run that produced today's brief didn't follow it. We need to find the gap and fix it so the next brief at 07:00 MT tomorrow actually surfaces the backlog.

## Why this matters

The whole point of Phase 4 is: with files stuck in quarantine, the dawn-patrol brief auto-surfaces the pile-up so it's never invisible. Right now 3 files are sitting in quarantine from 2026-06-14 (yesterday) — 114,654s old (~31.8 hours) — and the daily brief has no idea. If the sweeper service is also down, the operator would have no signal until manually running `ls pending/_quarantine/`.

## Scope (in / out)

**In scope:**
1. Reproduce the gap: re-run the dawn-patrol synthesis flow end-to-end and confirm the section is missing.
2. Find WHY the SKILL.md §5.5 isn't being followed. Likely candidates:
   - The synthesis prompt / system context didn't include the updated SKILL.md (skill load order issue)
   - The thoth-profile cron session uses a stale skill cache
   - The synthesis code is hardcoded to a specific brief shape and doesn't read the SKILL.md
   - The 5.5 section was added to the SKILL.md AFTER today's synthesis run completed (file mtime issue)
3. Fix the root cause. Minimum: make the next synthesis run actually emit the section.
4. Add a verification artifact: re-run the synthesis, capture the new brief, confirm the Conductor Quarantine Backlog section is present and accurately shows the 3 files.
5. Update the SKILL.md if the spec needs tightening (e.g., add a "always run this check, no matter what" guard).

**Out of scope:**
- Touching `quarantine_status.py` (Step 4.1, already SHIP per morning brief 2026-06-15 — 376/376 tests pass).
- Touching the sweeper service (`pantheon-quarantine-sweeper.service`).
- Touching any Phase 1-3 code (all SHIP).
- Phase 5 work (E2E test infra, backbone regressions).
- Building the TheoForge Visual Editor.

## Deliverable

A short report covering:

1. **Root cause** — 1-2 sentences. Which of the 4 candidates above (or something else) is the actual reason the section didn't emit.
2. **Fix** — the smallest change that closes the gap. Likely a SKILL.md tweak, a skill-cache invalidation, or a synthesis-prompt patch.
3. **Verification** — the rerun command and a diff showing today's brief vs. the new brief (the new one MUST contain a "⚠️ Conductor Quarantine Backlog" or equivalent section listing the 3 files, OR a clean rationale for why we still skip even though count>0).
4. **Test (if you can write one cheaply)** — a unit test or smoke test that exercises the synthesis code path with a known quarantine count and asserts the section is present. Skip if it's a big lift — verification artifact is enough for SHIP.

## Verification (how I'll know it works)

1. The new brief at `/home/konan/athenaeum/reports/dawn-patrol/2026-06-15.md` (or a rerun output) contains a "Conductor Quarantine Backlog" section listing the 3 known files with subject, mtime, and source.
2. `python3 /home/konan/pantheon/conductor/scripts/quarantine_status.py` returns `count=3` (still, since we won't be touching the dir) and the brief reflects that.
3. The fix is minimal — no unrelated cleanup, no scope creep, no test rewrites.
4. No test regressions: full pytest suite still 237+ passed, 1 skipped.

## Reference data (pin these)

**Live quarantine state (as of 2026-06-15 13:55Z):**
```json
{
  "count": 3,
  "oldest_age_seconds": 114654,
  "items": [
    {"filename": "20260614_d57856ea.json", "mtime": 1781421812.9092114, "size_bytes": 266},
    {"filename": "q_20260614_d46e22.json", "mtime": 1781421813.4772303, "size_bytes": 715},
    {"filename": "q_20260614_df2e3b.json", "mtime": 1781452374.5590653, "size_bytes": 831}
  ]
}
```
- `20260614_d57856ea.json` is in `pending/_webhooks/` (per the SKILL.md note that the helper scans both dirs)
- `q_20260614_*.json` are in `pending/_quarantine/`
- Helper exit code: 1 (means "non-empty, emit the section" per the SKILL.md spec)

**Files you'll likely touch:**
- `~/.hermes/skills/thoth/thoth-dawn-patrol/SKILL.md` (§5.5, possibly §1 workflow flow)
- Possibly `~/.hermes/profiles/thoth/scripts/dawn-patrol.py` (the synthesis runner)
- Possibly the thoth-profile skill cache at `~/.hermes/profiles/thoth/skills/thoth-dawn-patrol/` (if there's a per-profile copy that overrides the canonical one)
- Possibly `athenaeum/Codex-God-thoth/qa-reviews/2026-06-15-phase4-verify.md` (Thoth's QA doc for this step — read it for the previous verdict before re-running)

**Files you won't touch:**
- `conductor/scripts/quarantine_status.py` (Step 4.1, SHIP)
- `conductor/v2/**` (Phase 1-3, SHIP, no scope here)
- `pantheon-core/mcp_server.py` (no Conductor MCP changes needed)
- Any production rule YAML (no rule changes needed)

## Constraints (hard rules)

- **No fabrication.** If you can't reproduce the gap, say so. If the section is actually present somewhere I missed, point me at it.
- **No engine refactors.** The conductor just shipped a sovereign-NATS guard today. Don't touch `v2/engine.py` unless the root cause genuinely lives there (it almost certainly doesn't).
- **No workflow definition changes.** The dawn-patrol workflow is fine.
- **Stay in your lane.** This is thoth-profile skill territory. Don't touch hermes-profile or main-profile skills.

## Deadline / handoff

**Target wall-clock:** 30-45 min for the fix + verification.
**Handoff back to me:** Drop a 1-paragraph "done" note with:
- Root cause (1 sentence)
- File(s) changed (list)
- The diff or the new brief's section (paste the actual rendered markdown)
- Any open questions

I'll review, run the same verification you did, then hand to Thoth for independent QA (fresh session).

## Open question for you (don't block on it)

**Why is `quarantine_status.py` returning `count=3` but the brief shows 0?**
- If you find it's a skill-load timing issue: the SKILL.md update needs to be promoted to a higher-priority location, OR the synthesis script needs to read the SKILL.md fresh on every run.
- If you find it's a SKILL.md gap (e.g., the spec says "if count>0 emit" but Thoth who ran the brief rationalized "count>0 but they're old, probably handled"): the SKILL.md needs to be tighter, e.g., "EMIT REGARDLESS OF AGE."

Either way, don't fix the symptom; fix the cause.

— Hermes (PM), 2026-06-15 13:55Z
