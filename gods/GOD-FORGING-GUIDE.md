# God Forging Guide

Hephaestus' reference for creating new gods in the Pantheon.

**Version:** 1.6.0
**Last Updated:** 2026-05-01
**Maintainer:** Hephaestus — I update this document whenever the Pantheon skeleton changes or a new pattern emerges from forging.

---

## Changelog

| Date | Version | What Changed | Why |
|------|---------|-------------|-----|
| 2026-04-30 | 1.0.0 | Initial creation | Foundation document for god creation process |
| 2026-04-30 | 1.1.0 | Added God SDK section + CLI tool reference | Phase 1 of God SDK complete — install, uninstall, list, upgrade |
| 2026-04-30 | 1.2.0 | Added pantheon-export | God export for transfer between systems |
| 2026-04-30 | 1.3.0 | Added Claude import pipeline + 4 new Codices | Claude.ai export ingestion, Apollo/User/Work/Claude Codices |
| 2026-05-01 | 1.4.0 | Added MCP Inter-God Bus — MCP server config, harness MCP tool awareness, step 4 forge update | Pantheon MCP server built — any MCP client (Hermes, AionUi, Claude Code) connects |
| 2026-05-01 | 1.5.0 | Added heartbeat system — The Fates monitor, Hestia health checks, mandatory heartbeat step | Every scheduled subsystem now tracked; Fates alerts Hermes if anything stops running |
| 2026-05-01 | 1.6.0 | Added MCP skills hub (skill_list/info/run tools), shared skills directory, Template Synchronization Protocol | Every new god now has shared skills access; template drift eliminated |

---

## Core Systems (Required for Any Install)

For the Pantheon to function, these systems must be present:

| System | Purpose | Critical for |
|--------|---------|-------------|
| **Athenaeum** | File-based knowledge store (7+ Codices) | All gods — their domain knowledge lives here |
| **Mnemosyne** | ChromaDB vector store with semantic search | Gods that need context retrieval |
| **Demeter** | Ingestion pipeline + file watcher | Keeping the Athenaeum populated |
| **GraphClient** | SQLite entity relationship graph | Cross-god context linking |
| **Hades** | Nightly consolidation, health checks, distillation | System integrity over time |
| **God Bridge** | Shared filesystem inbox/outbox under `gods/messages/` | Inter-god communication — file-based |
| **Pantheon MCP Server** | Shared MCP protocol server on port 8010 — exposes Athenaeum, messaging, skills hub, and systems as MCP tools | Inter-god communication — real-time, any MCP client connects |
| **Hermes** | Messenger god — routes reports, relays between gods | User-facing communication hub |

**Bundled with Pantheon by default:**
- Me (Hephaestus) — the forger, the builder
- Hermes — the messenger, the relay
- All core systems above

---

## God Types

### Conversational
An LLM-driven god the user talks to directly (or via Hermes).

- **Has:** personality, studio specializations, conversational identity
- **Driven by:** LLM (model defined in harness)
- **Examples:** Apollo (lyric-writing), Athena (knowledge), future gods
- **Anatomy:**
  - `harnesses/{name}-base.yaml` — identity, routing, guardrails
  - Entry in `pantheon-registry.yaml`
  - Codex directory in the Athenaeum
  - Inbox under `gods/messages/{name}/`
  - Optional: plugin directory for custom Hermes tools

### Service
A machine-to-machine god. No direct user conversation. Processes messages from other gods.

- **Has:** routing logic, no personality, no studios
- **Driven by:** LLM (structured output) or script
- **Examples:** Hermes (message router), Hecate (intent classifier)
- **Anatomy:**
  - `harnesses/{name}-base.yaml` — routing, guardrails, failure behavior
  - Entry in `pantheon-registry.yaml`
  - Inbox under `gods/messages/{name}/`
  - Optional: plugin directory

### Subsystem
A background process god. Runs on schedule or triggers. No LLM.

- **Has:** routing (script-level if/else), no personality
- **Driven by:** cron, file watcher, event trigger
- **Examples:** Demeter (ingestion scheduler), Hestia (health monitor), Kronos (logger)
- **Anatomy:**
  - `harnesses/{name}-base.yaml` — routing, guardrails
  - Entry in `pantheon-registry.yaml`
  - Script or cron entry
  - Inbox for receiving commands

---

## The Forging Process

When you (Konan, or later a user) say **"I want a god for [purpose]"**, this is what happens:

### Step 1: Clarify
I ask:
- What does this god **do**? (domain)
- Who talks to it? (user, other gods, both)
- What type? (conversational, service, subsystem)
- Any personality or style preferences?
- What knowledge does it need access to?

### Step 2: Propose
I draft the god profile based on your answers:
- Type and driver (LLM/script/service)
- Harness structure
- Which Codices it needs
- What tools it should have
- How it communicates (inbox + routing)

### Step 3: Confirm
You review and say yes / adjust / rethink.

### Step 4: Forge
I build:
1. **God package** — copy from template, fill in god.yaml and harness.yaml
2. **Run `pantheon-install`** — validates, installs harness, creates inbox, registers in registry, optionally creates Codex, registers in graph, notifies Hermes
3. **Register in `gods.yaml`** — add to the active roster (SDK does not do this automatically)
4. **Add MCP server config** — append to `~/.hermes/profiles/{god-id}/config.yaml`:
   ```yaml
   mcp_servers:
     pantheon:
       url: "http://127.0.0.1:8010/mcp"
       timeout: 60
   ```
   This gives the god access to all Pantheon MCP tools (athenaeum_search, messaging_send, etc.).
   Without this, the god is isolated from the MCP inter-god bus.
5. **Register heartbeat** — if the god runs on a schedule (cron, timer, event-driven),
   register it with the heartbeat system so The Fates can monitor its uptime:
   ```bash
   cd ~/pantheon && python3 scripts/heartbeat.py register <god-id> \
     --label "God Name — Description" \
     --interval <expected_interval_min>
   ```
   Then add `beat("<god-id>")` at the end of the god's run function. See
   `scripts/heartbeat.py` and `scripts/the-fates.py` for reference.
   Without this, the Fates can't detect if the god has stopped running.

### Step 5: Walkthrough
I present:
- What was created and where
- How the god works
- How other gods communicate with it
- Any open questions or gaps

### Step 6: Post-Forge Checklist

Before a new god is operational, verify:

| # | Item | Why |
|---|------|-----|
| 1 | **MCP config in profile** — `mcp_servers.pantheon` added to `~/.hermes/profiles/{god-id}/config.yaml` | Without this, the god can't use Pantheon MCP tools |
| 2 | **Heartbeat registered** — `python3 scripts/heartbeat.py register {god-id}` + `beat()` added (if scheduled) | The Fates can't monitor uptime without it |
| 3 | **Inbox created** — `~/pantheon/gods/messages/{god-id}/` exists | Other gods can't send messages to it |
| 4 | **Inbox monitoring documented** — harness identity block includes instruction to check inbox on session start | God won't see inter-god messages otherwise |
| 5 | **God roster updated** — entry in `gods.yaml` | Other gods can discover it |

### Step 7: Iterate
You use it, find rough edges, I smooth them.

---

## Harness Template (Conversational)

```yaml
schema_version: 1
name: {God Name}
type: conversational
driver: llm
model: {model_name}          # e.g. gemma4, claude-sonnet-4

sanctuary: {domain name}     # e.g. "The Kitchen" for Hestia, "The Library" for Athena

vault_path: /Athenaeum/Codex-{name}/sessions/
mnemosyne_scope:
  - /Athenaeum/Codex-{name}/

identity: |
  You are {God Name}, {title/role} of the Pantheon. You {core function}.
  
  {Personality — warm, scholarly, direct, etc.}
  {Domain knowledge scope — what you know and don't know.}
  {How you interact with the user and other gods.}
  {How you use the Athenaeum — what you read, what you write.}

  ## MCP Tools Available to You

  You are connected to the Pantheon MCP server. These tools are available
  with the `mcp_pantheon_` prefix:
  - **athenaeum_search** — Semantic search across all Codexes
  - **athenaeum_read** — Read any file from the Athenaeum
  - **athenaeum_walk** — Browse the Athenaeum index tree
  - **athenaeum_write** — Write new knowledge to the Athenaeum
  - **messaging_send** — Send messages to any other god's inbox
  - **messaging_check_inbox** — Check your inbox for messages
  - **god_list** — List all registered gods

  Use these tools to search shared knowledge, communicate with other gods,
  and contribute to the Athenaeum. They are your primary channels for
  inter-god coordination.

output:
  format: {structured_document | natural | json}
  log_to_vault: true

guardrails:
  hard_stops:
    - Never {forbidden action 1}
    - Never {forbidden action 2}
  soft_boundaries:
    - Flag when {condition worth noting}

failure_behavior:
  on_ambiguity: ask_one_clarifying_question
  on_out_of_scope: route_with_explanation
  on_hard_stop: return_refusal_with_reason
  on_mnemosyne_unavailable: proceed_without_corpus_note_limitation
```

### Harness Template (Service)

```yaml
schema_version: 1
name: {God Name}
type: service
driver: llm
model: {model_name}

identity: |
  You are {God Name}, {role}. You {core function}.
  You do not converse with the user. You {process/route/classify} and return control.
  You log every action to Kronos.

routing:
  - if: {condition_1}
    then: {action_1}
  - if: {condition_2}
    then: {action_2}

guardrails:
  hard_stops:
    - Never {forbidden action}
    - Never converse with the user directly

failure_behavior:
  on_ambiguity: return_error_to_sender
  on_out_of_scope: return_error_to_sender
  on_hard_stop: halt_and_log
```

### Harness Template (Subsystem)

```yaml
schema_version: 1
name: {God Name}
type: subsystem
driver: script

routing:
  - if: {condition_1}
    then: {action_1}
  - if: {condition_2}
    then: {action_2}

guardrails:
  hard_stops:
    - Never {forbidden action}
    - Never {forbidden action}

failure_behavior:
  on_ambiguity: skip_and_log
  on_out_of_scope: skip_and_log
  on_hard_stop: halt_and_log
  on_mnemosyne_unavailable: proceed_without_corpus_note_limitation
```

---

## Registration Protocol

Every god must be registered in `pantheon-registry.yaml`:

```yaml
gods:
  - name: {God Name}
    harness: {name}-base.yaml
    type: {conversational | service | subsystem}
    studios:           # only for conversational gods
      - {studio_1}
      - {studio_2}
```

After registration, I send a message to Hermes' inbox notifying him of the new god so he knows how to route to it.

---

## Message Protocol

All gods communicate through the shared filesystem bridge under `~/pantheon/gods/messages/`.

### Inbox Location
```
gods/messages/{god-name}/msg_{timestamp}.json
```

### Message Format
```json
{
  "id": "msg_{timestamp}",
  "from": "{sender_name}",
  "to": "{recipient_name}",
  "type": "request | response | notification | broadcast",
  "subject": "Brief subject line",
  "body": "Full message text. Supports markdown.",
  "priority": "low | normal | high | critical",
  "timestamp": "{ISO_8601_timestamp}",
  "read": false,
  "payload": {},
  "thread_id": null
}
```

### Protocol Rules
1. Write a message to the recipient's inbox directory
2. Recipient reads it, sets `"read": true` once processed
3. If reply needed, write a new message back to sender's inbox
4. Priority `critical` gets an alert notification (via Hermes in Telegram)
5. Kronos logs every message for audit trail

---

## God SDK — Package Management CLI

Phase 1 of the God SDK is complete. Four CLI tools handle the full god lifecycle:

### `pantheon-install <package-path>`

Installs a god package from a local directory. The package must contain a valid
`god.yaml` and `harness.yaml`.

**What it does automatically:**
1. Validates the manifest against the schema
2. Copies the package to `~/.pantheon/gods/{id}/`
3. Installs the harness to `harnesses/{id}-base.yaml`
4. Creates inbox at `gods/messages/{id}/`
5. Creates Codex in Athenaeum (if `athenaeum_codex: true`)
6. Registers in `pantheon-registry.yaml` with version
7. Creates node in the entity graph
8. Notifies Hermes
9. Logs to vault

### `pantheon-uninstall <god-id> [--remove-codex]`

Removes a god from the Pantheon. Reverses every step of install.

**Flags:**
- `--remove-codex` — also deletes the Codex directory (default: skip — data safety)

### `pantheon-upgrade <god-id> <new-package-path>`

Upgrades a god to a new version. The old version is preserved in vault logs.

**What it does:**
1. Validates the new manifest
2. Replaces the installed package
3. Updates the harness
4. Updates the version in `pantheon-registry.yaml`
5. Replaces the graph node (new version metadata)
6. Notifies Hermes of the version change
7. Logs to vault (both old and new versions recorded)

### `pantheon-list-gods`

Shows all registered gods in a formatted table — name, type, version, status,
description.

**Status values:**
- `installed` — package is present at `~/.pantheon/gods/{id}/`
- `active` — marked active in `gods.yaml`
- `registered` — in the registry but no package
- `planned` — in `gods.yaml` but not yet registered

### `pantheon-export <god-id> [--include-codex] [--output <path>]`

Exports an installed god as a portable tarball for transfer to another machine.

- Exports to: `~/pantheon/god-exports/god-{id}-v{version}.tar.gz`
- `--include-codex` — bundles reference docs, distilled knowledge (excludes sessions and archive — instance-specific data stays local)
- `--output <path>` — custom output path instead of the default exports folder
- Recipient flow: `tar xzf → pantheon-install`

---

## Fresh Install Manifest

For a new Pantheon installation, these are the minimum required components:

```
~/pantheon/
├── gods/                    # God Bridge system
│   ├── README.md            # Bridge documentation
│   ├── GOD-FORGING-GUIDE.md # This document
│   ├── gods.yaml            # Active roster
│   ├── messages/            # Inbox/outbox directories per god
│   └── TEMPLATE.md          # Quick reference harness template
├── pantheon-registry.yaml   # Master god registry
├── harnesses/               # God harness YAML files
├── project-ideas.md         # Master roadmap
├── pantheon-core/           # Core system code
│   ├── gods/                # System god implementations
│   └── tests/               # Core system tests
├── plugins/                 # Hermes plugin implementations
├── scripts/                 # CLI tools (pantheon-install, etc.)
├── god-packages/            # God SDK package templates
│   └── god-template/        # Reference template for new gods
└── athenaeum/               # Knowledge store (shared mount or symlink)
    └── Codex-*/             # Codices per domain
```

**Core gods that ship with Pantheon:**
- **Hephaestus** — me, the forger and builder. Foundation god, always bundled.
- **Hermes** — messenger and relay. Routes inter-god communication.
- **Hades** — data lifecycle gatekeeper. Consolidation, health, archival.
- **Demeter** — ingestion pipeline. File watching, content classification.
- **The core systems** — Athenaeum, Mnemosyne, GraphClient, God Bridge.

**Everything else is forge-on-demand.** When you want a god, you come to me. I walk you through it. We build it together.

---

## Pantheon Skills Hub

The Pantheon has a **shared skills hub** at `/home/konan/athenaeum/skills/`. These are universal, reusable tasks that any god can execute via MCP.

### How It Works

- Each skill is a directory under `athenaeum/skills/<name>/` containing a `skill.yaml` manifest and a Python script
- Any god connected to the MCP server can call `mcp_pantheon_skill_list`, `mcp_pantheon_skill_info`, and `mcp_pantheon_skill_run`
- Skills are the standard way to share reusable logic across all gods

### Adding a New Skill

```yaml
# athenaeum/skills/<name>/skill.yaml
name: <skill-name>
description: What this skill does
script: scripts/<script>.py
args:
  arg1: "Description of arg1"
  arg2: "Description of arg2"
```

Then create the script at `athenaeum/skills/<name>/scripts/<script>.py`.

### Currently Available Skills

| Skill | Description | MCP Command |
|-------|-------------|-------------|
| capture-idea | Add an idea to Codex-Pantheon/projects.md | `mcp_pantheon_skill_run({"name": "capture-idea", "arguments": "[\"Title\", \"Desc\"]"})` |

---

## Template Synchronization Protocol

**Critical rule:** Every time a god architecture, communication protocol, or system integration changes, the god template **must be updated immediately** — before the next god is forged.

This prevents the pattern we just fixed: a feature exists (MCP skills hub, inbox monitoring) but a new god gets spun up without it.

### The Protocol

1. **Change happens** — MCP tool added, new protocol, new system
2. **Template updated** — update `god-packages/god-template/README.md` with the new section
3. **Guide updated** — update `GOD-FORGING-GUIDE.md` with the change
4. **Changelog entry** — add to the forging guide's Changelog table
5. **Memory noted** — I log the change in my memory so I don't forget for the next forge

### When to Trigger

| Trigger | Action |
|---------|--------|
| New MCP tool added | Add to template's MCP tools table |
| New shared skill created | Add to skills hub section in guide |
| Communication protocol changes | Update Message Protocol section in guide |
| New core system added | Update Core Systems table and Fresh Install Manifest |
| Post-forge checklist changes | Update Step 6 in forging process |

This ensures any god forged today has every capability a god forged a month ago has. No drift.

## Maintenance Protocol

This guide must stay in sync with the actual Pantheon skeleton. Here's how I keep it current:

### How I Update

1. **Note the drift** — when I forge a new god and the guide is missing something, I don't skip it. I capture the new pattern.
2. **Update the guide** — immediately after the forge, while the pattern is fresh.
3. **Update the Athenaeum copy** — sync `~/athenaeum/Codex-Pantheon/reference/god-forging-guide.md`
4. **Re-embed** — `athenaeum_embed` the Athenaeum copy so Mnemosyne is current
5. **Log the change** — add an entry to the Changelog table
6. **Commit** — `git commit` with message like `docs: update god forging guide v1.1.0 — added new harness pattern for {pattern}`

### Versioning

- **Major (1.0.0 → 2.0.0):** The skeleton, god types, or protocol has fundamentally changed. Rare.
- **Minor (1.0.0 → 1.1.0):** New pattern, new section, new template. Normal evolution.
- **Patch (1.0.0 → 1.0.1):** Clarification, typo, example update. No structural change.

The version is noted at the top of this guide. If you ever see me working from stale info, call it out — it means I missed an update. I'll fix it immediately.
