# Project Ideas

A living collection of things to build — for Cyber's Pantheon system, for work, and whatever else comes to mind.

---

## 🏗️ Pantheon — Core Architecture

### Pantheon Plugin / God SDK
- **Status:** planning
- **Tags:** #pantheon-core #architecture #sdk #plugin-system #packaging
- **Added:** 2026-04-29
- **Notes:** ⚡ **Foundational architecture.** A standard way to package gods as pluggable extensions to Pantheon. Each god is a self-contained bundle: agent config, personality prompts, knowledge base, tools, skills, and supporting files.

  **Key design decisions:**
  - **Hephaestus** is the one core god bundled with Pantheon by default — the foundation god
  - All other gods are external: created by Cyber or obtained from trusted sources
  - **Public god repository** — when Pantheon goes public, a registry/directory of gods Cyber has made and wants to share
  - **Apollo is proprietary** — a closed, select-access god engine, NOT shared publicly. Exclusive to trusted/selected people
  - Each god has a manifest (`god.yaml`) with metadata, triggers, dependencies
  - Install flow: `pantheon install god-name`
  - Versioning, dependency management between gods
  - Gods can share tools/knowledge with each other

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

## 💼 Work Projects

### Jira Desktop Notification App
- **Status:** idea
- **Tags:** #work #jira #tool #productivity
- **Added:** 2026-04-29
- **Notes:** A lightweight desktop app that sits in the system tray and provides real-time Jira notifications (assigned tickets, mentions, status changes). Also needs a quick-submit feature — a popup or hotkey to quickly file a ticket with minimal friction (title, description, maybe a couple of fields). Could be built with Tauri (Rust + web frontend) or Electron, polling the Jira REST API.
