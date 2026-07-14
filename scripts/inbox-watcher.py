#!/usr/bin/env python3
"""Pantheon inbox watcher.

Watches ~/pantheon/gods/messages/<god>/ for new msg_*.json files.
When one appears, reads the file, publishes a notification to the
local NATS bus on subject `inbox.new.<god>` so any subscribed god
session (or the Conductor) can react in real time.

Architecture:
    filesystem event  ->  watchgod callback  ->  parse msg JSON
                                              ->  async NATS publish
                                              ->  log

Why this exists:
    Before this, god inboxes were write-only. Messages accumulated
    silently; gods only saw them at the *next* session start. Konan's
    standing complaint: "nobody reads the inbox." This daemon makes
    the inbox push, not pull.

Subject schema:
    inbox.new.<god_name>           # new message arrived
    inbox.test                     # synthetic ping for health checks

Payload:
    {"event": "new", "god": "<god>", "msg_id": "...", "from": "...",
     "type": "...", "priority": "...", "subject": "...", "path": "...",
     "timestamp": "..."}

Reliability:
    - Local NATS at 127.0.0.1:4222, no auth (single-host bus)
    - Reconnect handled by nats-py
    - Files that don't exist anymore at publish time are skipped
      (race-safe: read happens immediately after the event)
    - Daemon never blocks filesystem: < 1ms per event

Run:
    python3 -m scripts.inbox-watcher            # default: watch all gods
    python3 -m scripts.inbox-watcher --ping     # publish test + exit
    python3 -m scripts.inbox-watcher --health   # print stats + exit
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
from typing import Any, Dict, Optional

try:
    import nats
except ImportError:
    print("FATAL: nats-py not installed. pip install nats-py", file=sys.stderr)
    sys.exit(2)

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

LOG = logging.getLogger("inbox-watcher")

MESSAGES_ROOT = Path(os.path.expanduser("~/pantheon/gods/messages"))
NATS_URL = os.environ.get("INBOX_NATS_URL", "nats://127.0.0.1:4222")
SUBJECT_NEW = "inbox.new"
SUBJECT_TEST = "inbox.test"

# Stats
STATS: Dict[str, int] = {
    "events": 0,
    "published": 0,
    "errors": 0,
    "started_at": time.time(),
}


class InboxPublisher:
    """Async NATS publisher with reconnect-on-failure semantics."""

    def __init__(self, url: str = NATS_URL) -> None:
        self.url = url
        self._nc: Any = None
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._nc and self._nc.is_connected:
            return
        try:
            self._nc = await nats.connect(self.url, connect_timeout=5, max_reconnect_attempts=-1)
            LOG.info(f"connected to NATS at {self.url}")
        except Exception as e:
            LOG.warning(f"NATS connect failed: {e} — will retry on next publish")
            self._nc = None

    async def publish(self, subject: str, payload: dict) -> bool:
        async with self._lock:
            if not self._nc or not self._nc.is_connected:
                await self.connect()
            if not self._nc or not self._nc.is_connected:
                STATS["errors"] += 1
                return False
            try:
                body = json.dumps(payload, default=str).encode("utf-8")
                await self._nc.publish(subject, body)
                await self._nc.flush()
                STATS["published"] += 1
                return True
            except Exception as e:
                LOG.error(f"publish failed on {subject}: {e}")
                STATS["errors"] += 1
                self._nc = None
                return False

    async def close(self) -> None:
        if self._nc:
            try:
                await self._nc.drain()
            except Exception:
                pass
            self._nc = None


def parse_message(path: Path) -> Optional[dict]:
    """Read a message file and return its parsed contents, or None on failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError, IOError) as e:
        LOG.warning(f"could not parse {path}: {e}")
        return None


class InboxEventHandler(FileSystemEventHandler):
    """Reacts to new msg_*.json files in any god's inbox dir."""

    def __init__(self, publisher: InboxPublisher, loop: asyncio.AbstractEventLoop) -> None:
        self.publisher = publisher
        self.loop = loop
        # Dedupe: watchdog fires multiple events for one file create
        # (created, modified, etc.). Track what we've already published.
        self._seen: Dict[str, float] = {}
        self._seen_ttl = 5.0  # seconds

    def _extract_god(self, path: str) -> Optional[str]:
        """Given /home/konan/pantheon/gods/messages/<god>/msg_X.json,
        return <god> or None if not under a god's inbox."""
        p = Path(path).resolve()
        try:
            rel = p.relative_to(MESSAGES_ROOT.resolve())
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) < 2:
            return None
        return parts[0]

    def _is_msg_file(self, path: str) -> bool:
        name = Path(path).name
        return name.startswith("msg_") and name.endswith(".json")

    def _dedupe(self, path: str) -> bool:
        """Return True if we should process this event."""
        now = time.time()
        # GC old entries
        stale = [k for k, v in self._seen.items() if now - v > self._seen_ttl]
        for k in stale:
            del self._seen[k]
        if path in self._seen:
            return False
        self._seen[path] = now
        return True

    def on_created(self, event) -> None:
        if event.is_directory:
            return
        self._handle(event.src_path, "created")

    def on_moved(self, event) -> None:
        # Atomic writes: some apps write to tmp + rename. Catch both ends.
        if event.is_directory:
            return
        # destination is the final path
        dest = getattr(event, "dest_path", None) or event.src_path
        self._handle(dest, "moved")

    def _handle(self, path: str, kind: str) -> None:
        if not self._is_msg_file(path):
            return
        if not self._dedupe(path):
            return
        god = self._extract_god(path)
        if not god:
            return

        # Small sleep to let the writer flush the file. If they haven't
        # closed it, parse_message returns None and we skip.
        time.sleep(0.05)

        msg = parse_message(Path(path))
        if not msg:
            return

        payload = {
            "event": "new",
            "kind": kind,
            "god": god,
            "msg_id": msg.get("id", Path(path).stem),
            "from": msg.get("from", "unknown"),
            "type": msg.get("type", "unknown"),
            "priority": msg.get("priority", "normal"),
            "subject": msg.get("subject", ""),
            "path": path,
            "timestamp": msg.get("timestamp"),
        }
        subject = f"{SUBJECT_NEW}.{god}"
        STATS["events"] += 1
        LOG.info(f"[{kind}] {god} <- {payload['from']}: {payload['subject'][:60]}")
        # Schedule the publish on the asyncio loop (watchdog is sync)
        try:
            asyncio.run_coroutine_threadsafe(
                self.publisher.publish(subject, payload), self.loop
            )
        except Exception as e:
            LOG.error(f"could not schedule publish: {e}")
            STATS["errors"] += 1


def install_signal_handlers(loop: asyncio.AbstractEventLoop, stop_event: asyncio.Event) -> None:
    def _stop():
        LOG.info("signal received, shutting down")
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            # Windows fallback
            signal.signal(sig, lambda *_: _stop())


async def run_forever(stop_event: asyncio.Event) -> None:
    publisher = InboxPublisher()
    await publisher.connect()

    if not MESSAGES_ROOT.is_dir():
        LOG.error(f"messages root not found: {MESSAGES_ROOT}")
        sys.exit(1)

    # Build a handler and one observer per existing god inbox.
    # Subdirs created later are picked up by a polling sweep every 30s.
    loop = asyncio.get_running_loop()
    handler = InboxEventHandler(publisher, loop)
    observers = []

    def attach_observer(god_dir: Path) -> None:
        # recursive=False — we only care about msg_*.json directly in the inbox,
        # not in any sub-folders.
        obs = Observer()
        obs.schedule(handler, str(god_dir), recursive=False)
        obs.daemon = True
        obs.start()
        observers.append(obs)
        LOG.info(f"watching {god_dir}")

    # Initial attach for existing inboxes
    for god_dir in MESSAGES_ROOT.iterdir():
        if god_dir.is_dir() and not god_dir.name.startswith("."):
            attach_observer(god_dir)

    # Sweep for new inboxes every 30s
    async def sweep_inboxes():
        while not stop_event.is_set():
            try:
                for god_dir in MESSAGES_ROOT.iterdir():
                    if god_dir.is_dir() and not god_dir.name.startswith("."):
                        already = any(
                            o and any(god_dir in Path(w).parents for w in [str(p) for p in []])
                            for o in observers
                        )
                        if not already:
                            attach_observer(god_dir)
                            LOG.info(f"new inbox discovered: {god_dir.name}")
            except Exception as e:
                LOG.warning(f"sweep error: {e}")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    LOG.info(f"watcher running on {MESSAGES_ROOT} via {NATS_URL}")
    try:
        await stop_event.wait()
    finally:
        for obs in observers:
            try:
                obs.stop()
                obs.join(timeout=2)
            except Exception:
                pass
        await publisher.close()
        LOG.info(f"watcher stopped. stats: {STATS}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pantheon inbox watcher")
    parser.add_argument("--ping", action="store_true", help="publish a test message and exit")
    parser.add_argument("--health", action="store_true", help="print stats and exit")
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    if args.ping:
        async def _ping():
            p = InboxPublisher()
            await p.connect()
            ok = await p.publish(SUBJECT_TEST, {"event": "ping", "ts": time.time()})
            print(f"ping published={ok}")
            await p.close()
            return 0 if ok else 1
        return asyncio.run(_ping())

    if args.health:
        print(json.dumps(STATS, indent=2))
        return 0

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
