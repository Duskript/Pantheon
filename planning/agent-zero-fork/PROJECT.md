# Agent-Zero / Pantheon Fork

## What This Is

A fork of [agent0ai/agent-zero](https://github.com/agent0ai/agent-zero) that replaces its built-in `_memory` plugin with the full Pantheon Athenaeum knowledge stack — a structured, multi-codex, markdown-first knowledge system backed by local-embedding vector search. The fork also adds first-class Ollama Cloud support and separates embedding from LLM routing so embeddings always run locally.

## Core Value

Agent-zero gains persistent, structured knowledge that organizes itself across sessions — not a flat vector store but a navigable Codex hierarchy that any god in the Pantheon system can read, write, and query.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] `_athenaeum` plugin replaces `_memory` — writes to Codex markdown files, maintains INDEX.md hierarchy, manages Staging inbox
- [ ] Mnemosyne vector layer replaces `_memory`'s vector store — local embeddings, Codex partition routing, same interface agent-zero expects
- [ ] Underworld operations — Hades distillation, Charon archiving, Fates TTL evaluation
- [ ] Demeter automation — file watcher, settle-window index regeneration, nightly scheduler
- [ ] Ollama Cloud support — `OllamaCloud` provider in `models.py`, separated from local embedding config

### Out of Scope

- Modifying agent-zero's core orchestration, tool system, or WebUI — this fork touches only the memory plugin and model config plugin
- Replacing the Staging inbox classifier with a fully automated Mnemosyne classifier — Phase 1 uses manual routing; automation is a future phase
- Multi-user or multi-agent shared Athenaeum — single-user only, matching Pantheon's single-user architecture
- S3 or remote backup of the Athenaeum — local filesystem only

## Context

**agent-zero codebase state (as of fork):**
- `plugins/_memory/` — vector store plugin; `Memory.get(agent)`, `search_similarity_threshold()`, flat metadata: `area`, `knowledge_source`, `timestamp`
- `tools/knowledge_tool._py` — disabled by default (`._py` extension); orchestrates memory search + web search concurrently
- `plugins/_model_config/` — handles model resolution at call time via `@extensible` hooks; presets in `default_presets.yaml`
- `models.py` — provider definitions; `Ollama` currently assumes `localhost:11434`; no Ollama Cloud entry
- `initialize.py` — `@extensible` init chain; plugins hook into named lifecycle points

**Pantheon Athenaeum design (source: `.planning/KNOWLEDGE.md`):**
- 4 layers: Athenaeum (markdown, source of truth) → Mnemosyne (vector index, derived) → Distilled (Hades consolidation) → Codex Partitions (metadata-scoped views)
- Hard rule: never write directly to vector store — always write to Athenaeum; Mnemosyne derives from it
- Gods: Demeter (file watcher + indexer), Mnemosyne (embedding), Hades (distillation), Charon (archive), Fates (TTL)
- Codices: SKC, Infrastructure, Pantheon, Forge, Fiction, Asclepius, General
- Staging area: inbox → classified → routed to Codex or rejected

## Constraints

- **Plugin boundary**: All Athenaeum code lives in `plugins/_athenaeum/`. No changes to `agent.py`, core agent-zero files, or any file outside the plugin and `models.py` / `_model_config`.
- **Local embeddings only**: Embedding model always runs on local Ollama (`localhost:11434`). This config key is separate from the LLM config and cannot be pointed at Ollama Cloud.
- **Interface compatibility**: `_athenaeum` must expose the same `Memory`-compatible interface that `knowledge_tool.py` and `_memory/tools/` use — no changes to callers.
- **Append-and-archive only**: Athenaeum files are never deleted in place. Only Charon moves files; only Fates purges from Tartarus.
- **Python only**: All plugin code is Python. No new languages introduced.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Replace `_memory` entirely rather than extend it | Athenaeum's write-to-markdown-first principle is incompatible with `_memory`'s direct vector write model | — Pending |
| Embedding always local, never cloud | Embedding models are small; cloud routing adds latency, cost, and uptime dependency for a non-LLM task | — Pending |
| Codex-General as default fallback | Matches Pantheon design — ambiguous content routes to General, not rejected | — Pending |
| `knowledge_tool._py` renamed `.py` and rewired | Tool was disabled; enabling it as the Athenaeum query interface is the cleanest activation path | — Pending |

---
*Last updated: 2026-04-24 — initial spec*
