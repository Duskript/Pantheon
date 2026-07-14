#!/usr/bin/env python3
"""
pool-patch.py — Credential-pool patcher for Hermes profiles.

Inserts a new API key into a Hermes profile's `credential_pool.opencode-go`
list at priority 0 (highest), bumping all existing entries down by one so
they become fallbacks. Useful when an existing pool of API keys is
exhausted and you need to slot a fresh one in as primary.

Usage
-----

Dry-run (show the diff without writing):

    OPENCODE_GO_NEW_KEY=sk-... python3 pool-patch.py \\
        --profile hephaestus --dry-run

Patch a single profile (default = hephaestus):

    python3 pool-patch.py --profile hephaestus \\
        --key-file /tmp/new-key.txt

Patch every profile under ``~/.hermes/profiles/`` that has an
``opencode-go`` pool entry:

    python3 pool-patch.py --all-profiles

Key can come from three places (in priority order):
1. ``--key-file PATH`` — read from file (safest — not in argv / shell history)
2. ``--key KEY`` — direct (avoid: ends up in shell history)
3. ``OPENCODE_GO_NEW_KEY`` env var (good for cron / scripting)

The patch is **atomic** — write to ``auth.json.tmp``, then rename over
the original. File permissions are reset to ``0o600`` after write (matches
the existing perms on these files).

Schema note
-----------
The ``credential_pool`` block in ``~/.hermes/profiles/<name>/auth.json``
follows this shape for ``opencode-go``:

.. code-block:: json

    {
      "id": "abcdef",
      "label": "opencode-go-key-N",
      "auth_type": "api_key",
      "priority": 0,
      "source": "manual",
      "access_token": "sk-...",
      "base_url": "https://opencode.ai/zen/go/v1",
      "last_status": "exhausted" | null,
      "last_status_at": <unix_ts> | null,
      "last_error_code": 401 | 429 | null,
      "last_error_reason": "CreditsError" | "GoUsageLimitError" | null,
      "last_error_message": "...",
      "last_error_reset_at": <unix_ts> | null,
      "request_count": <int>
    }

The patcher does NOT touch ``last_status``, ``last_error_*``, or
``request_count`` on existing entries — those are the system's tracking
that says "this key is exhausted, let it reset." When
``last_error_reset_at`` expires, the pool will retry them automatically.
We only bump their ``priority``.

Reversibility
-------------
The script is reversible: re-running it with the OLD key in
``OPENCODE_GO_NEW_KEY`` would put the old key at priority 0 again. For
true rollback, restore from backup (``auth.json.bak`` files exist in
each profile directory) or from git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import time
from pathlib import Path


def _new_id() -> str:
    """Generate a 6-char hex id matching the format of existing pool entries."""
    return secrets.token_hex(3)


def _key_fingerprint(key: str) -> str:
    """SHA-256 first 16 hex chars — matches the existing fingerprint style."""
    return "sha256:" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _add_key_to_pool(
    pool_path: Path,
    key: str,
    profile: str,
    dry_run: bool = False,
) -> dict:
    """Insert a new opencode-go key at priority 0 in ``pool_path``.

    Bumps all existing entries' priorities by 1 (so what was priority 0
    becomes priority 1, etc.). Updates the ``updated_at`` timestamp at
    the top level. Preserves all existing fields on existing entries
    (especially ``last_status``, ``last_error_*``, ``request_count``)
    so the existing exhaustion tracking keeps working.

    Returns a diff dict describing the change.
    """
    data = json.loads(pool_path.read_text())
    opencode_pool = (
        data.setdefault("credential_pool", {})
            .setdefault("opencode-go", [])
    )

    new_entry = {
        "id": _new_id(),
        "label": "opencode-go-key-fresh",
        "auth_type": "api_key",
        "priority": 0,
        "source": "manual",
        "access_token": key,
        "last_status": None,
        "last_status_at": None,
        "last_error_code": None,
        "last_error_reason": None,
        "last_error_message": None,
        "last_error_reset_at": None,
        "base_url": "https://opencode.ai/zen/go/v1",
        "request_count": 0,
    }

    bumped: list[tuple[str, int, int]] = []
    for entry in opencode_pool:
        old_priority = entry.get("priority", 0)
        new_priority = old_priority + 1
        entry["priority"] = new_priority
        bumped.append(
            (entry.get("label", entry.get("id", "?")), old_priority, new_priority)
        )

    opencode_pool.insert(0, new_entry)
    data["updated_at"] = time.strftime(
        "%Y-%m-%dT%H:%M:%S.000000+00:00", time.gmtime()
    )

    diff = {
        "profile": profile,
        "pool_path": str(pool_path),
        "added": {
            "id": new_entry["id"],
            "label": new_entry["label"],
            "priority": new_entry["priority"],
            "key_fingerprint": _key_fingerprint(key),
        },
        "bumped": bumped,
        "total_keys_in_pool": len(opencode_pool),
    }

    if dry_run:
        return diff

    # Atomic write: serialize to temp file, fsync, then rename over the
    # original. This avoids a half-written auth.json if the process dies
    # mid-write (auth.json corruption = Hermes gateway can't start = bad).
    tmp_path = pool_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    tmp_path.replace(pool_path)
    os.chmod(pool_path, 0o600)
    diff["written"] = True
    return diff


def _resolve_key(args: argparse.Namespace) -> str | None:
    """Pull the API key from --key-file, --key, or OPENCODE_GO_NEW_KEY env."""
    if args.key_file:
        return args.key_file.read_text().strip()
    if args.key:
        return args.key.strip()
    env_key = os.environ.get("OPENCODE_GO_NEW_KEY", "").strip()
    return env_key or None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add a fresh opencode-go API key to a Hermes profile's credential pool (priority 0).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--profile",
        default="hephaestus",
        help="Hermes profile whose auth.json to patch (default: hephaestus)",
    )
    parser.add_argument(
        "--key",
        help="API key. Prefer --key-file or env var over argv (shell history).",
    )
    parser.add_argument(
        "--key-file",
        type=Path,
        help="Read API key from this file (safest — not in argv/shell history).",
    )
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Patch every profile under ~/.hermes/profiles/* that has an opencode-go pool.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the diff without writing to disk.",
    )
    args = parser.parse_args()

    key = _resolve_key(args)
    if not key:
        print(
            "ERROR: no key provided. Use --key-file PATH, --key KEY, or set OPENCODE_GO_NEW_KEY env var.",
            file=sys.stderr,
        )
        return 2

    if not key.startswith("sk-"):
        print(
            f"WARNING: key doesn't start with 'sk-' — got prefix {key[:6]!r}. "
            f"Continuing anyway — opencode-go keys historically all start with sk-.",
            file=sys.stderr,
        )

    hermes_home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
    profiles_root = hermes_home / "profiles"

    if args.all_profiles:
        targets = sorted([p for p in profiles_root.iterdir() if p.is_dir()])
    else:
        targets = [profiles_root / args.profile]

    rc = 0
    for profile_dir in targets:
        profile_name = profile_dir.name
        pool_path = profile_dir / "auth.json"
        if not pool_path.exists():
            print(f"[{profile_name}] no auth.json — skipping", file=sys.stderr)
            continue
        try:
            data = json.loads(pool_path.read_text())
        except json.JSONDecodeError as e:
            print(f"[{profile_name}] auth.json invalid JSON: {e} — skipping", file=sys.stderr)
            rc = 1
            continue
        if "opencode-go" not in data.get("credential_pool", {}):
            print(f"[{profile_name}] no opencode-go pool — skipping", file=sys.stderr)
            continue

        try:
            diff = _add_key_to_pool(pool_path, key, profile_name, dry_run=args.dry_run)
            verb = "(dry-run) " if args.dry_run else ""
            print(
                f"[{profile_name}] {verb}added {diff['added']['label']} "
                f"({diff['added']['id']}) at priority 0; "
                f"bumped {len(diff['bumped'])} existing keys; "
                f"total pool size: {diff['total_keys_in_pool']}"
            )
            for label, old, new in diff["bumped"]:
                print(f"  - {label}: priority {old} → {new}")
        except Exception as e:
            print(f"[{profile_name}] ERROR: {type(e).__name__}: {e}", file=sys.stderr)
            rc = 1

    return rc


if __name__ == "__main__":
    sys.exit(main())
