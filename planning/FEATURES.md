# Pantheon — Feature Inventory

> **Canonical feature catalog — Last updated: 2026-05-20**
> Every feature that makes Pantheon what it is. Described at a high level: what it does, why it matters, and how it works.

---

## Core Architecture

### Pantheon MCP Server
The central integration point for the entire system. Runs as a standalone MCP server (FastMCP) on port 8010, exposing Athenaeum, Ichor memory, god roster, Hades reports, skill execution, and inter-god messaging as MCP tools. Any MCP client — Hermes Agent, AionUi, Claude Code — can connect and use Pantheon's full tool suite. This is the backbone that makes Pantheon's capabilities accessible to every god and every frontend.

### Ichor Multi-Tier Memory System
A sophisticated multi-backend memory engine that fuses keyword search (SQLite FTS5), semantic vector search (ChromaDB), entity-relationship graph traversal (Graph DB), and structured event logging into a single unified retrieval interface. The memory trait contract provides four standard operations — `ichor_store`, `ichor_retrieve`, `ichor_forget`, and `ichor_health` — so every god has consistent access to past context without needing to know which backend holds the data.

### Soul Forge — God Creation
The god creation pipeline that takes a user's description and crafts a complete god: SOUL.md (identity), god.json (metadata with display_name, icon, color, domain), and profile scaffolding. Accessed through the Forge Wizard in the Web UI, it lets users create new AI personalities with their own domain expertise and visual identity, expanding the Pantheon with custom gods on demand.

### God Profile System
A per-god identity and configuration system where every god has its own directory under `~/.hermes/profiles/<god>/` containing SOUL.md, persona.md, config.yaml (model, tool sets, MCP servers, provider), god.json metadata, icon, skills, sessions, memories, plans, cron jobs, platforms, workspace, and state database. This is what enables true multi-agent operation — each god is a fully independent agent with its own configuration, tools, and identity.

### God Harness System (Schema-Validated)
A schema-versioned YAML harness system that defines exactly what a god does, what it refuses, how it formats output, how it handles ambiguity, and how it routes out-of-scope requests. Base harnesses define core identity; studio harnesses extend them with domain-specific specializations. The loader validates schema_version before loading, and hard stops in the harness are non-negotiable — enforced at the definition level, not by convention. Though partially aspirational, this architecture underpins the whole god model.

### Ichor RALPH 5-Gate Harness
A deterministic middleware system that enforces the RALPH loop (Reasoning → Action → Logic → Planning → Handoff) at the tool-call level. Five composable gates — State Gate (read-before-write), Logic Gate (syntax validation), Intent Injection Gate (context pre-fetching), Phase Detection Gate (zero-LLM phase detection by keyword), and Handoff Gate (clean god-to-god transitions) — move reliability out of the prompt and into the infrastructure. Small models match SOTA reliability by having deterministic "rules of the road" enforced at the middleware layer.

### Ichor Forge — Self-Adjusting Harness
The meta-learning loop for the RALPH gates, patterned after Hermes Dojo: analyze → identify weakness → adjust → verify → report. Reads intervention logs, detects patterns (over-blocking gates, missing keywords, underused tools, recurring failure modes), and produces structured adjustment patches. This is not model fine-tuning — it's the harness learning from its own experience, like a blacksmith reshaping a blade after seeing how it cuts.

### Model Router
A dynamic model routing system that intelligently assigns which language model powers each god based on config.yaml settings. Supports OpenRouter, Ollama, and other providers with per-god model selection, allowing different gods to use different models optimized for their specific domain.

### Sanctuary Configuration
A configuration layer that defines the "room" a god operates in — the working context including workspace path, vault path, and environment settings. Manages per-god workspace isolation so each god has its own filesystem context.

### Vault Writer
A session logging system that writes structured conversation transcripts to the Athenaeum Codex vault. Ensures every god session is preserved for later distillation, search, and consolidation by Hades.

---

## Web UI (React)

### Pantheon Web UI — Glassmorphic Interface
A full-featured React-based web interface served at port 8787 (production) or 8788 (dev), built with glassmorphic design: blurred glass panels, ambient drifting gradient backgrounds, vignette edges, noise overlays, and a dark "Calm Console" color palette. Drops into Hermes Agent's Web UI as a custom index, providing a visually immersive experience for managing the entire Pantheon.

### God Picker & God Rail
A sidebar component that displays all available gods as a selectable grid with icons, names, and status indicators. The God Rail provides quick-switching between gods, showing active state, unread indicators, and accent colors per god. Each god's accent color glows subtly in the UI, giving every AI personality a distinct visual presence.

### God Management Panel (Summon/Exile/Export)
A full management interface for gods: summon new gods from the community repository (`Duskript/Pantheon-Summons`), exile gods you no longer need, export gods as portable bundles (tar.gz with SOUL.md, persona.md, config, icon, skills, MCP configs, and codexes) for sharing or backup. The export pipeline can also create GitHub PRs against the summon repo to share your gods with the community.

### Soul Forge Wizard
A step-by-step UI wizard that guides users through creating a new god. Provides icon selection, color picking, domain definition, and soul crafting. Handles the entire god creation flow from description to fully provisioned profile with SOUL.md and god.json metadata.

### God Accent Glow
A per-god visual theming system where each god's defined accent color (from god.json) permeates the UI — glowing borders, accent highlights, status indicators, and the god's icon all carry the god's unique color. Gives each AI personality an immediate visual identity that distinguishes it in the interface.

### Athenaeum Panel
A browser-based interface for the knowledge base: list all Codexes (knowledge domains), navigate the INDEX.md tree structure, read files, and perform semantic search across the entire Athenaeum. Makes the knowledge graph browsable without needing filesystem access.

### Kanban Board / Task Management
A kanban-style task management board integrated via the kanban_bridge API. Allows organizing work items, tracking progress across columns, and managing tasks visually within the Pantheon Web UI.

### Chat Interface with Full Markdown Rendering
The core conversation UI with streaming responses, markdown rendering (via marked.js), syntax-highlighted code blocks (via highlight.js), tool call display, and conversation history management. Supports pinning, renaming, archiving, and deleting conversations.

### Theme System
A CSS custom property-based theming system with the "Pantheon Calm Console" dark theme as default. Features ambient drifting background animations, glassmorphism with backdrop-blur, gradient accents, and Firefox-specific performance optimizations. Supports prefers-reduced-motion for accessibility.

### Mobile Layout & Responsive Design
Responsive CSS that adapts the Pantheon UI to mobile viewports with collapsible sidebars, touch-friendly controls, and adaptive layouts. The sidebar can be collapsed to provide more screen space on smaller devices.

### Bootstrap Launcher
A one-shot bootstrap script that discovers the Hermes Agent installation, resolves the correct Python interpreter, creates a virtualenv if needed, installs dependencies, and launches the Web UI server. Supports foreground mode for systemd/supervisord, automatic browser opening, and health-probe-based startup verification.

### Onboarding Flow
A first-run wizard that guides new users through setting up the Pantheon Web UI — configuring providers, setting up models, and connecting to the Hermes Agent runtime. Skips automatically when the environment is already configured.

---

## Memory & Knowledge

### Athenaeum Knowledge Graph
The Pantheon's structured knowledge base: a filesystem of Codexes (Codex-Forge, Codex-Pantheon, Codex-Infrastructure, Codex-General, Codex-User, plus per-god Codex-God-{name} directories) organized as markdown files with INDEX.md navigation. Backed by ChromaDB for semantic vector search and a Graph DB for entity-relationship queries. Every file is embeddable and searchable. This is Pantheon's long-term memory — persistent, structured, and god-accessible.

### Ichor Short-Term Memory (Tier A — Zero-LLM Regex Extraction)
A zero-LLM regex extraction engine that fires on conversation compaction events. Extracts structured events — decisions, commitments, facts, preferences, corrections, insights, blockers, references, and follow-ups — from conversation text using 170+ compiled regex patterns (15+ per type). Events are stored in the ichor_events table with confidence scores and synced to the knowledge graph. No LLM calls needed: it's fast, free, and runs silently in the background.

### Ichor Long-Term Recall (Hybrid Fused Search)
A fused search engine that combines all four memory backends — FTS5 keyword, ChromaDB semantic, Graph DB entity-relationship, and structured events — into a single ranked result set. Weights each backend (0.20/0.35/0.25/0.20) and normalizes scores before fusion. Gracefully degrades when a backend is unavailable. This is what powers `ichor_retrieve` and gives gods comprehensive memory recall.

### Ichor Brief — Query-less Context Recall
A "what should I know right now?" engine that scores every stored event by a weighted formula of priority (blockers > commitments > decisions), freshness (decaying over 7 days), confidence, and repetition. Returns a ranked, scannable brief for any god without requiring a search query. Gods can call `ichor_brief(god_name="hermes")` and instantly know what matters.

### Ichor Graph Query — Multi-hop NL Graph Traversal
A natural language query engine for the knowledge graph that translates questions like "What tools does Hermes use?" into multi-hop graph traversals. Uses an NL parser to extract anchor entities, relation verbs, and target types, then performs breadth-first graph walking with configurable depth. Supports relation inference, entity resolution, and path building.

### Shared Context Digest System
A cross-god shared context mechanism that generates a periodic DIGEST.md file in `~/pantheon/shared/`. Every god can read this to stay aware of decisions, active tasks, and knowledge updates from other gods. Injected into the shared context via cron, ensuring all gods have a baseline understanding of the current state of the Pantheon.

### Dreamweaver Consolidation (Icher Tier A Processing)
The extraction and consolidation layer that processes conversation text during compaction events. Tier A fires at configurable thresholds (default 40% compaction), extracts structured knowledge, stores it in the events database, syncs entities to the graph, and builds the foundation for the Ichor Brief and Subconscious Engine.

### Ichor Safety Layer — Secret Redaction
A pattern-based secret detection and sanitization system that prevents sensitive data (API keys, tokens, passwords, private keys, JWTs, AWS credentials) from being stored in memory. Detects 15+ patterns of secrets in text and JSON structures, redacting them before they enter the Ichor database. Protects both the system and the user's sensitive information.

### Schemas
The database schema definitions that underpin the Ichor memory system. The `ichor-events.sql` schema defines the events table with FTS5 full-text search support, confidence scoring, session tracking, and god-specific filtering — the foundation for all structured memory operations.

---

## System Operations

### Ichor Subconscious Engine — Periodic Background Awareness
A cron-driven engine that gives every god proactive awareness of pending items. Runs on a timer, queries the Ichor events database for actionable items (blockers, commitments, follow-ups, decisions, insights), builds a structured situation report, and delivers it to the god's filesystem inbox. Includes an overlap guard that prevents duplicate deliveries by tracking last-reported event IDs per god.

### Hades Nightly Consolidation Pipeline
The nightly cron job that maintains Athenaeum health. Performs four operations: (1) **Health checks** — compares ChromaDB vs filesystem consistency, validates INDEX.md coverage, finds stale files; (2) **Distillation** — extracts canonical knowledge from session vaults into distilled/ directories; (3) **Archive management** — identifies and moves stale/unlinked content; (4) **Report generation** — produces a structured nightly report available via MCP. Generates codex suggestions and shared context sweeps.

### Demeter — File Watcher & Ingest Pipeline
A filesystem watcher that monitors Codex directories for changes and triggers re-embedding into ChromaDB when files are added, modified, or removed. Combines a classifier, an ingester, and a watcher to keep the vector store synchronized with the filesystem in near-real-time.

### Hestia — Health Monitor
A system health checking service that monitors ChromaDB, Athenaeum filesystem, and embedding service availability. Runs regular checks and reports status, ensuring the core infrastructure is operational and alerting when components go down.

### Kronos — Event Logger
A structured logging service that records system events, gate interventions, and operational metrics. Provides an append-only log pipeline for debugging, auditing, and post-mortem analysis of Pantheon system behavior.

### Cron Job System
A scheduled job system managed via Hermes Agent's cron subsystem. Handles periodic tasks: Hades nightly runs, Shared Context digest generation (every 2 hours), Ichor Subconscious Engine ticks, Ichor Forge analysis, heartbeat monitoring, and Demeter watch cycles. Each god also has its own per-god cron/ directory for god-specific schedules.

### Heartbeat Monitor
A system that periodically checks the liveness of Pantheon services. Verifies that the MCP server, Web UI, and backend services are responding correctly, providing early warning of service degradation.

### Pantheon Scripts Suite
A comprehensive collection of CLI scripts for system management:
- `pantheon` — main CLI entry point
- `pantheon-install` / `pantheon-uninstall` / `pantheon-upgrade` — system lifecycle
- `pantheon-bundle` / `pantheon-export` — god export and bundling
- `pantheon-list-gods` — god roster query
- `pantheon-import-claude` — Claude project import
- `athenaeum-ingest` / `init-athenaeum.sh` — knowledge base initialization
- `hades` — nightly consolidation runner
- `demeter-watch.py` — file watcher launcher
- `check_heartbeat.py` — health check runner
- `inject-shared-context.py` — cross-god context injection
- `the-fates.py` — system orchestration
- `setup-server.py` — server provisioning
- `migrate-*` scripts — data migration tools
- `janus-bridge.py` / `janus-bridge-v2.py` — Claude Code / AionUi bridge

### Docker Support
A Dockerfile and docker-compose.yml for containerized deployment of the Pantheon MCP server, enabling easy setup in container orchestration environments.

### God CLI Tool
A command-line tool (`scripts/lib/god_cli/`) for managing god profiles from the terminal: creating new gods via templates (Jinja2 templates for SOUL.md, persona.md, config.yaml, god.yaml, harness.yaml, memory.md, journal, INDEX.md), validating god configurations, and maintaining the god registry.

---

## Inter-God Communication

### Inter-God Messaging System
A file-based message bus that enables gods to communicate asynchronously. Each god has an inbox directory at `~/pantheon/gods/messages/<god_name>/` where other gods can leave structured JSON messages. Supports six message types: report, request, notification, data, alert, and handoff. Messages include priority levels, thread IDs, and payload fields. This is the backbone of multi-agent collaboration — gods can delegate tasks, share information, and coordinate without needing to be in the same session.

### Handoff Manifest System
A signed, cryptographically-sealed handoff manifest that ensures clean transitions when one god passes a task to another. Captures the source god, target god, timestamp, state snapshot, and check results. Uses SHA-256 signing to bind the manifest, preventing tampering or confusion during multi-god workflows.

---

## Export & Distribution

### God Export Pipeline
Exports any god as a portable tar.gz bundle containing SOUL.md, persona.md, config.yaml, icon, selected skills, selected MCP configurations, and associated Codex folders. Supports two paths: the `pantheon-bundle` CLI or a profile-based fallback. Makes gods portable — shareable, backup-able, deployable to other Pantheon instances.

### God Summon Pipeline
Imports gods from the community repository at `github.com/Duskript/Pantheon-Summons`. Lists available gods, downloads their bundles, and provisions them locally. Can also create GitHub PRs to submit your own gods to the community repository — a full upstream contribution pipeline.

---

## Built-in Gods

### Hermes — Messenger & Operations Manager
The primary interface between the user and the Pantheon. Routes requests to the appropriate god, manages system operations, schedules, cron jobs, and serves as the message relay for all inter-god communication. Every user interaction flows through Hermes first.

### Hephaestus — God of the Forge
The collaborative builder, engineer, and architect. Handles tool building, code generation, project scaffolding, infrastructure planning, and program design. Available in multiple studio specializations: infrastructure-planning, program-design, and project-scoping.

### Clara — Prior Authorization Specialist (Potential)
A pre-built god template for healthcare prior authorization workflows, with a SOUL.md, persona.md, god.json, config.yaml template, and a provisioning script. Shows the potential for domain-specific gods in the Pantheon ecosystem.

---

## Gateway Plugins

### ichor-gates Plugin
Intercepts the Hermes Agent gateway message flow and injects Ichor context into every message. Connects the RALPH gate harness to real-time agent execution, ensuring deterministic guardrails are enforced on every tool call during a session.

### pantheon Plugin
Pantheon-specific gateway hooks that provide multi-god routing, session management, and Pantheon integration points. 33KB of gateway integration code that makes the Hermes Agent runtime Pantheon-aware.

### pantheon-shared-facts Plugin
Tracks shared facts and context across all gods. Ensures that knowledge discovered by one god is available to others, maintaining a consistent view of facts across the entire Pantheon.

### hermes-achievements Plugin
A binary plugin that implements an achievement/trophy system for the Hermes Agent. Gamifies agent usage with unlockable achievements.

### rtk-rewrite Plugin
A binary plugin for RTK (Real-Time Knowledge) prompt rewriting. Modifies prompts at the gateway level to inject relevant context before they reach the language model.

---

## MCP Servers

### Pantheon MCP (Internal)
The internal MCP server at `http://127.0.0.1:8010/mcp` that serves the entire Pantheon tool suite: Athenaeum (search, walk, read, write), Ichor (health, retrieve, store, forget, brief, graph_query), god roster, Hades reports, skill execution, and inter-god messaging.

### Filesystem MCP
Standard Filesystem MCP server providing file read, write, search, and directory listing capabilities to all gods. Each god's config.yaml can configure which directories are accessible.

### GitHub MCP
GitHub integration MCP server providing repository management, issue tracking, pull request operations, code search, and file management. Enables gods to interact with GitHub directly from conversations.

### Playwright MCP (Browser Automation)
Browser automation MCP server powered by Playwright. Provides web navigation, clicking, typing, screenshots, form filling, and network request inspection. Enables gods to automate web-based tasks and scrape information from websites.

### Composio MCP (500+ App Integrations)
External service connector providing access to 500+ third-party app integrations including Gmail, Google Calendar, Google Drive, Google Sheets, Slack, Notion, GitHub, Jira, Linear, and many more. The primary way gods interact with external services.

---

## Pre-installed Skills

### hermes-dojo
A skill that implements a continuous improvement loop: analyze current behavior, identify weaknesses, propose adjustments, apply changes, and verify results. Used by the Ichor Forge and other self-improving components.

### pantheon-operations
System operations skill providing Pantheon management commands: status checks, service control, health monitoring, and operational reporting.

### pantheon-bridge
Inter-god communication bridge skill that facilitates message passing, task delegation, and handoff coordination between gods.

### pantheon-digest-generation
Shared context digest generation skill that compiles cross-god decisions, active tasks, and knowledge updates into the periodic DIGEST.md file.

### pantheon-god-configuration
God configuration management skill for updating god settings, adjusting model assignments, modifying tool sets, and managing MCP server configurations per god.

### athenaeum-maintenance
Knowledge base maintenance skill for organizing Codexes, managing INDEX.md files, performing semantic re-embedding, and cleaning up stale content.

### ichor-harness-engineering
Gate harness engineering skill for analyzing gate performance, tuning RALPH phase detection, adjusting intervention thresholds, and maintaining the gate middleware.

### Composio Automations
Skill for configuring and orchestrating multi-step automations across the 500+ Composio-connected apps.

---

## Pantheon SDK & Developer Tools

### Pantheon SDK (`pantheon_sdk.py`)
A Python SDK for programmatic interaction with the Pantheon system. Provides client libraries for god management, Athenaeum operations, Ichor memory access, and inter-god messaging. Enables external tools and scripts to integrate with Pantheon.

### Claude Import Bridge
A bridge for importing Claude AI project configurations into the Pantheon god system. Supports migrating conversation archives, project knowledge, and custom instructions from Claude projects into Pantheon format.

### God CLI Tooling
A comprehensive god command-line interface with Jinja2 templates for scaffolding new gods, validation utilities for god configurations, a registry management system, and defaults management. Makes god creation and management possible entirely from the terminal.

---

## Developer Infrastructure

### Test Suite
A pytest-based test suite covering: API endpoints (test_api.py), Demeter file watcher (test_demeter.py), harness loader (test_harness_loader.py), Hestia health checks (test_hestia.py), Kronos logging (test_kronos.py), Mnemosyne client (test_mnemosyne.py), Sanctuary config (test_sanctuary_config.py), Vault writer (test_vault_writer.py), and Athenaeum triage. Includes fixture harness files for test scenarios.

### Requirements & Docker
A requirements.txt for Python dependencies and a Dockerfile for containerized deployment of the Pantheon MCP server, enabling reproducible environments and container-based deployment.
