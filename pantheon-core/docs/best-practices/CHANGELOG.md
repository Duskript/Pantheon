---
title: "Changelog"
last_verified: 2026-09-01
---

# Changelog

All notable changes to the Pantheon Best Practices docs are recorded here. Append-only. Newest first.

## 2026-09-01

- **Re-verification pass.** Re-read the flagged pages against the current Pantheon and Hermes source tree.
  - `00-quickstart.md` — corrected the MCP endpoint, service logging, manual-run command, roster path, and distinction between Ichor events and Markdown decisions.
  - `02-skills.md` — documented current profile/external skill discovery and explicit body loading via `skill_view`, slash commands, or `--skills`; removed the claim that phrase matching automatically loads a skill.
  - `05-using-a-skill.md` — clarified frontmatter behavior, platform/environment filters, plugin skill loading, and the 500-line guideline.
  - `08-decision-log.md` — replaced the obsolete per-user/global-sequence shape with the current `shared/decisions/` + `INDEX.md` convention and documented Ichor's separate FTS5 event path.
  - `09-mcp-tools.md` — refreshed the inventory to the 35 tools currently registered by `pantheon-core/mcp_server.py`, including goals, gates, L2 extraction, graph, workflow, and Pantheon index tools.
  - `README.md` — refreshed maintenance language and live-source references.

## 2026-06-19

- **Initial publication.** The numbered best-practices pages, README, and this changelog were authored from operator-locked decisions and god-notify history.
  - `00-quickstart.md` — five essential operator actions
  - `02-skills.md` — Skill invocation
  - `05-using-a-skill.md` — Frontmatter best practices
  - `08-decision-log.md` — Decision discipline
  - `09-mcp-tools.md` — MCP tool surface
  - `README.md` — refreshed table of contents and removed links to pages absent from the current checkout
  - `CHANGELOG.md` — This file
