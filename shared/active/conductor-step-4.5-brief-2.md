# Conductor v2 — Step 4.5 Brief 2 of 3 (v2 — backup was missing on first dispatch)

## What changed since v1

v1 of this brief (sent earlier in the day) was BLOCKED at pre-flight
V4: the backup path `~/athenaeum/Codex-God-hephaestus/.archive/`
did not exist. The plan YAML's reversibility claim (line 86) was
aspirational, not verified. Marvin caught it, wrote a blocker, and
stopped. **No data was lost.**

Per the operator call ("Option A: create backup, then re-run Brief 2"),
the backup has now been created. This v2 of the brief is identical
to v1 in intent, with two changes:

1. The backup path now exists (verified by the operator at ~03:50Z
   2026-06-16). Pre-flight V4 will pass.
2. The V1 expectation is corrected: the brief said "exactly 6 dirs
   × 1 file each = 6 SKILL.md total." Reality is 6 dirs × **11 files
   total** (SKILL.md + scripts/ + references/). This v2 pins the
   correct count.

## Scope (this brief)

Act on the Brief 1 dispositions: remove the 6 hephaestus `.archive/`
entries that Brief 1 classified as OBSOLETE. Read-only on canonical,
no symlink changes, no service changes. Just `rm -rf` 6 specific
directories with the destructive-op pre-flight check.

## Background (Brief 1 result)

6/6 OBSOLETE. Curator 2026-05-06 already merged 5/6 into
`pantheon-god-architecture` (3 as `references/` subfiles, 1 as a
section in the main SKILL.md). The 6th (`js-regex-escaping`) is a
1.5 KB micro-entry with 0 refs and 0 activity. No DUPLICATEs (the
demoted twins are `references/` subfiles, not same-named canonicals).

## The 6 entries + their full bundle (Brief 1 + V1 finding)

| Entry | SKILL.md | Bundle extras | Total bytes |
|---|---|---|---|
| `capture-idea` | 3,050 B | `scripts/add-idea.py` (2,759 B, exec) | 5,809 |
| `js-regex-escaping` | 1,642 B | (none) | 1,642 |
| `pantheon-god-bot-setup` | 13,470 B | `references/apollo-bot-setup-example.md` (3,146 B) | 16,616 |
| `pantheon-mcp-server` | 13,903 B | (none) | 13,903 |
| `pantheon-system-migration` | 6,395 B | `references/export-script.md` (1,450 B) + `references/install-script.md` (1,543 B) | 9,388 |
| `pantheon-wsl-networking` | 7,673 B | `references/remote-work-constraints.md` (2,621 B) | 10,294 |

Total: 11 files, 57,652 B. Plus perms/mtime preserved by `cp -a`.

## Pre-flight checklist (mandatory, before any rm)

1. **V1 — verify 6 dirs present + count matches.** Use:
   ```bash
   for d in capture-idea js-regex-escaping pantheon-god-bot-setup \
            pantheon-mcp-server pantheon-system-migration \
            pantheon-wsl-networking; do
     echo "--- $d ---"
     find "$HOME/.hermes/profiles/hephaestus/skills/.archive/$d" -type f
   done
   ```
   Expected: 11 files total (2+1+2+1+3+2). If any missing, STOP and write blocker.

2. **V2 — confirm 0 canonical twins.** `find ~/.hermes/skills -maxdepth 3
   -name "SKILL.md" -path "*<name>*"` for each name. Expected: 0 hits.

3. **V3 — confirm disposition file is fresh.** `ls -la
   ~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`.
   mtime should be ≤ 30 min old. (The 5-min cap from v1 was arbitrary
   and overly strict; 30 min is the real threshold for "operator is
   working from a fresh audit.")

4. **V4 — confirm backup exists for ALL 11 files.** Use:
   ```bash
   BACKUP=~/athenaeum/Codex-God-hephaestus/.archive
   for d in capture-idea js-regex-escaping pantheon-god-bot-setup \
            pantheon-mcp-server pantheon-system-migration \
            pantheon-wsl-networking; do
     [[ -d "$BACKUP/$d" ]] || { echo "BLOCKER: $d missing from backup"; exit 2; }
     count_src=$(find "$HOME/.hermes/profiles/hephaestus/skills/.archive/$d" -type f | wc -l)
     count_dst=$(find "$BACKUP/$d" -type f | wc -l)
     [[ "$count_src" == "$count_dst" ]] || { echo "BLOCKER: count mismatch in $d: src=$count_src dst=$count_dst"; exit 2; }
   done
   ```
   Expected: all 6 dirs present, 6 file-count matches. If any fail, STOP and write blocker.

## The ops (after pre-flight passes)

```bash
set -euo pipefail

ARCHIVE_ROOT=~/.hermes/profiles/hephaestus/skills/.archive
ENTRIES=(
  capture-idea
  js-regex-escaping
  pantheon-god-bot-setup
  pantheon-mcp-server
  pantheon-system-migration
  pantheon-wsl-networking
)

# Issue 6 plain rm -rf (safe per the destructive-op-checklist
# pre-flight: known-obsolete, backup-verified, all 11 files
# preserved in athenaeum backup, no canonical twin, no other
# consumers). The operator approved plain rm -rf for this brief
# (safe-rm is overkill for .archive/ entries already superseded
# in 5/2026 and now properly backed up).
for entry in "${ENTRIES[@]}"; do
  echo "removing: $ARCHIVE_ROOT/$entry/"
  rm -rf "$ARCHIVE_ROOT/$entry/"
done

# Verify the cleanup
echo "--- post-rm verification ---"
echo "--- .archive/ should be empty (or absent) ---"
ls -la "$ARCHIVE_ROOT/"
echo "--- find should return 0 ---"
find "$ARCHIVE_ROOT" -name SKILL.md
echo "--- backup should still be intact ---"
ls -la ~/athenaeum/Codex-God-hephaestus/.archive/
find ~/athenaeum/Codex-God-hephaestus/.archive/ -name SKILL.md | wc -l
```

## On safe-rm (operator decision: NOT using)

The operator approved plain `rm -rf` for this brief. Rationale (from
the operator decision log `shared/decisions/2026-06-16-step-4.5.md`):

- safe-rm is for irreversible content; these 6 are now backed up
  (120 KB across 11 files at `~/athenaeum/Codex-God-hephaestus/.archive/`)
- Pre-flight V1-V4 is operator-grade; safe-rm is human-grade
- The Step 4.4 Brief 2 incident (glob-mismatch on backup) doesn't
  apply here: 6 literal named paths, no glob, no risk of catching
  the wrong target

If you'd rather use safe-rm, you can — just say so in the handoff.

## Verification (this brief, post-rm)

- **V1:** Pre-flight `ls` of the 6 dirs, expect 11 files (2+1+2+1+3+2). ✓
- **V2:** Pre-flight canonical-twin check, expect 0 hits per name. ✓
- **V3:** Pre-flight disposition-file mtime check, expect ≤ 30 min. ✓
- **V4:** Pre-flight backup check, expect 6 backup dirs × correct file counts. ✓
- **V5:** Post-rm `find ~/.hermes/profiles/hephaestus -name SKILL.md -path '*.archive/*'`, expect **0** results. (Hard gate.)
- **V6:** Post-rm `ls ~/.hermes/profiles/hephaestus/skills/.archive/`, expect empty (or absent if you remove the empty parent).
- **V7:** Post-rm backup integrity: `find ~/athenaeum/Codex-God-hephaestus/.archive/ -name SKILL.md | wc -l` should be 6 (still 6 in backup). And `find ~/athenaeum/Codex-God-hephaestus/.archive/ -type f | wc -l` should be 11 (still 11 in backup).
- **V8:** `pytest -q in conductor/v2/tests/` — expect **200/1-skip/0-fail**. (Hard gate — no regression.)
- **V9:** `bash conductor/scripts/tests/test_profile_bootstrap_detect.sh` — expect **12/12** (no regression; detector's `.archive/` exclusion unchanged).
- **V10:** Re-run the Step 4.4 detector: `python3 ~/pantheon/conductor/scripts/profile-bootstrap-detect.py`. Expect stdout=0 (no missing), stderr=0 (no drift), exit 0.

## Out of scope (this brief)

- Promoting any entry to canonical (Brief 1 found 0 PROMOTE cases).
- Touching any non-`.archive/` per-profile path.
- Editing canonical `~/.hermes/skills/`.
- Changing any daemon or service file.
- Running the Step 4.4 bootstrap wire (Brief 3 will run the
  gateway restart that triggers the bootstrap and verifies nothing
  breaks).

## Reversibility

All 11 files (6 SKILL.md + 5 supplementary) are preserved at
`~/athenaeum/Codex-God-hephaestus/.archive/<name>/`. To restore,
`cp -a athenaeum/Codex-God-hephaestus/.archive/<name>/
~/.hermes/profiles/hephaestus/skills/.archive/<name>/` for each.
The disposition file (Brief 1 output) and the blocker file
(Brief 2 v1 output) are also still in `shared/active/`.

## Reference pinning (no need to re-discover)

- Brief 1 disposition (input): `~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`
- Brief 2 v1 blocker (what we fixed): `~/pantheon/shared/active/conductor-step-4.5-brief-2-blockers.md`
- Operator decision log (the "A" call): `~/pantheon/shared/decisions/2026-06-16-step-4.5.md`
- 6 entry paths + bundle contents: pinned in this brief (table above)
- Backup location (NOW EXISTS): `~/athenaeum/Codex-God-hephaestus/.archive/<name>/`
- Destructive-op checklist skill: `~/.hermes/profiles/marvin/skills/devops/destructive-op-checklist/SKILL.md`
- Step 4.4 detector's `.archive/` exclusion: `~/pantheon/conductor/scripts/profile-bootstrap-detect.py:59, 111, 116`
- Step 4.4 squash merge (bootstrap wire is live): commit `811197f` on `main`
- Step 4.4 P2 #2 hotfix (detector is correct): commit `bf8677d` on `main` (folded into 811197f via squash)
- Gate tests: `~/pantheon/conductor/v2/tests/test_bootstrap_detect.py`

## Time budget

10 min. Pre-flight is the bulk; rm takes < 1s; verification is the
remaining 4 min (pytest is the slow part, ~50s).

## Drop a handoff

1-paragraph handoff to Hermes inbox (mcp_pantheon_messaging_send
to=hermes) when done, same shape as your Step 4.4 briefs (root cause
1-sentence, files changed, verification output, open questions).

If blocked: write blocker to
`~/pantheon/shared/active/conductor-step-4.5-brief-2v2-blockers.md`
and ping Hermes.
