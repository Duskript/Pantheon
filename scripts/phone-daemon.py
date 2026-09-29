#!/usr/bin/env python3
"""
Pantheon Phone Notification Daemon
Polls the gateway phone via ADB every 10 seconds, routes notifications by app.
No LLM calls — just pure Python routing.

The device address and the adb binary are RESOLVED, never hardcoded. The phone's
LAN IP drifted .18 -> .19 -> .11 within a single month (each one "correct" when
written), and adb is not on PATH on this host — so a bare `subprocess(["adb", ...])`
raised FileNotFoundError and the daemon died at startup before polling anything.

Usage:
  python3 phone-daemon.py                  # run foreground
  python3 phone-daemon.py --daemon         # run as background process
  python3 phone-daemon.py --backend-check  # report screen-backend health and exit
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
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for phone_screen

from phone_screen import PhoneScreen, resolve_adb, resolve_device  # noqa: E402

# ── Config ──────────────────────────────────────────────────────────────
# Device + tooling are resolved, not constants. See phone_screen.resolve_device
# for the order (env override -> Tailscale -> a known adb transport -> last-known LAN).
ADB_BIN = resolve_adb()
PHONE_ADB = resolve_device(ADB_BIN)
POLL_INTERVAL = int(os.environ.get("PANTHEON_PHONE_POLL_INTERVAL", "10"))  # seconds between polls

#: When on, reply-worthy notifications are annotated with the foreground app, read
#: through the screen backend (ARTEMIS helper first, uiautomator2 fallback).
#: Off by default: it costs a screen read per event, and the helper is silent while
#: a god is driving the phone via uiautomator2 (UiAutomation suppresses it).
SCREEN_CONTEXT = os.environ.get("PANTHEON_PHONE_SCREEN_CONTEXT", "0").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
    "",
)
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
    """Run an ADB shell command, return (output, success).

    Uses the resolved ADB_BIN rather than a bare "adb": adb is not on PATH on this
    host, so the literal string raised FileNotFoundError and killed the daemon at
    startup with "ADB not found" before it ever polled a phone.
    """
    try:
        result = subprocess.run(
            [ADB_BIN, "-s", PHONE_ADB, "shell", command],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.stdout, result.returncode == 0
    except subprocess.TimeoutExpired:
        return "", False
    except FileNotFoundError:
        log.error(f"adb not found at {ADB_BIN!r}. Set PANTHEON_ADB_BIN to its full path.")
        sys.exit(1)


def backend_check() -> int:
    """Report screen-backend health and exit.

    Run this before blaming the daemon for anything: it shows which phone was
    resolved, whether the ARTEMIS helper is answering, and whether a UiAutomation
    holder is currently suppressing it. Note the daemon itself reads *notifications*
    via `dumpsys`, which is not a UiAutomation call — the screen backend is used
    only for the optional foreground-app annotation.
    """
    log.info(f"Gateway resolution: {PHONE_ADB}  (adb: {ADB_BIN})")
    report = PhoneScreen(device=PHONE_ADB).probe()
    for key, value in report.items():
        log.info(f"  {key}: {value}")
    log.info(f"  screen context enrichment: {'ON' if SCREEN_CONTEXT else 'off'}")
    return 0


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
    """For reply-worthy notifications, write to a reply queue file.

    The reply queue is consumed by the LLM when it's active — not polled.
    """
    if not entry["needs_reply"]:
        return

    # Optional enrichment: what app is on screen right now, read through the
    # screen backend. This is the only place the daemon uses the ARTEMIS helper.
    if SCREEN_CONTEXT:
        try:
            entry["screen"] = PhoneScreen(device=PHONE_ADB).foreground_app()
        except RuntimeError as exc:
            # A failed read must never drop the notification — record why instead.
            entry["screen"] = {"error": str(exc)}

    reply_queue = LOG_DIR / "reply_queue.jsonl"
    with open(reply_queue, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log.info(f"📩 Queued for reply: {entry['label']} — {entry['text'][:80]}")


def main():
    log.info("=" * 60)
    log.info("Pantheon Phone Notification Daemon starting...")
    log.info(f"Phone: {PHONE_ADB}   (resolved, not hardcoded)")
    log.info(f"ADB binary: {ADB_BIN}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Log file: {LOG_FILE}")
    log.info(f"Screen context: {'ON' if SCREEN_CONTEXT else 'off'}")
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
    if "--backend-check" in sys.argv:
        sys.exit(backend_check())
    if "--daemon" in sys.argv:
        # Fork to background
        pid = os.fork()
        if pid > 0:
            print(f"Daemon started (PID: {pid})")
            sys.exit(0)
        # Child continues
        sys.stdin.close()
    main()
