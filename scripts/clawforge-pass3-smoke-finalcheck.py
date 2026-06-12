#!/usr/bin/env python3
"""Clawforge Pass 3 — final assertion check (assertions 3 + 4 only).

By the time this runs, the 23:50Z validator fire should have
processed the `smoke_test_promotion_broadcast` triple, and the
proxy cache should have a `pat_smoke_test_promotion_broadcast_*`
pattern.

This script:
  - Verifies the broadcast pattern was promoted (assertion 3a)
  - Verifies the proxy cache contains a smoke_test_promotion_broadcast
    pattern (assertion 3b — the actual proxy-side of the broadcast)
  - Verifies no PII in any registry (assertion 4)

No NATS subscribing here — we use the proxy cache as evidence that
the broadcast reached the local instance.

Run from Pantheon:
    python3 ~/pantheon/scripts/clawforge-pass3-smoke-finalcheck.py
"""
from __future__ import annotations

import json
import sys

import importlib.util

spec = importlib.util.spec_from_file_location(
    "smoke_main", "/home/konan/pantheon/scripts/clawforge-pass3-smoke.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def main() -> None:
    pass_count = 0
    total = 3

    # Assertion 3a: smoke_test_promotion_broadcast exists and is promoted
    reg = smoke.fetch_registry(smoke.EFFECTIVENESS_URL)
    p = smoke.find_pattern(reg, smoke.TEST_BROADCAST_TYPE)
    if p is None:
        smoke.fail(f"[3a] no {smoke.TEST_BROADCAST_TYPE} in registry (validator may not have run since 23:43:43Z); types: {[x.get('type') for x in reg.get('patterns',[])]}")
    if p.get("status") == "promoted":
        smoke.pass_(f"[3a] {smoke.TEST_BROADCAST_TYPE} promoted (confirmed={p.get('instances_validated')}, avg_imp={p.get('avg_improvement_pct')})")
        pass_count += 1
    else:
        smoke.warn(f"[3a] {smoke.TEST_BROADCAST_TYPE} status={p.get('status')} (not yet promoted; waiting for next validator fire)")

    # Assertion 3b: proxy cache has the broadcast pattern
    if smoke.PROXY_CACHE.exists():
        try:
            cache = json.loads(smoke.PROXY_CACHE.read_text())
            cache_keys = list(cache.get("patterns", {}).keys())
            bcast_keys = [k for k in cache_keys if smoke.TEST_BROADCAST_TYPE in k]
            if bcast_keys:
                smoke.pass_(f"[3b] proxy cache has {len(bcast_keys)} {smoke.TEST_BROADCAST_TYPE} pattern(s) (broadcast reached proxy)")
                pass_count += 1
            else:
                smoke.warn(f"[3b] proxy cache has {len(cache_keys)} patterns, no {smoke.TEST_BROADCAST_TYPE} yet")
        except Exception as e:
            smoke.warn(f"[3b] could not read proxy cache: {e}")
    else:
        smoke.warn(f"[3b] proxy cache not present at {smoke.PROXY_CACHE}")

    # Assertion 4: no PII in any registry
    hits = smoke.scan_for_pii()
    if not hits:
        smoke.pass_("[4] no PII fields in any registry")
        pass_count += 1
    else:
        smoke.fail(f"[4] PII hits: {hits}")

    smoke.log(f"=== {pass_count}/{total} assertions passed ===")
    if pass_count < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
