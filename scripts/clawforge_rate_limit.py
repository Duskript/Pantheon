#!/usr/bin/env python3
"""
Clawforge Rate Limit — v0.4.0

Per-god token-bucket rate limiting + concurrent-subprocess semaphore
for the messenger and `ask` CLI. CONFIG-ONLY: refuses to start with
no config (user picked `rates_config`).

Config block (in ~/.hermes/clawforge.yaml):

    messenger:
      rate_limit:
        # Per-god token bucket. Each god gets its own bucket.
        per_god:
          capacity: 10               # burst size (tokens)
          refill_per_second: 1.0     # sustained rate
        # Concurrent subprocess cap (hermes chat instances)
        concurrency: 4
        # Apply same gates to outbound `ask` CLI (sender side)
        outbound_enabled: true

Usage:

    from clawforge_rate_limit import RateLimit, RateLimitDecision

    rl = RateLimit.from_config(cfg)  # raises SystemExit if missing/invalid
    decision = await rl.check_inbound("iris")  # or check_outbound
    if not decision.allowed:
        # return rate-limit response
        ...
    async with rl.semaphore:
        await call_local_god(...)

Design notes:
- Token bucket is in-memory (per-process). Multi-process deployments
  would need a shared store (Redis, NATS KV), but Clawforge is one
  messenger per instance, so in-memory is correct for v0.4.0.
- `check_inbound` is for the daemon; `check_outbound` is for the CLI.
  Both share the same bucket per god — a god that's being hammered
  inbound AND outbound gets rate-limited as a whole.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("clawforge-rate-limit")


@dataclass
class RateLimitConfig:
    """Validated rate-limit config block."""
    capacity: int
    refill_per_second: float
    concurrency: int
    outbound_enabled: bool

    @classmethod
    def from_dict(cls, d: dict) -> "RateLimitConfig":
        try:
            per_god = d["per_god"]
            capacity = int(per_god["capacity"])
            refill = float(per_god["refill_per_second"])
            concurrency = int(d["concurrency"])
            outbound = bool(d.get("outbound_enabled", True))
        except (KeyError, TypeError, ValueError) as e:
            raise SystemExit(
                f"rate_limit config missing/invalid ({e}). Expected: "
                "messenger.rate_limit.per_god.{capacity,refill_per_second} + concurrency"
            )
        if capacity <= 0 or refill <= 0 or concurrency <= 0:
            raise SystemExit(
                f"rate_limit values must be > 0 (got capacity={capacity}, "
                f"refill_per_second={refill}, concurrency={concurrency})"
            )
        return cls(capacity, refill, concurrency, outbound)


@dataclass
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: float = 0.0
    reason: str = ""

    def to_response_dict(self) -> dict:
        """Return the response payload when not allowed."""
        return {
            "status": "rate_limited",
            "retry_after_seconds": round(self.retry_after_seconds, 2),
            "reason": self.reason,
        }


class _TokenBucket:
    """Single token bucket. Thread/coroutine safe via asyncio.Lock."""
    def __init__(self, capacity: int, refill_per_second: float):
        self.capacity = capacity
        self.refill = refill_per_second
        self.tokens = float(capacity)  # start full
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def try_consume(self, n: int = 1) -> RateLimitDecision:
        async with self._lock:
            self._refill()
            if self.tokens >= n:
                self.tokens -= n
                return RateLimitDecision(allowed=True)
            # How long until n tokens are available?
            deficit = n - self.tokens
            wait = deficit / self.refill
            return RateLimitDecision(
                allowed=False,
                retry_after_seconds=wait,
                reason=f"per-god bucket empty (capacity={self.capacity}, refill={self.refill}/s)",
            )

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill)
        self.last_refill = now


class RateLimit:
    """Top-level gate: per-god bucket + global concurrency semaphore."""

    def __init__(self, cfg: RateLimitConfig):
        self.cfg = cfg
        self._buckets: dict[str, _TokenBucket] = {}
        self._buckets_lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(cfg.concurrency)

    @classmethod
    def from_config(cls, top_cfg: dict) -> "RateLimit":
        messenger = top_cfg.get("messenger")
        if not messenger:
            raise SystemExit(
                "messenger block missing in clawforge.yaml. Required: "
                "messenger.rate_limit.{per_god.{capacity,refill_per_second},concurrency}"
            )
        rl = messenger.get("rate_limit")
        if not rl:
            raise SystemExit(
                "messenger.rate_limit block missing in clawforge.yaml. Refusing to "
                "start with no rate-limit config (config-only mode)."
            )
        return cls(RateLimitConfig.from_dict(rl))

    async def _bucket_for(self, god: str) -> _TokenBucket:
        async with self._buckets_lock:
            b = self._buckets.get(god)
            if b is None:
                b = _TokenBucket(self.cfg.capacity, self.cfg.refill_per_second)
                self._buckets[god] = b
            return b

    async def check_inbound(self, god: str) -> RateLimitDecision:
        """Gate for incoming requests (messenger daemon)."""
        b = await self._bucket_for(god)
        return await b.try_consume()

    async def check_outbound(self, god: str) -> RateLimitDecision:
        """Gate for outbound `ask` CLI calls. Honors outbound_enabled."""
        if not self.cfg.outbound_enabled:
            return RateLimitDecision(allowed=True, reason="outbound_enabled=false")
        return await self.check_inbound(god)


# ----- Quick self-test ------------------------------------------------------

async def _selftest():
    """Minimal round-trip test. Run: python3 clawforge-rate-limit.py"""
    cfg = RateLimitConfig(capacity=3, refill_per_second=1.0, concurrency=2, outbound_enabled=True)
    rl = RateLimit(cfg)
    # Burst: 3 should pass, 4th should fail
    for i in range(4):
        d = await rl.check_inbound("iris")
        print(f"  attempt {i+1}: allowed={d.allowed} retry={d.retry_after_seconds:.2f}s")
    # Wait for refill
    print("  waiting 1.5s for refill...")
    await asyncio.sleep(1.5)
    d = await rl.check_inbound("iris")
    print(f"  after refill: allowed={d.allowed} tokens left should be ~1.5")
    # Different god has its own bucket
    d = await rl.check_inbound("marvin")
    print(f"  marvin bucket: allowed={d.allowed} (should be True, separate bucket)")
    print("OK")


if __name__ == "__main__":
    asyncio.run(_selftest())
