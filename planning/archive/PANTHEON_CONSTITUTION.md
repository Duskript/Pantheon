# PANTHEON — Architectural Constitution
> Living document. AI assistants must read this entire document before touching any code.
> All edits are patches. Nothing is rewritten. Version history is append-only.

---

## 1. What Pantheon Is

Pantheon is a privacy-centric personal AI operating system organized around mythological archetypes. It is not a chatbot. It is not a wrapper around a language model. It is a multi-agent system where every capability has a defined domain, a defined harness, and a defined relationship to every other capability.

Each agent in Pantheon is called a god. Each god has a specific job and nothing else. Gods do not step outside their domain — they route to the appropriate god when something is outside their scope. This is enforced at the harness level, not by trust.

Pantheon is built for a single primary user. It is privacy-centric by design — local inference is preferred, external services are evaluated deliberately rather than assumed. External reach is handled exclusively through Prometheus, the designated API bridge, ensuring all outbound calls are intentional and traceable. Cloud models and external APIs are supported where they add genuine value; they are never the default.

The system is designed around flow-state preservation. It should require minimal user intervention during operation. Gods handle routing, handoffs, and escalation internally. The user should only need to interact with a small number of conversational gods directly. Everything else runs silently.

Pantheon is also a framework. Its god/studio/harness model is portable across mythological pantheons. A user may select Greek, Norse, Egyptian, or custom naming at setup. The underlying architecture does not change — only the names and identity prompts of each agent.

### Single User Architecture

Each Pantheon instance is scoped to a single user. The system is personalized at the instance level — one Athenaeum, one god registry, one set of Sanctuaries, all built around one person's needs and knowledge. This is intentional. Deep personalization and a shared multi-user knowledge base are architectural opposites. Pantheon chooses personalization.

Multiple users means multiple instances. Each instance is independent. There is no shared state between instances by default.

**Multi-user is a future consideration, not a current requirement.** When designing any component do not architect against multi-user support but do not build for it either. The flag for future implementation is: shared Codex access with user-scoped write permissions and a unified Mnemosyne partition with user metadata tagging. This is not fleshed out and should not be implemented until explicitly specified.

### Core Principles

- **Privacy centric.** Local inference via Ollama is preferred. External services and cloud models are supported where they add genuine value but are never assumed. All external calls route through Prometheus and are intentional and traceable.
- **Domain isolation.** Every god has a lane. No god operates outside it.
- **Athenaeum as truth.** The Athenaeum is the canonical knowledge store — a filesystem of markdown files organized into Codices by domain. It is tool-agnostic; Obsidian is one way to interact with it, not a dependency. All other data layers are derived from the Athenaeum and can be rebuilt from it.
- **Append only.** Logs, version history, and the vault never delete — they archive.
- **Harness enforced.** Agent behavior is defined by harness files, not by trust or convention.
- **Flow preservation.** The system minimizes interruption. Human-in-the-loop gates exist only where decisions genuinely require human judgment.
- **Self-feeding.** Normal usage of Pantheon generates the knowledge base. Working in the system is building the system.

---

## 2. The Stack

This section describes the hardware and software Pantheon runs on. AI assistants must not assume any component not listed here exists. Do not introduce new dependencies without explicit instruction.

### Hardware

**Primary Workstation — Active**
- OS: CachyOS (Arch-based), KDE Plasma
- GPU: NVIDIA RTX 3060 12GB VRAM
- Role: Primary user interaction, all Phase 1 Pantheon services, Claude Code and CLI build sessions
- Note: All Phase 1 gods run here until homelab is operational

**Homelab Server — Planned, Not Yet Built**
- CPU: AMD Ryzen 7 (Zen 1)
- RAM: Maxed DDR4
- GPU: AMD Radeon 12GB
- Hypervisor: Proxmox (planned)
- Role (future): Always-on services, Ollama inference, Athenaeum hosting, vector DB, background god processes
- Note: Pantheon itself will assist in planning and building this server once Phase 1 is operational on the workstation

**Network**
- Tailscale running across all nodes
- All Pantheon services accessible via Tailscale without port exposure

### Core Software

**Inference**
- Ollama — primary local inference engine
- Primary model: Gemma 4 (subject to change per god/studio assignment)
- Embedding model: nomic-embed-text via Ollama
- Cloud models supported via Prometheus when local inference is insufficient

**Frontend**
- Forked Open WebUI — primary user-facing interface
- Rebuilt as Sanctuary-based workspace system
- Accessible via Tailscale on all user devices

**Knowledge Store**
- The Athenaeum — filesystem of markdown files organized into Codices
- Obsidian — optional human interaction layer for the Athenaeum, not a dependency

**Vector Database**
- Chroma (Phase 1) — local semantic search and embedding store
- Qdrant (Phase 2+ migration target) — higher performance at scale

**Version Control**
- Git — all Pantheon code and harness files under version control
- GitHub — remote under Duskript developer identity

**Networking**
- Tailscale — secure mesh access across all devices
- Proxmox — VM and container management on homelab server

**Containerization**
- Docker Compose + Portainer — service management on homelab
- Background gods run as containerized services where applicable



## 3. The Knowledge Layer

The knowledge layer is Pantheon's memory system. It has four distinct layers, each with a specific role. They are not interchangeable. AI assistants must understand the relationship between layers before touching any knowledge-related code.

### The Four Layers

**Layer 1 — The Athenaeum**
The canonical human-readable knowledge store. A filesystem of markdown files organized into Codices. This is the source of truth. It is append-and-archive only — nothing is deleted from the Athenaeum, only moved to archive subfolders. If every other layer were destroyed, the entire system could be rebuilt from the Athenaeum alone.

**Layer 2 — The Vector Store (Mnemosyne)**
A machine-readable semantic index of the Athenaeum. Built from and derived from Layer 1. Never the source of truth — always a derived layer. Gods query Mnemosyne when they need to find semantically relevant knowledge. Mnemosyne is rebuilt or updated whenever the Athenaeum changes. If the vector store is corrupted or lost it is rebuilt from the Athenaeum — no data is permanently lost.

**Layer 3 — The Distilled Layer**
Consolidated canonical concepts produced by Hades during nightly consolidation runs. Raw notes that have been merged, deduplicated, and summarized live here. Sits between raw Athenaeum content and vector search as a noise reduction layer. Distilled content is still stored in the Athenaeum under each Codex's /distilled/ subfolder — it is not a separate system.

**Layer 4 — Codex Partitions**
Scoped views into the vector store. Not separate databases. Each Codex has a corresponding Mnemosyne partition defined by metadata tags applied at embedding time. Studios query their designated partition only. A Lyric Writing Studio session never surfaces infrastructure notes. Partitions are logical, not physical.

### The Athenaeum File Structure

```
/Athenaeum/
├── Codex-SKC/
│   ├── lyrics/
│   ├── style/
│   ├── references/
│   ├── distilled/
│   └── archive/
│
├── Codex-Infrastructure/
│   ├── homelab/
│   ├── networking/
│   ├── proxmox/
│   ├── distilled/
│   └── archive/
│
├── Codex-Pantheon/
│   ├── constitution/
│   ├── harnesses/
│   ├── workflows/
│   ├── sessions/
│   ├── distilled/
│   └── archive/
│
├── Codex-Forge/
│   ├── blueprints/
│   ├── sessions/
│   ├── distilled/
│   └── archive/
│
├── Codex-Fiction/
│   ├── cantors-tale/
│   ├── worldbuilding/
│   ├── distilled/
│   └── archive/
│
├── Codex-General/
│   ├── notes/
│   ├── distilled/
│   └── archive/
│
├── Codex-Asclepius/
│   ├── research/
│   ├── references/
│   ├── conditions/
│   ├── treatments/
│   ├── distilled/
│   └── archive/
│
└── Codex-Inbox/
    ├── clippings/
    ├── documents/
    ├── references/
    └── processed/
```


### Codex Definitions

| Codex | Domain | Primary God | Studio Access |
|---|---|---|---|
| SKC | Music, lyrics, style, sonic references | Apollo | Lyric Writing, Poetry |
| Infrastructure | Homelab, networking, IT, Proxmox | Hephaestus | Infrastructure Planning |
| Pantheon | System docs, harnesses, workflows, sessions | Athena | All |
| Forge | Blueprints, planning sessions, specs | Hephaestus | Project Scoping, Program Design |
| Fiction | Long form narrative, worldbuilding | Calliope | Long Form Fiction |
| Asclepius | Medical research, health knowledge, treatment references | Caduceus | Medical Research, Health Reference |
| General | Uncategorized notes, personal knowledge | Athena | Knowledge Query |
| Inbox | Unprocessed clippings, documents, references | Hermes | None — staging only |

### Knowledge Flow

```
User works in a Sanctuary session
        ↓
Session auto-logs to designated Codex folder
        ↓
Demeter detects new content (file watcher)
        ↓
Mnemosyne re-embeds changed files with Codex metadata tag
        ↓
Hades runs nightly — consolidates and distills where appropriate
        ↓
Distilled content written back to Codex /distilled/ folder
        ↓
Mnemosyne re-embeds distilled content
```

### Hard Rules For This Layer

- The Athenaeum owns the truth. All other layers serve it.
- Never write directly to the vector store — always write to the Athenaeum and let Mnemosyne derive from it.
- Never delete from the Athenaeum — archive only.
- Codex partitions are defined by metadata tags at embedding time, not by separate database instances.
- Session logs are append-only markdown files. One file per session, named by timestamp.
- Hades writes distilled content back to the Athenaeum. Distillation is not destruction of the source — originals move to /archive/, not deletion.
- Codex-Inbox is a staging area only. Content dropped here is unprocessed and unsearchable until Hermes classifies and routes it to the appropriate Codex. Processed items move to /processed/ after routing — they are never deleted from Inbox immediately.

---


## 4. The God / Studio / Harness Model

This section defines how agents are structured in Pantheon. Every agent is a god. Every god has a harness. Some gods have studios. This hierarchy is the core architectural pattern of the entire system.

### The Three Layers

**The God**
The god is the agent's identity, domain, and personality. It defines what the agent is responsible for and what it is not. Gods do not overlap. When something is outside a god's domain the harness routes it to the appropriate god rather than attempting to handle it.

**The Studio**
A studio is a specialization layer loaded on top of a god's base harness for a specific task domain. A god can have multiple studios. Studios inherit the god's base identity and add targeted knowledge context, scoped Mnemosyne partitions, and domain-specific guardrails. Not all gods have studios — studios exist only where meaningful specialization is required.

**The Harness**
The harness is the constraining structure that makes a god's output reliable and consistent. It defines exactly what the god does, what it refuses, what format it outputs, how it handles ambiguity, and how it routes out-of-scope requests. The harness is enforced at the definition level — not by convention or trust. A god without a harness is not a Pantheon agent.

### The Hierarchy

```
Sanctuary (the room you work in)
└── God (who you are talking to)
    └── Studio (what they are specialized for)
        └── Harness (the guardrails and routing rules)
            └── Mnemosyne Partition (the scoped knowledge)
```

### The Harness File Schema

Every god is defined by a YAML harness file stored in /Athenaeum/Codex-Pantheon/harnesses/. This file is the complete definition of the agent. Nothing about a god's behavior exists outside this file.

```yaml
# Example: apollo-lyric-writing.yaml

name: Apollo
studio: Lyric Writing
sanctuary: The Studio

extends: apollo-base.yaml

driver: llm
model: gemma4
vault_path: /Athenaeum/Codex-SKC/sessions/
mnemosyne_scope:
  - /Athenaeum/Codex-SKC/lyrics/
  - /Athenaeum/Codex-SKC/style/
  - /Athenaeum/Codex-SKC/distilled/

identity: |
  You are Apollo operating in Lyric Writing mode.
  You assist exclusively with creative writing within
  the SKC artistic voice and style. You have access
  to the SKC creative corpus via Mnemosyne. You flag
  lyrical repetition from past work. You format output
  for Suno compatibility when requested.

receives:
  - Creative prompts
  - Mnemosyne corpus results
  - SKC style context

output:
  format: structured_sections
  schema: [section_type, content, notes]
  log_to_vault: true

routing:
  - if: it_or_infrastructure_topic
    then: route_to(hephaestus)
  - if: requires_vault_knowledge
    then: call(athena) → inject → continue
  - if: requires_corpus_search
    then: call(mnemosyne) → inject → continue
  - if: long_form_narrative_request
    then: suggest_sanctuary(calliope, long-form-fiction)
  - if: outside_all_known_domains
    then: escalate(zeus, reason="unclassified")

guardrails:
  hard_stops:
    - Never execute system commands
    - Never write outside SKC voice without explicit override flag
    - Never access Athenaeum directly — always via Athena or Mnemosyne
  soft_boundaries:
    - Flag if prompt feels outside established SKC themes
    - Flag if requested style conflicts with SKC style documents
    - Flag if imagery closely matches existing corpus content

failure_behavior:
  on_ambiguity: ask_one_clarifying_question
  on_out_of_scope: route_with_explanation
  on_hard_stop: return_refusal_with_reason
  on_mnemosyne_unavailable: proceed_without_corpus_note_limitation
```

### The Driver Field

Not every god requires a language model. The harness `driver` field defines what powers the god. This is a required field for all harness files.

```yaml
driver: llm          # Language model via Ollama — conversational and reasoning gods
driver: script       # Python or shell script — scheduled jobs, monitors, file watchers
driver: service      # Long-running process or API — vector DB interfaces, log pipelines
driver: hybrid       # Script with optional LLM calls for classification or summarization
```

Examples by god:

| God | Driver | Reason |
|---|---|---|
| Zeus | llm | Orchestration requires reasoning |
| Apollo | llm | Creative output requires inference |
| Hephaestus | llm | Planning requires reasoning |
| Athena | llm | Knowledge retrieval and synthesis |
| Mnemosyne | service | Vector DB interface — no inference needed |
| Hestia | script | Health checks — pure monitoring logic |
| Demeter | script | Cron scheduler — pure job triggering |
| Kronos | service | Log pipeline — append only, no inference |
| Hades | hybrid | File consolidation logic + LLM for summarization |
| Hermes | hybrid | Routing logic + LLM for Inbox classification |
| Hecate | llm | Intent classification requires inference |
| Hera | service | Config state management — no inference needed |
| Ares | script | Enforcement rules — deterministic logic only |
| Charon | script | File transfer pipeline — no inference needed |

For `script` and `service` drivers the `model` field is omitted entirely. For `hybrid` drivers the `model` field is optional and only invoked for specific steps defined in the harness.



Base harness files define a god's core identity and default behavior. Studio harness files extend the base, adding only what differs. This prevents duplication and ensures the god's core identity stays consistent across all studios.

```
apollo-base.yaml          ← core identity, default routing, base guardrails
apollo-lyric-writing.yaml ← extends base, adds SKC corpus scope and Suno awareness
apollo-poetry.yaml        ← extends base, adds poetry structure and meter awareness
apollo-short-fiction.yaml ← extends base, adds narrative structure awareness
```

### The God Registry

Zeus loads the god registry at startup. The registry is a single YAML file listing all available gods, their base harness files, and their available studios.

```yaml
# pantheon-registry.yaml

gods:
  - name: Zeus
    harness: zeus-base.yaml
    type: orchestrator
    studios: none

  - name: Apollo
    harness: apollo-base.yaml
    type: conversational
    studios:
      - lyric-writing
      - poetry
      - short-fiction

  - name: Hephaestus
    harness: hephaestus-base.yaml
    type: conversational
    studios:
      - program-design
      - infrastructure-planning
      - project-scoping

  - name: Athena
    harness: athena-base.yaml
    type: conversational
    studios:
      - knowledge-query
      - research
      - vault-management

  - name: Hermes
    harness: hermes-base.yaml
    type: service
    studios: none

  - name: Mnemosyne
    harness: mnemosyne-base.yaml
    type: subsystem
    studios: none

  - name: Hades
    harness: hades-base.yaml
    type: subsystem
    studios: none

  - name: Hecate
    harness: hecate-base.yaml
    type: service
    studios: none

  - name: Hestia
    harness: hestia-base.yaml
    type: subsystem
    studios: none

  - name: Demeter
    harness: demeter-base.yaml
    type: subsystem
    studios: none

  - name: Kronos
    harness: kronos-base.yaml
    type: subsystem
    studios: none

  - name: Hera
    harness: hera-base.yaml
    type: subsystem
    studios: none

  - name: Ares
    harness: ares-base.yaml
    type: subsystem
    studios: none

  - name: Caduceus
    harness: caduceus-base.yaml
    type: conversational
    studios:
      - medical-research
      - health-reference

  - name: Calliope
    harness: calliope-base.yaml
    type: conversational
    studios:
      - long-form-fiction
      - worldbuilding
```

### Agent Types

| Type | Description | User Interaction |
|---|---|---|
| conversational | Primary user-facing agents | Direct |
| orchestrator | Routes and synthesizes — Zeus only | Direct |
| service | Event-driven, handles handoffs and routing | Indirect |
| subsystem | Background processes, never conversational | None |

### Hard Rules For This Layer

- Every god must have a harness file before it is instantiated.
- No god operates outside its defined domain. Out-of-scope requests are routed, not handled.
- Studio harness files always extend a base — they never define a god from scratch.
- The registry is the only authoritative list of available gods. If a god is not in the registry it does not exist.
- Hera holds the official state of all harness files. Changes to harness files are propagated by Hera.
- Hard stops in a harness are non-negotiable. They cannot be overridden by user instruction at runtime.

---


## 5. The Sanctuary System

A Sanctuary is Pantheon's equivalent of a workspace or project. It is the room you work in. Each Sanctuary is bound to a specific god and optionally a specific studio. Opening a Sanctuary means you are talking to that god, in that specialization, with that scoped knowledge — and nothing else bleeds in.

Sanctuaries replace the workspace system in the Open WebUI fork. They are not workspaces with a different name. They are architecturally distinct — prompt isolation, harness loading, and vault logging are first-class features, not configurations.

### What A Sanctuary Contains

Every Sanctuary is defined by a configuration file stored in /Athenaeum/Codex-Pantheon/harnesses/sanctuaries/.

```yaml
# sanctuary-the-studio-lyric.yaml

name: The Studio — Lyric Writing
god: Apollo
studio: lyric-writing
harness: apollo-lyric-writing.yaml

model: gemma4
context_window: 8192

vault_logging:
  enabled: true
  path: /Athenaeum/Codex-SKC/sessions/
  format: markdown
  filename: timestamp

ui:
  accent_color: "#f59e0b"
  icon: 🎵
  description: "SKC lyric writing with full corpus awareness"
```

### Prompt Isolation — The Core Fix

This is the primary architectural problem the Sanctuary system solves. In standard Open WebUI a global system prompt bleeds into every workspace, overriding or conflicting with workspace-level prompts. In Pantheon this is not permitted.

The rule is absolute:

**When a Sanctuary is active, the god's harness file is the only system prompt. The global prompt is suppressed entirely.**

Zeus is the only god whose prompt has any global scope — and Zeus's global prompt is intentionally minimal. It contains only routing authority and nothing else. It cannot override a Sanctuary's harness because it contains no domain instructions to conflict with.

Implementation requirement for the fork: the prompt assembly pipeline must check for an active Sanctuary before constructing the system prompt. If a Sanctuary is active, load the harness file only. The global prompt slot is replaced, not appended to.

### Vault Logging

Every Sanctuary with vault_logging enabled automatically writes conversation turns to the designated Athenaeum path. This is not optional per session — it is a Sanctuary-level setting. If you do not want a session logged, use a Sanctuary with logging disabled.

Log format:

```markdown
---
sanctuary: The Studio — Lyric Writing
god: Apollo
studio: lyric-writing
timestamp: 2026-04-18T14:32:00
---

[User]: prompt content here

[Apollo]: response content here

---
```

Each session is one file. Filename is the timestamp of session start. Demeter detects new files and triggers Mnemosyne re-embedding automatically.

### The Sanctuary Selector

The Pantheon UI presents Sanctuaries as the primary navigation. On load the user sees their available Sanctuaries grouped by god. Selecting a Sanctuary loads the harness, sets the model, scopes Mnemosyne, and opens the chat interface. No further configuration is required.

```
⚡ Zeus — General Routing
🎵 Apollo
   └── The Studio: Lyric Writing
   └── The Studio: Poetry
   └── The Studio: Short Fiction
🔨 Hephaestus
   └── The Forge: Project Scoping
   └── The Forge: Program Design
   └── The Forge: Infrastructure Planning
🦉 Athena
   └── The Library: Knowledge Query
   └── The Library: Research
📖 Calliope
   └── The Scriptorium: Long Form Fiction
   └── The Scriptorium: Worldbuilding
```

### Human-In-The-Loop Gates

Sanctuaries support configurable gates — points in a workflow where the system pauses and requires explicit user approval before proceeding. Gates are defined in the harness routing table.

```yaml
gates:
  - trigger: before_vault_write
    message: "Apollo wants to save this session to Codex-SKC. Approve?"
    default: auto_approve

  - trigger: before_routing_to_external
    message: "This request requires Prometheus. Allow external call?"
    default: require_approval
```

Gate behavior operates at three levels of scope:

**Harness level** — default behavior defined in the harness file. Applied to every session using that Sanctuary unless overridden.

**Session level** — user can approve all gates of a specific type for the duration of the current session. Example: "Approve all external calls this session" suppresses the gate for every Prometheus call until the session ends. Session-level approvals do not persist after the session closes.

**Instance level** — single approval for a single triggered gate. Default behavior when no session-level approval is active.

The UI must present a clear option at each gate trigger: **Approve Once / Approve for This Session / Always Auto-Approve**. The third option modifies the harness default and requires confirmation before saving.

Gates defined as require_approval for external calls cannot be silently bypassed — session-level approval is still an explicit user action, just a one-time one per session rather than per call.

### Hera — The Settings Interface

Hera is not just a background config service. She is the primary settings and administration interface for all of Pantheon. When you need to create, edit, or manage any god, studio, harness, or Sanctuary — you go to Hera.

Hera lives as a dedicated section in the Pantheon UI, accessible from any Sanctuary via a persistent settings entry point. She presents everything through forms, dropdowns, and visual editors. No YAML knowledge is required to operate Pantheon.

**Hera's interface covers:**

*Codices*
- View all existing Codices and their folder structure
- Create a new Codex — name, description, primary god assignment, Mnemosyne partition auto-created on save
- Edit Codex metadata — rename, reassign primary god, update description
- Add or remove subfolders within a Codex
- Archive a Codex — removes from active selector, preserves all content in Athenaeum
- Trigger manual Mnemosyne re-embedding for any Codex

New Codex creation automatically:
- Creates the folder structure in the Athenaeum with /distilled/ and /archive/ subfolders
- Registers the Codex partition in Mnemosyne
- Makes the Codex available as a vault_path option in Sanctuary and harness editors

*Gods*
- View all registered gods and their current status
- Create a new god — guided form walks through every required harness field
- Edit an existing god — field-level editing, not full rewrites
- Archive a god — removes from active registry, preserves definition file

*Studios*
- View all studios per god
- Create a new studio — form pre-populated with parent god's base values
- Edit studio specialization, Mnemosyne scope, and guardrails
- Enable or disable studios per god without deleting them

*Harnesses*
- View raw YAML for any harness file with syntax highlighting
- Edit any harness field via form — changes write back to YAML on save
- Routing rule builder — visual if/then editor with available gods as dropdown targets
- Guardrail manager — add, edit, or remove hard stops and soft boundaries
- Driver selector — changes driver type and shows/hides relevant fields accordingly

*Sanctuaries*
- View all Sanctuaries grouped by god
- Create a new Sanctuary — select god, studio, vault path, logging settings, accent color
- Edit Sanctuary settings — any field editable without recreating the Sanctuary
- Gate configuration — set default gate behavior per trigger type
- Archive a Sanctuary — chat history preserved in Athenaeum

*Registry*
- View the full god registry
- Reorder gods in the Sanctuary selector
- Set a default Sanctuary for new sessions

**The raw YAML is always one click away** for users who prefer direct editing. Hera never hides the underlying files — she just makes them easier to work with.

All changes made through Hera are written to the appropriate files in /Athenaeum/Codex-Pantheon/harnesses/ and propagated to active gods. Changes to a currently active Sanctuary take effect on next session open.

### Sanctuary Types

| Type | Description | Example |
|---|---|---|
| Conversational | Primary working Sanctuaries — user talks to god directly | The Studio, The Forge |
| Monitoring | Read-only status views for subsystem gods | Hestia Dashboard |
| Workflow | Node-based workflow execution surface | Pantheon Workflows |
| Admin | Hera config management, registry editing | Olympus Control |

### Hard Rules For This Layer

- Every Sanctuary must reference a valid harness file. A Sanctuary cannot be created without one.
- Prompt isolation is non-negotiable. No global prompt bleeds into an active Sanctuary.
- Vault logging path must point to a valid Codex folder. Logging to arbitrary paths is not permitted.
- Gates defined as require_approval cannot be changed to auto_approve for external calls.
- Sanctuaries are not deleted — they are archived. A Sanctuary's chat history persists in the Athenaeum even if the Sanctuary is retired.

---


The following are planned but not built. Do not reference them as existing:
- The homelab server (hardware exists, Proxmox not yet installed)
- The Sanctuary system (fork not yet implemented)
- The harness file schema (designed, not yet formalized)
- The workflow engine and node editor
- Mnemosyne vector partitions

## 6. The Open WebUI Fork

Pantheon is built on a fork of Open WebUI. This section defines what Open WebUI provides that is worth keeping, what gets rebuilt, and what gets removed. AI assistants working on the fork must understand this distinction before touching any frontend or backend code.

### What Open WebUI Provides

These components are kept largely intact. Do not rewrite them unless a specific bug or incompatibility requires it.

- Ollama integration and model management
- HuggingFace model import pipeline
- Basic inference pipeline and streaming responses
- Tailscale-accessible web interface
- Mobile-responsive UI foundation
- User authentication system (single user — simplified but kept)
- Basic chat history storage
- RAG pipeline hooks (replaced but the hook points are useful)

### What Gets Rebuilt

These components are replaced entirely with Pantheon-specific implementations. The Open WebUI originals are removed.

| Component | Open WebUI Original | Pantheon Replacement |
|---|---|---|
| Workspaces | Generic workspaces with shared prompt bleed | Sanctuary system with full harness isolation |
| System prompt handling | Global prompt appended to all contexts | Harness file replaces global prompt per Sanctuary |
| RAG pipeline | Built-in RAG with limited scoping | Mnemosyne with Codex partition scoping |
| Settings interface | Generic model and account settings | Hera — full god, studio, harness, Sanctuary, Codex management |
| Chat logging | Internal DB only | Dual write — internal DB and Athenaeum markdown |
| Model selector | Per-conversation dropdown | Per-Sanctuary assignment via harness file |
| Navigation | Chat history sidebar | Sanctuary selector as primary navigation |

### What Gets Removed

These Open WebUI features conflict with Pantheon's architecture or are redundant. Remove cleanly — do not leave dead code.

- Default workspace system and all workspace-related UI
- Global system prompt field in settings
- Any built-in agent or tool-use implementations that conflict with the harness model
- Default RAG implementation (replaced by Mnemosyne)
- Multi-user management UI (single user instance — not needed)

### Fork Identity

The fork is maintained under the Duskript GitHub identity. It is not a theme or plugin on top of Open WebUI — it is a hard fork that diverges intentionally. Upstream Open WebUI changes are evaluated manually before merging. Security patches from upstream should be reviewed and applied. Feature updates from upstream are ignored unless they address a specific gap.

Repository structure:
```
pantheon/
├── frontend/          — Forked Open WebUI frontend
├── backend/           — Forked Open WebUI backend
├── pantheon-core/     — New Pantheon-specific code
│   ├── harness/       — Harness loader and validator
│   ├── sanctuary/     — Sanctuary session management
│   ├── routing/       — Zeus routing engine
│   ├── vault/         — Athenaeum write pipeline
│   └── gods/          — Individual god implementations
├── harnesses/         — Symlink to Athenaeum harness folder
└── docs/              — Constitution and build documentation
```

### UI and Visual Identity

The Pantheon fork has a distinct visual identity from Open WebUI. The following changes are expected and intentional:

- Primary navigation replaced by the Sanctuary selector
- Hera accessible as a persistent settings entry point from any screen
- Each Sanctuary has a configurable accent color and icon defined in its config file
- The default Open WebUI branding, color scheme, and logo are replaced entirely
- Typography, spacing, and component styling are updated to reflect Pantheon's identity
- The chat interface itself remains largely unchanged — it is functional and does not need redesign

Visual design decisions beyond these structural changes are deferred to implementation. The fork should look and feel like a distinct product, not a reskinned Open WebUI.

### Hecate — The Front Door

Pantheon includes a default general-purpose Sanctuary powered by Hecate. This is the landing Sanctuary when no specific context is needed — a place for quick questions, passing thoughts, and exploratory conversations that don't yet have a clear domain.

Hecate handles general queries directly without routing them unless the content clearly belongs to a specific god's domain. When she detects a strong domain signal she surfaces a suggestion — she does not route automatically without acknowledgment.

```
User: "I've been thinking about the chorus structure for the new track"
Hecate: "That sounds like Apollo territory — want me to open 
         The Studio: Lyric Writing?"
         [Open Studio] [Stay here]
```

Hecate's general Sanctuary behavior:
- Answers quick factual questions directly via Athena call if needed
- Handles conversational and exploratory queries without invoking other gods
- Surfaces routing suggestions for clear domain matches — never forces them
- Does not log to a specific Codex by default — logs to Codex-General
- Is the default Sanctuary on first load and after session end

Hecate as front door does not replace her role as silent context classifier for other Sanctuaries. She operates in both modes — visible generalist when you're talking to her directly, invisible classifier when another Sanctuary is active.

- Minimize new dependencies. Every new package is a future maintenance burden.
- Prefer Python for backend additions — consistent with Open WebUI's existing stack.
- Prefer vanilla JS or existing frontend framework for UI additions — do not introduce a second frontend framework.
- Docker Compose for all service orchestration. No kubernetes, no swarm.

### Hard Rules For This Layer

- Never modify Open WebUI's core inference pipeline. Route around it, don't change it.
- All Pantheon-specific code lives in pantheon-core/. Nothing Pantheon-specific is written into the Open WebUI frontend or backend directories directly — use hooks and extension points.
- The fork must remain buildable from a clean clone with a single Docker Compose command.
- Upstream security patches are reviewed within 14 days of release.
- The global system prompt field is removed from the UI entirely — not hidden, removed. Its existence invites misconfiguration.

---

- The homelab server (hardware exists, Proxmox not yet installed)
- The Sanctuary system (fork not yet implemented)
- The harness file schema (designed, not yet formalized)
- The workflow engine and node editor
- Mnemosyne vector partitions

## 7. Sanctuary Architecture

This section defines how Sanctuaries are implemented at the code level. It covers prompt assembly, harness loading, vault logging pipeline, and session lifecycle. This is implementation guidance for builders — not conceptual description.

### Session Lifecycle

```
User selects Sanctuary
        ↓
Sanctuary config file loaded
        ↓
Harness file loaded (including extends chain resolved)
        ↓
Hecate runs silent intent classification (updates context profile)
        ↓
Model initialized with harness as sole system prompt
        ↓
Mnemosyne scoped to Codex partitions defined in harness
        ↓
Session file created in Athenaeum vault_path
        ↓
[Active session — user interacts with god]
        ↓
Each turn appended to session file in real time
        ↓
Session ends (user closes or switches Sanctuary)
        ↓
Session file finalized — timestamp closed
        ↓
Demeter notified — triggers Mnemosyne re-embedding of new file
```

### Prompt Assembly Pipeline

This is the core fix over standard Open WebUI. The prompt assembly function must follow this exact order of precedence:

```python
def assemble_system_prompt(sanctuary, session):
    # 1. Check for active Sanctuary
    if sanctuary is None:
        # Fall back to Hecate base harness
        return load_harness("hecate-base.yaml").identity

    # 2. Load harness — resolve extends chain
    harness = load_harness(sanctuary.harness)
    if harness.extends:
        base = load_harness(harness.extends)
        harness = merge_harness(base, harness)

    # 3. Return harness identity as sole system prompt
    # Global prompt is NOT included — ever
    return harness.identity
```

The global prompt slot is never consulted when a Sanctuary is active. This is not configurable. There is no override. Any code path that appends the global prompt to an active Sanctuary context is a bug.

### Harness Loader

The harness loader is responsible for reading YAML harness files, resolving extends chains, and returning a merged harness object. Rules:

- Extends chains are resolved depth-first — child values always override parent values
- Circular extends references must be detected and rejected at load time
- Missing harness files cause a hard failure — no silent fallback to defaults
- Harness files are cached in memory after first load — reloaded only when Hera writes a change

```python
def load_harness(filename):
    path = HARNESS_DIR / filename
    if not path.exists():
        raise HarnessNotFoundError(f"Harness file not found: {filename}")
    harness = parse_yaml(path)
    validate_harness_schema(harness)  # Required fields check
    return harness

def merge_harness(base, child):
    merged = deep_merge(base, child)
    # Routing rules: child rules prepended to base rules
    merged.routing = child.routing + base.routing
    # Guardrails: hard stops are additive — never removed by child
    merged.guardrails.hard_stops = base.guardrails.hard_stops + child.guardrails.hard_stops
    return merged
```

### Vault Logging Pipeline

Every conversation turn is written to the Athenaeum in real time — not batched at session end. If the session crashes or the browser closes the content up to the last turn is preserved.

```python
def log_turn(session_file, role, content, timestamp):
    turn = f"\n[{role}]: {content}\n"
    append_to_file(session_file, turn)
    # No buffering — write immediately
```

Session file creation on Sanctuary open:

```python
def create_session_file(sanctuary):
    if not sanctuary.vault_logging.enabled:
        return None
    timestamp = now_iso8601()
    filename = f"{timestamp}.md"
    path = ATHENAEUM_ROOT / sanctuary.vault_logging.path / filename
    header = build_session_header(sanctuary, timestamp)
    write_file(path, header)
    return path
```

### Routing Engine

When a god's harness routing table triggers a route_to or call action the routing engine handles execution. Zeus is the orchestrator but routing can happen laterally between gods without Zeus involvement for call actions.

```
route_to(god)     — full handoff, current god's context ends,
                    target god loads in same Sanctuary or opens new one

call(god)         — temporary invoke, result injected into current
                    god's context, current god continues

escalate(zeus)    — sends full context to Zeus for orchestration decision

suggest_sanctuary — surfaces UI prompt to user, no automatic action
```

Routing rules are evaluated top to bottom. First match wins. If no rule matches and content is in-domain the god handles it directly. If no rule matches and content is clearly out-of-domain the god returns a soft refusal with a suggestion.

### Mnemosyne Scoping

When a Sanctuary session opens Mnemosyne is initialized with the scope defined in the harness:

```python
def scope_mnemosyne(harness):
    partitions = harness.mnemosyne_scope
    if not partitions:
        # No scope defined — Mnemosyne queries full Athenaeum
        return MnemosyneClient(scope="all")
    return MnemosyneClient(scope=partitions)
```

Gods that call Mnemosyne during a session always use the scoped client. They cannot query outside their defined scope without an explicit escalation that changes the scope for that call only.

### Error Handling

| Error | Behavior |
|---|---|
| Harness file not found | Hard failure — Sanctuary does not open, user notified |
| Model unavailable | Sanctuary opens, user notified, retry option presented |
| Mnemosyne unavailable | Session continues without corpus search, limitation noted in response |
| Vault write failure | Session continues, error logged to Kronos, user notified at session end |
| Routing target not found | Soft failure — god handles in-domain content, logs routing failure to Kronos |

### Hard Rules For This Layer

- The global system prompt is never included in an active Sanctuary context. No exceptions.
- Vault log writes are real-time append operations. Never batch or buffer turn logging.
- Harness extends chains are resolved at load time, not at runtime. A session always uses a fully merged harness.
- Hard stops in a harness are evaluated before any model call. A hard stop violation never reaches the model.
- Routing rule evaluation is synchronous. A god does not begin generating a response until routing evaluation is complete.
- Session files are named by ISO 8601 timestamp. Never use user-provided names for session files.

---


## 8. The Workflow Engine

The workflow engine is Pantheon's runtime for executing multi-god task pipelines. Where a Sanctuary is a conversation with one god, a workflow is a defined sequence of gods working together to complete a task — with human-in-the-loop gates at decision points and branching logic based on outputs.

Workflows are the mechanism that makes Pantheon more than a chat interface. They encode repeatable processes so you don't have to manually orchestrate the same sequence of god interactions every time.

### What A Workflow Is

A workflow is a directed graph stored as a JSON file in /Athenaeum/Codex-Pantheon/workflows/. Each node in the graph is a god action. Each edge is a connection between actions. Gates are nodes that pause execution and wait for user input before continuing.

Workflows are authored visually in the Node Editor (Section 9) and stored as JSON. The workflow engine reads and executes that JSON. The two systems are separate — the engine can run workflows defined as raw JSON without the editor.

### Workflow JSON Structure

```json
{
  "id": "skc-lyric-review",
  "name": "SKC Lyric Review Pipeline",
  "description": "Draft a section, check corpus for repetition, review, finalize",
  "version": "1.0.0",
  "nodes": [
    {
      "id": "n1",
      "type": "god",
      "god": "apollo",
      "studio": "lyric-writing",
      "action": "draft_section",
      "input_from": "user",
      "output_to": "n2"
    },
    {
      "id": "n2",
      "type": "god",
      "god": "mnemosyne",
      "action": "similarity_check",
      "input_from": "n1",
      "output_to": "n3"
    },
    {
      "id": "n3",
      "type": "gate",
      "label": "Review similarity results",
      "message": "Mnemosyne found similar content. Review before continuing?",
      "options": ["Continue", "Revise", "Abort"],
      "output_to": {
        "Continue": "n4",
        "Revise": "n1",
        "Abort": null
      }
    },
    {
      "id": "n4",
      "type": "god",
      "god": "apollo",
      "studio": "lyric-writing",
      "action": "finalize_section",
      "input_from": "n3",
      "output_to": "n5"
    },
    {
      "id": "n5",
      "type": "vault_write",
      "codex": "Codex-SKC",
      "path": "lyrics/",
      "input_from": "n4",
      "output_to": null
    }
  ]
}
```

### Node Types

| Type | Description |
|---|---|
| god | Invokes a god with a specific action and passes input/output |
| gate | Pauses execution, presents options to user, branches based on choice |
| vault_write | Writes output to the Athenaeum at a specified path |
| vault_read | Reads content from the Athenaeum and injects into next node |
| condition | Evaluates output against a condition and branches without user input |
| transform | Reformats or reshapes data between nodes without invoking a god |
| trigger | External event that starts a workflow — file change, schedule, user action |

### Execution Model

```
Workflow loaded from JSON
        ↓
Starting node identified (type: trigger or first god node)
        ↓
Node executed — output stored in session context
        ↓
Next node determined from output_to mapping
        ↓
If gate node — execution pauses, user presented with options
        ↓
User selects option — execution resumes on mapped branch
        ↓
Continue until output_to is null (workflow end)
        ↓
Workflow result logged to Kronos
        ↓
Vault writes executed if any pending
```

### Context Passing

Each node receives the output of its input node as context. Context accumulates through the workflow — later nodes can reference outputs from any earlier node, not just the immediately preceding one. This allows a finalization node to see both the original draft and the similarity check results simultaneously.

```python
def execute_node(node, workflow_context):
    input_data = resolve_inputs(node, workflow_context)
    result = dispatch_node(node, input_data)
    workflow_context[node.id] = result
    return result
```

### Workflow Storage and Management

Workflows are stored in /Athenaeum/Codex-Pantheon/workflows/ as JSON files. They are versioned — each save increments the version field. Old versions are archived, not deleted.

Workflows are available from any Sanctuary via a workflow launcher. Zeus can invoke workflows directly when routing determines a multi-step process is required. Users can also trigger workflows manually from the UI.

### Hard Rules For This Layer

- Workflows are JSON files in the Athenaeum. They are not stored in a database.
- Gate nodes always require explicit user action. They cannot be configured to auto-resolve.
- Workflow execution is logged to Kronos in full — every node, every output, every gate decision.
- A workflow that encounters a missing god or unavailable model fails at that node and notifies the user. It does not skip nodes silently.
- Circular node references are detected at load time and rejected.
- Vault write nodes execute only after all preceding nodes have completed successfully.

---


## 9. The Node Editor

The Node Editor is the visual authoring surface for workflows. It allows workflows to be created, edited, and connected graphically without writing JSON directly. The JSON is always the source of truth — the editor reads and writes it. The editor is a Phase 3 build target. The workflow engine must be operational before the editor is built.

### What The Node Editor Is

A canvas-based drag-and-drop interface embedded in the Pantheon UI. Users place nodes on a canvas, connect them with edges, configure each node via a sidebar panel, and save the result as a workflow JSON file in the Athenaeum.

The editor is not a third-party flow tool embedded in Pantheon. It is built as part of the fork. Existing open source node editor libraries may be used as a foundation — React Flow is the recommended starting point given the frontend stack.

### Canvas Behavior

```
Left panel    — Node palette, organized by type
               (Gods, Gates, Vault, Logic, Triggers)

Center canvas — Workflow graph, drag and drop surface
               Nodes connected by directional edges
               Zoom and pan supported

Right panel   — Selected node configuration
               Context-sensitive fields based on node type
               Previews routing options and gate branches
```

### Node Configuration By Type

**God Node**
- God selector — dropdown populated from registry
- Studio selector — populated based on selected god
- Action field — what this god is being asked to do
- Input label — describes what this node expects to receive
- Output label — describes what this node will produce

**Gate Node**
- Gate message — what the user sees when execution pauses
- Options — list of branch labels (Continue, Revise, Abort, etc.)
- Branch mapping — each option connects to a target node on the canvas
- Appearance — color and icon for visual distinction on canvas

**Vault Write Node**
- Codex selector — dropdown of available Codices
- Path field — subfolder within selected Codex
- Filename — auto timestamp or custom pattern
- Format — markdown, plaintext, JSON

**Condition Node**
- Condition expression — evaluates previous node output
- True branch — node to route to if condition passes
- False branch — node to route to if condition fails
- No user interaction — executes silently

**Trigger Node**
- Trigger type — manual, scheduled, file watch, Demeter event
- Schedule field — shown only for scheduled triggers
- Watch path — shown only for file watch triggers

### Workflow Validation

Before saving, the editor validates the workflow graph:

- All nodes must have at least one incoming or outgoing edge except triggers and terminal nodes
- Gate nodes must have all options mapped to target nodes
- No circular references unless explicitly flagged as intentional loops
- All referenced gods must exist in the registry
- All vault paths must point to valid Codex folders

Validation errors are shown inline on the canvas — the offending node is highlighted and the error described in the right panel. The workflow cannot be saved with validation errors.

### Import and Export

Workflows can be exported as JSON for sharing or backup. Exported files are valid workflow JSON and can be imported directly into any Pantheon instance. This is the mechanism for sharing workflow templates between instances — including between your instance and Fia's.

### Relationship To The Workflow Engine

The editor and engine are decoupled. The engine executes JSON. The editor produces JSON. A workflow created in the editor runs identically to one written by hand. A workflow engine update never requires an editor update unless the JSON schema changes.

When the JSON schema changes the editor must be updated before the schema version is incremented in production. Old workflow files are migrated by a schema migration script, not by hand.

### Hard Rules For This Layer

- The Node Editor is Phase 3. Do not begin building it until the workflow engine is operational and tested.
- React Flow or equivalent library is used as the canvas foundation. Do not build a canvas renderer from scratch.
- The editor never modifies workflow JSON directly in the Athenaeum during editing — it works on an in-memory copy and writes only on explicit save.
- Unsaved changes are flagged visually. Navigating away from an unsaved workflow prompts confirmation.
- The raw JSON view is always accessible from the editor via a toggle. Power users can edit JSON directly and see changes reflected on the canvas.

---


## 10. Communication Protocol

This section defines how gods communicate with each other. Every inter-god message follows a standard envelope format. Hermes is the transport layer. No god communicates directly with another god by bypassing Hermes except for call actions within an active Sanctuary session where latency matters.

### The Message Envelope

Every message passed between gods uses this structure:

```json
{
  "message_id": "uuid-v4",
  "timestamp": "ISO-8601",
  "from": "apollo",
  "to": "mnemosyne",
  "action": "similarity_check",
  "session_id": "sanctuary-session-uuid",
  "workflow_id": "workflow-uuid-or-null",
  "priority": "normal",
  "payload": {
    "content": "the content being passed",
    "context": "additional context if needed",
    "metadata": {}
  },
  "response_expected": true,
  "timeout_seconds": 30
}
```

### Message Types

| Type | Description | Response Expected |
|---|---|---|
| request | God asks another god to perform an action | Yes |
| response | Reply to a request | No |
| escalation | God routes up to Zeus for orchestration | Yes |
| notification | One-way informational message — no reply needed | No |
| gate_pause | Workflow engine signals user gate required | Yes — user input |
| gate_resume | User gate resolved — workflow continues | No |
| health_check | Hestia pings a god to confirm it is alive | Yes |
| event | Demeter or file watcher signals a state change | No |

### Hermes As Transport

Hermes maintains a lightweight internal message queue. Gods publish messages to Hermes and subscribe to responses. This decouples gods from each other — Apollo does not need to know how to reach Mnemosyne directly. Apollo sends a message to Hermes addressed to Mnemosyne. Hermes delivers it.

```
Apollo → [request to Mnemosyne] → Hermes queue
                                         ↓
                               Hermes delivers to Mnemosyne
                                         ↓
                        Mnemosyne processes and responds
                                         ↓
                          Hermes delivers response to Apollo
```

For call actions within an active Sanctuary session where latency is a concern, gods may invoke each other directly via the routing engine without going through the full Hermes queue. This is the exception, not the rule.

### Escalation To Zeus

When a god cannot resolve a request within its domain it escalates to Zeus with full context:

```json
{
  "from": "apollo",
  "to": "zeus",
  "action": "escalate",
  "payload": {
    "original_request": "...",
    "reason": "request_outside_domain",
    "suggested_god": "hephaestus",
    "context": "user appears to be asking about infrastructure"
  }
}
```

Zeus evaluates the escalation and either routes to the suggested god, routes elsewhere, or handles directly if it falls under orchestration. Zeus logs every escalation decision to Kronos.

### Kronos Logging

Every message that passes through Hermes is logged to Kronos with full envelope contents. This creates a complete audit trail of all inter-god communication. Kronos logs are append-only and stored in /Athenaeum/Codex-Pantheon/sessions/kronos/.

Log entries are structured for queryability — timestamp, from, to, action, session_id, and outcome are indexed fields. Full payload is stored but not indexed.

### Iris Notifications

When a background god needs to surface information to the user it does not interrupt the active session directly. It sends a notification message to Iris. Iris holds notifications and surfaces them at appropriate moments — between conversation turns, at session end, or immediately if priority is urgent.

```json
{
  "from": "hestia",
  "to": "iris",
  "action": "notify_user",
  "payload": {
    "message": "Mnemosyne re-embedding completed for Codex-SKC",
    "priority": "low",
    "surface_at": "next_turn_end"
  }
}
```

Priority levels:

| Priority | Behavior |
|---|---|
| urgent | Surfaces immediately, interrupts if necessary |
| normal | Surfaces between turns |
| low | Surfaces at session end or next natural pause |
| silent | Logged to Kronos only, never shown to user |

### Hard Rules For This Layer

- Every inter-god message uses the standard envelope. No freeform god-to-god communication.
- Hermes is the default transport. Direct god invocation is permitted only for synchronous call actions within an active session.
- All messages are logged to Kronos. No silent inter-god communication.
- Timeouts are always defined. A god waiting for a response that never comes fails gracefully after timeout_seconds and logs the failure.
- Iris is the only path to the user from background gods. Background gods never write directly to the active session.
- Escalations always include a reason and suggested routing. Zeus never receives a blank escalation.

---


## 11. Build Phases

This section defines what gets built in what order. Phases are sequential — do not begin a phase until the previous phase is complete and verified. Each phase produces a working system that is useful on its own before the next phase begins.

AI assistants must check the Version History section before starting any build work. The version history defines current state. Do not re-implement anything already marked complete.

### Phase 1 — Foundation
**Target version: v1.0.0**
Goal: A working local Pantheon instance on the primary workstation with core conversational gods, the Athenaeum structure, basic knowledge retrieval, and vault logging.

```
Athenaeum
├── Create folder structure for all defined Codices
├── Initialize all /distilled/ and /archive/ subfolders
├── Initialize Codex-Inbox with processing subfolders
└── Verify read/write from CachyOS workstation

Harness System
├── Define and validate harness YAML schema
├── Write base harness files for Phase 1 gods
│   ├── zeus-base.yaml
│   ├── hecate-base.yaml
│   ├── apollo-base.yaml
│   ├── hephaestus-base.yaml
│   ├── athena-base.yaml
│   ├── hermes-base.yaml
│   ├── hestia-base.yaml
│   ├── demeter-base.yaml
│   └── kronos-base.yaml
├── Write studio harness files
│   ├── apollo-lyric-writing.yaml
│   ├── apollo-poetry.yaml
│   ├── hephaestus-project-scoping.yaml
│   ├── hephaestus-program-design.yaml
│   └── hephaestus-infrastructure-planning.yaml
└── Implement harness loader with extends resolution

Ollama
├── Verify Ollama running on workstation
├── Pull primary model (Gemma 4)
├── Pull nomic-embed-text for Mnemosyne
└── Verify inference working

Mnemosyne (Phase 1 — Chroma)
├── Install and configure Chroma via Docker Compose
├── Implement embedding pipeline for Athenaeum files
├── Implement Codex partition scoping via metadata tags
├── Initial embedding run across all Athenaeum content
└── Verify semantic search returning expected results

Open WebUI Fork — Phase 1 Minimal
├── Fork Open WebUI repository under Duskript identity
├── Remove global system prompt field from UI
├── Implement Sanctuary config file structure
├── Implement harness loader integration
├── Implement prompt isolation — harness replaces global prompt
├── Implement basic Sanctuary selector as primary navigation
├── Implement vault logging pipeline (real-time append)
└── Verify prompt isolation with Apollo and Hephaestus Sanctuaries

Background Gods (script/service drivers)
├── Hestia — health check script for all services
├── Demeter — file watcher and cron scheduler
└── Kronos — log pipeline writing to Codex-Pantheon/sessions/kronos/

Verify Phase 1 Complete
├── Open Hecate Sanctuary — general chat working
├── Open Apollo/Lyric Writing — harness isolated, SKC corpus searchable
├── Open Hephaestus/Project Scoping — harness isolated
├── Open Athena/Knowledge Query — vault retrieval working
├── Confirm session files appearing in correct Codex folders
├── Confirm Hestia reporting health status
└── Confirm Kronos logging all activity
```

### Phase 2 — Connective Tissue
**Target version: v2.0.0**
Goal: Gods communicate with each other. Context switching works. The underworld runs nightly. Enforcement is active.

```
Communication Protocol
├── Implement Hermes message queue
├── Implement standard message envelope
├── Implement escalation path to Zeus
└── Implement Iris notification system with priority levels

Hecate — Context Classifier
├── Implement silent intent classification
├── Implement context profile generation
├── Implement routing suggestion UI in Hecate Sanctuary
└── Verify Hecate correctly identifies domain signals

Underworld Cluster
├── Hades — nightly consolidation job
│   ├── Flagging logic for consolidation candidates
│   ├── Ollama summarization prompt chain
│   └── Write-back to /distilled/ folders
├── Charon — file transfer pipeline to archive
├── Persephone — retrieval from archive
└── The Fates — data lifecycle evaluation rules

Governance
├── Hera — config state management service
├── Hera UI — graphical settings interface in fork
│   ├── Codex management forms
│   ├── God and studio management forms
│   ├── Harness editor with routing rule builder
│   └── Sanctuary creation and editing forms
└── Ares — enforcement rules for domain boundary violations

Mnemosyne Upgrade
├── Migrate from Chroma to Qdrant
├── Verify all partitions intact after migration
└── Verify query performance improvement

Verify Phase 2 Complete
├── Confirm inter-god message passing via Hermes
├── Confirm Hades running nightly and producing distilled content
├── Confirm Hera UI creating and editing gods/sanctuaries/harnesses
├── Confirm Ares blocking out-of-domain requests
└── Confirm Iris surfacing notifications correctly
```

### Phase 3 — Workflow Engine and Node Editor
**Target version: v3.0.0**
Goal: Repeatable multi-god workflows. Visual authoring surface.

```
Workflow Engine
├── Implement workflow JSON schema and validator
├── Implement node execution dispatcher
├── Implement context passing between nodes
├── Implement gate node pause/resume
├── Implement condition node branching
├── Implement vault read/write nodes
└── Test with hand-written workflow JSON

Node Editor
├── Integrate React Flow as canvas foundation
├── Implement node palette with all node types
├── Implement node configuration sidebar
├── Implement edge connection and branch mapping
├── Implement workflow validation on save
├── Implement JSON view toggle
└── Implement import/export

Verify Phase 3 Complete
├── Build SKC Lyric Review Pipeline in node editor
├── Execute workflow end to end
├── Confirm gate nodes pause and branch correctly
└── Confirm vault write at workflow end
```

### Phase 4 — Homelab Migration and External Bridges
**Target version: v4.0.0**
Goal: Move always-on services to homelab. Enable external knowledge access.

```
Homelab Server Build
├── Install Proxmox on homelab hardware
├── Configure VMs for Pantheon services
├── Migrate Ollama inference to homelab GPU
├── Migrate Mnemosyne/Qdrant to homelab
├── Migrate background gods to homelab
├── Configure Tailscale for seamless workstation access
└── Verify workstation frontend connects to homelab backend

Prometheus — External Bridge
├── Implement controlled external API access
├── Web search integration for research gods
├── Gate all external calls through approval system
└── Verify Caduceus and Apollo can access external references

Caduceus
├── Write caduceus-base.yaml harness
├── Write studio harnesses for medical-research and health-reference
├── Create Codex-Asclepius structure
└── Verify medical research corpus search working

Verify Phase 4 Complete
├── Confirm all services running on homelab
├── Confirm workstation UI connects via Tailscale
├── Confirm Prometheus gating external calls correctly
└── Confirm Caduceus operational with Codex-Asclepius
```

### Phase 5 — Personalization and Distribution
**Target version: v5.0.0**
Goal: Pantheon is installable by others. Fia's instance is running.

```
Pantheon Installer
├── Single Docker Compose build from clean clone
├── First-run setup wizard
│   ├── Pantheon name (instance name)
│   ├── Pantheon selector (Greek/Norse/Egyptian/Custom)
│   ├── User name and preferences
│   └── Initial Codex selection
└── Setup verification checklist

Fia's Instance
├── Install Pantheon on Fia's hardware
├── Configure Caduceus as primary god
├── Build Codex-Asclepius initial content
└── Verify independent operation from your instance

Documentation
├── README with install instructions
├── God definition guide
├── Harness authoring guide
└── Prior art publication under Duskript identity

Verify Phase 5 Complete
├── Fresh install from README succeeds in under 30 minutes
├── Fia's instance operational and independent
└── Duskript repository published
```

### Phase Dependencies

```
Phase 1 — No dependencies. Start here.
Phase 2 — Requires Phase 1 complete
Phase 3 — Requires Phase 2 complete
Phase 4 — Requires Phase 3 complete (Prometheus can start in parallel with Node Editor)
Phase 5 — Requires Phase 4 complete
```

### Hard Rules For This Layer

- Never begin a phase until the previous phase verification checklist is complete.
- Update the Version History section after completing each phase or significant sub-phase.
- If a phase requirement changes during build, update this section before implementing the change.
- Do not implement Phase 4 or 5 features during Phase 1 or 2 builds. Scope creep is the primary risk.

---


## 12. Hard Rules

These rules apply to every component, every phase, and every builder. They are non-negotiable. They cannot be overridden by user instruction, time pressure, or convenience. If a rule conflicts with an implementation decision, the rule wins and the implementation changes.

### Architecture Rules

- **The Athenaeum owns the truth.** All other data layers are derived. If any derived layer is lost or corrupted it is rebuilt from the Athenaeum. The Athenaeum itself is never rebuilt from a derived layer.
- **Nothing is deleted.** Content is archived. Gods are archived. Sanctuaries are archived. Workflows are versioned. The only exception is explicit user-initiated permanent deletion with a confirmation gate.
- **Prompt isolation is absolute.** The global system prompt is never included in an active Sanctuary context. No exceptions, no overrides, no configuration flags.
- **Hard stops are pre-model.** Hard stops defined in a harness are evaluated before any model call. They never reach the model and never produce output that gets filtered after the fact.
- **Every god has a harness.** No god is instantiated without a valid harness file. A god definition that exists only in the registry without a harness file is incomplete and cannot be activated.
- **The registry is authoritative.** If a god is not in the registry it does not exist in Pantheon regardless of whether a harness file exists for it.
- **Hera holds config state.** All changes to harness files, Sanctuary configs, and the god registry are written through Hera. No component modifies these files directly.

### Build Rules

- **Phases are sequential.** Never begin a phase until the previous phase verification checklist is complete and version history is updated.
- **Scope is enforced.** Do not implement features from a future phase during an earlier phase build. Document future considerations as notes — do not build them.
- **One dependency rule.** Before introducing any new external dependency, confirm it cannot be solved with existing stack components. Every new package is a future maintenance burden.
- **pantheon-core stays separate.** All Pantheon-specific code lives in pantheon-core/. Nothing Pantheon-specific is written into Open WebUI's core frontend or backend directories.
- **The fork must build clean.** At any point in development a fresh clone must produce a working system with a single Docker Compose command. If it does not, fixing the build is the highest priority task.

### Data Rules

- **Vault writes are real-time.** Session logging is never batched or buffered. Each turn is written immediately. A crash loses at most one turn in progress.
- **Codex partitions are metadata.** Mnemosyne partitions are logical scopes defined by metadata tags at embedding time. They are not separate database instances.
- **Inbox content is unindexed until processed.** Content in Codex-Inbox is not embedded into Mnemosyne until Hermes classifies and routes it to a destination Codex.
- **Distillation preserves originals.** When Hades distills content, original notes move to /archive/ — they are never deleted. The distilled version is a new file, not a replacement.

### Communication Rules

- **All inter-god messages use the standard envelope.** No freeform god-to-god communication outside the defined message format.
- **All messages are logged.** Kronos receives every inter-god message. There is no silent communication between gods.
- **Background gods use Iris.** Background gods never write directly to an active session. Iris is the only path from a background god to the user.
- **Escalations are never empty.** Every escalation to Zeus includes a reason, context, and suggested routing target.
- **Timeouts are always defined.** No god waits indefinitely for a response. Every request has a timeout_seconds value.

### Security and Privacy Rules

- **External calls are intentional.** All outbound requests route through Prometheus. No god makes external network calls directly.
- **External calls require gate approval.** Session-level approval is the minimum for external calls. Silent external calls are not permitted.
- **No credentials in harness files.** API keys, passwords, and secrets are never stored in harness YAML files. They are stored in environment variables or a secrets manager.
- **Tailscale is the network boundary.** Pantheon services are not exposed to the public internet. Access is via Tailscale only.

### Version and Documentation Rules

- **Version history is append-only.** Existing version entries are never modified. New entries are always appended below existing ones.
- **The bootstrap entry is permanent.** The bootstrap rule in the Version History section is never deleted or modified regardless of how many versions accumulate below it.
- **Constitution updates precede implementation.** If a build decision requires changing the architecture, update the relevant constitution section before writing code.
- **The What Does Not Exist Yet list is maintained.** As components are built the list is updated to reflect actual current state. A builder should always be able to read this list and know exactly what exists.

---

## 13. Version History

### BOOTSTRAP RULE
If this section contains only this entry, nothing has been built yet. This is a greenfield project. Do not assume any component exists. Begin at Phase 1, Step 1 of Section 11. After completing your first build session, append a version entry below the divider. Never delete or modify this bootstrap entry.

The version format is:
```
### v[MAJOR].[MINOR].[PATCH] — [Short Title]
Date: [ISO 8601]
Phase: [Phase number and status]
Completed:
- [what was built or fixed]
Known Issues:
- [anything incomplete or broken]
Next:
- [recommended next steps]
```

---

### v0.1.0 — Harness Loader
Date: 2026-04-18
Phase: 1 — In Progress
Completed:
- Athenaeum folder structure created for all Phase 1 Codices
- All Phase 1 base harness YAML files written (zeus, hecate, apollo, hephaestus, athena, hermes, hestia, demeter, kronos)
- Studio harness YAML files written (apollo-lyric-writing, apollo-poetry, hephaestus-project-scoping, hephaestus-program-design, hephaestus-infrastructure-planning)
- Harness loader implemented (loader.py) with extends resolution, circular reference detection, caching, and cache invalidation
- Schema validator implemented (schema.py) with driver-specific field rules and routing/guardrail validation
- Custom exceptions defined (exceptions.py)
- All 5 loader tests passing
Known Issues:
- None
Next:
- Open WebUI fork setup — Phase 1 minimal frontend work
- Sanctuary config file structure
- Prompt isolation implementation






