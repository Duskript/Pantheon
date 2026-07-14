"""
L2 Scenarios Query Extension for L2ReferenceBackend (P5d, 2026-06-21)
========================================================================

Why this module exists
----------------------

The Ichor v2 architecture (ichor-v2-build-blueprint.md §1) defines a
4-layer model:

    L0 RAW            cold_events, raw signals
    L1 ATOMIC         ichor_events, tier_a events, structured facts
    L2 SCENARIO       cross-session patterns, validated entities, compiled refs
    L3 PERSONA        god-specific worldview, derived from L2

The L2 Scenario layer is what the Overnight Forge (cron c7c93416a2dc)
produces. Pre-P5d, the Forge wrote its outputs back to L1 as
`digest_entry` events — the data was correct but the *shape* was wrong.
L1 events are atomic; L2 scenarios are cross-session patterns with
source-event provenance, confidence scores, and pattern-type tags.

P5d (2026-06-21) added a structured l2_scenarios table that the Forge
writes to. The companion `lib.ichor.l2_scenarios` module is the write
side (upsert_scenario, backfill_from_digest_entries). This module is
the read side — a thin query helper that the L2ReferenceBackend can
call without modifying ichor_hybrid.py directly.

The split is deliberate: ichor_hybrid.py is the monolithic HybridScorer
that the system depends on for every `ichor_retrieve` call, and editing
it has historically been a recipe for stale-import failures (the
pantheon-mcp service caches the module at process start). By keeping
this query extension in its own module, the L2 layer can be evolved
without triggering an MCP restart for every change.

The function `query_l2_scenarios` returns results in the unified result
dict shape that HybridScorer expects:

    {
        "id": "l2-scenario:<rowid>",
        "score": 0.85,                      # 0.5-1.0, driven by confidence
        "backend": "reference",             # the L2 backend label
        "type": "l2_scenario_<pattern_type>",  # e.g. l2_scenario_recurring_blocker
        "title": "<scenario title>",
        "snippet": "<body, truncated to 300 chars>",
        "source": "<slug>",
        "created_at": "<last_seen timestamp>",
        "l2_metadata": {
            "maturity": "scenario",
            "importance": 80,
            "trust": 80,
            "pattern_type": "<pattern_type>",
            "event_count": <int>,
            "session_count": <int>,
        },
    }

Score formula: 0.7 base + 0.3 * confidence, capped at [0.5, 1.0]. The
0.7 base reflects the fact that L2 scenarios are validated patterns
(not raw extracted facts); the confidence multiplier reflects the
agent's own assessment of evidence density.

Graceful degradation: if the l2_scenarios table doesn't exist (pre-
P5d migration), the function returns an empty list. The caller
(L2ReferenceBackend.search) treats empty as "no L2 hits" and the
query still gets results from the other L2 sources (warm_entities,
reference_knowledge) and from the other 4 backends (FTS5, vector,
graph, events).

Usage:

    from lib.ichor.l2_scenarios_query import query_l2_scenarios
    hits = query_l2_scenarios("%overnight_forge%", limit=5)
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger("ichor.l2_scenarios_query")

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


def query_l2_scenarios(pattern: str, limit: int = 5) -> List[Dict[str, Any]]:
    """LIKE-scan l2_scenarios (Forge cross-session patterns).

    Returns list of result dicts in the unified HybridScorer shape.
    Scenarios are scored by the agent's confidence: 0.7 base + 0.3 *
    confidence, capped at 1.0. The table may not exist on pre-P5d
    DBs; degrade gracefully and return an empty list if so.
    """
    if not pattern:
        return []
    try:
        conn = _connect()
        rows = conn.execute(
            """
            SELECT id, slug, pattern_type, title, body, confidence,
                   event_count, session_count, last_seen
            FROM l2_scenarios
            WHERE status = 'active'
              AND (title LIKE ? OR body LIKE ? OR slug LIKE ?)
            ORDER BY confidence DESC, last_seen DESC
            LIMIT ?
            """,
            (pattern, pattern, pattern, limit),
        ).fetchall()
        conn.close()
    except Exception as exc:
        logger.debug("L2 scenarios query failed: %s", exc)
        return []

    results: list = []
    for r in rows:
        snippet = (r["body"] or "")[:300]
        score = max(0.5, min(1.0, 0.7 + (r["confidence"] or 0) * 0.3))
        results.append({
            "id": f"l2-scenario:{r['id']}",
            "score": round(score, 3),
            "backend": "reference",
            "type": f"l2_scenario_{r['pattern_type']}",
            "title": r["title"] or r["slug"] or "",
            "snippet": snippet,
            "source": r["slug"] or "",
            "created_at": r["last_seen"] or "",
            "l2_metadata": {
                "maturity": "scenario",
                "importance": 80,
                "trust": 80,
                "pattern_type": r["pattern_type"] or "",
                "event_count": r["event_count"] or 0,
                "session_count": r["session_count"] or 0,
            },
        })
    return results
