#!/usr/bin/env python3
"""Bounded authoritative enrichment for the current Dojo candidate snapshot."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("/home/konan/.hermes/ichor.db")
CANDIDATE_IDS = [
    2195284,
    2191808,
    2191807,
    2191806,
    2191804,
    2191802,
    2191800,
    2191798,
    2179447,
    2174966,
]


def main() -> None:
    connection = sqlite3.connect(str(DB_PATH))
    connection.row_factory = sqlite3.Row
    placeholders = ",".join("?" for _ in CANDIDATE_IDS)
    candidates = connection.execute(
        f"""
        SELECT id, session_id, subject, event_type, importance, created_at,
               status, LENGTH(raw_text) AS raw_text_length,
               SUBSTR(REPLACE(raw_text, char(10), ' '), 1, 180) AS preview
        FROM ichor_events
        WHERE id IN ({placeholders})
        ORDER BY CASE id
            {" ".join(f"WHEN ? THEN {index}" for index, _ in enumerate(CANDIDATE_IDS))}
            ELSE {len(CANDIDATE_IDS)} END
        """,
        (*CANDIDATE_IDS, *CANDIDATE_IDS),
    ).fetchall()

    session_ids = sorted({row["session_id"] for row in candidates if row["session_id"]})
    aggregates = []
    latest_rows = []
    for session_id in session_ids:
        aggregate = connection.execute(
            """
            SELECT session_id, COUNT(*) AS row_count,
                   MIN(created_at) AS first_created_at,
                   MAX(created_at) AS last_created_at,
                   SUM(CASE WHEN status IN ('completed', 'complete', 'success', 'done')
                            THEN 1 ELSE 0 END) AS terminal_status_count,
                   SUM(CASE WHEN status IN ('active', 'pending', 'in_progress', 'blocked')
                            THEN 1 ELSE 0 END) AS unresolved_status_count
            FROM ichor_events
            WHERE session_id = ?
            GROUP BY session_id
            """,
            (session_id,),
        ).fetchone()
        aggregates.append(dict(aggregate) if aggregate else {"session_id": session_id})
        latest = connection.execute(
            """
            SELECT id, session_id, event_type, subject, status, created_at,
                   SUBSTR(REPLACE(raw_text, char(10), ' '), 1, 180) AS preview
            FROM ichor_events
            WHERE session_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 8
            """,
            (session_id,),
        ).fetchall()
        latest_rows.extend(dict(row) for row in latest)

    connection.close()
    print(json.dumps({
        "candidate_ids": CANDIDATE_IDS,
        "candidate_rows": [dict(row) for row in candidates],
        "session_aggregates": aggregates,
        "latest_rows": latest_rows,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
