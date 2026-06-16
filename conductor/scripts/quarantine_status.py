#!/usr/bin/env python3
"""Conductor quarantine status — read-only snapshot for the morning brief.

Counts files in ``pending/_quarantine/`` (NATS messages with no matching rule)
and ``pending/_webhooks/`` (webhooks with no matching rule). Surfaces the
backlog size, oldest age, and top-5 oldest entries so the dawn-patrol can
auto-emit a backlog section without shelling out to ``ls | wc -l``.

This is the BACKSTOP for the ``pantheon-quarantine-sweeper`` — if the
sweeper is down at 7am, the brief still detects the pile-up. It does NOT
deliver Telegram alerts (that's the sweeper's job).

Exit codes (per Phase 4 spec):
  0  both quarantine dirs are empty (or missing — handled gracefully)
  1  at least one of the two dirs has files

Output: a single JSON object on stdout, machine-readable by default::

    {
      "count": <int>,                  # total files across both dirs
      "oldest_age_seconds": <int|0>,   # age of the OLDEST file (not the average)
      "items": [                       # top 5 oldest, all from both dirs combined
        {"filename": "...", "mtime": <unix>, "size_bytes": <int>},
        ...
      ]
    }

Flags:
  --quarantine-dir PATH   override quarantine dir (default: production)
  --webhooks-dir PATH     override webhooks dir   (default: production)
  --json true|false       default true; set false for a human summary

The helper is stdlib-only and safe to run in any environment, even on a
fresh checkout where ``pending/_quarantine/`` does not exist yet.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

DEFAULT_PENDING = Path("/home/konan/pantheon/conductor/pending")
DEFAULT_QUARANTINE = DEFAULT_PENDING / "_quarantine"
DEFAULT_WEBHOOKS = DEFAULT_PENDING / "_webhooks"


def _scan_dir(d: Path) -> tuple[list[dict], int]:
    """Scan a single quarantine dir. Returns (items, total_count).

    Items: list of {filename, mtime, size_bytes} dicts. Each file contributes
    exactly one entry. Missing or unreadable dirs return ([], 0) and log to
    stderr — never raise.
    """
    if not d.exists():
        return [], 0
    if not d.is_dir():
        print(f"quarantine_status: not a directory: {d}", file=sys.stderr)
        return [], 0
    items: list[dict] = []
    try:
        for entry in d.iterdir():
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except (PermissionError, OSError) as e:
                print(f"quarantine_status: stat failed for {entry}: {e}", file=sys.stderr)
                continue
            items.append({
                "filename": entry.name,
                "mtime": stat.st_mtime,
                "size_bytes": stat.st_size,
            })
    except (PermissionError, OSError) as e:
        print(f"quarantine_status: listdir failed for {d}: {e}", file=sys.stderr)
        return [], 0
    return items, len(items)


def collect(
    quarantine_dir: Path = DEFAULT_QUARANTINE,
    webhooks_dir: Path = DEFAULT_WEBHOOKS,
    *,
    top: int = 5,
) -> dict:
    """Aggregate both quarantine dirs into the spec's JSON shape.

    Items from both dirs are merged, sorted oldest-first, and the top ``top``
    entries are returned. ``oldest_age_seconds`` is the age of the oldest
    file in EITHER dir, or 0 if both are empty.
    """
    q_items, _ = _scan_dir(quarantine_dir)
    w_items, _ = _scan_dir(webhooks_dir)

    merged = q_items + w_items
    # Oldest first → smaller mtime first
    merged.sort(key=lambda x: x["mtime"])

    if merged:
        oldest_mtime = merged[0]["mtime"]
        oldest_age = int(time.time() - oldest_mtime)
        # Defense in depth: clock skew / future mtimes shouldn't go negative
        if oldest_age < 0:
            oldest_age = 0
    else:
        oldest_age = 0

    return {
        "count": len(merged),
        "oldest_age_seconds": oldest_age,
        "items": merged[:top],
    }


def _format_age(seconds: int) -> str:
    """Convert seconds into a compact '2h 13m' / '45s' / '3d 4h' string.

    Used only by the --json=false human-readable path. The JSON path
    carries the raw integer so callers can format however they like.
    """
    if seconds <= 0:
        return "0s"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _format_human(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"Conductor quarantine backlog: {payload['count']} file(s)")
    if payload["count"] == 0:
        return "\n".join(lines)
    lines.append(f"Oldest age: {_format_age(payload['oldest_age_seconds'])}")
    lines.append("")
    lines.append("Top 5 oldest entries:")
    for it in payload["items"]:
        age = _format_age(int(time.time() - it["mtime"]))
        lines.append(
            f"  - {it['filename']}  age={age}  size={it['size_bytes']}B"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Snapshot of the Conductor quarantine backlog.",
    )
    parser.add_argument(
        "--quarantine-dir",
        type=Path,
        default=DEFAULT_QUARANTINE,
        help=f"path to _quarantine/ (default: {DEFAULT_QUARANTINE})",
    )
    parser.add_argument(
        "--webhooks-dir",
        type=Path,
        default=DEFAULT_WEBHOOKS,
        help=f"path to _webhooks/ (default: {DEFAULT_WEBHOOKS})",
    )
    parser.add_argument(
        "--json",
        type=lambda v: v.lower() in ("1", "true", "yes", "y"),
        default=True,
        help="output JSON (default true); set false for human-readable text",
    )
    args = parser.parse_args(argv)

    payload = collect(quarantine_dir=args.quarantine_dir, webhooks_dir=args.webhooks_dir)

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(_format_human(payload))

    # Spec exit code: 0 if empty, 1 if non-empty. Either dir counts.
    return 0 if payload["count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
