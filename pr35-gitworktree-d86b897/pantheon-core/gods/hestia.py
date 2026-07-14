"""Hestia — health check script for all Pantheon services.

Driver: script
Runs and exits, returning HealthStatus for each checked service.
Now includes heartbeat writing and can be run standalone or via cron.

Usage:
  python3 gods/hestia.py                      # Run all checks
  python3 gods/hestia.py --send-hermes        # Run + send report to Hermes
  python3 gods/hestia.py --heartbeat-only     # Just write heartbeat
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx

# Ensure scripts/ is on path so we can import heartbeat
_SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

_HEARTBEAT_AVAILABLE = False
try:
    from heartbeat import beat, initialise  # noqa: F401
    _HEARTBEAT_AVAILABLE = True
except ImportError:
    pass

# ── Paths ─────────────────────────────────────────────────────────────

_HOME = os.path.expanduser("~")
_REAL_HOME = os.environ.get("HERMES_REAL_HOME", _HOME)
if _REAL_HOME != _HOME and _REAL_HOME != os.path.join(_HOME, ".."):
    _HOME = _REAL_HOME
if ".hermes/profiles" in _HOME:
    _HOME = _HOME.split("/.hermes/profiles/")[0]

HERMES_INBOX = Path(f"{_HOME}/pantheon/gods/messages/hermes")


@dataclass
class HealthStatus:
    service: str
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class HestiaChecker:
    """Checks health of Pantheon service dependencies."""

    _TIMEOUT = 5.0  # seconds per check (bumped from 2.0 for MCP server)

    def check_ollama(self, host: str = "localhost", port: int = 11434) -> HealthStatus:
        return self._check_http("ollama", host, port, path="/")

    def check_chromadb(self, host: str = "localhost", port: int = 8000) -> HealthStatus:
        """Check ChromaDB via embedded PersistentClient (not HTTP — it's file-based)."""
        try:
            import chromadb
            t0 = time.monotonic()
            client = chromadb.PersistentClient(path=str(Path(f"{_HOME}/.hermes/pantheon/chroma")))
            client.heartbeat()
            # List collections to verify it's functional
            cols = client.list_collections()
            total_vecs = sum(c.count() for c in cols)
            latency_ms = (time.monotonic() - t0) * 1000.0
            return HealthStatus(
                service="chromadb",
                ok=True,
                latency_ms=round(latency_ms, 2),
                error=f"({len(cols)} collections, {total_vecs} vectors)" if total_vecs > 0 else None,
            )
        except Exception as exc:
            return HealthStatus(service="chromadb", ok=False, error=str(exc))

    def check_pantheon_api(self, host: str = "localhost", port: int = 8001) -> HealthStatus:
        return self._check_http("pantheon-api", host, port, path="/sanctuaries")

    def check_mcp_server(self, host: str = "localhost", port: int = 8010) -> HealthStatus:
        """Check Pantheon MCP server via initialize handshake."""
        url = f"http://{host}:{port}/mcp"
        try:
            t0 = time.monotonic()
            resp = httpx.post(
                url,
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
                        "clientInfo": {"name": "hestia", "version": "1.0.0"},
                    },
                    "id": 1,
                },
                timeout=self._TIMEOUT,
            )
            latency_ms = (time.monotonic() - t0) * 1000.0
            if resp.status_code == 200:
                return HealthStatus(
                    service="mcp-server", ok=True, latency_ms=round(latency_ms, 2),
                )
            return HealthStatus(
                service="mcp-server", ok=False,
                latency_ms=round(latency_ms, 2),
                error=f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return HealthStatus(service="mcp-server", ok=False, error=str(exc))

    def check_disk_space(self, path: str = "/home") -> HealthStatus:
        """Check available disk space on the given mount."""
        try:
            import shutil
            t0 = time.monotonic()
            usage = shutil.disk_usage(path)
            latency_ms = (time.monotonic() - t0) * 1000.0
            pct = (usage.used / usage.total) * 100
            ok = pct < 90  # Warning if >90% full
            return HealthStatus(
                service="disk-space",
                ok=ok,
                latency_ms=round(latency_ms, 2),
                error=f"{pct:.1f}% used" if not ok else None,
            )
        except Exception as exc:
            return HealthStatus(service="disk-space", ok=False, error=str(exc))

    def check_all(self) -> list[HealthStatus]:
        return [
            self.check_ollama(),
            self.check_chromadb(),
            self.check_pantheon_api(),
            self.check_mcp_server(),
            self.check_disk_space(),
        ]

    def all_healthy(self) -> bool:
        return all(s.ok for s in self.check_all())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_http(
        self,
        service: str,
        host: str,
        port: int,
        path: str = "/",
    ) -> HealthStatus:
        url = f"http://{host}:{port}{path}"
        try:
            t0 = time.monotonic()
            resp = httpx.get(url, timeout=self._TIMEOUT)
            latency_ms = (time.monotonic() - t0) * 1000.0
            if resp.status_code < 500:
                return HealthStatus(
                    service=service,
                    ok=True,
                    latency_ms=round(latency_ms, 2),
                )
            return HealthStatus(
                service=service,
                ok=False,
                latency_ms=round(latency_ms, 2),
                error=f"HTTP {resp.status_code}",
            )
        except Exception as exc:
            return HealthStatus(service=service, ok=False, error=str(exc))


# ── Report Formatting ─────────────────────────────────────────────────


def format_report(results: list[HealthStatus]) -> str:
    """Format health check results as a concise report."""
    lines = [
        f"# 🏛️  Hestia Health Report — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "| Service | Status | Latency | Error |",
        "|---------|--------|---------|-------|",
    ]
    for r in results:
        icon = "✅" if r.ok else "❌"
        lat = f"{r.latency_ms}ms" if r.latency_ms else "-"
        err = r.error or "-"
        lines.append(f"| {r.service} | {icon} {'UP' if r.ok else 'DOWN'} | {lat} | {err} |")

    lines.append("")
    all_ok = all(r.ok for r in results)
    if all_ok:
        lines.append("**✅ All systems healthy**")
    else:
        failed = [r.service for r in results if not r.ok]
        lines.append(f"**⚠️  {len(failed)} service(s) degraded:** {', '.join(failed)}")

    return "\n".join(lines)


def send_to_hermes(results: list[HealthStatus]) -> None:
    """Send health report to Hermes inbox."""
    now = datetime.now(timezone.utc)
    all_ok = all(r.ok for r in results)
    failed = [r.service for r in results if not r.ok]

    if all_ok:
        subject = "✅ Hestia — All systems healthy"
    else:
        subject = f"⚠️ Hestia — {len(failed)} service(s) degraded"

    body = format_report(results)
    message = {
        "id": f"hestia_{now.strftime('%Y%m%d_%H%M%S')}",
        "from": "hestia",
        "to": "hermes",
        "type": "report",
        "subject": subject,
        "body": body,
        "priority": "high" if not all_ok else "low",
        "timestamp": now.isoformat(),
        "read": False,
        "payload": {
            "report_type": "hestia_health",
            "timestamp": now.isoformat(),
            "services": {r.service: r.ok for r in results},
            "all_healthy": all_ok,
        },
        "thread_id": "hestia-health",
    }

    HERMES_INBOX.mkdir(parents=True, exist_ok=True)
    msg_path = HERMES_INBOX / f"{message['id']}.json"
    try:
        msg_path.write_text(json.dumps(message, indent=2) + "\n", encoding="utf-8")
        print(f"Report sent to Hermes: {msg_path.name}")
    except Exception as exc:
        print(f"Failed to send report: {exc}")


# ── CLI Entry Point ───────────────────────────────────────────────────


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Hestia — Pantheon Health Checker")
    parser.add_argument("--heartbeat-only", action="store_true",
                        help="Just write heartbeat, skip health checks")
    parser.add_argument("--send-hermes", action="store_true",
                        help="Send report to Hermes inbox")
    args = parser.parse_args()

    if args.heartbeat_only:
        if _HEARTBEAT_AVAILABLE:
            beat("hestia")
            print("Heartbeat written for hestia")
        else:
            print("WARNING: heartbeat library not available")
        return

    checker = HestiaChecker()
    results = checker.check_all()

    report = format_report(results)
    print(report)

    if args.send_hermes:
        send_to_hermes(results)

    # Always write heartbeat
    if _HEARTBEAT_AVAILABLE:
        errors = [r.error for r in results if not r.ok]
        if errors:
            beat("hestia", error=f"{len(errors)} failed: {', '.join(errors[:3])}")
        else:
            beat("hestia")

    sys.exit(0 if all(r.ok for r in results) else 1)


if __name__ == "__main__":
    main()
