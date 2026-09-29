"""Ichor temporal helpers: as-of validity, active-at checks, rank boosts.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 1/7).

Active rules:

- ``status != 'active'`` is inactive unless the caller explicitly asks for
  archived/superseded rows (``include_inactive=True`` at the call site).
- ``valid_until < query_timestamp`` is inactive.
- ``valid_from > query_timestamp`` is inactive.
- If no ``query_timestamp`` is supplied, validity windows are NOT
  wall-clock-expired; only the ``status != 'active'`` exclusion applies.
- ``mentioned_at`` defaults to ``created_at`` during migration/backfill.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, List, Mapping, Optional, Tuple

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")
_UTC = timezone.utc


def parse_iso_z(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (with optional Z / offset) to aware UTC.

    Accepts ``YYYY-MM-DDTHH:MM:SS``, ``YYYY-MM-DD HH:MM:SS`` (SQLite
    ``datetime('now')`` shape), with optional ``Z`` or ``+HH:MM`` suffix.
    Returns ``None`` for empty/unparseable input — never raises.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return dt.astimezone(_UTC)
    except (ValueError, TypeError):
        return None


def normalize_timestamp(value: str | datetime | None) -> str | None:
    """Normalize a timestamp to a canonical ``YYYY-MM-DDTHH:MM:SSZ`` string.

    ``None``/unparseable input returns ``None``. Naive datetimes are
    assumed to be UTC (SQLite convention).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_UTC)
        return dt.astimezone(_UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    parsed = parse_iso_z(str(value))
    if parsed is None:
        return None
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── SQL-side normalisation of stored timestamps ─────────────────────────
#
# `created_at` is written in FOUR different shapes by different writers:
#
#   'YYYY-MM-DD HH:MM:SS'               SQLite `DEFAULT (datetime('now'))`
#   'YYYY-MM-DDTHH:MM:SSZ'              explicit ISO-8601 UTC
#   'YYYY-MM-DDTHH:MM:SS.ffffff+00:00'  `datetime.isoformat()` (aware)
#   'YYYY-MM-DDTHH:MM:SS'               naive ISO (`strftime`, no suffix)
#
# All four are UTC, but comparing the RAW column against a literal of a
# different shape is only correct down to the DAY. At offset 10 the separator
# differs -- ' ' (0x20) vs 'T' (0x54) -- so on the boundary day a space-shaped
# row sorts BEFORE an ISO-shaped row whatever the actual times are.
#
# Live example (2026-09-22): the eviction predicate
# `created_at < '2026-06-24T13:52:42+00:00'` matched id 164078 at
# '2026-06-24 23:51:31' -- a row 89.6 days old, not 90 -- because ' ' < 'T'
# decided the comparison. The error is in the DELETE direction: the job evicts
# rows that are not yet old enough. The reverse direction exists too
# (2026-09-22 morning-briefing's 14h lookback used a naive-'T' cutoff, which
# dropped space-shaped rows written after the boundary).
#
# `datetime()` parses all four shapes -- and any explicit offset, converted to
# UTC -- and returns 'YYYY-MM-DD HH:MM:SS', so normalising BOTH sides makes the
# comparison exact. Unparseable input yields NULL and `NULL < x` is false, so a
# malformed timestamp can never be treated as old enough to delete.
#
# Cost: wrapping the column forfeits any index on it. Measured on the live DB
# (81k rows): the age-bound scan is 0.7 ms normalised vs 2.6 ms raw (the
# importance index still drives the plan); a bare recent-window scan over the
# whole table costs ~27 ms vs 1.1 ms. Use it where correctness matters; do not
# put it in a per-request hot loop over a very large table.
CREATED_AT_SHAPES: tuple[str, ...] = (
    "YYYY-MM-DD HH:MM:SS",
    "YYYY-MM-DDTHH:MM:SSZ",
    "YYYY-MM-DDTHH:MM:SS.ffffff+00:00",
    "YYYY-MM-DDTHH:MM:SS",
)


def sql_utc(column: str = "created_at") -> str:
    """SQLite expression normalising a stored timestamp to UTC.

    Use it on BOTH sides of every comparison against a time literal::

        WHERE {sql_utc("created_at")} < datetime('now', '-90 day')

    See ``CREATED_AT_SHAPES`` above for why the raw column cannot be compared
    to a differently-shaped literal.
    """
    return f"datetime({column})"


def _relative_bound(days: int | None, hours: int | None) -> str:
    if (days is None) == (hours is None):
        raise ValueError("pass exactly one of days= or hours=")
    if days is not None:
        modifier = f"-{int(days)} day"
    else:
        assert hours is not None
        modifier = f"-{int(hours)} hour"
    return f"datetime('now', '{modifier}')"


def older_than_sql(
    column: str = "created_at", *, days: int | None = None, hours: int | None = None
) -> str:
    """Normalised ``column < now - N`` fragment (no leading WHERE).

    e.g. ``older_than_sql("created_at", days=90)`` →
    ``datetime(created_at) < datetime('now', '-90 day')``.
    """
    return f"{sql_utc(column)} < {_relative_bound(days, hours)}"


def newer_than_sql(
    column: str = "created_at", *, days: int | None = None, hours: int | None = None
) -> str:
    """Normalised ``column >= now - N`` fragment (no leading WHERE)."""
    return f"{sql_utc(column)} >= {_relative_bound(days, hours)}"


def event_best_timestamp(row: Mapping[str, Any]) -> str | None:
    """Pick the best event timestamp: occurred_start > occurred_end >
    mentioned_at > created_at. Returns canonical ISO string or None.
    """
    for key in ("occurred_start", "occurred_end", "mentioned_at", "created_at"):
        raw = row.get(key)
        if raw:
            norm = normalize_timestamp(raw)
            if norm:
                return norm
    return None


def is_active_at(
    row: Mapping[str, Any],
    query_timestamp: str | datetime | None,
) -> bool:
    """Return True when a row is active at the query timestamp.

    - ``status != 'active'`` (and not NULL) → inactive.
    - ``valid_until < query_timestamp`` → inactive.
    - ``valid_from > query_timestamp`` → inactive.
    - No ``query_timestamp`` → validity windows are not enforced; only the
      status exclusion applies.
    """
    status = row.get("status")
    if status is not None and str(status).strip().lower() != "active":
        return False
    if query_timestamp is None:
        return True
    qt = parse_iso_z(str(query_timestamp))
    if qt is None:
        # Unparseable anchor — be conservative and treat as active (no
        # temporal evidence to expire the row).
        return True
    valid_until = row.get("valid_until")
    if valid_until:
        vu = parse_iso_z(str(valid_until))
        if vu is not None and vu < qt:
            return False
    valid_from = row.get("valid_from")
    if valid_from:
        vf = parse_iso_z(str(valid_from))
        if vf is not None and vf > qt:
            return False
    return True


# Rank boost constants — small, bounded, deterministic.
_TEMPORAL_CLOSE_DAYS = 7.0
_TEMPORAL_CLOSE_BOOST = 0.05
_TEMPORAL_FAR_PENALTY = -0.05
_TEMPORAL_PER_DAY = 0.004


def temporal_rank_boost(
    row: Mapping[str, Any],
    query_timestamp: str | datetime | None,
) -> Tuple[float, List[str]]:
    """Compute a bounded additive temporal rank boost for one result.

    When a ``query_timestamp`` is supplied, rows whose best timestamp is
    temporally close to the anchor get a small boost; far rows get a small
    penalty. Returns ``(boost, reasons)``.

    No ``query_timestamp`` → ``(0.0, [])`` (no temporal signal).
    """
    if query_timestamp is None:
        return 0.0, []
    qt = parse_iso_z(str(query_timestamp))
    if qt is None:
        return 0.0, []
    best = event_best_timestamp(row)
    if best is None:
        return 0.0, []
    ts = parse_iso_z(best)
    if ts is None:
        return 0.0, []
    delta_days = abs((qt - ts).total_seconds()) / 86400.0
    if delta_days <= _TEMPORAL_CLOSE_DAYS:
        boost = _TEMPORAL_CLOSE_BOOST
        reasons = ["temporal_close"]
    else:
        boost = max(_TEMPORAL_FAR_PENALTY, -_TEMPORAL_PER_DAY * delta_days)
        reasons = ["temporal_far"]
    return round(boost, 4), reasons


def days_between(a: str | None, b: str | None) -> float:
    """Whole-day span between two timestamps (0.0 when either is missing)."""
    da, db = parse_iso_z(a), parse_iso_z(b)
    if da is None or db is None:
        return 0.0
    return round(abs((db - da).total_seconds()) / 86400.0, 3)


def is_within_days(timestamp: str | None, reference: datetime, days: int) -> bool:
    """True when ``timestamp`` is within ``days`` before ``reference``."""
    ts = parse_iso_z(timestamp)
    if ts is None:
        return False
    return reference - ts <= timedelta(days=days) and ts <= reference + timedelta(days=1)
