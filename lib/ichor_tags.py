"""Ichor tag normalization and strict tag/scope SQL filtering.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 1/5).

Semantics of the four match modes (applied BEFORE ranking/truncation):

| Mode         | Include row when ...                                        |
|--------------|-------------------------------------------------------------|
| any          | has at least one requested tag OR has no tags               |
| all          | has all requested tags OR has no tags                       |
| any_strict   | has at least one requested tag (untagged rows excluded)     |
| all_strict   | has all requested tags (untagged rows excluded)             |

Default policy:
- User-scoped calls default to ``any_strict`` when any ``user:<id>`` tag is
  present (enforced at the call site, not here).
- Legacy calls with no tags preserve existing behavior (empty filter).
- Untagged global memory is allowed only when no tags are passed or strict
  mode is not requested.
- ``user:<id>`` tags are NEVER inferred here — they must come from a trusted
  caller or an explicit metadata map.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable, List, Literal, Optional, Tuple

TagsMatch = Literal["any", "all", "any_strict", "all_strict"]

# Canonical tag shape: <scope>:<value> where scope is a lowercase word and
# value is lowercase word chars / dots / dashes / underscores.
NORMAL_TAG_RE = re.compile(r"^[a-z][a-z0-9_-]*:[a-z0-9_.-]+$")

# Valid non-strict modes map (any/all) — used to detect strict requests.
_STRICT_MODES = frozenset({"any_strict", "all_strict"})


def normalize_tag(tag: str) -> str:
    """Normalize a single tag to canonical lowercase ``scope:value`` form.

    Raises:
        ValueError: if the tag cannot be normalized to the canonical shape.
    """
    if tag is None:
        raise ValueError("tag must be a non-empty string")
    cleaned = str(tag).strip().lower()
    if not cleaned:
        raise ValueError("tag must be a non-empty string")
    if not NORMAL_TAG_RE.match(cleaned):
        raise ValueError(
            f"invalid tag {tag!r}: must match {NORMAL_TAG_RE.pattern!r}"
        )
    return cleaned


def normalize_tags(tags: Iterable[str] | None) -> List[str]:
    """Normalize an iterable of tags into a deduped, ordered list.

    ``None``/empty input returns ``[]``. Invalid tags raise ValueError so
    callers fail clearly instead of silently misbehaving.
    """
    if not tags:
        return []
    seen: dict[str, None] = {}
    for tag in tags:
        seen[normalize_tag(tag)] = None
    return list(seen.keys())


def is_strict(tags_match: str | None) -> bool:
    return bool(tags_match) and tags_match in _STRICT_MODES


def default_tags_match(tags: Iterable[str] | None, tags_match: str | None) -> TagsMatch | None:
    """Resolve the effective tags_match mode for a call.

    - No tags → None (legacy behavior: no tag filtering at all).
    - Explicit tags_match → that mode.
    - Tags with a ``user:<id>`` member and no explicit mode → ``any_strict``.
    - Otherwise → ``any``.
    """
    if not tags:
        return None
    if tags_match:
        if tags_match not in ("any", "all", "any_strict", "all_strict"):
            raise ValueError(
                f"invalid tags_match {tags_match!r}: expected any|all|any_strict|all_strict"
            )
        return tags_match  # type: ignore[return-value]
    normalized = normalize_tags(tags)
    if any(t.startswith("user:") for t in normalized):
        return "any_strict"
    return "any"


def build_tag_filter_sql(
    table_alias: str,
    tag_table: str,
    parent_column: str,
    tag_fk_column: str,
    tags: List[str],
    tags_match: TagsMatch,
) -> Tuple[str, List[Any]]:
    """Build a SQL WHERE fragment enforcing one tag match mode.

    The fragment joins ``{tag_table}`` (e.g. ``ichor_event_tags``) whose tag
    column is ``tag`` and whose FK to the parent row is ``{tag_fk_column}``
    (e.g. ``event_id``), on the parent's primary key
    ``{table_alias}.{parent_column}`` (e.g. ``e.id``).

    Returns:
        (sql, params): ``sql`` is ``""`` when there is nothing to filter
        (no tags), in which case callers should skip the fragment entirely.
    """
    if not tags:
        return "", []
    normalized = normalize_tags(tags)
    placeholders = ", ".join("?" * len(normalized))
    fk = f"{table_alias}.{parent_column}"
    exists_any = (
        f"EXISTS (SELECT 1 FROM {tag_table} t "
        f"WHERE t.{tag_fk_column} = {fk} AND t.tag IN ({placeholders}))"
    )
    exists_any_params: List[Any] = list(normalized)
    exists_untagged = (
        f"NOT EXISTS (SELECT 1 FROM {tag_table} t WHERE t.{tag_fk_column} = {fk})"
    )
    all_count = (
        f"(SELECT COUNT(DISTINCT t.tag) FROM {tag_table} t "
        f"WHERE t.{tag_fk_column} = {fk} AND t.tag IN ({placeholders}))"
    )

    if tags_match == "any":
        # At least one requested tag OR untagged.
        return f"({exists_any} OR {exists_untagged})", exists_any_params
    if tags_match == "all":
        # Every requested tag OR untagged.
        sql = (
            f"({exists_untagged} OR {all_count} = ?)"
        )
        return sql, exists_any_params + [len(normalized)]
    if tags_match == "any_strict":
        return exists_any, exists_any_params
    if tags_match == "all_strict":
        return f"({all_count} = ?)", exists_any_params + [len(normalized)]
    raise ValueError(
        f"invalid tags_match {tags_match!r}: expected any|all|any_strict|all_strict"
    )


def attach_event_tags(
    conn: sqlite3.Connection, event_id: int, tags: Iterable[str]
) -> None:
    """Attach normalized tags to an event (idempotent, INSERT OR IGNORE)."""
    normalized = normalize_tags(tags)
    if not normalized:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO ichor_event_tags (event_id, tag) VALUES (?, ?)",
        [(int(event_id), tag) for tag in normalized],
    )


def attach_observation_tags(
    conn: sqlite3.Connection, observation_id: int, tags: Iterable[str]
) -> None:
    """Attach normalized tags to an observation (idempotent)."""
    normalized = normalize_tags(tags)
    if not normalized:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO ichor_observation_tags (observation_id, tag) VALUES (?, ?)",
        [(int(observation_id), tag) for tag in normalized],
    )


def infer_event_tags(
    *,
    god_name: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
) -> List[str]:
    """Infer safe tags for an event: ``god:<name>`` and ``session:<id>`` only.

    ``user:<id>`` tags are never inferred — they require trusted
    caller-provided metadata (``metadata={"user_id": "konan"}``).

    Args:
        god_name: God that produced the event.
        session_id: Source session id.
        metadata: Optional trusted metadata dict. Recognized keys:
            ``user_id`` (trusted user tag source), ``extra_tags`` (iterable
            of additional caller-supplied tags).

    Returns:
        Normalized tag list (valid ones only; invalid values are dropped
        rather than raised so inference never blocks a write).
    """
    inferred: List[str] = []
    meta = metadata or {}

    def _safe(tag: str) -> None:
        try:
            inferred.append(normalize_tag(tag))
        except ValueError:
            pass

    if god_name:
        _safe(f"god:{god_name}")
    if session_id:
        _safe(f"session:{session_id}")
    user_id = meta.get("user_id")
    if user_id:
        _safe(f"user:{user_id}")
    for extra in meta.get("extra_tags") or []:
        _safe(str(extra))
    # Dedupe preserving order.
    seen: dict[str, None] = {}
    return [t for t in inferred if not (t in seen or seen.__setitem__(t, None))]
