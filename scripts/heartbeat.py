"""Pantheon Heartbeat — shared subsystem heartbeat tracking.

Every scheduled subsystem (Hades, Hestia, Demeter, Fates, MCP server, etc.)
writes a heartbeat entry when it runs successfully. The Fates monitor checks
all heartbeats and alerts Hermes if any are stale.

Architecture:
  - Single JSON file: ~/.hermes/pantheon/heartbeat.json
  - Each subsystem has an entry with: last_ok, last_error, expected_interval_min
  - The Fates reads all entries, compares against current time, raises alerts
  - Alerts go to Hermes' inbox via the file bridge protocol
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────

# Compute REAL_HOME (Hermes-proof, same logic as pantheon_sdk.py)
_HOME = os.path.expanduser("~")
_REAL_HOME = os.environ.get("HERMES_REAL_HOME", _HOME)
if _REAL_HOME != _HOME and _REAL_HOME != os.path.join(_HOME, ".."):
    _HOME = _REAL_HOME
if ".hermes/profiles" in _HOME:
    _HOME = _HOME.split("/.hermes/profiles/")[0]

_PANTHEON_DATA_DIR = Path(f"{_HOME}/.hermes/pantheon")
HEARTBEAT_PATH = _PANTHEON_DATA_DIR / "heartbeat.json"
HERMES_INBOX = Path(f"{_HOME}/pantheon/gods/messages/hermes")

# ── Data Model ────────────────────────────────────────────────────────

# Each entry: subsystem id → status dict
DEFAULT_HEARTBEATS: dict[str, Any] = {
    "mcp_server": {
        "label": "Pantheon MCP Server",
        "last_ok": None,        # ISO 8601 timestamp string
        "last_error": None,     # ISO 8601 or null
        "expected_interval_min": 5,
    },
    "hermes_gateway": {
        "label": "Hermes Gateway (Telegram/Discord)",
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": 5,
    },
    "apollo_gateway": {
        "label": "Apollo Gateway (Telegram)",
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": 5,
    },
    "hades": {
        "label": "Hades — Nightly Consolidation",
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": 1440,  # daily
    },
    "hestia": {
        "label": "Hestia — Every-Other-Hour Health Checks",
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": 120,
    },
    "demeter_watcher": {
        "label": "Demeter — File Watcher",
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": 120,
    },
    "the_fates": {
        "label": "The Fates — Heartbeat Monitor",
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": 5,
    },
}


# ── Read / Write ──────────────────────────────────────────────────────


def _read_raw() -> dict[str, Any]:
    """Read the heartbeat file. Returns empty dict if missing or corrupt."""
    if not HEARTBEAT_PATH.exists():
        return {}
    try:
        raw = HEARTBEAT_PATH.read_text(encoding="utf-8")
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, Exception):
        logger.warning("Corrupt heartbeat file — starting fresh")
        return {}


def _write_raw(data: dict[str, Any]) -> None:
    """Atomically write the heartbeat file."""
    _PANTHEON_DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(data, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.rename(HEARTBEAT_PATH)  # atomic on same filesystem


def initialise() -> None:
    """Create or reset the heartbeat file with all default entries."""
    existing = _read_raw()
    # Merge defaults in, preserving existing timestamps
    for sid, default in DEFAULT_HEARTBEATS.items():
        if sid not in existing:
            existing[sid] = default
        else:
            # Ensure all keys exist even if we added new fields
            for k, v in default.items():
                existing[sid].setdefault(k, v)
    _write_raw(existing)
    logger.info("Heartbeat file initialised at %s", HEARTBEAT_PATH)


def beat(subsystem_id: str, error: Optional[str] = None) -> None:
    """Record a heartbeat for a subsystem.

    Args:
        subsystem_id: One of the keys in DEFAULT_HEARTBEATS (or a custom id).
        error: If set, records this as the last error. Omit to record success.
    """
    now = datetime.now(timezone.utc).isoformat()
    data = _read_raw()

    if subsystem_id not in data:
        # Auto-register if it's a new subsystem
        data[subsystem_id] = {
            "label": subsystem_id.replace("_", " ").title(),
            "last_ok": None,
            "last_error": None,
            "expected_interval_min": 1440,  # default: daily
        }

    if error:
        data[subsystem_id]["last_error"] = now
    else:
        data[subsystem_id]["last_ok"] = now
        data[subsystem_id]["last_error"] = None

    _write_raw(data)
    status = "ERROR" if error else "OK"
    logger.debug("Heartbeat %s for %s", status, subsystem_id)


def check_stale(max_staleness_min: Optional[int] = None) -> list[dict[str, Any]]:
    """Check all heartbeats and return list of stale subsystems.

    Args:
        max_staleness_min: Override staleness threshold. If None, uses each
                           subsystem's own expected_interval_min.

    Returns:
        List of dicts: {subsystem_id, label, last_ok, staleness_min, expected_interval_min}
    """
    data = _read_raw()
    now = datetime.now(timezone.utc)
    stale = []

    for sid, info in data.items():
        # Skip if never reported (use last_error as marker too)
        last_ok_str = info.get("last_ok")
        last_error_str = info.get("last_error")
        interval = info.get("expected_interval_min", 1440)

        # Determine the latest timestamp from this subsystem
        latest_str = last_ok_str or last_error_str
        if latest_str is None:
            # Never checked in — mark as stale immediately
            stale.append({
                "subsystem_id": sid,
                "label": info.get("label", sid),
                "last_ok": last_ok_str,
                "last_error": last_error_str,
                "staleness_min": None,
                "expected_interval_min": interval,
                "reason": "never_reported",
            })
            continue

        latest_dt = datetime.fromisoformat(latest_str)
        elapsed_min = (now - latest_dt).total_seconds() / 60.0

        threshold = max_staleness_min if max_staleness_min is not None else interval

        if elapsed_min > threshold:
            stale.append({
                "subsystem_id": sid,
                "label": info.get("label", sid),
                "last_ok": last_ok_str,
                "last_error": last_error_str,
                "staleness_min": round(elapsed_min, 1),
                "expected_interval_min": interval,
                "reason": "stale" if elapsed_min > interval else "missed_window",
            })

    return stale


def get_all() -> dict[str, Any]:
    """Return the full heartbeat state, merging with defaults if needed."""
    data = _read_raw()
    for sid, default in DEFAULT_HEARTBEATS.items():
        if sid not in data:
            data[sid] = default
    return data


def register_subsystem(
    subsystem_id: str,
    label: str,
    expected_interval_min: int,
) -> None:
    """Register a new subsystem for heartbeat tracking.

    Call this during god creation to ensure the new service is tracked
    from the start.
    """
    data = _read_raw()
    data[subsystem_id] = {
        "label": label,
        "last_ok": None,
        "last_error": None,
        "expected_interval_min": expected_interval_min,
    }
    _write_raw(data)
    logger.info(
        "Registered heartbeat for %s (%s, every %d min)",
        subsystem_id, label, expected_interval_min,
    )


# ── CLI ───────────────────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Pantheon Heartbeat Manager")
    parser.add_argument("action", choices=["init", "beat", "check", "status", "register"],
                        help="Action to perform")
    parser.add_argument("--subsystem", help="Subsystem ID (for beat, register)")
    parser.add_argument("--label", help="Human label (for register)")
    parser.add_argument("--interval", type=int, default=1440,
                        help="Expected interval in minutes (for register)")
    parser.add_argument("--error", help="Error message (for beat)")
    parser.add_argument("--max-staleness", type=int, default=None,
                        help="Override max staleness in minutes (for check)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.action == "init":
        initialise()
        print(f"Heartbeat file initialised at {HEARTBEAT_PATH}")
        for sid, info in DEFAULT_HEARTBEATS.items():
            print(f"  {sid}: {info['label']} (every {info['expected_interval_min']} min)")

    elif args.action == "beat":
        if not args.subsystem:
            print("ERROR: --subsystem is required for beat")
            return
        beat(args.subsystem, error=args.error)
        status = "ERROR" if args.error else "OK"
        print(f"  {args.subsystem}: {status}")

    elif args.action == "check":
        stale = check_stale(max_staleness_min=args.max_staleness)
        if not stale:
            print("✅ All subsystems healthy")
        else:
            print(f"⚠️  {len(stale)} stale subsystem(s):")
            for s in stale:
                reason = s.get("reason", "stale")
                mins = s.get("staleness_min", "?")
                print(f"  ❌ {s['label']} ({s['subsystem_id']})")
                print(f"     Reason: {reason} | Last OK: {s.get('last_ok', 'never')} | "
                      f"Stale for: {mins} min | Expected: {s['expected_interval_min']} min")

    elif args.action == "status":
        data = get_all()
        now = datetime.now(timezone.utc)
        print(f"Heartbeat file: {HEARTBEAT_PATH}")
        print()
        for sid, info in sorted(data.items()):
            ok = info.get("last_ok")
            err = info.get("last_error")
            interval = info.get("expected_interval_min", "?")
            status = "❌ Never" if ok is None and err is None else \
                     "✅ OK" if ok else "⚠️  Error"
            print(f"  {status} {info.get('label', sid)}")
            print(f"     ID: {sid} | Interval: {interval} min")
            if ok:
                dt = datetime.fromisoformat(ok)
                ago = (now - dt).total_seconds() / 60
                print(f"     Last OK: {ok} ({round(ago)} min ago)")
            if err:
                print(f"     Last Error: {err}")

    elif args.action == "register":
        if not args.subsystem or not args.label:
            print("ERROR: --subsystem and --label are required for register")
            return
        register_subsystem(args.subsystem, args.label, args.interval)
        print(f"  Registered {args.subsystem}: {args.label} (every {args.interval} min)")


if __name__ == "__main__":
    main()
