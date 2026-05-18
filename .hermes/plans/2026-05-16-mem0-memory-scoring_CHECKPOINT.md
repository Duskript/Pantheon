# Checkpoint: Mem0-Inspired Memory Scoring

Last updated: 2026-05-16

## Status
- Scout: complete
- Design: complete
- Plan: complete
- Build: complete
- Close: in progress

## File State
- `pantheon-core/mnemosyne/client.py` — added `score_memory_importance()`, ChromaDB `priority_score` metadata on embed, query return passthrough.
- `pantheon-core/gods/graph_client.py` — added deterministic fact registration and conflict detection with `contradicts` edges.
- `pantheon-core/tests/test_mnemosyne.py` — added priority-score tests and fixed httpx-free test stub.
- `pantheon-core/tests/test_graph_client.py` — added fact conflict tests.
- `project-ideas.md` — marked Mem0 idea done with notes.

## Verification
- `uvx pytest tests/test_mnemosyne.py tests/test_graph_client.py -q` → 20 passed
- `python3 -m py_compile mnemosyne/client.py gods/graph_client.py` → passed

## Next Action
Commit/push code changes, then brief Konan.
