"""Hestia — health check script for all Pantheon services.

Driver: script
Runs and exits, returning HealthStatus for each checked service.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class HealthStatus:
    service: str
    ok: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None


class HestiaChecker:
    """Checks health of Pantheon service dependencies."""

    _TIMEOUT = 2.0  # seconds per check

    def check_ollama(self, host: str = "localhost", port: int = 11434) -> HealthStatus:
        return self._check_http("ollama", host, port, path="/")

    def check_chromadb(self, host: str = "localhost", port: int = 8000) -> HealthStatus:
        return self._check_http("chromadb", host, port, path="/api/v1/heartbeat")

    def check_pantheon_api(self, host: str = "localhost", port: int = 8001) -> HealthStatus:
        return self._check_http("pantheon-api", host, port, path="/sanctuaries")

    def check_all(self) -> list[HealthStatus]:
        return [
            self.check_ollama(),
            self.check_chromadb(),
            self.check_pantheon_api(),
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
            with httpx.Client(timeout=self._TIMEOUT) as client:
                import time
                t0 = time.monotonic()
                resp = client.get(url)
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
        except Exception as exc:  # noqa: BLE001
            return HealthStatus(service=service, ok=False, error=str(exc))
