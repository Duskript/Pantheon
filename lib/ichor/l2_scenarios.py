"""
L2 Scenarios writer + backfill (P5d, 2026-06-21).

The Overnight Forge previously wrote cross-session patterns as
`digest_entry` events back into ichor_events (L1). P5d introduces a
structured L2 table (l2_scenarios) that the Forge writes to instead.
This module is the write side:

  1. `upsert_scenario(...)` — single-row idempotent insert. The slug
     is the natural key; re-running with the same slug updates the
     existing row instead of creating a duplicate.

  2. `backfill_from_digest_entries(...)` — one-shot backfill for the
     existing `digest_entry` events. Reads every digest_entry that
     came from the forge (the `forge:` key prefix or `scw-event` source
     flag), extracts the topic + source event ids, and writes a
     corresponding l2_scenarios row. Idempotent: re-running is a no-op
     because the slug is derived from the event id.

The new Overnight Forge (`ichor_overnight_forge.py` v2) calls
`upsert_scenario` directly from the cron-emitted JSON; the backfill is
a one-time migration to seed the table with patterns the forge has
already discovered.

Usage:

    # Backfill (one-shot, idempotent):
    python3 -m lib.ichor.l2_scenarios --backfill

    # Verify state:
    python3 -m lib.ichor.l2_scenarios --status

    # Manual upsert:
    from lib.ichor.l2_scenarios import upsert_scenario
    upsert_scenario(
        slug="forge:2026-06-20:1",
        title="...",
        body="...",
        source_events=[42, 43, 44],
        source_sessions=["sess_a", "sess_b"],
        confidence=0.7,
    )
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

_REAL_HOME = Path(
    os.environ.get("REAL_HOME")
    or os.environ.get("HERMES_REAL_HOME")
    or "/home/konan"
)
DB_PATH = _REAL_HOME / ".hermes" / "ichor.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def upsert_scenario(
    *,
    slug: str,
    title: str,
    body: str,
    source_events: list[int] | None = None,
    source_sessions: list[str] | None = None,
    source_gods: list[str] | None = None,
    confidence: float = 0.5,
    pattern_type: str = "cross_session",
    provenance_refs: list[str] | None = None,
    event_count: int | None = None,
    session_count: int | None = None,
    first_seen: str | None = None,
    last_seen: str | None = None,
    status: str = "active",
) -> int:
    """Insert or update a scenario row by slug.

    Returns the row's id (existing or new). Idempotent: re-running
    with the same slug updates the row's body, source lists, and
    timestamps; created_at is preserved on update.
    """
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id, created_at FROM l2_scenarios WHERE slug = ?",
            (slug,),
        ).fetchone()

        payload = {
            "title": title,
            "body": body,
            "source_events": json.dumps(source_events or []),
            "source_sessions": json.dumps(source_sessions or []),
            "source_gods": json.dumps(source_gods or []),
            "confidence": float(confidence),
            "pattern_type": pattern_type,
            "provenance_refs": json.dumps(provenance_refs or []),
            "event_count": int(event_count or len(source_events or [])),
            "session_count": int(session_count or len(source_sessions or [])),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "status": status,
        }

        if existing is None:
            cur = conn.execute(
                """
                INSERT INTO l2_scenarios
                    (slug, title, body, source_events, source_sessions,
                     source_gods, confidence, pattern_type, provenance_refs,
                     event_count, session_count, first_seen, last_seen,
                     status, created_at, updated_at)
                VALUES (:slug, :title, :body, :source_events, :source_sessions,
                        :source_gods, :confidence, :pattern_type, :provenance_refs,
                        :event_count, :session_count, :first_seen, :last_seen,
                        :status, datetime('now'), datetime('now'))
                """,
                {**payload, "slug": slug},
            )
            new_id = cur.lastrowid
        else:
            conn.execute(
                """
                UPDATE l2_scenarios SET
                    title = :title,
                    body = :body,
                    source_events = :source_events,
                    source_sessions = :source_sessions,
                    source_gods = :source_gods,
                    confidence = :confidence,
                    pattern_type = :pattern_type,
                    provenance_refs = :provenance_refs,
                    event_count = :event_count,
                    session_count = :session_count,
                    first_seen = :first_seen,
                    last_seen = :last_seen,
                    status = :status,
                    updated_at = datetime('now')
                WHERE slug = :slug
                """,
                {**payload, "slug": slug},
            )
            new_id = existing["id"]

        conn.commit()
        return int(new_id)
    finally:
        conn.close()


# Patterns we recognize in digest_entry content as forge outputs.
# The forge writes content like:
#   "Overnight Forge found cross-session pattern: <topic>. <desc>. Sources: <ids>"
_FORGE_TOPIC_RE = re.compile(
    r"Overnight Forge found cross-session pattern:\s*"
    r"(?P<topic>.+?)\.\s*"
    r"(?P<desc>.+?)\s*"
    r"Sources?:\s*\[?(?P<sources>[0-9,\s]+)\]?",
    re.DOTALL,
)


def _slug_for_digest(event_id: int, topic: str) -> str:
    """Deterministic slug from (event_id, topic). Idempotent on re-run."""
    h = hashlib.sha1(f"{event_id}:{topic}".encode("utf-8")).hexdigest()[:10]
    safe = re.sub(r"[^a-z0-9]+", "_", topic.lower())[:30].strip("_")
    return f"forge:backfill:e{event_id}:{safe}:{h}"


def backfill_from_digest_entries(
    *,
    min_confidence: float = 0.3,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One-shot backfill: read existing digest_entry events, write l2_scenarios rows.

    Source filter: event_type='digest_entry' AND
    (source LIKE 'forge%' OR session_id LIKE 'thoth-%' OR session_id LIKE 'scw-%'
     OR raw_text LIKE '%Overnight Forge%').

    Pattern: parse the body with _FORGE_TOPIC_RE. If it matches and the
    sources are parseable, write a scenario. Rows that don't match the
    forge pattern are skipped (they're not forge outputs — they're
    shared-context-watcher entries that the L2 layer doesn't need to
    re-encode).

    Returns counts: total_seen, parsed, written, skipped, errors.
    """
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT id, subject, raw_text, god_name, session_id,
                   created_at, importance
            FROM ichor_events
            WHERE event_type = 'digest_entry'
              AND raw_text LIKE '%Overnight Forge found cross-session pattern%'
            ORDER BY id DESC
            """,
        ).fetchall()

        counts = {
            "total_seen": len(rows),
            "parsed": 0,
            "written": 0,
            "skipped_no_match": 0,
            "skipped_low_confidence": 0,
            "errors": 0,
        }

        for r in rows:
            text = r["raw_text"] or ""
            m = _FORGE_TOPIC_RE.search(text)
            if not m:
                counts["skipped_no_match"] += 1
                continue
            topic = m.group("topic").strip()[:80]
            desc = m.group("desc").strip()[:400]
            sources_str = m.group("sources").strip()
            try:
                source_ids = [
                    int(x.strip())
                    for x in sources_str.split(",")
                    if x.strip().isdigit()
                ]
            except Exception:
                source_ids = []

            counts["parsed"] += 1

            # Confidence heuristic: 0.4 base + 0.1 per source event (capped at 0.95).
            # This is intentionally rough — the forge agent's own confidence
            # would be better but we don't have access to it post-hoc.
            confidence = min(0.95, 0.4 + 0.1 * len(source_ids))
            if confidence < min_confidence:
                counts["skipped_low_confidence"] += 1
                continue

            slug = _slug_for_digest(r["id"], topic)

            if dry_run:
                continue

            try:
                upsert_scenario(
                    slug=slug,
                    title=f"Cross-session pattern: {topic}",
                    body=desc,
                    source_events=source_ids,
                    source_sessions=[r["session_id"]] if r["session_id"] else [],
                    source_gods=[r["god_name"]] if r["god_name"] else [],
                    confidence=confidence,
                    pattern_type="cross_session",
                    provenance_refs=[f"ichor_events:{r['id']}"],
                    event_count=len(source_ids),
                    session_count=1,
                    first_seen=r["created_at"],
                    last_seen=r["created_at"],
                    status="active",
                )
                counts["written"] += 1
            except Exception as exc:
                counts["errors"] += 1
                counts["_last_error"] = str(exc)

        return counts
    finally:
        conn.close()


def get_status() -> dict[str, Any]:
    """Return the L2 layer state — table exists + row count + samples."""
    conn = _connect()
    try:
        try:
            total = conn.execute("SELECT COUNT(*) FROM l2_scenarios").fetchone()[0]
        except sqlite3.OperationalError as exc:
            return {"table_exists": False, "error": str(exc)}

        by_type = {
            r["pattern_type"]: r["n"]
            for r in conn.execute(
                "SELECT pattern_type, COUNT(*) AS n FROM l2_scenarios "
                "GROUP BY pattern_type"
            ).fetchall()
        }
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM l2_scenarios GROUP BY status"
            ).fetchall()
        }

        # Top 5 by confidence for a sample.
        samples = conn.execute(
            "SELECT slug, pattern_type, title, confidence, event_count, "
            "       session_count, last_seen "
            "FROM l2_scenarios "
            "ORDER BY confidence DESC, last_seen DESC "
            "LIMIT 5"
        ).fetchall()
        sample_dicts = [dict(r) for r in samples]

        return {
            "table_exists": True,
            "total": total,
            "by_pattern_type": by_type,
            "by_status": by_status,
            "top_5": sample_dicts,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    import json
    import sys

    if "--status" in sys.argv:
        print(json.dumps(get_status(), indent=2, default=str))
    elif "--backfill" in sys.argv:
        dry = "--dry-run" in sys.argv
        print(json.dumps(
            backfill_from_digest_entries(dry_run=dry),
            indent=2, default=str,
        ))
    elif "--backfill-and-status" in sys.argv:
        bf = backfill_from_digest_entries()
        print("--- backfill ---")
        print(json.dumps(bf, indent=2, default=str))
        print("--- status ---")
        print(json.dumps(get_status(), indent=2, default=str))
    else:
        print("Usage: python3 -m lib.ichor.l2_scenarios "
              "[--status | --backfill [--dry-run] | --backfill-and-status]")
        sys.exit(1)
