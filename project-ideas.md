# Project Ideas

A living collection of things to build — for Konan's Pantheon system, for work, and whatever else comes to mind.

---

## 🏗️ Pantheon — Core Architecture

### Full Rebrand: Hermes → Pantheon
- **Status:** in-progress
- **Tags:** #pantheon-core #branding #infrastructure #public-launch
- **Added:** 2026-04-29
- **Notes:** ⚡ **Strategic goal for public launch.** Fork/rebrand the entire Hermes Agent system to become Pantheon. This is a lift — the binary, CLI commands, config paths (~/.hermes/), skill system, gateway — everything branded as Pantheon. Hermes stays as a god within Pantheon (the agent you chat with). Key considerations:
  - Fork the Hermes codebase and replace all branding
  - New CLI: `pantheon chat`, `pantheon gateway`, `pantheon install god-hephaestus`
  - Config moves to `~/.pantheon/`
  - Gods become the core organizing concept
  - Only worth doing once the God SDK and plugin system are solid
  - This is what goes public — Hermes Agent is the foundation, Pantheon is the product

### Open Swarm — Agent Handoff Investigation
- **Status:** idea
- **Tags:** #pantheon-core #multi-agent #research #communication
- **Added:** 2026-05-06
- **Notes:** Investigate Open Swarm's agent handoff mechanism — how its agents pass control and context to each other. Need to understand:
  - Handoff protocol: what gets passed (context, state, tool access?)
  - How the routing/decision logic works for choosing the next agent
  - How errors/timeouts propagate between agents
  - Whether the handoff model scales to Pantheon's god architecture
  - Could inform Pantheon Bridge Phase 3 (event bus with routing)

### Pantheon OS — Desktop Companion v2
- **Status:** idea
- **Tags:** #pantheon-v2 #os #desktop #ubuntu #space-agent #vision
- **Added:** 2026-05-08
- **Vision:** An AI-native Ubuntu-based OS where Pantheon gods live on the desktop as persistent companions. A fusion of three projects:
  - **Pantheon** — multi-god backend (Athenaeum, orchestration, specialized agent architecture)
  - **Space Agent** (agent0ai/space-agent) — frontend runtime that can dynamically reshape the UI, build tools/widgets/panels on the fly from natural language, using SKILL.md modularity and git-backed history
  - **Ubuntu** — the familiar desktop foundation
- **Key concept:** A persistent "little Hermes" (or any god) lives on the desktop as an always-available companion. You ask for any program, tool, or workflow → Space Agent manifests it in the frontend runtime while Pantheon gods handle the backend brain. The agent isn't trapped inside a chat widget — it reshapes the workspace itself.
- **Approaches:**
  1. **GNOME/KDE Shell Extension** — Lightest lift. Persistent god panel docked to desktop. Click → ask → manifests via Space Agent runtime in a floating workspace.
  2. **Space Agent as Desktop Shell** — Replace or augment the desktop environment with Space Agent's runtime as the primary UI layer, Pantheon gods as the backend.
  3. **Pantheon OS (Ubuntu Flavor)** — Full custom distro with gods embedded at the OS level. An ISO you boot and gods are there from first login.
- **Why it works:** Space Agent reshapes the **frontend** (lives in the browser/app runtime, can build any UI from text) while Pantheon runs the **backend brain** (specialized agents, persistent memory, autonomous operations). Together they're the intelligence + the interface.
- **Notes:** Long-term vision. Needs deeper research into Space Agent's runtime architecture to understand how its frontend layer works under the hood and how gods would connect to it. The "persistent god companion" layer is the killer feature — think a Hades-game Hermes sprite that actually does stuff on your desktop.

### Package Pantheon core
- **Status:** idea
- **Added:** 2026-05-10
- **Notes:** Needs to have the webui, Hermes agent, and athenaeum file memory skeleton with all sub systems (all of the underworld). Included agents should be (Hermes/default, hephaestus) also needs to have litellm as part of the stack.


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

## 🏛️ Greek System Gods (Built into Pantheon Core)

These aren't installable gods — they're the architecture OF Pantheon itself, named after Greek entities that rule the divine order:

| Entity | Domain | Role |
|--------|--------|------|
| **Hera** | UI & Settings | Queen of the gods — all settings panels, configuration UI, user management |
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

## 🤖 God's Suggestions — From the Morning Briefing

Suggestions generated by the Morning Briefing research pipeline (Reddit, GitHub, community ecosystem scans). These are AI-sourced ideas for Pantheon improvements — prioritized and ready to promote to Core Architecture when you're ready.

### Plugin SDK — Community Gods
- **Status:** suggestion
- **Tags:** #pantheon-core #sdk #ecosystem #community
- **Added:** 2026-05-08
- **Priority:** 🔥 HIGHEST
- **Source:** Reddit (r/ClaudeAI) — HermesTool auto-discovery plugin pattern
- **Notes:** Create a `pantheon-plugin-sdk` with per-god `plugins_dir` using type-hint-driven JSON schema generation + subprocess isolation. This is THE gate to community-built gods. Without it, every god is hand-crafted by you. With it, the ecosystem builds itself.

### Skill Chain DAG Workflows
- **Status:** suggestion
- **Tags:** #pantheon-core #workflows #inter-god
- **Added:** 2026-05-08
- **Priority:** 🔥 HIGH
- **Source:** Reddit (r/LocalLLaMA) — skill chaining for multi-step workflows
- **Notes:** Formalized skill DAGs with typed input/output schemas and conditional branching for inter-god handoffs. Lets Hephaestus chain a dev task into Demeter's review pipeline or Apollo's analysis. Upgrade the current workflows system.

### Per-Message Entity Extraction (Zep Pattern)
- **Status:** suggestion
- **Tags:** #memory #extraction #zep #enhancement
- **Added:** 2026-05-08
- **Priority:** HIGH
- **Source:** Research Radar — Zep multi-layer memory analysis
- **Notes:** Pantheon currently does per-file entity extraction. Zep does per-message — giving way richer cross-session recall. Highest architectural match to Pantheon's existing three-pronged memory (vector + graph + summarization). Worth evaluating Zep as graph.db replacement.

### Dynamic Mid-Session Archival
- **Status:** suggestion
- **Tags:** #memory #memgpt #distillation #mnemosyne
- **Added:** 2026-05-08
- **Priority:** HIGH
- **Source:** Research Radar — MemGPT/Letta virtual context management
- **Notes:** Hades runs nightly distillation. MemGPT does real-time archival *on context pressure*. Trigger distillation mid-session when context gets hot — game-changer for Mnemosyne.

### Per-God MCP Aggregation Gateway
- **Status:** suggestion
- **Tags:** #pantheon-core #mcp #gateway
- **Added:** 2026-05-08
- **Priority:** MEDIUM
- **Source:** Reddit (r/LocalLLaMA) — custom MCP tools stack
- **Notes:** Multi-MCP gateway with priority-tagged tools and fallback chains. Each god gets an MCP priority stack layering domain-specific tools on the shared Pantheon MCP bus.

### Memory Importance Scoring & Conflict Detection
- **Status:** suggestion
- **Tags:** #memory #mem0 #chromadb #enhancement
- **Added:** 2026-05-08
- **Priority:** MEDIUM
- **Source:** Research Radar — Mem0 3D memory indexing
- **Notes:** Mem0's `priority_score` field could slot into ChromaDB metadata. Also add conflict detection (Mem0/Graphiti pattern) for the entity graph — currently no way to resolve contradictory facts.

### Community-Level Graph Summaries
- **Status:** suggestion
- **Tags:** #memory #graphrag #dream-cycle #enhancement
- **Added:** 2026-05-08
- **Priority:** MEDIUM
- **Source:** Research Radar — GraphRAG / Neo4j community summaries
- **Notes:** Community detection on graph.db via graph partitioning — local + global summary retrieval. Would power "what's the general theme of Codex-X" type queries.

### Centralized Plugin Registry / Skill Marketplace
- **Status:** suggestion
- **Tags:** #ecosystem #marketplace #pantheon-core
- **Added:** 2026-05-08
- **Priority:** MEDIUM
- **Source:** Community ecosystem gap analysis
- **Notes:** No centralized plugin registry or skill marketplace exists for Hermes Agent ecosystem. Pantheon could be the *first* to ship this. Community gods, shared skills, version management.

### Hades Entity Extraction Timeout Fix
- **Status:** suggestion
- **Tags:** #hades #extraction #bugfix #stability
- **Added:** 2026-05-08
- **Priority:** URGENT
- **Source:** Overnight inbox (Hephaestus)
- **Notes:** `extract-entities.py` timed out after 20 minutes. Needs: shorter timeout per Hades call (1200s → 300s) with partial progress, file-level checkpointing so it resumes where it left off instead of restarting every night, and proper env loading for cron environment.

### Desktop God-Switcher (cc-switch Pattern)
- **Status:** suggestion
- **Tags:** #ui #desktop #god-switching
- **Added:** 2026-05-08
- **Priority:** LOW
- **Source:** Ecosystem scan — farion1231/cc-switch (62.9k ⭐)
- **Notes:** Desktop All-in-One launcher for switching between gods. Click between Hephaestus, Apollo, Thoth from one tray. Could be Pantheon's entrypoint.

### Mem0 Integration for ChromaDB
- **Status:** suggestion
- **Tags:** #memory #chromadb #mem0 #integration
- **Added:** 2026-05-08
- **Priority:** LOW
- **Source:** Research Radar — GitHub LLM memory systems
- **Notes:** ChromaDB-native memory layer with automatic extraction. Zero-infra-change addition to Pantheon. Easiest win on the memory improvement list.

### Multi-Profile Athenaeum Symlinks
- **Status:** suggestion
- **Tags:** #pantheon-core #athenaeum #profiles
- **Added:** 2026-05-08
- **Priority:** LOW
- **Source:** Reddit (r/LocalLLaMA) — multi-profile switching with shared skills
- **Notes:** Use symlinks for per-god shortcuts into the Athenaeum. Validates our existing architecture — formalize the pattern.

## 💼 Work Projects

### Suno Player — Custom Music Player
- **Status:** in-progress
- **Added:** 2026-05-08
- **Notes:** Custom SvelteKit web app for playing Suno AI tracks...

### Jira Desktop Notification App
- **Status:** idea
- **Added:** 2026-05-08
- **Notes:** A lightweight desktop app...
