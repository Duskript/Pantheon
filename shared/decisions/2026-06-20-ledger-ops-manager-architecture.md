# Ledger + Ops Manager — Architecture Decisions
**Date:** 2026-06-20
**Session:** Konan + Hephaestus
**Status:** Op-locked

---

## Decision 1: Deployment Architecture

**Docker on main drive, data on external drive.**

- Docker images and container runtime on `/` (6.5GB available)
- All persistent data (Frappe sites, uploads, DB files) on `/mnt/space` (477GB)
- Reason: Docker overlay2 requires ext4/xfs; external drive is currently vfat
- **Action needed:** Reformat `/dev/sdb1` to ext4, or use native install instead of Docker

## Decision 2: Frappe/ERPNext Module Selection

**Keep:** Accounting, CRM, HR, Projects, Calendar (core)
**Cut:** Manufacturing, Inventory, Buying, Support, Website/Blog, Quality Management, Asset Management, Education, Healthcare, Agriculture

- Reason: Ledger is a practice management platform. The demo page (theoforgesolutions.com/demos/ledger.html) shows 11 capabilities covering billing, client hub, staff utilization, task management, calendar, time tracking, documents, credentials, integrations
- Estimated RAM savings: ~200-300MB (from 1.5GB to ~1.2GB)
- Implementation: Install full ERPNext, disable unused modules via Frappe config

## Decision 3: Ops Manager = Custom Hermes Profile

**Not a separate system. A customized Hermes Agent profile with domain-specific skills.**

- Same engine (Hermes Agent), same backends (Ichor, Athenaeum)
- Different SOUL (ops manager persona)
- Different skill set (Ledger API skills instead of build/engineering skills)
- The Ops Manager calls the Frappe REST API — it IS the conversational UI for Ledger

## Decision 4: Skill Domain Cuts

### Active (loaded on boot)
- Pantheon core (ichor, athenaeum, god comms)
- Research (web search, domain lookups)
- Email + Calendar (client communication, scheduling)
- Note-taking + Docs (obsidian, notion, sheets)
- Social media (X, LinkedIn — firm presence)
- Media (content, spotify)
- Browser (web research)

### Dormant (installed, toggled off)
- Creative (ASCII art, design, music — enable if firm wants ad creative)
- Marketing (kairos, campaigns, ads — enable for growth campaigns)
- Kanban orchestration (Conductor UI backend — enable if using workflow builder)

### Cut (not installed)
- Devops (Docker, deploy, system health)
- Gaming (Minecraft, Pokemon)
- ML ops (training, serving, evaluation)
- Autonomous agents (claude-code, codex, opencode)
- PM skills (PRDs, roadmaps, OKRs, sprint planning)
- Red-teaming (jailbreaking)
- Smart home (OpenHue)
- GitHub (repo management, PRs)
- Data science (Jupyter, database ops)
- Code generation (React, Python, TDD, frontend)
- Diagramming
- Prototyping
- Triage/Debugging tools
- GIFs/YouTube/Spotify control

## Decision 5: Creative + Marketing Toggle Pattern

Skills that COULD be useful but aren't default-loaded:
1. Install to skill directory
2. Set `enabled: false` in profile config
3. Ops Manager can activate via `/skill-load creative` when firm owner asks for ad creative
4. Auto-unloads after session or stays active per operator preference

## Decision 6: Ledger Apps Are Pure Frappe

Zero imports from `erpnext` across all three custom apps (ledger_brand, ledger_admin, ledger_intake). They only use `frappe` framework APIs with lazy imports. This means they work on any Frappe install regardless of which ERPNext modules are active.

## Decision 7: Conductor UI Dispatcher Bug

The kanban dispatcher ignores parent-child gating at claim time. Multiple workers spawn in parallel into the same `dir:` workspace, causing file collisions. Workaround: reclaim premature workers, block with `GATED:` comment, let chain run sequentially. Long-term fix needed in dispatcher code.

---

## Open Items (for next session)

1. Reformat `/dev/sdb1` to ext4 (Docker requirement)
2. Build Docker compose for Ledger (slimmed ERPNext + custom apps)
3. Create Ops Manager god profile (SOUL.md + persona.md + skill set)
4. Build Ops Manager skills (Frappe API wrappers, attention surfacing, scheduling)
5. Wire Ops Manager to Ledger instances
6. Complete Conductor UI W1c chain (W1c-c-a running, rest gated)
7. Complete Conductor UI W2 chain (gated on W1c-c)
8. Create Ichor v2 Phase 3 card (provenance enforcement — missed during DB lock)
9. Create Ichor v2 QA chains (14 cards for Phases 1-6)
