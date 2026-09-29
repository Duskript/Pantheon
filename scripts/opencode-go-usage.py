#!/usr/local/lib/hermes-agent/venv/bin/python3
"""OpenCode Go quota windows (5-hour / weekly / monthly) for every credential-pool key.

The Go plan caps usage at $12 per 5 hours, $30 weekly and $60 monthly, and the provider reports
each window as a *used percentage* on ``GET https://opencode.ai/zen/go/v1/usage``. The windows
belong to the API KEY, not to the account, and the Pantheon fleet rotates round-robin across every
``opencode-go`` key in the credential pool — so one key's percentage is not the fleet's picture.

Read-only: it fetches quota, it never spends tokens and never writes pool state. It reuses the same
helpers as ``/usage`` in Hermes so the numbers cannot drift from what a god reports.

Usage:
    opencode-go-usage.py                     # this profile: per-key table + the /usage block
    opencode-go-usage.py --json              # machine-readable, for cron/watchdogs
    opencode-go-usage.py --all-profiles      # every Hermes profile's own pool, grouped by profile
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys

# Private helpers on purpose: this script must agree with `/usage` exactly, and a second
# implementation of the same endpoint is a guaranteed future drift.
from agent.account_usage import (
    _OPENCODE_GO_DEFAULT_BASE_URL,
    _opencode_go_payload,
    _opencode_go_pool_entries,
    _opencode_go_usage_url,
    _opencode_go_windows,
    fetch_account_usage,
    render_account_usage_lines,
)

_TIMEOUT = 15.0
_WINDOW_ORDER = ("5-hour", "Weekly", "Monthly")


def collect(base_url: str | None = None) -> list[dict]:
    """One record per distinct pool key, in pool order. Never raises: a dead key reports ``error``."""
    records: list[dict] = []
    for label, token in _opencode_go_pool_entries():
        record: dict = {"key": label}
        try:
            windows, notes = _opencode_go_windows(
                _opencode_go_payload(token, _opencode_go_usage_url(base_url), timeout=_TIMEOUT)
            )
        except Exception as exc:  # network / auth / shape — report, never abort the sweep
            record["error"] = f"{type(exc).__name__}: {exc}"
            records.append(record)
            continue
        record["windows"] = {
            w.label: {
                "used_percent": w.used_percent,
                "remaining_percent": None if w.used_percent is None else max(0, round(100 - w.used_percent)),
                "resets_at": w.reset_at.isoformat() if w.reset_at else None,
                "status": w.detail,
            }
            for w in windows
        }
        record["notes"] = notes
        records.append(record)
    return records


def render(records: list[dict]) -> str:
    lines = [f"OpenCode Go quota — {len(records)} key(s) in the credential pool", ""]
    for record in records:
        lines.append(record["key"])
        if "error" in record:
            lines.append(f"    unavailable — {record['error']}")
            continue
        for label in _WINDOW_ORDER:
            window = record["windows"].get(label)
            if window is None:
                continue
            remaining, used = window["remaining_percent"], window["used_percent"]
            if remaining is None:
                lines.append(f"    {label:<8} unavailable")
                continue
            reset = f"  resets {window['resets_at']}" if window["resets_at"] else ""
            # ``:g`` keeps the provider's own precision: 10 not 10.0, but 0.4 stays 0.4.
            lines.append(f"    {label:<8} {remaining:>3}% left ({used:g}% used){reset}")
        for note in record["notes"]:
            lines.append(f"    ! {note}")
    return "\n".join(lines)


def profile_homes() -> list[tuple[str, str]]:
    """``(name, HERMES_HOME)`` for the default profile plus every profile that has a config.yaml."""
    hermes = pathlib.Path.home() / ".hermes"
    homes = [("default", str(hermes))]
    profiles = hermes / "profiles"
    if profiles.is_dir():
        homes += [(d.name, str(d)) for d in sorted(profiles.iterdir()) if (d / "config.yaml").is_file()]
    return homes


def collect_all_profiles(base_url: str | None = None) -> list[dict]:
    """Re-exec this script once per profile: the credential pool is resolved from ``HERMES_HOME`` at
    import time, so a profile's pool cannot be read from inside this process."""
    out: list[dict] = []
    for name, home in profile_homes():
        cmd = [sys.executable, os.path.abspath(__file__), "--json"]
        if base_url:
            cmd += ["--base-url", base_url]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                                  env={**os.environ, "HERMES_HOME": home})
            payload = json.loads(proc.stdout) if proc.returncode == 0 else {}
        except (subprocess.TimeoutExpired, ValueError):
            payload = {}
        out.append({"profile": name, "keys": payload.get("keys", [])})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "OpenCode Go quota windows (5-hour / weekly / monthly) for every credential-pool key. "
            "Read-only: fetches quota from the provider, never spends tokens, never writes pool state."
        )
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--base-url", default=None,
                        help=f"Go inference root (default {_OPENCODE_GO_DEFAULT_BASE_URL})")
    parser.add_argument("--usage-block", action="store_true",
                        help="also print the exact account-limits block /usage renders")
    parser.add_argument("--all-profiles", action="store_true",
                        help="sweep every Hermes profile's own credential pool")
    args = parser.parse_args(argv)

    if args.all_profiles:
        profiles = collect_all_profiles(args.base_url)
        if args.json:
            print(json.dumps({"provider": "opencode-go", "profiles": profiles}, indent=2))
            return 0
        for entry in profiles:
            keys = entry["keys"]
            if not keys:
                print(f"{entry['profile']}: no opencode-go keys in pool")
                continue
            print(f"=== {entry['profile']} ===")
            print(render(keys))
            print()
        return 0

    records = collect(args.base_url)
    if args.json:
        print(json.dumps({"provider": "opencode-go", "keys": records}, indent=2))
        return 0

    print(render(records))
    if args.usage_block:
        snapshot = fetch_account_usage("opencode-go", base_url=args.base_url)
        print("\n" + "\n".join(render_account_usage_lines(snapshot, markdown=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
