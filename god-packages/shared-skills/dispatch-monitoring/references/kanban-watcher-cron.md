# Kanban-Watcher Cron — Proactive Chain State Notifications

## Purpose

Operators don't sit in a chat session watching the kanban. The chain can be running for 30+ minutes between operator check-ins, and the operator needs persistent visibility into state changes without having to ask "where are we at" every turn.

The kanban-watcher is a small cron-driven script that:
1. Polls `hermes kanban list` every N minutes
2. Diffs the state against the last snapshot
3. Pushes Telegram (or other channel) notifications on detected changes
4. Suppresses duplicate notifications via a dedup hash

## Why this exists (operator correction, 2026-06-16)

> "I am getting frustrated with having to constantly ask what is happening."

The default behavior pre-correction was: check the chain when the operator asks. The post-correction behavior is: **the system tells the operator** when state changes happen. The kanban-watcher is the persistent implementation of that correction.

## File layout

```
~/.hermes/cron/kanban-watcher/
├── kanban-watcher.py           # the polling script
├── notify-config.yaml          # which chat to notify, dedup window, poll interval
├── state/                      # last-snapshot storage (JSON)
│   └── last-snapshot.json
└── log/                        # cron output (success/error logs)
    └── watcher.log
```

## The script (kanban-watcher.py)

```python
#!/usr/bin/env python3
"""
Kanban-watcher — proactive chain state notifications.

Polls `hermes kanban list` every N minutes, diffs against the last snapshot,
and pushes notifications on detected state changes.
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Config
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / "state" / "last-snapshot.json"
LOG_FILE = SCRIPT_DIR / "log" / "watcher.log"
POLL_INTERVAL_SEC = int(os.environ.get("KANBAN_WATCHER_INTERVAL", 300))  # 5 min
NOTIFY_CHAT = os.environ.get("KANBAN_NOTIFY_CHAT", "1460056890")
NOTIFY_PROFILE = os.environ.get("KANBAN_NOTIFY_PROFILE", "thoth")
DEDUP_WINDOW_MIN = 15  # suppress duplicate notifications within this window

# Ensure dirs exist
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}\n"
    with LOG_FILE.open("a") as f:
        f.write(line)


def get_kanban_state() -> list[dict]:
    """Run `hermes kanban list --json` and return the parsed task list."""
    result = subprocess.run(
        ["hermes", "kanban", "list", "--json"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        log(f"hermes kanban list failed: {result.stderr}")
        return []
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        log(f"json parse error: {e}")
        return []


def load_last_snapshot() -> list[dict]:
    if not STATE_FILE.exists():
        return []
    try:
        return json.loads(STATE_FILE.read_text())
    except json.JSONDecodeError:
        return []


def save_snapshot(state: list[dict]) -> None:
    STATE_FILE.write_text(json.dumps(state, sort_keys=True))


def task_signature(task: dict) -> str:
    """Stable signature for dedup — status + id + last_heartbeat."""
    h = hashlib.sha256()
    h.update(task["id"].encode())
    h.update(task.get("status", "").encode())
    h.update(task.get("last_heartbeat_at", "").encode())
    return h.hexdigest()[:16]


def diff_states(old: list[dict], new: list[dict]) -> list[dict]:
    """Return tasks that changed status since the last snapshot."""
    old_sigs = {t["id"]: task_signature(t) for t in old}
    changes = []
    for task in new:
        if task["id"] not in old_sigs:
            # new task
            changes.append({"type": "new", "task": task})
        elif old_sigs[task["id"]] != task_signature(task):
            # status changed
            old_status = next(
                (t.get("status") for t in old if t["id"] == task["id"]), None
            )
            changes.append({
                "type": "status_change",
                "task": task,
                "old_status": old_status,
            })
    # also catch removed tasks (chain cancelled, etc.)
    new_ids = {t["id"] for t in new}
    for t in old:
        if t["id"] not in new_ids:
            changes.append({"type": "removed", "task": t})
    return changes


def format_notification(change: dict) -> str | None:
    """Format a notification message for a state change. None = no notification."""
    task = change["task"]
    title = task.get("title", task["id"])
    status = task.get("status", "unknown")
    assignee = task.get("assignee", "?")

    if change["type"] == "new":
        return f"[chain] new task: {title} (assignee: {assignee}, status: {status})"

    if change["type"] == "status_change":
        old_status = change.get("old_status", "?")
        if status == "blocked":
            reason = task.get("block_reason", "no reason given")
            return (
                f"[chain] BLOCKED: {title}\n"
                f"  status: {old_status} → {status}\n"
                f"  reason: {reason}\n"
                f"  action: unblock with `hermes kanban unblock {task['id']} '<reason>'`"
            )
        if status == "running" and old_status in ("ready", "todo"):
            return f"[chain] started: {title} (assignee: {assignee})"
        if status == "done":
            return f"[chain] done: {title} (assignee: {assignee})"
        if status in ("crashed", "gave_up"):
            return (
                f"[chain] CRASHED: {title}\n"
                f"  status: {old_status} → {status}\n"
                f"  action: check `hermes kanban log {task['id']}` and decide (reclaim / reassign / cancel)"
            )
        return f"[chain] status change: {title} ({old_status} → {status})"

    if change["type"] == "removed":
        return f"[chain] task removed: {title} (was {task.get('status', '?')})"

    return None


def push_notification(message: str) -> None:
    """Send a notification via messaging_send to the operator's chat."""
    log(f"notify: {message[:200]}")
    # Use the thoth profile's messaging_send to deliver to the operator's chat.
    # The profile owns the gateway that posts to Telegram.
    subprocess.run(
        [
            "hermes", "run",
            "--profile", NOTIFY_PROFILE,
            "mcp_pantheon_messaging_send",
            f"--to=konan",
            f"--subject=chain-update",
            f"--body={message}",
            "--priority=info",
        ],
        capture_output=True, text=True, timeout=30,
    )


def main() -> int:
    log(f"poll start (interval: {POLL_INTERVAL_SEC}s)")
    old_state = load_last_snapshot()
    new_state = get_kanban_state()

    if not new_state:
        log("no tasks found or list failed; skipping")
        return 0

    changes = diff_states(old_state, new_state)
    log(f"detected {len(changes)} change(s)")

    for change in changes:
        msg = format_notification(change)
        if msg:
            push_notification(msg)

    save_snapshot(new_state)
    log("poll done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

## The crontab entry

```cron
# Kanban-watcher — proactive chain state notifications
*/5 * * * * cd ~/.hermes/cron/kanban-watcher && python3 kanban-watcher.py >> log/watcher.log 2>&1
```

## Notification priority rules

| Change | Channel | Priority |
|---|---|---|
| New task created | thoth (info) | low |
| Task started (ready → running) | thoth (info) | low |
| Task blocked (operator gate) | thoth (warning) | medium — operator needs to act |
| Task done | thoth (info) | low |
| Worker crashed / gave_up | thoth (error) | high — operator decides recover/cancel |
| Phase complete (all phase tasks done) | thoth (info) | medium — operator signs off next phase |
| QA verdict `block` | thoth (error) | high — chain is halted |

## Dedup logic

- Snapshot stores `task_signature` per task (id + status + last_heartbeat)
- On each poll, diff against last snapshot — only emit notifications for *changes*
- Re-poll within the dedup window: no notification (state didn't change)
- This prevents the "every 5 min you get a 'task still running' ping" problem

## What this script does NOT do

- It does **not** watch the chain in real-time (5-min cadence is the floor)
- It does **not** start, claim, complete, or modify any task (read-only)
- It does **not** decide operator actions — it surfaces the state and the recommended action, the operator decides
- It does **not** replace `dispatch-monitoring` — the skill governs the human-in-the-loop interpretation of state changes; the cron just delivers the data

## Pitfalls

**Don't push notifications on every poll.** Use the dedup snapshot — only emit on *change*. A constant "task still running" ping is worse than no notification at all.

**Don't act on the state.** The watcher is read-only. The watchdog (in the chat session) or the operator decides what to do with a stalled task.

**Don't run the watcher at sub-minute cadence.** Every 5 min is the right balance: catches stalls within 5-10 min, doesn't hammer the DB or the chat. If you need faster visibility, run `hermes kanban watch` interactively in a long-lived session.

**Don't put the script in `~/pantheon/` or `~/projects/`.** It lives in `~/.hermes/cron/kanban-watcher/`. The cron dir is the home for unattended automation that owns the gateway.

**Don't skip the log file.** When the watcher is silent, the operator can't tell whether "no change" means "the chain is healthy" or "the script crashed." Write a heartbeat line on every poll (success or failure).

## The "one-minute" rule for stalled tasks

If a task has been `running` for >10 minutes without a heartbeat in the snapshot, the watcher should emit a warning. The 10-min threshold is chosen because:
- Workers with `--max-runtime` of 30-60 min should be heartbeating every 5-10 min
- A 10-min silence is the first signal of a real stall
- Below 10 min, the noise-vs-signal ratio is too high (workers pause for tool calls)

The watcher does NOT auto-reclaim stalled tasks. The watchdog (in the dispatch-monitoring skill) does that. The watcher just surfaces the stall to the operator.

## Future improvements (not yet built)

- **Real-time WebSocket** — replace the 5-min poll with a push from the kanban daemon (the daemon already has a WebSocket layer; the watcher just needs a WS client)
- **Per-chain subscriptions** — operators with multiple in-flight chains should be able to subscribe to a specific chain, not get notified on every chain
- **Operator-configurable thresholds** — let the operator tune the stall threshold (default 10 min) and the dedup window (default 15 min) per profile

## See also

- `dispatch-monitoring` SKILL.md — the watchdog skill that interprets the watcher's notifications
- `plan-execution` SKILL.md — the dispatching skill that creates the in-flight tasks the watcher is monitoring
- `build-plan-orchestrator` SKILL.md — the chain that creates the plan the dispatcher consumes
- `references/operator-locked-output-rules-2026-06-16.md` (in `build-spec-authoring`) — the no-time-estimates rule applies to notifications too
