"""Clawforge learning exporter.

Reads the entity `relationships` table for "learning" type edges
(learned_from, superseded_by, informed_by, built_on) and emits a
`dojo.learning.submitted` payload to NATS.

This is the Pass 3.1 counterpart to the
`phronesis_learning_exporter` (formerly "Dojo learning exporter"
in the spec). Same anonymization contract as the other exporters.

The spec calls this `dojo.learning.submitted`; we keep that NATS
subject for backward compatibility with the existing pattern
subscriber (E2.3 upgrades will accept either).

Output schema (matches spec §3.3 example):
  {
    "schema_version": 1,
    "instance_id": <sha256(machine_id)[:12]>,
    "submitted_at": <iso8601>,
    "span_days": int,
    "total_learnings": int,
    "learnings": [
      {
        "id": int,
        "type": "learned_from" | "superseded_by" | "informed_by" | "built_on",
        "source_id": int,
        "target_id": int,
        "confidence": float,
        "weight": float,
        "created_at": <iso8601>,
        "days_ago": int,
        "provenance": "phronesis" | "llm" | "manual" | "regex" | "dream_cycle" | ...,
      },
      ...
    ],
    "by_type": { "learned_from": int, "superseded_by": int, ... },
  }

Usage:
    # Build only (no NATS, for tests)
    entry = export_dojo_learnings(instance_id)
    assert_anonymized(entry)

    # Build + run all three export legs (real run)
    result = await run(days=7)
    assert result["published_local"]

Self-test (requires `lib/` on sys.path):
    PYTHONPATH=/home/konan/pantheon/lib \
      python3 -m clawforge.learning_exporter
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
log = logging.getLogger("clawforge-learning-exporter")


# Token loading, `_now`, `publish` and the three-leg run live in
# `clawforge.legs`. They used to be duplicated here and in the other two
# exporters, which is how this lane kept a hardcoded peer address as its
# silent destination and had no local leg at all while `adjustment_exporter`
# was fixed. See that module's docstring for the gating rules.


def export_dojo_learnings(
    instance_id: str,
    days: int = 7,
) -> dict[str, Any]:
    """Build the dojo-learnings.json submission entry from local
    entity-relationship data.

    The wrapper script `clawforge_export_run.py` calls `run(days)`, but
    this pure function is also exported so tests can build entries
    without touching NATS or the live token file.

    Args:
        instance_id: anonymous instance id (12 hex chars).
        days: window for the learning query. Default 7.

    Returns:
        Dict matching the spec's `dojo.learning.submitted` payload.
    """
    # Import here (not at module top) so the self-test can run
    # without nats-py installed. The `clawforge_export_run.py`
    # wrapper inserts /home/konan/pantheon/lib onto sys.path so the
    # bare-name `clawforge.memory_api` works.
    from clawforge.memory_api import get_recent_learnings  # type: ignore

    # 1. Gather learning-type relationships from the entity graph
    raw_learnings = get_recent_learnings(days=days)

    # 2. Group by type for the `by_type` summary
    by_type: dict[str, int] = {}
    for lrn in raw_learnings:
        by_type[lrn["type"]] = by_type.get(lrn["type"], 0) + 1

    # 3. Strip provenance to the canonical form (provenance strings
    # can be long; "phronesis" / "llm" / "manual" is enough)
    learnings = [
        {
            "id": lrn["id"],
            "type": lrn["type"],
            "source_id": lrn["source_id"],
            "target_id": lrn["target_id"],
            "confidence": round(float(lrn["confidence"]), 3),
            "weight": round(float(lrn["weight"]), 3),
            "created_at": lrn["created_at"],
            "days_ago": lrn["days_ago"],
            "provenance": lrn["provenance"],
        }
        for lrn in raw_learnings
    ]

    entry = {
        "schema_version": 1,
        "instance_id": instance_id,
        "submitted_at": _now(),
        "span_days": days,
        "total_learnings": len(learnings),
        "learnings": learnings,
        "by_type": by_type,
    }
    return entry


def assert_anonymized(entry: dict) -> None:
    """Self-test guard: ensure no forbidden keys are present in the
    submission entry.

    Per spec §9, forbidden keys:
      - session_id
      - user_id, user_intent
      - raw_text, raw_event_text
      - source_ref (might contain raw event text)

    We also verify that source_id and target_id are integers (not
    names), and that the `learnings` list does not carry any
    free-form text fields beyond the typed schema.
    """
    forbidden = {
        "session_id", "user_id", "user_intent",
        "raw_text", "raw_event_text", "source_ref",
        "query", "notes",
    }
    # Top-level
    for k in forbidden:
        if k in entry:
            raise AssertionError("forbidden key at top level: " + k)
    # Each learning record
    for lrn in entry.get("learnings", []):
        for k in forbidden:
            if k in lrn:
                raise AssertionError("forbidden key in learning: " + k)
        # Verify source_id and target_id are integers (entity ids, not names)
        if not isinstance(lrn.get("source_id"), int):
            raise AssertionError("source_id must be an int (entity id), not a name")
        if not isinstance(lrn.get("target_id"), int):
            raise AssertionError("target_id must be an int (entity id), not a name")
        # type must be one of the known learning types
        if lrn.get("type") not in (
            "learned_from", "superseded_by", "informed_by", "built_on",
        ):
            raise AssertionError("unknown learning type: " + repr(lrn.get("type")))
    # by_type must be a flat dict[str, int]
    by_type = entry.get("by_type", {})
    for k, v in by_type.items():
        if not isinstance(v, int):
            raise AssertionError("by_type values must be ints: " + repr(v))
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
    `entry`; the local count is echoed as `total_learnings`.

    Matches the contract of `adjustment_exporter.run` so the wrapper script
    `clawforge_export_run.py` can call it generically.
    """
    from clawforge.instance_id import get_instance_id  # type: ignore

    instance_id = get_instance_id()
    entry = export_dojo_learnings(instance_id, days=days)
    assert_anonymized(entry)

    result = await run_legs("dojo", entry, share=share)
    result["total_learnings"] = entry["total_learnings"]
    log.info(
        "dojo.learning.submitted: %d learnings, by_type=%s (local=%s, federation=%s)",
        entry["total_learnings"],
        entry["by_type"],
        result["published_local"],
        result["published_remote"],
    )
    return result


if __name__ == "__main__":
    # Self-test: build the entry, print it, assert anonymization.
    from clawforge.instance_id import get_instance_id  # type: ignore

    inst = get_instance_id()
    entry = export_dojo_learnings(inst, days=30)
    assert_anonymized(entry)
    print(json.dumps(entry, indent=2))
    print("---")
    print(
        "self-test OK: instance_id=" + inst
        + ", learnings=" + str(entry["total_learnings"])
        + ", by_type=" + json.dumps(entry["by_type"])
    )

    # If --publish flag passed, actually publish
    if "--publish" in sys.argv:
        asyncio.run(run(days=30))
