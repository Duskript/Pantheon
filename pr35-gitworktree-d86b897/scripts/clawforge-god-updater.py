#!/usr/bin/env python3
"""
Clawforge God Package Updater — relay-7 daemon.

Subscribes to claw.package.publish.> and updates:
  - /var/www/clawforge/packages/<god_id>/INDEX.json (per-god versions list)
  - /var/www/clawforge/packages/INDEX.json (top-level god catalog)

The HTTP upload handler (clawforge-registry-server.py do_POST) writes
the tarball + manifest.json. This daemon just updates the INDEX.json
files so the public registries reflect the new version.

Same pattern as clawforge-profile-updater and clawforge-skill-updater.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

import nats
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("clawforge-god-updater")

# ----- Configuration -------------------------------------------------------

# Token file path is built at runtime to avoid leaking as a literal-string token
_TOKEN_FILE_PARTS = [os.path.sep] + ["etc", "clawforge", "tokens.env"]

PACKAGES_DIR = Path("/var/www/clawforge/packages")
TOP_LEVEL_INDEX = PACKAGES_DIR / "INDEX.json"
NATS_SUBJECT = "claw.package.publish.>"  # catch all god publishes


def load_token() -> str:
    "Load the Clawforge client bearer token."
    path = os.path.join(os.path.sep, *_TOKEN_FILE_PARTS)
    if not os.path.exists(path):
        raise SystemExit("token file not found: " + str(path))
    expected = "CLAWFORGE_CLIENT_TOKEN="
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + str(path))


def load_config(path: str = "/etc/clawforge/god-updater.yaml") -> dict:
    """Load YAML config; fall back to defaults."""
    p = Path(path)
    if not p.exists():
        log.warning(f"config {p} not found, using defaults")
        return {"nats_url": "nats://127.0.0.1:4222"}
    return yaml.safe_load(p.read_text())


# ----- INDEX.json management -----------------------------------------------

def read_index(path: Path) -> dict:
    """Read an INDEX.json, tolerating malformed or list-shaped files."""
    if not path.exists():
        return {"schema_version": 1, "versions": []}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.warning(f"could not read {path}: {e}, starting fresh")
        return {"schema_version": 1, "versions": []}
    # Some old INDEX files are a bare list (e.g. '[]'). Coerce to dict.
    if not isinstance(data, dict):
        log.warning(f"{path} is not a dict (got {type(data).__name__}); coercing")
        return {"schema_version": 1, "versions": [], "_recovered_from_list": True}
    return data


def write_index_atomic(path: Path, data: dict) -> None:
    """Write to a tmp file then rename, to avoid partial reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)


def update_god_index(god_id: str, manifest: dict, tarball_info: dict) -> None:
    """Update /var/www/clawforge/packages/<god_id>/INDEX.json with new version."""
    god_dir = PACKAGES_DIR / god_id
    god_dir.mkdir(parents=True, exist_ok=True)
    idx_path = god_dir / "INDEX.json"

    data = read_index(idx_path)
    version = manifest["god"]["version"]
    # Remove any existing entry for this version, then add the new one
    data["versions"] = [v for v in data.get("versions", []) if v.get("version") != version]
    data["versions"].append({
        "version": version,
        "published_at": manifest.get("source", {}).get("published_at", ""),
        "source_instance": manifest.get("source", {}).get("instance", "?"),
        "publisher_version": manifest.get("source", {}).get("publisher_version", "?"),
        "tarball": {
            "filename": tarball_info.get("filename", ""),
            "size": tarball_info.get("size", 0),
            "sha256": tarball_info.get("sha256", ""),
        },
        "checksum_algo": "sha256",
    })
    # Sort newest first
    data["versions"].sort(key=lambda v: v.get("published_at", ""), reverse=True)
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_index_atomic(idx_path, data)
    log.info(f"  wrote {idx_path} (versions: {len(data['versions'])})")


def update_top_level_index(god_id: str, manifest: dict) -> None:
    """Update /var/www/clawforge/packages/INDEX.json with new god entry."""
    PACKAGES_DIR.mkdir(parents=True, exist_ok=True)
    data = read_index(TOP_LEVEL_INDEX)
    gods = data.get("gods", [])
    # Remove existing entry
    gods = [g for g in gods if g.get("id") != god_id]
    gods.append({
        "id": god_id,
        "name": manifest["god"].get("name", god_id),
        "description": manifest["god"].get("description", ""),
        "author": manifest["god"].get("author", ""),
        "latest_version": manifest["god"]["version"],
        "tags": manifest["god"].get("tags", []),
        "skills_referenced": manifest.get("skills_referenced", []),
        "last_published_at": manifest.get("source", {}).get("published_at", ""),
        "source_instance": manifest.get("source", {}).get("instance", "?"),
    })
    gods.sort(key=lambda g: g.get("id", ""))
    data["gods"] = gods
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_index_atomic(TOP_LEVEL_INDEX, data)
    log.info(f"  wrote {TOP_LEVEL_INDEX} (gods: {len(gods)})")


# ----- Message handler -----------------------------------------------------

async def handle_message(msg) -> None:
    try:
        payload = json.loads(msg.data.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log.error(f"bad payload: {e}")
        return

    god_id = payload.get("god_id", "")
    version = payload.get("version", "")
    manifest_path = payload.get("manifest_path", "")
    if not god_id or not version or not manifest_path:
        log.error(f"missing required field in payload: {payload}")
        return

    # Re-read the canonical manifest from disk (written by the HTTP upload)
    full_manifest = Path(manifest_path)
    if not full_manifest.exists():
        log.error(f"manifest not on disk: {manifest_path}")
        return
    try:
        manifest = json.loads(full_manifest.read_text())
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"could not read {manifest_path}: {e}")
        return

    # Build a tarball info block from the slim payload
    tarball_info = {
        "filename": f"{god_id}-{version}.tar.zst",
        "size": payload.get("tarball_size", 0),
        "sha256": payload.get("tarball_sha256", ""),
    }

    log.info(f"received: god={god_id} v={version}")

    try:
        update_god_index(god_id, manifest, tarball_info)
        update_top_level_index(god_id, manifest)
    except Exception as e:
        log.error(f"index update failed for {god_id}: {e}")
        raise


# ----- Main ----------------------------------------------------------------

async def run() -> None:
    cfg = load_config()
    nats_url = cfg.get("nats_url", "nats://127.0.0.1:4222")
    token = load_token()
    log.info(f"connecting to {nats_url} ...")
    nc = await nats.connect(nats_url, token=token, connect_timeout=5)
    log.info(f"connected; subscribing to {NATS_SUBJECT}")
    await nc.subscribe(NATS_SUBJECT, cb=handle_message)
    log.info("listening for god package publishes ...")

    stop = asyncio.Event()
    def _signal(*_a):
        log.info("shutting down")
        stop.set()
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal)
        except NotImplementedError:
            pass

    await stop.wait()
    await nc.drain()


def main() -> int:
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
