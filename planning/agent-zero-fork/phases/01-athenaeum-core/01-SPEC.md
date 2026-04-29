# Phase 1: Athenaeum Core — Specification

**Created:** 2026-04-24
**Ambiguity score:** 0.14
**Requirements:** 5 locked

## Goal

Replace agent-zero's `_memory` plugin with `_athenaeum` — a plugin that writes knowledge to Codex markdown files, maintains an INDEX.md hierarchy at every folder level, and provides a Staging inbox for unclassified content.

## Background

agent-zero's `plugins/_memory/` stores all memory directly to a vector store with flat metadata (`area`, `knowledge_source`, `timestamp`). There is no markdown persistence, no human-readable knowledge structure, and no index system. The `knowledge_tool._py` is disabled by default (`._py` extension). The Pantheon Athenaeum design requires the opposite: markdown files are the source of truth; the vector store is always derived. This phase builds the file system layer — the foundation every subsequent phase depends on.

## Requirements

1. **Plugin manifest**: `_athenaeum` has a valid `plugin.yaml` that disables `_memory` and registers `_athenaeum` in its place.
   - Current: `plugins/_memory/plugin.yaml` exists and is active; no `_athenaeum` plugin exists
   - Target: `plugins/_athenaeum/plugin.yaml` exists; `_memory` is toggled off via `.toggle-0`; agent-zero loads `_athenaeum` on startup
   - Acceptance: Agent-zero starts without errors; `_memory` tools do not load; `_athenaeum` tools load successfully

2. **Codex file structure**: Plugin initializes the Athenaeum directory layout on first run if it does not exist.
   - Current: No Athenaeum directory exists; agent-zero uses `knowledge/` folder with flat files
   - Target: `Athenaeum/` created at configured root with subdirectories for all 7 Codices (SKC, Infrastructure, Pantheon, Forge, Fiction, Asclepius, General), each containing domain subfolders, `distilled/`, `archive/`, and an `INDEX.md`
   - Acceptance: Running `execute.py` on a clean system creates the full Athenaeum tree; each Codex folder contains an `INDEX.md`; no errors thrown if tree already exists

3. **Append-only Codex writes**: When agent-zero saves a memory, it is written as a markdown file to the appropriate Codex subfolder, never overwriting existing files.
   - Current: `_memory` calls `Memory.save()` which upserts a vector record; no markdown file is written
   - Target: `AthenaeumMemory.save(content, codex, subfolder, metadata)` writes a new `.md` file named `{ISO8601-timestamp}-{slug}.md`; existing files are never modified
   - Acceptance: Calling `save()` twice with the same content produces two separate timestamped files; no file is overwritten; file content matches input

4. **INDEX.md auto-generation**: After any write, the affected folder's INDEX.md and all parent INDEX.md files up to the Athenaeum root are regenerated.
   - Current: No INDEX.md system exists
   - Target: Every folder in the Athenaeum contains an INDEX.md listing its contents with one-line summaries; root `Athenaeum/INDEX.md` lists all Codices; regeneration happens synchronously after each write in this phase (async via Demeter in Phase 4)
   - Acceptance: After saving a new file to `Codex-General/notes/`, the `notes/INDEX.md`, `Codex-General/INDEX.md`, and `Athenaeum/INDEX.md` all reflect the new file within the same call

5. **Staging inbox**: Unclassified content drops to `Staging/inbox/` rather than being rejected.
   - Current: No Staging area exists; all content routes directly to the vector store
   - Target: `AthenaeumMemory.save()` accepts `codex=None`; content with no Codex destination is written to `Staging/inbox/{timestamp}-{slug}.md`; Staging is never embedded or indexed
   - Acceptance: Calling `save()` with `codex=None` creates a file in `Staging/inbox/`; no INDEX.md is created for Staging; Staging files are not accessible via search

## Boundaries

**In scope:**
- `plugins/_athenaeum/` directory with `plugin.yaml`, `execute.py`, `hooks.py`
- `helpers/athenaeum.py` — Codex file manager (create structure, write files, regenerate indexes)
- `tools/memory_save.py` — replaces `_memory/tools/memory_save.py` with Athenaeum write
- `tools/memory_load.py` — stub for Phase 2 (returns empty; Mnemosyne not yet wired)
- `default_config.yaml` — Athenaeum root path, Codex definitions
- Disabling `_memory` plugin via `.toggle-0`
- Renaming `tools/knowledge_tool._py` → `tools/knowledge_tool.py` (activation only; full rewire in Phase 2)

**Out of scope:**
- Vector search — Phase 2 (Mnemosyne)
- Distillation, archiving, TTL — Phase 3 (Underworld)
- File watching, async index regeneration — Phase 4 (Demeter)
- Ollama Cloud or embedding config — Phase 5

## Constraints

- Athenaeum root path must be configurable via `default_config.yaml` (default: `~/Pantheon/Athenaeum/`)
- INDEX.md format must follow Pantheon KNOWLEDGE.md spec exactly — table with File/Summary columns, Parent link, Last updated timestamp
- Plugin must not import from `plugins._memory` — clean break, no shared code
- `memory_load.py` must return a valid empty result (not an error) so agent-zero does not crash before Phase 2

## Acceptance Criteria

- [ ] Agent-zero starts with `_athenaeum` loaded and `_memory` absent from loaded plugins
- [ ] `execute.py` creates full Athenaeum + Staging directory tree on a clean system
- [ ] `AthenaeumMemory.save(content, codex="General", subfolder="notes")` creates a timestamped `.md` file in `Athenaeum/Codex-General/notes/`
- [ ] Calling `save()` twice creates two files, not one overwritten file
- [ ] `Athenaeum/INDEX.md`, `Codex-General/INDEX.md`, and `notes/INDEX.md` all updated after `save()`
- [ ] `AthenaeumMemory.save(content, codex=None)` creates a file in `Staging/inbox/` with no INDEX.md update
- [ ] `memory_load.py` returns empty result without error
- [ ] `tools/knowledge_tool.py` exists (renamed from `._py`) and loads without import errors

## Ambiguity Report

| Dimension           | Score | Min  | Status | Notes |
|---------------------|-------|------|--------|-------|
| Goal Clarity        | 0.90  | 0.75 | ✓      | |
| Boundary Clarity    | 0.92  | 0.70 | ✓      | Phases 2-5 explicitly out of scope |
| Constraint Clarity  | 0.85  | 0.65 | ✓      | Config path and INDEX format specified |
| Acceptance Criteria | 0.88  | 0.70 | ✓      | 8 pass/fail checkboxes |
| **Ambiguity**       | 0.14  | ≤0.20| ✓      | |

## Interview Log

| Round | Perspective      | Question summary                     | Decision locked |
|-------|------------------|--------------------------------------|----------------|
| 1     | Researcher       | What does `_memory` actually write?  | Vector records only — no markdown at all |
| 2     | Simplifier       | Minimum viable Athenaeum for Phase 1? | File writes + INDEX — no search yet |
| 3     | Boundary Keeper  | What is NOT this phase?              | Vector search, distillation, file watching all deferred |
| 4     | Failure Analyst  | What if Codex is unknown?            | Routes to Staging/inbox — never rejected |

---

*Phase: 01-athenaeum-core*
*Spec created: 2026-04-24*
*Next step: /gsd:discuss-phase 1 — implementation decisions (file naming, INDEX format, config schema)*
