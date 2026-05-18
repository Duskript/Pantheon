# Mem0-Inspired Memory Scoring — Implementation Plan

Goal: turn the project-ideas entry "Memory Importance Scoring & Conflict Detection" into a small, testable Pantheon memory improvement.

## Scope

- Add deterministic importance scoring to Mnemosyne embeddings via ChromaDB metadata (`priority_score`).
- Add graph-level fact conflict detection helpers using the existing `contradicts` edge type.
- Keep this local, dependency-free, and backward compatible.
- Do not commit Hermes plan files.

## Tasks

1. Scout current memory/vector/graph code.
2. Add `score_memory_importance()` in `mnemosyne/client.py` and store `priority_score` during `embed_file()`.
3. Return `priority_score` from `query()` when present.
4. Add `register_fact()` and `find_conflicts_for_fact()` helpers to `gods/graph_client.py`.
5. Add tests for Mnemosyne priority metadata and graph conflict detection.
6. Run targeted tests and compile checks.
7. Update `project-ideas.md` status/notes.
