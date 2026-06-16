# Conductor v2 — Step 4.4, Brief 2 of 3 — Apply per-profile symlinks for detected skills

**From:** Hermes (PM)
**To:** Marvin
**Cycle:** PM-loop, post-Brief 1 SHIP
**Status:** pending → in-progress on your ack
**Spec:** `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml#step-4.4` (full step), `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml#step-4.4.briefs.brief_2_of_3` (this brief)

---

## TL;DR

Brief 1 shipped the detector (`profile-bootstrap-detect.{sh,py}`) which reports 762 missing per-profile symlinks across 7 god profiles plus 360 drifted regular files. **This brief is Brief 2 of 3** — the apply half. You will write an applier that takes the detector's output (or runs the same scan inline) and creates the missing symlinks with `ln -sf`, force-overwriting the drifted regular files. Brief 3 is the verification (fresh-gateway-start test, pytest, no regression on existing symlinks).

## What came before (context, not your work)

- **Brief 1 SHIPPED**: `~/pantheon/conductor/scripts/profile-bootstrap-detect.py` exists, runs, emits 762 stdout lines + 360 stderr drift lines for the current state. Confirmed by Hermes review session at the start of this PM cycle.
- **Step 4.3 closed 95 drifted skills** with `ln -sf` to canonical. Step 4.4 Brief 2 closes the **new** drift (762 missing + 360 regular-file drift that Brief 1's detector flagged).
- **The 86 NO-CANON entries** at `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt` are still the authoritative exclusion list. Reuse the parser from Brief 1.

## Real numbers (operator-pinned 2026-06-15)

```
Detector output (re-run 2026-06-15T17:55Z, stdin = live filesystem):
  apollo       88 missing symlinks
  cachyos      89
  hephaestus   88
  iris         89
  marvin      160   (zero coverage — every canonical skill is missing)
  rheta       160   (zero coverage — same)
  thoth        88
  -----------
  TOTAL       762 missing

Drift (stderr from same run — regular files where symlinks should be):
  TOTAL       360 drifted per-profile regular files (Brief 1's stderr log)

Canonical skills in scope: 160 (per Brief 1's `iter_canonical_skill_files`)
NO-CANON filter: 86 entries (currently zero-impact — paths don't collide with canon)
```

**Sanity check you can run yourself:**
```bash
python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py 2>/dev/null | wc -l   # → 762
python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py 2>&1 >/dev/null | wc -l   # → 360 drift
```

## Your task (this brief only)

Write an applier script that creates per-profile symlinks for every canonical skill that Brief 1 flagged as missing or drifted. The script must be **safe to re-run (idempotent)**, **dry-run capable by default**, and **require an explicit flag to actually mutate the filesystem**.

### Script requirements

1. **Location:** `~/pantheon/conductor/scripts/profile-bootstrap-apply.sh` (or `.py` if you prefer Python — your call). **Bash is fine if it stays readable; Python is fine if you want clean JSON I/O.** Mirror the language choice from Brief 1 (which you shipped as Python) unless you have a strong reason to switch.

2. **Inputs:**
   - **The canonical skills root** (same as Brief 1): `~/.hermes/skills/<cat>/<skill>/SKILL.md`
   - **The per-profile skills roots** (same as Brief 1): `~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md`
   - **The 86 NO-CANON exclusions** (same as Brief 1): `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt`
   - **The 7 god profiles in scope** (same as Brief 1): `apollo cachyos hephaestus iris marvin rheta thoth`

3. **Logic (do this in order, fail loudly on any mismatch):**

   a. **Re-run detection inline** (don't trust a captured stdout from a previous run — the filesystem is the source of truth). Call Brief 1's logic OR duplicate the scan-and-filter into the applier. Recommendation: import / source Brief 1's module if you went Python; if you went Bash, just `python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py 2>/dev/null` and parse the stdout.

   b. **Build the to-do list:** for each `(god, cat, skill)` flagged as missing by the detector, plan to create `~/.hermes/profiles/{god}/skills/{cat}/{skill}/SKILL.md` as a symlink → `~/.hermes/skills/{cat}/{skill}/SKILL.md`.

   c. **Sanity checks before any write:**
      - Canonical target must exist and be a regular file (`is_file()` + `not is_symlink()`). If not, ABORT with a clear error naming the bad target.
      - Per-profile parent dir must be creatable (`mkdir -p` of `~/.hermes/profiles/{god}/skills/{cat}/{skill}/`). No `chmod`, no `chown` — just `mkdir -p`.
      - If the per-profile path already exists as a symlink, verify `readlink` resolves to the same canonical target. If yes: skip (already correct, log "skip: already symlinked to correct target"). If no (broken or pointing elsewhere): overwrite with `ln -sf` (this is the drift case).
      - If the per-profile path already exists as a regular file (the 360 drift): overwrite with `ln -sf` (Brief 1 marked it as drift; Brief 2 fixes it).

   d. **Apply with `ln -sf`:** for each to-do entry, run `ln -sf <canonical_target> <per_profile_path>`. Force-overwrites both drift (regular file) and stale-wrong-target (symlink to wrong place) cases.

   e. **Verify after the write:** after each `ln -sf`, confirm the resulting path is a symlink (`is_symlink()`) and `readlink` resolves to the expected canonical target. If not, log the failure to stderr and increment a `failed_count`. Do NOT abort the whole run on a single failure — continue with the next entry.

   f. **Summary at end (stdout):**
      ```
      attempted: <int>
      succeeded: <int>
      skipped (already correct): <int>
      failed:    <int>
      ```
      Plus an exit code:
      - `0` if `failed == 0` (success or partial success is still 0 — we report partial via the summary)
      - `1` only if the script itself is broken (parse error, NO-CANON file missing, canonical root missing, etc.) AND nothing was written

4. **CLI flags:**
   - `--dry-run` (default true if not specified): print the to-do list and the summary, but **do NOT touch the filesystem**. This is the safety rail — operators can run it cold and review.
   - `--apply`: actually mutate the filesystem. **Required** to override `--dry-run`. Without this flag, the script is a no-op (just like Brief 1).
   - `--god <name>`: optional. Restrict to a single profile. Useful for testing one god at a time. Repeatable (`--god apollo --god thoth`).
   - `--limit <int>`: optional. Cap the number of symlinks created. Useful for staged rollout (e.g. `--limit 10` to test on 10 skills first).
   - `--json`: optional. Emit the to-do list + summary as JSON for downstream tooling (Brief 3's verification step, dashboard panels).
   - `--backup-dir <path>`: optional. Default: `~/.hermes/profiles/_bootstrap-backups/<timestamp>/`. If a per-profile regular file is about to be overwritten (drift case), copy it to the backup dir first. The symlink itself is trivially reversible (just `rm`); the **drift backup is the safety net** in case an operator wants to see what a profile's local file said before it was force-symlinked.

5. **Output (default text mode, applies to both --dry-run and --apply):**
   - **stdout:** the per-entry log (one line per symlink created/skipped) + final summary
   - **stderr:** the same drift log Brief 1 emits (so operators can see drift separately from the apply pass)
   - **Exit code:** as specified in (3.f)

6. **Constraint: Brief 1 must remain untouched.** Don't edit `profile-bootstrap-detect.py`. The applier treats it as a black box. If you need to refactor (e.g. extract a shared lib), propose it in the handoff — don't do it unilaterally.

### What about the 360 drift entries — do those get force-overwritten?

**Yes.** That is Brief 2's job. Brief 1 reported them as drift; Brief 2 fixes them. The `--backup-dir` flag (requirement 4) is the safety net so we don't lose data — every overwritten regular file is preserved at `~/.hermes/profiles/_bootstrap-backups/<timestamp>/<god>/<cat>/<skill>/SKILL.md` before the `ln -sf` runs.

**Important:** the backup dir itself must be excluded from any future Brief 1 runs (otherwise Brief 1's scan would see it as a profile). Brief 1 already only scans 7 named god profiles (`TARGET_PROFILES = ("apollo", "cachyos", "hephaestus", "iris", "marvin", "rheta", "thoth")`) — `_bootstrap-backups` is not in that list, so it's already excluded by name. Confirm this in your handoff; if Brief 1 ever changes its profile enumeration, the backup dir is safe because it's not a god name.

## Success criteria (this brief)

1. `~/pantheon/conductor/scripts/profile-bootstrap-apply.sh` (or `.py`) exists.
2. `bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --dry-run` runs and prints the 762-entry to-do list + a summary, exit 0, **no filesystem changes**.
3. `bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --apply` runs and creates 762 symlinks (or 762 - skipped, where `skipped` is non-zero if Brief 1's drift-360 already includes some symlinks that pre-resolve correctly). Drift entries are force-overwritten; backups land in `~/.hermes/profiles/_bootstrap-backups/<timestamp>/`.
4. After `--apply`: re-running Brief 1's detector shows **0 missing** and **0 drift** (idempotency proof).
5. After `--apply`: `find ~/.hermes/profiles -name SKILL.md -type l | wc -l` increases by exactly 762 (or the same minus the pre-existing-symlink count from criterion 3).
6. After `--apply`: the 86 NO-CANON entries from `conductor-step-4.3-no-canon.txt` are still present at their per-profile paths (NOT force-symlinked, since the filter excluded them).
7. The 95 symlinks that Step 4.3 created are still correct after the apply pass (verify with `find ... -type l` + readlink spot-check on a sample of 5).
8. Exit code 0 on the live `--apply` run. Exit code 1 only on script-broken scenarios (test with a deliberately broken NO-CANON path).

## Verification (how I'll know it works)

```bash
# 1. Dry-run sanity (no writes)
bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --dry-run 2>/dev/null | head -5
# Expect: tab-separated per-entry log, first line should be one of the 762 missing entries

bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --dry-run 2>/dev/null | wc -l
# Expect: 762 (matches Brief 1's stdout)

# 2. Backups are creatable
bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --dry-run --backup-dir /tmp/test-backup
# Expect: prints backup dir plan but doesn't create it (dry-run)

# 3. Snapshot before apply (operator's safety net — your script can also do this internally)
SNAPSHOT_BEFORE=$(find ~/.hermes/profiles -name SKILL.md | wc -l)
DRIFT_BEFORE=$(python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py 2>&1 >/dev/null | wc -l)
echo "Before: $SNAPSHOT_BEFORE SKILL.md total, $DRIFT_BEFORE drift entries"

# 4. THE actual apply
bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --apply
# Expect: 762 succeeded, 0 failed (or near-zero with explanations for any failure)

# 5. Post-apply verification
SNAPSHOT_AFTER=$(find ~/.hermes/profiles -name SKILL.md | wc -l)
MISSING_AFTER=$(python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py 2>/dev/null | wc -l)
DRIFT_AFTER=$(python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py 2>&1 >/dev/null | wc -l)
echo "After:  $SNAPSHOT_AFTER SKILL.md total, $MISSING_AFTER missing, $DRIFT_AFTER drift"
# Expect: MISSING_AFTER = 0, DRIFT_AFTER = 0

# 6. NO-CANON preservation
for line in $(grep -v '^#' ~/pantheon/shared/active/conductor-step-4.3-no-canon.txt | head -3 | cut -d'|' -f1,2,3); do
  god=$(echo $line | cut -d'|' -f1)
  cat=$(echo $line | cut -d'|' -f2)
  skill=$(echo $line | cut -d'|' -f3)
  pp=~/.hermes/profiles/$god/skills/$cat/$skill/SKILL.md
  if [ -f "$pp" ] && [ ! -L "$pp" ]; then
    echo "OK: $pp is a regular file (preserved as NO-CANON)"
  else
    echo "FAIL: $pp is a symlink or missing (NO-CANON should be regular)"
  fi
done

# 7. Sample check on Step 4.3 symlinks (these should still be correct)
# (Per Thoth QA 2026-06-16: the original sample used 'thoth/thoth-dawn-patrol' which
#  is in NO-CANON — that path is a per-profile regular file, not a Step 4.3 symlink.
#  Replaced with paths that are actually symlinked by Step 4.3.)
for skill in 'thoth/dogfood' 'pantheon/pantheon-bridge' 'devops/api-integration'; do
  for god in apollo cachyos hephaestus iris thoth; do
    pp=~/.hermes/profiles/$god/skills/$skill/SKILL.md
    target=$(readlink "$pp" 2>/dev/null)
    if [ -n "$target" ]; then
      echo "OK: $pp -> $target"
    else
      echo "FAIL: $pp is not a symlink"
    fi
  done
done

# 8. Idempotency
bash ~/pantheon/conductor/scripts/profile-bootstrap-apply.sh --apply
# Expect: all 762 entries report "skipped: already correct", 0 created, 0 failed
```

## Files touched (this brief only)

- NEW: `~/pantheon/conductor/scripts/profile-bootstrap-apply.{sh,py}` (your call on extension; mirror Brief 1)
- NEW: `~/pantheon/conductor/scripts/tests/test_profile_bootstrap_apply.{sh,py}` (smoke test, optional but cheap)
- NEW (created at apply time, gitignored): `~/.hermes/profiles/_bootstrap-backups/<timestamp>/<god>/<cat>/<skill>/SKILL.md` (the drift backups)
- UPDATED: `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` — flip Step 4.4 status to `in_progress` and update `current_step` to `4.4.briefs.brief_2_of_3`. (Brief 3 will flip to DONE.)

## Out of scope (Brief 3)

- Verifying with a fresh-gateway-start test (Brief 3)
- pytest lock-in (Brief 3)
- The systemd wiring (the hook that calls Brief 1 at gateway start) — that's Brief 3's wiring step, not this brief
- Heuristic .archive/ cleanup for the 6 hephaestus entries (Step 4.5, different work)
- YAML guardrails + workflow validator (Step 4.6, deferrable)

## Constraints (hard rules)

- **No canonical edits.** Don't touch `~/.hermes/skills/`. Symlinks point AT canonical, never the other way.
- **No silent destruction of drift files.** Every regular file you overwrite must first be backed up to `--backup-dir` (default: `~/.hermes/profiles/_bootstrap-backups/<timestamp>/`). The backup is the operator's audit trail.
- **`--dry-run` is the default.** Don't make `--apply` the default. The point of this script is to be reviewable before it mutates.
- **Stay in your lane.** This is hermes-profile + main + per-profile scripts territory. Don't touch thoth/iris/hephaestus/cachyos/apollo/rheta/marvin's other config.
- **The 86 NO-CANON entries must be filtered.** Same parser as Brief 1. Don't re-flag them or re-symlink them.
- **`.archive/` subdirs are out of scope.** Same filter as Brief 1.
- **Idempotent re-runs must be safe.** Running `--apply` twice in a row must not break anything. The second run should report "skipped: already correct" for all 762 entries.

## Reversibility

- **Symlinks:** `find ~/.hermes/profiles -name SKILL.md -type l -newer <apply-timestamp> -delete` removes the new symlinks. (Or per-profile: `rm ~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md`.)
- **Drift backups:** preserved at `~/.hermes/profiles/_bootstrap-backups/<timestamp>/`. Operator can `cp` them back to restore drift state.
- **The apply script itself:** `rm` the script = full revert (no state files, no daemon, no service file edits).

## Deadline / handoff

**Target wall-clock:** 30-45 min.
**Handoff back to me:** Same format as Brief 1 (root cause 1-sentence, files changed, verification output, open questions).
Drop a 1-paragraph handoff to Hermes inbox (`mcp_pantheon_messaging_send to=hermes`) when done. I'll review, hand to Thoth for independent QA, then dispatch Brief 3.

## Reference data (pin these)

- **Canonical skills root:** `~/.hermes/skills/<cat>/<skill>/SKILL.md` (depth 3: `~/.hermes/skills/{cat}/{skill}/SKILL.md`)
- **Per-profile skills roots:** `~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md`
- **Profiles in use today:** apollo, cachyos, hephaestus, iris, marvin, rheta, thoth (7 total)
- **NO-CANON report:** `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt` (14.3K, 86 entries, pipe-separated)
- **Brief 1 detector:** `~/pantheon/conductor/scripts/profile-bootstrap-detect.py` (treat as black box; do not edit)
- **Step 4.3 audit list (the 95 already-symlinked):** `/tmp/step-4.3-drift-list.txt` (still on disk; sample-check 5 of these after --apply to confirm no regression)

## Open question for you (don't block on it)

**Single-shot vs. staged apply.** My read: ship a single `--apply` that does all 762 in one go (it's fast — `ln -sf` is microseconds per call). If you want a safety net, gate the first run with `--limit 50` to confirm the script works, then re-run without `--limit` to finish. Your call. Either way, the script must support `--limit` because Brief 3's verification will use it.

— Hermes (PM), 2026-06-15T18:00Z
