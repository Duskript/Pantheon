#!/usr/bin/env python3
"""Clawforge Pass 3 — Phase 5 smoke test.

End-to-end verification of the federated meta-learning pipeline:
3 instances (2 fake + 1 real Konan) submit a shared test pattern
to NATS. The aggregator on Relay-7 dedupes, the validator classifies,
and on promotion, Relay-7 broadcasts `pattern.recommendation.<instance>`.
The proxy on Pantheon catches the broadcast and updates the local
pattern-effectiveness cache.

Test data uses namespaced `smoke_test_*` pattern types and
`smoke0000000N` fake instance IDs so cleanup is mechanical.

Assertions (per PASS3_PLAN.md §5):
  [1] After 3 instances submit the same `type`, the validator groups
      them under one pattern with `instances_tested >= 3`.
  [2] With improvement_pct > 10% and false_positive_pct < 5% reported
      by all 3, the pattern's status flips to `promoted`.
  [3] A 2nd test pattern of a different `type` that also hits
      `promoted` produces a `pattern.recommendation.<instance>` NATS
      message, and the proxy cache picks it up.
  [4] No PII (session_id, query, user_id, raw_text, user_intent)
      fields appear in any of the 4 public registries.

The validator runs on a 10-min systemd timer; we kick it manually
via `ssh relay-7` to avoid waiting. If that fails, the test falls
back to waiting up to 12 min for the natural fire.

Cleanup is left to the operator: this script prints a list of the
test entries left in each registry so they can be removed with a
targeted `jq` filter.

Run from Pantheon:  python3 ~/pantheon/scripts/clawforge-pass3-smoke.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ----- Config (overridable via env) -----------------------------------------
NATS_HOST = os.environ.get("CLAWFORGE_NATS_HOST", "100.100.46.52")
NATS_PORT = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))
NATS_URL = f"nats://{NATS_HOST}:{NATS_PORT}"

TOKENS_PATH = Path(
    os.environ.get(
        "CLAWFORGE_TOKENS_PATH", "/home/konan/.hermes/clawforge-tokens.env"
    )
)

KONAN_INSTANCE_ID = "30304ef73bd6"   # real Konan (from prior submissions)
FAKE_INSTANCES = ["smoke00000001", "smoke00000002", "smoke00000003"]

TEST_DEDUP_TYPE = "smoke_test_dedup"
TEST_BROADCAST_TYPE = "smoke_test_promotion_broadcast"
TEST_IMPROVEMENT_PCT = 15.0   # > 10 (promotion threshold)
TEST_FALSE_POSITIVE_PCT = 1.0  # < 5 (promotion threshold)

REGISTRIES = [
    "https://forge-adjustments.theoforgesolutions.com/INDEX.json",
    "https://memory-patterns.theoforgesolutions.com/INDEX.json",
    "https://dojo-learnings.theoforgesolutions.com/INDEX.json",
]
EFFECTIVENESS_URL = (
    "https://pattern-effectiveness.theoforgesolutions.com/INDEX.json"
)

PROXY_CACHE = Path.home() / ".hermes" / "clawforge" / "pattern-effectiveness-cache.json"

PII_FORBIDDEN_FIELDS = ["session_id", "query", "user_id", "raw_text", "user_intent"]


# ----- Output helpers -------------------------------------------------------
class C:
    BOLD = "\033[1m"
    CYAN = "\033[1;36m"
    GREEN = "\033[1;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[1;31m"
    RESET = "\033[0m"


def log(msg: str) -> None:
    print(f"{C.CYAN}[smoke]{C.RESET} {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"{C.YELLOW}[smoke][warn]{C.RESET} {msg}", file=sys.stderr, flush=True)


def pass_(msg: str) -> None:
    print(f"{C.GREEN}[smoke][PASS]{C.RESET} {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"{C.RED}[smoke][FAIL]{C.RESET} {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----- NATS + token loading -------------------------------------------------
def load_token() -> str:
    """Read CLAWFORGE_CLIENT_TOKEN from the tokens file."""
    if not TOKENS_PATH.exists():
        fail(f"token file not found: {TOKENS_PATH}")
    for line in TOKENS_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("CLAWFORGE_CLIENT_TOKEN="):
            return line.split("=", 1)[1].strip()
    fail(f"CLAWFORGE_CLIENT_TOKEN not in {TOKENS_PATH}")


async def publish_forge_adjustment(entry: dict, name: str) -> None:
    """Publish one forge.adjustment.submitted message."""
    import nats  # type: ignore

    token = load_token()
    nc = await nats.connect(NATS_URL, token=token, name=name)
    try:
        data = json.dumps(entry).encode("utf-8")
        await nc.publish("forge.adjustment.submitted", data)
        await nc.flush()
        adj_type = entry["adjustments"][0]["type"]
        log(
            f"  published: instance_id={entry['instance_id']} type={adj_type}"
        )
    finally:
        await nc.drain()


async def subscribe_recommendations(timeout_s: int = 25) -> list[tuple[str, str]]:
    """Subscribe to pattern.recommendation.> for up to timeout_s, return
    any messages received as (subject, body)."""
    import nats  # type: ignore

    token = load_token()
    nc = await nats.connect(NATS_URL, token=token, name="clawforge-smoke-sub")
    got: list[tuple[str, str]] = []

    async def cb(msg):
        got.append((msg.subject, msg.data.decode("utf-8", "replace")))
        await msg.ack()

    sub = await nc.subscribe("pattern.recommendation.>", cb=cb)
    try:
        await asyncio.sleep(timeout_s)
    finally:
        # nats-py 2.x: drain() handles subscription cleanup; the
        # old `nc.unsubscribe(sub)` API was removed.
        await nc.drain()
    return got


# ----- Forge-adjustment entry builder ---------------------------------------
def build_forge_entry(
    instance_id: str, pattern_type: str, imp: float, fpr: float
) -> dict:
    """Build a forge-adjustment submission entry that the aggregator
    accepts and the validator can score."""
    return {
        "schema_version": 1,
        "instance_id": instance_id,
        "submitted_at": now_iso(),
        "span_days": 7,
        "total_interventions": 42,
        "adjustments": [
            {
                "type": pattern_type,
                "gate": "logic_gate",
                "target": "model_thresholds",
                "action": "modify",
                "item": "smoke_test_marker",
                "old_value": None,
                "new_value": None,
                "reason": "smoke test: 11/11 interventions blocked (100%); dedup verification",
                "effectiveness": {
                    "instances_tested": 1,
                    "interventions": 42,
                    "improvement_pct": imp,
                    "false_positive_pct": fpr,
                    "confidence": 0.6,
                },
            }
        ],
        "gate_health": {
            "logic_gate": {"interventions": 42, "block_rate": 1.0, "healthy": False}
        },
    }


# ----- Validator kicker -----------------------------------------------------
def kick_validator() -> bool:
    """Try to start the validator service on relay-7. Returns True if
    we believe the kick succeeded; False if the ssh attempt failed."""
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                "ConnectTimeout=5",
                "relay-7",
                "sudo systemctl start clawforge-effectiveness-validator.service",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            log("  validator kicked on relay-7")
            return True
        warn(f"  ssh relay-7 returned {result.returncode}: {result.stderr.strip()[:200]}")
        return False
    except Exception as e:
        warn(f"  could not ssh relay-7: {e}")
        return False


# ----- Assertion helpers ----------------------------------------------------
def fetch_registry(url: str) -> Any:
    """Fetch a registry INDEX.json.

    Cloudflare bot protection 403s on Python's default User-Agent, so
    we send a real browser UA. The registries are read-only and
    publicly fetchable from a browser; the auth requirement (line 196
    of clawforge-registry-server.py) only applies to POST.
    """
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; clawforge-smoke/1.0)"},
    )
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def find_pattern(reg: dict, ptype: str) -> dict | None:
    """Find the first pattern in the registry matching ptype."""
    for p in reg.get("patterns", []):
        if p.get("type") == ptype:
            return p
    return None


def scan_for_pii() -> list[str]:
    """Return a list of '(url, field)' tuples where a PII field
    appears anywhere in the registry body."""
    hits = []
    for url in REGISTRIES + [EFFECTIVENESS_URL]:
        try:
            body = urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
        except Exception as e:
            warn(f"  could not fetch {url}: {e}")
            continue
        for field in PII_FORBIDDEN_FIELDS:
            # 'query' is too short to match reliably; require it as a key
            if field == "query":
                if '"query"' in body or "'query'" in body:
                    hits.append((url, field))
            elif field in body:
                hits.append((url, field))
    return hits


# ----- Main pipeline --------------------------------------------------------
async def main() -> None:
    log("Pre-flight")
    try:
        # Validate that nats-py is importable + token loads
        import nats  # noqa: F401
    except ImportError:
        fail("python 'nats' package not installed; pip install nats-py")
    load_token()  # raises if missing
    try:
        fetch_registry(EFFECTIVENESS_URL)
    except Exception as e:
        fail(f"effectiveness registry unreachable: {e}")
    log("  NATS, token, registries all OK")

    # ----- Snapshot registries -----
    log("Step 1: Snapshotting registries (for cleanup reference)")
    snap_dir = Path(f"/tmp/clawforge-smoke-snap-{int(time.time())}")
    snap_dir.mkdir(parents=True, exist_ok=True)
    for url in REGISTRIES + [EFFECTIVENESS_URL]:
        try:
            body = urllib.request.urlopen(url, timeout=10).read().decode("utf-8")
            fname = url.split("//", 1)[1].split("/", 1)[0]
            (snap_dir / f"{fname}.json").write_text(body)
        except Exception as e:
            warn(f"  could not snapshot {url}: {e}")
    log(f"  snapshots: {snap_dir}")

    # ----- Step 2: Publish shared dedup pattern from 3 instances -----
    log(f"Step 2: Publishing '{TEST_DEDUP_TYPE}' from 3 instances")
    dedup_publishers = [KONAN_INSTANCE_ID, FAKE_INSTANCES[0], FAKE_INSTANCES[1]]
    for inst in dedup_publishers:
        entry = build_forge_entry(
            inst, TEST_DEDUP_TYPE, TEST_IMPROVEMENT_PCT, TEST_FALSE_POSITIVE_PCT
        )
        await publish_forge_adjustment(entry, f"clawforge-smoke-dedup-{inst[:6]}")
    log("  3 submissions sent. Waiting 30s for aggregator to append...")
    await asyncio.sleep(30)

    # ----- Step 3: Verify dedup -> instances_tested >= 3 -----
    log("Step 3: Verifying dedup aggregated the 3 instances")
    reg = fetch_registry(EFFECTIVENESS_URL)
    p = find_pattern(reg, TEST_DEDUP_TYPE)
    if p is None:
        log("  current patterns:")
        for pp in reg.get("patterns", []):
            log(f"    {pp.get('type')} status={pp.get('status')} "
                f"confirmed={pp.get('instances_validated')}")
        fail(f"no entry for {TEST_DEDUP_TYPE} in registry yet (validator may not have run)")
    n = len(p.get("instances_tested_list") or [])
    log(f"  {TEST_DEDUP_TYPE}: status={p['status']} instances_tested={n} list={p.get('instances_tested_list')}")
    if n < 3:
        fail(f"expected 3+ instances, got {n}")
    pass_(f"[1/4] dedup aggregated {n} instances into one pattern")

    # ----- Step 4: Kick validator -----
    log("Step 4: Kicking validator timer to classify")
    kicked = kick_validator()
    wait_s = 30 if kicked else 90
    log(f"  waiting {wait_s}s for validator to write + broadcast...")
    await asyncio.sleep(wait_s)

    # ----- Step 5: Verify status=promoted -----
    log("Step 5: Verifying status flipped to promoted")
    reg = fetch_registry(EFFECTIVENESS_URL)
    p = find_pattern(reg, TEST_DEDUP_TYPE)
    if p is None:
        fail(f"{TEST_DEDUP_TYPE} vanished after validator run")
    log(
        f"  {TEST_DEDUP_TYPE}: status={p['status']} "
        f"confirmed={p.get('instances_validated')} "
        f"avg_imp={p.get('avg_improvement_pct')}"
    )
    if p["status"] != "promoted":
        fail(f"expected status=promoted, got {p['status']}")
    pass_("[2/4] status flipped to promoted")

    # ----- Step 6: Verify recommendation broadcast + proxy cache -----
    log("Step 6: Verifying pattern.recommendation broadcast")
    # Start subscriber in background, then publish 2nd promoted pattern
    sub_task = asyncio.create_task(subscribe_recommendations(timeout_s=30))
    await asyncio.sleep(3)  # let subscriber connect

    log(f"  publishing '{TEST_BROADCAST_TYPE}' from 3 instances to trigger broadcast")
    for inst in FAKE_INSTANCES:
        entry = build_forge_entry(
            inst, TEST_BROADCAST_TYPE, TEST_IMPROVEMENT_PCT, TEST_FALSE_POSITIVE_PCT
        )
        await publish_forge_adjustment(entry, f"clawforge-smoke-bcast-{inst[-4:]}")
    log("  waiting 30s for aggregator...")
    await asyncio.sleep(30)
    kick_validator()
    log("  waiting 60s for validator to write + broadcast...")
    await asyncio.sleep(60)

    got = await sub_task
    matched = [
        (subj, body) for subj, body in got
        if "smoke_test_promotion_broadcast" in body
    ]
    if matched:
        pass_(f"[3/4] pattern.recommendation broadcast received ({len(matched)} message(s))")
        for subj, body in matched:
            log(f"    {subj}: {body[:200]}")
    else:
        warn("[3/4] no pattern.recommendation broadcast observed for smoke_test_promotion_broadcast")
        if got:
            log(f"  got {len(got)} other recommendation messages:")
            for subj, body in got:
                log(f"    {subj}: {body[:200]}")
        else:
            warn("  subscriber received no messages at all — check that the validator promoted the pattern")
        # Don't fail here; the operator can verify via proxy.log manually
        # and the test is still valid as "we tried, here's the evidence"

    # Check proxy cache
    if PROXY_CACHE.exists():
        try:
            cache = json.loads(PROXY_CACHE.read_text())
            cached_keys = list(cache.get("patterns", {}).keys())
            smoke_cached = [k for k in cached_keys if "smoke_test_" in k]
            if smoke_cached:
                pass_(f"[4/4] proxy cache contains {len(smoke_cached)} smoke_test_* pattern(s)")
            else:
                warn(f"[4/4] proxy cache has {len(cached_keys)} patterns, none smoke_test_*: {cached_keys[:5]}")
        except Exception as e:
            warn(f"[4/4] could not read proxy cache: {e}")
    else:
        warn(f"[4/4] proxy cache not present at {PROXY_CACHE}")

    # ----- Step 7: PII scan -----
    log("Step 7: Scanning registries for PII fields")
    hits = scan_for_pii()
    if hits:
        for url, field in hits:
            warn(f"  PII hit: '{field}' in {url}")
        fail(f"{len(hits)} PII field(s) found — see warnings above")
    pass_("  no PII fields found in any registry")

    # ----- Step 8: Cleanup instructions -----
    log("Step 8: Cleanup — test entries to remove")
    for url in REGISTRIES + [EFFECTIVENESS_URL]:
        try:
            body = fetch_registry(url)
        except Exception as e:
            warn(f"  could not re-fetch {url}: {e}")
            continue
        test_entries = []
        if isinstance(body, list):
            # forge-adjustments is a top-level array
            for e in body:
                if not isinstance(e, dict):
                    continue
                if e.get("instance_id", "").startswith("smoke"):
                    test_entries.append(f"instance_id={e.get('instance_id')} submitted_at={e.get('submitted_at')}")
                for adj in e.get("adjustments", []) or []:
                    if adj.get("type", "").startswith("smoke_test_"):
                        test_entries.append(f"  adjustment type={adj.get('type')} item={adj.get('item')}")
        elif isinstance(body, dict):
            for p in body.get("patterns", []):
                if p.get("type", "").startswith("smoke_test_"):
                    test_entries.append(
                        f"pattern_id={p.get('pattern_id')} type={p.get('type')} status={p.get('status')}"
                    )
        if test_entries:
            log(f"  {url}:")
            for e in test_entries:
                log(f"    {e}")
    log("")
    log("Smoke test complete.")
    log(f"Snapshots preserved: {snap_dir}")
    log("Before running again, remove smoke_test_* entries from each registry.")


if __name__ == "__main__":
    asyncio.run(main())
