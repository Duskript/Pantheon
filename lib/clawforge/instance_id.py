"""Clawforge anonymous instance identifier.

Per the meta-learning spec (section 3.5), the instance_id is the
first 12 hex characters of sha256(machine_id). This gives ~48 bits
of entropy, which is enough to distinguish instances in a federation
of a few dozen without collision risk, but cannot be reversed to
identify the host.

Consistent across restarts (machine_id is stable on Linux). Falls
back to a synthetic hash for containers / non-Linux where
/etc/machine-id might not exist.

Usage:
    from clawforge.instance_id import get_instance_id
    inst = get_instance_id()  # e.g. "a3f8c291b4c7"
"""
from __future__ import annotations

import hashlib
import os


def _read_machine_id() -> str:
    """Read /etc/machine-id (Linux) or return a stable fallback.

    The fallback is generated from a constant so that:
      - All processes on the same machine get the same fallback
      - A fresh container on a different host gets a different one
    """
    paths = ["/etc/machine-id", "/var/lib/dbus/machine-id"]
    for p in paths:
        try:
            with open(p) as f:
                return f.read().strip()
        except (FileNotFoundError, PermissionError, OSError):
            continue
    # Fallback: hash a constant that includes the hostname, so two
    # containers on the same host share a fallback but different
    # hosts diverge. NOT a security boundary; just a stable label.
    seed = "container:" + str(os.uname())  # noqa: F821 — POSIX-only
    return "container-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def get_instance_id() -> str:
    """Return the anonymous instance ID.

    First 12 hex chars of sha256(machine_id). Stable across restarts
    on the same host. Cannot be reversed without brute-forcing 2^48
    possibilities.
    """
    machine_id = _read_machine_id()
    full = hashlib.sha256(machine_id.encode("utf-8")).hexdigest()
    return full[:12]


if __name__ == "__main__":
    # Self-test
    inst = get_instance_id()
    assert len(inst) == 12, f"expected 12 hex chars, got {len(inst)}: {inst!r}"
    assert all(c in "0123456789abcdef" for c in inst), f"non-hex chars: {inst!r}"
    # Stability: call twice, get the same answer
    assert get_instance_id() == inst, "instance_id is not stable"
    print("instance_id:", inst)
    print("self-test OK")
