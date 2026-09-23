#!/usr/bin/env python3
"""Ichor Ebbinghaus Decay — daily importance decay for memory events.

Applies an Ebbinghaus forgetting-curve multiplier to the `importance`
column of every row in `ichor_events`. Recent events decay faster;
older events (already low) decay asymptotically toward zero without
ever hitting it exactly.

Schedule: daily at 02:30, before eviction at 02:45.

Usage:
    python3 lib/ichor_decay.py                          # dry-run
    python3 lib/ichor_decay.py --apply                  # apply to live DB
    python3 lib/ichor_decay.py --db /tmp/test.db --apply
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("ichor_decay")

DEFAULT_DB = Path.home() / ".hermes" / "ichor.db"
DECAY_FACTOR: float = 0.85  # base daily multiplier
EBBINGHAUS_C: float = 0.50  # curve constant — higher = slower decay

# Don't touch events younger than this (hours).
MIN_AGE_HOURS: float = 1.0

# Floor: importance never drops below this (prevents total annihilation).
IMPORTANCE_FLOOR: float = 0.001


def ebbinghaus_multiplier(days_old: float) -> float:
    """Ebbinghaus forgetting curve multiplier.

    R = C ^ (t / 7)  where C=0.5 means:
      After  7 days: 0.50x
      After 30 days: 0.17x
      After 90 days: 0.04x
    """
    if days_old <= 0:
        return 1.0
    return max(EBBINGHAUS_C ** (days_old / 7.0), 0.001)


def run_decay(
    db_path: str | Path,
    *,
    dry_run: bool = True,
    reference_now: datetime | None = None,
) -> Dict[str, Any]:
    """Apply Ebbinghaus decay to all ichor_events.

    Args:
        db_path: Path to ichor.db.
        dry_run: If True, compute and report but don't write.
        reference_now: Override "now" for deterministic testing.

    Returns:
        Dict with `decayed` (count updated), `skipped` (too recent),
        `sample` (list of {id, old_importance, new_importance, days_old}).
    """
    path = Path(db_path)
    if not path.exists():
        return {"decayed": 0, "skipped": 0, "sample": [], "error": "db not found"}

    now = reference_now or datetime.now(timezone.utc)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            "SELECT id, importance, created_at FROM ichor_events "
            "WHERE importance IS NOT NULL AND importance > 0"
        ).fetchall()
    except sqlite3.OperationalError as exc:
        conn.close()
        return {"decayed": 0, "skipped": 0, "sample": [], "error": str(exc)}

    updates: List[Tuple[float, int]] = []
    skipped: int = 0
    sample: List[Dict[str, Any]] = []

    for row in rows:
        created_str = row["created_at"] or ""
        try:
            created_str = (created_str or "").replace("Z", "+00:00")
            created = datetime.fromisoformat(created_str)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            skipped += 1
            continue

        hours_old = (now - created).total_seconds() / 3600.0
        if hours_old < MIN_AGE_HOURS:
            skipped += 1
            continue

        days_old = hours_old / 24.0
        old_imp = float(row["importance"] or 0)
        multiplier = ebbinghaus_multiplier(days_old)
        new_imp = round(old_imp * multiplier * DECAY_FACTOR, 4)
        new_imp = max(new_imp, IMPORTANCE_FLOOR)

        updates.append((new_imp, row["id"]))

        if len(sample) < 5:
            sample.append({
                "id": row["id"],
                "old_importance": old_imp,
                "new_importance": new_imp,
                "days_old": round(days_old, 1),
                "multiplier": round(multiplier, 3),
            })

    if not dry_run and updates:
        conn.executemany(
            "UPDATE ichor_events SET importance = ? WHERE id = ?", updates
        )
        conn.commit()
        logger.info("Decay applied: %d events updated", len(updates))

    conn.close()
    return {"decayed": len(updates), "skipped": skipped, "sample": sample}


def main() -> None:
    ap = argparse.ArgumentParser(description="Ichor Ebbinghaus Decay")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="Path to ichor.db")
    ap.add_argument("--apply", action="store_true", help="Actually apply (default: dry-run)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    result = run_decay(args.db, dry_run=not args.apply)
    if result.get("error"):
        print(f"ERROR: {result['error']}")
        return

    mode = "APPLIED" if args.apply else "DRY-RUN"
    print(f"{mode}: {result['decayed']} decayed, {result['skipped']} skipped")
    for s in result.get("sample", []):
        print(
            f"  id={s['id']} {s['old_importance']:.4f} → {s['new_importance']:.4f} "
            f"({s['days_old']}d old, ×{s['multiplier']})"
        )


if __name__ == "__main__":
    main()
