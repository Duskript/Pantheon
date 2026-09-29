#!/usr/bin/env python3
"""Forward Resend inbound events to TheoForge without breaking operator alerts.

The Hermes webhook route runs this script before its existing direct Discord
notification. Resend's event contains metadata only, so this script retrieves
the received body, forwards an enriched copy to the private Tailnet bridge,
and emits that copy for the operator notification. If retrieval or forwarding
fails, the original metadata remains available and no lead is fabricated.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BRIDGE_URL = "http://100.115.50.41:4323/inbound/reply"
RESEND_ENV_PATH = Path.home() / ".hermes" / ".env"
FORWARD_TIMEOUT_SECONDS = 15
EVENT_TYPE = "email.received"


def _log(message: str) -> None:
    """Write diagnostics to stderr; stdout is reserved for the route payload."""
    print(f"[theoforge-forward] {message}", file=sys.stderr)


def _load_resend_key() -> str | None:
    """Read the Resend key from the inherited environment or local env file."""
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if key:
        return key
    try:
        for raw_line in RESEND_ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() == "RESEND_API_KEY":
                return value.strip().strip("'\"") or None
    except OSError as exc:
        _log(f"Resend env unavailable: {exc}")
    return None


def _enrich_received_event(payload: dict) -> dict:
    """Fetch Resend's body-only data and return an enriched event copy."""
    event_type = payload.get("type") or payload.get("event_type")
    data = payload.get("data")
    if event_type != EVENT_TYPE or not isinstance(data, dict):
        return payload
    email_id = str(data.get("email_id") or "").strip()
    if not email_id or os.environ.get("THEOFORGE_INBOUND_FORWARD_DRY_RUN") == "1":
        return payload
    key = _load_resend_key()
    if not key:
        _log("RESEND_API_KEY unavailable; forwarding metadata only")
        return payload

    url = "https://api.resend.com/emails/receiving/" + urllib.parse.quote(email_id, safe="")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) TheoForge-Bridge/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT_SECONDS) as response:
            received = json.loads(response.read().decode("utf-8"))
        if isinstance(received.get("data"), dict):
            received = received["data"]
        if not isinstance(received, dict):
            _log("Resend received-email response was not an object")
            return payload
        enriched = dict(payload)
        enriched_data = dict(data)
        for field in (
            "text", "html", "headers", "message_id", "reply_to", "cc", "bcc",
            "received_for", "attachments",
        ):
            if field in received:
                enriched_data[field] = received[field]
        if not str(enriched_data.get("text") or "").strip():
            enriched_data["text"] = str(received.get("html") or "").strip()
        enriched_data["email_id"] = email_id
        enriched["data"] = enriched_data
        _log("retrieved received-email content from Resend")
        return enriched
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError,
            json.JSONDecodeError) as exc:
        _log(f"received-email lookup failed: {exc}; forwarding metadata only")
        return payload


def _forward(payload: dict) -> None:
    """Best-effort forward; never turn a bridge error into lost notification."""
    event_type = payload.get("type") or payload.get("event_type")
    if event_type != EVENT_TYPE:
        return
    if os.environ.get("THEOFORGE_INBOUND_FORWARD_DRY_RUN") == "1":
        _log("dry-run; bridge request skipped")
        return

    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        BRIDGE_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=FORWARD_TIMEOUT_SECONDS) as response:
            response.read()
            if not 200 <= response.status < 300:
                _log(f"bridge returned HTTP {response.status}")
            else:
                _log(f"bridge accepted event HTTP {response.status}")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        _log(f"bridge forward failed: {exc}")


def main() -> int:
    """Read one JSON webhook payload, forward it, and preserve it on stdout."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        _log(f"invalid JSON input: {exc}")
        return 1
    if not isinstance(payload, dict):
        _log("payload must be a JSON object")
        return 1

    output_payload = _enrich_received_event(payload)
    _forward(output_payload)
    print(json.dumps(output_payload, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
