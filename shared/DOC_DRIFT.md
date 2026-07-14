# Doc Discipline — Drift Report

**Generated:** 2026-07-14 03:00:30 MDT
**Severity counts:** 0 drift, 3 warn, 2 info

**Skill:** `doc-discipline` (`~/pantheon/god-packages/shared-skills/doc-discipline/`)
**Script:** `~/pantheon/scripts/doc-discipline-verify.py`
**Schedule:** 0 3 * * * (system cron, no god binding)

---

## 🟡 WARN

### doc-stale::OLYMPUS_UI_STATE.md
- **Claim:** OLYMPUS_UI_STATE.md last verified within 7 days
- **Actual:** last verified 2026-06-11 (33 days ago)
- **Where:** `/home/konan/athenaeum/Codex-Olympus/OLYMPUS_UI_STATE.md`
- **Fix:** Re-verify claims in the doc against current state, update the date

### doc-stale::OLYMPUS_UI_ROADMAP.md
- **Claim:** OLYMPUS_UI_ROADMAP.md last verified within 7 days
- **Actual:** last verified 2026-06-02 (42 days ago)
- **Where:** `/home/konan/athenaeum/Codex-Olympus/OLYMPUS_UI_ROADMAP.md`
- **Fix:** Re-verify claims in the doc against current state, update the date

### tsc-errors
- **Claim:** Olympus-UI tsc -b should be 0 errors for green build
- **Actual:** tsc -b reports 32 error(s)
- **Where:** `/home/konan/Olympus-UI`
- **Fix:** Run `cd ~/Olympus-UI && npx --yes tsc -b --noEmit` to see errors; fix or update state doc if intentional and documented

## 🔵 INFO

### olympus-uncommitted
- **Claim:** Olympus-UI working tree clean
- **Actual:** 286 uncommitted change(s) in ~/Olympus-UI/
- **Where:** `/home/konan/Olympus-UI`
- **Fix:** Commit or stash before next session; consider applying doc-discipline skill first

### bundles-stale
- **Claim:** Compiled bundles in webui/static/assets/ are recent (within 48h)
- **Actual:** newest bundle is 936.8h old
- **Where:** `/home/konan/pantheon/webui/static/assets`
- **Fix:** If Olympus-UI source has uncommitted changes, build and deploy via deploy-olympus.sh

---

## What to do

1. **drift findings (🔴):** These are real problems. Fix before the next commit. If the doc-discipline skill is being followed, these should be 0.
2. **warn findings (🟡):** Soft signals. Doc is stale, or a build claim is drifting. Decide if it's worth a session or if the next natural change will address it.
3. **info findings (🔵):** Informational. Unpushed commits, uncommitted WIP, stale bundles. Decide if these are intentional.

If you disagree with a finding, edit this report or update the canonical doc — do not silence the script.
