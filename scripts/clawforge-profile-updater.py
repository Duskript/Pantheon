#!/usr/bin/env python3
"""Clawforge profile registry updater.

Subscribes to NATS subject `claw.profile.update` and merges incoming
profile updates into /var/www/clawforge/profiles/PROFILES.json.

Message format (JSON):
{
    "instance_id": "konan",          # required
    "display_name": "Konan's Pantheon",  # required
    "gods": {                        # required
        "hermes": {"display_name": "Hermes", "role": "...", "capabilities": [...]},
        ...
    }
}

The PROFILES.json format:
{
    "updated_at": "2026-06-10T...",
    "instances": {
        "konan": {
            "display_name": "Konan's Pantheon",
            "last_seen": "2026-06-10T...",
            "gods": {...}
        },
        ...
    }
}
"""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

import nats
import yaml

PROFILES_PATH = "/var/www/clawforge/profiles/PROFILES.json"


def load_profiles() -> dict:
    """Load current PROFILES.json (or init if missing)."""
    if not os.path.exists(PROFILES_PATH):
        return {"updated_at": _now(), "instances": {}}
    try:
        with open(PROFILES_PATH, "r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"WARN: existing PROFILES.json unreadable ({e}), starting fresh", flush=True)
        return {"updated_at": _now(), "instances": {}}


def save_profiles(data: dict) -> None:
    """Atomic write: write to temp, rename."""
    data["updated_at"] = _now()
    dir_name = os.path.dirname(PROFILES_PATH)
    fd, tmp_path = tempfile.mkstemp(dir=dir_name, prefix=".PROFILES.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, PROFILES_PATH)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_update(profiles: dict, msg: dict) -> dict:
    """Merge an incoming profile update into the registry."""
    instance_id = msg.get("instance_id")
    display_name = msg.get("display_name")
    gods = msg.get("gods", {})
    if not instance_id or not display_name:
        print(f"WARN: malformed message (missing instance_id or display_name): {msg}", flush=True)
        return profiles
    profiles["instances"][instance_id] = {
        "display_name": display_name,
        "last_seen": _now(),
        "gods": gods,
    }
    return profiles


async def message_handler(msg):
    """Handle a single NATS message.

    Note: this is a plain (non-JetStream) subscription, so we don't
    call msg.ack() — that would raise NotJSMessageError. NATS handles
    message lifecycle for plain subscribes automatically.
    """
    try:
        data = json.loads(msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        preview = msg.data[:200] if msg.data else b""
        print(f"WARN: bad message JSON: {e}: {preview!r}", flush=True)
        return
    profiles = load_profiles()
    profiles = apply_update(profiles, data)
    try:
        save_profiles(profiles)
        msg_count = len(data.get("gods", {}))
        instance = data.get("instance_id", "?")
        print(f"OK: updated profile for '{instance}' ({msg_count} gods)", flush=True)
    except OSError as e:
        print(f"ERROR: could not save profiles: {e}", flush=True)


def load_config() -> dict:
    config_path = "/etc/clawforge/profile-updater.yaml"
    if not os.path.exists(config_path):
        # Fallback to env vars
        return {
            "nats": {
                "url": os.environ.get("CLAWFORGE_NATS_URL", "nats://nats.theoforgesolutions.com:4222"),
                "token": os.environ.get("CLAWFORGE_CLIENT_TOKEN", ""),
            },
            "subject": "claw.profile.update",
        }
    with open(config_path) as f:
        return yaml.safe_load(f)


async def main():
    config = load_config()
    nats_url = config["nats"]["url"]
    nats_token = config["nats"]["token"]
    subject = config.get("subject", "claw.profile.update")

    if not nats_token:
        print("ERROR: no NATS token configured", flush=True)
        sys.exit(1)

    print(f"Connecting to NATS at {nats_url} ...", flush=True)
    nc = await nats.connect(
        nats_url,
        token=nats_token,
        connect_timeout=10,
        reconnect_time_wait=2,
        max_reconnect_attempts=-1,  # forever
    )
    print(f"Connected. Subscribing to '{subject}' ...", flush=True)

    # Use JetStream if available, otherwise plain subscribe
    sub = await nc.subscribe(subject, cb=message_handler)
    print(f"Subscribed. Awaiting messages.", flush=True)

    # Run forever
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        await sub.unsubscribe()
        await nc.drain()


if __name__ == "__main__":
    asyncio.run(main())
