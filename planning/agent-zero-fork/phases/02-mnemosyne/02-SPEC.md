# Phase 2: Mnemosyne — Specification

**Created:** 2026-04-24
**Ambiguity score:** 0.16
**Requirements:** 4 locked

## Goal

Replace agent-zero's vector store with Mnemosyne — a local-embedding semantic search layer that indexes Athenaeum content by Codex partition and exposes the same `search_similarity_threshold()` interface the rest of agent-zero expects.

## Background

After Phase 1, the Athenaeum contains markdown files but `memory_load.py` returns empty results. agent-zero's `knowledge_tool.py` calls `Memory.get(agent)` and then `db.search_similarity_threshold(query, limit, threshold, filter)`. This phase wires Mnemosyne into that call path: a local embedding model (running on local Ollama) embeds Athenaeum content into a vector store partitioned by Codex metadata. Search queries route to the correct Codex partition and return semantically relevant documents.

## Requirements

1. **Local embedding**: Athenaeum files are embedded using a local Ollama embedding model, never a cloud provider.
   - Current: `_memory` uses whatever embedding model is configured globally — potentially cloud
   - Target: `_athenaeum/default_config.yaml` has a separate `embedding` key pointing to `localhost:11434` with a configurable model name (default: `nomic-embed-text`); this key is independent of the LLM config; embedding calls never use Ollama Cloud or any remote endpoint
   - Acceptance: With Ollama Cloud configured as the LLM provider, embedding calls still go to `localhost:11434`; changing the LLM provider does not affect the embedding endpoint

2. **Codex partition routing**: Vector search queries are scoped to the relevant Codex partition via metadata filtering.
   - Current: `_memory` uses a flat `area` metadata field with no partition concept
   - Target: Each embedded document carries `codex`, `subfolder`, `source_file`, and `timestamp` metadata; `MnemosyneSearch.query(question, codex=None)` filters by `codex` metadata when specified; `codex=None` searches all partitions
   - Acceptance: A document in `Codex-SKC` is not returned when querying with `codex="Infrastructure"`; a query with `codex=None` can return documents from any Codex

3. **Interface compatibility**: `_athenaeum` exposes the same `Memory`-compatible interface that `knowledge_tool.py` and other callers use.
   - Current: `Memory.get(agent)` returns an object with `search_similarity_threshold(query, limit, threshold, filter)` method
   - Target: `AthenaeumMemory.get(agent)` returns an `MnemosyneAdapter` object that implements the same method signature; existing callers require no modification
   - Acceptance: `knowledge_tool.py` runs without modification after this phase; `mem_search_enhanced()` calls succeed and return structured results

4. **Re-embedding on write**: When `AthenaeumMemory.save()` writes a new file, that file is embedded into Mnemosyne immediately (synchronous in Phase 2; async via Demeter in Phase 4).
   - Current: Phase 1 writes files but Mnemosyne has no content
   - Target: After `save()` completes, the new file is embedded and searchable via `search_similarity_threshold()` in the same process
   - Acceptance: Save a file, then immediately search for its content — the file appears in results above threshold

## Boundaries

**In scope:**
- `helpers/mnemosyne.py` — embedding client (local Ollama), vector store management, Codex partition metadata
- `tools/memory_load.py` — full implementation replacing Phase 1 stub; calls `MnemosyneAdapter`
- `MnemosyneAdapter` class implementing `search_similarity_threshold()` interface
- `default_config.yaml` — `embedding.base_url`, `embedding.model`, `embedding.threshold` keys
- Initial bulk embedding of existing Athenaeum content on plugin startup (via `execute.py`)
- Enabling `tools/knowledge_tool.py` as the active knowledge query tool

**Out of scope:**
- Staging inbox files — never embedded by design
- Distilled layer embedding — Phase 3 (Hades writes distilled content; Mnemosyne embeds it then)
- Async re-embedding triggered by file watcher — Phase 4 (Demeter)
- Ollama Cloud model config — Phase 5

## Constraints

- Vector store backend must be ChromaDB (matching agent-zero's existing dependency) — do not introduce a new vector store library
- Embedding model must be configurable but default to `nomic-embed-text` — available via `ollama pull nomic-embed-text`
- `search_similarity_threshold()` method signature must be identical to the `_memory` version: `(query, limit, threshold, filter=None)` — no new required parameters
- Mnemosyne never reads from or embeds Staging content — not a constraint to be relaxed

## Acceptance Criteria

- [ ] `default_config.yaml` has `embedding.base_url: http://localhost:11434` and `embedding.model: nomic-embed-text`
- [ ] Changing LLM provider to Ollama Cloud does not change the embedding endpoint
- [ ] `AthenaeumMemory.get(agent)` returns an object with `search_similarity_threshold()` method
- [ ] `knowledge_tool.py` runs `mem_search_enhanced()` without import errors or crashes
- [ ] A file saved to `Codex-General` is returned by a search with `codex="General"` when threshold is met
- [ ] A file saved to `Codex-SKC` is NOT returned by a search with `codex="Infrastructure"`
- [ ] `execute.py` bulk-embeds existing Athenaeum files on first run
- [ ] Staging files are never present in search results regardless of query

## Ambiguity Report

| Dimension           | Score | Min  | Status | Notes |
|---------------------|-------|------|--------|-------|
| Goal Clarity        | 0.88  | 0.75 | ✓      | |
| Boundary Clarity    | 0.90  | 0.70 | ✓      | Staging exclusion and async deferral explicit |
| Constraint Clarity  | 0.85  | 0.65 | ✓      | ChromaDB pinned, interface signature locked |
| Acceptance Criteria | 0.82  | 0.70 | ✓      | 8 pass/fail criteria |
| **Ambiguity**       | 0.16  | ≤0.20| ✓      | |

## Interview Log

| Round | Perspective      | Question summary                        | Decision locked |
|-------|------------------|-----------------------------------------|----------------|
| 1     | Researcher       | What vector store does `_memory` use?   | ChromaDB — keep it, don't add new dependency |
| 2     | Simplifier       | Minimum viable Mnemosyne?               | Embed + search with Codex filter — no async yet |
| 3     | Boundary Keeper  | Does Staging get embedded?              | Never — hard rule from Pantheon design |
| 4     | Failure Analyst  | What if embedding model not pulled?     | `execute.py` checks and prints clear error with `ollama pull` instruction |

---

*Phase: 02-mnemosyne*
*Spec created: 2026-04-24*
*Next step: /gsd:discuss-phase 2 — implementation decisions (ChromaDB collection naming, embedding batch size, threshold defaults)*
