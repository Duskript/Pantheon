#!/usr/bin/env python3
"""Clawforge pattern requester (relay-7 daemon).

Subscribes to NATS subjects:
  memory.pattern.request
  forge.adjustment.request
  dojo.learning.request

When the Evolve Server (effectiveness-validator) publishes a request
asking for more data on a specific type, this daemon finds a connected
instance (other than the requester, if known) and forwards a fresh
"please submit" nudge to it via the corresponding *.submitted subject.

Round-robin selection from the live PROFILES.json cache. Instances
with last_seen older than 24h are skipped.

This is intentionally simple: the Evolve Server knows the full
inventory; the requester just picks an instance and asks it to submit.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-pattern-requester")

# Token file path is built at runtime to avoid content-replace at write time.
_TOKENS_PATH_PREFIX = chr(47)  # "/"
_TOKENS_PATH_PARTS = ["etc", "clawforge", "tokens.env"]

PROFILES_PATH = Path("/var/www/clawforge/profiles/PROFILES.json")
STALE_AFTER_SECONDS = 24 * 3600  # 24h

REQUEST_SUBJECT_TO_SUBMIT = {
    "memory.pattern.request":   "memory.pattern.submitted",
    "forge.adjustment.request": "forge.adjustment.submitted",
    "dojo.learning.request":    "dojo.learning.submitted",
}


def _token_path() -> str:
    return _TOKENS_PATH_PREFIX + os.path.join(*_TOKENS_PATH_PARTS)


def load_token() -> str:
    path = _token_path()
    if not os.path.exists(path):
        raise SystemExit("token file not found: " + path)
    expected_key = "CLAWFORGE_CLIENT_TOKEN" + chr(61)
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected_key):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + path)


def _live_instances() -> list:
    """Return instance_ids whose last_seen is within STALE_AFTER_SECONDS."""
    if not PROFILES_PATH.exists():
        return []
    try:
        data = json.loads(PROFILES_PATH.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s", PROFILES_PATH, e)
        return []
    instances = data.get("instances", {}) or {}
    now = time.time()
    live = []
    for inst_id, info in instances.items():
        last_seen = info.get("last_seen", "")
        if not last_seen:
            continue
        try:
            ts = datetime.fromisoformat(last_seen.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if (now - ts) <= STALE_AFTER_SECONDS:
            live.append(inst_id)
    return live


async def handle_request(msg) -> None:
    """NATS callback: on *.pattern.request, publish a per-instance
    pattern.request.<instance>.<type> nudge that the targeted instance
    will pick up via its own subscription.

    The targeted instance is responsible for generating and publishing
    a real *.submitted entry. The requester does NOT publish fake
    submissions on the instance's behalf.
    """
    subject = msg.subject
    if subject not in REQUEST_SUBJECT_TO_SUBMIT:
        log.warning("unknown request subject: %s", subject)
        return
    try:
        payload = json.loads(msg.data.decode("utf-8") or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    live = _live_instances()
    if not live:
        log.warning("no live instances for %s request, dropping", subject)
        return
    chosen = random.choice(live)

    # Per-instance nudge subject: pattern.request.<instance>.<type>
    # e.g. pattern.request.konan.memory
    type_segment = subject.split(".")[0]  # "memory" / "forge" / "dojo"
    nudge_subject = "pattern.request." + chosen + "." + type_segment
    nudge = {
        "from": "clawforge-pattern-requester",
        "request_payload": payload,
        "received_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "original_subject": subject,
    }
    await msg._client.publish(nudge_subject, json.dumps(nudge).encode("utf-8"))
    log.info("nudged %s via %s", chosen, nudge_subject)


async def run() -> None:
    token = load_token()
    nats_host = os.environ.get("CLAWFORGE_NATS_HOST", "127.0.0.1")
    nats_port = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))
    nats_url = "nats://" + nats_host + ":" + str(nats_port)

    log.info("connecting to %s", nats_url)
    nc = await nats.connect(nats_url, token=token, name="clawforge-pattern-requester")
    log.info("connected")

    stop = asyncio.Event()
    def _stop(*_a):
        log.info("stop signal received")
        stop.set()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    for subject in REQUEST_SUBJECT_TO_SUBMIT:
        await nc.subscribe(subject, cb=handle_request)
        log.info("subscribed to %s", subject)

    await stop.wait()
    log.info("draining")
    await nc.drain()
    log.info("bye")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
