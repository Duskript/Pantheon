---
title: "Changelog"
last_verified: 2026-11-01
---

# Changelog

All notable changes to the Pantheon Best Practices docs are recorded here. Append-only. Newest first.

## 2026-11-01

- **Monthly re-verification pass** (triggered by `docs-staleness-check.py`; all seven pages were last verified 2026-09-01, i.e. 61 days old). Every page was re-read against the live installation and the current Hermes source tree.
  - `00-quickstart.md` — no factual change needed. Confirmed `pantheon-mcp.service` exists and is enabled as a user unit, `mcp_server.py` defaults to port 8010, and a live `GET http://127.0.0.1:8010/mcp` returns HTTP 200 with the streamable-http transport hint. Confirmed `~/pantheon/gods/gods.yaml`, `~/pantheon/gods/messages/`, and `~/pantheon/shared/decisions/INDEX.md` all exist.
  - `02-skills.md` — clarified the offer-time filters by name: `platforms:` (host OS), `environments:` (runtime relevance — `skill_matches_environment` documents itself as an offer-time filter that explicit loads bypass), and `requires_apps:` (host must satisfy each declared app; unknown names fail closed). Discovery order (`skills.external_dirs` after the local profile skills dir) and slash-command normalization (` ` and `_` → `-`, `agent/skill_commands.py`) both re-confirmed.
  - `05-using-a-skill.md` — documented `requires_apps:` and the `metadata.hermes` condition keys the loader actually reads (`requires_tools`, `requires_toolsets`, `fallback_for_tools`, `fallback_for_toolsets`, `session_platforms`) plus `metadata.hermes.config`. Confirmed the name-format rule in `tools/skill_linter.py` and that the 500-line figure remains a house guideline with no runtime enforcement in the Hermes tree.
  - `08-decision-log.md` — no factual change needed. Confirmed `shared/decisions/` + `INDEX.md` are the current convention and that `ichor_store` routes through the memory backend rather than writing decision Markdown.
  - `09-mcp-tools.md` — re-counted `pantheon-core/mcp_server.py`: **35** `@mcp.tool` registrations, and the per-category split (19 / 2 / 2 / 3 / 2 / 1 / 6) still sums to 35. Every tool named on the page is still present in the source.
  - `README.md` — no change beyond the verification date; page inventory and maintenance language still accurate.
  - `CHANGELOG.md` — this entry.

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
