# Pantheon — The Sanctuary System

> Source: Constitution Sections 5, 6, 7
> Read this document when: working on the Open WebUI fork, prompt assembly, vault logging, Sanctuary config files, Hera UI, or the session lifecycle.

---

## Section 5 — The Sanctuary System

A Sanctuary is Pantheon's equivalent of a workspace or project. It is the room you work in. Each Sanctuary is bound to a specific god and optionally a specific studio. Opening a Sanctuary means you are talking to that god, in that specialization, with that scoped knowledge — and nothing else bleeds in.

Sanctuaries replace the workspace system in the Open WebUI fork. They are not workspaces with a different name. They are architecturally distinct — prompt isolation, harness loading, and vault logging are first-class features, not configurations.

### What A Sanctuary Contains

Every Sanctuary is defined by a configuration file stored in `/Athenaeum/Codex-Pantheon/harnesses/sanctuaries/`.

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

**Session level** — user can approve all gates of a specific type for the duration of the current session. Session-level approvals do not persist after the session closes.

**Instance level** — single approval for a single triggered gate. Default behavior when no session-level approval is active.

The UI must present a clear option at each gate trigger: **Approve Once / Approve for This Session / Always Auto-Approve**. The third option modifies the harness default and requires confirmation before saving.

Gates defined as `require_approval` for external calls cannot be silently bypassed.

### Hera — The Settings Interface

Hera is not just a background config service. She is the primary settings and administration interface for all of Pantheon. When you need to create, edit, or manage any god, studio, harness, or Sanctuary — you go to Hera.

Hera lives as a dedicated section in the Pantheon UI, accessible from any Sanctuary via a persistent settings entry point. She presents everything through forms, dropdowns, and visual editors. No YAML knowledge is required to operate Pantheon.

**Hera's interface covers:**

*Codices* — view, create, edit, archive Codices; trigger manual Mnemosyne re-embedding. New Codex creation automatically creates folder structure, registers Mnemosyne partition, and makes the Codex available as a vault_path option.

*Gods* — view all registered gods and their current status; create, edit, or archive gods via guided form.

*Studios* — view, create, edit, enable, or disable studios per god.

*Harnesses* — view raw YAML with syntax highlighting; edit any field via form; routing rule builder (visual if/then editor); guardrail manager; driver selector.

*Sanctuaries* — view all Sanctuaries grouped by god; create, edit, configure gates, or archive Sanctuaries.

*Registry* — view the full god registry; reorder gods in the Sanctuary selector; set a default Sanctuary.

*Backup* — configure and monitor the Pantheon backup system.
- **Backup target** — local path, Syncthing, or cloud (OneDrive/Google Drive — Phase 5)
- **Schedule** — configurable; nightly by default; runs alongside Hades and The Fates
- **Enable/disable toggle** — backup is opt-in, not forced
- **Last backup status** — timestamp and result of most recent backup run
- **Manual trigger** — run a backup immediately without waiting for the schedule

Backup covers `~/Pantheon/` and the repo's `harnesses/` directory. Execution is a background script configured by Hera and scheduled by Demeter. Cloud backup encryption is a future consideration — not in current scope.

**The raw YAML is always one click away** for users who prefer direct editing. Hera never hides the underlying files.

All changes made through Hera are written to `/Athenaeum/Codex-Pantheon/harnesses/` and propagated to active gods. Changes to a currently active Sanctuary take effect on next session open.

### Sanctuary Types

| Type | Description | Example |
|---|---|---|
| Conversational | Primary working Sanctuaries — user talks to god directly | The Studio, The Forge |
| Monitoring | Read-only status views for subsystem gods | Hestia Dashboard |
| Workflow | Node-based workflow execution surface | Pantheon Workflows |
| Admin | Hera config management, registry editing | Olympus Control |

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

Hecate as front door does not replace her role as silent context classifier for other Sanctuaries. She operates in both modes — visible generalist when talking to her directly, invisible classifier when another Sanctuary is active.

### Disambiguation Protocol — Conflicting Domain Signals

When Hecate detects that a request has valid signals for more than one god's domain, she consults Zeus internally before responding. Zeus is never visible to the user in this exchange — Hecate is the sole mouthpiece.

```
Ambiguous request lands with Hecate
        ↓
Hecate detects conflicting domain signals
        ↓
Hecate consults Zeus (silent — not visible to user)
        ↓
Zeus evaluates candidate gods and returns routing options with reasoning
        ↓
Hecate surfaces disambiguation to user in her own voice
        ↓
User selects → Hecate suggests the Sanctuary (no hard switch)
User answers naturally → Zeus re-evaluates, Hecate routes silently
User dismisses → Hecate handles it herself, conversation continues
```

The disambiguation message is delivered in Hecate's voice — tongue-in-cheek, on-brand, with the candidate gods named explicitly so the user understands what they're choosing between:

```
User: "I want to set up a dedicated space for recording"
Hecate: "Looks like we've got an argument between gods on this one —
         are you thinking creatively (Apollo) or technically (Hephaestus)?"
         [Apollo — Creative] [Hephaestus — Technical] [Keep talking to me]
```

The candidate gods surfaced are always contextual to the actual conflict — not a generic creative/technical binary. Zeus determines which gods are in contention; Hecate frames the question.

**Dismissal behavior:** If the user dismisses or ignores the disambiguation, Hecate continues the conversation in her general capacity. No routing is forced. The request is not held or repeated.

**Natural resolution:** If the user's next message makes the domain unambiguous without explicitly choosing, Zeus re-evaluates and Hecate routes silently with a soft confirmation — no second disambiguation prompt.

### Hard Rules — Sanctuary System

- Every Sanctuary must reference a valid harness file. A Sanctuary cannot be created without one.
- Prompt isolation is non-negotiable. No global prompt bleeds into an active Sanctuary.
- Vault logging path must point to a valid Codex folder. Logging to arbitrary paths is not permitted.
- Gates defined as require_approval cannot be changed to auto_approve for external calls.
- Sanctuaries are not deleted — they are archived. A Sanctuary's chat history persists in the Athenaeum even if the Sanctuary is retired.

---

## Section 6 — The Open WebUI Fork

Pantheon is built on a fork of Open WebUI. This section defines what Open WebUI provides that is worth keeping, what gets rebuilt, and what gets removed.

### What Open WebUI Provides (Keep As-Is)

- Ollama integration and model management
- HuggingFace model import pipeline
- Basic inference pipeline and streaming responses
- Tailscale-accessible web interface
- Mobile-responsive UI foundation
- Basic chat history storage
- RAG pipeline hooks (replaced but the hook points are useful)

### What Gets Rebuilt

| Component | Open WebUI Original | Pantheon Replacement |
|---|---|---|
| Workspaces | Generic workspaces with shared prompt bleed | Sanctuary system with full harness isolation |
| System prompt handling | Global prompt appended to all contexts | Harness file replaces global prompt per Sanctuary |
| RAG pipeline | Built-in RAG with limited scoping | Mnemosyne with Codex partition scoping |
| Settings interface | Generic model and account settings | Hera — full god, studio, harness, Sanctuary, Codex management |
| Chat logging | Internal DB only | Dual write — internal DB and Athenaeum markdown |
| Model selector | Per-conversation dropdown | Per-Sanctuary assignment via harness file |
| Navigation | Chat history sidebar | Sanctuary selector as primary navigation |

### What Gets Removed (Remove Cleanly — No Dead Code)

- Default workspace system and all workspace-related UI
- Global system prompt field in settings
- Any built-in agent or tool-use implementations that conflict with the harness model
- Default RAG implementation (replaced by Mnemosyne)
- Open WebUI's built-in auth system (replaced — see Authentication below)

### Authentication

Tailscale is the network boundary — Pantheon is never exposed to the public internet. App-level auth sits on top of Tailscale as a second gate protecting unattended device sessions.

**First-run setup** creates the owner account before anything else in Pantheon is accessible. Username and password are set here. This happens at Phase 1 first-run, not Phase 5.

**Session behavior by device type:**

| Device | Session Type | Timeout |
|---|---|---|
| Trusted (e.g. primary desktop) | Persistent | None — stays logged in until explicit logout |
| Untrusted (e.g. mobile, guest device) | Inactivity timeout | 7 days of inactivity triggers re-auth |

**Trusted device flag** — set per device at first login. Managed through Hera. A device can be trusted or untrusted at any time after the fact.

**Password recovery** — no email-based reset. Recovery is handled by a CLI script on the host machine. If you have physical or SSH access to the machine you can reset credentials. If you don't have that access, you shouldn't be able to reset anyway.

```bash
# scripts/reset-auth.sh
# Resets owner credentials. Requires host machine access.
# Usage: ./scripts/reset-auth.sh
```

**User roles** — defined from day one to support future multi-user without a rewrite:

| Role | Status | Description |
|---|---|---|
| owner | Active | Full access, all Hera controls, single user in single-user mode |
| collaborator | Defined, not activatable | Read/write access to designated Codices — enabled via Hera when multi-user is turned on |
| guest | Defined, not activatable | Read-only access — enabled via Hera when multi-user is turned on |

**Multi-user** is a deliberate opt-in action through Hera. It is never enabled by accident. When enabled, Hera exposes user management forms that are hidden in single-user mode. The underlying user/session/permission data model exists from Phase 1 — enabling multi-user is additive, not structural.

### Fork Identity

The fork is maintained under the Duskript GitHub identity. It is a hard fork that diverges intentionally. Upstream Open WebUI changes are evaluated manually before merging. Security patches from upstream should be reviewed and applied within 14 days. Feature updates from upstream are ignored unless they address a specific gap.

### Repository Structure

```
pantheon/                     ← git repo root
├── .gitignore
├── CLAUDE.md                 ← auto-read by Claude Code
├── .planning/                ← all planning docs
├── pantheon-core/            ← all Pantheon-specific code
│   ├── harness/
│   ├── sanctuary/
│   ├── routing/
│   ├── vault/
│   └── gods/
├── frontend/                 ← forked Open WebUI frontend
├── backend/                  ← forked Open WebUI backend
├── harnesses/                ← harness YAML files (tracked in git)
├── Athenaeum.scaffold/       ← empty folder templates (tracked in git)
│   └── [Codex stubs with INDEX.md.template per folder]
├── scripts/
│   ├── init-athenaeum.sh
│   └── docker-compose.yml
└── docs/
```

Real Athenaeum and Staging live **outside the repo entirely** at `~/Pantheon/` — never in git.

### .gitignore Minimum Required Entries

```gitignore
# Athenaeum — personal knowledge store, never in git
Athenaeum/

# Staging — unprocessed content
Staging/

# Environment and secrets
.env
*.env
secrets/

# Local config overrides
config.local.yaml

# Runtime and cache
__pycache__/
*.pyc
.chroma/
.qdrant/
node_modules/
```

### UI and Visual Identity

- Primary navigation replaced by the Sanctuary selector
- Hera accessible as a persistent settings entry point from any screen
- Each Sanctuary has a configurable accent color and icon defined in its config file
- The default Open WebUI branding, color scheme, and logo are replaced entirely
- Typography, spacing, and component styling are updated to reflect Pantheon's identity
- The chat interface itself remains largely unchanged — it is functional and does not need redesign
- The global system prompt field is removed from the UI entirely — not hidden, removed

### Fork Hard Rules

- Never modify Open WebUI's core inference pipeline. Route around it, don't change it.
- All Pantheon-specific code lives in `pantheon-core/`. Nothing Pantheon-specific is written into the Open WebUI frontend or backend directories directly — use hooks and extension points.
- The fork must remain buildable from a clean clone with a single Docker Compose command.
- Upstream security patches are reviewed within 14 days of release.
- Minimize new dependencies. Every new package is a future maintenance burden.
- Prefer Python for backend additions. Prefer vanilla JS or existing frontend framework for UI additions — do not introduce a second frontend framework.
- Docker Compose for all service orchestration. No Kubernetes, no swarm.

---

## Section 7 — Sanctuary Architecture

This section defines how Sanctuaries are implemented at the code level. It covers prompt assembly, harness loading, vault logging pipeline, and session lifecycle.

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

- Extends chains are resolved depth-first — child values always override parent values
- Circular extends references must be detected and rejected at load time
- Missing harness files cause a hard failure — no silent fallback to defaults
- Harness files are cached in memory after first load — reloaded only when Hera writes a change

### Vault Logging Pipeline

Every conversation turn is written to the Athenaeum in real time — not batched at session end.

```python
def log_turn(session_file, role, content, timestamp):
    turn = f"\n[{role}]: {content}\n"
    append_to_file(session_file, turn)
    # No buffering — write immediately

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

```python
def scope_mnemosyne(harness):
    partitions = harness.mnemosyne_scope
    if not partitions:
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

### Hard Rules — Sanctuary Architecture

- The global system prompt is never included in an active Sanctuary context. No exceptions.
- Vault log writes are real-time append operations. Never batch or buffer turn logging.
- Harness extends chains are resolved at load time, not at runtime.
- Hard stops in a harness are evaluated before any model call. A hard stop violation never reaches the model.
- Routing rule evaluation is synchronous. A god does not begin generating a response until routing evaluation is complete.
- Session files are named by ISO 8601 timestamp. Never use user-provided names for session files.
