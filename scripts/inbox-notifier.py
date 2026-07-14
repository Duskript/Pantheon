#!/usr/bin/env python3
"""Pantheon inbox notifier — subscribes to inbox.new.> and routes.

Second half of the inbox-watcher pipeline. The watcher (inotify)
publishes NATS messages when msg_*.json files land in any god's
inbox. This daemon subscribes to inbox.new.> and:

  1. Writes a per-god "pending notification" file at
     ~/.local/share/pantheon/inbox_notify/<god>.json
     Session-start hooks read this to know "you have mail."

  2. Appends a high-priority flag if the message priority is high,
     so the next session that wakes up displays it prominently.

Why this exists:
    The watcher turns "inbox is silent" into "inbox is loud."
    The notifier turns "loud inbox" into "the next session that
    wakes up MUST look." Together with the watcher, they close
    the loop on Konan's #1 complaint: messages piling up with
    nobody knowing.

Architecture:
    inbox-watcher.py (inotify -> NATS)  ->  inbox.new.<god>
                                              |
                                              v
                                       inbox-notifier.py
                                              |
                                              v
                              ~/.local/share/pantheon/inbox_notify/<god>.json
                              (read by session-start hooks)

Reliability:
    - Daemon; systemd-managed
    - nats-py handles reconnects (max_reconnect_attempts=-1)
    - File write is atomic via tmp+rename
    - No HTTP, no Discord dependency — works fully offline
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict

try:
    import nats
except ImportError:
    print("FATAL: nats-py not installed", file=sys.stderr)
    sys.exit(2)


LOG = logging.getLogger("inbox-notifier")

NATS_URL = os.environ.get("INBOX_NATS_URL", "nats://127.0.0.1:4222")
NOTIFY_DIR = Path(os.path.expanduser("~/.local/share/pantheon/inbox_notify"))

STATS: Dict[str, Any] = {
    "received": 0,
    "files_written": 0,
    "high_priority": 0,
    "errors": 0,
    "started_at": time.time(),
}


def ensure_dir() -> None:
    NOTIFY_DIR.mkdir(parents=True, exist_ok=True)


def write_notification_file(god: str, payload: dict) -> None:
    """Atomic write: tmp file -> rename.

    The session-start hook reads this and forces the god to look
    at the inbox before doing anything else. For high-priority
    messages, we additionally append a "high_priority" flag the
    hook can use to block harder.
    """
    path = NOTIFY_DIR / f"{god}.json"
    tmp = path.with_suffix(".json.tmp")
    data = {
        "god": god,
        "ts": time.time(),
        "received_at": payload.get("timestamp"),
        "from": payload.get("from"),
        "type": payload.get("type"),
        "priority": payload.get("priority", "normal"),
        "subject": payload.get("subject"),
        "msg_id": payload.get("msg_id"),
        "path": payload.get("path"),
    }
    tmp.write_text(json.dumps(data, indent=2, default=str))
    tmp.rename(path)
    STATS["files_written"] += 1
    if payload.get("priority") == "high":
        STATS["high_priority"] += 1
    LOG.info(
        f"notif: {god} <- {payload.get('from')}: "
        f"{payload.get('subject', '')[:60]} [{payload.get('priority', 'normal')}]"
    )


async def message_handler(msg) -> None:
    STATS["received"] += 1
    try:
        payload = json.loads(msg.data.decode("utf-8"))
    except Exception as e:
        LOG.error(f"bad payload on {msg.subject}: {e}")
        STATS["errors"] += 1
        return
    god = payload.get("god")
    if not god:
        LOG.warning(f"no god in payload: {msg.subject}")
        return
    try:
        write_notification_file(god, payload)
    except Exception as e:
        LOG.error(f"file write failed for {god}: {e}")
        STATS["errors"] += 1


async def run_forever(stop_event: asyncio.Event) -> None:
    """Connect to NATS, subscribe, stay alive. nats-py handles reconnects.

    Previous bug: was checking nc._close_event (doesn't exist) which
    caused a 1Hz reconnect storm. Fixed.
    """
    ensure_dir()

    async def _connect_and_serve() -> None:
        nc = await nats.connect(
            NATS_URL,
            connect_timeout=5,
            max_reconnect_attempts=-1,
            reconnect_time_wait=2,
        )
        LOG.info(f"connected to NATS at {NATS_URL}")
        sub = await nc.subscribe("inbox.new.>", cb=message_handler)
        LOG.info("subscribed to inbox.new.>")
        await stop_event.wait()
        LOG.info("stop event set, draining NATS")
        try:
            await sub.unsubscribe()
            await nc.drain()
        except Exception as e:
            LOG.warning(f"shutdown error: {e}")

    while not stop_event.is_set():
        try:
            await _connect_and_serve()
        except Exception as e:
            LOG.error(f"NATS error: {e}, reconnecting in 3s")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=3)
            except asyncio.TimeoutError:
                pass
    LOG.info(f"notifier stopped. stats: {STATS}")


def install_signal_handlers(loop, stop_event):
    def _stop():
        loop.call_soon_threadsafe(stop_event.set)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: _stop())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    stop = asyncio.Event()
    install_signal_handlers(loop, stop)
    try:
        loop.run_until_complete(run_forever(stop))
    finally:
        loop.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
