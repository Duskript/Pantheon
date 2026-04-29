# Pantheon — Build Phases

> Source: Constitution Section 11
> Read this document when: starting any build session, determining what to build next, or verifying phase completion. Check STATE.md first to know current phase status before reading this document.

---

## Rules For Builders

- Never begin a phase until the previous phase verification checklist is complete and version history is updated.
- Check the Version History in STATE.md before starting any build work. Do not re-implement anything already marked complete.
- If a phase requirement changes during build, update the relevant constitution document before implementing the change.
- Do not implement Phase 4 or 5 features during Phase 1 or 2 builds. Scope creep is the primary risk.

---

## Phase Dependencies

```
Phase 1 — No dependencies. Start here.
Phase 2 — Requires Phase 1 complete
Phase 3 — Requires Phase 2 complete
Phase 4 — Requires Phase 3 complete (Prometheus can start in parallel with Node Editor)
Phase 5 — Requires Phase 4 complete
```

---

## Phase 1 — Foundation
**Target version: v1.0.0**
Goal: A working local Pantheon instance on the primary workstation with core conversational gods, the Athenaeum structure, basic knowledge retrieval, and vault logging.

```
Athenaeum
├── Create Athenaeum.scaffold/ in repo with all Codex folder stubs
├── Write INDEX.md.template for root and each Codex
├── Write init-athenaeum.sh to build real Athenaeum from scaffold
├── Add .gitignore entries for Athenaeum/ and Staging/
├── Run init-athenaeum.sh — verify real Athenaeum created at ~/Pantheon/
├── Verify Staging/ created with inbox/, processing/, rejected/
└── Verify read/write from CachyOS workstation

Harness System
├── Define and validate harness YAML schema
├── Define initial schema_version (v1) and document all required fields
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
├── Implement harness loader with extends resolution
├── Implement schema_version validation — fail loudly on mismatch
├── Implement structured error reporting with field-level diff and fix suggestions
├── Implement Iris notification for schema mismatch errors
├── Implement Hera warning badge for affected harnesses
└── Write scripts/migrate-harness.sh — single-file schema migration tool

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
├── Remove Open WebUI built-in auth system
├── Implement Pantheon auth layer
│   ├── First-run setup wizard — create owner account before app is accessible
│   ├── Token-based session management
│   ├── Trusted device flag — set at first login per device, managed via Hera
│   ├── 7-day inactivity timeout for untrusted devices
│   ├── User/session/role data model (owner active, collaborator/guest defined)
│   └── Write scripts/reset-auth.sh — CLI credential reset tool
├── Implement Sanctuary config file structure
├── Implement harness loader integration
├── Implement prompt isolation — harness replaces global prompt
├── Implement basic Sanctuary selector as primary navigation
├── Implement vault logging pipeline (real-time append)
└── Verify prompt isolation with Apollo and Hephaestus Sanctuaries

Background Gods (script/service drivers)
├── Hestia — health check script for all services
├── Demeter
│   ├── inotify file watcher on live Codex paths
│   ├── 5-second settle window — batch events before firing
│   ├── Pause/resume signal handler via Hermes for bulk operations
│   ├── Index regeneration with retry-once failure handling
│   ├── Iris notification on regeneration failure
│   └── Cron scheduler for nightly Hades, The Fates, and backup jobs
└── Kronos — log pipeline writing to Codex-Pantheon/sessions/kronos/

Backup — Phase 1 State
├── Document known gap — no off-machine backup until homelab is online (Phase 4)
├── Btrfs/Snapper on workstation provides implicit local snapshot recovery
├── Implement backup script (covers ~/Pantheon/ and harnesses/)
├── Implement Hera backup config UI — target, schedule, enable/disable, status, manual trigger
└── Demeter schedules nightly backup run alongside Hades and The Fates

Verify Phase 1 Complete
├── Open Hecate Sanctuary — general chat working
├── Open Apollo/Lyric Writing — harness isolated, SKC corpus searchable
├── Open Hephaestus/Project Scoping — harness isolated
├── Open Athena/Knowledge Query — vault retrieval working
├── Confirm session files appearing in correct Codex folders
├── Confirm Hestia reporting health status
└── Confirm Kronos logging all activity
```

---

## Phase 2 — Connective Tissue
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
│   ├── Rollback instruction interface
│   └── Write-back of distilled content to Codex /distilled/ folders
├── Charon — file move pipeline (bidirectional)
│   ├── Moves source files to /archive/asphodel/ on distillation
│   ├── Moves distilled versions to /archive/elysium/ on rollback
│   ├── Moves content to /archive/tartarus/ on condemnation
│   ├── Executes permanent deletion from Tartarus on Fates instruction
│   ├── Maintains versioned ARCHIVE_INDEX.md per Codex
│   └── Notifies Mnemosyne of stale vectors on every move
├── Persephone — retrieval from Asphodel and Elysium for Hades review
└── The Fates — data lifecycle evaluation (nightly to weekly schedule)
    ├── Asphodel entries older than 6 months → condemn to Tartarus
    └── Tartarus entries older than 3 months → purge via Charon

Governance
├── Hera — config state management service
├── Hera UI — graphical settings interface in fork
│   ├── Codex management forms
│   ├── God and studio management forms
│   ├── Harness editor with routing rule builder
│   ├── Sanctuary creation and editing forms
│   └── Prometheus config — enable/disable per god, approval mode per god
└── Ares — enforcement rules for domain boundary violations

Prometheus — Phase 2 Foundation
├── Write prometheus-base.yaml harness
├── Implement web search execution (script driver)
├── Implement per-god permission enforcement
├── Implement approval mode handling (once per session / every call / always accessible)
├── Implement Iris approval prompt for gated calls
├── Implement result staging to Staging/inbox/ after successful call
└── Implement Kronos logging for all calls

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

---

## Phase 3 — Workflow Engine and Node Editor
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

---

## Phase 4 — Homelab Migration and External Bridges
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
├── Configure Syncthing — sync ~/Pantheon/ and harnesses/ from workstation to Proxmox
├── Proxmox handles backup from Syncthing target (personal setup, outside Pantheon scope)
└── Verify workstation frontend connects to homelab backend

Prometheus — Phase 4 Extension
├── Verify Prometheus operational on homelab
├── Enable web search access for Caduceus and Apollo in Hera
└── Verify external reference lookups working for research gods

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

---

## Phase 5 — Personalization and Distribution
**Target version: v5.0.0**
Goal: Pantheon is installable by others. Fia's instance is running.

```
Pantheon Installer
├── Single Docker Compose build from clean clone
├── First-run setup wizard
│   ├── Auth setup — create owner account (built in Phase 1, surfaced here for new installs)
│   ├── Pantheon name (instance name)
│   ├── Pantheon selector (Greek/Norse/Egyptian/Custom)
│   ├── User name and preferences
│   ├── Initial Codex selection
│   └── Backup target setup — local path, Syncthing, or cloud (OneDrive/Google Drive via rclone)
└── Setup verification checklist

Backup — Phase 5 Additions
├── Implement cloud backup connector (rclone — OneDrive/Google Drive)
├── Surface cloud backup option in Hera backup config UI
└── Document cloud backup encryption as future work — not implemented in Phase 5

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
