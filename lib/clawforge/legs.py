"""Shared three-leg export machinery for the Clawforge Pass 3 exporters.

WHY THIS MODULE EXISTS
----------------------
Each exporter (`adjustment_exporter`, `pattern_exporter`, `learning_exporter`)
has to do the same three things with a payload:

  1. LOCAL ARTIFACT — write down what this instance produced. Always runs.
  2. LOCAL RELAY    — publish to the local NATS named by the `relay:` block in
                      `~/.hermes/clawforge.yaml`. Always runs, unauthenticated.
                      This is the leg local consumers read.
  3. FEDERATION     — transmit to a peer instance. Requires an explicitly
                      configured `federation:` host AND the `pattern_sharing`
                      opt-in.

The three exporters used to implement that separately, and the copies diverged:
`adjustment_exporter` was fixed on 2026-09-22 while the other two still defaulted
to a hardcoded peer address and had no local leg at all. One defect, three
copies, one fixed.

Repairing copies one at a time does not close the class, because the next
exporter is cloned from whichever copy is nearest. So the legs live here, once,
and every exporter calls `run_legs()`. An exporter that does not call it shows up
as a lane with no local leg.

GATING RULES (the part that was wrong)
--------------------------------------
- `pattern_sharing.enabled` gates ONLY the federation leg. It used to gate the
  whole run, so a cross-instance PRIVACY switch silently disabled local
  self-improvement — and the wrapper logged SKIPPED while exiting 0, so systemd
  reported the unit healthy for months.
- The per-system opt-in (`pattern_sharing.<system>`) also gates ONLY the
  federation leg. Reading it as a run gate is the same defect one level down.
- The federation host has NO default. A hardcoded tailnet address made a peer
  instance the silent destination of a purely local run. If federation is
  requested without a configured peer, the leg is refused with a note.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("clawforge-legs")

#: ~/.hermes/clawforge.yaml — relay + federation + pattern_sharing blocks.
CLAWFORGE_CONFIG = Path(os.path.expanduser("~/.hermes/clawforge.yaml"))

#: Where the local-artifact leg writes, one file per exporter.
LOCAL_ARTIFACT_DIR = Path(os.path.expanduser("~/.hermes/pantheon"))

#: Per-exporter wiring: artifact stem, `pattern_sharing` opt-in key, NATS subject.
EXPORTERS: dict[str, dict[str, str]] = {
    "forge": {
        "artifact": "forge-adjustments",
        "sharing_key": "forge_adjustments",
        "subject": "forge.adjustment.submitted",
    },
    "memory": {
        "artifact": "memory-patterns",
        "sharing_key": "memory_patterns",
        "subject": "memory.pattern.submitted",
    },
    "dojo": {
        "artifact": "dojo-learnings",
        "sharing_key": "dojo_learnings",
        "subject": "dojo.learning.submitted",
    },
}

#: Which `pattern_sharing` key opts a given exporter's data into sharing.
SHARING_OPT_IN: dict[str, str] = {
    name: spec["sharing_key"] for name, spec in EXPORTERS.items()
}


# ---------------------------------------------------------------------------
# Config + target resolution
# ---------------------------------------------------------------------------

def config() -> dict:
    """Load ~/.hermes/clawforge.yaml. Returns {} when absent or unparseable.

    Parsed with a real YAML loader on purpose: the wrapper in scripts/ hand-rolls
    an indentation walk, and that is how a whole `pattern_sharing` block went
    missing without anyone noticing.
    """
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(CLAWFORGE_CONFIG.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # unreadable or invalid config must not crash a run
        log.warning("could not read %s: %s", CLAWFORGE_CONFIG, exc)
        return {}


def local_nats_url() -> str:
    """The local relay endpoint, from the `relay:` block. Defaults to loopback."""
    relay = config().get("relay") or {}
    host = relay.get("host") or "127.0.0.1"
    port = relay.get("port") or 4222
    return "nats://" + str(host) + ":" + str(port)


def sharing_enabled() -> bool:
    """True only when `pattern_sharing.enabled: true` is explicitly present."""
    return bool((config().get("pattern_sharing") or {}).get("enabled"))


def sharing_allowed_for(name: str) -> bool:
    """Whether THIS artifact class may cross the instance boundary.

    Both the master switch and the per-system opt-in must be true.

    These keys live INSIDE the `pattern_sharing` block, so they scope sharing.
    The wrapper used to read them as a gate on producing the artifact at all,
    which is how a sharing setting came to disable local self-improvement — the
    same defect as the master switch, one level down.
    """
    ps = config().get("pattern_sharing") or {}
    return bool(ps.get("enabled")) and bool(ps.get(SHARING_OPT_IN.get(name, name)))


def federation_target() -> tuple[str, str]:
    """(nats_url, bearer_token) for the cross-instance leg.

    Host and port come from the explicit `federation:` block. There is no
    hardcoded default: defaulting the host to a peer's tailnet address made a
    PEER INSTANCE the silent destination of a purely local run.
    """
    fed = config().get("federation") or {}
    host = os.environ.get("CLAWFORGE_NATS_HOST") or fed.get("host") or ""
    port = os.environ.get("CLAWFORGE_NATS_PORT") or fed.get("port") or 4222
    if not host:
        raise SystemExit(
            "federation leg requested but no peer configured: set "
            "`federation: {host: <host>, port: 4222}` in ~/.hermes/clawforge.yaml "
            "or export CLAWFORGE_NATS_HOST"
        )
    return "nats://" + str(host) + ":" + str(port), load_token()


# ---------------------------------------------------------------------------
# Token loading (was duplicated byte-for-byte in all three exporters)
# ---------------------------------------------------------------------------

def _find_token_path() -> str:
    """Find the Clawforge token file. Tries:
      1. CLAWFORGE_TOKENS_PATH env var
      2. ~/.hermes/clawforge-tokens.env (Pantheon)
      3. /etc/clawforge/tokens.env (Relay-7)
    Returns the first existing path, or the first candidate if none exist.
    """
    candidates: list[str] = []
    env_path = os.environ.get("CLAWFORGE_TOKENS_PATH")
    if env_path:
        candidates.append(env_path)
    home = os.path.expanduser("~")
    candidates.extend([
        os.path.join(home, ".hermes", "clawforge-tokens.env"),
        os.path.sep + os.path.join("etc", "clawforge", "tokens.env"),
    ])
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0] if candidates else ""


def load_token() -> str:
    """Load the Clawforge client bearer token from the first available token file."""
    path = _find_token_path()
    if not path or not os.path.exists(path):
        raise SystemExit("token file not found (tried CLAWFORGE_TOKENS_PATH, "
                         "~/.hermes/clawforge-tokens.env, /etc/clawforge/tokens.env)")
    expected_key = "CLAWFORGE_CLIENT_TOKEN" + chr(61)
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(chr(35)):
            continue
        if line.startswith(expected_key):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + path)


# ---------------------------------------------------------------------------
# Artifact + publish
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def artifact_path(name: str) -> Path:
    """Local-artifact path for an exporter, e.g. dojo-learnings-latest.json."""
    spec = EXPORTERS.get(name)
    if spec is None:
        raise ValueError("unknown exporter: " + repr(name))
    return LOCAL_ARTIFACT_DIR / (spec["artifact"] + "-latest.json")


def write_local_artifact(name: str, entry: dict) -> Path:
    path = artifact_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2, sort_keys=True))
    return path


async def publish(nc, subject: str, entry: dict) -> None:
    """Publish a single submission to NATS."""
    data = json.dumps(entry).encode("utf-8")
    await nc.publish(subject, data)


# ---------------------------------------------------------------------------
# The three legs
# ---------------------------------------------------------------------------

async def run_legs(
    name: str,
    entry: dict,
    *,
    share: Optional[bool] = None,
    subject: Optional[str] = None,
) -> dict[str, Any]:
    """Run all three legs for one exporter payload and report which fired.

    `share` overrides config detection. None means read the per-system
    `pattern_sharing` opt-in via `sharing_allowed_for(name)`.

    Returns a summary dict. `published_local` is the one that matters for local
    self-improvement; `published_remote` covers the federation leg. A run whose
    local leg did not publish has not done its job — callers should treat that as
    failure rather than success.
    """
    import nats  # type: ignore

    spec = EXPORTERS.get(name)
    if spec is None:
        raise ValueError("unknown exporter: " + repr(name))
    subject = subject or spec["subject"]

    result: dict[str, Any] = {
        "exporter": name,
        "entry": entry,
        "subject": subject,
        "artifact": "",
        "published_local": False,
        "published_remote": False,
        "local_url": local_nats_url(),
        "notes": [],
    }

    # Leg 1 — local artifact. Always. No switch can turn this off.
    try:
        result["artifact"] = str(write_local_artifact(name, entry))
    except OSError as exc:
        result["notes"].append("local artifact write failed: " + str(exc))

    # Leg 2 — local relay. Always, unauthenticated.
    try:
        nc = await nats.connect(result["local_url"], name="clawforge-" + name + "-local")
        try:
            await publish(nc, subject, entry)
            await nc.flush()
            result["published_local"] = True
            log.info("published %s to LOCAL relay %s", subject, result["local_url"])
        finally:
            await nc.drain()
    except Exception as exc:
        result["notes"].append(
            "local relay publish failed: " + type(exc).__name__ + ": " + str(exc)
        )

    # Leg 3 — federation. Explicitly gated; a local run must never require it.
    want_share = sharing_allowed_for(name) if share is None else bool(share)
    if not want_share:
        result["notes"].append(
            "federation leg skipped: pattern_sharing is not armed for '" + name + "' "
            "(local artifact + local relay ran)"
        )
        return result

    try:
        url, token = federation_target()
    except SystemExit as exc:
        result["notes"].append("federation leg skipped: " + str(exc))
        return result

    try:
        nc = await nats.connect(url, token=token, name="clawforge-" + name + "-federation")
        try:
            await publish(nc, subject, entry)
            await nc.flush()
            result["published_remote"] = True
            log.info("published %s to FEDERATION %s", subject, url)
        finally:
            await nc.drain()
    except Exception as exc:
        result["notes"].append(
            "federation publish failed: " + type(exc).__name__ + ": " + str(exc)
        )
    return result
