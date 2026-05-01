#!/usr/bin/env python3
"""The Fates — Pantheon heartbeat monitor and subsystem watchdog.

Runs every 5 minutes via cron. For each tracked subsystem:
  1. Checks the heartbeat file for staleness
  2. For reachable subsystems, does an active liveness probe
  3. If any subsystem is stale AND unreachable, sends an alert to Hermes

Also writes its own heartbeat on successful completion.

Usage:
  python3 scripts/the-fates.py          # Normal run
  python3 scripts/the-fates.py --init   # Initialize heartbeat file + run
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure we can import heartbeat.py from the same directory
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from heartbeat import beat, check_stale, initialise, get_all  # noqa: E402

logger = logging.getLogger("the-fates")

# ── Paths ─────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
_REAL_HOME = os.environ.get("HERMES_REAL_HOME", _HOME)
if _REAL_HOME != _HOME and _REAL_HOME != os.path.join(_HOME, ".."):
    _HOME = _REAL_HOME
if ".hermes/profiles" in _HOME:
    _HOME = _HOME.split("/.hermes/profiles/")[0]

HERMES_INBOX = Path(f"{_HOME}/pantheon/gods/messages/hermes")
MCP_SERVER_URL = "http://127.0.0.1:8010/mcp"

# Subsystems whose process we can actively check via MCP or process signals
PROBEABLE = {"mcp_server", "hermes_gateway", "apollo_gateway"}

# Subsystems we actively probe via MCP
MCP_PROBEABLE = {
    "mcp_server": "system_health",
    "hermes_gateway": "god_list",   # if MCP is up, we know Hermes profile ran
    "apollo_gateway": "god_list",  # same for Apollo
}


# ── Probes ────────────────────────────────────────────────────────────


def probe_mcp_server() -> tuple[bool, Optional[str]]:
    """Check if the Pantheon MCP server is alive via HTTP.

    Returns (alive, error_message).
    """
    import httpx
    try:
        resp = httpx.post(
            MCP_SERVER_URL,
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream, application/json",
            },
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "the-fates", "version": "1.0.0"},
                },
                "id": 1,
            },
            timeout=10.0,
        )
        if resp.status_code == 200:
            return True, None
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, str(exc)


def probe_process(process_name: str) -> tuple[bool, Optional[str]]:
    """Check if a process is running by name using ps.

    Returns (running, error_message).
    """
    try:
        result = os.popen(f"pgrep -f '{process_name}' 2>/dev/null").read().strip()
        if result:
            return True, None
        return False, f"process {process_name} not found"
    except Exception as exc:
        return False, str(exc)


def probe_subsystem(subsystem_id: str) -> tuple[bool, Optional[str]]:
    """Actively probe a subsystem for liveness.

    Returns (alive, error_message).
    """
    if subsystem_id == "mcp_server":
        return probe_mcp_server()
    elif subsystem_id == "hermes_gateway":
        # Check for hermes gateway process
        alive, err = probe_process("hermes gateway")
        if alive:
            return True, None
        # Alternative: check for Telegram bot processes
        return probe_process("hermes")
    elif subsystem_id == "apollo_gateway":
        return probe_process("apollo")
    else:
        # Can't probe — rely on heartbeat only
        return True, None


# ── Alerting ──────────────────────────────────────────────────────────


def send_alert(subsystem_id: str, label: str, reason: str,
               staleness_min: Optional[float], probe_error: Optional[str]) -> None:
    """Send a high-priority alert to Hermes' inbox."""
    now = datetime.now(timezone.utc)

    body_parts = [
        f"**Subsystem:** {label} (`{subsystem_id}`)",
        f"**Status:** ⚠️  MISSING HEARTBEAT",
        f"**Detected at:** {now.isoformat()}",
        f"**Reason:** {reason}",
    ]
    if staleness_min is not None:
        body_parts.append(f"**Stale for:** {staleness_min} minutes")
    if probe_error:
        body_parts.append(f"**Probe error:** {probe_error}")

    # Suggest actions based on subsystem
    suggestions = {
        "mcp_server": "Run: `cd ~/pantheon/pantheon-core && python3 mcp_server.py --port 8010` or `systemctl --user start pantheon-mcp`",
        "hermes_gateway": "Run: `hermes gateway start` or check `~/.hermes/logs/gateway.log`",
        "apollo_gateway": "Run: `hermes -p apollo gateway start` or check profile logs",
        "hades": "Run: `cd ~/pantheon && python3 pantheon-core/gods/hades.py` to trigger manually",
        "hestia": "Run: `cd ~/pantheon && python3 pantheon-core/gods/hestia.py` if health checks are stuck",
    }
    if subsystem_id in suggestions:
        body_parts.append(f"\n**Suggested action:** {suggestions[subsystem_id]}")

    body_parts.append(f"\nAll heartbeats: `cat ~/.hermes/pantheon/heartbeat.json`")
    body = "\n".join(body_parts)

    message = {
        "id": f"fates_alert_{now.strftime('%Y%m%d_%H%M%S')}_{subsystem_id[:12]}",
        "from": "the_fates",
        "to": "hermes",
        "type": "alert",
        "subject": f"⚠️ MISSING HEARTBEAT: {label}",
        "body": body,
        "priority": "high",
        "timestamp": now.isoformat(),
        "read": False,
        "payload": {
            "subsystem_id": subsystem_id,
            "label": label,
            "reason": reason,
            "staleness_min": staleness_min,
            "probe_error": probe_error,
            "alert_type": "missed_heartbeat",
        },
        "thread_id": "heartbeat-monitoring",
    }

    HERMES_INBOX.mkdir(parents=True, exist_ok=True)
    msg_path = HERMES_INBOX / f"{message['id']}.json"
    try:
        msg_path.write_text(json.dumps(message, indent=2) + "\n", encoding="utf-8")
        logger.warning(
            "Alert sent to Hermes: %s missing (%s)",
            subsystem_id, reason,
        )
    except Exception as exc:
        logger.error("Failed to write alert message: %s", exc)


# ── Dedup: Track what we've already alerted about ─────────────────────


_ALERTED_PATH = Path(f"{_HOME}/.hermes/pantheon/fates-alerted.json")


def _load_alerted() -> dict[str, str]:
    """Load the set of subsystems we've already alerted about.

    Returns {subsystem_id: last_alert_timestamp}
    """
    if not _ALERTED_PATH.exists():
        return {}
    try:
        return json.loads(_ALERTED_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_alerted(alerted: dict[str, str]) -> None:
    """Save the alerted set."""
    _ALERTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    _ALERTED_PATH.write_text(json.dumps(alerted, indent=2) + "\n", encoding="utf-8")


def _should_alert(subsystem_id: str, staleness_min: Optional[float]) -> tuple[bool, Optional[str]]:
    """Check if we should send an alert for this subsystem.

    Rules:
    - Alert if it's been stale for more than 2x its expected interval
    - Alert immediately if it's a critical subsystem (mcp_server, hermes_gateway)
    - Don't re-alert if we already alerted within the last 60 minutes
    """
    alerted = _load_alerted()
    last_alert = alerted.get(subsystem_id)

    if last_alert:
        last = datetime.fromisoformat(last_alert)
        minutes_since = (datetime.now(timezone.utc) - last).total_seconds() / 60
        if minutes_since < 60:
            return False, "already alerted within last hour"

    # Check if it's critical or stale enough
    if subsystem_id in ("mcp_server", "hermes_gateway", "the_fates"):
        return True, None  # Always alert on critical systems

    if staleness_min is not None and staleness_min >= 120:
        return True, None  # Stale for 2+ hours

    # For subsystems with large intervals like Hades (daily), alert sooner
    if staleness_min is not None and staleness_min >= 30:
        return True, None

    return False, "not stale enough to alert"


def _mark_alerted(subsystem_id: str) -> None:
    """Record that we sent an alert."""
    alerted = _load_alerted()
    alerted[subsystem_id] = datetime.now(timezone.utc).isoformat()
    _save_alerted(alerted)


# ── Main Run Logic ────────────────────────────────────────────────────


def run() -> int:
    """Run The Fates check cycle.

    Returns 0 if all ok, 1 if alerts were sent.
    """
    now = datetime.now(timezone.utc)
    logger.info("The Fates check cycle starting at %s", now.isoformat())

    # Step 1: Get all stale subsystems from heartbeat file
    stale_list = check_stale()
    alerts_sent = 0

    # Step 2: For each stale subsystem, probe actively
    for entry in stale_list:
        sid = entry["subsystem_id"]
        label = entry["label"]
        reason = entry.get("reason", "stale")
        staleness = entry.get("staleness_min")

        should_alert, skip_reason = _should_alert(sid, staleness)
        if not should_alert:
            logger.debug("Skipping alert for %s: %s", sid, skip_reason)
            continue

        # Active probe
        alive, probe_err = probe_subsystem(sid)

        if not alive:
            send_alert(sid, label, reason, staleness, probe_err)
            _mark_alerted(sid)
            alerts_sent += 1
        else:
            # Subsystem is alive but didn't write heartbeat — update it
            logger.info("%s is alive (probe OK) but heartbeat missing — updating", sid)
            beat(sid)
            if sid in _load_alerted() and staleness and staleness > 60:
                # Clear prior alert: it's alive now
                alerted = _load_alerted()
                if sid in alerted:
                    del alerted[sid]
                    _save_alerted(alerted)

    # Step 3: Also check critical subsystems that might NOT be in stale_list
    # (e.g., MCP server could be completely down and never wrote a heartbeat)
    for sid in ("mcp_server", "hermes_gateway"):
        alive, _ = probe_subsystem(sid)
        stale_sids = {e["subsystem_id"] for e in stale_list}
        if not alive and sid not in stale_sids:
            # It's down but never registered a heartbeat — this is a "never started" scenario
            should_alert, _ = _should_alert(sid, None)
            if should_alert:
                all_heartbeats = get_all()
                label = all_heartbeats.get(sid, {}).get("label", sid)
                send_alert(sid, label, "never_reported_or_unreachable", None, f"Active probe failed")
                _mark_alerted(sid)
                alerts_sent += 1

    # Step 4: Write The Fates' own heartbeat
    if alerts_sent > 0:
        logger.warning("Check cycle complete — %d alert(s) sent", alerts_sent)
    else:
        logger.info("Check cycle complete — all subsystems healthy")

    beat("the_fates")
    return 1 if alerts_sent > 0 else 0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="The Fates — Pantheon Heartbeat Monitor")
    parser.add_argument("--init", action="store_true", help="Initialize heartbeat file before running")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.init:
        logger.info("Initializing heartbeat file...")
        initialise()

    exit_code = run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
