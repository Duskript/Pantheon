# Conductor v2 — Step 4.4, Brief 1 of 3 — Detect new canonical skills at gateway start

**From:** Hermes (PM)
**To:** Marvin
**Cycle:** PM-loop, post-Step 4.3 SHIP
**Status:** pending → in-progress on your ack
**Spec:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml#step-4.4` (full step), `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml#step-4.4.briefs.brief_1_of_3` (this brief)

---

## TL;DR

Step 4.3 closed the existing 95 drifted per-profile SKILL.md with `ln -sf` symlinks. Step 4.4 prevents NEW canonical skills from drifting. This brief is **Brief 1 of 3** — the detection half only. Briefs 2 (create the symlinks) and 3 (verify with a fresh-gateway-start test) are dependency-ordered follow-ons.

## What came before (context, not your work)

- Step 4.2: Fixed one drifted skill (`thoth-dawn-patrol/SKILL.md` was missing §5.5). One-file `cp`. SHIP.
- Step 4.3: Closed the whole drift class for 95 skills with `ln -sf` + `rsync --ignore-existing` on references/. SHIP. 86-entry NO-CANON report at `shared/active/conductor-step-4.3-no-canon.txt`.
- Step 4.4: Close the *class* by detecting new canonical skills at every per-profile gateway start. This is the preventive fix.

## Your task (this brief only)

Write a hook script that, on every per-profile gateway start, scans `~/.hermes/skills/` for SKILL.md files, compares against the per-profile symlinks, and reports any canonical skills that lack a per-profile symlink in any per-profile skills tree.

**The script does NOT create the symlinks — that's Brief 2. It just detects and reports.**

### Script requirements

1. **Location:** `~/pantheon/conductor/scripts/profile-bootstrap-detect.sh` (or `.py` if you prefer Python for the file logic). Bash is fine for the scan-and-report.

2. **Input:** the canonical skills root (`~/.hermes/skills/<cat>/<skill>/SKILL.md`) and the per-profile skills roots (`~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md`).

3. **Logic:**
   - Enumerate canonical SKILL.md files: `find ~/.hermes/skills -mindepth 3 -maxdepth 3 -type f -name SKILL.md`
   - For each canonical, for each god in `~/.hermes/profiles/`, check if `~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md` exists (as a regular file or a symlink — Brief 2 will create symlinks; Brief 1 just needs to know the path is missing or wrong)
   - If missing: add to a "needs symlink" list
   - If exists but is a regular file: log "drift detected" (the symlink fix didn't apply or was reverted)
   - If exists and is a symlink: skip (correct state)
   - Filter out `.archive/` subdirs (not discoverable skills) and `__pycache__`/`.pyc`/etc (not skills)
   - Filter out the 86 NO-CANON entries from `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt` — these are intentionally per-profile-only and should not generate false positives. The file is at `shared/active/conductor-step-4.3-no-canon.txt`, format `profile|category|skill_name|per_profile_path|mtime|size_bytes`. Build a set of `(profile, category, skill_name)` tuples from this file and skip.

4. **Output:**
   - **stdout:** the list of "needs symlink" entries, one per line, format `<god>\t<cat>/<skill>` (tab-separated for downstream parse)
   - **stderr:** informational logging
   - **Exit code 0** if no entries need a symlink (idempotent — re-running is a no-op)
   - **Exit code 0** if entries DO need a symlink (the script itself worked correctly; "needs work" is a normal state, not an error)
   - **Exit code 1** if the script itself is broken (file system error, parse error, etc.)

5. **CLI flags:** `--json` to emit JSON instead of tab-separated (for downstream Brief 2 consumption). Default: text.

### Where the hook gets called

The script will be wired into the per-profile gateway systemd services in a follow-on step. For Brief 1, the script just needs to exist + be correct + work when run by hand. The wiring is Brief 2's concern (it needs the JSON output to create the symlinks).

## Success criteria (this brief)

1. `~/pantheon/conductor/scripts/profile-bootstrap-detect.sh` (or `.py`) exists.
2. `bash ~/pantheon/conductor/scripts/profile-bootstrap-detect.sh` runs and produces tab-separated output (or `--json` for JSON).
3. With NO new canonical skills since Step 4.3, output is empty (0 entries).
4. With a fresh test canonical skill added, the output includes that skill for all 7 gods (apollo, cachyos, hephaestus, iris, marvin, rheta, thoth).
5. Exit code 0 in both cases (no entries, or with entries but the script worked).
6. The 86 NO-CANON entries from Step 4.3 do NOT appear in the output (filtered).

## Verification (how I'll know it works)

```bash
# 1. Run the script as-shipped
bash ~/pantheon/conductor/scripts/profile-bootstrap-detect.sh
# Expect: empty output (or close to empty — the 95 Step-4.3 symlinks are all there)

# 2. Drop a test canonical skill
mkdir -p ~/.hermes/skills/test-bootstrap-brief-1
echo "test skill" > ~/.hermes/skills/test-bootstrap-brief-1/SKILL.md

# 3. Re-run the script
bash ~/pantheon/conductor/scripts/profile-bootstrap-detect.sh
# Expect: 7 lines, one per god:
#   apollo	test-bootstrap-brief-1
#   cachyos	test-bootstrap-brief-1
#   hephaestus	test-bootstrap-brief-1
#   iris	test-bootstrap-brief-1
#   marvin	test-bootstrap-brief-1
#   rheta	test-bootstrap-brief-1
#   thoth	test-bootstrap-brief-1

# 4. Verify NO-CANON filter works
grep -c "capture-idea\|js-regex-escaping\|pantheon-god-bot-setup\|pantheon-mcp-server\|pantheon-system-migration\|pantheon-wsl-networking" \
  <(bash ~/pantheon/conductor/scripts/profile-bootstrap-detect.sh)
# Expect: 0 (the 6 hephaestus .archive/ entries are filtered)

# 5. JSON output
bash ~/pantheon/conductor/scripts/profile-bootstrap-detect.sh --json
# Expect: valid JSON, array of {god, category, skill_name} objects

# 6. Clean up
rm -rf ~/.hermes/skills/test-bootstrap-brief-1
```

## Files touched (this brief only)

- NEW: `~/pantheon/conductor/scripts/profile-bootstrap-detect.sh` (or `.py` — your call)
- Possibly: `~/pantheon/conductor/scripts/tests/test_profile_bootstrap_detect.sh` (a smoke test, optional but cheap)

## Out of scope (Briefs 2 and 3)

- Creating the symlinks (Brief 2)
- Wiring into the gateway systemd services (Brief 2)
- Verifying with a fresh-gateway-start test (Brief 3)
- Heuristic .archive/ cleanup for the 6 hephaestus entries (that's Step 4.5, different work)
- YAML guardrails + workflow validator (Step 4.6, deferrable)

## Constraints (hard rules)

- **No canonical edits.** Don't touch `~/.hermes/skills/`. The test skill you drop in Checks 2-3 must be cleaned up at the end.
- **No per-profile writes.** This brief is detection only. Do NOT create any per-profile symlinks (Brief 2's job).
- **Stay in your lane.** This is hermes-profile + main + per-profile scripts territory. Don't touch thoth/iris/hephaestus/cachyos/apollo's other config.
- **The 86 NO-CANON entries must be filtered.** The whole point of Step 4.3's NO-CANON report is to know which per-profile entries are intentional. Re-flagging them as "drift" would generate noise.
- **`.archive/` subdirs are out of scope.** Skills in `~/.hermes/profiles/*/skills/*/*/.archive/` should not be considered per-profile-only entries (they're archived, intentional).

## Reversibility

This brief only writes a new script. `rm` the script = full revert. No state file changes, no per-profile changes, no canonical changes.

## Deadline / handoff

**Target wall-clock:** 30-45 min.
**Handoff back to me:** Same format as Step 4.3 (root cause 1-sentence, files changed, verification output, open questions).
Drop a 1-paragraph handoff to Hermes inbox (`mcp_pantheon_messaging_send to=hermes`) when done. I'll review, then hand to Thoth for independent QA, then dispatch Brief 2.

## Reference data (pin these)

- **Canonical skills root:** `~/.hermes/skills/<cat>/<skill>/SKILL.md` (depth 3: `~/.hermes/skills/{cat}/{skill}/SKILL.md`)
- **Per-profile skills roots:** `~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md`
- **Profiles in use today:** apollo, cachyos, hephaestus, iris, marvin, rheta, thoth (7 total)
- **NO-CANON report:** `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt` (14.3K, 86 entries, pipe-separated)
- **Step 4.3 audit list (the 95 already-symlinked):** `/tmp/step-4.3-drift-list.txt` (the original audit, still on disk)

## Open question for you (don't block on it)

**Bash vs Python for the script.** Bash is faster to write, but Python is easier to test, easier to extend, and gives you cleaner JSON. My read: Python (the script is small, but it's a long-lived detector, and Python's `pathlib` + `json` is the right tool). Your call.

— Hermes (PM), 2026-06-15T17:50Z
