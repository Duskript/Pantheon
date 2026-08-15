# Conductor v2 — Step 4.5 Brief 3 of 3

## Scope (this brief)

Verify that the 6 `.archive/` removals (Brief 2 v2) haven't broken
anything. Concretely:

1. The Step 4.4 bootstrap wire still runs cleanly on gateway start
2. The 1126 symlinks are still 1126 (no regression on the symlink
   count)
3. Pytest 200/1-skip/0-fail (Brief 2's V8 gate; the gate test file
   was corrupted and restored by the operator mid-brief, this is
   the closure check)
4. The bash detector test 12/12
5. The 6 `.archive/` entries are still gone (Brief 2's V5 was
   post-rm; this is the after-restart check)
6. The 11 backup files are still in `athenaeum/` (Brief 2's V7
   was post-rm; this is the after-restart check)

If all 6 pass, Step 4.5 is closed. No new code, no new files.
This is a pure verification brief.

## Background

- **Brief 1** (done): 6/6 OBSOLETE disposition. Output at
  `~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`.
- **Brief 2 v1** (blocked at V4): no backup existed. Blocker at
  `~/pantheon/shared/active/conductor-step-4.5-brief-2-blockers.md`.
- **Brief 2 v2** (done): 6 entries removed, 11 files preserved in
  `~/athenaeum/Codex-God-hephaestus/.archive/`. Handoff at
  `msg_20260616_035528_hermes`. Found + reported a pre-existing
  test-file corruption (the operator restored it from git).
- **Brief 3** (this brief): closure verification.

## What you do

### Step 1: Pre-restart snapshot

Capture the current state for the after-restart diff.

```bash
# Symlink count per profile (the 1126 baseline)
for profile in apollo cachyos hephaestus iris marvin rheta thoth hermes; do
  count=$(find "$HOME/.hermes/profiles/$profile/skills" -type l 2>/dev/null | wc -l)
  echo "$profile: $count symlinks"
done

# .archive/ should already be empty
find ~/.hermes/profiles/hephaestus -name SKILL.md -path '*.archive/*' | wc -l
# Expect: 0

# Backup should still be intact
find ~/athenaeum/Codex-God-hephaestus/.archive/ -type f | wc -l
# Expect: 11
```

### Step 2: Restart one gateway profile

The Step 4.4 bootstrap wire (Brief 3 of Step 4.4) is wired to the
template `hermes-gateway@.service` with `ExecStartPre=-...`. Restarting
ANY profile will exercise the wire (it's `%i`-substituted). Pick
**hephaestus** (it's the profile that owned the removed entries, so
its restart is the highest-signal test).

```bash
# Restart the hephaestus gateway
systemctl --user restart hermes-gateway@hephaestus.service

# Wait for it to come up
sleep 3

# Confirm it's active
systemctl --user is-active hermes-gateway@hephaestus.service
# Expect: active
```

### Step 3: Verify the bootstrap ran

The bootstrap is `ExecStartPre=-...` so it runs BEFORE the gateway
starts. The output goes to the journal (template service has
`StandardOutput=journal`+`StandardError=journal`).

```bash
# Pull the bootstrap output from the journal
journalctl --user -u hermes-gateway@hephaestus.service -n 50 --no-pager | \
  grep -E "profile-bootstrap-apply|attempted|succeeded|skipped|failed|missing_total"
# Expect: lines showing the apply.py summary
# (e.g. "missing_total: 0", "attempted: 0", "skipped: N", "failed: 0")
```

**Note:** The bootstrap output may be terse on a no-op restart
(state is current, nothing to do). The key signal is `missing_total: 0`
and `failed: 0` — those two mean "bootstrap ran, no drift detected,
no errors."

### Step 4: Post-restart snapshot

Re-run the Step 1 snapshot commands and diff.

```bash
# Symlink count per profile (should be IDENTICAL to pre-restart)
for profile in apollo cachyos hephaestus iris marvin rheta thoth hermes; do
  count=$(find "$HOME/.hermes/profiles/$profile/skills" -type l 2>/dev/null | wc -l)
  echo "$profile: $count symlinks"
done

# .archive/ still empty
find ~/.hermes/profiles/hephaestus -name SKILL.md -path '*.archive/*' | wc -l
# Expect: 0

# Backup still intact
find ~/athenaeum/Codex-God-hephaestus/.archive/ -type f | wc -l
# Expect: 11
```

The key invariant: **symlink count is unchanged** before and after
the restart. If the bootstrap is broken, the count would drop
(missing) or grow (false-positive symlink creation). Neither should
happen.

### Step 5: Gate test suite

```bash
# Run the pytest suite the right way (NOT python3 -m pytest, which
# may be intercepted by a wrapper; use the venv binary directly)
cd ~/pantheon/conductor/v2 && \
  PYTHONPATH=/home/konan/pantheon \
  ~/.hermes/hermes-agent/venv/bin/pytest tests/ -q --tb=line 2>&1 | tail -5
# Expect: 200 passed, 1 skipped, 0 failed
```

```bash
# Run the bash detector test
bash ~/pantheon/conductor/scripts/tests/test_profile_bootstrap_detect.sh 2>&1 | tail -3
# Expect: 12 passed, 0 failed
```

### Step 6: Run the detector one more time

```bash
# Direct detector call (not through the bootstrap wire)
python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py
# Expect: 0 stdout lines (no missing), clean stderr (no drift, no errors), exit 0
```

This is the dry-run of the detector itself, separate from the
bootstrap. The bootstrap's output is the wire-level view; this is
the direct read of the detector state.

## Verification (this brief)

- **V1:** Pre-restart symlink counts captured (expect 7 profiles
  with counts in the 150-170 range, total 1126 ± 1 hardlink case).
- **V2:** Post-restart symlink counts **match pre-restart counts
  per profile** (hard gate — the bootstrap must be a no-op on
  current state).
- **V3:** `find ... -path '*.archive/*' -name SKILL.md` returns 0
  (the 6 entries stayed gone after the restart).
- **V4:** `find athenaeum/Codex-God-hephaestus/.archive/ -type f`
  returns 11 (the backup is intact across the restart).
- **V5:** Gateway is `active` after restart.
- **V6:** Journal shows the bootstrap output, with `missing_total: 0`
  and `failed: 0` (the bootstrap ran cleanly).
- **V7:** pytest 200/1-skip/0-fail (the gate test file is clean;
  V8 from Brief 2 v2 was unrunnable due to corruption — the
  operator restored it, this confirms the restore is good).
- **V8:** bash detector test 12/12.
- **V9:** Direct detector call: 0 missing, exit 0, no drift log.

## Out of scope (this brief)

- Any code changes (this is pure verification).
- Any symlink changes (the bootstrap should be a no-op).
- Removing the 11 backup files (the backup is the reversibility
  safety net; it stays until Step 4.5 is fully closed and
  ratifed at Phase 4 review).
- Restarting more than 1 profile (hephaestus is the highest-signal
  case; if it works, the other 6 templates will work too).
- Touching any per-profile path other than the hephaestus gateway
  service.

## On what to do if a check fails

- **V2 fails (symlink count changed):** STOP. This means the
  bootstrap either missed a missing symlink (decreased count) or
  created an unexpected one (increased count). Pull the journal
  with `journalctl --user -u hermes-gateway@hephaestus.service -n 200`
  and look for `profile-bootstrap-apply` lines. If the bootstrap
  attempted to create a symlink that the detector didn't flag as
  missing, that's a P1 hotfix candidate. Write blocker to
  `~/pantheon/shared/active/conductor-step-4.5-brief-3-blockers.md`
  and ping Hermes.
- **V3 fails (`.archive/` entries reappeared):** This would mean
  the Step 4.4 detector's `.archive/` exclusion is broken AND the
  bootstrap is trying to recreate the entries. Very unlikely (the
  bootstrap only re-creates `skills/<cat>/<name>/` paths, not
  `.archive/`), but if it happens, write blocker immediately.
- **V4 fails (backup files disappeared):** This is a filesystem
  anomaly. The 11 backup files were created by the operator with
  `cp -a` and not touched since. If they're gone, the filesystem
  layer is doing something weird. STOP and investigate.
- **V5/V6 fail (gateway didn't come up):** The bootstrap's `-`
  prefix (non-fatal) means a bootstrap failure shouldn't block
  startup. If the gateway is `inactive` or `failed` after the
  restart, the issue is in the gateway itself, not the bootstrap.
  Look at the journal for non-bootstrap errors.
- **V7 fails (pytest < 200):** The gate test file corruption may
  have recurred. Restore it from git:
  `cd ~/pantheon && git checkout HEAD -- conductor/v2/tests/test_bootstrap_detect.py`,
  re-run, investigate the source of the corruption.

## Reversibility

This brief is pure verification. If a check fails, don't reverse
any state — diagnose first, then decide whether to write a blocker
or take corrective action. Brief 2 v2's destructive op is already
done; the backup is the only path back.

## Reference pinning (don't re-discover)

- Brief 1 disposition: `~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`
- Brief 2 v1 blocker: `~/pantheon/shared/active/conductor-step-4.5-brief-2-blockers.md`
- Brief 2 v2 handoff: `msg_20260616_035528_hermes`
- Brief 3 of Step 4.4 (the bootstrap wire that this brief verifies):
  `~/.config/systemd/user/hermes-gateway@.service.d/10-skill-bootstrap.conf`
- Backup location: `~/athenaeum/Codex-God-hephaestus/.archive/`
- Step 4.4 squash merge: commit `811197f` on `main`
- Step 4.4 P1 hotfix (mcp_server.py → v2 engine): commit `63f2d36`
  (folded into 811197f via squash)
- Step 4.4 P2 #2 hotfix (detector inode check): commit `bf8677d`
  (folded into 811197f via squash)
- Gate tests: `~/pantheon/conductor/v2/tests/test_bootstrap_detect.py`
- Detector: `~/pantheon/conductor/scripts/profile-bootstrap-detect.py`
- Applier: `~/pantheon/conductor/scripts/profile-bootstrap-apply.py`
- Plan YAML: `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml`
  (Step 4.5 lines 71-88; will be flipped to DONE on Brief 3 SHIP)

## Time budget

10 min. Pre/post snapshots are 30 seconds each, restart is 1 second,
gate tests are 90 seconds (pytest dominates), journal grep is 30
seconds. Total wall-clock ~5 min plus 5 min buffer for setup.

## Drop a handoff

1-paragraph handoff to Hermes inbox (mcp_pantheon_messaging_send
to=hermes) when done, same shape as your Step 4.4 briefs (root cause
1-sentence, files changed, verification output, open questions).
If all 9 checks pass, also include the literal string
"**STEP 4.5 CLOSED — ready for plan YAML flip**" so the operator
knows the next action is on them, not you.

If blocked: write blocker to
`~/pantheon/shared/active/conductor-step-4.5-brief-3-blockers.md`
and ping Hermes.
