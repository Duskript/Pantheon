#!/usr/bin/env python3
"""
Pantheon Phone Notification Daemon
Polls the Pixel 7 via ADB every 10 seconds, routes notifications by app.
No LLM calls — just pure Python routing.

Usage:
  python3 phone-daemon.py              # run foreground
  python3 phone-daemon.py --daemon     # run as background process
"""

import sys
import os
import json
import time
import re
import subprocess
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path

# ── PYTHONPATH fix: Strip Hermes vendor (PIL conflict) ────────────────
_HERMES_VENDOR = str(Path.home() / ".hermes" / "vendor")
sys.path = [p for p in sys.path if _HERMES_VENDOR not in p]

# ── Config ──────────────────────────────────────────────────────────────
PHONE_ADB = os.environ.get("PANTHEON_PHONE_ADB_ADDR", "192.168.1.18:5555")
POLL_INTERVAL = int(os.environ.get("PANTHEON_PHONE_POLL_INTERVAL", "10"))  # seconds between polls
LOG_DIR = Path(os.environ.get("PANTHEON_PHONE_DAEMON_DIR", str(Path.home() / "pantheon" / "phone-daemon")))
LOG_FILE = LOG_DIR / "notifications.jsonl"
STATE_FILE = LOG_DIR / "seen_notifications.json"

# App routing — which apps get LLM replies vs just logged
APP_ROUTES = {
    "com.facebook.orca": {        # Facebook Messenger
        "priority": "high",
        "label": "Facebook Messenger",
        "needs_reply": True,
    },
    "com.facebook.katana": {      # Facebook
        "priority": "medium",
        "label": "Facebook",
        "needs_reply": False,
    },
    "com.twitter.android": {      # Twitter/X
        "priority": "medium",
        "label": "Twitter/X",
        "needs_reply": False,
    },
    "com.linkedin.android": {     # LinkedIn
        "priority": "medium",
        "label": "LinkedIn",
        "needs_reply": False,
    },
    "xyz.blueskyweb.app": {       # Bluesky
        "priority": "medium",
        "label": "Bluesky",
        "needs_reply": False,
    },
    "com.reddit.frontpage": {     # Reddit
        "priority": "medium",
        "label": "Reddit",
        "needs_reply": False,
    },
    "com.ebay.mobile": {          # eBay
        "priority": "low",
        "label": "eBay",
        "needs_reply": False,
    },
    "com.instagram.android": {    # Instagram
        "priority": "medium",
        "label": "Instagram",
        "needs_reply": False,
    },
}

# ── Setup ──────────────────────────────────────────────────────────────
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "daemon.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("phone-daemon")


def adb_shell(command: str) -> tuple[str, bool]:
    """Run an ADB shell command, return (output, success)."""
    try:
        result = subprocess.run(
            ["adb", "-s", PHONE_ADB, "shell", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout, result.returncode == 0
    except subprocess.TimeoutExpired:
        return "", False
    except FileNotFoundError:
        log.error("ADB not found. Make sure it's installed and in PATH.")
        sys.exit(1)


def get_raw_notifications() -> str:
    """Get all current notifications as raw text."""
    output, ok = adb_shell("dumpsys notification --noredact")
    return output if ok else ""


def parse_notifications(raw: str) -> list[dict]:
    """Parse dumpsys notification output into structured notification dicts."""
    notifications = []
    current = None

    for line in raw.split("\n"):
        # Start of a new notification record
        m = re.match(r'\s+NotificationRecord\(.*?\)\s+u=\d+\s+pkg=(\S+)', line)
        if m:
            if current:
                notifications.append(current)
            current = {
                "package": m.group(1),
                "key": "",
                "title": "",
                "text": "",
                "when": 0,
            }
            continue

        if current is None:
            continue

        # Key
        m = re.match(r'\s+key=(\S+)', line)
        if m:
            current["key"] = m.group(1)
            continue

        # Title
        m = re.match(r'\s+android\.title=(\S+)', line)
        if m:
            current["title"] = m.group(1)
            continue

        # Text (message content)
        m = re.match(r'\s+android\.text=(\S+)', line)
        if m:
            current["text"] = m.group(1)
            continue

        # When (timestamp)
        m = re.match(r'\s+when=(\d+)', line)
        if m:
            current["when"] = int(m.group(1))
            continue

    if current:
        notifications.append(current)

    return notifications


def load_seen() -> set:
    """Load set of already-seen notification keys."""
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()))
        except (json.JSONDecodeError, KeyError):
            pass
    return set()


def save_seen(seen: set):
    """Save seen notification keys."""
    STATE_FILE.write_text(json.dumps(list(seen)))


def notification_id(n: dict) -> str:
    """Create a unique ID for dedup."""
    raw = f"{n.get('key', '')}|{n.get('title', '')}|{n.get('text', '')}"
    return hashlib.md5(raw.encode()).hexdigest()


def route_notification(n: dict) -> dict:
    """Route a notification and return the routing decision."""
    pkg = n.get("package", "")
    route = APP_ROUTES.get(pkg, {
        "priority": "ignore",
        "label": pkg.split(".")[-1] if "." in pkg else pkg,
        "needs_reply": False,
    })

    return {
        "id": notification_id(n),
        "package": pkg,
        "label": route["label"],
        "priority": route["priority"],
        "needs_reply": route["needs_reply"],
        "title": n.get("title", ""),
        "text": n.get("text", ""),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actions": [],
    }


def log_notification(entry: dict):
    """Write a notification entry to the JSONL log."""
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def dispatch_reply_queue(entry: dict):
    """For high-priority notifications, write to a reply queue file.

    The reply queue is consumed by the LLM when it's active — not polled.
    """
    if entry["needs_reply"]:
        reply_queue = LOG_DIR / "reply_queue.jsonl"
        with open(reply_queue, "a") as f:
            f.write(json.dumps(entry) + "\n")
        log.info(f"📩 Queued for reply: {entry['label']} — {entry['text'][:80]}")


def main():
    log.info("=" * 60)
    log.info("Pantheon Phone Notification Daemon starting...")
    log.info(f"Phone: {PHONE_ADB}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Log file: {LOG_FILE}")
    log.info("=" * 60)

    # Verify ADB connection
    output, ok = adb_shell("getprop ro.product.model")
    if not ok:
        log.error(f"Cannot connect to phone at {PHONE_ADB}. Check ADB.")
        sys.exit(1)
    log.info(f"Connected to: {output.strip()}")

    seen = load_seen()
    log.info(f"Loaded {len(seen)} previously seen notifications")

    cycle_count = 0
    while True:
        try:
            raw = get_raw_notifications()
            notifs = parse_notifications(raw)

            new_count = 0
            for n in notifs:
                nid = notification_id(n)
                if nid in seen:
                    continue
                seen.add(nid)

                entry = route_notification(n)
                if entry["priority"] == "ignore":
                    continue  # skip unregistered apps silently

                log_notification(entry)
                dispatch_reply_queue(entry)
                new_count += 1

                if entry["priority"] == "high":
                    log.info(f"🔴 [{entry['label']}] {entry['text'][:120]}")
                elif entry["priority"] == "medium":
                    log.info(f"🟡 [{entry['label']}] {entry['text'][:80]}")
                else:
                    log.debug(f"⚪ [{entry['label']}] {entry['text'][:60]}")

            # Compact seen set occasionally
            cycle_count += 1
            if cycle_count % 60 == 0:  # ~every 10 min
                save_seen(seen)
                log.debug(f"State saved. Tracking {len(seen)} notification IDs.")

        except Exception as e:
            log.error(f"Error in poll cycle: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    if "--daemon" in sys.argv:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            print(f"Daemon started (PID: {pid})")
            sys.exit(0)
        # Child continues
        sys.stdin.close()
    main()
