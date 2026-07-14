"""One-shot backfill of event_embeddings for existing ichor_events.

Reads events in batches of 64, embeds with BGE-small, bulk-upserts to
event_embeddings. Resumable: progress is checkpointed after every batch.
Logs to ~/.hermes/log/embed-backfill.log. Idempotent (INSERT OR REPLACE).

Spike projection (Beelink i3-5005U, BGE-small):
    Throughput: 12-14 texts/sec at ~150 tokens
    ~109K events → ~2.2-2.4 hours
    Storage: ~166 MB total

Usage:
    python3 scripts/backfill-embeddings.py            # run
    python3 scripts/backfill-embeddings.py --dry-run  # count, no writes
    python3 scripts/backfill-embeddings.py --status   # print progress

State file: ~/.hermes/state/embed-backfill.json
Log file:   ~/.hermes/log/embed-backfill.log

P5a (2026-06-20, ichor-semantic-search-recovery): replaces the
deprecated scripts/embed-fast.py and the ad-hoc ChromaDB-era
embedding scripts. Idempotent — re-running over already-embedded
events is a no-op (INSERT OR REPLACE).
"""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from pathlib import Path

# Ensure ~/pantheon is on sys.path so we can import lib.ichor.*
_PANTHEON_ROOT = Path.home() / "pantheon"
if str(_PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PANTHEON_ROOT))

# Paths
_HOME = Path.home()
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_STATE = _HOME / ".hermes" / "state" / "embed-backfill.json"
_LOG_FILE = _HOME / ".hermes" / "log" / "embed-backfill.log"

# Config
BATCH_SIZE = 64
MIN_TEXT_LEN = 50  # skip tiny events (matches spike query threshold)

# Ensure log/state dirs exist before logging.basicConfig opens the file
_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
_STATE.parent.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(_LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("embed-backfill")


def load_state() -> dict:
    """Load checkpoint from disk. Returns fresh state if no file."""
    if _STATE.exists():
        return json.loads(_STATE.read_text())
    return {"last_event_id": 0, "embedded_count": 0}


def save_state(state: dict) -> None:
    """Persist checkpoint atomically (write to tmp, rename)."""
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(_STATE)


def iter_events(db: sqlite3.Connection, after_id: int, batch: int):
    """Yield (event_id, raw_text) batches in id order, skipping tiny events."""
    cur = db.execute(
        """
        SELECT id, raw_text FROM ichor_events
        WHERE id > ? AND raw_text IS NOT NULL AND length(raw_text) > ?
        ORDER BY id ASC
        LIMIT ?
        """,
        (after_id, MIN_TEXT_LEN, batch),
    )
    return cur.fetchall()


def run(dry_run: bool = False) -> int:
    """Embed all qualifying ichor_events. Resumable via state file."""
    from lib.ichor.embedder import embed
    from lib.ichor.vector_backend import VectorBackend

    db = sqlite3.connect(str(_ICHOR_DB))
    db.row_factory = sqlite3.Row
    state = load_state()
    log.info(
        "Starting at event_id=%d (already embedded: %d)",
        state["last_event_id"], state["embedded_count"],
    )

    if dry_run:
        total = db.execute(
            "SELECT COUNT(*) FROM ichor_events "
            "WHERE raw_text IS NOT NULL AND length(raw_text) > ?",
            (MIN_TEXT_LEN,),
        ).fetchone()[0]
        log.info("DRY RUN: %d events to embed", total)
        return 0

    backend = VectorBackend()
    t_total = time.time()
    while True:
        rows = iter_events(db, state["last_event_id"], BATCH_SIZE)
        if not rows:
            break
        texts = [r["raw_text"] for r in rows]
        eids = [r["id"] for r in rows]
        vectors = embed(texts)
        if not vectors or len(vectors) != len(eids):
            log.warning(
                "Embedder returned %d/%d — skipping batch (will retry next run)",
                len(vectors), len(eids),
            )
            # Advance past this batch to avoid infinite loop; will re-embed on resume
            state["last_event_id"] = eids[-1]
            save_state(state)
            continue
        # Build (event_id, vector) pairs, skipping any wrong-dim
        items = [
            (eid, vec) for eid, vec in zip(eids, vectors)
            if len(vec) == 384
        ]
        backend.upsert_batch(items)
        state["last_event_id"] = eids[-1]
        state["embedded_count"] += len(items)
        save_state(state)
        elapsed = time.time() - t_total
        rate = state["embedded_count"] / elapsed if elapsed > 0 else 0
        log.info(
            "Embedded %d events (%.1f/sec) — last_id=%d",
            state["embedded_count"], rate, state["last_event_id"],
        )

    log.info(
        "DONE: %d events embedded in %.1f minutes",
        state["embedded_count"], (time.time() - t_total) / 60,
    )
    return 0


def print_status() -> int:
    """Show progress: total, embedded, remaining."""
    state = load_state()
    db = sqlite3.connect(str(_ICHOR_DB))
    total = db.execute(
        "SELECT COUNT(*) FROM ichor_events "
        "WHERE raw_text IS NOT NULL AND length(raw_text) > ?",
        (MIN_TEXT_LEN,),
    ).fetchone()[0]
    remaining = max(0, total - state["embedded_count"])
    print(f"Total events:       {total}")
    print(f"Already embedded:   {state['embedded_count']}")
    print(f"Remaining:          {remaining}")
    print(f"Last processed id:  {state['last_event_id']}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    if args.status:
        sys.exit(print_status())
    sys.exit(run(dry_run=args.dry_run))