#!/usr/bin/env python3
"""
Pantheon Sync Scheduler — 20-minute cron sync loop (T11).

Walks active connections, checks sync state, and calls adapters.
Adapters are stubs for now; real adapters arrive in T12.

Usage:
    python sync_scheduler.py               # single tick (cron mode)
    python sync_scheduler.py --loop        # run continuously, sleep 20 min
    python sync_scheduler.py --loop --interval 600   # 10-min loop

Cron line (documented, NOT installed by this script):
    */20 * * * * cd ~/.hermes/cron/pantheon-sync && python3 sync_scheduler.py

Commit message: feat(sync): 20-min cron scheduler
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List

from sync_state import SyncState

# ---------------------------------------------------------------------------
# Import adapter framework (T12) — auto-registers Gmail, GitHub, Slack adapters
# ---------------------------------------------------------------------------

from adapters import get_adapter, list_adapters  # noqa: E402

# ---------------------------------------------------------------------------
# Paths — everything lives under ~/.hermes/cron/pantheon-sync/
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CONNECTIONS_FILE = BASE_DIR / "connections.json"
SCAN_LOG = BASE_DIR / "scan.log"
STATE_FILE = BASE_DIR / "sync_state.json"

# ---------------------------------------------------------------------------
# Logging — file (scan.log) + stderr (for cron capture)
# ---------------------------------------------------------------------------


def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("pantheon-sync")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler — every tick written to scan.log
    fh = logging.FileHandler(str(SCAN_LOG))
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Stream handler — INFO and above to stderr so cron / manual runs see it
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.INFO)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    return logger


log = _setup_logging()

# ---------------------------------------------------------------------------
# Adapter stubs (T12 will register real adapters here)
# ---------------------------------------------------------------------------


def _resolve_adapter(connection: dict) -> Any:
    """Resolve an adapter callable for a connection.

    Returns a callable matching the legacy API: (conn, state) → dict.
    """
    provider = connection.get("provider")

    # New T12 adapters (provider-based)
    if provider and provider in list_adapters():
        adapter = get_adapter(provider)

        def _bridge(conn: dict, _state: SyncState) -> dict:
            result = adapter.sync()
            return {
                "synced": len(result.records),
                "cursor": result.next_cursor,
                "status": result.status,
                "records": result.records,
            }

        return _bridge

    # Legacy adapter name lookup
    adapter_name = connection.get("adapter", "")
    if adapter_name in ADAPTER_REGISTRY:
        return ADAPTER_REGISTRY[adapter_name]

    return _stub_sync


def _stub_sync(connection: dict, _state: SyncState) -> dict:
    """Log intent and return a placeholder result."""
    provider = connection.get("provider", "unknown")
    conn_id = connection["id"]
    log.info("would sync %s (connection=%s)", provider, conn_id)
    return {"synced": 0, "cursor": None, "status": "ok"}


# Map adapter name → callable.  Legacy — prefer 'provider' field in connections.
ADAPTER_REGISTRY: Dict[str, Callable] = {}

# ---------------------------------------------------------------------------
# Connection loading
# ---------------------------------------------------------------------------


def load_connections() -> List[dict]:
    """Load active (enabled) connections from connections.json.

    Creates a minimal default file if none exists so the scheduler is
    always runnable out of the box.
    """
    if not CONNECTIONS_FILE.exists():
        log.warning(
            "connections.json not found at %s — creating default stub",
            CONNECTIONS_FILE,
        )
        default = {
            "_note": "Auto-created default. Edit for real connections.",
            "connections": [
                {
                    "id": "default-stub",
                    "provider": "stub",
                    "adapter": "stub_adapter",
                    "enabled": True,
                    "sync_interval_minutes": 20,
                    "daily_budget": 1000,
                }
            ],
        }
        CONNECTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CONNECTIONS_FILE, "w") as fh:
            json.dump(default, fh, indent=2)
        return default["connections"]

    with open(CONNECTIONS_FILE) as fh:
        data = json.load(fh)

    all_conns = data.get("connections", [])
    return [c for c in all_conns if c.get("enabled", True)]


# ---------------------------------------------------------------------------
# Sync logic
# ---------------------------------------------------------------------------


def _should_sync(connection: dict, state: SyncState) -> tuple[bool, str]:
    """Decide whether *connection* is ready for a sync tick.

    Returns (do_sync, reason).
    """
    conn_id = connection["id"]

    # 1. Daily budget reset
    state.reset_daily_if_needed(conn_id)

    # 2. Honor the connection's daily budget (set it in state so
    #    is_over_budget uses the right cap)
    budget = connection.get("daily_budget", 1000)
    state.set_daily_budget(conn_id, budget)

    # 3. Interval check
    interval = connection.get("sync_interval_minutes", 20)
    if not state.is_due(conn_id, interval):
        return False, "not due yet"

    # 4. Budget check
    if state.is_over_budget(conn_id):
        return False, "over daily budget"

    return True, "ready"


def run_sync_tick() -> int:
    """Execute one full sync tick — iterate all active connections.

    Returns the number of connections that were actually synced (for
    callers that want to know if anything happened).
    """
    tick_start = datetime.now()
    log.info("=== Sync tick started  %s ===", tick_start.isoformat())

    # --- Load connections ---------------------------------------------------
    try:
        connections = load_connections()
    except Exception:
        log.exception("Failed to load connections — aborting tick")
        return 0

    if not connections:
        log.info("No active connections — nothing to sync.")
        return 0

    # --- Init state ---------------------------------------------------------
    state = SyncState(str(STATE_FILE))

    n_synced = 0
    n_skipped = 0
    n_errors = 0

    for conn in connections:
        conn_id = conn.get("id", "<unknown>")

        try:
            do_sync, reason = _should_sync(conn, state)

            if not do_sync:
                log.debug("SKIP  %-24s  %s", conn_id, reason)
                n_skipped += 1
                continue

            # --- Call adapter -------------------------------------------------
            adapter = _resolve_adapter(conn)

            result = adapter(conn, state)

            synced = result.get("synced", 0)
            cursor = result.get("cursor")
            state.record_sync(conn_id, synced, cursor)
            log.info(
                "SYNC  %-24s  synced=%-4d  status=%s",
                conn_id,
                synced,
                result.get("status", "ok"),
            )
            n_synced += 1

        except Exception:
            log.exception("ERROR syncing %s", conn_id)
            n_errors += 1

    elapsed = (datetime.now() - tick_start).total_seconds()
    log.info(
        "=== Sync tick complete  synced=%d  skipped=%d  errors=%d  elapsed=%.1fs ===",
        n_synced,
        n_skipped,
        n_errors,
        elapsed,
    )

    return n_synced


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pantheon Sync Scheduler — 20-min cron sync loop (T11)"
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously, sleeping between ticks.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=1200,
        metavar="SECONDS",
        help="Sleep interval for --loop mode (default: 1200 = 20 min).",
    )
    args = parser.parse_args()

    log.info("Pantheon Sync Scheduler starting  (loop=%s)", args.loop)

    if args.loop:
        log.info(
            "Continuous loop mode — sleeping %ds (%d min) between ticks",
            args.interval,
            args.interval // 60,
        )
        try:
            while True:
                run_sync_tick()
                log.info("Sleeping %ds …", args.interval)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log.info("Sync scheduler stopped by user (KeyboardInterrupt)")
    else:
        run_sync_tick()


if __name__ == "__main__":
    main()
