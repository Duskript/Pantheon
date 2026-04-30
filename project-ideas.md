# Project Ideas

A living collection of things to build — for Konan's Pantheon system, for work, and whatever else comes to mind.

---

## 🏗️ Pantheon — Core Architecture

### Pantheon Bridge — Inter-God Communication Layer
- **Status:** planning
- **Tags:** #pantheon-core #architecture #communication #mcp
- **Added:** 2026-04-29
- **Notes:** ⚡ The messaging layer that lets gods talk to each other. Starts as a shared filesystem directory (`~/pantheon/gods/messages/`) where gods write JSON messages to each other's inboxes. Designed to evolve 1:1 into an MCP-based message bus later. Gods register in `gods.yaml` with their capabilities. This is what lets Hermes deliver a Hades report to Konan, or let Hephaestus ask Thoth for research context.
  - Phase 1: File-based inbox/outbox per god
  - Phase 2: MCP tools for `pantheon_send_message`, `pantheon_check_inbox`, etc.
  - Phase 3: Full event bus with routing, filtering, persistence

### Pantheon Plugin / God SDK
- **Status:** planning
- **Tags:** #pantheon-core #architecture #sdk #plugin-system #packaging
- **Added:** 2026-04-29
- **Notes:** ⚡ **Foundational architecture.** A standard way to package gods as pluggable extensions to Pantheon. Each god is a self-contained bundle: agent config, personality prompts, knowledge base, tools, skills, and supporting files.

  **Key design decisions:**
  - **Hephaestus** is the one core god bundled with Pantheon by default — the foundation god
  - All other gods are external: created by Konan or obtained from trusted sources
  - **Public god repository** — when Pantheon goes public, a registry/directory of gods Konan has made and wants to share
  - **Apollo is proprietary** — a closed, select-access god engine, NOT shared publicly. Exclusive to trusted/selected people
  - Each god has a manifest (`god.yaml`) with metadata, triggers, dependencies
  - Install flow: `pantheon install god-name`
  - Versioning, dependency management between gods
  - Gods can share tools/knowledge with each other

### Full Rebrand: Hermes → Pantheon
- **Status:** idea
- **Tags:** #pantheon-core #branding #infrastructure #public-launch
- **Added:** 2026-04-29
- **Notes:** ⚡ **Strategic goal for public launch.** Fork/rebrand the entire Hermes Agent system to become Pantheon. This is a lift — the binary, CLI commands, config paths (~/.hermes/), skill system, gateway — everything branded as Pantheon. Hermes stays as a god within Pantheon (the agent you chat with). Key considerations:
  - Fork the Hermes codebase and replace all branding
  - New CLI: `pantheon chat`, `pantheon gateway`, `pantheon install god-hephaestus`
  - Config moves to `~/.pantheon/`
  - Gods become the core organizing concept
  - Only worth doing once the God SDK and plugin system are solid
  - This is what goes public — Hermes Agent is the foundation, Pantheon is the product

### Pantheon UI — Hera's Domain
- **Status:** idea
- **Tags:** #pantheon-core #ui #design #hera
- **Added:** 2026-04-29
- **Notes:** The settings panels and UI of Pantheon fall under **Hera** — queen of the gods, keeper of order, manager of the divine household. All configuration, preferences, user management, and system settings live in her domain.

### The Underworld — Data Lifecycle System
- **Status:** planning
- **Tags:** #pantheon-core #data #lifecycle #hades #fates
- **Added:** 2026-04-29
- **Notes:** ⚡ A structured data lifecycle system with Greek underworld hierarchy:
  - **Meadows of Asphodel** — Short-term archival. Data sits here for 6 months before moving on.
  - **Fields of Elysium** — Permanent long-term archive. Data that earned its place.
  - **Tartarus** — Final countdown. Data has 30 days here before permanent deletion.
  - **Hades** — Gatekeeper and ruler of the underworld. Processes data through the lifecycle. CAN recover anything from any layer, even Tartarus, if needed.
  - **The Fates** — Only they have the ultimate authority to permanently delete data. Data goes through Hades first, the Fates cut the thread.
  - Total lifecycle from Asphodel to deletion: ~7 months (6mo Asphodel + 30d Tartarus), with Elysium as the permanent escape hatch.

### Claude.ai Conversation Ingestion System
- **Status:** idea
- **Tags:** #system #data #claude #pantheon-core
- **Added:** 2026-04-29
- **Notes:** Build a system to ingest all past conversations from claude.ai into a local database. Needs to handle exporting from claude.ai (JSON/HTML exports), parsing conversation history, and storing them in a queryable format — possibly feeding into Hermes memory or a local vector store for search/reference. Could be a core Pantheon data pipeline.

### Ollama Context Window Monitor
- **Status:** idea
- **Tags:** #tool #monitoring #ollama #mlops
- **Added:** 2026-04-29
- **Notes:** Create a tool or dashboard to monitor Ollama's context window usage across all running sessions. Track when the context window is approaching its limit and about to "roll over" (truncate/forget). Should provide real-time visibility into each active model's context utilization, token counts, and alert when approaching the limit. Could be a TUI dashboard or a lightweight CLI command.

## 🏛️ God Roster (Planned)

### Hestia — Interactive Cookbook & Kitchen Assistant
- **Status:** idea
- **Tags:** #god #lifestyle #cooking #assistant
- **Added:** 2026-04-29
- **Mythology:** Greek — Goddess of the hearth, home, and family meals
- **Personality:** Warm, nurturing, patient — like a grandmother who's been cooking for 60 years
- **Notes:** An interactive cookbook god. You tell her "I want to make mom's chocolate chip cookies" and she not only knows the recipe but walks you through step-by-step. KEY FEATURE: skill-level adaptive guidance. If you're a novice, she assumes NOTHING — explains every technique, every tool, every doneness cue. If you're experienced, she keeps it breezy. Should support:
  - Recipe recall by name, ingredient, or vibe
  - Step-by-step voice/timed walkthrough mode
  - Dietary substitutions on the fly
  - Personal recipe import ("here's my grandma's casserole, digitize this")
  - Meal planning and leftovers management

### Caduceus — Medical Research & Medication Assistant
- **Status:** idea
- **Tags:** #god #health #medical #assistant
- **Added:** 2026-04-29
- **Mythology:** Greek — The staff carried by Hermes, also associated with Asclepius (god of medicine). Caduceus is a fitting medical symbol.
- **Personality:** Calm, precise, thorough — the kind of god you want helping you make health decisions
- **Notes:** A medical research and medication management god. Helps with:
  - Medication research — interactions, side effects, timing
  - Dosing schedules and reminders ("take your blood pressure med at 8am")
  - Symptom logging — track what you're feeling, when, severity
  - Identify patterns in symptoms over time
  - Drug interaction checking across your full medication list
  - Note: MUST have strong disclaimers — assistant, not doctor. Source citations required.

### Thoth — Knowledge Management & Research Synthesis
- **Status:** idea
- **Tags:** #god #knowledge #research #egyptian
- **Added:** 2026-04-29
- **Mythology:** Egyptian — God of writing, wisdom, and magic. The divine scribe.
- **Personality:** Scholarly, meticulous, quietly brilliant — the kind of god who's read everything and remembers it all.
- **Notes:** Knowledge management god. Every book, note, PDF, or conversation you've ever saved — Thoth organizes it, cross-references it, surfaces connections. The perfect companion for the Claude ingestion system. Can synthesize research across multiple sources, maintain a personal wiki, and answer "haven't we talked about this before?" with actual receipts.

### Heimdall — Infrastructure Monitoring & Watchman
- **Status:** idea
- **Tags:** #god #infrastructure #monitoring #norse
- **Added:** 2026-04-29
- **Mythology:** Norse — The watchman of the gods, guardian of the Bifrost. Sees and hears everything.
- **Personality:** Vigilant, calm under pressure, speaks in clear alarms — the security guard who's never surprised.
- **Notes:** Infrastructure monitoring dashboard. Server uptime, resource usage, log watching, anomaly detection, alert routing. Heimdall stands at the gates and watches everything — when something's wrong, he blows the Gjallarhorn. Could feed into a visual dashboard showing the health of all Pantheon services.

### Skadi — Fitness, Wellness & Outdoor Coach
- **Status:** idea
- **Tags:** #god #fitness #wellness #health #norse
- **Added:** 2026-04-29
- **Mythology:** Norse — Goddess of winter, skiing, hunting, and mountains. An independent, capable figure.
- **Personality:** Direct, motivating, tough-but-fair — the personal trainer who knows when to push and when to ease off.
- **Notes:** Fitness and wellness tracking god. Workout logging, outdoor activity planning, nutrition notes, sleep tracking. Adapts to your fitness level — can design a plan for the couch potato or the marathon runner. The god who yells at you to go touch grass, but in a LOVING way.

### Inari — Intelligent Bookkeeping & Finance
- **Status:** idea
- **Tags:** #god #finance #bookkeeping #shinto
- **Added:** 2026-04-29
- **Mythology:** Shinto — God of rice, sake, prosperity, and harvest. Associated with foxes (kitsune).
- **Personality:** Wise, thoughtful, slightly mysterious — the accountant who always knows where every penny went.
- **Notes:** Intelligent finance and bookkeeping god. Expense tracking, budget planning, "where did all my money go this month?" analysis. Can connect to bank feeds (or manual entry), categorize spending, identify trends, suggest budgets. Inari knows the bounty of your harvest and where it all went.

### Ganesha — Project Scaffolding & Obstacle Removal
- **Status:** idea
- **Tags:** #god #productivity #debugging #hindu
- **Added:** 2026-04-29
- **Mythology:** Hindu — Remover of obstacles, god of beginnings, wisdom, and intellect.
- **Personality:** Wise, patient, solution-oriented — the mentor who helps you see the path forward.
- **Notes:** When you're stuck — code bug, blocked workflow, can't figure out a config — Ganesha clears the path. Also the god to call when STARTING something new: "Ganesha, scaffold me a new Python project with FastAPI, SQLAlchemy, and tests." Project initialization, boilerplate generation, and creative problem-solving all in one.

### Anubis — Data Archival & Embalming (Hades' Right Hand)
- **Status:** idea
- **Tags:** #god #data #archival #egyptian #underworld
- **Added:** 2026-04-29
- **Mythology:** Egyptian — God of embalming, mummification, and ushering souls to the afterlife.
- **Personality:** Solemn, precise, methodical — the archivist who does his job perfectly and quietly.
- **Notes:** Works alongside Hades in the Underworld data lifecycle. Anubis handles the embalming (compression, packaging, indexing) of data before it moves through the Underworld stages. Prepares data for its journey through Asphodel, Elysium, or Tartarus. The meticulous craftsman of data death and preservation.

## 🏛️ Greek System Gods (Built into Pantheon Core)

These aren't installable gods — they're the architecture OF Pantheon itself, named after Greek entities that rule the divine order:

| Entity | Domain | Role |
|--------|--------|------|
| **Hera** | UI & Settings | Queen of the gods — all settings panels, configuration UI, user management |
| **Hades** | Data Lifecycle Gatekeeper | Ruler of the Underworld — processes data through archival/compression/burial pipeline |
| **The Fates** | Ultimate Deletion Authority | Only they can permanently delete data — Hades processes, the Fates decide |
| **Demeter** | Growth, Seeding, Learning | Training pipelines, model seeding, data cultivation |
| **Athena** | Wisdom, Strategy, System Architecture | High-level system design, strategic decisions, architecture planning |

### Multi-User Pantheon Architecture
- **Status:** idea
- **Tags:** #pantheon-core #architecture #multi-user #infrastructure
- **Added:** 2026-04-29
- **Notes:** ⚡ Needs careful planning — Pantheon is currently single-user. When it goes public, multiple users means:
  - **God isolation** — Each user gets their own gods? Or shared gods with per-user context?
  - **Per-user profiles** — Every user needs their own config, memories, sessions, skills
  - **Multi-tenant Hermes** — Does each user get their own gateway/bot, or one gateway routing by identity?
  - **The Apollo problem** — How does a proprietary god live on a shared system without leaking?
  - **God marketplace** — If User A installs a god, should User B see it too?
  - **Shared vs private knowledge** — Some gods share a knowledge base (Hephaestus docs), others are private
  - **Resource quotas** — Ollama context windows, terminal sessions, disk usage per user
  - **The Pantheon filesystem** — Currently `~/pantheon/` is single-user. Multi-user needs a new home.
  - **God permissions** — Can user A's Hephaestus send messages to user B's Thoth?
  - Worth sketching this out as a dedicated architecture doc early, even if Phase 1 is single-user only.

### The Underworld — Data Flow

```
Data enters Hades' domain
        │
        ▼
  ┌─────────────┐
  │   Anubis    │  ← Embalming (compression, packaging, indexing)
  └──────┬──────┘
         │
         ▼
  ┌──────────────────────────────┐
  │  Meadows of Asphodel         │  6 months — short-term archival
  │  (warm, accessible storage)  │
  └──────┬───────────────────────┘
         │
         ├──────────────────────────────┐
         ▼                              ▼
  ┌──────────────┐            ┌─────────────────┐
  │ Fields of    │            │    Tartarus     │
  │  Elysium     │            │  30-day countdown│
  │ (permanent)  │            │ (final warning)  │
  └──────────────┘            └────────┬────────┘
                                       │
                                       ▼
                               ┌────────────────┐
                               │   The Fates    │
                               │ (final verdict)│
                               │  ✂️  ✂️  ✂️   │
                               └────────────────┘
                                       │
                                       ▼
                                  PERMANENT
                                  DELETION

       👑 Hades can recover from ANY layer, even Tartarus
```

## 💼 Work Projects

### Jira Desktop Notification App
- **Status:** idea
- **Tags:** #work #jira #tool #productivity
- **Added:** 2026-04-29
- **Notes:** A lightweight desktop app that sits in the system tray and provides real-time Jira notifications (assigned tickets, mentions, status changes). Also needs a quick-submit feature — a popup or hotkey to quickly file a ticket with minimal friction (title, description, maybe a couple of fields). Could be built with Tauri (Rust + web frontend) or Electron, polling the Jira REST API.
