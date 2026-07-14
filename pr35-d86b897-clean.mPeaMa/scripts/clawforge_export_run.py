#!/usr/bin/env python3
"""Wrapper that runs a Pass 3 exporter with sentinel-file opt-in.

The sentinel file is `~/.hermes/clawforge/exports/<name>.enabled`.
If the file is missing, the wrapper logs "skipped" and exits 0
(so the timer fires cleanly without doing anything).

This pattern lets us ship Phase 4 timers immediately and have them
just work when the deferred exporters (Pass 3.1) land. Today:
  - forge adjustment exporter: real, ships to forge.adjustment.submitted
  - memory pattern exporter:   placeholder, no source data yet
  - dojo learning exporter:    placeholder, no source data yet

CLI:
    clawforge_export_run.py forge   [extra args]
    clawforge_export_run.py memory  [extra args]
    clawforge_export_run.py dojo    [extra args]

Config (~/.hermes/clawforge.yaml) shape we read:
    pattern_sharing:
      enabled: <bool>                 # master switch
      memory_patterns: <bool>         # per-system opt-in
      forge_adjustments: <bool>
      dojo_learnings: <bool>
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_value(line: str) -> str:
    """Strip the value out of a YAML-style `key: value # comment` line.
    Also strips surrounding quotes and inline comments.
    """
    if ":" not in line:
        return ""
    raw = line.split(":", 1)[1].strip()
    # Strip inline comment (must be preceded by whitespace to avoid # in strings)
    if " #" in raw:
        raw = raw.split(" #", 1)[0].strip()
    # Strip surrounding quotes
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
        raw = raw[1:-1]
    return raw


def _find_value_after_block(key: str, block_name: str) -> str:
    """Find the value of `key` inside the YAML block `block_name:`.
    Returns the raw value string, or "" if not found.

    A "block" is the top-level `block_name:` header and its indented
    children. We stop when we hit a line at the same or lesser indent
    than the block header.
    """
    p = Path.home() / ".hermes" / "clawforge.yaml"
    if not p.exists():
        return ""
    try:
        text = p.read_text()
    except OSError:
        return ""
    in_block = False
    child_indent = None
    for line in text.splitlines():
        if not in_block:
            if line.startswith(block_name + ":"):
                in_block = True
            continue
        # in_block == True: process child lines
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # If this line is at the same or lesser indent than the
        # block header (0), we've left the block
        if not line.startswith(" "):
            return ""
        # Track the indent of the first child to detect when we leave
        current_indent = len(line) - len(line.lstrip(" "))
        if child_indent is None:
            child_indent = current_indent
        elif current_indent < child_indent:
            return ""
        if stripped.startswith(key + ":"):
            return _parse_value(line)
    return ""


def _master_enabled() -> bool:
    """Read the master switch from the clawforge config. Returns
    False (safe default) if anything goes wrong reading the file.
    """
    val = _find_value_after_block("enabled", "pattern_sharing")
    return val.lower() == "true"


def _is_per_system_enabled(name: str) -> bool:
    """Read the per-system opt-in from the clawforge config.
    Returns True if pattern_sharing.<name>_patterns: true.
    """
    key_map = {
        "memory": "memory_patterns",
        "forge":  "forge_adjustments",
        "dojo":   "dojo_learnings",
    }
    needle = key_map.get(name, name)
    val = _find_value_after_block(needle, "pattern_sharing")
    return val.lower() == "true"


def _sentinel_path(name: str) -> Path:
    return Path.home() / ".hermes" / "clawforge" / "exports" / (name + ".enabled")


def _log_skip(name: str, reason: str) -> None:
    print("[" + _now() + "] " + name + " export: SKIPPED (" + reason + ")", flush=True)


def _log_run(name: str) -> None:
    print("[" + _now() + "] " + name + " export: RUNNING", flush=True)


async def _run_actual(name: str) -> int:
    """Run the actual exporter module. Returns 0 on success, 1 on error.
    Imports are lazy so the wrapper exits cleanly when a deferred
    exporter doesn't exist yet.
    """
    sys.path.insert(0, "/home/konan/pantheon")
    sys.path.insert(0, "/home/konan/pantheon/lib")
    if name == "forge":
        try:
            from clawforge.adjustment_exporter import run
        except ImportError as e:
            print("  ERROR importing adjustment_exporter: " + str(e), flush=True)
            return 1
        entry = await run(days=7)
        print("  published " + str(len(entry.get("adjustments", []))) + " adjustment(s)", flush=True)
        return 0
    if name == "memory":
        try:
            from clawforge.pattern_exporter import run
        except ImportError:
            print("  pattern_exporter not implemented yet (deferred to Pass 3.1)", flush=True)
            return 0
        entry = await run(days=7)
        print("  published " + str(len(entry.get("patterns", []))) + " pattern(s)", flush=True)
        return 0
    if name == "dojo":
        try:
            from clawforge.learning_exporter import run
        except ImportError:
            print("  learning_exporter not implemented yet (deferred to Pass 3.1)", flush=True)
            return 0
        entry = await run(days=7)
        print("  published " + str(len(entry.get("learnings", []))) + " learning(s)", flush=True)
        return 0
    print("  unknown exporter name: " + name, flush=True)
    return 1


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: clawforge_export_run.py {forge|memory|dojo}", flush=True)
        return 1
    name = sys.argv[1]
    # Master switch (from config)
    if not _master_enabled():
        _log_skip(name, "pattern_sharing.enabled = false in config")
        return 0
    # Per-system opt-in (from config)
    if not _is_per_system_enabled(name):
        _log_skip(name, "per-system opt-in for " + name + " is false in config")
        return 0
    # Sentinel file (manual switch)
    sentinel = _sentinel_path(name)
    if not sentinel.exists():
        _log_skip(name, "sentinel file missing: " + str(sentinel))
        return 0
    # All gates passed — run
    _log_run(name)
    return asyncio.run(_run_actual(name))


if __name__ == "__main__":
    sys.exit(main())
