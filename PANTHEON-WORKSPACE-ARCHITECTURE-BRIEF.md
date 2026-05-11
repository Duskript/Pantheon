# Pantheon architecture brief for Workspace integration

This document explains the underlying Pantheon layout so a frontend agent (for example Codex working on a Hermes Workspace fork) can wire itself correctly.

## 1. What Pantheon is

Pantheon is not a separate replacement for Hermes Agent. It is a layered system built on top of Hermes Agent.

Think of it as:

1. Hermes Agent = runtime engine
   - profiles
   - sessions
   - tools
   - gateway/API server
   - cron/memory/skills/tool calling

2. Pantheon = multi-agent architecture and shared knowledge layer on top of Hermes
   - named agents called “gods”
   - harness files defining identity/routing/guardrails
   - a shared knowledge system (Athenaeum + Mnemosyne)
   - inter-god messaging
   - Pantheon-specific MCP tools

So the frontend should not treat Pantheon as a monolithic app server. It is a composition of:
- Hermes API/gateway processes
- Pantheon MCP server
- shared files/repos/configs
- optional frontend(s)

## 2. The proxy layer (LiteLLM)

Between Hermes gateways and model providers sits an optional but recommended **model proxy layer** running LiteLLM on the U55.

### What it does

Rather than each Hermes gateway (root, Hephaestus, Apollo, etc.) connecting directly to different model providers with different API structures, all gateways point at a single LiteLLM endpoint. LiteLLM inspects the `model` field in each incoming request and routes it to the correct provider backend.

```
Hermes (model: deepseek-v4-flash:cloud) ──┐
                                          │
Hephaestus (model: kimi-k2.6:cloud) ──────┤──► LiteLLM @ pantheon:4000 ──► Ollama Cloud
                                          │                              └─► Anthropic
Apollo (model: claude-sonnet-4) ──────────┘                              └─► OpenAI
```

### How profiles still work

Each god's Hermes profile specifies:
- `provider: openai` (LiteLLM speaks OpenAI-compatible API)
- `base_url: http://pantheon:4000` (single LiteLLM endpoint on U55)
- `model: <whatever>` (this is what LiteLLM uses to decide where to route)

So each god keeps its own model but hits the same endpoint. LiteLLM's `config.yaml` on the U55 defines the routing table that maps model names to actual provider backends.

### Why this matters for the frontend

- **Single integration point** — the frontend only needs to know about one model endpoint
- **Runtime model swapping** — changing a god's model becomes a LiteLLM config change, not a Hermes profile rebuild
- **Admin API available** — LiteLLM exposes REST endpoints for model management (`GET /models`, `POST /model/new`) that a frontend can call to add/remove/swap model backends at runtime without YAML editing
- **Low resource impact** — LiteLLM uses ~200-500MB RAM and near-zero CPU; it is a proxy, not an inference engine

### Current status

LiteLLM is not yet installed on the U55 but is planned. The U55 has adequate resources (5.7GB free RAM, 67GB free disk) to run it alongside the existing Ollama and Pantheon gateway. When deployed, `pantheon:4000` becomes the single model endpoint for all gods.

## 3. Core runtime pieces

### A. Hermes gateways / API servers

Live on this machine now:
- Hermes root gateway: `hermes-gateway.service`
- Hephaestus gateway: `hermes-gateway-hephaestus.service`

Observed listening ports:
- `127.0.0.1:8642` = root Hermes API server
- `127.0.0.1:8643` = Hephaestus profile API server

These are the primary chat/session/runtime endpoints a Workspace-style frontend should talk to.

### B. Pantheon MCP server

Live on this machine now:
- `pantheon-mcp.service`

Observed listening port:
- `127.0.0.1:8010`

This exposes Pantheon systems as MCP tools, especially:
- Athenaeum semantic search / read / write / walk
- god roster access
- inter-god messaging
- Hades reports
- skills hub access

### C. Shared filesystem

Pantheon relies heavily on a shared local filesystem. Important roots:
- `~/pantheon/` = Pantheon code, harnesses, god registry, packages, planning docs
- `~/athenaeum/` = canonical markdown knowledge base
- `~/.hermes/` = Hermes runtime state, config, profiles, sessions, auth, logs

A frontend that wants to understand Pantheon should model these as first-class sources of truth, not just “assets.”

## 3. Data ownership: what lives where

### Hermes-owned data (`~/.hermes/`)

Important subtrees:
- `~/.hermes/config.yaml` = root Hermes config
- `~/.hermes/.env` = root secrets/env
- `~/.hermes/profiles/<name>/` = one isolated Hermes profile per god/runtime
- `~/.hermes/sessions/` = session transcripts for root profile
- `~/.hermes/profiles/<name>/sessions/` = per-profile sessions
- `~/.hermes/logs/` and per-profile logs
- `~/.hermes/auth.json` and per-profile auth
- `~/.hermes/pantheon/chroma/` = Mnemosyne vector store / ChromaDB

Hermes is the runtime truth for:
- sessions
- messages in active agent conversations
- tool invocation state
- gateway/API behavior
- profile-level isolation

### Pantheon-owned data (`~/pantheon/`)

Important paths:
- `~/pantheon/harnesses/` = base/studio harness YAMLs
- `~/pantheon/gods/gods.yaml` = active god roster
- `~/pantheon/pantheon-registry.yaml` = registered gods and studios
- `~/pantheon/god-packages/` = installable god bundles
- `~/pantheon/plugins/pantheon/` = Pantheon plugin code
- `~/pantheon/planning/` = architecture / constitution / system docs
- `~/pantheon/gods/messages/` = fallback inter-god filesystem inboxes
- `~/pantheon/project-ideas.md` = shared project list / housekeeping artifact

Pantheon is the truth for:
- god definitions
- routing/harness concepts
- installable god packages
- shared multi-agent conventions
- fallback messaging structure

### Athenaeum-owned data (`~/athenaeum/`)

This is the canonical knowledge base.

Examples of codices seen on this machine include:
- `Codex-Pantheon`
- `Codex-Forge`
- `Codex-Infrastructure`
- `Codex-SKC`
- others

The Athenaeum is the source of truth for human-readable knowledge.
Mnemosyne/Chroma is derived from it, not vice versa.

## 4. The god model

Pantheon uses a three-layer agent model:
- God = identity/domain/personality
- Studio = specialization mode for that god
- Harness = the actual executable definition/guardrails/routing structure

### God roster (active machine-level roster)
Current `~/pantheon/gods/gods.yaml` shows:
- Hermes = messenger/interface
- Hephaestus = engineering/builder
- Apollo = creative/songcraft

### Global registry
`~/pantheon/pantheon-registry.yaml` includes broader architectural gods such as:
- Zeus
- Hecate
- Apollo
- Hephaestus
- Athena
- Hermes
- Hestia
- Demeter
- Kronos

That means there are two useful views:
1. active roster = what is instantiated/active for this deployment
2. registry = what the architecture knows how to support

A frontend should not assume every registered god is currently live.

## 5. Harnesses: what they mean

Harness files live in `~/pantheon/harnesses/`.
Examples:
- `hermes-base.yaml`
- `hephaestus-base.yaml`
- `apollo-base.yaml`
- studio variants like `hephaestus-program-design.yaml`

Harnesses define:
- name
- type
- driver (`llm`, `script`, `service`, `hybrid`)
- model (if applicable)
- identity prompt
- routing rules
- guardrails
- failure behavior

This matters for frontend work because a Workspace should be able to display a god as more than “just a chat profile.” A god has:
- a role
- a domain
- a harness
- optional studios
- optional scoped knowledge partitions

## 6. Inter-god communication

There are two layers:

### Primary: MCP-based communication
Preferred path in current architecture.
Pantheon MCP exposes tools for messaging and roster access.

### Fallback: filesystem inboxes
Path:
- `~/pantheon/gods/messages/<god>/msg_*.json`

This is a compatibility/fallback transport, not the long-term primary UI contract.

Implication for frontend design:
- If the frontend needs “god messaging” or “god roster” views, prefer MCP-backed operations.
- Only surface raw filesystem inboxes as a debugging/ops layer, not as the main UX abstraction.

## 7. Knowledge architecture

Pantheon’s knowledge layer has four conceptual layers:

1. Athenaeum
   - markdown files
   - canonical source of truth
   - organized into codices

2. Mnemosyne
   - ChromaDB vector index derived from Athenaeum
   - local path: `~/.hermes/pantheon/chroma/`

3. Distilled layer
   - curated/summarized knowledge written back into Athenaeum under `distilled/`

4. Codex partitions
   - logical scoped views into the vector store
   - not separate databases

Frontend implication:
- browsing files and semantic search are different operations
- “read a note” should target Athenaeum files
- “find relevant knowledge” should target MCP semantic search / Mnemosyne-backed tools
- do not present vector search as if it were a filesystem listing

## 8. Current live integration contract for a frontend

If you are wiring a Hermes Workspace fork today, the cleanest mental model is:

### Primary runtime APIs
- Hermes root API: `http://127.0.0.1:8642`
- Hephaestus API: `http://127.0.0.1:8643`

Use these for:
- sessions
- chat
- profile/runtime state
- agent operations already exposed by Hermes

### Pantheon knowledge/agent-system access
- Pantheon MCP server: `http://127.0.0.1:8010`

Use this for:
- Athenaeum browsing/search/write
- god roster and messaging abstractions
- Pantheon-specific system knowledge

### Frontend service file currently present
`/home/konan/.config/systemd/user/pantheon-workspace.service`
contains:
- `HERMES_API_URL=http://127.0.0.1:8642`
- `CLAUDE_DASHBOARD_URL=http://127.0.0.1:8020`
- `HERMES_DASHBOARD_URL=http://127.0.0.1:8020`

Observed reality during inspection:
- 8642 is live
- 8643 is live
- 8010 is live
- nothing was listening on 8020 at inspection time
- the old Pantheon MCP bridge service references `mcp_bridge.py`, but that file is currently missing from `~/pantheon/pantheon-core/`

So if Codex is wiring a new frontend, it should treat 8642 and 8010 as the reliable current integration points, and treat 8020/old bridge assumptions as stale until intentionally rebuilt.

## 9. Important conceptual split for UI design

A good Pantheon frontend needs to keep these concepts separate:

### A. Hermes runtime view
Questions like:
- what profiles exist?
- what sessions exist?
- what messages are in this session?
- what jobs/tool runs exist?

This comes from Hermes.

### B. Pantheon architecture view
Questions like:
- what gods exist conceptually?
- what harness defines this god?
- what studios can it enter?
- how is work routed?

This comes from Pantheon repo files and MCP metadata.

### C. Knowledge view
Questions like:
- what codices exist?
- what note/file should I open?
- what semantic results are relevant?

This comes from Athenaeum + Mnemosyne via MCP.

Do not collapse all three into a single “chat app” abstraction or the wiring will get muddy fast.

## 10. Recommended frontend architecture for the fork

For the Workspace fork, model Pantheon as three backends:

1. Hermes backend
   - source: Hermes API server(s)
   - concern: chat, sessions, profile runtime

2. Pantheon system backend
   - source: Pantheon MCP server
   - concern: gods, messaging, Athenaeum tools, reports

3. Local static/project metadata
   - source: `~/pantheon/` repo files
   - concern: harness files, registry, planning docs, deployment-specific layout

If you need one combined UX, unify them in the frontend state layer, not by pretending they are one server.

## 11. Practical path for Codex wiring

If Codex is implementing the fork, it should:

1. Read Hermes profile/session data from the Hermes API endpoint.
2. Read Pantheon knowledge and god-system data through MCP-backed endpoints/tools.
3. Treat harness YAMLs and registry YAMLs as inspectable configuration artifacts.
4. Support multiple Hermes profiles as separate runtimes, not just labels.
5. Assume Pantheon-specific concepts may exist even when a given god is not currently active.
6. Avoid depending on old retired frontend services (Pantheon UI, AionUI, Kitchen).

## 12. Short version for prompt injection

Pantheon is a multi-agent architecture built on top of Hermes Agent. Hermes provides the live runtime (profiles, sessions, API servers, tools, gateway). Pantheon adds god definitions, harness YAMLs, inter-god routing/messaging, and a shared knowledge system. The canonical knowledge store is `~/athenaeum/`; semantic search is derived via ChromaDB in `~/.hermes/pantheon/chroma/`. The Pantheon repo at `~/pantheon/` contains harnesses, registries, god packages, and planning docs. Current live integration points are Hermes API on `127.0.0.1:8642` (root) and `127.0.0.1:8643` (Hephaestus), plus Pantheon MCP on `127.0.0.1:8010`. A frontend should treat Hermes runtime, Pantheon system metadata, and Athenaeum knowledge as three related but distinct layers.
