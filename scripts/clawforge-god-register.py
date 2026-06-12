#!/usr/bin/env python3
"""
Clawforge God Register — v0.3.0

After `clawforge-god-puller.py pull konan:iris@1.0.0` extracts a god
into ~/.hermes/profiles/<god>/, this command adds the canonical entry
to gods/gods.yaml so the god shows up in `clawforge who`.

Behavior:
  - Reads ~/.hermes/profiles/<god>/god.yaml for the canonical metadata
    (name, author, model, description)
  - Reads the first 200 chars of SOUL.md to seed a short description
    if god.yaml doesn't have one
  - Adds an entry under `gods:` with sensible defaults
  - Does NOT auto-start any hermes-gateway service (user runs that manually)
  - Does NOT overwrite an existing entry unless --force is given

Usage:
    clawforge-god-register.py <god_id> [--registry PATH] [--profile PATH] [--force]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml


# ----- Paths ---------------------------------------------------------------

DEFAULT_REGISTRY = Path.home() / "pantheon" / "gods" / "gods.yaml"
DEFAULT_PROFILE_DIR = Path.home() / ".hermes" / "profiles"


# ----- Helpers -------------------------------------------------------------

def _safe_yaml_load(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text()) or {}


def _shorten(text: str, max_len: int = 200) -> str:
    """Collapse whitespace and truncate to a one-liner."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len - 1].rstrip() + "…"
    return text


def _read_soul_excerpt(profile_dir: Path, max_len: int = 200) -> str:
    soul = profile_dir / "SOUL.md"
    if not soul.exists():
        return ""
    # Skip the first H1 heading line if present
    lines = soul.read_text().splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        return _shorten(s, max_len)
    return ""


def build_entry(god_id: str, profile_dir: Path) -> dict:
    """Build a gods.yaml entry from the profile's metadata."""
    god_yaml = _safe_yaml_load(profile_dir / "god.yaml")
    if not god_yaml:
        raise SystemExit(f"no god.yaml in {profile_dir}")
    if god_yaml.get("id") and god_yaml["id"] != god_id:
        print(f"warning: god.yaml id={god_yaml['id']!r} != arg={god_id!r}; using arg",
              file=sys.stderr)

    # Try to derive a short description from god.yaml, fall back to SOUL.md
    desc = god_yaml.get("description", "").strip()
    if not desc:
        desc = _read_soul_excerpt(profile_dir)

    return {
        "display_name": god_yaml.get("name", god_id.title()),
        "role": f"Imported from Clawforge ({god_yaml.get('author', '?')})",
        "description": desc,
        "capabilities": [],  # unknown until user inspects
        "status": "imported",
        "source": {
            "origin": "clawforge",
            "publisher": god_yaml.get("author", ""),
            "version": god_yaml.get("version", ""),
            "imported_at": _now_iso(),
        },
        "model": god_yaml.get("model", ""),
    }


def _now_iso() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ----- Atomic YAML write ---------------------------------------------------

def atomic_write_yaml(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, sort_keys=False, default_flow_style=False))
    tmp.rename(path)


# ----- Main flow ------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(description="Clawforge God Register (v0.3.0)")
    p.add_argument("god_id", help="god id (matches profile dir name)")
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY),
                   help=f"path to gods.yaml (default: {DEFAULT_REGISTRY})")
    p.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR),
                   help=f"path to profiles dir (default: {DEFAULT_PROFILE_DIR})")
    p.add_argument("--force", action="store_true",
                   help="overwrite an existing entry")
    args = p.parse_args()

    god_id = args.god_id
    profile_dir = Path(args.profile_dir) / god_id
    registry = Path(args.registry)

    if not profile_dir.is_dir():
        raise SystemExit(f"profile not found: {profile_dir}")
    if not registry.exists():
        raise SystemExit(f"registry not found: {registry}")

    print(f"=== Registering {god_id} ===")
    print(f"  profile: {profile_dir}")
    print(f"  registry: {registry}")

    data = _safe_yaml_load(registry)
    gods = data.setdefault("gods", {})
    if god_id in gods and not args.force:
        print(f"  {god_id!r} already in registry (use --force to overwrite)")
        return 0
    if god_id in gods and args.force:
        print(f"  overwriting existing {god_id!r} entry")

    entry = build_entry(god_id, profile_dir)
    gods[god_id] = entry
    atomic_write_yaml(registry, data)
    print(f"  wrote entry to {registry}")

    # Print next steps
    print()
    print(f"=== Next steps for {god_id} ===")
    print(f"  1. Inspect the generated entry:")
    print(f"     grep -A 12 '  {god_id}:' {registry}")
    print(f"  2. Customize capabilities / role / description as needed")
    print(f"  3. Start the hermes-gateway service (if not already):")
    print(f"     systemctl --user enable --now hermes-gateway-{god_id}.service")
    print(f"  4. Restart clawforge-proxy so the new god appears in `who`:")
    print(f"     systemctl --user restart clawforge-proxy.service")
    print(f"  5. Verify:")
    print(f"     clawforge who | grep {god_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
