"""Gods module for Pantheon-core — provides analysis and reporting modules.

This module was restored after the pantheon-core pruning (commit bce14cb)
which removed the entire gods/ directory. The athenaeum_triage module is
consumed by athenaeum/scripts/athenaeum-triage.py as part of the morning
briefing pipeline.

Subpackages
-----------
- ``gods.hades``  — nightly consolidation, distillation, archiving.
- ``gods.ichor``  — Phase 5 state-ledger rendering for system-prompt injection.

Public API
----------
- :func:`build_system_prompt` — prepends the state ledger for a god to a base
  system prompt. Implemented per ``ichor-v2-build-blueprint.md`` §7
  (Phase 5 — State Ledger Rendering).
"""

from __future__ import annotations

from typing import Optional


def build_system_prompt(
    god_name: str,
    base_prompt: str = "",
    db_path: Optional[str] = None,
) -> str:
    """Build a god's system prompt with the state ledger prepended.

    The state ledger gives every agent a query-less "what should I know
    right now?" preamble — active blockers, recent decisions, open
    commitments, and key entity relationships. This is the LedgerAgent
    pattern from ``ichor-v2-build-blueprint.md`` §7.

    Behavior:
      - Empty ``god_name`` → returns ``base_prompt`` unchanged.
      - DB missing / unreadable → returns ``base_prompt`` unchanged.
      - DB present but god has nothing → returns ``base_prompt`` unchanged.
      - DB present and god has ledger → prepends

        ``## Current State Ledger\\n\\n{ledger}``

        to ``base_prompt``, separated by a blank line.

    Args:
        god_name: God identifier (e.g. 'hermes', 'hephaestus').
        base_prompt: The existing system prompt to augment. Empty string
            is allowed (returns just the ledger section, with header).
        db_path: Optional explicit path to ichor.db. Defaults to
            ``~/.hermes/ichor.db`` (the value used by the live ledger).

    Returns:
        The combined system prompt string. Always includes the ledger
        section header when any ledger content was prepended, so the
        downstream prompt stays structured even if the ledger is empty
        after the ``build_system_prompt`` decides not to prepend.
    """
    if not god_name:
        return base_prompt

    # Lazy import — keep top-level imports light so this module imports
    # cleanly even if the ichor package path is missing (e.g. during
    # migrations or in tests that don't touch the ledger).
    try:
        from gods.ichor.state_ledger import render_god_ledger
    except ImportError:
        # Degrade silently — the ledger is an enhancement, not a hard
        # dependency of the system prompt builder.
        return base_prompt

    ledger = render_god_ledger(god_name, db_path=db_path)
    if not ledger:
        return base_prompt

    if base_prompt:
        return f"{base_prompt}\n\n## Current State Ledger\n\n{ledger}"
    return f"## Current State Ledger\n\n{ledger}"


__all__ = ["build_system_prompt"]