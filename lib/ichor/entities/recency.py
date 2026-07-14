"""
Recency Reranker — query-time confidence adjustment based on last_accessed.

Simon Scrapes' "perfect memory" system uses a reranker pass at query time
that factors in recency. This module provides the same capability:

  recency_weight(last_accessed, updated_at, half_life_days=7)
    → float in (0, 1] — multiplicative boost/penalty factor

  rerank_results(results, get_la_fn, half_life_days=7)
    → results list with adjusted scores

Usage:
    from lib.ichor.entities.recency import recency_weight, rerank_results

    # Score a single entity
    w = recency_weight(entity["last_accessed"], entity["updated_at"])

    # Rerank a list of search results
    results = rerank_results(raw_results, lambda r: r["last_accessed"])
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_HALF_LIFE_DAYS = 7  # matches dream.py


def _parse_dt(iso_str: str | None) -> datetime | None:
    """Parse an ISO datetime string, with lenient handling."""
    if not iso_str or not isinstance(iso_str, str):
        return None
    s = iso_str.strip()
    if s.endswith(" UTC"):
        s = s[:-4]
    # Drop subseconds if present
    if len(s) > 19 and s[19] in (".", ","):
        s = s[:19]
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def recency_weight(
    last_accessed: str | None,
    updated_at: str | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    min_weight: float = 0.1,
) -> float:
    """Calculate the recency boost factor for an entity or relationship.

    Args:
        last_accessed: ISO datetime of last access (preferred).
        updated_at: ISO datetime of last update (fallback if no last_accessed).
        half_life_days: days after which weight drops to 50%.
        min_weight: minimum return value (prevents complete exclusion).

    Returns:
        float in [min_weight, 1.0]. 1.0 = accessed just now.
        0.5 = accessed half_life_days ago.
        Approaches min_weight asymptotically for very old data.

    Formula:
        weight = 2^(-Δt / half_life_days)
        which is equivalent to: weight = exp(-Δt * ln(2) / half_life_days)

    This is the SAME exponential decay formula as the background dream cycle,
    but applied AT QUERY TIME rather than as a background maintenance job.
    The dream cycle eventually archives entities that fall below threshold;
    this function lets you adjust result ranking before that happens.
    """
    effective_la = last_accessed or updated_at
    if not effective_la:
        return 1.0  # no timestamp = assume fresh

    dt = _parse_dt(effective_la)
    if dt is None:
        return 1.0  # unparseable = assume fresh

    now = datetime.now(timezone.utc)
    delta_days = (now - dt).total_seconds() / 86400.0

    if delta_days <= 0:
        return 1.0

    k = math.log(2) / half_life_days
    weight = math.exp(-k * delta_days)
    return max(weight, min_weight)


def rerank_results(
    results: list[dict[str, Any]],
    get_recency_field: Callable[[dict[str, Any]], tuple[str | None, str | None]],
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    score_field: str = "confidence",
    output_field: str = "recency_adjusted_score",
) -> list[dict[str, Any]]:
    """Apply recency weighting to a list of search/traversal results.

    Each result's original score (confidence) is multiplied by the
    recency_weight for its entity. Results are re-sorted by the
    combined score.

    Args:
        results: list of result dicts (from traversal, search, etc.)
        get_recency_field: function that extracts (last_accessed, updated_at)
            from a result dict.
        half_life_days: decay half-life in days.
        score_field: the field in each result dict to use as the base score.
            Default: "confidence".
        output_field: the field name for the adjusted score.
            Default: "recency_adjusted_score".

    Returns:
        New list of results, each with `output_field` added, sorted
        descending by `output_field`.
    """
    if not results:
        return []

    for r in results:
        la, ua = get_recency_field(r)
        rw = recency_weight(la, ua, half_life_days=half_life_days)
        base = r.get(score_field, 1.0) if isinstance(r.get(score_field), (int, float)) else 1.0
        r[output_field] = round(base * rw, 4)

    # Sort by adjusted score descending
    return sorted(results, key=lambda r: r[output_field], reverse=True)
