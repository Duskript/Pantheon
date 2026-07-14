"""Hermes Dojo (Phase 6 of ichor-v2).

Two scripts + two cron jobs that turn Ichor event streams into skill
candidates (skill_crystallization) and failure patterns (failed_trajectory_mining).

NOTE: This package is distinct from the Phronesis skill at
~/.hermes/skills/hermes-dojo/. Phronesis reads from state.db (session transcripts);
these scripts read from ~/.hermes/ichor.db (the canonical event log).
Different signal source, complementary purpose.

See ~/athenaeum/Codex-Pantheon/plans/ichor-v2-build-blueprint.md §8.
"""
__version__ = "1.0.0"
