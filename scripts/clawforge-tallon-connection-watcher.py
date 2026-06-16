#!/usr/bin/env python3
"""
clawforge-tallon-connection-watcher.py

Polls the Clawforge known-instances cache for a new "tallon" entry.
When Tallon's Pantheon proxy heartbeats for the first time and his
entry appears in known-instances.json, sends a Telegram notification
to the home channel and exits cleanly.

This is a one-shot watcher — it runs until either:
  (a) the "tallon" key appears in known-instances.json (success), OR
  (b) the max runtime elapses (default 7 days), OR
  (c) it receives SIGINT/SIGTERM (manual cancel)

Why a dedicated script vs. a cron:
  - The known-instances.json file is updated by clawforge-proxy on
    every heartbeat from any instance. Polling is cheap (a few KB of
    JSON) but we want the check to fire FAST after Tallon connects
    (so we can immediately do a round-trip test), not wait for the
    next 15-min cron tick.
  - Sending a Telegram alert from inside a cron means shelling out
    to a Python script that reads ~/.config/systemd/.../override.conf
    for the bot token. Easier to just have a single-purpose script
    do it inline.

Usage:
    # Default: watch for 7 days, check every 30s
    python3 scripts/clawforge-tallon-connection-watcher.py

    # Quick test: 60s timeout
    python3 scripts/clawforge-tallon-connection-watcher.py --max-runtime 60 --interval 5

    # Background, detached (so it survives this session ending):
    nohup python3 scripts/clawforge-tallon-connection-watcher.py > /tmp/tallon-watch.log 2>&1 &
    echo $! > /tmp/tallon-watch.pid
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

# --- Paths -------------------------------------------------------------------
KNOWN_INSTANCES = Path("/home/konan/.hermes/clawforge/known-instances.json")
LOG_FILE = Path("/home/konan/.hermes/clawforge/tallon-watcher.log")
STATE_FILE = Path("/home/konan/.hermes/clawforge/tallon-watcher.state")
TELEGRAM_BOT_TOKEN = ""  # read from env at runtime
TELEGRAM_CHAT_ID = "1460056890"  # Cyber's home channel

# --- Logging -----------------------------------------------------------------
def _setup_logging(verbose: bool = False) -> logging.Logger:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = logging.getLogger("tallon-watcher")
    log.setLevel(logging.DEBUG if verbose else logging.INFO)
    # File handler
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s"))
    log.addHandler(fh)
    # Stdout handler
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s"))
    log.addHandler(sh)
    return log


# --- Telegram ----------------------------------------------------------------
def _read_telegram_token() -> Optional[str]:
    """Read TELEGRAM_BOT_TOKEN from any plausible source.

    Order of preference:
      1. Environment (set by a systemd drop-in or by the parent shell)
      2. ~/.hermes/.env (the global Hermes env file)
    """
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if tok:
        return tok
    env_path = Path("/home/konan/.hermes/.env")
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
            if val:
                return val
    return None


def send_telegram(log: logging.Logger, text: str) -> bool:
    tok = _read_telegram_token()
    if not tok:
        log.warning("TELEGRAM_BOT_TOKEN not set; cannot send alert")
        return False
    url = f"https://api.telegram.org/bot{tok}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        # Markdown is auto-converted by the gateway; keep it minimal
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status == 200
            log.info("telegram send: status=%s", resp.status)
            return ok
    except Exception as e:
        log.warning("telegram send failed: %s", e)
        return False


# --- Watcher loop ------------------------------------------------------------
def check_tallon_present(log: logging.Logger) -> Optional[dict]:
    """Read known-instances.json and return the tallon entry if present."""
    if not KNOWN_INSTANCES.exists():
        return None
    try:
        data = json.loads(KNOWN_INSTANCES.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.debug("known-instances.json not yet parseable: %s", e)
        return None
    instances = data.get("instances", {}) or {}
    entry = instances.get("tallon")
    return entry if entry else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument(
        "--interval",
        type=int,
        default=30,
        help="seconds between checks (default 30)",
    )
    ap.add_argument(
        "--max-runtime",
        type=int,
        default=7 * 24 * 3600,
        help="max seconds to run before giving up (default 7 days)",
    )
    ap.add_argument("--once", action="store_true", help="check once and exit (diagnostic)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    log = _setup_logging(args.verbose)
    log.info("watcher starting; pid=%d interval=%ds max_runtime=%ds",
             os.getpid(), args.interval, args.max_runtime)
    log.info("watching %s for 'tallon' entry", KNOWN_INSTANCES)

    # Honor SIGINT/SIGTERM cleanly
    stop = {"flag": False}
    def _handle(_signo, _frame):
        stop["flag"] = True
        log.info("received signal, will exit after this iteration")
    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)

    # If we're a re-run after a previous run already found tallon, just exit
    if STATE_FILE.exists():
        try:
            prev = json.loads(STATE_FILE.read_text())
            if prev.get("tallon_seen_at"):
                log.info("tallon was previously seen at %s; nothing to do",
                         prev["tallon_seen_at"])
                return 0
        except (json.JSONDecodeError, OSError):
            pass

    start = time.time()
    checks = 0
    while not stop["flag"]:
        if time.time() - start > args.max_runtime:
            log.warning("max runtime (%ds) reached without seeing tallon; exiting",
                        args.max_runtime)
            send_telegram(
                log,
                "⚠️ Clawforge Tallon-watcher: max runtime reached (7 days) "
                "without Tallon appearing in known-instances. Manual check needed.",
            )
            return 1

        entry = check_tallon_present(log)
        checks += 1
        if entry:
            seen_at = entry.get("last_seen", "unknown")
            gods = list((entry.get("gods") or {}).keys())
            god_count = len(gods)
            god_list = ", ".join(gods[:6])
            if len(gods) > 6:
                god_list += f", +{len(gods) - 6} more"

            msg = (
                "🟢 **Clawforge federation: Tallon is online**\n\n"
                f"Last heartbeat: {seen_at}\n"
                f"Gods registered: {god_count} ({god_list})\n"
                f"Source subject: {entry.get('source_subject', '?')}\n\n"
                "His proxy is heartbeating on `claw.profile.update` and his entry "
                "is now in `known-instances.json`. Federation is up.\n\n"
                "Next: run a round-trip probe — `hermes ask talon:data@tallon "
                "--message 'bus round-trip test'`."
            )
            log.info("TALLON DETECTED at check #%d: gods=%d last_seen=%s",
                     checks, god_count, seen_at)
            send_telegram(log, msg)
            STATE_FILE.write_text(json.dumps({
                "tallon_seen_at": seen_at,
                "detected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "checks_to_detect": checks,
                "god_count": god_count,
            }, indent=2))
            return 0

        if args.verbose or checks % 20 == 0:
            log.info("check #%d: tallon not yet present (%.0fs elapsed)",
                     checks, time.time() - start)

        if args.once:
            log.info("--once: tallon not present, exiting")
            return 2

        # Sleep with early-exit on signal
        for _ in range(args.interval):
            if stop["flag"]:
                break
            time.sleep(1)

    log.info("watcher stopped by signal")
    return 0


if __name__ == "__main__":
    sys.exit(main())
