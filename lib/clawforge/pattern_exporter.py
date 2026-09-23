"""Clawforge memory pattern exporter.

Reads the local outcome tracking data (via `lib.clawforge.memory_api`)
and emits a `memory.pattern.submitted` payload to NATS.

This is the Pass 3.1 counterpart to `adjustment_exporter.py` (which
ships forge adjustment data). Same anonymization contract: no
session_id, no raw query text, no result_ids. The shape follows the
spec at `~/athenaeum/soulforge/clawforge/clawforge-revision-meta-learning.md`
§3.1.

Output schema (matches spec §3.1 example):
  {
    "schema_version": 1,
    "instance_id": <sha256(machine_id)[:12]>,
    "submitted_at": <iso8601>,
    "span_days": int,
    "total_queries": int,
    "patterns": [
      { "query_class": str, "outcome": str, "count": int, "confidence": float },
      ...
    ],
    "retrieval_stats": {
      "total_queries": int,
      "span_days": int,
      "by_outcome": { outcome: count, ... },
      "backend_usage": { backend: count, ... },
      "avg_result_count": float,
      "max_result_count": int,
      "weight_distribution": { backend: avg_weight, ... },
    },
    "coverage_gaps": {
      "by_type": { event_type: { total, tier_a, coverage_pct, gap } },
      "low_coverage_types": [str, ...],
      "threshold_pct": float,
      "total_events": int,
      "total_tier_a": int,
      "overall_coverage_pct": float,
    },
  }

Usage:
    # Build only (no NATS, for tests)
    entry = export_memory_patterns(instance_id)
    assert_anonymized(entry)

    # Build + run all three export legs (real run)
    result = await run(days=7)
    assert result["published_local"]

Self-test (requires `lib/` on sys.path):
    PYTHONPATH=/home/konan/pantheon/lib \
      python3 -m clawforge.pattern_exporter
prints the entry and asserts anonymization.

The three export legs (local artifact / local relay / federation) are shared
with the other exporters in `clawforge.legs`; this module only owns the payload.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Optional

from clawforge.legs import (  # type: ignore
    _find_token_path,
    load_token,
    now_iso as _now,
    publish,
    run_legs,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-pattern-exporter")


# Token loading, `_now`, `publish` and the three-leg run live in
# `clawforge.legs`. They used to be duplicated here and in the other two
# exporters, which is how this lane kept a hardcoded peer address as its
# silent destination and had no local leg at all while `adjustment_exporter`
# was fixed. See that module's docstring for the gating rules.


def export_memory_patterns(
    instance_id: str,
    days: int = 7,
    *,
    min_cluster_size: int = 2,
) -> dict[str, Any]:
    """Build the memory-patterns.json submission entry from local
    outcome + coverage data.

    The wrapper script `clawforge_export_run.py` calls `run(days)`, but
    this pure function is also exported so tests can build entries
    without touching NATS or the live token file.

    Args:
        instance_id: anonymous instance id (12 hex chars).
        days: window for outcome/learning queries. Default 7.
        min_cluster_size: drop pattern clusters smaller than this.
            Default 2 so singletons don't dominate.

    Returns:
        Dict matching the spec's `memory.pattern.submitted` payload.
    """
    # Import here (not at module top) so the self-test can run
    # without nats-py installed. The `clawforge_export_run.py`
    # wrapper inserts /home/konan/pantheon/lib onto sys.path so the
    # bare-name `clawforge.memory_api` works.
    from clawforge.memory_api import (  # type: ignore
        compute_retrieval_stats,
        detect_tier_a_coverage_gaps,
        extract_patterns_from_outcomes,
        get_recent_outcomes,
    )

    # 1. Gather outcome tracking data
    outcomes = get_recent_outcomes(days=days)

    # 2. Extract patterns (anonymized query_class clusters)
    patterns_raw = extract_patterns_from_outcomes(
        outcomes, min_cluster_size=min_cluster_size,
    )
    patterns = [
        {
            "query_class": p.query_class,
            "outcome": p.outcome,
            "count": p.count,
            "confidence": round(p.confidence, 3),
        }
        for p in patterns_raw
    ]

    # 3. Compute retrieval stats (aggregates only — no raw entries)
    stats = compute_retrieval_stats(outcomes)

    # 4. Identify coverage gaps
    coverage = detect_tier_a_coverage_gaps()

    entry = {
        "schema_version": 1,
        "instance_id": instance_id,
        "submitted_at": _now(),
        "span_days": days,
        "total_queries": outcomes.total,
        "patterns": patterns,
        "retrieval_stats": stats,
        "coverage_gaps": coverage,
    }
    return entry


def assert_anonymized(entry: dict) -> None:
    """Self-test guard: ensure no forbidden keys are present in the
    submission entry.

    Per spec §9, forbidden keys at any level:
      - session_id
      - query (raw query text — only `query_class` hashes allowed)
      - user_id, user_intent (raw text)
      - raw_text, raw_event_text
    """
    forbidden = {
        "session_id", "query", "user_id", "user_intent",
        "raw_text", "raw_event_text",
    }
    # Top-level
    for k in forbidden:
        if k in entry:
            raise AssertionError("forbidden key at top level: " + k)
    # Patterns: query_class is OK, raw "query" is not
    for p in entry.get("patterns", []):
        for k in forbidden:
            if k in p:
                raise AssertionError("forbidden key in pattern: " + k)
        # query_class is the only query-related key allowed
        if "query" in p and "query_class" not in p:
            raise AssertionError("pattern has 'query' but not 'query_class'")
    # Stats: must not contain raw entries/queries at any depth
    stats = entry.get("retrieval_stats", {})
    stats_s = json.dumps(stats) if stats else ""
    if "user_intent" in stats_s or "session_id" in stats_s:
        raise AssertionError("retrieval_stats must not contain raw text fields")
    # Coverage: must not contain raw events
    coverage = entry.get("coverage_gaps", {})
    for k in ("events", "raw_events", "samples"):
        if k in coverage:
            raise AssertionError(
                "coverage_gaps must not contain raw events"
            )
    # instance_id format
    inst = entry.get("instance_id", "")
    if len(inst) != 12 or not all(c in "0123456789abcdef" for c in inst):
        raise AssertionError("instance_id wrong format: " + repr(inst))


async def run(days: int = 7, share: Optional[bool] = None) -> dict[str, Any]:
    """Run all three export legs and report which fired.

    `share` overrides config detection. None means read the per-system
    `pattern_sharing` opt-in (see `clawforge.legs.sharing_allowed_for`).

    Returns the summary dict from `run_legs`: `published_local` covers the local
    artifact + local relay legs (the ones local self-improvement depends on) and
    `published_remote` covers the federation leg. The built payload is under
    `entry`; the local counts are echoed as `pattern_count` / `total_queries`.

    Matches the contract of `adjustment_exporter.run` so the wrapper script
    `clawforge_export_run.py` can call it generically.
    """
    from clawforge.instance_id import get_instance_id  # type: ignore

    instance_id = get_instance_id()
    entry = export_memory_patterns(instance_id, days=days)
    assert_anonymized(entry)

    result = await run_legs("memory", entry, share=share)
    result["pattern_count"] = len(entry["patterns"])
    result["total_queries"] = entry["total_queries"]
    log.info(
        "memory.pattern.submitted: %d patterns, %d queries, %d gap types "
        "(local=%s, federation=%s)",
        len(entry["patterns"]),
        entry["total_queries"],
        len(entry["coverage_gaps"].get("low_coverage_types", [])),
        result["published_local"],
        result["published_remote"],
    )
    return result


if __name__ == "__main__":
    # Self-test: build the entry, print it, assert anonymization.
    from clawforge.instance_id import get_instance_id  # type: ignore

    inst = get_instance_id()
    entry = export_memory_patterns(inst, days=30)
    assert_anonymized(entry)
    print(json.dumps(entry, indent=2))
    print("---")
    print(
        "self-test OK: instance_id=" + inst
        + ", patterns=" + str(len(entry["patterns"]))
        + ", total_queries=" + str(entry["total_queries"])
        + ", gap_types=" + str(len(
            entry["coverage_gaps"].get("low_coverage_types", [])
        ))
    )

    # If --publish flag passed, actually publish
    if "--publish" in sys.argv:
        asyncio.run(run(days=30))
