"""Canonical inbox statistics for Pantheon gods.

The single source of truth for "how many unread messages does god X have?"
and the breakdown by message type / priority. Designed to be consumed by
any dashboard or UI that needs to show an inbox count.

Bug history (2026-06-19):
    Iris's handoff flagged that the WebUI dashboard unread counter for iris
    was showing 110 — exactly the number of `subconscious_*.json` files in
    her inbox dir — while `messaging_check_inbox(god_name="iris")` correctly
    returned 1 unread (matching the disk truth of 1 unread + 1 unread-with-
    bool-casing). The dashboard counter was counting files without filtering
    on the `read` field, or counting only the subconscious stream while
    ignoring msg_* files and read state.

This module fixes that by being the canonical answer. It implements the
exact same glob-and-filter logic as `mcp_server.py::messaging_check_inbox`
so any caller that uses this utility will agree with the MCP tool's count.

Usage:
    from lib.inbox_stats import inbox_stats
    stats = inbox_stats("iris")
    # {"god_name": "iris", "total": 133, "unread": 2, "msg": 22,
    #  "subconscious": 111, "by_priority": {"high": 0, "normal": 2}}

CLI:
    python3 -m lib.inbox_stats iris                # JSON to stdout
    python3 -m lib.inbox_stats --all               # all gods
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_HOME = Path(os.path.expanduser("~"))
_MESSAGES_DIR = _HOME / "pantheon" / "gods" / "messages"


def _real_home() -> Path:
    """Resolve the actual $HOME, profile-aware (Hermes-proof)."""
    home = Path(os.path.expanduser("~"))
    real = os.environ.get("HERMES_REAL_HOME", str(home))
    if real != str(home) and real != str(home.parent):
        home = Path(real)
    if ".hermes/profiles" in str(home):
        home = Path(str(home).split("/.hermes/profiles/")[0])
    return home


def _is_read(data: dict) -> bool:
    """The canonical read-state check.

    Matches the logic in mcp_server.py::messaging_check_inbox:
    `data.get("read", False)` — but applied carefully so that the JSON
    `false` literal and Python `False` both read as not-read.

    Note: we don't try to be clever about `True` (capital T, Python bool)
    vs `true` (lowercase JSON literal) here — both deserialize to the
    same Python `True` via json.loads. The mcp_server check does the same.
    """
    return bool(data.get("read", False))


def inbox_stats(god_name: str, base_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Return canonical inbox statistics for a god.

    Args:
        god_name: Name of the god (e.g. "iris", "marvin", "hephaestus").
        base_dir: The messages directory. `inbox_stats` will look at
            `<base_dir>/<god_name>`. If None, defaults to
            `~/pantheon/gods/messages` so the god's subdir is appended.

    Returns:
        Dict with: god_name, inbox_dir, total, unread, msg, subconscious,
        by_priority, oldest_unread_timestamp, latest_timestamp. If the
        god's inbox dir doesn't exist, returns zeros with an "exists=false"
        marker rather than raising.
    """
    home = _real_home()
    if base_dir is None:
        # Default: messages root, so we append god_name.
        inbox = home / "pantheon" / "gods" / "messages" / god_name
    elif base_dir.name == god_name:
        # Caller passed the god's full inbox dir already.
        inbox = base_dir
    else:
        # Caller passed the messages root — append god_name.
        inbox = base_dir / god_name

    if not inbox.is_dir():
        return {
            "god_name": god_name,
            "inbox_dir": str(inbox),
            "exists": False,
            "total": 0,
            "unread": 0,
            "msg": 0,
            "subconscious": 0,
            "by_priority": {"high": 0, "normal": 0, "low": 0},
            "oldest_unread_timestamp": None,
            "latest_timestamp": None,
        }

    total = 0
    unread = 0
    msg_count = 0
    sub_count = 0
    by_priority: Dict[str, int] = {"high": 0, "normal": 0, "low": 0}
    oldest_unread_ts: Optional[str] = None
    latest_ts: Optional[str] = None

    for f in inbox.glob("*.json"):
        total += 1
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue

        # Classify file type by name (same convention as mcp_server)
        name = f.name
        if name.startswith("msg_"):
            msg_count += 1
        elif name.startswith("subconscious_"):
            sub_count += 1
        # (other prefixes: future-proof; not counted separately)

        if not _is_read(data):
            unread += 1
            ts = data.get("timestamp")
            if ts and (oldest_unread_ts is None or ts < oldest_unread_ts):
                oldest_unread_ts = ts

        ts = data.get("timestamp")
        if ts and (latest_ts is None or ts > latest_ts):
            latest_ts = ts

        priority = data.get("priority", "normal")
        by_priority[priority] = by_priority.get(priority, 0) + 1

    return {
        "god_name": god_name,
        "inbox_dir": str(inbox),
        "exists": True,
        "total": total,
        "unread": unread,
        "msg": msg_count,
        "subconscious": sub_count,
        "by_priority": by_priority,
        "oldest_unread_timestamp": oldest_unread_ts,
        "latest_timestamp": latest_ts,
    }


def all_inboxes(base_dir: Optional[Path] = None) -> Dict[str, Dict[str, Any]]:
    """Return inbox_stats for every god with an inbox directory.

    Sorted by unread count descending so the most-overloaded gods are
    surfaced first.
    """
    home = _real_home()
    messages_root = base_dir or (home / "pantheon" / "gods" / "messages")
    if not messages_root.is_dir():
        return {}
    result = {}
    for entry in sorted(messages_root.iterdir()):
        if not entry.is_dir():
            continue
        result[entry.name] = inbox_stats(entry.name, base_dir=messages_root)
    # Re-sort by unread desc, then name
    return dict(sorted(result.items(), key=lambda kv: (-kv[1]["unread"], kv[0])))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Pantheon inbox statistics (canonical source of truth for unread counts)"
    )
    parser.add_argument("god_name", nargs="?", help="God name (omit with --all)")
    parser.add_argument("--all", action="store_true", help="All gods")
    parser.add_argument("--json", action="store_true", help="Force JSON output (default)")
    args = parser.parse_args()

    if args.all:
        result = all_inboxes()
    elif args.god_name:
        result = inbox_stats(args.god_name)
    else:
        parser.error("Provide a god name or --all")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
