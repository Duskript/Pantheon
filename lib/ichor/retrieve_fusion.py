"""Ichor V2 retrieval fusion — god-scoped boost + temporal filtering.

Phase 2 (ichor-v2-build-blueprint.md §4) layers god-scoping on top of
the unified retrieval layer. Each result's `fused_score` is multiplied
by a god-scoping factor AFTER backend fusion:

    ┌─────────────────────────────────┬────────────┐
    │ Condition                       │ Factor     │
    ├─────────────────────────────────┼────────────┤
    │ result.god_name == active_god   │ 2.0  same  │
    │ result.god_name != active_god   │ 1.5  cross │
    │ result.god_name is empty/None   │ 1.0  neut. │
    │ result is temporally expired    │ 0.0  expir.│
    └─────────────────────────────────┴────────────┘

`apply_god_boost()` is a pure function so it can be unit-tested in
isolation. The MCP tool surfaces an `active_god` parameter; when
empty, the boost is a no-op (factor=1.0 for everything).

Temporal expiry contract (Phase 0 added the columns):
    - entities.valid_until < now       → expired
    - entities.status != 'active'      → expired (covers 'archived', 'merged')
    - entities.superseded_by IS NOT NULL → expired (lineage replaced)

For non-entity backends (FTS5, vector, events — which have no temporal
columns), `valid_until` is absent and the expiry check is a no-op.
The contract is forward-compatible: when temporal columns land on
`cold_events`/`ichor_events` in a future phase, results from those
backends will start respecting `0x expired` automatically.

Boost is applied AFTER dedup, so the same title/snippet from two
backends with different god metadata gets its own boost per row.
The list is re-sorted and re-capped after boosting so the caller
sees results in the new order.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Boost multipliers (deliberately small integers / halves so logs are readable)
GOD_BOOST_SAME: float = 2.0
GOD_BOOST_CROSS: float = 1.5
GOD_BOOST_NEUTRAL: float = 1.0
GOD_BOOST_EXPIRED: float = 0.0


def is_entity_expired(
    valid_until: Optional[str],
    status: Optional[str],
    now_iso: str,
    superseded_by: Optional[int] = None,
) -> bool:
    """Return True if an entity is temporally expired.

    Args:
        valid_until: ISO timestamp string from `entities.valid_until`, or None.
        status: Entity status string ('active' | 'archived' | 'merged'), or None.
        now_iso: Reference time as ISO string ('YYYY-MM-DD HH:MM:SS').
        superseded_by: Optional FK id of the replacement entity.

    Returns:
        True if the entity should be filtered out.
    """
    # Status check first — covers 'archived' and 'merged' explicitly
    if status and status != "active":
        return True
    # Superseded-by check — Phase 0 lineage replacement
    if superseded_by is not None:
        return True
    # Temporal expiry — only kicks in when valid_until is set
    if valid_until and valid_until < now_iso:
        return True
    return False


def god_boost_factor(
    god_name: Optional[str],
    active_god: Optional[str],
    expired: bool = False,
) -> float:
    """Compute the boost factor for one result.

    Args:
        god_name: The god that owns this result (None/empty = neutral).
        active_god: The god asking (None/empty disables boost).
        expired: Whether the result is temporally expired.

    Returns:
        Multiplier in {0.0, 1.0, 1.5, 2.0}.
    """
    if expired:
        return GOD_BOOST_EXPIRED
    if not active_god:
        return GOD_BOOST_NEUTRAL
    if not god_name:
        # No god metadata — can't boost, but don't penalize either
        return GOD_BOOST_NEUTRAL
    if god_name == active_god:
        return GOD_BOOST_SAME
    return GOD_BOOST_CROSS


def apply_god_boost(
    results: List[Dict[str, Any]],
    active_god: Optional[str] = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Apply god-scoped boost + temporal filter to a list of retrieval results.

    Modifies each result's `fused_score` in place, sets `boost_factor`
    and `boost_reason` for observability, and returns the list
    (modified + returned for chaining).

    Args:
        results: List of result dicts. Each may carry:
            - fused_score: float (will be modified in place; falls back to score)
            - god_name: str (empty/None = neutral; required for the boost to bite)
            - valid_until: str (ISO timestamp; entity-level expiry)
            - status: str (entity status: active|archived|merged)
            - superseded_by: int (FK id of replacement entity; expired if set)
        active_god: God asking the question. None/empty disables boost (no-op).
        now: Reference time for expiry comparison. Defaults to utcnow().

    Returns:
        The same list (modified in place + returned for chaining).
    """
    if now is None:
        now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%d %H:%M:%S")

    for r in results:
        expired = is_entity_expired(
            r.get("valid_until"),
            r.get("status"),
            now_iso,
            r.get("superseded_by"),
        )
        factor = god_boost_factor(r.get("god_name"), active_god, expired)
        original = r.get("fused_score", r.get("score", 0.0))
        r["fused_score"] = round(float(original) * factor, 4)
        r["boost_factor"] = factor
        if expired:
            r["boost_reason"] = "expired"
        elif active_god and r.get("god_name") == active_god:
            r["boost_reason"] = "same_god"
        elif active_god and r.get("god_name"):
            r["boost_reason"] = "cross_god"
        else:
            r["boost_reason"] = "neutral"

    return results