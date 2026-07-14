"""Hermes Dojo scripts (Phase 6 of ichor-v2).

Two scripts + two cron jobs:

  - skill_crystallization.py — extracts execution patterns from recent complex
    tasks (insight events with importance > 0.3 in last 24h) and offers them as
    skill candidates.

  - failed_trajectory_mining.py — finds the most common failure modes each
    week (blocker/correction events with low trust) and surfaces top patterns.

Both scripts read from ~/.hermes/ichor.db (the canonical event log), not from
state.db. They complement the Phronesis skill at ~/.hermes/skills/hermes-dojo/,
which reads session transcripts.

Spec: ~/athenaeum/Codex-Pantheon/plans/ichor-v2-build-blueprint.md §8.
"""
