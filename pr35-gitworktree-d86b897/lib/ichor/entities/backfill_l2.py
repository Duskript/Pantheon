#!/usr/bin/env python3
"""L2 backfill runner.

Loops `lib.ichor.entities.l2_llm.extract_incremental()` over all
cold_events past a starting point, storing LLM-extracted entities and
relationships (including `learned_from` and `superseded_by`).

This is the B3 deliverable. The runner is a thin orchestrator — all
the heavy lifting lives in `extract_incremental()` and
`_store_extraction()`. We just need a loop that knows when to stop
(no more events past `last_event_id`) and a way to skip a rate-
limited or transient LLM failure (continue to next batch).

## Why a separate script?

`extract_incremental()` is one batch. The L2 design assumes the caller
tracks `last_event_id` across passes (it's a cursor). For a one-shot
backfill, we start at 0 and let the loop walk to the end.

## Usage

    python3 -m lib.ichor.entities.backfill_l2 \
        --batch-size 50 \
        --provider-config /etc/clawforge/llm.yaml

## Cost

~500 tokens per pass (per the build list). With batch_size=50 and
~7000 cold_events on Pantheon, that's ~140 passes = ~70K tokens.
At $3/MTok, that's ~$0.21 per full backfill.

## B3 scope

This script only RUNS the backfill. The LLM prompt updates for
`learned_from` and `superseded_by` are in `l2_llm.py` (B2). The
canonical type seeds for both are in `relationship_type_seeds.py`
(B1). This runner is the third leg: a loop that exercises all three.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

import sqlite3

from lib.ichor.entities.schema import DB_PATH, get_conn
from lib.ichor.entities.l2_llm import extract_incremental

logger = logging.getLogger("ichor.entities.backfill_l2")


def _load_provider_cfg(path: str | None) -> dict[str, Any]:
    """Load LLM provider config from JSON. Defaults to a no-op stub
    suitable for tests (call_fn injected by the caller)."""
    if path is None:
        return {"provider": "stub", "model": "stub"}
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"provider config not found: {path}")
    return json.loads(p.read_text())


def run(
    db_path: str | Path | None = None,
    *,
    batch_size: int = 50,
    starting_event_id: int = 0,
    max_passes: int = 10_000,
    sleep_between_passes: float = 0.0,
    provider_cfg: dict[str, Any] | None = None,
    call_fn=None,
    session_id: str = "backfill_l2",
) -> dict[str, Any]:
    """Run the L2 backfill loop to completion.

    Stops when either:
      - `extract_incremental` reports no more events past last_event_id, OR
      - `max_passes` is reached (safety cap for test runs).

    Returns aggregated counts and timing.
    """
    conn = get_conn(db_path)
    owns_conn = db_path is not None  # get_conn opened if path given
    if provider_cfg is None:
        provider_cfg = _load_provider_cfg(None)

    last_event_id = starting_event_id
    pass_count = 0
    total_entities = 0
    total_relationships = 0
    total_relationship_types_created = 0
    started = time.time()

    try:
        while pass_count < max_passes:
            result = extract_incremental(
                conn,
                last_event_id=last_event_id,
                batch_size=batch_size,
                provider_cfg=provider_cfg,
                call_fn=call_fn,
                session_id=session_id,
            )
            pass_count += 1
            stored = result.get("stored", {})
            total_entities += stored.get("entities_created", 0)
            total_relationships += stored.get("relationships_created", 0)
            total_relationship_types_created += stored.get("rel_types_created", 0)

            if result.get("events_in_batch", 0) == 0:
                logger.info("no more events past last_event_id=%s; backfill done", last_event_id)
                break

            new_last = result["last_event_id_after"]
            if new_last == last_event_id:
                # Defensive: extract_incremental returned events but didn't
                # advance. Shouldn't happen but stop the loop if it does.
                logger.warning("last_event_id didn't advance (was=%s, now=%s); stopping", last_event_id, new_last)
                break
            last_event_id = new_last

            if pass_count % 10 == 0:
                logger.info(
                    "pass %d done: last_event_id=%s, +entities=%d, +relationships=%d",
                    pass_count, last_event_id, total_entities, total_relationships,
                )

            if sleep_between_passes > 0:
                time.sleep(sleep_between_passes)
    finally:
        if owns_conn:
            conn.close()

    elapsed = time.time() - started
    return {
        "passes": pass_count,
        "last_event_id": last_event_id,
        "total_entities_created": total_entities,
        "total_relationships_created": total_relationships,
        "total_relationship_types_created": total_relationship_types_created,
        "elapsed_seconds": round(elapsed, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the L2 backfill to completion.")
    parser.add_argument("--db", default=str(DB_PATH), help=f"Path to ichor.db (default: {DB_PATH})")
    parser.add_argument("--batch-size", type=int, default=50, help="Events per LLM pass (default 50)")
    parser.add_argument("--starting-event-id", type=int, default=0, help="Start cursor (default 0 = from beginning)")
    parser.add_argument("--max-passes", type=int, default=10_000, help="Safety cap (default 10000)")
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between passes (default 0)")
    parser.add_argument("--provider-config", default=None, help="Path to LLM provider config JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    provider_cfg = _load_provider_cfg(args.provider_config)
    result = run(
        db_path=args.db,
        batch_size=args.batch_size,
        starting_event_id=args.starting_event_id,
        max_passes=args.max_passes,
        sleep_between_passes=args.sleep,
        provider_cfg=provider_cfg,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
