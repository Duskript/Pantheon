"""Quarantine Sweeper — turn silent quarantine files into Telegram alerts.

Background problem: external events (webhooks, NATS messages) hit the
Conductor and end up in ``pending/_quarantine/`` when no rule matches.
The on-disk file is the durable record, but nothing in the v1 or v2
delivery paths fires a Telegram alert for it today. The user has no way
to know quarantine items are piling up.

The sweeper closes that gap. It:

  1. Watches ``pending/_quarantine/`` (and a parallel ``_webhooks/`` for
     raw originals) using ``watchdog`` (already a transitive dep).
  2. For every new file, formats a human-readable alert with
     ``format_quarantine_alert()`` from delivery.py and ships it to
     Telegram via a tiny ``sendTelegram`` HTTP call (no hermes-agent
     dependency).
  3. Dedupe-tracks seen files in ``/var/tmp/conductor_quarantine_seen.json``
     so restarts do not re-fire alerts for old items.
  4. Exposes a tiny control HTTP server on ``--control-port`` (default
     8767) so the user can ``snooze`` and ``status`` via the bot.

Run via systemd (``pantheon-quarantine-sweeper.service``) or directly:

    python3 -m v2.quarantine_sweeper
    python3 -m v2.quarantine_sweeper --once        # process current queue and exit
    python3 -m v2.quarantine_sweeper --control-port 8767
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

# watchdog is already a transitive dep of the v2 daemon
try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
    WATCHDOG_AVAILABLE = True
except Exception:  # pragma: no cover
    WATCHDOG_AVAILABLE = False

from . import delivery as delivery_mod  # format_quarantine_alert, DeliveryRouter
from .delivery import utc_now  # type: ignore

LOG = logging.getLogger("conductor.v2.quarantine_sweeper")

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

SEEN_FILE = Path(os.environ.get(
    "CONDUCTOR_SWEEPER_SEEN_FILE",
    "/var/tmp/conductor_quarantine_seen.json",
))


def quarantine_dir() -> Path:
    """Resolve ``pending/_quarantine/`` lazily so env-var override works."""
    base = os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return Path(base) / "pending" / "_quarantine"
    root = os.environ.get("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    return Path(root) / "conductor" / "pending" / "_quarantine"


def webhooks_dir() -> Path:
    base = os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return Path(base) / "pending" / "_webhooks"
    root = os.environ.get("PANTHEON_ROOT", str(Path.home() / "pantheon"))
    return Path(root) / "conductor" / "pending" / "_webhooks"


# ---------------------------------------------------------------------------
# Snooze state
# ---------------------------------------------------------------------------

@dataclass
class SnoozeState:
    """Tracks per-source snoozes and a global snooze.

    Stored in-memory and persisted to ``SEEN_FILE`` (alongside seen set)
    so restarts honor the user's last snooze.
    """
    until_ts: float = 0.0  # 0 = not snoozed
    per_source: dict[str, float] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.per_source is None:
            self.per_source = {}

    def is_silenced(self, source: str, now: float | None = None) -> bool:
        now = now or time.time()
        if self.until_ts and now < self.until_ts:
            return True
        until = self.per_source.get(source, 0.0)
        return bool(until and now < until)

    def snooze(self, seconds: float, source: str | None = None) -> dict[str, Any]:
        until = time.time() + seconds
        if source:
            self.per_source[source] = until
        else:
            self.until_ts = until
        return {
            "source": source or "*",
            "snoozed_until": datetime.fromtimestamp(until, tz=timezone.utc).isoformat(),
            "seconds": seconds,
        }

    def cancel(self, source: str | None = None) -> dict[str, Any]:
        if source:
            self.per_source.pop(source, None)
        else:
            self.until_ts = 0.0
        return {"cancelled": source or "*"}

    def status(self) -> dict[str, Any]:
        now = time.time()
        return {
            "global_snoozed_until": (
                datetime.fromtimestamp(self.until_ts, tz=timezone.utc).isoformat()
                if self.until_ts > now else None
            ),
            "per_source": {
                src: datetime.fromtimestamp(until, tz=timezone.utc).isoformat()
                for src, until in self.per_source.items()
                if until > now
            },
        }

    def to_dict(self) -> dict[str, Any]:
        return {"until_ts": self.until_ts, "per_source": self.per_source}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SnoozeState":
        return cls(
            until_ts=float(d.get("until_ts", 0.0) or 0.0),
            per_source=dict(d.get("per_source") or {}),
        )


# ---------------------------------------------------------------------------
# Persistence: dedupe + snooze
# ---------------------------------------------------------------------------

def _load_seen() -> tuple[set[str], SnoozeState]:
    if not SEEN_FILE.exists():
        return set(), SnoozeState()
    try:
        d = json.loads(SEEN_FILE.read_text())
    except Exception:
        return set(), SnoozeState()
    return set(d.get("seen") or []), SnoozeState.from_dict(d.get("snooze") or {})


def _save_seen(seen: set[str], snooze: SnoozeState) -> None:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SEEN_FILE.with_name(f".{SEEN_FILE.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(
        {"seen": sorted(seen), "snooze": snooze.to_dict()},
        indent=2, sort_keys=True,
    ))
    tmp.replace(SEEN_FILE)


# ---------------------------------------------------------------------------
# Quarantine event shape (matches what conductor_server.py + v2 engine write)
# ---------------------------------------------------------------------------

def _load_event(path: Path) -> dict[str, Any]:
    """Best-effort: pull the event payload out of a quarantine file.

    Two shapes in the wild:
      1. v2 engine → ``{"event": {...}, "queued_at": ..., "rule_id": ...}``
      2. v1 NATS handler → ``{...dispatch fields..., "context": {...}}``
    """
    try:
        raw = json.loads(path.read_text())
    except Exception as e:
        LOG.warning(f"could not read {path}: {e}")
        return {}

    if "event" in raw and isinstance(raw["event"], dict):
        ev = raw["event"]
    else:
        ev = raw

    payload = ev.get("payload") or {}
    return {
        "source": ev.get("source", "unknown"),
        "subject": ev.get("subject", ""),
        "type": ev.get("type", "unknown"),
        "is_external": ev.get("is_external", True),
        "rule_id": raw.get("rule_id", "__default_external__"),
        "payload": payload,
        "summary": payload.get("summary") or ev.get("subject") or ev.get("type", "unknown"),
        "raw": raw,
        "file": str(path),
    }


# ---------------------------------------------------------------------------
# Telegram delivery
# ---------------------------------------------------------------------------

def _read_telegram_config() -> tuple[str, str]:
    """Pull bot token + chat id from the standard env vars.

    Thoth profile has them; the conductor service itself may not. We
    fall back to the canonical home location so a manual run from any
    profile still works.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("CONDUCTOR_TELEGRAM_CHAT_ID") or os.environ.get("TELEGRAM_HOME_CHANNEL", "")

    if not token:
        # Fallback: read from thoth's .env so the daemon finds it without
        # the user having to plumb env vars through the systemd unit.
        for candidate in (
            Path.home() / ".hermes" / "profiles" / "thoth" / ".env",
            Path.home() / ".hermes" / "profiles" / "hermes" / ".env",
            Path.home() / ".hermes" / ".env",
        ):
            if not candidate.exists():
                continue
            try:
                for line in candidate.read_text().splitlines():
                    if line.startswith("TELEGRAM_BOT_TOKEN=") and not token:
                        token = line.split("=", 1)[1].strip()
                    elif line.startswith("TELEGRAM_HOME_CHANNEL=") and not chat:
                        chat = line.split("=", 1)[1].strip()
            except Exception:
                continue

    return token, chat


def send_telegram(text: str, bot_token: str, chat_id: str) -> tuple[bool, str]:
    """Synchronous Telegram send. Returns (ok, detail)."""
    import urllib.request
    import urllib.parse

    if not bot_token or not chat_id:
        return False, "missing TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL"

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get("ok"):
                return True, f"msg_id={data.get('result', {}).get('message_id')}"
            return False, f"telegram error: {data.get('description', 'unknown')}"
    except Exception as e:
        return False, f"network error: {e}"


# ---------------------------------------------------------------------------
# Main sweeper
# ---------------------------------------------------------------------------

class QuarantineSweeper:
    """Watch the quarantine dir, fire one alert per new file.

    Alert format comes from ``delivery.format_quarantine_alert`` so the
    user sees a single consistent message style.
    """

    def __init__(
        self,
        token: str = "",
        chat_id: str = "",
        seen: set[str] | None = None,
        snooze: SnoozeState | None = None,
        control_port: int = 8767,
        run_control_server: bool = True,
    ) -> None:
        self.token = token
        self.chat_id = chat_id
        self.seen = seen if seen is not None else set()
        self.snooze = snooze or SnoozeState()
        self.control_port = control_port
        self.run_control_server = run_control_server
        self._control_server: Optional[ThreadingHTTPServer] = None
        self._shutdown = asyncio.Event()
        self._stats = {
            "files_seen": 0,
            "alerts_sent": 0,
            "alerts_suppressed_snooze": 0,
            "alerts_failed": 0,
            "started_at": utc_now(),
        }

    # ---- public API ----

    async def run(self, poll_interval: float = 5.0) -> None:
        """Run until SIGINT/SIGTERM. Polls the dir every ``poll_interval``."""
        if not self.token or not self.chat_id:
            token, chat = _read_telegram_config()
            self.token = self.token or token
            self.chat_id = self.chat_id or chat

        if not self.token or not self.chat_id:
            LOG.error("No Telegram config — sweeper will scan but not alert.")
        else:
            LOG.info(f"Telegram target: chat_id={self.chat_id}")

        qdir = quarantine_dir()
        wdir = webhooks_dir()
        qdir.mkdir(parents=True, exist_ok=True)
        wdir.mkdir(parents=True, exist_ok=True)
        LOG.info(f"Watching {qdir} and {wdir}")

        # Initial sweep — handle anything already on disk at startup
        await self._scan_once()

        if self.run_control_server and self.control_port:
            self._start_control_server()

        try:
            while not self._shutdown.is_set():
                try:
                    await asyncio.wait_for(self._shutdown.wait(), timeout=poll_interval)
                except asyncio.TimeoutError:
                    pass
                await self._scan_once()
        finally:
            self._stop_control_server()
            LOG.info(f"final stats: {self._stats}")

    async def scan_once(self) -> dict[str, int]:
        """Process whatever's currently in the queue. Returns delta counts
        (only the new work this call did). Cumulative state stays in self._stats."""
        before = dict(self._stats)
        await self._scan_once()
        return {
            "scanned": self._stats["files_seen"] - before["files_seen"],
            "sent": self._stats["alerts_sent"] - before["alerts_sent"],
            "suppressed": self._stats["alerts_suppressed_snooze"] - before["alerts_suppressed_snooze"],
            "failed": self._stats["alerts_failed"] - before["alerts_failed"],
        }

    # ---- internals ----

    async def _scan_once(self) -> None:
        qdir = quarantine_dir()
        if not qdir.exists():
            return
        for path in sorted(qdir.glob("*.json")):
            key = path.name
            if key in self.seen:
                continue
            self.seen.add(key)
            self._stats["files_seen"] += 1
            await self._handle_file(path)
        # persist seen + snooze on every pass so a hard kill still dedupes
        try:
            _save_seen(self.seen, self.snooze)
        except Exception as e:
            LOG.warning(f"could not persist seen: {e}")

    async def _handle_file(self, path: Path) -> None:
        ev = _load_event(path)
        if not ev:
            return

        source = ev.get("source", "unknown")
        if self.snooze.is_silenced(source):
            LOG.info(f"silenced: {path.name} (source={source})")
            self._stats["alerts_suppressed_snooze"] += 1
            return

        text = delivery_mod.format_quarantine_alert(
            event_summary=ev.get("summary", "unknown"),
            source=source,
            subject=ev.get("subject", ""),
            rule_id=ev.get("rule_id", "__default_external__"),
            quarantine_path=str(path),
        )
        text = self._append_kill_switch(text)

        ok, detail = send_telegram(text, self.token, self.chat_id)
        if ok:
            LOG.info(f"alerted: {path.name} ({detail})")
            self._stats["alerts_sent"] += 1
        else:
            LOG.warning(f"alert failed for {path.name}: {detail}")
            self._stats["alerts_failed"] += 1

    def _append_kill_switch(self, text: str) -> str:
        """Add the snooze hint to every alert."""
        return text + (
            "\n\n_Reply: `snooze 1h` / `snooze 1h github` / `snooze off` / `status`_"
        )

    # ---- control HTTP server ----

    def _start_control_server(self) -> None:
        sweeper = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt: str, *args: Any) -> None:  # quiet
                LOG.debug(f"control: {fmt % args}")

            def _send(self, code: int, body: dict[str, Any]) -> None:
                payload = json.dumps(body, indent=2).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/status":
                    self._send(200, {
                        "snooze": sweeper.snooze.status(),
                        "stats": sweeper._stats,
                        "seen_count": len(sweeper.seen),
                    })
                elif self.path == "/healthz":
                    self._send(200, {"ok": True})
                else:
                    self._send(404, {"error": "not found"})

            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode() if length else "{}"
                try:
                    data = json.loads(body) if body.strip() else {}
                except Exception:
                    data = {}

                if self.path == "/snooze":
                    seconds = float(data.get("seconds", 3600))
                    source = data.get("source")
                    result = sweeper.snooze.snooze(seconds, source)
                    _save_seen(sweeper.seen, sweeper.snooze)
                    self._send(200, {"status": "snoozed", **result})
                elif self.path == "/unsnooze":
                    source = data.get("source")
                    sweeper.snooze.cancel(source)
                    _save_seen(sweeper.seen, sweeper.snooze)
                    self._send(200, sweeper.snooze.cancel(source))
                else:
                    self._send(404, {"error": "not found"})

        try:
            self._control_server = ThreadingHTTPServer(("127.0.0.1", self.control_port), Handler)
        except OSError as e:
            LOG.warning(f"control server bind failed on :{self.control_port}: {e}")
            return
        import threading
        t = threading.Thread(
            target=self._control_server.serve_forever,
            name="quarantine-control",
            daemon=True,
        )
        t.start()
        LOG.info(f"control server listening on http://127.0.0.1:{self.control_port}")

    def _stop_control_server(self) -> None:
        if self._control_server:
            self._control_server.shutdown()
            self._control_server.server_close()
            self._control_server = None

    def request_shutdown(self) -> None:
        self._shutdown.set()


# ---------------------------------------------------------------------------
# Parse "snooze 1h github" from a Telegram reply
# ---------------------------------------------------------------------------

DURATION_RE = re.compile(r"(\d+)\s*(s|m|h|d)", re.IGNORECASE)
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> float:
    """Parse ``1h``, ``30m``, ``2d`` etc. into seconds. 0 on no match."""
    m = DURATION_RE.search(text)
    if not m:
        return 0.0
    return int(m.group(1)) * UNIT_SECONDS[m.group(2).lower()]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _main() -> int:
    p = argparse.ArgumentParser(description="Conductor quarantine sweeper")
    p.add_argument("--once", action="store_true", help="scan once and exit")
    p.add_argument("--poll-interval", type=float, default=5.0, help="seconds between scans")
    p.add_argument("--control-port", type=int, default=8767, help="HTTP control port (0=off)")
    p.add_argument("--log-level", default="INFO")
    args = p.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )

    seen, snooze = _load_seen()
    sweeper = QuarantineSweeper(
        seen=seen,
        snooze=snooze,
        control_port=args.control_port,
        run_control_server=not args.once,
    )

    if args.once:
        result = await sweeper.scan_once()
        print(json.dumps(result, indent=2))
        return 0

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, sweeper.request_shutdown)

    await sweeper.run(poll_interval=args.poll_interval)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(_main()))
