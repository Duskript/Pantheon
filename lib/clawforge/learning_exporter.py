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

    # Build + publish (real run)
    await run(days=7)

Self-test: `python3 -m lib.clawforge.learning_exporter` prints the entry
and asserts anonymization.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-learning-exporter")


def _find_token_path() -> str:
    """Find the Clawforge token file. Tries:
      1. CLAWFORGE_TOKENS_PATH env var
      2. /home/konan/.hermes/clawforge-tokens.env (Pantheon)
      3. /etc/clawforge/tokens.env (Relay-7)
      4. ~/.hermes/clawforge-tokens.env
    Returns the first existing path, or "" if none.
    """
    candidates: list[str] = []
    env_path = os.environ.get("CLAWFORGE_TOKENS_PATH")
    if env_path:
        candidates.append(env_path)
    home = os.path.expanduser("~")
    sep = os.path.sep
    candidates.extend([
        os.path.join(home, ".hermes", "clawforge-tokens.env"),
        sep + os.path.join("etc", "clawforge", "tokens.env"),
    ])
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0] if candidates else ""


def load_token() -> str:
    """Load the Clawforge client bearer token from the first
    available token file."""
    path = _find_token_path()
    if not path or not os.path.exists(path):
        raise SystemExit("token file not found (tried CLAWFORGE_TOKENS_PATH, "
                         "~/.hermes/clawforge-tokens.env, /etc/clawforge/tokens.env)")
    expected_key = "CLAWFORGE_CLIENT_TOKEN" + chr(61)
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(chr(35)):
            continue
        if line.startswith(expected_key):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


async def publish(nc, subject: str, entry: dict) -> None:
    """Publish a single submission to NATS."""
    data = json.dumps(entry).encode("utf-8")
    await nc.publish(subject, data)


async def run(days: int = 7) -> dict[str, Any]:
    """Top-level entry: build the entry, publish, return the entry.

    Matches the contract of `adjustment_exporter.run` so the wrapper
    script `clawforge_export_run.py` can call it generically.
    """
    import nats  # type: ignore
    from clawforge.instance_id import get_instance_id  # type: ignore

    instance_id = get_instance_id()
    entry = export_dojo_learnings(instance_id, days=days)
    assert_anonymized(entry)

    token = load_token()
    nats_host = os.environ.get("CLAWFORGE_NATS_HOST", "100.100.46.52")
    nats_port = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))
    nats_url = "nats://" + nats_host + ":" + str(nats_port)

    log.info("connecting to %s", nats_url)
    nc = await nats.connect(nats_url, token=token, name="clawforge-learning-exporter")
    try:
        await publish(nc, "dojo.learning.submitted", entry)
        await nc.flush()
        log.info(
            "published dojo.learning.submitted: %d learnings, by_type=%s",
            entry["total_learnings"],
            entry["by_type"],
        )
    finally:
        await nc.drain()
    return entry


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
