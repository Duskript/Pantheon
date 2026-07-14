
"""integrations_bridge.py — Control integrations adapter for Olympus UI.

Read-only health for Composio, Google/Gmail, and other external
integrations. No tokens, secrets, or credentials exposed.

Endpoints:
  GET /api/control/integrations → all integration statuses
"""

from __future__ import annotations

import os
import json

from api.helpers import bad, j


def _composio_status():
    """Check if Composio is configured (no API key exposed)."""
    api_key = os.environ.get("COMPOSIO_API_KEY")
    return {
        "configured": bool(api_key),
        "status": "active" if api_key else "not_configured",
        "note": "API key present" if api_key else "Set COMPOSIO_API_KEY to enable",
    }


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
