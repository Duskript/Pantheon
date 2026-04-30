#!/usr/bin/env python3
"""Pantheon Bridge: Check Hermes' inbox for unread messages and auto-ack them."""

import json
import os
import glob

HERMES_INBOX = os.path.expanduser("~/pantheon/gods/messages/hermes")

def check_and_ack():
    """Find all unread messages, report them, then mark them read."""
    if not os.path.isdir(HERMES_INBOX):
        print("NO_INBOX")
        return

    messages = []
    for msg_file in sorted(glob.glob(os.path.join(HERMES_INBOX, "msg_*.json"))):
        try:
            with open(msg_file) as f:
                msg = json.load(f)
            if not msg.get("read", False):
                messages.append((msg_file, msg))
        except (json.JSONDecodeError, IOError):
            continue

    if not messages:
        print("NO_NEW")
        return

    # Output report AND mark each as read
    count = len(messages)
    print(f"NEW:{count}")

    for msg_file, msg in messages:
        from_god = msg.get("from", "unknown")
        subject = msg.get("subject", "No subject")
        priority = msg.get("priority", "normal")
        body = msg.get("body", "")
        msg_id = msg.get("id", "unknown")

        preview = body[:300] + ("..." if len(body) > 300 else "")
        print(f"MSG:{msg_id}|from:{from_god}|priority:{priority}|subject:{subject}")
        print(f"BODY:{preview}")

        # Mark as read
        msg["read"] = True
        with open(msg_file, "w") as f:
            json.dump(msg, f, indent=2, default=str)

    print("ACKED:true")

if __name__ == "__main__":
    check_and_ack()
