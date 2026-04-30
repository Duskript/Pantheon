#!/usr/bin/env python3
"""Pantheon Bridge: Check Hermes' inbox for unread messages and report them."""

import json
import os
import glob
from datetime import datetime, timezone

HERMES_INBOX = os.path.expanduser("~/pantheon/gods/messages/hermes")
INBOX_INDEX = os.path.join(HERMES_INBOX, "hermes-inbox.json")

def check_inbox():
    """Find all unread messages in Hermes' inbox."""
    if not os.path.isdir(HERMES_INBOX):
        return []

    messages = []
    for msg_file in sorted(glob.glob(os.path.join(HERMES_INBOX, "msg_*.json"))):
        try:
            with open(msg_file) as f:
                msg = json.load(f)
            if not msg.get("read", False):
                messages.append(msg)
        except (json.JSONDecodeError, IOError):
            continue

    return messages

def main():
    messages = check_inbox()

    if not messages:
        print("No new messages.")
        return

    count = len(messages)
    print(f"📬 {count} new message(s) in Hermes' inbox!")
    print()

    for msg in messages:
        from_god = msg.get("from", "unknown")
        subject = msg.get("subject", "No subject")
        priority = msg.get("priority", "normal")
        body = msg.get("body", "")
        ts = msg.get("timestamp", "")

        priority_icon = {"high": "🔴", "normal": "🟢", "low": "🔵"}.get(priority, "🟢")

        print(f"{priority_icon} From: {from_god}")
        print(f"   Subject: {subject}")
        print(f"   Time: {ts}")
        # Show first 200 chars of body as preview
        preview = body[:200] + ("..." if len(body) > 200 else "")
        print(f"   Preview: {preview}")
        print()

    print(f"Check 'cat ~/pantheon/gods/messages/hermes/' to read them in full.")

if __name__ == "__main__":
    main()
