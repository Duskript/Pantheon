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

---

## 🚧 In Progress

*No features currently in progress.*

---

## 💡 Planned

### 4. God SDK — Phase 2: Build, Install, Uninstall

- **Status:** planned
- **Phase:** 2
- **Tags:** #pantheon-core #sdk #cli #packaging #distribution
- **Planned:** 2026-05-13
- **Description:** Extend the CLI with `pantheon god build`, `pantheon god install`, and `pantheon god uninstall`. Build packages a god + its bundled Codexes into a distributable tarball. Install extracts bundled Codexes to `~/athenaeum/` and scaffolds Codex-God-{Name} fresh per-user. Uninstall cleans up cleanly. Upgrade from argparse to Click/Typer for better subcommand nesting.

### God Distribution Hub (name TBD)

- **Status:** planned
- **Phase:** 2
- **Tags:** #pantheon-core #ecosystem #marketplace #community
- **Planned:** 2026-05-13
- **Description:** A central collection where people can submit custom Pantheon gods for approval and share them with others. Submission pipeline: dev builds god via SDK → submits → approval gate → published. Installation via `pantheon god install <name>` or WebUI with one click. Versioning, discovery, ratings. Requires Phase 2 CLI (build/install) to be solid first. WebUI dialog on export: "Submit to registry?".

---

## 🏛️ Core Architecture (always present, always evolving)

These aren't features you "ship" — they're the foundation everything runs on. Listed here because they're part of what makes Pantheon Pantheon.

| System | Description |
|--------|-------------|
| **Athenaeum** | Shared knowledge layer — ChromaDB vector store + filesystem Codexes + entity graph. Gods search it, Hades consolidates it, every Codex has a home. The memory that outlives any single session. |
| **Multi-God Architecture** | Domain-specific Hermes profiles, each with its own SOUL.md, persona, config, and MCP tool access. Gods are isolated but coordinated — shared context, notifications, and the Athenaeum bridge the gaps. |
| **Hades Nightly Consolidation** | Automated pipeline: health check → distillation → archive → shared context sweep → entity extraction → suggestions → heartbeat → report. Keeps the Athenaeum clean and the system running. |
| **God Notifications** | Push-based alert system via `god-notify` script + WebUI bell + PWA push. Gods ping you when tasks complete, errors happen, or your input is needed. Replaced the old inbox-polling pattern. |
