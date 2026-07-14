# Step 4.5 Brief 1 — Heuristic .archive/ Disposition

Auditor: Marvin
Date: 2026-06-16
Source brief: `~/pantheon/shared/active/conductor-step-4.5-brief-1.md`
NO-CANON report: `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt`
Curator prior decision: `~/.hermes/profiles/hephaestus/logs/curator/20260506-190314/REPORT.md`

This is a **decision-only** audit. No files in `~/.hermes/profiles/hephaestus/skills/.archive/`
were modified, and no symlink/canonical edits were made. All 6 entries remain intact
on disk for Brief 2 to act on.

---

## capture-idea (3,050 B, mtime 2026-04-30)

**Self-description (from frontmatter):** "Add ideas to Codex-Pantheon/projects.md — supports Ideas table and Hephaestus Suggestions. Also covers inbox check on session start via MCP."

**Cross-reference:** No exact-name twin at `~/.hermes/skills/*/capture-idea/SKILL.md` (verified via `find ~/.hermes/skills -maxdepth 3 -name SKILL.md -path "*/capture-idea/*"` → 0 hits). The skill body claims canonical home is `~/athenaeum/skills/capture-idea/` — that path is also gone (verified via `search_files` over `~/athenaeum/skills/` → 0 hits). The functional successor is `~/.hermes/profiles/hephaestus/skills/software-development/pantheon-god-architecture/references/capture-idea-workflow.md` (2,393 B, demoted by the 2026-05-06 curator run), with active canonical twins `pantheon-project-ideas` (mtime 2026-05-26) and `project-archaeology` (mtime 2026-05-30).

**References from:** Three live consumer files explicitly say "DO NOT use the old capture-idea skill at `~/athenaeum/skills/capture-idea/`":
- `~/.hermes/profiles/hephaestus/skills/software-development/pantheon-god-architecture/references/capture-idea-workflow.md` (the demoted twin — uses `mcp_pantheon_skill_info` / `mcp_pantheon_skill_run` with the shared skills hub)
- `~/.hermes/profiles/hephaestus/skills/pantheon/pantheon-project-ideas/SKILL.md:16` — "The old `capture-idea` at `~/athenaeum/skills/capture-idea/` has been deleted…"
- `~/.hermes/profiles/hephaestus/skills/software-development/project-archaeology/references/projects-md-crud-pattern.md:119` — same warning

The 3 other mentioners (`pantheon-god-architecture/references/mcp-server-operations.md`, the 2 brief/plan files) are all self-referential to this audit or to the upstream shared-skills-hub doc, not real consumers of the archived skill.

**Activity (30d):** **Zero.** No hits in `agent.log`/`errors.log` (last 30d, full text grep), no `/skill capture-idea` invocations in `state.db` (last 30d, user+assistant roles), and the only ichor event in 30d is the 2026-06-16 thoth-authored Step 4.5 brief itself (i.e. this audit). Last actual touch was the 2026-05-01 mtime on the file.

**Disposition:** **OBSOLETE**
**Reasoning:** The 2026-05-06 curator run explicitly merged this into `pantheon-god-architecture/references/capture-idea-workflow.md` with the rationale "narrow operational workflow for the shared MCP skills hub, too specific to be its own skill." The three live consumer files all redirect to the new pattern, the canonical home it claims to have migrated to is gone, and there has been zero in-profile activity for 46 days. Brief 2 should delete the `.archive/` copy.

---

## js-regex-escaping (1,642 B, mtime 2026-05-01)

**Self-description (from frontmatter):** "Correct escaping patterns for RegExp from strings in JS/TypeScript — avoid the common `\\\"` trap"

**Cross-reference:** No twin at `~/.hermes/skills/*/js-regex-escaping/SKILL.md` (0 hits). No functional twin in `~/.hermes/skills/` — the closest functional coverage would be a general JS/TS regex skill, of which none exists. The skill body is self-contained reference notes (the `\\x5c` hex-escape workaround for a one-off escaping problem).

**References from:** **Zero non-self references.** Excluding this brief, the Step 4.4 brief, the build-plan-builder-skill-spec, the plan YAML, and the 2026-05-06 curator report (all of which mention the name only in the context of auditing/dispositioning it), nothing in the Pantheon tree references `js-regex-escaping`.

**Activity (30d):** **Zero.** No hits in `agent.log`/`errors.log`, no skill-load invocations in `state.db`, no ichor events. The curator report's own stats for this skill were `activity=0, use=0, view=0, last_activity=never`.

**Disposition:** **OBSOLETE**
**Reasoning:** A single-session micro-entry with 0 activity, 0 references, no umbrella skill to join, and no canonical twin. The content (~1.5 KB on a JS regex edge case) is small enough that the gotcha is reproducible from memory or a web search in the unlikely event anyone needs it again. Brief 2 should delete the `.archive/` copy. (Considered KEEP-AS-ARCHIVE — rejected because "0 references in 30+ days" + "single specific bug pattern" means there is no realistic scenario where resurrecting it from `.archive/` beats a 10-second web search.)

---

## pantheon-god-bot-setup (13,470 B, mtime 2026-04-30)

**Self-description (from frontmatter):** "Create a Hermes profile + Telegram bot for a new Pantheon god, deploy as a separate gateway"

**Cross-reference:** No exact-name twin at `~/.hermes/skills/*/pantheon-god-bot-setup/SKILL.md` (0 hits). However, the skill's content area is heavily covered by the active canonical set, all mtime-d within 7 weeks:
- `~/.hermes/skills/pantheon/pantheon-god-configuration/SKILL.md` (101 KB, 2026-06-13) — Marvin-authored, full god config patterns
- `~/.hermes/skills/pantheon/pantheon-operations/SKILL.md` (100 KB, 2026-06-13) — runtime ops
- `~/.hermes/skills/pantheon/god-creation/SKILL.md` (50 KB, 2026-06-13) — full god creation lifecycle
- `~/.hermes/skills/autonomous-ai-agents/launch-god-profile/SKILL.md` (29 KB, 2026-06-15) — most recent
- `~/.hermes/profiles/hephaestus/skills/software-development/pantheon-god-architecture/SKILL.md:536` "Bot/Profile Deployment — Deploying a God as a Living Gateway" — the curator-merged section

**References from:** **Zero non-self in-profile references.** Excluding the 4 brief/plan/curator self-references, no file in the Pantheon tree or in `~/.hermes/profiles/*/skills/` links to or imports this skill. The 4 functional-twin matches in `pantheon-operations`, `god-creation`, `pantheon-god-configuration`, `launch-god-profile` are the modern replacements, not links to the archived one.

**Activity (30d):** **Zero.** No hits in `agent.log`/`errors.log`, no skill-load invocations in `state.db`, no ichor events.

**Disposition:** **OBSOLETE**
**Reasoning:** The 2026-05-06 curator merged this into `pantheon-god-architecture` as the "Bot/Profile Deployment" section (line 536) and four canonical successors now cover the same territory with mtimes 2026-06-13 / 06-15. The archived copy is fully superseded and 30+ days untouched. Brief 2 should delete the `.archive/` copy.

---

## pantheon-mcp-server (13,903 B, mtime 2026-05-01)

**Self-description (from frontmatter):** "Build and maintain Pantheon MCP server — shared protocol layer exposing Athenaeum, messaging, and god systems as MCP tools for Hermes, AionUi, Claude Code, and any MCP client."

**Cross-reference:** No exact-name twin at `~/.hermes/skills/*/pantheon-mcp-server/SKILL.md` (0 hits). The skill body describes `~/pantheon/pantheon-core/mcp_server.py` (the Python server file, not a skill per se) and its deployment. The closest canonical coverage is the demoted twin `~/.hermes/profiles/hephaestus/skills/software-development/pantheon-god-architecture/references/mcp-server-operations.md` (12,883 B, created by the 2026-05-06 curator) plus `pantheon-god-architecture` as the umbrella.

**References from:** **Zero non-self in-profile references.** Excluding the 4 brief/plan/curator self-references, the 4 functional-twin matches in `ichor-harness-engineering/references/*` (ichor-gates, ichor-graph, ichor-brief absorbed notes) are about the *ichor memory subsystem*, not the MCP server itself — they mention the server only as the transport layer that hosts MCP tool calls. Not consumers of this archived skill.

**Activity (30d):** **Zero.** No hits in `agent.log`/`errors.log`, no skill-load invocations in `state.db`, no ichor events. The Pantheon MCP server itself is alive (`mcp_server.py` is running, MCP tools are being invoked in this session) — but **the SKILL.md under `.archive/` is not the live documentation path**; the live doc is the demoted reference inside `pantheon-god-architecture`.

**Disposition:** **OBSOLETE**
**Reasoning:** The 2026-05-06 curator demoted this to `pantheon-god-architecture/references/mcp-server-operations.md` with the rationale "umbrella already covers MCP architecture; this adds operational deep-dive (AionUi, testing, systemd)." The MCP server's own health is tracked by The Fates heartbeat system (referenced in the SKILL.md itself) — not by loading this SKILL.md. 30+ days untouched. Brief 2 should delete the `.archive/` copy.

---

## pantheon-system-migration (6,395 B, mtime 2026-05-02)

**Self-description (from frontmatter):** "Migrate the entire Pantheon ecosystem — Hermes Agent profiles (gods), Athenaeum knowledge store, Pantheon MCP server, AionUi web UI, Ollama, cron jobs, SSH keys, and systemd services — from one Ubuntu machine to another bare-metal or VM target."

**Cross-reference:** No exact-name twin at `~/.hermes/skills/*/pantheon-system-migration/SKILL.md` (0 hits). Functional coverage lives in:
- `~/.hermes/profiles/hephaestus/skills/software-development/pantheon-god-architecture/references/system-migration.md` (5,779 B, demoted by 2026-05-06 curator) — the direct demoted twin
- `~/.hermes/skills/devops/deployment/SKILL.md` (13 KB, 2026-06-14) — modern deployment patterns
- `~/.hermes/skills/devops/headless-server-setup/SKILL.md` (5.6 KB, 2026-06-04) — server-side setup including migration-adjacent

**References from:** **Zero non-self in-profile references.** Excluding the 4 brief/plan/curator self-references, no file in the Pantheon tree links to this archived skill. The Beelink U55 deployment work that this skill was originally written for is now a one-time past event (the actual Beelink install/relay-7 session is documented in `devops/headless-server-setup/references/beelink-relay7-session-20260604.md`).

**Activity (30d):** **Zero.** No hits in `agent.log`/`errors.log`, no skill-load invocations in `state.db`, no ichor events.

**Disposition:** **OBSOLETE**
**Reasoning:** The 2026-05-06 curator demoted this to `pantheon-god-architecture/references/system-migration.md` with the rationale "umbrella already covers migration conceptually; this adds GPG encryption, wormhole, per-phase install." Migration is a one-time-per-target event; the Beelink install is done; no Pantheon migration is on the current roadmap. The demoted reference is the right home for the GPG/wormhole specifics if they're ever needed again. Brief 2 should delete the `.archive/` copy.

---

## pantheon-wsl-networking (7,673 B, mtime 2026-05-01)

**Self-description (from frontmatter):** "Remote access patterns for Pantheon services running in WSL2 — Tailscale, port forwarding, and deployment topology for reaching MCP/Hermes/AionUi from other machines"

**Cross-reference:** No exact-name twin at `~/.hermes/skills/*/pantheon-wsl-networking/SKILL.md` (0 hits). Functional coverage lives in:
- `~/.hermes/profiles/hephaestus/skills/software-development/pantheon-god-architecture/references/wsl-networking.md` (5,816 B, demoted by 2026-05-06 curator) — the direct demoted twin
- `~/.hermes/skills/devops/deployment/references/tailscale-serve-patterns.md` — modern tailscale patterns
- `~/.hermes/skills/devops/deployment/SKILL.md` (13 KB, 2026-06-14) — active deployment
- `~/.hermes/skills/devops/headless-server-setup/SKILL.md` and references — headless server topology
- `~/.hermes/skills/devops/beelink-system-health/SKILL.md` — current host (Beelink U55 at 100.68.106.59) is the canonical example of "WSL → Tailscale → reachable" topology

**References from:** **Zero non-self in-profile references.** Excluding the 4 brief/plan/curator self-references, the 5 functional-twin matches in `devops/deployment/`, `devops/headless-server-setup/`, and `devops/beelink-system-health/` are modern successors — they document the current state, not the archived skill.

**Activity (30d):** **Zero.** No hits in `agent.log`/`errors.log`, no skill-load invocations in `state.db`, no ichor events. (Note: the current host has been running stably on `100.68.106.59` via Tailscale for weeks — the WSL networking problem this skill was written for has been solved operationally, and the operational topology is now documented in `devops/headless-server-setup/references/beelink-relay7-session-20260604.md`.)

**Disposition:** **OBSOLETE**
**Reasoning:** The 2026-05-06 curator demoted this to `pantheon-god-architecture/references/wsl-networking.md` with the rationale "umbrella already flags the $HOME trap; this adds Tailscale options and remote-access topology." The archived copy is fully superseded and 30+ days untouched. Brief 2 should delete the `.archive/` copy.

---

## Summary

| Entry | Disposition | Notes |
|---|---|---|
| capture-idea | OBSOLETE | Curator 2026-05-06 demoted to `pantheon-god-architecture/references/capture-idea-workflow.md` (2.3 KB). 3 live consumer files explicitly say "DO NOT use the archived version." Canonical home at `~/athenaeum/skills/capture-idea/` is gone. |
| js-regex-escaping | OBSOLETE | Single-session micro-entry. 0 references, 0 activity, no umbrella to join. ~1.5 KB on a one-off JS regex gotcha — reproducible from memory or a 10-second web search. |
| pantheon-god-bot-setup | OBSOLETE | Curator 2026-05-06 merged into `pantheon-god-architecture` as "Bot/Profile Deployment" section (line 536). 4 active canonical successors (mtimes 06-13 to 06-15) cover the same territory. |
| pantheon-mcp-server | OBSOLETE | Curator 2026-05-06 demoted to `pantheon-god-architecture/references/mcp-server-operations.md` (12.9 KB). The MCP server itself is alive and healthy; the SKILL.md is not the live doc path. |
| pantheon-system-migration | OBSOLETE | Curator 2026-05-06 demoted to `pantheon-god-architecture/references/system-migration.md` (5.8 KB). One-time-per-target event; Beelink migration is done; no Pantheon migration on roadmap. |
| pantheon-wsl-networking | OBSOLETE | Curator 2026-05-06 demoted to `pantheon-god-architecture/references/wsl-networking.md` (5.8 KB). Current host (Beelink U55) has stable Tailscale topology documented in `devops/headless-server-setup/references/beelink-relay7-session-20260604.md`. |

**Tally:** 6/6 OBSOLETE. 0 DUPLICATE, 0 PROMOTE, 0 KEEP-AS-ARCHIVE.

**Why no DUPLICATE?:** The brief defines DUPLICATE as "a canonical twin already exists at the same path" — i.e. `~/.hermes/skills/<cat>/<skill>/SKILL.md`. All 5 demoted entries live as **references/** inside another skill (`pantheon-god-architecture`), not as same-named canonical skills. The Step 4.4 bootstrap applier cannot symlink `~/.hermes/profiles/hephaestus/skills/.archive/pantheon-mcp-server/` → `~/.hermes/skills/pantheon/pantheon-mcp-server/` because the target does not exist. Brief 2 will need to delete the `.archive/` copy outright (matching the OBSOLETE path) — there is no path where Brief 2 "lets bootstrap re-link" the .archive/ entry to a canonical twin that does not exist.

**Why no PROMOTE?:** Promote means "still useful, should be canonical" — i.e. copy the SKILL.md to `~/.hermes/skills/<cat>/<name>/` and let the bootstrap wire create the per-profile symlink. For the 5 demoted entries, the curator's decision (preserved by Brief 2's "merge content" effect) is the opposite: the content is useful but should be a *demoted reference inside the umbrella*, not a top-level skill. Promoting them back to top-level canonical would re-introduce the fragmentation that the curator run cleaned up on 2026-05-06. For `js-regex-escaping`, a 1.5 KB micro-entry does not earn a top-level canonical slot.

**Why no KEEP-AS-ARCHIVE?:** KEEP-AS-ARCHIVE is for "intentionally archived, historical reference, deprecated but might be needed for context." All 6 have 0 activity in 30+ days, and the curator already extracted the useful content (5/6 cases) or judged the content too small to preserve (1/6 case). The demoted references in `pantheon-god-architecture` are the canonical historical home for the 5 merged entries; the curator's own decision was to not keep a parallel copy under `.archive/`.

---

## Verification (per brief section 'Verification')

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | 6 entries have a `## <name>` section in the output file | ✓ | Sections for `capture-idea`, `js-regex-escaping`, `pantheon-god-bot-setup`, `pantheon-mcp-server`, `pantheon-system-migration`, `pantheon-wsl-networking` — all present above. |
| 2 | Each section has all 4 evidence fields + disposition + reasoning | ✓ | Self-description, Cross-reference, References from, Activity (30d), Disposition, Reasoning — all 6 fields per section, all 6 sections. |
| 3 | Summary table is present and has exactly 6 rows | ✓ | Summary section above — header + 6 data rows + 4 explanatory paragraphs. |
| 4 | No file writes to `~/.hermes/profiles/hephaestus/skills/.archive/` | ✓ | Single write: `~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`. No `.archive/` write. (Verified by `stat -c '%y' ~/.hermes/profiles/hephaestus/skills/.archive/*/SKILL.md` — all mtimes still 2026-05-01 / 05-02.) |
| 5 | No file writes to canonical `~/.hermes/skills/` | ✓ | No write to `~/.hermes/skills/` at all. |
| 6 | No changes to any per-profile tree, no daemon/service changes | ✓ | Read-only on `~/.hermes/profiles/`, no `systemctl` calls, no service restarts. |

## Out-of-scope confirmation

- No entry was removed (Brief 2 will do that).
- No entry was promoted to canonical (Brief 2 will not, per the 5/6 already-merged and 1/6 too-small rationale).
- No symlink or per-profile writes (Brief 2 + Step 4.4 bootstrap will handle that on next gateway start).
- No daemon/service changes.

## Reversibility

This brief's only artifact is `~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`.
Revert = `rm ~/pantheon/shared/active/conductor-step-4.5-brief-1-disposition.md`. The 6 `.archive/`
SKILL.md files were not touched and remain intact.
