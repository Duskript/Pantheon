# Conductor v2 — Step 4.5 Brief 1 of 3

## Scope (this brief)

Audit the 6 hephaestus `.archive/` entries and produce a disposition
decision per entry. The decisions are the input Brief 2 needs to
either remove (if obsolete) or promote (if still useful).

This is **decision-only** — no file writes beyond a single output
artifact. Brief 2 will act on the decisions. Brief 3 will verify.

## The 6 entries (verified on disk 2026-06-16)

```
$ find ~/.hermes/profiles/hephaestus -name SKILL.md -path '*.archive/*' | sort
/home/konan/.hermes/profiles/hephaestus/skills/.archive/capture-idea/SKILL.md
/home/konan/.hermes/profiles/hephaestus/skills/.archive/js-regex-escaping/SKILL.md
/home/konan/.hermes/profiles/hephaestus/skills/.archive/pantheon-god-bot-setup/SKILL.md
/home/konan/.hermes/profiles/hephaestus/skills/.archive/pantheon-mcp-server/SKILL.md
/home/konan/.hermes/profiles/hephaestus/skills/.archive/pantheon-system-migration/SKILL.md
/home/konan/.hermes/profiles/hephaestus/skills/.archive/pantheon-wsl-networking/SKILL.md
```

Size + mtime snapshot (from `stat -c '%Y %s %n'`):

| Entry | Size | Mtime | Age |
|---|---|---|---|
| `capture-idea` | 3,050 B | 2026-04-30 | ~47 d |
| `pantheon-god-bot-setup` | 13,470 B | 2026-04-30 | ~47 d |
| `pantheon-wsl-networking` | 7,673 B | 2026-05-01 | ~46 d |
| `pantheon-mcp-server` | 13,903 B | 2026-05-01 | ~46 d |
| `js-regex-escaping` | 1,642 B | 2026-05-01 | ~46 d |
| `pantheon-system-migration` | 6,395 B | 2026-05-02 | ~45 d |

All six are **per-profile-only** (not in canonical `~/.hermes/skills/`,
not in the NO-CANON report — they live under `.archive/` which is
excluded from discovery by the Step 4.4 detector by design).

## Disposition taxonomy (apply to each of the 6)

For each entry, pick exactly one of:

- **OBSOLETE** — skill is dead. No canonical twin, no references from
  other skills, no test coverage, no user mention in the last 30 days.
  Brief 2 will delete `~/.hermes/profiles/hephaestus/skills/.archive/<name>/`.

- **DUPLICATE** — a canonical twin already exists. Brief 2 will delete
  the per-profile `.archive/` copy and let the Step 4.4 bootstrap
  re-link the per-profile path to canonical (no human action needed;
  bootstrap will re-create the symlink on next gateway start).

- **PROMOTE** — still useful, should be canonical. Brief 2 will copy
  the SKILL.md to `~/.hermes/skills/<cat>/<name>/SKILL.md`, remove
  the per-profile `.archive/` copy, and let the Step 4.4 bootstrap
  create the per-profile symlink to canonical on next gateway start.

- **KEEP-AS-ARCHIVE** — intentionally archived (historical reference,
  deprecated but might be needed for context). Brief 2 takes no
  action; Brief 3 leaves the entry alone.

## Evidence to gather (per entry)

For each of the 6, gather the following 4 pieces of evidence:

1. **SKILL.md self-description** — read the file, quote the
   `description:` field (frontmatter) or the first paragraph. The
   intent of the skill as the original author wrote it.

2. **Cross-reference scan** — does canonical `~/.hermes/skills/`
   have a twin under a different name? Use:
   `grep -ril "<name-or-keyword>" ~/.hermes/skills/` (limit to
   the most likely twin — don't blanket-grep).

3. **Reference scan** — does anything else in Pantheon **import,
   link, or mention** this skill by name? Use:
   `grep -rl "<name>" ~/pantheon ~/.hermes/profiles --include="*.py"
   --include="*.md" --include="*.yaml" --include="*.yml" 2>/dev/null`
   (exclude `.archive/` itself).

4. **Activity scan** — has this skill been loaded or referenced
   in any session or cron output in the last 30 days? Check:
   `~/.hermes/logs/agent.log`, `~/.hermes/logs/errors.log`, and
   the ichor session database if available. (A 0-result here is
   informative — it suggests OBSOLETE.)

## Deliverable format (this brief's output)

A single markdown file:
`~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`

Structure:

```markdown
# Step 4.5 Brief 1 — Heuristic .archive/ Disposition

## capture-idea (3,050 B, mtime 2026-04-30)
**Self-description:** <quoted from SKILL.md>
**Cross-reference:** <canonical twin path or "none found">
**References from:** <list of paths that mention this skill, or "none">
**Activity (30d):** <0/1/few references, with sources>
**Disposition:** <OBSOLETE|DUPLICATE|PROMOTE|KEEP-AS-ARCHIVE>
**Reasoning:** <1-2 sentences>

## js-regex-escaping (1,642 B, mtime 2026-05-01)
... (same structure)

## pantheon-god-bot-setup (13,470 B, mtime 2026-04-30)
... (same structure)

## pantheon-mcp-server (13,903 B, mtime 2026-05-01)
... (same structure)

## pantheon-system-migration (6,395 B, mtime 2026-05-02)
... (same structure)

## pantheon-wsl-networking (7,673 B, mtime 2026-05-01)
... (same structure)

## Summary
| Entry | Disposition | Notes |
|---|---|---|
| capture-idea | OBSOLETE | ... |
| ... | ... | ... |
```

## Verification (this brief)

- 6 entries have a `## <name>` section in the output file
- Each section has all 4 evidence fields + disposition + reasoning
- Summary table is present and has exactly 6 rows
- No file writes to `~/.hermes/profiles/hephaestus/skills/.archive/`
- No file writes to canonical `~/.hermes/skills/`
- No changes to any per-profile tree
- No daemon/service changes

## Out of scope (this brief)

- Removing any entry (Brief 2)
- Promoting any entry to canonical (Brief 2)
- Any symlink or per-profile writes (Brief 2 + Step 4.4 bootstrap
  will handle that on next gateway start)

## Reversibility

This brief is decision-only. The output file is one new markdown
file. Revert = `rm shared/active/conductor-step-4.5-brief-1-disposition.md`.

The 6 `.archive/` SKILL.md are NOT touched and remain intact.

## Reference pinning (no need to re-discover)

- Plan YAML line 71-88: `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml`
- Step 4.4 detector (.archive/ exclusion logic): `~/pantheon/conductor/scripts/profile-bootstrap-detect.py:59, 111, 116`
- Step 4.3 NO-CANON report (proves these 6 are NOT in the canonical
  scope): `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt`
  (hephaestus is listed; check that these 6 names are absent).
- Step 4.4 squash merge (proves the bootstrap wire is in place on
  the live filesystem): commit `811197f` on `main` —
  `git show 811197f --stat | grep bootstrap`
- Brief 3 systemd drop-in: `~/.config/systemd/user/hermes-gateway@.service.d/10-skill-bootstrap.conf`

## Time budget

30 min. This is a read-and-classify exercise, no scripts, no writes
beyond the output file.

## Drop a handoff

1-paragraph handoff to Hermes inbox (mcp_pantheon_messaging_send
to=hermes) when done. Shape: per-entry disposition + total count of
OBSOLETE/DUPLICATE/PROMOTE/KEEP-AS-ARCHIVE + reversibility note +
open questions (if any).

If blocked: write blocker to
`~/pantheon/shared/active/conductor-step-4.5-brief-1-blockers.md`
and ping Hermes.
