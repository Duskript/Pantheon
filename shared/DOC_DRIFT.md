# Doc Discipline — Drift Report

**Generated:** 2026-11-21 03:00:52 MST
**Severity counts:** 0 drift, 2 warn, 2 info

**Skill:** `doc-discipline` (`~/pantheon/god-packages/shared-skills/doc-discipline/`)
**Script:** `~/pantheon/scripts/doc-discipline-verify.py`
**Schedule:** 0 3 * * * (system cron, no god binding)

---

## 🟡 WARN

### doc-stale::OLYMPUS_UI_STATE.md
- **Claim:** OLYMPUS_UI_STATE.md last verified within 7 days
- **Actual:** last verified 2026-06-11 (163 days ago)
- **Where:** `/home/konan/athenaeum/Codex-Olympus/OLYMPUS_UI_STATE.md`
- **Fix:** Re-verify claims in the doc against current state, update the date

### doc-stale::OLYMPUS_UI_ROADMAP.md
- **Claim:** OLYMPUS_UI_ROADMAP.md last verified within 7 days
- **Actual:** last verified 2026-06-02 (172 days ago)
- **Where:** `/home/konan/athenaeum/Codex-Olympus/OLYMPUS_UI_ROADMAP.md`
- **Fix:** Re-verify claims in the doc against current state, update the date

## 🔵 INFO

### olympus-uncommitted
- **Claim:** Olympus-UI working tree clean
- **Actual:** 313 uncommitted change(s) in ~/Olympus-UI/
- **Where:** `/home/konan/Olympus-UI`
- **Fix:** Commit or stash before next session; consider applying doc-discipline skill first

### bundles-stale
- **Claim:** Compiled bundles in webui/static/assets/ are recent (within 48h)
- **Actual:** newest bundle is 2530.3h old
- **Where:** `/home/konan/pantheon/webui/static/assets`
- **Fix:** If Olympus-UI source has uncommitted changes, build and deploy via deploy-olympus.sh

---

## What to do

1. **drift findings (🔴):** These are real problems. Fix before the next commit. If the doc-discipline skill is being followed, these should be 0.
2. **warn findings (🟡):** Soft signals. Doc is stale, or a build claim is drifting. Decide if it's worth a session or if the next natural change will address it.
3. **info findings (🔵):** Informational. Unpushed commits, uncommitted WIP, stale bundles. Decide if these are intentional.

If you disagree with a finding, edit this report or update the canonical doc — do not silence the script.
