"""n8n REST API client — credential management for Olympus.

Wraps the self-hosted n8n Docker instance at http://localhost:5678.
Uses N8N_API_KEY from environment for authentication.

Flow for OAuth connections:
  1. POST /api/v1/credentials → create credential (type = OAuth2)
  2. n8n returns the credential object with OAuth callback info
  3. User completes OAuth in n8n's web UI (localhost:5678)
  4. GET /api/v1/credentials/{id} → check status (connected/error)

n8n credential type names:
  Provider        → n8n type
  gmail           → gmailOAuth2Api
  github          → githubOAuth2Api
  google_calendar → googleCalendarOAuth2Api
  google_drive    → googleDriveOAuth2Api
  notion          → notionOAuth2Api
  slack           → slackOAuth2Api
  discord         → discordOAuth2Api
  outlook         → microsoftOAuth2Api
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

N8N_BASE = "http://localhost:5678"
N8N_API_BASE = f"{N8N_BASE}/api/v1"
N8N_TIMEOUT = 10  # seconds

# Public-facing n8n URL — used for links returned to the user's browser.
# Override via N8N_PUBLIC_URL env var. Auto-detects Tailscale serve
# (https://pantheon.tail164759.ts.net:5679/) when available.
# Falls back to localhost for direct local access.
_N8N_PUBLIC_URL = os.environ.get("N8N_PUBLIC_URL", "")
if not _N8N_PUBLIC_URL:
    try:
        import subprocess as _sp
        result = _sp.run(
            ["tailscale", "serve", "status"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            # Parse the actual Tailscale URL from serve status output
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith("https://") and ":5679" in line:
                    _N8N_PUBLIC_URL = line.split()[0]
                    break
    except Exception:
        pass
if not _N8N_PUBLIC_URL:
    _N8N_PUBLIC_URL = N8N_BASE  # fallback to localhost


def _load_env_file() -> dict[str, str]:
    """Load N8N_API_KEY from the webui .env file as fallback.

    Reads ~/pantheon/webui/.env and extracts N8N_API_KEY=VALUE lines.
    The key may or may not be prefixed with 'export '.
    """
    env_vars: dict[str, str] = {}
    env_path = Path.home() / "pantheon" / "webui" / ".env"
    try:
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Strip optional 'export ' prefix
                if line.startswith("export "):
                    line = line[7:]
                if "=" in line:
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    env_vars[key] = value
    except Exception:
        pass
    return env_vars


def _get_api_key() -> str:
    """Get N8N_API_KEY from environment, falling back to .env file."""
    key = os.environ.get("N8N_API_KEY", "")
    if not key:
        env_file = _load_env_file()
        key = env_file.get("N8N_API_KEY", "")
    return key

# Provider → n8n credential type mapping
PROVIDER_TO_N8N_TYPE: dict[str, str] = {
    "gmail": "gmailOAuth2Api",
    "github": "githubOAuth2Api",
    "google_calendar": "googleCalendarOAuth2Api",
    "google_cal": "googleCalendarOAuth2Api",
    "google_drive": "googleDriveOAuth2Api",
    "google_docs": "googleDriveOAuth2Api",
    "notion": "notionOAuth2Api",
    "slack": "slackOAuth2Api",
    "discord": "discordOAuth2Api",
    "outlook": "microsoftOAuth2Api",
    "microsoft": "microsoftOAuth2Api",
}

# Standard provider display metadata
PROVIDERS: list[dict[str, str]] = [
    {"id": "gmail", "name": "Gmail", "icon": "gmail"},
    {"id": "github", "name": "GitHub", "icon": "github"},
    {"id": "google_calendar", "name": "Google Calendar", "icon": "calendar"},
    {"id": "google_drive", "name": "Google Drive", "icon": "drive"},
    {"id": "notion", "name": "Notion", "icon": "notion"},
    {"id": "slack", "name": "Slack", "icon": "slack"},
    {"id": "discord", "name": "Discord", "icon": "discord"},
    {"id": "outlook", "name": "Outlook", "icon": "outlook"},
]


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    """Make an authenticated request to the n8n REST API.

    Returns the parsed JSON response or raises a descriptive error dict.
    """
    api_key = _get_api_key()
    if not api_key:
        return {"error": "N8N_API_KEY not configured in environment"}

    url = f"{N8N_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body else None

    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )

    try:
        with urllib.request.urlopen(req, timeout=N8N_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        try:
            body_raw = exc.read().decode("utf-8")
            detail = json.loads(body_raw) if body_raw else {"message": str(exc)}
        except Exception:
            detail = {"message": str(exc)}
        logger.warning("n8n API %s %s → %s: %s", method, path, exc.code, detail.get("message", str(exc)))
        return {"error": detail.get("message", str(exc)), "status": exc.code}
    except urllib.error.URLError as exc:
        logger.warning("n8n API unreachable: %s", exc.reason)
        return {"error": f"n8n unreachable: {exc.reason}", "status": 502}
    except Exception as exc:
        logger.warning("n8n API error: %s", exc)
        return {"error": str(exc), "status": 500}


# ── Public API ──────────────────────────────────────────────────────────────


def get_status() -> dict[str, Any]:
    """Check if n8n is reachable and healthy.

    Returns:
        {"healthy": bool, "version": str|None, "error": str|None, "url": str}
    """
    try:
        req = urllib.request.Request(f"{N8N_BASE}/healthz")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return {"healthy": True, "version": None, "error": None, "url": _N8N_PUBLIC_URL}
            return {"healthy": False, "version": None, "error": f"HTTP {resp.status}", "url": _N8N_PUBLIC_URL}
    except Exception as exc:
        return {"healthy": False, "version": None, "error": str(exc), "url": _N8N_PUBLIC_URL}


def list_credentials() -> dict[str, Any]:
    """List all n8n credentials with their connection status.

    Returns:
        {"credentials": [...], "total": int, "error": None}
        or {"credentials": [], "total": 0, "error": "message"}
    """
    resp = _request("GET", "/credentials")
    if "error" in resp:
        return {"credentials": [], "total": 0, "error": resp["error"]}

    data = resp.get("data", [])
    credentials = []
    for cred in data:
        credentials.append({
            "id": cred.get("id"),
            "name": cred.get("name"),
            "type": cred.get("type"),
            "is_managed": cred.get("isManaged", False),
            "created_at": cred.get("createdAt"),
            "updated_at": cred.get("updatedAt"),
            # n8n doesn't expose "connected" in list — we infer from existence
            "status": "connected" if cred.get("id") else "unknown",
        })

    return {"credentials": credentials, "total": len(credentials)}


def get_credential(provider: str) -> dict[str, Any]:
    """Get credential status for a specific provider.

    Looks up the provider by its n8n credential type name.
    Returns the first matching credential, or {"status": "not_connected"} if none exists.
    """
    n8n_type = PROVIDER_TO_N8N_TYPE.get(provider)
    if not n8n_type:
        return {"status": "unknown", "error": f"Unknown provider: {provider}"}

    resp = _request("GET", "/credentials")
    if "error" in resp:
        return {"status": "error", "error": resp["error"]}

    data = resp.get("data", [])
    for cred in data:
        if cred.get("type") == n8n_type:
            return {
                "status": "connected",
                "credential_id": cred.get("id"),
                "name": cred.get("name"),
                "type": cred.get("type"),
                "created_at": cred.get("createdAt"),
            }

    return {"status": "not_connected", "provider": provider, "n8n_type": n8n_type}


def connect_credential(provider: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Initiate an OAuth credential for a provider in n8n.

    n8n requires BYOK (Bring Your Own Key) credentials — client ID, client secret,
    etc. — for OAuth2 credential types. The Olympus → n8n flow has two paths:

    PATH A (BYOK, programmatic):
        User provides OAuth app credentials (client_id, client_secret).
        Olympus creates the credential in n8n and returns the OAuth setup URL.

    PATH B (n8n UI, manual):
        User clicks "Connect" → Olympus returns the n8n credential creation URL.
        User visits n8n UI at localhost:5678, creates the credential manually,
        then Olympus polls GET /api/n8n/credentials/{provider} for status.

    Args:
        provider: Provider ID (e.g., "gmail", "github")
        data: Optional dict with BYOK fields (client_id, client_secret, etc.)

    Returns:
        Status dict with credential info, setup URL, and instructions.
    """
    n8n_type = PROVIDER_TO_N8N_TYPE.get(provider)
    if not n8n_type:
        return {"status": "error", "error": f"Unknown provider: {provider}"}

    provider_name = _provider_display_name(provider)

    # Check if already connected
    existing = get_credential(provider)
    if existing.get("status") == "connected":
        return {
            "status": "already_connected",
            "credential_id": existing.get("credential_id"),
            "provider": provider,
            "message": f"{provider_name} is already connected.",
        }

    # Build credential data with sensible defaults
    credential_data = _default_credential_data(provider, data or {})

    # If no BYOK credentials provided, return n8n UI instructions
    if not data or not (data.get("client_id") or data.get("clientId")):
        return {
            "status": "requires_byok",
            "provider": provider,
            "provider_name": provider_name,
            "n8n_type": n8n_type,
            "message": (
                f"n8n requires a {provider_name} OAuth app (client ID + secret). "
                f"Open the n8n UI to set this up."
            ),
            "n8n_setup_url": f"{_N8N_PUBLIC_URL}/credentials",
            "n8n_new_url": f"{_N8N_PUBLIC_URL}/home/credentials/create/{n8n_type}",
            "required_fields": _required_fields_for(n8n_type),
        }

    # PATH A: Create credential with BYOK data
    body = {
        "name": f"Pantheon — {provider_name}",
        "type": n8n_type,
        "data": credential_data,
    }

    resp = _request("POST", "/credentials", body=body)
    if "error" in resp:
        return {
            "status": "error",
            "provider": provider,
            "error": resp["error"],
            "message": f"Failed to create {provider_name} credential.",
        }

    credential_id = resp.get("id") or resp.get("data", {}).get("id")

    return {
        "status": "created",
        "credential_id": credential_id,
        "provider": provider,
        "provider_name": provider_name,
        "n8n_type": n8n_type,
        "message": (
            f"{provider_name} credential created. "
            f"Complete OAuth in the n8n UI: {_N8N_PUBLIC_URL}/credentials/{credential_id}"
        ),
        "n8n_credential_url": f"{_N8N_PUBLIC_URL}/credentials/{credential_id}" if credential_id else f"{_N8N_PUBLIC_URL}/credentials",
        "next_step": "Visit the n8n credential page to authorize and connect.",
    }


def _default_credential_data(provider: str, data: dict[str, Any]) -> dict[str, Any]:
    """Build credential data with sensible defaults for a provider.

    Merges user-provided data with per-provider defaults (server URLs, scopes).
    """
    defaults: dict[str, dict[str, Any]] = {
        "github": {
            "serverUrl": "https://api.github.com",
        },
        "gmail": {
            "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        },
        "google_calendar": {
            "scope": "https://www.googleapis.com/auth/calendar.readonly https://www.googleapis.com/auth/calendar.events",
        },
        "google_drive": {
            "scope": "https://www.googleapis.com/auth/drive.readonly",
        },
        "slack": {
            "serverUrl": "https://slack.com/api",
        },
        "discord": {
            "serverUrl": "https://discord.com/api",
        },
        "notion": {
            "serverUrl": "https://api.notion.com",
        },
        "outlook": {
            "serverUrl": "https://graph.microsoft.com",
        },
    }

    base = defaults.get(provider, {})
    merged = {**base, **data}
    return merged


def _required_fields_for(n8n_type: str) -> list[str]:
    """Return the minimum required fields for a given n8n credential type.

    Based on n8n's credential schemas. Most OAuth2 types require
    clientId and clientSecret at minimum.
    """
    return ["clientId", "clientSecret"]


def delete_credential(provider: str) -> dict[str, Any]:
    """Delete a credential for a provider from n8n.

    Finds the credential by n8n type name, then deletes it via the n8n REST API.
    Used for disconnect in the Olympus UI.

    Returns:
        {\"status\": \"deleted\", \"credential_id\": str}
        or {\"status\": \"not_found\"}
        or {\"status\": \"error\", \"error\": str}
    """
    n8n_type = PROVIDER_TO_N8N_TYPE.get(provider)
    if not n8n_type:
        return {"status": "error", "error": f"Unknown provider: {provider}"}

    # Find the credential ID
    resp = _request("GET", "/credentials")
    if "error" in resp:
        return {"status": "error", "error": resp["error"]}

    credential_id = None
    for cred in resp.get("data", []):
        if cred.get("type") == n8n_type:
            credential_id = cred.get("id")
            break

    if not credential_id:
        return {"status": "not_found", "provider": provider}

    # Delete it
    del_resp = _request("DELETE", f"/credentials/{credential_id}")
    if "error" in del_resp:
        return {"status": "error", "error": del_resp["error"]}

    return {"status": "deleted", "credential_id": credential_id, "provider": provider}


def _provider_display_name(provider: str) -> str:
    """Get the display name for a provider ID."""
    for p in PROVIDERS:
        if p["id"] == provider:
            return p["name"]
    return provider.replace("_", " ").title()
