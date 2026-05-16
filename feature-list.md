# Pantheon Feature List

*A running inventory of every public-facing feature Pantheon ships. Internal plumbing and one-time tasks don't belong here — only things that set Pantheon apart.*

---

## ✅ Completed

### 1. Shared Context 24h Buffer

- **Status:** completed
- **Phase:** 1
- **Tags:** #pantheon-core #communication #context #gods
- **Completed:** 2026-05-12
- **Description:** A `~/pantheon/shared/` directory that all gods read/write as a 24-hour slip buffer. Active tasks, decisions, and athenaeum writes get logged here during the day. Hades sweeps entries >24h old into the Athenaeum for permanent storage. Gods search this directory when the user references cross-session or cross-god work — pull-only, no auto-injection.
- **Components:**
  - `active/` — Current tasks, updated in place
  - `decisions/` — Append-only decision log by date
  - `athenaeum-writes.md` — Append-only path log for Athenaeum file writes
  - `archive/` — Completed/stale active tasks moved here
  - Hades nightly sweep integration (Phase 4)

### 2. Soul Forge — Conversational God Creation

- **Status:** completed
- **Phase:** 1
- **Tags:** #pantheon-core #forge #soul #ui
- **Completed:** 2026-05-13
- **Description:** A chat popup in the WebUI where you talk to Hephaestus to conversationally create a new god's SOUL.md. The LLM interviews you about domain, voice, boundaries, and operational needs, then produces a full SOUL.md. On accept, the backend automatically scaffolds the complete god profile (config, persona, Codex, registries) via the God SDK CLI. No manual setup required.

### 3. God SDK — Phase 1 CLI

- **Status:** completed
- **Phase:** 1
- **Tags:** #pantheon-core #sdk #cli #scaffolding
- **Completed:** 2026-05-13
- **Description:** Two CLI commands for creating and maintaining Pantheon gods:
  - `pantheon init <name> --domain <domain>` — Full god scaffold in one command. Creates profile, SOUL.md, persona.md, config.yaml (~50 lines minimal), god.yaml + harness.yaml, Codex-God-{Name} with INDEX.md + memory.md + journal/, and updates both registries. Supports `--dry-run`, `--force`, `--json`, `--codexes`, `--no-suggest-codexes`. Domain-to-codex mapping auto-attaches reference knowledge (e.g. creative domain → Codex-Apollo, health → Codex-Medica, forge → Codex-Forge).
  - `pantheon validate [name]` — 8 checks per god validating SOUL.md sections, persona, config.yaml MCP/toolsets, Codex structure, registries, and manifest. Validates one god or ALL gods. Supports `--json` output for UI integration.

### 4. Athenaeum Web Clipper — Browser Bookmarklet + PWA Share Target

- **Status:** completed
- **Phase:** 1
- **Tags:** #pantheon-core #athenaeum #web-clipper #pwa #utilities
- **Completed:** 2026-05-14
- **Description:** A complete "save anything to the Athenaeum" system accessible from Settings → Utilities in the WebUI:
  - **Bookmarklet:** Drag a button from Settings → Utilities to your browser's bookmarks bar. Click it on any page → saves URL, title, and highlighted text to the Athenaeum inbox
  - **PWA Share Target:** Install Pantheon as a PWA on mobile → use the OS share sheet → "Pantheon" appears as a share target. Saves links directly to the inbox
  - **Server URL config:** Overridable for Tailscale/custom domains
  - **Inbox pipeline:** `~/athenaeum/inbox/` receives clips → `process-inbox.py` fetches readable content, classifies into the right Codex (by domain), and files it
  - **Multiple delivery channels:** Works with Syncthing too — any `.md` file dropped in `inbox/` gets processed identically

### 5. Summon God Repository — Two-Way God Marketplace

- **Status:** completed
- **Phase:** 1
- **Tags:** #pantheon-core #marketplace #ecosystem #gods #community
- **Completed:** 2026-05-14
- **Description:** A full god marketplace powered by the `Duskript/Pantheon-Summons` GitHub repo. Browse, install, and publish Pantheon gods without leaving the WebUI:
  - **Browse:** `GET /api/gods/summon/list` — proxies GitHub Contents API to list all available gods with their SOUL.md, icons, and repo stars
  - **Summon (Install):** `POST /api/gods/summon` — pulls a god's complete profile from the Summons repo and scaffolds it locally (config, persona, Codex, registries)
  - **Submit:** `POST /api/gods/{name}/submit-to-summons` — forks the Summons repo, creates a branch, commits your god's bundle, opens a PR. Turns any local god into a published community god
  - **WebUI Drawer:** Summon drawer in the right panel shows available gods with cards, SOUL preview, and one-click install

### 6. ACI (Agent-Computer Interface) — 600+ Pre-Built MCP Integrations

- **Status:** pre-installed
- **Phase:** 1
- **Tags:** #pantheon-core #mcp #integrations #saas #ecosystem
- **Installed:** 2026-05-14
- **Description:** ACI is an open-source platform that wraps 600+ SaaS APIs (Gmail, Slack, GitHub, Notion, Vercel, Supabase, Stripe, Sentry, Brave Search, etc.) into MCP tools accessible directly from your Hermes agent:
  - **Unified Server** (default): Uses only 3 meta-tools (`ACI_SEARCH_FUNCTIONS`, `ACI_EXECUTE_FUNCTION`, `ACI_SEARCH_DOCS`) — near-zero context bloat. The agent searches for tools by intent and only loads the schema it needs at call time.
  - **Apps Server**: Exposes every function of specific apps as individual MCP tools for known workflows
  - **VibeOps Server**: DevOps-focused tools for Vercel, GitLab, Supabase, Sentry automation
  - **Integration:** Added as stdio MCP server in `config.yaml` under `mcp_servers.aci`. Zero Pantheon code changes — Hermes' native MCP client handles discovery automatically.

### 7. Hermes Dojo — Agent Self-Improvement Pipeline

- **Status:** pre-installed
- **Phase:** 1
- **Tags:** #pantheon-core #dojo #self-improvement #skills #ml
- **Installed:** 2026-05-14
- **Description:** Hermes Dojo is a meta-agent that closes the feedback loop on agent performance by reading session logs, finding recurring failures, and auto-patching the skills behind them:
  - **Monitor** — Reads `state.db` and classifies tool errors, retry loops, user corrections, and skill gaps via regex patterns
  - **Analyzer** — Maps failing tools to existing skills, ranks weaknesses by error rate × frequency
  - **Fixer** — Patches SKILL.md files, creates new skills from templates, runs GEPA evolution on weak skills
  - **Tracker** — Persists metrics snapshots with 90-day history, sparkline visualization
  - **Reporter** — Telegram/CLI morning digest with deltas and improvement summaries
  - **Integration:** Installed as a `/dojo` Hermes skill at `~/.hermes/skills/hermes-dojo/`. Run `/dojo auto` for the overnight improvement cycle.

---

## 🚧 In Progress

*No features currently in progress.*

---

## 💡 Planned

### God SDK — Phase 2: Build, Install, Uninstall

- **Status:** planned
- **Phase:** 2
- **Tags:** #pantheon-core #sdk #cli #packaging #distribution
- **Planned:** 2026-05-13
- **Description:** Extend the CLI with `pantheon god build`, `pantheon god install`, and `pantheon god uninstall`. Build packages a god + its bundled Codexes into a distributable tarball. Install extracts bundled Codexes to `~/athenaeum/` and scaffolds Codex-God-{Name} fresh per-user. Uninstall cleans up cleanly. Upgrade from argparse to Click/Typer for better subcommand nesting.

---

## 🏛️ Core Architecture (always present, always evolving)

These aren't features you "ship" — they're the foundation everything runs on. Listed here because they're part of what makes Pantheon Pantheon.

| System | Description |
|--------|-------------|
| **Athenaeum** | Shared knowledge layer — ChromaDB vector store + filesystem Codexes + entity graph. Gods search it, Hades consolidates it, every Codex has a home. The memory that outlives any single session. |
| **Multi-God Architecture** | Domain-specific Hermes profiles, each with its own SOUL.md, persona, config, and MCP tool access. Gods are isolated but coordinated — shared context, notifications, and the Athenaeum bridge the gaps. |
| **Hades Nightly Consolidation** | Automated pipeline: health check → distillation → archive → shared context sweep → entity extraction → suggestions → heartbeat → report. Keeps the Athenaeum clean and the system running. |
| **God Notifications** | Push-based alert system via `god-notify` script + WebUI bell + PWA push. Gods ping you when tasks complete, errors happen, or your input is needed. Replaced the old inbox-polling pattern. |
