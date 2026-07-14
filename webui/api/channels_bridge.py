
"""channels_bridge.py — Communication channels adapter for Olympus UI.

Read-only status for Twilio SMS / A2P, Telegram gateway, webhooks,
and future Gmail inbox. No credentials, tokens, or message bodies exposed.

Endpoints:
  GET /api/channels              → all channel statuses
  GET /api/channels/twilio/status → Twilio bridge health + A2P
  GET /api/channels/messages/recent → recent inbound SMS metadata
  GET /api/channels/webhooks       → webhook endpoint state
  GET /api/channels/telegram       → Telegram gateway status
"""

from __future__ import annotations

import json
import os
import subprocess
import time

from api.helpers import bad, j

TWILIO_BRIDGE_URL = os.environ.get("TWILIO_BRIDGE_URL", "http://127.0.0.1:8090")
TWILIO_A2P_STATUS = os.environ.get("TWILIO_A2P_STATUS", "IN_PROGRESS")


def _http_get(url, timeout=3):
    """Minimal HTTP GET using urllib — no external deps."""
    from urllib.request import Request, urlopen
    from urllib.error import URLError
    try:
        req = Request(url, headers={"User-Agent": "Olympus-UI/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return {"status_code": resp.status, "body": resp.read().decode("utf-8", errors="replace")}
    except URLError as e:
        return {"status_code": 0, "error": str(e.reason) if hasattr(e, "reason") else str(e)}
    except Exception as e:
        return {"status_code": 0, "error": str(e)}


def _get_twilio_status():
    """Check Twilio bridge health and A2P registration state."""
    health = _http_get(TWILIO_BRIDGE_URL + "/health")
    return {
        "bridge": {
            "url": TWILIO_BRIDGE_URL,
            "healthy": health.get("status_code") == 200,
            "response": health,
        },
        "a2p_registration": TWILIO_A2P_STATUS,
    }


def _get_telegram_status():
    """Check if Telegram gateway is connected (via Hermes process check)."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "hermes-gateway"],
            capture_output=True, text=True, timeout=5
        )
        active = result.stdout.strip() == "active"
        return {"status": "active" if active else "inactive", "service": "hermes-gateway"}
    except Exception:
        return {"status": "unknown", "service": "hermes-gateway"}


def _get_webhook_status():
    """Return webhook endpoint configuration (no secrets)."""
    conductor_url = "http://127.0.0.1:8088"
    health = _http_get(conductor_url + "/health")
    return {
        "conductor_webhook": {
            "url": conductor_url,
            "healthy": health.get("status_code") == 200,
            "endpoint": "https://sms.theoforgesolutions.com/sms",
        }
    }


def _get_gmail_status():
    """Placeholder for future Gmail/Google integration health."""
    composio_configured = bool(os.environ.get("COMPOSIO_API_KEY"))
    return {
        "status": "pending" if composio_configured else "not_configured",
        "account": "pantheon.theoforge@gmail.com",
        "note": "Account creation pending user completion"
    }


def handle_channels(handler, parsed):
    path = parsed.path
    
    if path == "/api/channels":
        return j(handler, {
            "channels": {
                "twilio": _get_twilio_status(),
                "telegram": _get_telegram_status(),
                "webhooks": _get_webhook_status(),
                "gmail": _get_gmail_status(),
            }
        })
    
    if path == "/api/channels/twilio/status":
        return j(handler, _get_twilio_status())
    
    if path == "/api/channels/messages/recent":
        return j(handler, {"messages": [], "note": "SMS message metadata endpoint — not yet wired to Twilio API"})
    
    if path == "/api/channels/webhooks":
        return j(handler, _get_webhook_status())
    
    if path == "/api/channels/telegram":
        return j(handler, _get_telegram_status())
    
    return False
