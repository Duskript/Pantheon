"""Ichor write-time reconciliation helpers.

Phase 2 R-Memory: opt-in reconciliation against the live event store.
This module keeps the policy small and deterministic so the MCP write
path can call it without dragging in extra infrastructure.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from lib.ichor_db import IchorDB

_RECONCILE_EVENT_TYPE = "correction"
_VALUE_BEARING_CATEGORIES = frozenset({
    "fact",
    "preference",
    "decision",
    "commitment",
    "insight",
    "blocker",
    "follow_up",
    "correction",
    "reference",
    "user_md_update",
})


def _row_text(row: sqlite3.Row | dict[str, Any]) -> str:
    """Fold an event row into a single contradiction-check string."""
    if hasattr(row, "keys"):
        keys = row.keys()  # type: ignore[call-arg]
        parts = [str(row[k] or "") for k in ("subject", "predicate", "object", "raw_text") if k in keys]
    else:
        parts = [str(row.get(k) or "") for k in ("subject", "predicate", "object", "raw_text")]
    return " ".join(part for part in parts if part).strip()


def reconcile_memory_event(
    db: IchorDB,
    *,
    namespace: str,
    key: str,
    content: str,
    category: str,
    session_id: str,
    god_name: str,
    inserted_event_id: int,
    limit: int = 5,
) -> dict[str, Any]:
    """Apply a tiny, deterministic write-time reconciliation pass.

    The current implementation is intentionally conservative:
    - only value-bearing categories participate
    - only the most recent matching memory in the same namespace/god is considered
    - if the new content contradicts that candidate, the older row is deleted
      and a correction event is recorded for the audit trail

    Returns a structured summary for MCP callers and audit logs.
    """
    if category not in _VALUE_BEARING_CATEGORIES:
        return {
            "applied": False,
            "operation": "NOOP",
            "reason": "category_not_reconciled",
            "candidate_ids": [],
            "deleted_ids": [],
            "recorded_event_id": None,
        }

    if not content.strip():
        return {
            "applied": False,
            "operation": "NOOP",
            "reason": "empty_content",
            "candidate_ids": [],
            "deleted_ids": [],
            "recorded_event_id": None,
        }

    conn = db.connect()
    match_subject = key.strip() or content.strip()[:80]
    god_filter = god_name.strip() or namespace.strip() or ""
    params: list[Any] = [match_subject, inserted_event_id]
    sql = (
        "SELECT id, subject, predicate, object, raw_text, session_id, event_type, god_name "
        "FROM ichor_events "
        "WHERE subject = ? AND id != ?"
    )
    if god_filter:
        sql += " AND COALESCE(god_name, '') = ?"
        params.append(god_filter)
    sql += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    candidate_ids = [int(row["id"]) for row in rows]
    if not rows:
        return {
            "applied": False,
            "operation": "NOOP",
            "reason": "no_candidates",
            "candidate_ids": [],
            "deleted_ids": [],
            "recorded_event_id": None,
        }

    # Load the matcher lazily to avoid an import cycle at module import time.
    from lib.ichor_hybrid import detect_contradiction

    for row in rows:
        old_text = _row_text(row)
        if not old_text:
            continue
        if detect_contradiction(old_text, content):
            deleted_id = int(row["id"])
            conn.execute("DELETE FROM ichor_events WHERE id = ?", (deleted_id,))
            # Keep the audit trail readable: record what happened without
            # stuffing the full content back into the correction row.
            summary = (
                f"Reconciled {match_subject!r} in namespace {namespace!r}; "
                f"superseded event {deleted_id} after contradiction detection."
            )
            correction_id = db.insert_event(
                session_id=session_id or match_subject,
                event_type=_RECONCILE_EVENT_TYPE,
                subject=match_subject,
                predicate="reconciles",
                object=str(deleted_id),
                confidence=1.0,
                source="reconcile",
                raw_text=summary,
                god_name=god_name or namespace,
            )
            conn.commit()
            return {
                "applied": True,
                "operation": "UPDATE",
                "reason": "contradiction_detected",
                "candidate_ids": candidate_ids,
                "deleted_ids": [deleted_id],
                "recorded_event_id": correction_id,
            }

    return {
        "applied": False,
        "operation": "NOOP",
        "reason": "no_contradiction",
        "candidate_ids": candidate_ids,
        "deleted_ids": [],
        "recorded_event_id": None,
    }
