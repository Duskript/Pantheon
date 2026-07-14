#!/usr/bin/env python3
"""Pantheon session-start inbox gate.

The session-start hook for every god. Before a god session begins
work, this script:

  1. Reads the pending notification file at
     ~/.local/share/pantheon/inbox_notify/<god>.json (if any).
     This is written by the inbox-notifier daemon when a new
     msg_*.json lands while the god was asleep.

  2. Counts ACTIONABLE unread messages in the inbox dir
     (~pantheon/gods/messages/<god>/msg_*.json with read=False).
     subconscious_* and other trace files are not actionable.

  3. Decides whether to BLOCK the session:
     - If any msg_* is high-priority OR > 24h old, the session
       is BLOCKED. The god MUST acknowledge each blocking message
       before continuing.
     - For Hermes (Konan's direct interface), any unread msg_*
       blocks because Konan's time is the most valuable resource.

  4. If not blocking, prints a summary and returns 0 (proceed).

Why this exists:
    Konan's persistent complaint: "messages pile up and nobody
    reads them." This gate is the enforcement. Even a sleeping
    god session, when it wakes, must look at its mail first.

Usage:
    python3 -m scripts.inbox-gate <god_name>
    python3 -m scripts.inbox-gate hermes --json   # for tooling
    python3 -m scripts.inbox-gate hermes --no-block   # for testing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Make lib importable regardless of cwd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

NOTIFY_DIR = Path(os.path.expanduser("~/.local/share/pantheon/inbox_notify"))
HIGH_PRIORITY_GODS = {"hermes"}  # any unread msg_* blocks
SECONDS_24H = 24 * 3600


def now() -> float:
    return time.time()


def parse_ts(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def get_actionable_messages(god: str):
    """Return list of (filename, data, age_seconds) for unread msg_*.
    subconscious_* and other prefixes are NOT counted as actionable.
    """
    inbox_dir = Path(os.path.expanduser(f"~/pantheon/gods/messages/{god}"))
    if not inbox_dir.exists():
        return [], None
    msgs = []
    high_pri_count = 0
    for f in sorted(inbox_dir.glob("msg_*.json")):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if d.get("read", False):
            continue
        ts = parse_ts(d.get("timestamp", ""))
        age = now() - ts if ts else 0
        if d.get("priority") == "high":
            high_pri_count += 1
        msgs.append((f, d, age))
    return msgs, high_pri_count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("god_name")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument(
        "--no-block",
        action="store_true",
        help="Don't block, just report (for testing)",
    )
    args = parser.parse_args()

    god = args.god_name
    msgs, high_count = get_actionable_messages(god)

    notif_path = NOTIFY_DIR / f"{god}.json"
    notif = None
    if notif_path.exists():
        try:
            notif = json.loads(notif_path.read_text())
        except Exception:
            notif = None

    blocking_reasons = []
    high_msgs = [m for m in msgs if m[1].get("priority") == "high"]
    stale_msgs = [m for m in msgs if m[2] > SECONDS_24H]

    if god in HIGH_PRIORITY_GODS and len(msgs) > 0:
        blocking_reasons.append(
            f"Hermes-inbox-policy: {len(msgs)} unread msg_* block"
        )
    if high_msgs:
        blocking_reasons.append(
            f"{len(high_msgs)} high-priority msg_* unread"
        )
    if stale_msgs:
        blocking_reasons.append(
            f"{len(stale_msgs)} stale msg_* > 24h unread"
        )

    should_block = bool(blocking_reasons) and not args.no_block

    out = {
        "god": god,
        "unread_msg_count": len(msgs),
        "high_priority_count": len(high_msgs),
        "stale_count": len(stale_msgs),
        "blocking_reasons": blocking_reasons,
        "should_block": should_block,
        "pending_notification": notif,
    }

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    inbox_dir = Path(os.path.expanduser(f"~/pantheon/gods/messages/{god}"))
    print(f"=== {god.upper()} INBOX GATE ===")
    print(f"  Inbox: {inbox_dir}")
    print(f"  Actionable unread: {len(msgs)} msg_*")
    if notif:
        print(f"  Pending notification: {notif.get('subject', '?')[:70]}")
        print(f"    from: {notif.get('from')}  priority: {notif.get('priority')}")
    if high_msgs:
        print(f"  HIGH-PRIORITY ({len(high_msgs)}):")
        for f, d, age in high_msgs[:5]:
            age_str = f"{age/3600:.1f}h" if age else "?"
            print(
                f"    [{age_str:>8}] {d.get('from', '?'):20} "
                f"{d.get('subject', '?')[:60]}"
            )
    if stale_msgs:
        print(f"  STALE > 24h ({len(stale_msgs)}):")
        for f, d, age in stale_msgs[:5]:
            age_str = f"{age/86400:.1f}d" if age else "?"
            print(
                f"    [{age_str:>8}] {d.get('from', '?'):20} "
                f"{d.get('subject', '?')[:60]}"
            )

    if should_block:
        print()
        print("  WARNING: SESSION BLOCKED — you must acknowledge these messages before proceeding.")
        print("  Use messaging_check_inbox() to read, then mark as read.")
        return 2

    if len(msgs) > 0:
        print()
        print("  (non-blocking — you have mail but it can wait)")
        return 0
    print("  (clean — no unread msg_*)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
