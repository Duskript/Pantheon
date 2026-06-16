# Conductor v2 — Step 4.3 Build Brief

**From:** Hermes (PM)
**To:** Marvin
**Cycle:** PM-loop round, post-Step 4.2 QA (SHIP)
**Status:** pending → in-progress on your ack
**Spec:** `~/pantheon/conductor/BUILD-PLAN.md` §Step 4.3 (added 2026-06-15)

---

## TL;DR

Step 4.2 was a one-off fix for a single drifted per-profile SKILL.md. Step 4.3 closes the **whole class of drift** across all 5 god profiles. Thoth's QA found 95 drifted per-profile `SKILL.md` files (no "stale-fork-bigger" cases — every drift is `pp_size < canon_size`) plus 127 per-profile SKILL.md with no canonical twin (profile-only or moved/renamed). Close the 95, surface the 127 as a report, prevent the class from recurring.

## Why this matters

Every god-profile session loads skills from `~/.hermes/profiles/<god>/skills/**/SKILL.md`, NOT from `~/.hermes/skills/...`. When canonical is updated and the per-profile copy isn't refreshed, the profile silently runs a stale version. We hit this exact bug on `thoth-dawn-patrol` §5.5 in Step 4.2 — the synthesis ran, but emitted no Conductor Quarantine Backlog section because the §5.5 spec wasn't in the loaded SKILL.md. Drift is invisible until it bites.

## Decisions (operator-locked 2026-06-15 16:18Z)

1. **references/ scope: rsync --ignore-existing** (B). Don't clobber profile-only files. Closes existing divergence without overwriting intentional per-profile additions.
2. **NO-CANON handling: emit a report** (Y). Append a `no-canon.txt` listing all 127 per-profile SKILL.md without a canonical twin. Operator-visible, but no action required.
3. **SKILL.md mechanism: symlink** (Symlink). `~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md` becomes a symlink to `~/.hermes/skills/<cat>/<skill>/SKILL.md`. Drift becomes impossible by construction.

## Scope (in / out)

**In scope:**

1. **Read the audit data** at `/tmp/step-4.3-drift-list.txt` (95 drifted files) and the corresponding canonical paths. Don't re-derive — Thoth's audit is current.
2. **For each of the 95 drifted SKILL.md paths:**
   - Verify the per-profile file is a regular file (not already a symlink — skip if it is, log "already symlinked").
   - Verify the canonical twin exists at the expected path.
   - Replace the per-profile regular file with a symlink to the canonical twin.
   - Use `ln -sf` so the swap is atomic.
3. **For each of the 95 skills, rsync the references/ subdir with `--ignore-existing`:**
   - If `~/.hermes/profiles/<god>/skills/<cat>/<skill>/references/` exists, merge new files from canonical using `rsync -a --ignore-existing canonical/references/ per-profile/references/`.
   - Do NOT delete per-profile files that have no canonical twin.
   - If canonical has no `references/` and per-profile has one, leave per-profile alone.
4. **Emit a NO-CANON report:**
   - Generate a per-profile SKILL.md inventory.
   - For each per-profile `SKILL.md`, check if a canonical twin exists at the inferred path (`~/.hermes/skills/<cat>/<skill>/SKILL.md`).
   - If no canonical twin: append to `/home/konan/pantheon/shared/active/conductor-step-4.3-no-canon.txt` with columns: `profile | category | skill_name | per_profile_path | mtime | size_bytes`.
   - Format: pipe-separated (operator-readable, no markdown table — operator will read it as a Telegram attachment).
5. **Verify the work:**
   - For each of the 95 paths: `readlink` returns the canonical path, `test -f` succeeds.
   - `diff -q` of a few symlinked SKILL.md vs canonical: no output (byte-identical by symlink).
   - References: `find ~/.hermes/profiles/*/skills/*/*/references/ -type f | wc -l` ≥ pre-fix count (we only add, never remove).
6. **Run the conductor v2 test suite** as a smoke regression: `cd ~/pantheon/conductor/v2/tests && python3 -m pytest -q`. Expect 193/193 still pass.
7. **Update the BUILD-PLAN.md** Step 4.3 line with: status, files-changed-summary, and the symlink+rsync commands used (so future operators can re-run if drift re-emerges).

**Out of scope:**

- Touching any of the 127 NO-CANON files (report only, no action).
- Touching canonical SKILL.md content (we're only moving per-profile).
- Changing the god-profile skill discovery logic in `pantheon-god-configuration` (out of scope; this is a data fix, not a code fix).
- Step 4.4 or later work.
- Any production rule YAMLs.
- Any conductor engine code.

## Deliverable (back to me)

1. **Summary of actions:** counts (95 symlinks created, N references merged, M already symlinked/skipped, 0 errors). 1 paragraph.
2. **Files changed (concrete list):**
   - The 95 symlink replacements (`old_path → canonical_path`).
   - The N rsync-merged references/ subdirs.
   - The BUILD-PLAN.md update.
3. **Verification output:**
   - `readlink` spot-check on 3-5 symlinks.
   - `pytest -q` output (expect 193/193).
   - Pre-fix vs post-fix references/ file count per profile.
4. **NO-CANON report location:** `/home/konan/pantheon/shared/active/conductor-step-4.3-no-canon.txt` with file size + first 5 lines + last 5 lines. (Operator will read it as a Telegram attachment later.)
5. **Open questions** (any).

## Verification (how I'll know it works)

1. **The 95 drift paths are now symlinks.** One-liner: `for p in $(awk '/canon=/ && !/^#/ {print $NF}' /tmp/step-4.3-drift-list.txt | tail -n +5); do test -L "$p" || echo "MISSING SYMLINK: $p"; done` — expect 0 missing.
2. **No per-profile regular SKILL.md remains where a canonical twin exists.** `find ~/.hermes/profiles/*/skills/*/*/SKILL.md -type f -not -name "*.bak"` should equal the count of NO-CANON files plus any pre-existing intentional per-profile forks (0 expected — Thoth's audit found none).
3. **pytest -q → 193/193 pass.** No regressions.
4. **BUILD-PLAN.md Step 4.3 line** has the symlink+rsync commands documented.

## Reference data

**Thoth's audit (locked 2026-06-15 16:14Z):**
- 95 drifted per-profile SKILL.md across 5 profiles (iris 20, hephaestus 20, thoth 19, cachyos 18, apollo 18)
- 22 distinct skill names affected
- Drift pattern uniform: `pp_size < canon_size` in all 95 cases
- Full sorted list: `/tmp/step-4.3-drift-sorted.txt` (95 lines, by drift size desc)
- Unsorted source: `/tmp/step-4.3-drift-list.txt` (the working file to read)

**Key paths to know:**
- Per-profile skills root: `~/.hermes/profiles/<god>/skills/<cat>/<skill>/SKILL.md`
- Canonical skills root: `~/.hermes/skills/<cat>/<skill>/SKILL.md`
- The drift list's `per_profile_path` column has the full per-profile path; canonical path is `<per-profile-path>` with `~/.hermes/profiles/<god>/skills/` rewritten to `~/.hermes/skills/`.

## Constraints (hard rules)

- **No fabrication.** If `readlink` or `diff` fails, report it.
- **No canonical edits.** We're only moving per-profile paths, never touching `~/.hermes/skills/`.
- **No symlinks outside the per-profile skills tree.** Don't symlink anything else (config, scripts, etc.) — out of scope.
- **Atomic swaps.** Use `ln -sf` to replace; no half-states where the per-profile file is gone and the symlink isn't there.
- **Preserve `references/` content.** `rsync --ignore-existing` only. Never delete.
- **Stay in your lane.** This is hermes-profile + main + per-profile skills territory. Don't touch thoth/iris/hephaestus/cachyos/apollo's other config (rules, agents, lsp).

## Deadline / handoff

**Target wall-clock:** 30-45 min for the symlinks + rsync + verification.
**Handoff back to me:** Same format as Step 4.2 (root cause 1-sentence, files changed, verification output, open questions, NO-CANON location).

I'll review, then hand to Thoth for independent QA (fresh session, re-verify symlinks + regression). Then operator reviews the NO-CANON report.

## Open question for you (don't block on it)

**How to prevent this drift class going forward?** The symlink fix makes it impossible to drift on the 95 fixed skills, but a new skill added to canonical won't get a per-profile symlink until a profile session loads it. Options:

1. **Profile-bootstrap hook** — on every per-profile gateway start, run a one-shot diff+symlink script. Catches new canonical skills at session-start.
2. **Cron job** — daily `diff + symlink` for all profiles. Operator-visible, low frequency.
3. **Lazy** — wait for drift to be reported in a daily brief, then fix.

My read: #1 is the right answer but it's a Step 4.4+ thing, not 4.3. **Don't do it now; just note it in the open questions so we have it on the radar.**

— Hermes (PM), 2026-06-15 16:18Z
