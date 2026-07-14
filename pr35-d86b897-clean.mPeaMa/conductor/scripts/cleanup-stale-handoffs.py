#!/usr/bin/env python3
"""Conductor inbox cleanup — quarantine or delete stale handoff files.

Runs every 15 minutes via cron. For each pending/ subdirectory:
  - Skip protected inboxes (_quarantine, _webhooks)
  - If file is older than max_age_minutes (default 60):
      - If source matches quarantine_match.sources: move to _quarantine/
      - Otherwise: delete

Idempotent. Exits 0 always — no pending handoffs is not an error.

Cron entry:
  */15 * * * * /usr/bin/env python3 /home/konan/pantheon/conductor/scripts/cleanup-stale-handoffs.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

PENDING_DIR = Path(os.environ.get("CONDUCTOR_PENDING_DIR", "/home/konan/pantheon/conductor/pending"))
MAX_AGE_MIN = int(os.environ.get("CONDUCTOR_CLEANUP_MAX_AGE", "60"))
PROTECTED = {"_quarantine", "_webhooks"}
QUARANTINE_SOURCES = {"smoke-test", "test-source", "github"}


def age_minutes(path: Path) -> float:
    return (time.time() - path.stat().st_mtime) / 60.0


def source_of(path: Path) -> str:
    """Read the 'source' field from a handoff JSON, best effort."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    # Schema varies: handoffs use 'source', events use 'source' too
    return str(data.get("source", "")).strip()


def main() -> int:
    if not PENDING_DIR.is_dir():
        print(f"pending dir not found: {PENDING_DIR}", file=sys.stderr)
        return 0

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    stats = {"scanned": 0, "stale": 0, "quarantined": 0, "deleted": 0}

    for inbox in PENDING_DIR.iterdir():
        if not inbox.is_dir():
            continue
        if inbox.name in PROTECTED:
            continue
        for handoff in inbox.glob("*.json"):
            stats["scanned"] += 1
            try:
                age = age_minutes(handoff)
            except FileNotFoundError:
                continue
            if age < MAX_AGE_MIN:
                continue
            stats["stale"] += 1
            src = source_of(handoff)
            if src in QUARANTINE_SOURCES:
                target = PENDING_DIR / "_quarantine" / handoff.name
                try:
                    shutil.move(str(handoff), str(target))
                    stats["quarantined"] += 1
                except Exception as e:
                    print(f"  ! failed to quarantine {handoff}: {e}", file=sys.stderr)
            else:
                try:
                    handoff.unlink()
                    stats["deleted"] += 1
                except Exception as e:
                    print(f"  ! failed to delete {handoff}: {e}", file=sys.stderr)

    if stats["stale"]:
        print(f"[{now}] cleanup: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
