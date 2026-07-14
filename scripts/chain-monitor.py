#!/usr/bin/env python3
"""Kanban chain monitor — polls task state, notifies operator on changes.

Watches specific project prefixes (uce-v0.3, conductor-ui) and sends
Telegram notifications when tasks change status (running→done,
todo→running, →blocked, →failed).

Usage: python3 chain-monitor.py
Runs continuously, polls every 120s.
"""

import subprocess
import json
import time
import os
import sys
from datetime import datetime

PROJECTS = ["uce-v0.3", "conductor-ui"]
POLL_SECONDS = 120
NOTIFY_SCRIPT = os.path.expanduser("~/.local/bin/god-notify")

# Track last-seen state per task: {task_id: {"status": ..., "title": ...}}
last_state: dict[str, dict] = {}


def get_kanban_state() -> dict[str, dict]:
    """Get current kanban state for monitored projects as {task_id: {status, title, assignee}}."""
    try:
        result = subprocess.run(
            ["hermes", "kanban", "list", "--json"],
            capture_output=True, text=True, timeout=30
        )
        tasks = json.loads(result.stdout) if result.stdout.strip() else []
    except Exception as e:
        print(f"[{datetime.now()}] Error fetching kanban: {e}", file=sys.stderr)
        return {}

    state = {}
    for t in tasks:
        title = t.get("title", "")
        for prefix in PROJECTS:
            if f"[{prefix}]" in title:
                state[t["id"]] = {
                    "status": t.get("status", "unknown"),
                    "title": title,
                    "assignee": t.get("assignee", "?"),
                    "project": prefix,
                }
                break
    return state


def notify(title: str, body: str):
    """Send notification to operator via god-notify."""
    try:
        subprocess.run(
            [NOTIFY_SCRIPT, "Hephaestus", "info", title, body],
            capture_output=True, timeout=10
        )
    except Exception as e:
        print(f"[{datetime.now()}] Notify failed: {e}", file=sys.stderr)


def status_icon(status: str) -> str:
    icons = {
        "done": "✅", "running": "▶", "todo": "◻", "ready": "▶",
        "blocked": "⊘", "failed": "❌", "cancelled": "✗"
    }
    return icons.get(status, "?")


def main():
    global last_state

    print(f"[{datetime.now()}] Chain monitor started. Watching: {PROJECTS}. Poll: {POLL_SECONDS}s")
    print(f"[{datetime.now()}] Initial snapshot...")

    # Initial snapshot — don't notify, just seed state
    last_state = get_kanban_state()
    print(f"[{datetime.now()}] Seeded {len(last_state)} tasks.")

    while True:
        time.sleep(POLL_SECONDS)
        current = get_kanban_state()

        for tid, cur in current.items():
            prev = last_state.get(tid)
            if prev is None:
                # New task appeared
                last_state[tid] = cur
                notify(
                    f"{cur['project']}: New task",
                    f"{status_icon(cur['status'])} {cur['title']} → {cur['assignee']} ({cur['status']})"
                )
            elif prev["status"] != cur["status"]:
                # Status change
                old_icon = status_icon(prev["status"])
                new_icon = status_icon(cur["status"])
                notify(
                    f"{cur['project']}: {prev['status']} → {cur['status']}",
                    f"{old_icon}→{new_icon} {cur['title']}\nAssignee: {cur['assignee']}"
                )
                last_state[tid] = cur
            else:
                last_state[tid] = cur  # Update in case title/assignee changed

        # Detect tasks that disappeared (completed/archived)
        gone = set(last_state.keys()) - set(current.keys())
        for tid in gone:
            prev = last_state[tid]
            notify(
                f"{prev['project']}: Task gone",
                f"🎯 {prev['title']} — removed from board (archived?)"
            )
        for tid in gone:
            del last_state[tid]


if __name__ == "__main__":
    main()
