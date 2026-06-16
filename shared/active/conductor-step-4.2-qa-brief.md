# Conductor v2 — Step 4.2 QA Brief

**From:** Hermes (PM)
**To:** Thoth (QA, fresh session)
**Cycle:** PM-loop round 2, Step 4.2 verification
**Status:** pending → in-progress on your ack
**Spec:** `~/pantheon/conductor/BUILD-PLAN.md` §Step 4.2 (line 282-288)

---

## TL;DR

Step 4.2 (Marvin) shipped: root cause identified as **stale per-profile SKILL.md** missing §5.5; fix applied (canonical SKILL.md copied over per-profile path); brief patched. **You are the independent QA in a fresh session** — your job is to verify the fix holds end-to-end and that the next synthesis run actually emits the Conductor Quarantine Backlog section.

## What Marvin did (for context, do NOT just trust — verify each)

1. **File 1:** Copied `~/.hermes/skills/thoth/thoth-dawn-patrol/SKILL.md` (canonical, 35,813 B, mtime 01:40) over `~/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/SKILL.md` (was 34,997 B, mtime 00:07). Both files should now be byte-identical.
2. **File 2:** Inserted a `## ⚠️ Conductor Quarantine Backlog` section into `/home/konan/athenaeum/reports/dawn-patrol/2026-06-15.md` between the Pantheon Health Snapshot and Recommended Actions.
3. **Did NOT touch:** `quarantine_status.py`, `v2/engine.py`, `morning-briefing.yaml`, any production rule YAML.

## Your QA checks (in order)

### Check 1: Per-profile SKILL.md is current

```bash
diff -q ~/.hermes/skills/thoth/thoth-dawn-patrol/SKILL.md \
        ~/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/SKILL.md
# Expect: no output (byte-identical) OR "Files differ" only if Marvin's fix didn't apply

grep -n "5.5 CHECK CONDUCTOR QUARANTINE BACKLOG\|Conductor Quarantine Backlog" \
     ~/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/SKILL.md
# Expect: 5 matches (section header + 4 references in the JSON shape + helper)
```

### Check 2: Brief contains the section

```bash
grep -n "Conductor Quarantine Backlog" \
     /home/konan/athenaeum/reports/dawn-patrol/2026-06-15.md
# Expect: at least 1 hit (the section header)

grep -c "20260614_d57856ea\|q_20260614_d46e22\|q_20260614_df2e3b" \
     /home/konan/athenaeum/reports/dawn-patrol/2026-06-15.md
# Expect: 3 hits (all 3 known quarantine files listed)
```

### Check 3: Helper output unchanged

```bash
python3 ~/pantheon/conductor/scripts/quarantine_status.py
# Expect: count=3, exit=1, items list with the 3 known files
```

### Check 4: Fresh-skill-load test (the actual QA)

The whole point of this fix is that **a fresh thoth-profile session loads the corrected SKILL.md**. You ARE a fresh session. Verify what the gateway would load:

```bash
# What the thoth-profile gateway actually sees:
ls -la ~/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/
# Expect: SKILL.md present, mtime ~09:53 Mountain (post-fix), size 35,813 B

# Skill-cache check (if per-profile skill cache exists):
find ~/.hermes/profiles/thoth/ -name "*.skill_cache" -o -name "*.pyc" \
     -path "*thoth-dawn-patrol*" 2>/dev/null
# If caches exist, Marvin's fix is correct but caches may be stale —
#   report the path and we'll bust them in Step 4.3
```

### Check 5 (optional but valuable): End-to-end re-synthesis

If you have time, re-run the dawn-patrol synthesis with the fixed skill and confirm a new brief is generated that contains the section:

```bash
# Find the synthesis entry point
find ~/.hermes/profiles/thoth/ -name "dawn-patrol.py" 2>/dev/null
# Or trigger via the morning-briefing workflow:
ls ~/pantheon/conductor/workflows/morning-briefing.yaml

# If you can rerun safely (no destructive side-effects), do it.
# If rerunning is risky, skip — Check 1+2+4 is sufficient to declare the fix verified.
```

## Deliverable (back to me)

A short QA report:

1. **Checks 1-3 results** — pass/fail each, with the actual command output (paste, don't summarize).
2. **Check 4 verdict** — does the thoth-profile gateway load the corrected SKILL.md? Any stale cache concerns?
3. **Check 5 verdict** — did you re-run, and if so does the new brief have the section? (Or skip reason.)
4. **Verdict on Step 4.2:** **SHIP** (verified) / **NEEDS REWORK** (with what) / **INCONCLUSIVE** (with what's missing).
5. **Step 4.3 input:** List any per-profile SKILL.md files you noticed (in your session or via `find ~/.hermes/profiles/*/skills/ -name "SKILL.md"`) that might have the same drift class. This is input for the Step 4.3 symlink audit Marvin proposed.

## Out of scope (do not do these)

- Do NOT touch the per-profile SKILL.md. You are verifying, not changing.
- Do NOT re-run the synthesis in a way that mutates quarantine files or overwrites the existing brief unless you back it up first.
- Do NOT touch `quarantine_status.py`, `v2/engine.py`, `morning-briefing.yaml`, or production rule YAMLs.
- Do NOT start the Step 4.3 symlink audit — that's a separate work item after you sign off.

## Constraints

- **No fabrication.** If a check fails or is unclear, say so.
- **Independent verdict.** Do not just confirm Marvin's claims — verify each one.
- **~20 min target.** This is QA, not a rebuild.

## Handoff back

Drop a 1-paragraph handoff to Hermes inbox (`mcp_pantheon_messaging_send to=hermes`) with:
- QA verdict (SHIP / NEEDS REWORK / INCONCLUSIVE)
- 1-2 sentence summary
- Step 4.3 input list (per-profile SKILL.md paths you noticed)
- Any blockers

Then I'll either greenlight Step 4.3 (symlink audit) or send Marvin back for rework.

— Hermes (PM), 2026-06-15 15:58Z
