#!/usr/bin/env python3
"""Outcome backfill for retrieval-log entries.

The retrieval log (`~/.hermes/pantheon/retrieval-log.jsonl`) accumulates
~100 entries per day. Each entry is logged at retrieval time with
`outcome: "pending"`. The original design assumed a follow-up hook
would resolve each entry to `"used"` or `"irrelevant"` once the user
reacted to the results. That hook was never wired.

This script (B4 in the Pass 3.1 cleanup) does the next-best thing:
mark all entries older than `grace_hours` with `outcome: "pending"`
as `outcome: "unknown"`. They stay in the log (audit trail) but no
longer count as `pending` for the Outcome API.

The Outcome API (`get_recent_outcomes` in clawforge.memory_api) only
returns entries with `outcome != "pending"`. After this backfill:
  - New retrievals still get `outcome: "pending"` until the user
    reacts (or until they're old enough to fall out of grace)
  - After `grace_hours`, they get promoted to `outcome: "unknown"`
    by the daily sweep
  - The Outcome API can now return aggregate counts based on
    `unknown` (the bulk) plus any future `used`/`irrelevant` resolved
    by the user feedback hook (when it's wired)

## Usage

    python3 -m lib.clawforge.outcome_backfill               # default grace=4h
    python3 -m lib.clawforge.outcome_backfill --grace-hours 1 --dry-run

## Why "unknown" instead of deleting the field

We want a literal outcome value that:
  1. Is NOT "pending" (so it surfaces to the Outcome API)
  2. Is clearly NOT a real signal (so it doesn't get used for
     "irrelevant" learning)
  3. Is auditable (the original "pending" was a state, not a verdict)

"unknown" satisfies all three. The Outcome API can then distinguish
"resolved and used" from "resolved and irrelevant" from "ran out the
clock".
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("clawforge.outcome_backfill")

_HOME = Path(os.environ.get("HOME", str(Path.home())))
_DEFAULT_LOG = _HOME / ".hermes" / "pantheon" / "retrieval-log.jsonl"


def _atomic_write_jsonl(path: Path, entries: list[dict[str, Any]]) -> None:
    """Rewrite the JSONL atomically. Same pattern as the other clawforge writers."""
    p_parent = path.parent
    p_name = path.name
    fd, tmp_name = tempfile.mkstemp(
        dir=str(p_parent), prefix="." + p_name + ".", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")))
                f.write("\n")
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def backfill_pending(
    log_path: Path | None = None,
    *,
    grace_hours: float = 4.0,
    new_outcome: str = "unknown",
    dry_run: bool = False,
) -> dict[str, int]:
    """Mark all `outcome: "pending"` entries older than `grace_hours` as
    `new_outcome` (default "unknown"). Returns counts.

    Args:
        log_path: path to retrieval-log.jsonl (default: ~/.hermes/pantheon/retrieval-log.jsonl)
        grace_hours: skip entries with timestamp newer than now - grace_hours
        new_outcome: value to set in place of "pending" (default "unknown")
        dry_run: if True, do not write; just count what would change

    Returns: {scanned, already_resolved, pending_within_grace, promoted, malformed}
    """
    if log_path is None:
        log_path = _DEFAULT_LOG
    if not log_path.exists():
        logger.warning("retrieval log not found: %s", log_path)
        return {"scanned": 0, "already_resolved": 0, "pending_within_grace": 0,
                "promoted": 0, "malformed": 0}

    cutoff = time.time() - (grace_hours * 3600.0)
    entries: list[dict[str, Any]] = []
    counts = {"scanned": 0, "already_resolved": 0, "pending_within_grace": 0,
              "promoted": 0, "malformed": 0}

    with open(log_path, errors="replace") as f:
        for line in f:
            if not line.strip():
                continue
            counts["scanned"] += 1
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                counts["malformed"] += 1
                entries.append({"__raw_invalid__": line.strip()})
                continue
            ts = entry.get("timestamp", 0)
            outcome = entry.get("outcome", "pending")
            if outcome == "pending" and ts < cutoff:
                # Promote
                entry["outcome"] = new_outcome
                entry["_promoted_at"] = time.time()
                entry["_promoted_from"] = "pending"
                counts["promoted"] += 1
            elif outcome == "pending":
                counts["pending_within_grace"] += 1
            else:
                counts["already_resolved"] += 1
            entries.append(entry)

    if not dry_run and counts["promoted"] > 0:
        _atomic_write_jsonl(log_path, entries)
        logger.info("wrote %d entries to %s (promoted=%d)",
                    len(entries), log_path, counts["promoted"])
    elif dry_run and counts["promoted"] > 0:
        logger.info("[dry-run] would promote %d entries", counts["promoted"])

    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill retrieval-log pending outcomes.")
    parser.add_argument("--log", default=str(_DEFAULT_LOG), help="Path to retrieval-log.jsonl")
    parser.add_argument("--grace-hours", type=float, default=4.0,
                        help="Skip entries newer than this (default 4h)")
    parser.add_argument("--new-outcome", default="unknown",
                        help="Value to replace 'pending' with (default 'unknown')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count but don't write")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    counts = backfill_pending(
        Path(args.log),
        grace_hours=args.grace_hours,
        new_outcome=args.new_outcome,
        dry_run=args.dry_run,
    )
    print(json.dumps({"status": "ok", "counts": counts, "dry_run": args.dry_run}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
