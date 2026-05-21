# Pantheon System Architecture

> **Canonical reference — Last updated: 2026-05-20**
> Maps every Pantheon component, what it touches, what depends on it, and where it diverges from a stock Hermes Agent installation.
>
> Keep this updated as architecture changes.

---

## 1. High-Level Overview

Pantheon is a layer of custom infrastructure on top of **Hermes Agent** (the base LLM agent system). It adds:
- A **god profile system** — multi-agent identities with per-god configs, skills, sessions, and memory
- A **web management UI** — browser interface for managing gods, summoning/exporting, health monitoring
- A **knowledge management system** (Athenaeum + Hades + Ichor) — structured, persistent, graph-aware memory
- An **export/summon pipeline** — god distribution via GitHub PRs against `Duskript/Pantheon-Summons`
- **Gateway plugins** — runtime hooks that extend agent behavior (ichor gates, shared facts, etc.)

### Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    TAILSCALE (pantheon)                      │
│  serve / → :8787 (prod)  /dev → :8788  /dashboard → :9119   │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌──────────────────────────────┐  │
│  │  Hermes Web UI      │  │  Hermes Dashboard            │  │
│  │  (prod :8787)       │  │  (dev :8788)  (dashboard)    │  │
│  │  server.py + api/   │  │                               │  │
│  └─────────┬───────────┘  └──────────┬───────────────────┘  │
│            │                          │                       │
│            ▼                          ▼                       │
│  ┌────────────────────────────────────────────────────┐      │
│  │              Hermes Agent Runtime                   │      │
│  │  ~/.hermes/  (config.yaml, profiles, skills)        │      │
│  │  Gateway + Plugins + MCP Servers                    │      │
│  └────────┬──────────────┬──────────────┬──────────────┘      │
│           │              │              │                      │
│           ▼              ▼              ▼                      │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐        │
│  │ Athenaeum  │  │ Ichor      │  │ Legacy YAMLs     │        │
│  │ ~/athenaeum│  │ Memory     │  │ (dead references)│        │
│  │ Codexes    │  │ System     │  │ harnesses/*.yaml │        │
│  └────────────┘  └────────────┘  │ gods.yaml        │        │
│                                  └──────────────────┘        │
└─────────────────────────────────────────────────────────────┘
```

### File System Layout

```
~/
├── .hermes/                          ← Hermes Agent home (base system)
│   ├── config.yaml                   ← Agent configuration
│   ├── SOUL.md                       ← Hermes identity
│   ├── persona.md                    ← Hermes behavior
│   ├── icon.png                      ← Hermes icon
│   ├── god.json                      ← Hermes metadata
│   ├── skills/                       ← Global skill repository (133 skills)
│   ├── profiles/                     ← God profiles (the core god system)
│   │   ├── hermes/                   ← Hermes profile
│   │   ├── apollo/                   ← Apollo profile
│   │   ├── thoth/                    ← Thoth profile
│   │   ├── marvin/                   ← Marvin profile
│   │   ├── caduceus/                 ← Caduceus profile
│   │   ├── hephaestus/               ← Hephaestus profile
│   │   ├── cachyos/                  ← CachyOS Bridge (restricted)
│   │   └── .../                      ← Each god has:
│   │       ├── SOUL.md               ←   Identity/personality
│   │       ├── persona.md            ←   Behavior guide
│   │       ├── config.yaml           ←   Model, toolsets, MCP, provider
│   │       ├── god.json              ←   Metadata (display_name, icon, color, domain)
│   │       ├── icon.png              ←   Profile avatar
│   │       ├── skills/               ←   Skill files (populated on install)
│   │       ├── sessions/             ←   Session transcripts (runtime)
│   │       ├── memories/             ←   Cross-session memory (runtime)
│   │       ├── plans/, cron/         ←   Plans and cron jobs (runtime)
│   │       ├── logs/, bin/           ←   Runtime artifacts
│   │       ├── platforms/            ←   Platform connection state
│   │       ├── skins/                ←   UI skins
│   │       ├── webui_state/          ←   UI state cache
│   │       ├── workspace/            ←   God's workspace
│   │       ├── state.db              ←   Session/state SQLite DB
│   │       └── auth.json             ←   Authentication
│   ├── cron/                         ← Scheduled job definitions
│   ├── plugins/                      ← Gateway plugins
│   │   ├── ichor-gates/              ←   Ichor nudge integration
│   │   ├── pantheon/                 ←   Pantheon-specific hooks
│   │   ├── pantheon-shared-facts/    ←   Shared fact tracking
│   │   ├── hermes-achievements/      ←   Achievement system
│   │   └── rtk-rewrite/              ←   RTK prompt rewrite
│   ├── ichor/                        ← Ichor memory backend data
│   ├── sessions/                     ← Global session store
│   ├── memories/                     ← Global memory store
│   ├── hooks/                        ← Event hooks
│   ├── logs/                         ← Hermes agent logs
│   └── ...                           ← Other standard Hermes dirs
│
├── pantheon/                         ← Pantheon custom code
│   ├── webui/                        ← Web UI server
│   │   ├── server.py                 ←   HTTP server (dev mode)
│   │   ├── hermes-ui.html            ←   React frontend (full Pantheon UI)
│   │   ├── static/
│   │   │   ├── index.html            ←   Vanilla JS frontend (fallback)
│   │   │   ├── god-management.js     ←   God management panel (Summon/Export/Edit/Exile)
│   │   │   ├── forge-wizard.js       ←   God creation wizard
│   │   │   ├── god-picker.js         ←   God sidebar grid
│   │   │   └── ...                   ←   Other static assets
│   │   └── api/
│   │       ├── routes.py             ←   ALL API routing (455KB, 11K+ lines)
│   │       ├── profiles.py           ←   Profile management
│   │       ├── soul_forge.py         ←   God creation forge
│   │       ├── athenaeum.py          ←   Knowledge base management
│   │       ├── config.py             ←   Configuration (173KB)
│   │       ├── providers.py          ←   Provider/model listing
│   │       ├── models.py             ←   Model management
│   │       ├── streaming.py          ←   SSE streaming (172KB)
│   │       ├── system_health.py      ←   Health monitoring
│   │       ├── mcp_services.py       ←   MCP service management
│   │       ├── kanban_bridge.py      ←   Kanban integration
│   │       ├── auth.py               ←   Authentication
│   │       ├── helpers.py            ←   Shared utilities
│   │       ├── workspace.py          ←   Workspace management
│   │       ├── onboarding.py         ←   Onboarding flow
│   │       ├── upload.py             ←   File upload handling
│   │       ├── oauth.py              ←   OAuth flows
│   │       └── ...                   ←   Other API modules
│   │
│   ├── harnesses/                    ← ☠️ LEGACY — 12 YAML files, zero code references
│   ├── gods/
│   │   ├── gods.yaml                 ← ☠️ LEGACY — superseded by profile god.json
│   │   ├── GOD-FORGING-GUIDE.md      ← Documentation
│   │   └── manifest-reference.md     ← Documentation
│   ├── planning/
│   │   └── ARCHITECTURE.md           ← ⚠️ PARTIALLY STALE — God/Studio/Harness model
│   └── shared/
│       ├── DIGEST.md                 ← Cross-god shared context (generated by cron)
│       ├── decisions/                ← Architectural Decision Records
│       └── archive/                  ← Archived docs
│
└── athenaeum/                        ← Knowledge base (Codexes)
    ├── Codex-Apollo/                 ← Apollo domain knowledge
    ├── Codex-God-thoth/              ← Thoth domain knowledge
    ├── Codex-God-caduceus/           ← Caduceus domain knowledge
    ├── Codex-God-Hephaestus/         ← Hephaestus domain knowledge
    ├── Codex-Forge/                  ← Technical/code knowledge
    ├── Codex-Pantheon/               ← Pantheon system knowledge
    ├── Codex-General/                ← General knowledge
    ├── Codex-Infrastructure/         ← Infrastructure knowledge
    ├── Codex-User/                   ← User profile knowledge
    └── ...                           ← Other codexes
```

---

## 2. Component Dependency Graph

Each component listed with: what files/locations it uses, what depends on it, and notes.

### 2.1 Hermes Agent Base System

**Location:** `~/.hermes/`
**Config:** `~/.hermes/config.yaml`
**Entry points:** Hermes CLI (`hermes`), Gateway, WebUI API

| What it owns | What reads it | What writes it |
|---|---|---|
| `config.yaml` | All Hermes subsystems (gateway, plugins, profiles, webui) | Manual edits, `hermes config set` |
| Global `skills/` | All profiles via `skills` toolset | Skill curator, `hermes skill create` |
| Global `sessions/` | WebUI on session page load | Gateway on session end |
| `cron/` (jobs.json) | Hermes scheduler | `hermes cron` CLI |
| `plugins/` | Gateway at startup | Manual installs |

### 2.2 God Profiles System

**Source:** `~/pantheon/webui/api/profiles.py` (43KB)
**Storage:** `~/.hermes/profiles/<god>/`

**Dependencies:**
- Reads: `~/.hermes/config.yaml` (for profile root), `god.json`, `config.yaml` per god
- Writes: profile directories via `create_profile_api()` → `hermes_cli.profiles.create_profile()`
- Depended on by: Soul Forge, God Management UI, Export/Summon, Health monitoring

**Key functions:**
- `_resolve_profile_home_for_name(name)` → maps god name to `~/.hermes/profiles/<name>/`
- `_read_god_metadata(profile_dir)` → reads `god.json`
- `_write_god_metadata(profile_dir, metadata)` → writes `god.json`
- `create_profile_api(name)` → delegates to `hermes_cli.profiles.create_profile` for scaffolding
- `list_profiles_api()` → returns all profiles with gateway status, model, provider, skill count

**Key API routes (in routes.py):**
- `GET /api/profiles` → list with status
- `GET /api/gods` → list all gods
- `GET /api/gods/{name}` → individual god info
- `POST /api/gods/{name}` → start/stop/set_model
- `GET /api/gods/{name}/icon` → serve icon.png
- `GET /api/gods/{name}/skills` → profile + global skills
- `GET /api/gods/{name}/mcp-servers` → MCP config from config.yaml
- `GET /api/gods/{name}/codex-folders` → associated Codex-God-{name} or Codex-{Name}

**Runtime auto-creates for each god:**
- Directories: `skills/`, `sessions/`, `memories/`, `plans/`, `cron/`, `logs/`, `bin/`, `skins/`, `platforms/`, `workspace/`, `webui_state/`
- Files: `config.yaml` (with defaults), `auth.json`, `state.db`

### 2.3 Soul Forge (God Creation)

**Source:** `~/pantheon/webui/api/soul_forge.py` (13KB)
**Caller:** `POST /api/gods/{name}/forge` in routes.py

**Creates:**
- `SOUL.md` — the crafted soul document
- `god.json` — metadata (display_name, icon, color, domain)

**Does NOT create:**
- ❌ Skills — skills/ dir left empty
- ❌ Codex — no Codex-God-{name} initialized
- ❌ persona.md — not generated
- ❌ config.yaml defaults — not seeded
- ❌ MCP config — not set up

**Hook points:**
- Calls `hermes_cli.profiles.create_profile()` for scaffolding (may or may not work)
- Called from: God Management UI → Forge Wizard (`static/forge-wizard.js`)

### 2.4 Athenaeum (Knowledge Codexes)

**Source:** `~/pantheon/webui/api/athenaeum.py` (14KB)
**Storage:** `~/athenaeum/`

**Structure:**
```
~/athenaeum/
├── Codex-{DomainName}/           ← Domain-level codex (Apollo, Forge, Pantheon...)
│   ├── INDEX.md                  ← Codex index
│   ├── sessions/                 ← Session transcripts
│   ├── distilled/                ← Compiled knowledge
│   └── knowledge/                ← Reference articles
├── Codex-God-{godname}/          ← God-specific codex (thoth, caduceus...)
│   ├── research/                 ← God-specific knowledge
│   └── memory.md                 ← God-specific memory
└── .chromadb/                    ← Vector embeddings
```

**API routes:**
- `GET /api/athenaeum/list` → list all codexes
- `GET /api/athenaeum/walk?path=INDEX.md` → navigate tree
- `GET /api/athenaeum/read?path=...` → read file
- `GET /api/athenaeum/search?q=...` → semantic search

**Hades nightly** — consolidation pipeline:
- Runs daily (cron)
- Compiles sessions into distilled knowledge
- Updates INDEX.md files
- Archives stale sessions

### 2.5 Ichor Memory System

**Sources:**
- `~/.hermes/ichor/` — backend storage
- `~/.hermes/plugins/ichor-gates/` — gateway integration plugin
- `ichor` tool suite built into Hermes Agent

**Architecture:**
```
Ichor Memory — Multi-Backend Fused Search
│
├── FTS5 (SQLite)      — Keyword search, events, facts
├── ChromaDB            — Semantic vector search (in ~/athenaeum/.chromadb/)
├── Graph DB            — Entity-relationship graph
└── Events              — Structured event log
```

**API routes (via MCP `pantheon` server at :8010):**
- `ichor_health()` — check all backend status
- `ichor_retrieve(query)` — fused search across all backends
- `ichor_store(key, content, category)` — store to appropriate backend
- `ichor_forget(key)` — delete item
- `ichor_brief(god_name)` — ranked context brief for a god
- `ichor_graph_query(query)` — natural language graph query

**Known divergence from stock Hermes:**
- User is considering wiring Ichor store to the **memory nudge** (an LLM call on session end) instead of the compaction pipeline. This would be a significant customization.
- The `ichor-gates` plugin intercepts gateway message flow to inject Ichor context.

### 2.6 Export / Summon Pipeline

**Export:**
- `POST /api/gods/{name}/export` in routes.py (~line 5215)
- Accepts: `selected_skills[]`, `selected_mcp[]`, `codex_folders[]`
- Returns: tar.gz with `god-{name}/` containing SOUL.md, persona.md, config, icon, selected skills, selected MCP configs, selected codexes
- Two paths: `pantheon-bundle` CLI (if available) or profile-based fallback
- Tarball structure:
  ```
  god-{name}/
  ├── SOUL.md
  ├── persona.md
  ├── config.yaml
  ├── profles.json (if exists)
  ├── icon.png
  ├── mcp.json (selected MCP servers)
  ├── skills/
  │   ├── {skill1}/
  │   └── {skill2}/
  └── codex/
      └── Codex-{Name}/
  ```

**Summon:**
- `GET /api/gods/summon/list` → available gods from `Duskript/Pantheon-Summons` repo
- `POST /api/gods/summon` → create PR against summon repo with god bundle
- Routes: lines ~5520-5700 in routes.py

**Repo:** `https://github.com/Duskript/Pantheon-Summons`
**Current gods in repo:** `marvin/` (SOUL.md + icon.png only, no metadata.json yet)

### 2.7 Gateway Plugins

**Location:** `~/.hermes/plugins/`

| Plugin | Files | What it does |
|---|---|---|
| `ichor-gates/` | `__init__.py` (9KB), `plugin.yaml` | Intercepts gateway message flow, injects Ichor context per message |
| `pantheon/` | `__init__.py` (33KB), `plugin.yaml` | Pantheon-specific gateway hooks (routing, multi-god) |
| `pantheon-shared-facts/` | `__init__.py` (14KB), `plugin.yaml` | Tracks shared facts across gods |
| `hermes-achievements/` | (binary plugin) | Achievement/trophy system |
| `rtk-rewrite/` | (binary plugin) | RTK prompt rewriting |

**Plugin loading:** Gateway loads plugins from `~/.hermes/plugins/` at startup. Each must have `plugin.yaml` + `__init__.py` with `setup()` hook.

### 2.8 WebUI / Frontend

**Two frontends:**

| Version | File | Route | Notes |
|---|---|---|---|
| React | `hermes-ui.html` | Normal (controlled by `HERMES_WEBUI_INDEX`) | Full Pantheon UI with glassmorphic design |
| Vanilla JS | `static/index.html` | Fallback | Simpler, used for dev work |

**Key JS modules:**
- `god-management.js` — God management panel (Summon/Export modal/Edit/Exile), 1167+ lines IIFE
- `forge-wizard.js` — God creation wizard with icon/color picker
- `god-picker.js` — God sidebar selection grid
- `header-overflow.js` — Header menu with god management entry
- `god-rail.js` — God sidebar rail

**Server config:**
- Prod: systemd service, port 8787
- Dev: manual `python3 server.py`, port 8788
- Dashboard: separate process, port 9119

### 2.9 MCP Services

**Internal MCP server:** `pantheon` at `http://127.0.0.1:8010/mcp`
  - Serves: Athenaeum (search, walk, read, write), Ichor (health, retrieve, store, forget, brief, graph_query), God list, Hades reports, Skill info/run, Messaging
  - Configured in each god's `config.yaml` under `mcp_servers:`

**External:** Composio MCP — primary external service connector

**MCP tool registration:** Tools defined in each god's config, served via Hermes Agent's native MCP client

---

## 3. Divergence Points — Where Pantheon ≠ Stock Hermes

These are the places where our customizations deviate from a standard Hermes Agent installation.

### 3.1 Profile System (HEAVY CUSTOMIZATION)
Stock Hermes has a flat profile system. Pantheon layers on:
- `god.json` metadata (display_name, icon, color, domain) — stock Hermes doesn't use this file
- `GET /api/gods/*` routes — entirely custom routing layer
- Soul Forge — custom god creation pipeline
- Export/Summon — custom god distribution pipeline

### 3.2 WebUI (HEAVY CUSTOMIZATION)
- `./pantheon/webui/` is a fork of the Hermes Web UI (nesquena)
- Custom frontend (React hermes-ui.html)
- Custom API modules (soul_forge, kanban_bridge, athenaeum, mcp_services)
- Routes.py is 455KB — FAR beyond stock Hermes Web UI

### 3.3 Ichor / Memory (MODERATE CUSTOMIZATION)
- Stock Hermes memory is simpler (FTS5 + ChromaDB)
- Pantheon adds Graph DB layer, structured events backend
- `ichor-gates` plugin is a Pantheon invention
- Memory nudge → Ichor integration is being considered (would be a Pantheon-only hook)

### 3.4 Athenaeum / Hades (PANTHEON-ORIGINAL)
- Entirely custom — not part of stock Hermes
- Codex system with per-god knowledge domains
- Hades nightly compilation pipeline
- WebUI API for browsing/searching

### 3.5 Gateway Plugins (MODERATE CUSTOMIZATION)
- `ichor-gates`, `pantheon`, `pantheon-shared-facts` are Pantheon-only
- Not part of any stock Hermes plugin catalog

---

## 4. Legacy / Dead Systems

These files remain on disk but are NOT referenced by any active code. They are safe to clean up once the architecture doc is established.

### 4.1 `~/pantheon/harnesses/*.yaml` (12 files)
- **Status:** ☠️ DEAD — zero references in routes.py, config.yaml, or any active code
- **Content:** Old god-role definitions (thoth-base.yaml, apollo-base.yaml, etc.)
- **Replaced by:** Per-god `config.yaml` in profile directories
- **Suggested cleanup:** Add deprecation header, then archive or delete

### 4.2 `~/pantheon/gods/gods.yaml`
- **Status:** ☠️ DEAD — zero references in routes.py
- **Content:** Lists all gods with display_name, role, description, capabilities, status
- **Replaced by:** Per-god `god.json` in profile directories + `GET /api/profiles` endpoint
- **Suggested cleanup:** Add deprecation header, then archive or delete

### 4.3 `~/pantheon/planning/ARCHITECTURE.md`
- **Status:** ⚠️ PARTIALLY STALE — describes the God/Studio/Harness conceptual model
- The harness model was never implemented as code — it was aspirational architecture
- `gods.yaml` was meant to be the registry; it's now dead
- Capital-R "Architecture" references may confuse vs THIS document

---

## 5. Deployment Architecture

```
                   TAILNET (tail164759.ts.net)
                          │
              ┌───────────┴───────────┐
              │   pantheon node        │
              │   100.68.106.59        │
              │   pantheon.tail164759  │
              │   .ts.net              │
              └───────────┬───────────┘
                          │
                          ▼
              ┌───────────────────────┐
              │   Tailscale Serve      │
              │   (port 443)           │
              ├───────────────────────┤
              │  /  → localhost:8787   │  ← Prod WebUI
              │  /dev → localhost:8788 │  ← Dev WebUI
              │  /dashboard → :9119    │  ← Dashboard
              └───────────────────────┘

Services:
  ┌── prod-webui ──┐  ┌── dev-webui ────┐  ┌── dashboard ──┐
  │  Port 8787      │  │  Port 8788      │  │  Port 9119    │
  │  systemd        │  │  manual start   │  │  -hermes flag  │
  │  Binds 127.0.0.1│  │  Binds 0.0.0.0  │  │               │
  └────────────────┘  └────────────────┘  └───────────────┘
```

### Dev Server
```bash
cd ~/pantheon/webui
HERMES_WEBUI_HOST=0.0.0.0 HERMES_WEBUI_PORT=8788 \
  HERMES_WEBUI_INDEX=hermes-ui.html python3 server.py
```

### Promote to Prod
Konan says "ship it" → swap to 8787. **Never swap without explicit OK.**

---

## 6. Known Pain Points & TODO

| Issue | Impact | Status |
|---|---|---|
| God forge doesn't seed skills/codex/config | New gods start incomplete | Needs fix |
| Codex naming inconsistency (`Codex-God-{name}` vs `Codex-{Name}`) | Export can't find codexes | Partially fixed |
| Legacy YAML files not marked as dead | Confuses newcomers | Needs cleanup |
| No `metadata.json` standard in summon repo | Export/Summon data incomplete | Not started |
| Ichor store may move from compaction to memory nudge | Architecture change pending | Under discussion |
| `routes.py` is 455KB monolithic file | Hard to maintain, hard to diff | Not addressed |
| No unit tests for god-management.js | UI changes risk regression | Not addressed |

---

## 7. File Reference Index

Quick lookup: which file should I read for what?

| I want to... | Read this file |
|---|---|
| Understand the full API surface | `~/pantheon/webui/api/routes.py` |
| Create a new god | `~/pantheon/webui/api/soul_forge.py` |
| Manage profiles/gods list | `~/pantheon/webui/api/profiles.py` |
| Browse the Athenaeum | `~/pantheon/webui/api/athenaeum.py` |
| Work on the God Management UI | `~/pantheon/webui/static/god-management.js` |
| Work on the Forge Wizard | `~/pantheon/webui/static/forge-wizard.js` |
| Configure a god's model/skills | `~/.hermes/profiles/<god>/config.yaml` |
| See what skills exist | `~/.hermes/skills/` or `GET /api/skills` |
| See what codexes exist | `~/athenaeum/` or `GET /api/athenaeum/list` |
| Understand base Hermes Agent | `~/.hermes/config.yaml` |
| See current shared decisions | `~/pantheon/shared/DIGEST.md` (cron-generated) |
| Configure Tailscale serve | `tailscale serve status` |
