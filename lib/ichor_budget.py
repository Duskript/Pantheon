"""Ichor budgeted / token-bounded recall controls.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 6).

Separates retrieval effort (candidate multiplier) from the final returned
result count (``limit``) and payload size (``max_tokens``). No heavyweight
dependencies: token estimation is a deterministic char/4 heuristic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

Budget = Literal["low", "mid", "high"]


@dataclass(frozen=True)
class RecallBudget:
    """One named recall budget profile."""

    name: str
    candidate_multiplier: int
    graph_depth: int
    hydrate_sources: bool
    default_max_tokens: int


BUDGETS: Dict[str, RecallBudget] = {
    "low": RecallBudget("low", candidate_multiplier=3, graph_depth=0, hydrate_sources=False, default_max_tokens=2048),
    "mid": RecallBudget("mid", candidate_multiplier=8, graph_depth=1, hydrate_sources=False, default_max_tokens=4096),
    "high": RecallBudget("high", candidate_multiplier=20, graph_depth=2, hydrate_sources=True, default_max_tokens=8192),
}

_VALID_BUDGET_NAMES = frozenset(BUDGETS.keys())


def resolve_budget(
    budget: str | None,
    max_tokens: int | None,
) -> RecallBudget:
    """Resolve a named budget + explicit max_tokens into a RecallBudget.

    - ``budget=None`` → ``mid`` (spec default for new callers).
    - Explicit ``max_tokens`` overrides the profile default.
    - Invalid budget name raises ValueError (fail clearly).
    """
    name = budget or "mid"
    if name not in _VALID_BUDGET_NAMES:
        raise ValueError(
            f"invalid budget {budget!r}: expected one of {sorted(_VALID_BUDGET_NAMES)}"
        )
    profile = BUDGETS[name]
    if max_tokens is not None:
        if max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        return RecallBudget(
            name=profile.name,
            candidate_multiplier=profile.candidate_multiplier,
            graph_depth=profile.graph_depth,
            hydrate_sources=profile.hydrate_sources,
            default_max_tokens=int(max_tokens),
        )
    return profile


def estimate_tokens(text: str) -> int:
    """Cheap deterministic token estimate (no tokenizer dependency)."""
    if not text:
        return 0
    return max(1, len(str(text)) // 4)


def _result_tokens(result: Dict[str, Any], include_sources: bool) -> int:
    """Estimate the token cost of one result dict.

    Counts title + snippet (+ type/backend), plus source quotes when
    ``include_sources`` is set.
    """
    parts = [
        result.get("title"),
        result.get("snippet"),
        result.get("type"),
        result.get("backend"),
    ]
    if include_sources:
        sources = result.get("sources") or []
        for src in sources:
            if isinstance(src, dict):
                parts.append(src.get("quote"))
            else:
                parts.append(str(src))
        parts.append(str(result.get("source_ids") or ""))
        parts.append(str(result.get("source") or ""))
    return estimate_tokens(" ".join(str(p) for p in parts if p))


def truncate_for_token_budget(
    results: List[Dict[str, Any]],
    max_tokens: int,
    include_sources: bool = False,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Greedily fit ranked results within a token budget.

    Always keeps the top result when any result exists and ``max_tokens > 0``.
    Returns ``(kept, dropped_count, tokens_used)``. Order is preserved.
    """
    if max_tokens is None or max_tokens <= 0:
        return results, 0, sum(_result_tokens(r, include_sources) for r in results)
    kept: List[Dict[str, Any]] = []
    used = 0
    for idx, r in enumerate(results):
        cost = _result_tokens(r, include_sources)
        if idx == 0 and not kept:
            # Always include the top result.
            kept.append(r)
            used += cost
            continue
        if used + cost > max_tokens:
            break
        kept.append(r)
        used += cost
    dropped = len(results) - len(kept)
    return kept, dropped, used


def candidate_limit(limit: int, budget: RecallBudget) -> int:
    """Candidate fetch limit per backend: max(limit, limit * multiplier)."""
    return max(int(limit), int(limit) * int(budget.candidate_multiplier))
