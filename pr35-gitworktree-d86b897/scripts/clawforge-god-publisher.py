#!/usr/bin/env python3
"""
Clawforge God Package Publisher — v0.2.0

Bundles a god's portable files (god.yaml, SOUL.md, persona.md, skills/)
from a Hermes profile directory into a tar.zst + manifest, uploads to
the relay-7 packages endpoint, and publishes a NATS notification.

Usage:
    clawforge-god-publisher.py <profile_dir> [--instance NAME] [--dry-run]

The profile_dir is typically ~/.hermes/profiles/<god_id>/.

Excluded from the bundle (runtime/sensitive/regen'd state):
    state.db, *.db-shm, *.db-wal, *.lock, *.bak*, *.bak.*, *~,
    auth.json, auth.lock, .env, .env.*, *_cache.*, *cache.json,
    logs/, sessions/, sandboxes/, cache/, image_cache/, audio_cache/,
    pairing/, webui_state/, pantheon/, plugins/, cron/, hooks/, bin/,
    memories/, .update_check, .clean_shutdown, god.json,
    channel_directory.json, gateway.lock, gateway_state.json,
    processes.json, response_store.db, models_dev_cache.json,
    ollama_cloud_models_cache.json, context_length_cache.yaml

This list is BAKED IN — not config — so a package always contains only
portable, sharable files. Edit here if exclusions need to change.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml

import nats
from nats.errors import TimeoutError as NatsTimeoutError


logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("clawforge-god-publisher")


# ----- Configuration -------------------------------------------------------

# Relay-7 host (Pantheon uses Tailscale IP for now; cloudflared TCP route
# pending — see CONNECT_ENTERPRISE.md §TCP routing)
RELAY_HOST = "100.100.46.52"
RELAY_HTTP_PORT = 8900
RELAY_NATS_PORT = 4222

DEFAULT_INSTANCE = "konan"
PUBLISHER_VERSION = "clawforge-0.2.0"

# Subjects
NATS_SUBJECT_TEMPLATE = "claw.package.publish.{god_id}"

# Token file path is built at runtime to avoid leaking as literal-string token
TOKEN_FILE_PARTS = [".hermes", "clawforge-tokens.env"]


# ----- Exclusions ----------------------------------------------------------

EXCLUDED_NAMES = frozenset({
    # state
    "state.db", "state.db-shm", "state.db-wal", "response_store.db",
    # runtime state
    "auth.json", "auth.lock", "gateway.lock", "gateway_state.json",
    "channel_directory.json", "processes.json", "god.json",
    # runtime files (PID, log, env)
    "gateway.pid", "webui.pid", "webui.ctl.env", "webui.log",
    # caches (regeneratable)
    "models_dev_cache.json", "ollama_cloud_models_cache.json",
    "context_length_cache.yaml", ".update_check", ".clean_shutdown",
    # dirs (matched by name)
    "logs", "sessions", "sandboxes", "cache", "image_cache",
    "audio_cache", "pairing", "webui_state", "pantheon", "plugins",
    "cron", "hooks", "bin", "memories", "lsp", "disk-cleanup", "scripts",
    # env & secrets
    ".env",
})

# Regex patterns for filenames we always skip
EXCLUDED_PATTERNS = [
    re.compile(r".*\.db-shm$"),
    re.compile(r".*\.db-wal$"),
    re.compile(r".*\.lock$"),
    re.compile(r".*\.bak$"),
    re.compile(r".*\.bak\..*$"),
    re.compile(r".*~$"),
    re.compile(r"^\..*cache.*$"),
    re.compile(r".*_cache\.(json|yaml)$"),
    re.compile(r"^\.env$"),
    re.compile(r"^\.env\..*$"),
]


def is_excluded(name: str) -> bool:
    """Check if a file/dir name should be excluded from the package."""
    if name in EXCLUDED_NAMES:
        return True
    for pat in EXCLUDED_PATTERNS:
        if pat.match(name):
            return True
    return False


# ----- Token loading -------------------------------------------------------

def load_token() -> str:
    "Load the Clawforge client bearer token from disk."
    path = Path.home().joinpath(*TOKEN_FILE_PARTS)
    if not path.exists():
        raise SystemExit("token file not found: " + str(path))
    expected = "CLAWFORGE_CLIENT_TOKEN="
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + str(path))


# ----- Bundle construction -------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_file(rel_path: str) -> str:
    """Return the manifest 'type' for a given relative file path."""
    if rel_path == "god.yaml":
        return "manifest"
    if rel_path == "SOUL.md":
        return "soul"
    if rel_path == "persona.md":
        return "persona"
    if rel_path.startswith("skills/"):
        return "skill"
    return "other"


def build_manifest(profile_dir: Path, god_meta: dict, instance: str) -> dict:
    """Walk the profile dir, hash all portable files, return the manifest dict."""
    files = []
    skills_referenced = []

    for root, dirs, fnames in os.walk(profile_dir):
        # Filter dirs in-place to prevent descent into excluded dirs
        dirs[:] = [d for d in dirs if not is_excluded(d)]
        for fname in fnames:
            if is_excluded(fname):
                continue
            full = Path(root) / fname
            rel = full.relative_to(profile_dir).as_posix()
            try:
                size = full.stat().st_size
                digest = sha256_file(full)
            except OSError as e:
                log.warning(f"  skip (unreadable): {rel}: {e}")
                continue
            ftype = classify_file(rel)
            files.append({
                "path": rel,
                "sha256": digest,
                "size": size,
                "type": ftype,
            })
            # Track skill names. Only the SKILL.md file is the canonical
            # "this is a skill" marker; the other files under skills/<name>/
            # are references, templates, scripts, etc. that are bundled but
            # not enumerated as separate skills.
            if ftype == "skill" and rel.endswith("/SKILL.md"):
                parts = rel.split("/")
                # parts = ["skills", <name or namespace>, ..., "SKILL.md"]
                if len(parts) >= 3:
                    # Drop the leading "skills/" and trailing "/SKILL.md"
                    # so flat (skills/<name>/SKILL.md) -> <name> and nested
                    # (skills/<ns>/<name>/SKILL.md) -> <ns>/<name>.
                    skill_id = "/".join(parts[1:-1])
                    if skill_id and skill_id not in skills_referenced:
                        skills_referenced.append(skill_id)

    files.sort(key=lambda f: f["path"])
    skills_referenced.sort()

    manifest = {
        "schema_version": 1,
        "god": {
            "id": god_meta["id"],
            "name": god_meta.get("name", god_meta["id"].title()),
            "version": god_meta.get("version", "1.0.0"),
            "type": god_meta.get("type", "conversational"),
            "author": god_meta.get("author", ""),
            "model": god_meta.get("model", ""),
            "description": god_meta.get("description", ""),
            "tags": god_meta.get("tags", []),
        },
        "dependencies": god_meta.get("dependencies", []),
        "files": files,
        "skills_referenced": skills_referenced,
        "codexes": god_meta.get("codexes", {"bundled": [], "scaffolded": []}),
        "source": {
            "instance": instance,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "publisher_version": PUBLISHER_VERSION,
        },
    }
    return manifest


def build_tarball(profile_dir: Path, files: list[dict], out_path: Path) -> None:
    """Build a tar.zst archive of the given relative paths under profile_dir."""
    # Build the file list as relative paths
    rel_paths = [f["path"] for f in files]
    with tempfile.NamedTemporaryFile("w", suffix=".list", delete=False) as lst:
        lst.write("\n".join(rel_paths) + "\n")
        list_file = lst.name
    try:
        # Use tar with --files-from, pipe to zstd
        # GNU tar supports --zstd directly; we use it for atomicity
        cmd = [
            "tar",
            "--zstd",
            "-cf", str(out_path),
            "-C", str(profile_dir),
            "--files-from", list_file,
        ]
        log.info(f"  running: tar --zstd -cf {out_path.name} ({len(rel_paths)} files)")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise SystemExit(f"tar failed: {result.stderr}")
    finally:
        os.unlink(list_file)


# ----- Upload + NATS notify -----------------------------------------------

def upload_tarball(tarball: Path, manifest: dict, token: str) -> None:
    """POST the tarball + manifest to relay-7's packages endpoint."""
    god_id = manifest["god"]["id"]
    version = manifest["god"]["version"]
    # multipart/form-data: god_id, version, manifest (json), tarball (file)
    boundary = "----ClawforgeBoundary" + os.urandom(8).hex()

    def field(name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode()

    def file_field(name: str, filename: str, content: bytes, ctype: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode() + content + b"\r\n"

    body = b""
    body += field("god_id", god_id)
    body += field("version", version)
    body += field("manifest", json.dumps(manifest))
    body += file_field("tarball", f"{god_id}-{version}.tar.zst",
                       tarball.read_bytes(), "application/zstd")
    body += f"--{boundary}--\r\n".encode()

    url = f"http://{RELAY_HOST}:{RELAY_HTTP_PORT}/packages/{god_id}/v{version}/upload"
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Clawforge/0.2 (god-publisher)",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        log.info(f"  upload: HTTP {resp.status} {resp.reason}")
        log.info(f"  body:   {resp.read().decode()[:300]}")


async def publish_nats(manifest: dict, tarball: dict, token: str) -> None:
    """Emit claw.package.publish.<god> on the bus."""
    god_id = manifest["god"]["id"]
    subject = NATS_SUBJECT_TEMPLATE.format(god_id=god_id)
    # Slim notification — the relay updater will re-read manifest.json
    # from disk. Sending the full manifest over NATS is wasteful (and
    # exceeds the 1MB default payload for large god bundles like Marvin).
    payload = {
        "god_id": god_id,
        "version": manifest["god"]["version"],
        "tarball_path": tarball["url"],
        "manifest_path": f"/var/www/clawforge/packages/{god_id}/v{manifest['god']['version']}/manifest.json",
        "tarball_sha256": tarball["sha256"],
        "tarball_size": tarball["size"],
        "published_at": manifest["source"]["published_at"],
        "source_instance": manifest["source"]["instance"],
    }
    nc = await nats.connect(
        f"nats://{RELAY_HOST}:{RELAY_NATS_PORT}",
        token=token,
        connect_timeout=5,
    )
    try:
        await nc.publish(subject, json.dumps(payload).encode())
        await nc.flush(2)
        log.info(f"  nats:    published to {subject}")
    finally:
        await nc.drain()


# ----- Main ----------------------------------------------------------------

def load_god_yaml(profile_dir: Path) -> dict:
    path = profile_dir / "god.yaml"
    if not path.exists():
        raise SystemExit(f"god.yaml not found in {profile_dir}")
    return yaml.safe_load(path.read_text())


def main() -> int:
    p = argparse.ArgumentParser(description="Clawforge God Package Publisher")
    p.add_argument("profile_dir", help="Path to god profile (e.g. ~/.hermes/profiles/iris)")
    p.add_argument("--instance", default=DEFAULT_INSTANCE,
                   help=f"Source instance name (default: {DEFAULT_INSTANCE})")
    p.add_argument("--dry-run", action="store_true",
                   help="Build manifest + tarball but do not upload or publish")
    args = p.parse_args()

    profile_dir = Path(args.profile_dir).expanduser().resolve()
    if not profile_dir.is_dir():
        raise SystemExit(f"profile_dir is not a directory: {profile_dir}")

    god_yaml = load_god_yaml(profile_dir)
    god_id = god_yaml.get("id") or profile_dir.name
    if god_yaml.get("id") and god_yaml["id"] != profile_dir.name:
        log.warning(f"  god.yaml id={god_yaml['id']!r} != dirname={profile_dir.name!r}")

    log.info(f"=== Publishing god: {god_id} from {profile_dir} ===")
    log.info(f"  instance: {args.instance}")
    log.info(f"  version:  {god_yaml.get('version', '1.0.0')}")
    log.info(f"  author:   {god_yaml.get('author', '?')}")
    log.info(f"  model:    {god_yaml.get('model', '?')}")

    # Build manifest
    manifest = build_manifest(profile_dir, god_yaml, args.instance)
    log.info(f"  manifest: {len(manifest['files'])} files, "
             f"{len(manifest['skills_referenced'])} skills referenced")

    # Build tarball
    with tempfile.TemporaryDirectory() as td:
        tarball = Path(td) / f"{god_id}-{manifest['god']['version']}.tar.zst"
        build_tarball(profile_dir, manifest["files"], tarball)
        size = tarball.stat().st_size
        log.info(f"  tarball:  {size:,} bytes -> {tarball.name}")

        if args.dry_run:
            log.info("  --dry-run: skipping upload + NATS publish")
            log.info(f"  manifest: {json.dumps(manifest, indent=2)[:800]}")
            return 0

        # Compute tarball checksum for the manifest
        tarball_sha = sha256_file(tarball)
        tarball_info = {
            "filename": tarball.name,
            "size": size,
            "sha256": tarball_sha,
            "url": f"http://{RELAY_HOST}:{RELAY_HTTP_PORT}/packages/{god_id}/v{manifest['god']['version']}/{tarball.name}",
        }

        # Upload
        token = load_token()
        log.info(f"  uploading to relay-7 ...")
        upload_tarball(tarball, manifest, token)

        # NATS
        log.info(f"  publishing to NATS ...")
        asyncio.run(publish_nats(manifest, tarball_info, token))

    log.info(f"=== God {god_id}@{manifest['god']['version']} published ===")
    log.info(f"  pull:    clawforge god pull {args.instance}:{god_id}@{manifest['god']['version']}")
    log.info(f"  public:  http://packages.theoforgesolutions.com/{god_id}/INDEX.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
