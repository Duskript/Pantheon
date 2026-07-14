# Conductor v2 — Step 4.3 QA Brief

**From:** Hermes (PM)
**To:** Thoth (QA, fresh session)
**Cycle:** PM-loop round 3, Step 4.3 verification
**Status:** pending → in-progress on your ack
**Spec:** `~/pantheon/conductor/BUILD-PLAN.md` §Step 4.3 (locked 2026-06-15 16:30Z by Marvin)

---

## TL;DR

Step 4.3 (Marvin) shipped: 95 per-profile SKILL.md replaced with `ln -sf` symlinks to canonical twin, 66 references/ subdirs rsync-merged (`--ignore-existing`, additive only), NO-CANON report at `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt` (86 entries, scope ratified by operator). **You are the independent QA in a fresh session** — your job is to verify the symlinks work, the regressions are clean, and the NO-CANON report is accurate.

## What Marvin did (for context, do NOT just trust — verify each)

1. **Symlinks (95):** Replaced 95 drifted per-profile SKILL.md with `ln -sf ~/.hermes/skills/<cat>/<skill>/SKILL.md` symlinks. Profiles: apollo 18, cachyos 18, hephaestus 20, iris 20, thoth 19.
2. **References (66):** `rsync -a --ignore-existing ~/.hermes/skills/<cat>/<skill>/references/ ~/.hermes/profiles/<god>/skills/<cat>/<skill>/references/` for 66 of the 95 skills. 29 noop (canonical had no references/).
3. **NO-CANON report (86):** Enumerated ALL discoverable per-profile SKILL.md (`<profile>/skills/<cat>/<skill>/SKILL.md`), found 86 with no canonical twin. Per-god: hephaestus 28, marvin 21, thoth 15, iris 12, apollo 5, cachyos 4, rheta 1. Operator ratified the 86-scope (vs the loose 127 from a wider find).
4. **Did NOT touch:** `~/.hermes/skills/` (canonical), any per-profile non-SKILL files, any NO-CANON per-profile SKILL.md, production rule YAMLs, conductor engine code.

## Your QA checks (in order)

### Check 1: Symlink integrity (the actual fix)

```bash
# 1a. Verify all 95 symlinks resolve to the correct canonical target.
# Read the original drift list and confirm each per-profile path is now a symlink
# whose target matches the inferred canonical path.
DRIFT_LIST="/tmp/step-4.3-drift-list.txt"
MISSING=0
WRONG_TARGET=0
while IFS= read -r line; do
  [[ -z "$line" || "$line" == \#* ]] && continue
  pp=$(echo "$line" | awk '{print $NF}')
  if [[ ! -L "$pp" ]]; then
    echo "NOT A SYMLINK: $pp"
    ((MISSING++))
    continue
  fi
  target=$(readlink "$pp")
  expected=$(echo "$pp" | sed 's|/profiles/\([^/]*\)/skills/|/skills/|')
  if [[ "$target" != "$expected" ]]; then
    echo "WRONG TARGET: $pp -> $target (expected $expected)"
    ((WRONG_TARGET++))
  fi
done < "$DRIFT_LIST"
echo "MISSING=$MISSING WRONG_TARGET=$WRONG_TARGET"
# Expect: MISSING=0 WRONG_TARGET=0
```

```bash
# 1b. Spot-check 5 symlinks: the symlinked file content is byte-identical to canonical.
for pp in $(awk '/canon=/ && !/^#/ {print $NF}' "$DRIFT_LIST" | head -5); do
  canon=$(echo "$pp" | sed 's|/profiles/\([^/]*\)/skills/|/skills/|')
  diff -q "$canon" "$pp" && echo "OK: $pp"
done
# Expect: 5 OK lines (diff -q exits 0 on identical files; symlink resolves transparently)
```

### Check 2: References/ additive-only guarantee

```bash
# 2a. Per-profile references/ file count should be ≥ pre-fix count.
# Pre-fix (Marvin's report): 1270 files. Post-fix: 1821 (his number) or close.
# (Some drift is expected as other gods add files concurrently.)
find /home/konan/.hermes/profiles -type f -path "*/skills/*/*/references/*" \
  | wc -l
# Expect: ≥ 1500 (allow for concurrent god activity)
```

```bash
# 2b. Spot-check: per-profile references/ files that DIDN'T exist in canonical
# should still be intact. Pick a profile with known pre-existing per-profile-only files.
# Thoth's earlier finding: thoth-dawn-patrol had 5 per-profile, 2 canonical, zero overlap.
ls -la /home/konan/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/references/ 2>/dev/null
ls -la /home/konan/.hermes/skills/thoth/thoth-dawn-patrol/references/ 2>/dev/null
# Both should be present. If per-profile has 5+ files, those pre-existing per-profile files
# must still be there (not clobbered by rsync).
```

```bash
# 2c. Verify rsync was additive (--ignore-existing). Canonical-then-per-profile
# mtime check: a per-profile file that did NOT exist in canonical before should
# have an mtime NEWER than the rsync window (Marvin ran ~16:30Z, so check mtimes).
find /home/konan/.hermes/profiles -type f -path "*/skills/*/*/references/*" \
  -newermt "2026-06-15 16:25" | wc -l
# Expect: ~551 (matches Marvin's claimed rsync adds, allow for concurrent activity)
```

### Check 3: NO-CANON report accuracy

```bash
# 3a. Re-derive the NO-CANON count independently. Don't trust the report.
# A SKILL.md is NO-CANON if it lives at <profile>/skills/<cat>/<skill>/SKILL.md
# AND there's no canonical twin at ~/.hermes/skills/<cat>/<skill>/SKILL.md.
count=0
while IFS= read -r pp; do
  canon=$(echo "$pp" | sed 's|/profiles/\([^/]*\)/skills/|/skills/|')
  [[ ! -f "$canon" ]] && ((count++))
done < <(find /home/konan/.hermes/profiles -mindepth 4 -maxdepth 4 -type f -name SKILL.md \
  -path "*/skills/*/*/SKILL.md" -not -path "*/.npm/*" -not -path "*/.bun/*" -not -path "*/.archive/*")
echo "INDEPENDENT NO-CANON COUNT: $count"
# Expect: 86 (matches Marvin's report)
```

```bash
# 3b. Compare your re-derived list to Marvin's report. Same 86 paths?
diff <(awk -F'|' 'NR>5 && $1 !~ /^#/ && $1!="" {print $4}' \
       /home/konan/pantheon/shared/active/conductor-step-4.3-no-canon.txt | sort) \
     <(find /home/konan/.hermes/profiles -mindepth 4 -maxdepth 4 -type f -name SKILL.md \
       -path "*/skills/*/*/SKILL.md" -not -path "*/.npm/*" -not -path "*/.bun/*" -not -path "*/.archive/*" \
     | while read pp; do
         canon=$(echo "$pp" | sed 's|/profiles/\([^/]*\)/skills/|/skills/|')
         [[ ! -f "$canon" ]] && echo "$pp"
       done | sort)
# Expect: no output (identical lists)
```

```bash
# 3c. Spot-check 3 NO-CANON entries: confirm they really have no canonical twin.
# Pick one each from hephaestus, marvin, thoth (the top 3).
head -10 /home/konan/pantheon/shared/active/conductor-step-4.3-no-canon.txt
# Manually verify 3 of the listed paths have no canonical twin.
```

### Check 4: Regression — pytest still 193/193

```bash
cd /home/konan/pantheon/conductor && \
  PANTHEON_ROOT=/home/konan/pantheon \
  PYTHONPATH=/home/konan/pantheon \
  pytest v2/tests -q
# Expect: 193 passed, 1 skipped (matches pre-fix baseline; no regressions)
```

### Check 5: Canonical untouched

```bash
# Spot-check 5 canonical SKILL.md that were symlink targets: mtime + size
# should match the audit (canon_size column in drift list).
# Pick from the drift list, compare actual canonical mtime vs the mtime column.
awk '/canon=/ && !/^#/ {print $1, $2, $NF}' /tmp/step-4.3-drift-list.txt | head -5
# For each line, the first field is canonical size, the second is canonical mtime.
# Manually verify the canonical file at the inferred path still has those attrs.
# (This is a rough check — Marvin ran rsync but explicitly said he didn't touch canonical.)
```

### Check 6 (optional): Fresh-profile skill load

```bash
# You ARE a fresh thoth-profile session. Verify the §5.5 (Step 4.2 spec) is still
# loaded correctly, AND that a representative symlinked skill (e.g. writing-plans
# or test-driven-development) also loads correctly.
grep -c "5.5 CHECK CONDUCTOR QUARANTINE BACKLOG" \
     /home/konan/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/SKILL.md
# Expect: ≥1 (Step 4.2 fix still intact)

# And a known symlinked one:
readlink /home/konan/.hermes/profiles/thoth/skills/software-development/writing-plans/SKILL.md
# Expect: a path under /home/konan/.hermes/skills/...
```

## Deliverable (back to me)

A short QA report:

1. **Checks 1-6 results** — pass/fail each, with the actual command output (paste, don't summarize).
2. **NO-CANON count verdict** — does your independent count match Marvin's 86? (Yes / no / different number with explanation.)
3. **Verdict on Step 4.3:** **SHIP** (verified) / **NEEDS REWORK** (with what) / **INCONCLUSIVE** (with what's missing).
4. **Open questions** for me.

## Out of scope (do not do these)

- Do NOT touch any per-profile symlinks. You are verifying, not changing.
- Do NOT touch `~/.hermes/skills/` (canonical).
- Do NOT touch the NO-CANON report.
- Do NOT re-run any rsync.
- Do NOT start any Step 4.4 work.

## Constraints

- **No fabrication.** If a check fails or is unclear, say so.
- **Independent verdict.** Do not just confirm Marvin's claims — verify each.
- **~15-20 min target.** This is QA, not a rebuild.

## Handoff back

Drop a 1-paragraph handoff to Hermes inbox (`mcp_pantheon_messaging_send to=hermes`) with:
- QA verdict (SHIP / NEEDS REWORK / INCONCLUSIVE)
- 1-2 sentence summary
- Independent NO-CANON count (and whether it matches Marvin's 86)
- Any blockers

Then I'll either greenlight the NATS breach operator-action plan (next PM-loop item) or send Marvin back for rework.

— Hermes (PM), 2026-06-15 16:35Z
