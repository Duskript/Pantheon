# Pantheon Core — Package Scope

> Last updated: 2026-05-11
> Written for the Phase 5 README and installer build.
> Source: Direct decision with Konan.

## Philosophy

Pantheon Core ships just enough to run a Pantheon instance. Two gods (Hermes + Hephaestus), a WebUI with the Pantheon overlay, LiteLLM for unified model routing, and the background infrastructure (Athenaeum, MCP server, cron gods). Everything else is user-built.

---

## ✅ INCLUDED — What goes in the repo

### pantheon-core/
The Python package — ~4,300 lines across:
- `mcp_server.py` — MCP server exposing Athenaeum, messaging, god system, health, ChromaDB tools over HTTP/stdio
- `api.py` — Original FastAPI app (thin, endpoints used by legacy paths)
- `model_router.py` — Model selection and provider routing
- `harness/` — Harness YAML loader with extends resolution, schema validation, custom exceptions
- `sanctuary/` — Sanctuary config loader with dataclass models
- `vault/` — Session vault writer with ISO8601 timestamped files
- `gods/hestia.py` — Health checker (service pings for Ollama, ChromaDB, MCP server)
- `gods/hades.py` — Nightly consolidation (summarization, distillation, archival of Athenaeum content)
- `gods/demeter.py` — Cron scheduler + file watcher stubs
- `gods/kronos.py` — JSONL log pipeline writer
- `gods/graph_client.py` — Knowledge graph client for the Athenaeum
- `mnemosyne/` — ChromaDB client with lazy connect, partition scoping, query, embed_file
- `tests/` — 82 tests, all passing, fully isolated (no external deps for CI)
- `Dockerfile` — Container build
- `requirements.txt` — FastAPI, uvicorn, PyYAML, httpx, pytest, chromadb

### hermes-webui/ (the Pantheon fork of nesquena/hermes-webui)
The frontend, overhauled with Pantheon-specific additions:
- God naming layer (profile-based identity, god icons/colors in UI)
- Boon drawer — slide-out overlay, scoped by session, inline-toggle only for Android WebView compatibility
- Athenaeum API routes — read/write/search/walk the knowledge graph from the UI
- Forge API — god creation UI workflows
- God notifications — bell icon with PWA push support, god-notify endpoint
- MCP server panel in Settings — active servers and tool search
- Health popup — live system health (CPU/mem/disk) + Hermes/MCP/LiteLLM status + god runtime states
- Lucide SVG icons, themed to god profiles
- The rest of hermes-webui is standard CLI parity (chat, streaming, sessions, cron, skills, memory, workspace, kanban, settings, profiles, i18n, auth)

### scripts/
- `pantheon-install` — Fresh install entrypoint
- `pantheon-uninstall` — Clean removal
- `pantheon-upgrade` — Version upgrade
- `pantheon-bundle` — God marketplace export, called by WebUI Export Bundle
- `pantheon-import-claude` — Claude conversation import pipeline
- `pantheon-list-gods` — Registry query
- `init-athenaeum.sh` — Builds Athenaeum + Staging folder structure from scaffold
- `demeter-watch.py` — Background file watcher daemon
- `heartbeat.py` — Service heartbeat monitoring
- `the-fates.py` — Data lifecycle evaluation (nightly/weekly archival rules)
- `reembed-athenaeum.py` + `reembed.sh` — Vector re-embedding pass
- `spot-fix-embed.py` — Targeted vector repair
- `docker-compose.yml` — ollama + chromadb + pantheon-core services

### Litellm
Included as a managed service. Ships with `litellm-config.yaml` (model-list template) and auto-starts on install.
- Single proxy endpoint (port 4000) — all gods point here
- API key management in one place — no scattered env vars per model
- Can route to: local Ollama, OpenCode Go, OpenRouter, Anthropic, OpenAI, any OpenAI-compatible endpoint
- Installer configures the proxy + Hermes Agent integration

### harnesses/
Only the core gods ship:
- `hermes-base.yaml` — Hermes identity, inter-god routing, operations
- `hephaestus-base.yaml` — Hephaestus identity, build/design domain
- Plus the `god-template/` package with template harness YAML for new gods

### god-packages/
- `god-template/` — `god.yaml`, `harness.yaml`, `README.md` — the canonical god creation template
- `shared-skills/` — Skills shared across all gods (auto-compact-topic-shift, etc.)
- NOT included: `god-apollo/` (instance-specific)

### templates/god/
Shared Brain Protocol template for every new god:
- `memory.md` — Long-term memory file
- `journal/TEMPLATE.md` — Daily journal structure
- `SHARED_BRAIN_PROTOCOL.md` — Protocol spec for copy-paste into harness

### plugins/pantheon/
Hermes Agent plugin that connects the agent runtime to Pantheon:
- Demeter watcher + classifier + ingest pipeline
- Graph client for Athenaeum knowledge graph
- `plugin.yaml` — Plugin manifest

### planning/
Architecture and reference documents:
- PROJECT.md — What Pantheon Is (design philosophy, core principles)
- ROADMAP.md — Build phases (Phases 1–5)
- ARCHITECTURE.md — God / Studio / Harness model
- STACK.md — Hardware and software stack
- STATE.md — Build status (updated per release)
- COMMS.md — Communication protocol (Hermes, Iris, Kronos)
- KNOWLEDGE.md — Knowledge layer (Athenaeum, Codices, Mnemosyne)
- SANCTUARY.md — Sanctuary system (legacy, documented for understanding)
- WORKFLOWS.md — Workflow engine and node editor (Phase 3 target)
- RULES.md — Hard rules (non-negotiable across all phases)
- NAVIGATION.md — Athenaeum navigation protocol for gods
- MIGRATION.md — ORACLE vault migration reference (documented, not shipped)
- CORE-SCOPE.md — This file

### Other root files
- `pantheon-registry.yaml` — God registry (Hermes + Hephaestus + template)
- `LICENSE` + `NOTICE` — Duskript licensing
- `.env.example` — Template env vars
- `.gitignore`

---

## ❌ EXCLUDED — What does NOT ship

| Thing | Why |
|-------|-----|
| Migration scripts (`migrate-oracle-vault.sh`, `migrate-export.sh`, `migrate-restore.sh`) | One-time use per instance. Not framework. |
| Sanctuary YAML config files | Sanctuary model replaced by Hermes Agent profiles. Not used. |
| Apollo / Caduceus / Thoth / other god packages | Instance-specific gods. Only Hermes + Hephaestus in core. |
| Cron jobs (Briefing, Genre Lexicon, Artist Profiles, Dreamweaver, etc.) | Personal scheduling. Installer can create defaults but these are user-scoped. |
| `~/.hermes/config.yaml` | Personal provider config with API keys. | 
| `~/.hermes/profiles/*` | Per-god profile configs. Generated by installer. |
| Actual Athenaeum content | Codex-SKC, user knowledge files. Scaffold structure ships (`init-athenaeum.sh`), content does not. |
| `gods/messages/` | Runtime inter-god message inbox data. Ephemeral. |
| `.env` files | API keys, secrets. `.env.example` ships, `.env` does not. |

---

## Architecture diagram

```
┌─────────────────────────────────────────────────┐
│               Pantheon Instance                  │
│                                                   │
│  ┌──────────┐   ┌──────────┐                      │
│  │  Hermes   │   │Hephaestus│    (god profiles)    │
│  │  Agent    │   │  Agent   │                      │
│  └────┬─────┘   └────┬─────┘                      │
│       └──────┬───────┘                            │
│              │ MCP tools                           │
│     ┌────────▼────────┐                           │
│     │  MCP Server     │  pantheon-core/mcp_server  │
│     │  (port 8010)    │                           │
│     └────────┬────────┘                           │
│              │                                     │
│  ┌───────────┼───────────────┐                     │
│  │ Athenaeum │  Background   │                     │
│  │ Knowledge │  Gods         │                     │
│  │ Graph     │  (Hestia,     │                     │
│  │ ChromaDB  │   Demeter,    │                     │
│  │           │   Hades,      │                     │
│  │           │   Kronos,     │                     │
│  │           │   Fates)      │                     │
│  └───────────┴───────────────┘                     │
│                                                    │
│  ┌──────────────┐   ┌──────────────┐              │
│  │ Hermes WebUI │   │   LiteLLM    │              │
│  │ (Pantheon    │   │   Proxy      │              │
│  │  fork)       │   │   (port 4000)│              │
│  └──────────────┘   └──────┬───────┘              │
│                            │ model routing          │
│                     ┌──────▼──────┐                │
│                     │  Ollama +   │                │
│                     │   Providers │                │
│                     └─────────────┘                │
└─────────────────────────────────────────────────┘
```
