"""Ichor optional reranker lane — DISABLED BY DEFAULT.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 10).

Feature flags (environment variables, no restart needed):

    ICHOR_RERANK_ENABLED=false          # master switch (default: disabled)
    ICHOR_RERANK_MODE=none              # none | heuristic | local_cross_encoder
    ICHOR_RERANK_TIMEOUT_SECONDS=10
    ICHOR_RERANK_MAX_CANDIDATES=100

Only the model-free ``heuristic`` mode is implemented. ``local_cross_encoder``
is intentionally NOT implemented (no model download in the default path).
Any disabled/unavailable/failed rerank degrades to passthrough: the original
order is preserved and ``rerank_status`` explains why.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

_ENABLED_KEY = "ICHOR_RERANK_ENABLED"
_MODE_KEY = "ICHOR_RERANK_MODE"
_TIMEOUT_KEY = "ICHOR_RERANK_TIMEOUT_SECONDS"
_MAX_CANDIDATES_KEY = "ICHOR_RERANK_MAX_CANDIDATES"

# Heuristic rerank formula weights (spec §Phase 10).
W_LEXICAL = 0.50
W_CONFIDENCE = 0.20
W_PROOF = 0.15
W_TEMPORAL = 0.10
W_SCOPE = 0.05

_VALID_MODES = frozenset({"none", "heuristic", "local_cross_encoder"})


def rerank_enabled() -> bool:
    return os.environ.get(_ENABLED_KEY, "false").strip().lower() == "true"


def rerank_mode() -> str:
    mode = os.environ.get(_MODE_KEY, "none").strip().lower()
    return mode if mode in _VALID_MODES else "none"


def rerank_max_candidates() -> int:
    try:
        return max(1, int(os.environ.get(_MAX_CANDIDATES_KEY, "100")))
    except (TypeError, ValueError):
        return 100


def rerank_timeout_seconds() -> float:
    try:
        return max(0.0, float(os.environ.get(_TIMEOUT_KEY, "10")))
    except (TypeError, ValueError):
        return 10.0


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _proof_norm(result: Dict[str, Any]) -> float:
    proof = result.get("proof_count")
    if isinstance(proof, (int, float)):
        return _clamp(float(proof) / 10.0)
    return 0.0


def _temporal_score(result: Dict[str, Any]) -> float:
    score = result.get("score")
    reasons = result.get("rank_reasons") or []
    if "temporal_close" in reasons:
        return 1.0
    if "temporal_far" in reasons:
        return 0.0
    return 0.5


def _scope_score(result: Dict[str, Any]) -> float:
    scope = result.get("scope_status")
    if scope == "strict_scope_match":
        return 1.0
    if scope == "untagged_backend":
        return 0.0
    return 0.5


def heuristic_rerank(
    results: List[Dict[str, Any]],
    query: str = "",
) -> List[Dict[str, Any]]:
    """Model-free rerank per the spec formula.

    ``final_score = 0.50*lexical + 0.20*confidence + 0.15*proof_norm
                     + 0.10*temporal + 0.05*scope``

    Mutates each result's ``score``/``fused_score`` and appends rank reasons.
    Returns the re-sorted list. Deterministic (stable sort by final_score).
    """
    if not results:
        return results
    for r in results:
        lexical = _clamp(float(r.get("score") or r.get("fused_score") or 0.0))
        confidence = _clamp(float(r.get("confidence") or 0.0))
        final = (
            W_LEXICAL * lexical
            + W_CONFIDENCE * confidence
            + W_PROOF * _proof_norm(r)
            + W_TEMPORAL * _temporal_score(r)
            + W_SCOPE * _scope_score(r)
        )
        r["final_score"] = round(final, 4)
        r["score"] = round(final, 4)
        if "fused_score" in r:
            r["fused_score"] = round(final, 4)
        reasons: List[str] = r.setdefault("rank_reasons", [])
        if "heuristic_rerank" not in reasons:
            reasons.append("heuristic_rerank")
    return sorted(results, key=lambda r: float(r.get("final_score") or 0.0), reverse=True)


def rerank_results(
    results: List[Dict[str, Any]],
    query: str = "",
    *,
    requested_mode: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], str]:
    """Apply the reranker lane or pass through.

    Returns ``(results, rerank_status)`` where status is one of:
    ``disabled``, ``passthrough``, or ``heuristic``. Never raises — any
    failure degrades to passthrough so retrieval always returns results.
    """
    try:
        mode = requested_mode or rerank_mode()
        if not rerank_enabled() and requested_mode is None:
            return results, "disabled"
        if mode == "none":
            return results, "disabled"
        if mode != "heuristic":
            # local_cross_encoder is intentionally not implemented; a caller
            # explicitly requesting it gets a safe passthrough.
            return results, "passthrough"
        if not results:
            return results, "heuristic"
        capped = results[: rerank_max_candidates()]
        out = heuristic_rerank(capped, query)
        # Preserve results beyond the candidate cap untouched, in place.
        if len(results) > len(capped):
            out = out + list(results[len(capped):])
        return out, "heuristic"
    except Exception:
        return results, "passthrough"
