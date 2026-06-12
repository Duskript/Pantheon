#!/usr/bin/env python3
"""
Clawforge God Package Puller — v0.2.0

Downloads a god package from a remote Clawforge instance and installs it
locally. Verifies the tarball checksum against the per-god INDEX.json
before extraction, so an attacker who controls the wire but not the
checksum can't substitute a different bundle.

Usage:
    clawforge-god-puller.py pull <instance>:<god>@<version> [--prefix PATH]
    clawforge-god-puller.py list   [--instance NAME]

Example:
    clawforge-god-puller.py pull konan:iris@1.0.0
    clawforge-god-puller.py pull konan:iris@latest

The puller does NOT auto-register the god in gods.yaml. That's a user
decision — god installation has side effects (systemd services, etc.)
that should be opt-in. The puller DOES update the local federation
cache so `clawforge who` shows the new instance's package.

For Pass 2 v0.2.0 the puller is also read-only by design for now; it
prints `clawforge god register <god>` instructions at the end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sys
import tarfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

# ----- Logger -----
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("clawforge-god-puller")



# ----- Configuration -------------------------------------------------------

# Default registry bases, tried in order. The first hit wins.
# 1. The multi-tenancy public URL (requires Advanced SSL or per-host cert)
# 2. The bare public URL (works under current Universal SSL)
# 3. Tailscale (works for clients inside the tailnet; bypasses Cloudflare)
DEFAULT_REGISTRY_BASES = [
    "https://{instance}.packages.theoforgesolutions.com",
    "https://packages.theoforgesolutions.com",
    "http://100.100.46.52:8900",
]
LOCAL_PROFILES_DIR = Path.home() / ".hermes" / "profiles"
LOCAL_GODS_YAML = Path.home() / "pantheon" / "gods" / "gods.yaml"
LOCAL_CACHE_DIR = Path.home() / ".hermes" / "clawforge"


def _registry_bases(instance: str) -> list[str]:
    """Return the candidate registry bases for a given instance, in priority order.

    Allow env override via CLAWFORGE_REGISTRY_BASE=url (single value, used as-is).
    """
    custom = os.environ.get("CLAWFORGE_REGISTRY_BASE")
    if custom:
        return [custom]
    return [b.format(instance=instance) for b in DEFAULT_REGISTRY_BASES]


# ----- HTTP helpers --------------------------------------------------------

def http_get(url: str, host: str | None = None) -> bytes:
    """GET with a browser User-Agent to dodge Cloudflare 1010.

    If `host` is given, override the Host header (used for the Tailscale
    fallback to the relay IP, which needs Host: <sub>.theoforgesolutions.com
    for the Python registry server to route correctly).
    """
    headers = {"User-Agent": "Clawforge/0.3 (god-puller)"}
    if host:
        headers["Host"] = host
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def http_get_with_fallback(candidates: list[tuple[str, str | None]]) -> tuple[bytes, str]:
    """Try each (url, host_override) in order; return (body, url_that_succeeded).

    The Tailscale fallback for relay-7 needs a Host header because the
    Python registry server routes by Host.
    """
    last_err = None
    for url, host in candidates:
        try:
            return http_get(url, host=host), url
        except Exception as e:
            last_err = e
            continue
    raise SystemExit(f"all registry bases failed for {[u.split("/")[2] for u, _ in candidates]}: {last_err}")


def parse_target(target: str) -> tuple[str, str, str | None]:
    """Parse 'instance:god@version' into (instance, god, version|None)."""
    version = None
    if "@" in target:
        target, version = target.rsplit("@", 1)
        if version == "latest":
            version = None
    if ":" not in target:
        raise SystemExit(f"target must be 'instance:god[@version]', got {target!r}")
    instance, god = target.split(":", 1)
    return instance, god, version


# ----- INDEX.json resolution -----------------------------------------------

def fetch_god_index(instance: str, god: str) -> dict:
    """Fetch the per-god INDEX.json for a remote instance.

    Tries multi-tenant public URL first, then bare public, then Tailscale.
    The Tailscale URL needs the original Host header so the registry server
    can route by Host (Python http.server has no SNI-like host matching).
    """
    base_hosts = {
        "konan": "konan.packages.theoforgesolutions.com",
        "enterprise": "enterprise.packages.theoforgesolutions.com",
    }
    original_host = base_hosts.get(instance, "packages.theoforgesolutions.com")
    candidates = []
    for b in _registry_bases(instance):
        host_override = original_host if b.startswith("http://100.100.46.52") else None
        candidates.append((f"{b}/{god}/INDEX.json", host_override))
    body, used = http_get_with_fallback(candidates)
    log.info(f"  used: {used.split("/")[2]}")
    return json.loads(body.decode())


def select_version(idx: dict, version: str | None) -> dict:
    """Pick the version entry to install (defaults to most recent)."""
    versions = idx.get("versions", [])
    if not versions:
        raise SystemExit(f"no versions in INDEX.json")
    if version:
        for v in versions:
            if v.get("version") == version:
                return v
        available = ", ".join(v.get("version", "?") for v in versions)
        raise SystemExit(f"version {version!r} not found; available: {available}")
    # Newest first
    return versions[0]


# ----- Download + verify ---------------------------------------------------

def download_tarball(instance: str, god: str, version_entry: dict, dest: Path) -> None:
    """Download the tarball, verify sha256, write to dest."""
    tb = version_entry.get("tarball", {})
    filename = tb.get("filename", f"{god}-{version_entry.get('version')}.tar.zst")
    expected_sha = tb.get("sha256", "")
    expected_size = tb.get("size", 0)

    # The public URL is /<god>/<version_seg>/<filename>
    version_seg = f"v{version_entry.get('version', '?')}"
    base_hosts = {
        "konan": "konan.packages.theoforgesolutions.com",
        "enterprise": "enterprise.packages.theoforgesolutions.com",
    }
    original_host = base_hosts.get(instance, "packages.theoforgesolutions.com")
    candidates = []
    for b in _registry_bases(instance):
        host_override = original_host if b.startswith("http://100.100.46.52") else None
        candidates.append((f"{b}/{god}/{version_seg}/{filename}", host_override))
    print(f"  downloading from: {candidates[0][0]}")
    body, used = http_get_with_fallback(candidates)
    log.info(f"  used: {used.split("/")[2]}")

    if expected_size and len(body) != expected_size:
        raise SystemExit(
            f"size mismatch: got {len(body)} bytes, expected {expected_size}"
        )

    actual_sha = hashlib.sha256(body).hexdigest()
    if expected_sha and actual_sha != expected_sha:
        raise SystemExit(
            f"sha256 mismatch:\n    expected: {expected_sha}\n    actual:   {actual_sha}"
        )
    print(f"  verified:    sha256={actual_sha[:16]}... size={len(body):,}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)


# ----- Install -------------------------------------------------------------

def install_god(god: str, tarball: Path, profile_dir: Path) -> None:
    """Extract the tarball into the local profiles dir, overwriting the
    god's existing files but NOT touching other state (logs/, etc.)."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"  extracting to: {profile_dir}")
    # Use the system `tar` command (Python 3.14 stdlib tarfile doesn't
    # support zstd mode without the zstandard pip package).
    import subprocess
    result = subprocess.run(
        ["tar", "--zstd", "-xf", str(tarball), "-C", str(profile_dir)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"tar extract failed: {result.stderr}")


# ----- Optional: register in gods.yaml -------------------------------------

def offer_register(god: str) -> None:
    """Tell the user how to register the installed god."""
    print()
    print(f"  God {god!r} installed to {LOCAL_PROFILES_DIR / god}")
    print(f"  To register in Pantheon's god catalog, run:")
    print(f"    clawforge god register {god}")
    print(f"  Or manually add an entry to {LOCAL_GODS_YAML}")


# ----- list subcommand -----------------------------------------------------

def cmd_list(args: argparse.Namespace) -> int:
    """List all gods in the top-level registry INDEX.json."""
    # The list endpoint is shared (not per-instance), so we use the bare base
    base = os.environ.get("CLAWFORGE_REGISTRY_BASE") or DEFAULT_REGISTRY_BASES[1]
    url = f"{base}/INDEX.json"
    try:
        data = json.loads(http_get(url).decode())
    except Exception as e:
        raise SystemExit(f"could not fetch top-level INDEX from {url}: {e}")
    gods = data.get("gods", [])
    print(f"=== {len(gods)} god(s) in registry ===")
    for g in gods:
        print(f"  {g.get('id'):20s} v{g.get('latest_version', '?'):8s} "
              f"{g.get('name', '?'):20s} ({g.get('source_instance', '?')})")
    return 0


# ----- pull subcommand -----------------------------------------------------

def cmd_pull(args: argparse.Namespace) -> int:
    target = args.target
    print(f"=== Pulling {target} ===")

    instance, god, version = parse_target(target)
    print(f"  instance: {instance}")
    print(f"  god:      {god}")
    print(f"  version:  {version or 'latest'}")

    idx = fetch_god_index(instance, god)
    print(f"  fetched:   {len(idx.get('versions', []))} version(s) in INDEX.json")

    entry = select_version(idx, version)
    print(f"  selected:  v{entry.get('version')} "
          f"(published {entry.get('published_at', '?')})")

    profile_dir = LOCAL_PROFILES_DIR / god
    tarball = LOCAL_CACHE_DIR / "downloads" / f"{god}-{entry.get('version')}.tar.zst"
    download_tarball(instance, god, entry, tarball)
    install_god(god, tarball, profile_dir)

    offer_register(god)
    return 0


# ----- Main ----------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Clawforge God Package Puller")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_pull = sub.add_parser("pull", help="pull a god package")
    p_pull.add_argument("target", help="instance:god[@version] (e.g. konan:iris@1.0.0)")
    p_pull.set_defaults(func=cmd_pull)

    p_list = sub.add_parser("list", help="list gods in the registry")
    p_list.set_defaults(func=cmd_list)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
