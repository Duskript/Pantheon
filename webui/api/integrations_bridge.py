"""integrations_bridge.py — Control integrations adapter for the Olympus UI.

Read-only health for Composio and the other external integrations surfaced in
Control → Integrations. No tokens, secrets or credentials are ever exposed:
only booleans, counts and human-readable notes leave this module.

Endpoints:
  GET /api/control/integrations → all integration statuses

Composio specifically:

The Composio bridge (composio-bridge, systemd user unit, http://127.0.0.1:8789)
owns the project API key and the reusable Tool Router Session, so this module
asks the bridge for its state rather than guessing from the environment.  A bare
env-var check cannot tell the three cases apart that actually matter to an
operator:

  * no key configured at all            → ``not_configured``
  * a key is present but Composio said  → ``key_invalid`` (with Composio's own
    it is invalid / the wrong kind         message, e.g. the ``ck_`` vs ``ak_``
                                           project-key mix-up)
  * a live session with N connections   → ``active``
  * the bridge is not running           → ``bridge_unreachable``

See ``docs/COMPOSIO_SETUP.md`` for the operator-facing walkthrough.
"""

from __future__ import annotations

import json
import os
import urllib.request

from api.helpers import bad, j


COMPOSIO_BRIDGE_URL = os.environ.get("COMPOSIO_BRIDGE_URL", "http://127.0.0.1:8789")


def _composio_status():
    """Report Composio bridge state without ever exposing the key.

    Returns a small dict the UI can render directly:

        {"configured": bool, "status": str, "note": str, ...}

    where ``status`` is one of ``not_configured``, ``active``, ``key_invalid``
    or ``bridge_unreachable``.
    """
    key = (
        os.environ.get("COMPOSIO_API_KEY")
        or os.environ.get("COMPOSIO_PROJECT_KEY")
        or ""
    ).strip()
    status = {
        "configured": bool(key),
        "status": "not_configured",
        "note": "Set COMPOSIO_API_KEY (an ak_ project key) to enable",
    }
    if not key:
        return status

    try:
        with urllib.request.urlopen(f"{COMPOSIO_BRIDGE_URL}/health", timeout=4) as resp:
            health = json.load(resp)
        status["bridge"] = True
        status["key_valid"] = bool(health.get("key_valid"))
        status["connections"] = int(health.get("connections") or 0)
        if health.get("composio"):
            status["status"] = "active"
            status["note"] = f"{status['connections']} connection(s)"
        else:
            status["status"] = "key_invalid"
            status["note"] = health.get("error") or "bridge reports no Composio session"
    except Exception as exc:  # noqa: BLE001 — a status endpoint must never raise
        status["bridge"] = False
        status["status"] = "bridge_unreachable"
        status["note"] = (
            f"Composio bridge not reachable on {COMPOSIO_BRIDGE_URL} "
            f"({exc.__class__.__name__}). Start it with: "
            "systemctl --user start composio-bridge"
        )
    return status


def _google_status():
    """Check Google/Gmail integration state."""
    return {
        "account": "pantheon.theoforge@gmail.com",
        "status": "pending_user_setup",
        "services": ["gmail", "drive", "sheets", "calendar"],
        "note": "Account creation requires manual Google signup completion",
    }


def _github_status():
    """Check GitHub integration state."""
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    return {
        "configured": bool(token),
        "status": "active" if token else "not_configured",
    }


def handle_integrations(handler, parsed):
    path = parsed.path
    if path == "/api/control/integrations":
        return j(handler, {
            "integrations": {
                "composio": _composio_status(),
                "google": _google_status(),
                "github": _github_status(),
            }
        })
    return False
