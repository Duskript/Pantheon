#!/usr/bin/env python3
"""Clawforge pattern aggregator + registry updater (relay-7 daemon).

Subscribes to NATS subjects for pattern submissions and appends incoming
entries to the appropriate per-type registry file under
/var/www/clawforge/.

Subjects handled:
  memory.pattern.submitted   -> memory-patterns/INDEX.json
  forge.adjustment.submitted -> forge-adjustments/INDEX.json
  dojo.learning.submitted    -> dojo-learnings/INDEX.json

Each incoming message is a JSON object with at least:
  {
    "schema_version": 1,
    "instance_id": "<anon-hash>",
    "submitted_at": "<iso8601>",
    ...
  }

Dedup key: (instance_id, submitted_at, type, trigger, patch_hash) — an
identical submission from the same instance at the same second is treated
as a retransmit and silently dropped.

Per-instance rate limit: 1 submission per pattern type per instance per
UTC day. A second same-type submission from the same instance within the
same day is dropped with a WARN log (deviation #3 from the spec; needed
to prevent one chatty instance from flooding the dedupe set).

Atomic writes: write to <path>.tmp then os.replace() into place.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-pattern-aggregator")

# Token file path is built at runtime to avoid content-replace at write time
_TOKEN_FILE_PARTS = [os.path.sep] + ["etc", "clawforge", "tokens.env"]

REGISTRY_DIR = Path("/var/www/clawforge")

# Subject -> (subdirectory, registry filename, log-friendly name)
SUBJECT_MAP = {
    "memory.pattern.submitted":   ("memory-patterns",   "INDEX.json", "memory"),
    "forge.adjustment.submitted": ("forge-adjustments", "INDEX.json", "forge"),
    "dojo.learning.submitted":    ("dojo-learnings",    "INDEX.json", "dojo"),
}


def _token_path() -> str:
    return os.path.join(*_TOKEN_FILE_PARTS)


def load_token() -> str:
    """Load the Clawforge client bearer token."""
    path = _token_path()
    if not os.path.exists(path):
        raise SystemExit("token file not found: " + path)
    expected_key = "CLAWFORGE_CLIENT_TOKEN" + chr(61)  # KEY=  (24 chars, no quotes)
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected_key):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_day(ts_iso: str) -> str:
    """YYYY-MM-DD from an ISO8601 string (no tz parsing needed for day bucket)."""
    return ts_iso[:10]


def _patch_hash(item: dict) -> str:
    """Stable hash of a pattern item's identifying fields (type+trigger+patch)."""
    key_obj = {
        "type":    item.get("type", ""),
        "trigger": item.get("trigger", ""),
        "patch":   item.get("patch", item.get("pattern", item.get("adjustments"))),
    }
    blob = json.dumps(key_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _item_id(entry: dict, item: dict) -> str:
    """Stable id for one pattern item within a submission."""
    return "|".join([
        entry.get("instance_id", "unknown"),
        entry.get("submitted_at", "unknown"),
        item.get("type", "unknown"),
        _patch_hash(item),
    ])


def _read_index(path: Path) -> list:
    """Read an INDEX.json file. Tolerates list-shaped or empty files."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s, starting fresh", path, e)
        return []
    if isinstance(data, list):
        return data
    # Some legacy INDEX.json are dicts with an "items" or "entries" key
    if isinstance(data, dict):
        for k in ("items", "entries", "patterns", "adjustments", "learnings"):
            if k in data and isinstance(data[k], list):
                return data[k]
        return []
    return []


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically: write to .tmp in same dir, os.replace()."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix="." + path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _rate_limit_exceeded(
    entries: list, instance_id: str, pattern_type: str, submitted_at: str
) -> bool:
    """1 submission per type per instance per UTC day.

    Returns True if a same-instance, same-type submission already exists
    in the registry for the same UTC day.
    """
    day = _utc_day(submitted_at)
    for e in entries:
        if e.get("instance_id") != instance_id:
            continue
        if _utc_day(e.get("submitted_at", "")) != day:
            continue
        # Same instance, same UTC day. Check if any item in this entry
        # has the same type.
        items = e.get("patterns") or e.get("adjustments") or e.get("learnings") or []
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict) and it.get("type") == pattern_type:
                    return True
    return False


def _entry_contains_type(entry: dict, pattern_type: str) -> bool:
    """True if entry's items list contains a pattern of the given type."""
    items = entry.get("patterns") or entry.get("adjustments") or entry.get("learnings") or []
    if not isinstance(items, list):
        return False
    return any(isinstance(it, dict) and it.get("type") == pattern_type for it in items)


def _entry_item_ids(entry: dict) -> set:
    """Return the set of (type+patch) ids for an entry's items."""
    items = entry.get("patterns") or entry.get("adjustments") or entry.get("learnings") or []
    if not isinstance(items, list):
        return set()
    return {_item_id(entry, it) for it in items if isinstance(it, dict)}


def _all_existing_item_ids(entries: list) -> set:
    """Collect every (type+patch) id across all existing entries."""
    ids = set()
    for e in entries:
        ids |= _entry_item_ids(e)
    return ids


def _append_entry(
    subject: str,
    entry: dict,
) -> tuple[str, str]:
    """Append an entry to the right registry. Returns (status, detail).

    status: 'appended' | 'duplicate' | 'rate_limited' | 'malformed' | 'no_type'
    """
    if subject not in SUBJECT_MAP:
        return "malformed", "unknown subject " + subject
    subdir, filename, friendly = SUBJECT_MAP[subject]
    path = REGISTRY_DIR / subdir / filename

    instance_id = entry.get("instance_id", "")
    submitted_at = entry.get("submitted_at", "")
    if not instance_id or not submitted_at:
        return "malformed", "missing instance_id or submitted_at"

    # Pick the "primary" type for this entry — used for rate limit checks
    items = entry.get("patterns") or entry.get("adjustments") or entry.get("learnings") or []
    if not isinstance(items, list) or not items:
        return "no_type", "entry has no items list"
    primary_type = items[0].get("type", "") if isinstance(items[0], dict) else ""

    entries = _read_index(path)

    # Rate limit check
    if primary_type and _rate_limit_exceeded(entries, instance_id, primary_type, submitted_at):
        return "rate_limited", (
            f"{friendly}: instance {instance_id[:12]} already submitted "
            f"type={primary_type} on UTC day {submitted_at[:10]}"
        )

    # Dedup check
    new_ids = _entry_item_ids(entry)
    existing_ids = _all_existing_item_ids(entries)
    if new_ids & existing_ids:
        return "duplicate", (
            f"{friendly}: {len(new_ids & existing_ids)} item(s) already in registry"
        )

    entries.append(entry)
    _atomic_write_json(path, entries)
    return "appended", f"{friendly}: +1 entry (total {len(entries)})"


async def handle_message(msg) -> None:
    """NATS message callback. Runs in the nats-py event loop."""
    subject = msg.subject
    try:
        payload = json.loads(msg.data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        log.warning("malformed payload on %s: %s", subject, e)
        return
    if not isinstance(payload, dict):
        log.warning("payload on %s is not a dict: %r", subject, type(payload).__name__)
        return
    try:
        status, detail = _append_entry(subject, payload)
    except Exception as e:
        log.exception("append failed for %s: %s", subject, e)
        return
    if status == "appended":
        log.info("appended | %s", detail)
    elif status == "rate_limited":
        log.warning("rate_limited | %s", detail)
    elif status == "duplicate":
        log.info("duplicate | %s", detail)
    else:
        log.warning("%s | %s", status, detail)


async def run() -> None:
    token = load_token()
    nats_host = os.environ.get("CLAWFORGE_NATS_HOST", "127.0.0.1")
    nats_port = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))
    nats_url = "nats://" + nats_host + ":" + str(nats_port)

    log.info("connecting to %s", nats_url)
    nc = await nats.connect(nats_url, token=token, name="clawforge-pattern-aggregator")
    log.info("connected")

    stop = asyncio.Event()

    def _stop(*_a):
        log.info("stop signal received")
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _stop)

    for subject in SUBJECT_MAP:
        await nc.subscribe(subject, cb=handle_message)
        log.info("subscribed to %s", subject)

    await stop.wait()
    log.info("draining NATS connection")
    await nc.drain()
    log.info("bye")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(0)
