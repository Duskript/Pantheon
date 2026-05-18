# Pantheon Feature List

*A living inventory of every capability Pantheon ships. Updated 2026-05-16.*

> **Status legend:** ✅ Completed | 🚧 In Progress | 💡 Planned | 🏛️ Core Infrastructure
> Features are organized by domain. Cross-reference with `project-ideas.md` for detailed notes on planned items.

---

## 🖥️ Core Platform

### Hermes Agent Gateway
- **Status:** ✅ completed
- **Description:** The long-running gateway process that connects messaging platforms to the AI agent loop. Runs as `pantheon-webui.service` managing Telegram, CLI, and API server connections.
- **Components:**
  - Telegram bot — full conversational agent with slash commands, media upload, voice messages
  - API server (port 8642) — JSON API for direct agent interaction
  - Session management — per-user conversation state, checkpoint/restore
  - Memory provider chain — built-in + `pantheon-shared-facts` plugin
  - Tool schema caching — 128-entry LRU cache for fast agent spawning
  - Memory pressure monitor — auto-evicts idle agents at 2GB threshold
  - Cron scheduler — 14+ internal cron jobs managed by gateway
  - Platform allowlists — restrict which chats/rooms each agent operates on

### Pantheon WebUI
- **Status:** ✅ completed
- **Description:** Full web interface at port 8787 with 30+ API endpoint modules. Serves as the primary visual interface for Pantheon operations.
- **Components:**
  - Chat interface — SSE streaming, message history, thread topics
  - God management — create/edit/delete profiles, switch gods, configure settings
  - God picker — visual god selection with icons, roles, accent colors
  - Settings panel — model routing, providers, MCP servers, platform config
  - Athenaeum browser — browse/search Codexes, view knowledge base files
  - Kanban board — drag-drop task management with assignee filtering
  - Ideas dropdown — browse/edit project ideas inline
  - Soul Forge — conversational god creation via chat popup
  - Summon drawer — browse/install marketplace gods
  - Boon Drawer — rich artifact search
  - Utilities panel — bookmarklet installer, PWA share target config
  - Session recovery — restore crashed sessions
  - Theme system — density (compact/comfortable/spacious), color scheme
  - Terminal access — in-browser terminal
  - File upload — image/audio/video media support
  - User authentication — single-user mode with future multi-user hooks
  - PWA support — installable as progressive web app with push notifications

### Pantheon MCP Server
- **Status:** ✅ completed
- **Description:** HTTP MCP server on port 8010 exposing Pantheon subsystems as standard MCP tools. Backbone for all agent-to-Pantheon interaction.
- **Tools (14+):** `athenaeum_graph_search`, `athenaeum_search`, `athenaeum_walk`, `athenaeum_read`, `athenaeum_write`, `athenaeum_list_codexes`, `messaging_send`, `messaging_check_inbox`, `hades_get_report`, `god_list`, `system_health`, `skill_list`, `skill_info`, `skill_run`
- **Integrations:** ChromaDB (21 collections, 1424 vectors), SQLite knowledge graph, embedding service via OpenRouter/Ollama

### Janus MCP Hub
- **Status:** ✅ completed
- **Description:** MCP aggregation server that spawns and proxies multiple child MCP services through a single STDIO transport. Reduces context overhead by exposing multiple tool providers as one server.
- **Child services:** Filesystem (14 tools), Google Workspace (11 tools: Gmail, Calendar, Drive)

### Playwright MCP — Browser Automation
- **Status:** ✅ completed
- **Description:** Full browser automation via Playwright MCP connected to Chrome DevTools Protocol. Navigate, click, type, screenshot, snapshot, network monitoring, file upload — all from agent tool calls.
- **Connection:** CDP via Vivaldi browser bridge on port 9222

### Multi-User Ready Shared Context
- **Status:** ✅ completed
- **Description:** All shared context paths scoped by `HERMES_USER_ID` env var. Decision files at `decisions/{user_id}/`, context injection at `CONTEXT_{user_id}.md`. Inject cron discovers all user subdirectories automatically. Single-user today (konan), zero-config when multi-user arrives.

---

## 🤖 Agent & AI Infrastructure

### Model Routing & Provider System
- **Status:** ✅ completed
- **Description:** Routes requests to the optimal model per task type — vision, compression, web extraction, session search, approval, MCP dispatch, etc. DeepSeek V4 Flash as default, with fallback through 10+ providers.
- **Configured providers:** OpenCode Go, Ollama (local), OpenRouter
- **Router models:** Minimax M2.5 (web extract, session search, MCP dispatch, title gen), Qwen 3.6 Plus (skills hub), DeepSeek V4 Pro (approval)

### Context Compression Pipeline
- **Status:** ✅ completed
- **Description:** Auto-compresses conversation history at 40% context threshold (reduced from 70%). Before compression, extracts decisions/facts via `pantheon-shared-facts` provider using regex priority scoring — no LLM call needed.
- **Components:**
  - `on_pre_compress` hook in memory provider plugin
  - Priority scoring (1-10) via regex pattern matching
  - Domain auto-detection (infrastructure, development, config, music, writing, design)
  - Jaccard word-set deduplication against last 20 files
  - Decision files saved to `~/pantheon/shared/decisions/{user_id}/`
  - CONTEXT regeneration cron every 15 min (`inject-shared-context.py`)
  - System prompt injection via `system_prompt_block()` hook
  - Budget-aware (full items for large models, one-liner for small models)

### Memory & Knowledge Systems

#### Mnemosyne — Semantic Memory with Importance Scoring
- **Status:** ✅ completed
- **Description:** ChromaDB-based semantic search with Mem0-style priority scoring. `score_memory_importance()` writes `priority_score` into ChromaDB metadata. Conflict detection via graph nodes + `contradicts` edges.
- **Tests:** `tests/test_mnemosyne.py`, `tests/test_graph_client.py`

#### Athenaeum — Shared Knowledge Layer
- **Status:** 🏛️ core
- **Description:** Multi-codex knowledge base at `~/athenaeum/` with 21 codexes / 1873 files. ChromaDB vector store + filesystem markdown + entity-relationship graph. The memory that outlives any single session.
- **Components:**
  - Codex-partitioned markdown files with INDEX.md per codex
  - Auto-embedding on write via OpenRouter/Ollama
  - Vector search via `athenaeum_search` MCP tool
  - Graph search via `athenaeum_graph_search` (BFS, pathfinding, entity lookup)
  - Inbox pipeline: bookmarklet/PWA/Syncthing drops → `process-inbox.py` → classify → file

#### Knowledge Graph (GraphClient)
- **Status:** ✅ completed
- **Description:** SQLite entity-relationship graph with 18 entity types (file, session, entity, codex, url, concept, person, project, tool, system, organization, place, event, decision, preference, media, skill, fact). Typed edges, BFS pathfinding, FTS5 full-text search, CRUD operations.
- **Code:** `pantheon-core/gods/graph_client.py` (855 lines)

#### Memory Importance Scoring & Conflict Detection
- **Status:** ✅ completed
- **Description:** Mem0-inspired pattern — deterministic fact nodes + `contradicts` edges when same subject/predicate has conflicting values. Zero external dependencies.

#### Memory Extraction Weekly Review
- **Status:** 💡 cron (not yet run)
- **Description:** Weekly cron (Sundays 08:00) that reviews recent sessions via `session_search` and proposes durable memory entries. Never run — first fire this Sunday.

### Hermes Dojo — Agent Self-Improvement
- **Status:** ✅ completed (pre-installed)
- **Description:** Meta-agent that reads session logs, finds recurring failures, and auto-patches the skills behind them. Pipeline: Monitor → Analyzer → Fixer → Tracker → Reporter. Run with `/dojo auto`.

### Agent Delegation System
- **Status:** ✅ completed
- **Description:** `delegate_task` tool spawns isolated subagents with their own conversation, terminal, and toolset. Parallel batch mode (up to 3 concurrent). Orchestrator mode for recursive decomposition. Integrates with Claude Code, Codex CLI, and OpenCode CLI as ACP subprocess agents.

### Native MCP Client
- **Status:** ✅ completed
- **Description:** Built-in MCP client in Hermes Agent that connects STDIO and HTTP MCP servers. Auto-discovers tools, manages transport lifecycle, handles tool call routing.

---

## 📨 Communication & Platforms

### Telegram Integration
- **Status:** ✅ completed
- **Description:** Full Telegram bot with native media support (photos, videos, audio/voice), markdown formatting, thread/topic targeting, slash commands, scheduled delivery, and platform allowlists.

### API Server
- **Status:** ✅ completed
- **Description:** JSON API on port 8642 for headless agent interaction. Used by WebUI and external tools.

### Discord Integration
- **Status:** 🚧 broken (`hermes-gateway-hephaestus` service failed)
- **Description:** Discord bot gateway. Currently non-functional due to configuration/auth issue — needs investigation.

### God-to-God Messaging (Pantheon Bridge)
- **Status:** ✅ completed
- **Description:** MCP-based inter-god messaging system. Gods send messages via `messaging_send`, check inbox via `messaging_check_inbox`. Messages persist as JSON files in `gods/messages/`. Supports priority levels and message types.

### God Notifications
- **Status:** ✅ completed
- **Description:** Push-based notification system via `god-notify` script. Routes to WebUI bell + PWA push + Telegram. Gods ping users when tasks complete, errors happen, or input is needed. Replaced inbox-polling.

### Push Notifications (PWA)
- **Status:** ✅ completed
- **Description:** Web Push API integration. Pantheon as installed PWA receives push notifications for god alerts, task completions, and system events.

---

## 🌐 Web & Content

### Athenaeum Web Clipper
- **Status:** ✅ completed
- **Description:** Save anything to the Athenaeum from anywhere:
  - **Bookmarklet** — drag a button from Settings → Utilities to bookmarks bar. Click on any page → saves URL, title, highlighted text
  - **PWA Share Target** — mobile OS share sheet → "Pantheon" appears as share target
  - **Server URL config** — overridable for Tailscale/custom domains
  - **Inbox pipeline** → `process-inbox.py` fetches content, classifies into codex, files it
  - **Syncthing-compatible** — any `.md` dropped in inbox/ gets processed identically

### Pantheon Browser Extension
- **Status:** ✅ completed
- **Description:** Full Chrome extension:
  - Popup with god roster, sessions, ideas list
  - Side panel chat — talk to any god without leaving the page
  - Web clipper — save URLs/titles/highlights to Athenaeum
  - Context menus for quick actions
  - Config.js for server URL

### Humanizer Skill
- **Status:** ✅ completed
- **Description:** Strips AI-isms from public-facing content. No em dashes, no rule-of-three lists, no bold-header-colons, no signposting, no bullet-list structures, no tilde approximations. Mandatory for all public-facing text.

---

## 🎵 Creative & Music

### Apollo — Creative God
- **Status:** ✅ completed
- **Description:** Registered Pantheon god for songcraft, lyrics, poetry, and Suno AI music production. Active profile with SOUL.md, persona, and skill chain.

### Lyric Smith Workflow — Full Songwriting Pipeline
- **Status:** ✅ completed
- **Description:** Multi-phase songwriting workflow via Lyric Smith skill. Phase 1: setup fields one at a time. Phase 2 Creation Loop: one section at a time (not bulk generation). Preferred metaphor vocabulary: fuse/dynamite/explosion/shrapnel over flame/fire.

### Suno AI Music Production
- **Status:** ✅ completed
- **Description:** Complete Suno AI pipeline from lyrics → tags → generation. Genre lexicon (130+ genre profiles), artist profiles (28 artist reference profiles), V5 style library, format validation.

### Morning Hook Ideas — Apollo Cron
- **Status:** ✅ completed
- **Description:** Cron job (08:00 UTC, 7/30 days) generates 3 original song hook ideas and patches them into project-ideas.md's Song Hooks section. Produces rich genre/vibe/lyrical-angle notes.

### Genre Lexicon Expansion — Apollo Cron
- **Status:** ✅ completed
- **Description:** Daily cron (09:00 UTC, 7/30 days) adds 2-3 genre profiles per run. Expanded to 130+ genre profiles with production notes and reference artists.

### Artist Profile Expansion — Apollo Cron
- **Status:** ✅ completed
- **Description:** Daily cron (09:30 UTC, 7/30 days) adds 2-3 artist profile references. 28+ profiles cataloging lyric craft and musical identity.

### HeartMuLa — Song Generation
- **Status:** ✅ completed
- **Description:** Suno-like song generation from lyrics + tags. Audio file output for testing.

### SongSee — Audio Spectrograms
- **Status:** ✅ completed
- **Description:** Audio spectrogram and feature extraction (mel, chroma, MFCC) via CLI.

### SNES God Portraits
- **Status:** ✅ completed
- **Description:** Generate SNES-era pixel art portrait prompts in the style of classic RPGs.

---

## 🔧 Developer Tools & SDK

### God SDK — Phase 1 CLI
- **Status:** ✅ completed
- **Description:** Two CLI commands for creating and maintaining Pantheon gods:
  - `pantheon init <name>` — Full god scaffold: profile, SOUL.md, persona, config.yaml, harness, Codex, registries. Domain-to-codex mapping auto-attaches reference knowledge.
  - `pantheon validate [name]` — 8 checks per god (SOUL sections, persona, config, MCP, Codex structure, registries, manifest). Validates one or ALL gods.

### God Creation Lifecycle
- **Status:** ✅ completed
- **Description:** Full pipeline from blueprint → forge → scaffold:
  - **Soul Forge** — WebUI chat popup interviews about domain, voice, boundaries, produces SOUL.md
  - **Scaffold** — `pantheon init` builds complete profile structure
  - **Codex authoring** — structured knowledge base entries
  - **Bundle** — `pantheon-bundle` packages god as marketplace-ready tarball
  - **Distribution** — Summon repository for community sharing

### Pantheon Bundle
- **Status:** ✅ completed
- **Description:** `pantheon-bundle` CLI exports a god + its bundled Codexes as a distributable tarball with `god.yaml`, SOUL.md, persona, config.yaml, and asset checksums.

### Pantheon Migration
- **Status:** ✅ completed
- **Description:** Full deployment migration over Tailscale/SSH/USB. Export/install scripts (`migrate-export.sh`, `migrate-restore.sh`) with credential vault migration and Oracle vault support.

### Claude Code Integration
- **Status:** ✅ completed
- **Description:** Delegate coding tasks to Claude Code CLI via ACP subprocess. Handle repo coding, debugging, refactoring, testing, and PR creation. Hermes orchestrates, Claude Code executes, Hermes verifies.

### Codex CLI Integration
- **Status:** ✅ completed
- **Description:** Delegate coding to OpenAI Codex CLI. Same orchestrator pattern as Claude Code.

### OpenCode CLI Integration
- **Status:** ✅ completed
- **Description:** Delegate coding to OpenCode CLI for PR review and code tasks.

---

## 🤖 Automation & Operations

### Hades Nightly Consolidation
- **Status:** 🏛️ core (✅ completed)
- **Description:** Automated pipeline running daily at 00:00 UTC. Health checks → distillation → archive management → LLM compilation → entity extraction → shared context sweep → codex auto-creation → INDEX.md generation → stale file detection → suggestions → heartbeat → report.
- **Code:** `pantheon-core/gods/hades.py` (1911 lines)

### Dreamweaver Dream Cycle
- **Status:** ✅ completed
- **Description:** Daily cron (08:15 UTC) that runs knowledge graph maintenance: entity deduplication, enrichment, relationship decay, and inference. Keeps the graph clean and connected.

### Athenaeum Entity Extraction
- **Status:** ✅ completed
- **Description:** Pre-Hades pipeline (07:30 UTC) that extracts entities from new Athenaeum content and registers them in the knowledge graph. Feeds Hades consolidation.

### Hestia — System Health Monitor
- **Status:** 🏛️ core (✅ completed)
- **Description:** Checks ChromaDB, Athenaeum filesystem, embedding service, gateway, and cron job health. Writes heartbeats, sends reports to Hermes inbox on failure. Runs as systemd timer.

### Shared Context Digest
- **Status:** ✅ completed
- **Description:** Generates `~/pantheon/shared/DIGEST.md` every 2h with decisions (grouped by user), active tasks, and Athenaeum writes. Primary cross-god awareness mechanism — Hermes checks before significant builds.

### Morning Briefing Pipeline
- **Status:** ✅ completed
- **Description:** Daily cron (07:05 UTC) gathers: system status, Hades report, project ideas, research radar (Reddit, GitHub, job market), Apollo hook ideas, heartbeats, god inboxes. Composes energetic Hermes-style briefing → Telegram delivery.

### Bedtime Reminders
- **Status:** ✅ completed
- **Description:** Systemd timer Mon–Fri at 04:00 UTC (22:00 MDT) with escalation reminders at 04:05, 04:10, 04:15 UTC. Silent resets daily.

### Athenaeum Triage
- **Status:** ✅ completed
- **Description:** Parses Hades reports into actionable health cards with severity levels. Morning briefing includes triage state. Wrapper at `~/athenaeum/scripts/athenaeum-triage.py`.

### Kanban Board
- **Status:** ✅ completed
- **Description:** Full Kanban system in WebUI with task columns (triage → backlog → blocked → in-progress → review → done). Drag-drop, assignee filtering, per-profile lanes, comments, events, dispatcher nudge.

### Webhook Subscriptions
- **Status:** ✅ completed
- **Description:** Event-driven agent runs triggered by external webhooks. Git pushes, CI completions, or custom events can kick off autonomous agent sessions.

---

## 🗄️ Integrations & External Services

### Google Workspace (Gmail, Calendar, Drive, Docs, Sheets)
- **Status:** ✅ completed
- **Description:** Full Google Workspace MCP integration via `@aaronsb/google-workspace-mcp`. 11 tools for mail, calendar events, drive file management, docs/sheets editing. OAuth2 authenticated.

### Ollama Local LLM
- **Status:** ✅ completed
- **Description:** Local LLM inference server on port 11434. Runs as system service. Used as fallback provider for local-only operations.

### Tailscale Mesh VPN
- **Status:** 🏛️ core
- **Description:** Secure mesh VPN connecting 4 devices: Pantheon server, personal desktop (cachyOS), phone (Pixel 9), and remote Windows machine (VTCU). Direct connections where possible, relay fallback.

### Spotify Integration
- **Status:** ✅ completed
- **Description:** Play, search, queue, manage playlists and devices via skill.

### GitHub Integration Suite
- **Status:** ✅ completed
- **Description:** 6 skills covering: repo management (clone/create/fork/releases), PR lifecycle (branch/commit/open/CI/merge), code review (diffs, inline comments), issues (create/triage/label), auth setup (HTTPS tokens, SSH keys, gh CLI), codebase inspection (pygount LOC analysis).

### ACI — 600+ Pre-Built MCP Integrations
- **Status:** ✅ completed (pre-installed)
- **Description:** Open-source platform wrapping 600+ SaaS APIs (Gmail, Slack, GitHub, Notion, Vercel, Supabase, Stripe, Sentry, Brave Search) into MCP tools. Unified Server mode uses only 3 meta-tools for minimal context overhead. Currently disabled — was removed from config due to missing `--linked-account-owner-id` flag.

### X/Twitter (xurl)
- **Status:** ✅ completed
- **Description:** Full X/Twitter v2 API via xurl CLI: post tweets, search, DMs, media upload, account operations.

### YouTube Content
- **Status:** ✅ completed
- **Description:** YouTube transcripts → summaries, threads, blog posts, social content.

---

## 🌍 Community & Marketplace

### Summon God Repository
- **Status:** ✅ completed
- **Description:** Two-way god marketplace powered by `Duskript/Pantheon-Summons` GitHub repo:
  - Browse — `/api/gods/summon/list` proxies GitHub Contents API for available gods
  - Install — `POST /api/gods/summon` pulls god from Summons repo, scaffolds locally
  - Submit — `POST /api/gods/{name}/submit-to-summons` forks repo, creates branch, opens PR
  - WebUI drawer — visual cards with SOUL preview, one-click install

### Featured Gods Available
- **Status:** ✅ completed
- **Description:** Three registered Pantheon gods deployed and active:
  - **Hermes** — Messenger & Interface Operations Manager
  - **Hephaestus** — Core Builder & Tool Forger (code, scaffolding, SDK)
  - **Apollo** — Creative God of Songcraft (lyrics, poetry, Suno production)

---

## 🚧 In Progress

### Discord Gateway
- **Status:** 🚧 broken
- **Description:** `hermes-gateway-hephaestus.service` has failed. Needs investigation — likely config/auth issue.
- **Impact:** Discord platform unavailable. Telegram, API server, and CLI are unaffected.

---

## 💡 Planned

### Janus Cloud Broker — Zero-Friction OAuth Bridge
- **Status:** 💡 idea
- **Priority:** 🔥 HIGH
- **Description:** Tiny relay server (Cloudflare Worker or cheap VPS) removing the Google Cloud Console step from janus onboarding. `janus connect google-workspace` opens browser → auth.janus.sh → pre-registered OAuth → encrypts tokens. Grandparent-ready OAuth.

### context_dirs Plugin — Auto-Inject Shared Context
- **Status:** 💡 idea
- **Description:** Hermes Agent plugin that auto-reads configured directories and injects their content into every turn's system prompt. Solves "gods never read shared context" once and for all. Would disable the digest cron.

### God SDK — Phase 2: Build, Install, Uninstall
- **Status:** 💡 planned
- **Description:** `pantheon god build/install/uninstall`. Build packages god + bundled Codexes as tarball. Install extracts Codexes to `~/athenaeum/`. Uninstall cleans up cleanly. Upgrade to Click/Typer for subcommand nesting.

### Skill Chain DAG Workflows
- **Status:** 💡 suggestion
- **Priority:** 🔥 HIGH
- **Description:** Formalized skill DAGs with typed input/output schemas and conditional branching for inter-god handoffs. Lets Hephaestus chain a dev task into Demeter's review pipeline or Apollo's analysis.

### Per-Message Entity Extraction (Zep Pattern)
- **Status:** 💡 suggestion
- **Priority:** HIGH
- **Description:** Move from per-file entity extraction to per-message. Richer cross-session recall. Worth evaluating Zep as graph.db replacement.

### Per-God MCP Aggregation Gateway
- **Status:** 💡 suggestion
- **Description:** Multi-MCP gateway with priority-tagged tools and fallback chains. Each god gets an MCP priority stack.

### Community-Level Graph Summaries (GraphRAG)
- **Status:** 💡 suggestion
- **Description:** Community detection on graph.db via graph partitioning — local + global summary retrieval. Powers "what's the general theme of Codex-X" queries.

### Pantheon OS — Desktop Companion
- **Status:** 💡 idea
- **Description:** AI-native Ubuntu-based OS where Pantheon gods live on the desktop as persistent companions. Fusion of Pantheon (backend), Space Agent (frontend runtime), and Ubuntu (foundation).

### Multi-User Pantheon Architecture
- **Status:** 💡 idea
- **Description:** Multi-tenant Pantheon with per-user profiles, god isolation, shared vs private knowledge, resource quotas, and god permissions. Full architecture sketch in project-ideas.md.

### Browser Extension — Pin Objective
- **Status:** 💡 idea
- **Priority:** HIGH
- **Description:** "Pin Objective" button in WebUI chat header. Locks agent onto a goal across turns. Visual indicator: "Locked on: [objective]".

### Voice Cloning in TTS Settings
- **Status:** 💡 idea
- **Description:** "Clone Voice" button in TTS panel. Record or upload sample → generate custom voice → assign to a god. Each god could have their own voice.

### Session Management UI (Checkpoints v2)
- **Status:** 💡 idea
- **Description:** Session history in WebUI with save/restore/delete. Visual timeline per god.

### Platform Allowlist Editor
- **Status:** 💡 idea
- **Description:** UI panel in God Settings for per-platform allowlists. Visual toggle per channel.

### Video Upload + Analysis Panel
- **Status:** 💡 idea
- **Description:** Video upload alongside image/audio. Analysis with timestamps, object detection, transcript extraction.

### Centralized Plugin Registry / Skill Marketplace
- **Status:** 💡 suggestion
- **Description:** No centralized plugin registry exists for Hermes Agent ecosystem. Pantheon could be first. Community gods, shared skills, version management.

### Layout Density Fix
- **Status:** 🐛 known bug
- **Description:** Density CSS variables apply to outer containers but not inner padding. User bubble padding stays fixed. Lower-specificity density rules lose to higher-specificity message styles.

### Gateway Memory Scaling — P1 Lightweight Agent
- **Status:** 💡 known issue (LOW priority)
- **Description:** AIAgent monolith has 1,058 CLI-only attrs. ~6MB per instance. For 100+ users, a lightweight GatewayAIAgent subclass drops to ~2MB. Multiple other scaling issues documented in Codex-Pantheon/reference/.

### Remote Management / Multi-Install
- **Status:** 💡 idea
- **Description:** Connect to and manage other Pantheon installations remotely. SSH/Tailscale-based god orchestration across multiple servers.

### Suno Player — Custom Music Player
- **Status:** 💡 idea
- **Description:** SvelteKit web app for browsing, playing, and managing Suno AI music tracks.

### Jack Roberts Intel
- **Status:** 💡 paused
- **Description:** Competitive intel on "Hermes OS" (Jack Roberts' branded Hermes Agent configs, Pantheon personas, Claude Code OS workflows). Behind Skool paywall — paused pending cashyOS connection.

---

## 🏗️ Planned Gods

### Hestia — Interactive Cookbook & Kitchen Assistant
- **Status:** 💡 idea
- **Description:** Warm, nurturing cooking god. Step-by-step recipe guidance with skill-level adaptation. Dietary substitutions, meal planning, leftovers management.

### Heimdall — Infrastructure Monitoring & Watchman
- **Status:** 💡 idea
- **Description:** Server uptime, resource usage, log watching, anomaly detection, alert routing. The watchman who never sleeps.

### Skadi — Fitness, Wellness & Outdoor Coach
- **Status:** 💡 idea
- **Description:** Workout logging, outdoor activity planning, nutrition notes, sleep tracking. Adaptive to fitness level.

### Inari — Intelligent Bookkeeping & Finance
- **Status:** 💡 idea
- **Description:** Expense tracking, budget planning, spending analysis. Knows where every penny went.

### Ganesha — Project Scaffolding & Obstacle Removal
- **Status:** 💡 idea
- **Description:** When stuck — code bug, blocked workflow, config issues — Ganesha clears the path. Also project scaffolding and boilerplate generation.

---

## ⚠️ Known Issues & Tech Debt

| Issue | Priority | Status |
|-------|----------|--------|
| Discord gateway broken (`hermes-gateway-hephaestus.service`) | HIGH | Needs investigation |
| Gateway ~140MB/hr leak from cached agent `_session_messages` | HIGH | Message history truncation not yet implemented |
| WebUI layout density CSS not applied to inner elements | MEDIUM | Bug in CSS specificity |
| Janus MCP may need restart (last active May 14) | LOW | Check + restart if stale |
| ACI integration removed from config (missing flag) | LOW | Re-add if needed |
| WebUI `gateway.status` drift after ~20h runtime | LOW | Known false-positive in gateway health check |
| Weekly memory extraction cron has never run | LOW | First fire Sunday at 08:00 |

---

*This feature list is the authoritative catalog. For detailed notes on planned features, see `project-ideas.md`. For daily operational status, see `shared/DIGEST.md`.*
