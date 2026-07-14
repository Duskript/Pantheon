"""
Pantheon Sync Adapter — Base classes and data types.

Separated from __init__.py to avoid circular imports
when adapters import from the package.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SyncRecord:
    """A single canonicalized record from a provider."""

    provider: str
    source_id: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class SyncResult:
    """Result of a sync operation."""

    provider: str
    records: list[SyncRecord]
    next_cursor: str | None = None
    status: str = "ok"
    error: str | None = None


class BaseAdapter(ABC):
    """Abstract base for provider adapters.

    Each adapter checks connection status for one external provider (Gmail,
    GitHub, etc.) via n8n credential management. Actual data sync is handled
    by n8n workflows.
    """

    provider: str = ""

    @abstractmethod
    def sync(self, connection: dict[str, Any], cursor: str | None = None) -> SyncResult:
        """Fetch new records from the provider since the given cursor."""
        ...

    @abstractmethod
    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        """Convert a raw provider record to canonical SyncRecord."""
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} provider={self.provider!r}>"


# ── n8n credential helper ──────────────────────────────────────

N8N_API_BASE = "http://localhost:5678/api/v1"
N8N_TIMEOUT = 10

# Provider → n8n credential type mapping
# (mirrors webui/api/n8n_client.py PROVIDER_TO_N8N_TYPE)
PROVIDER_TO_N8N_TYPE: dict[str, str] = {
    "gmail": "gmailOAuth2Api",
    "github": "githubOAuth2Api",
    "google_calendar": "googleCalendarOAuth2Api",
    "notion": "notionOAuth2Api",
    "slack": "slackOAuth2Api",
    "discord": "discordOAuth2Api",
    "outlook": "microsoftOAuth2Api",
    "microsoft_teams": "microsoftOAuth2Api",
}


def _get_n8n_api_key() -> str | None:
    """Get N8N_API_KEY from environment or .env file."""
    key = os.environ.get("N8N_API_KEY", "")
    if key:
        return key

    # Fallback: read from webui .env file
    env_path = Path.home() / "pantheon" / "webui" / ".env"
    try:
        if env_path.is_file():
            for line in env_path.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[7:]
                if line.startswith("N8N_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def _check_n8n_credential(provider: str) -> dict:
    """Check if an n8n credential exists for the given provider.

    Calls n8n REST API ``GET /api/v1/credentials`` and searches for a
    credential matching the provider's n8n type.

    Returns:
        {
            "connected": bool,
            "credential_id": str | None,
            "credential_name": str | None,
            "error": str | None,
        }
    """
    api_key = _get_n8n_api_key()
    if not api_key:
        return {
            "connected": False,
            "credential_id": None,
            "credential_name": None,
            "error": "N8N_API_KEY not configured. Set up n8n in Settings → Integrations.",
        }

    n8n_type = PROVIDER_TO_N8N_TYPE.get(provider)
    if not n8n_type:
        return {
            "connected": False,
            "credential_id": None,
            "credential_name": None,
            "error": f"Unknown provider: {provider}",
        }

    try:
        req = urllib.request.Request(
            f"{N8N_API_BASE}/credentials",
            headers={
                "X-N8N-API-KEY": api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=N8N_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        for cred in data.get("data", []):
            if cred.get("type", "").lower() == n8n_type.lower():
                return {
                    "connected": True,
                    "credential_id": cred.get("id"),
                    "credential_name": cred.get("name"),
                    "error": None,
                }

        return {
            "connected": False,
            "credential_id": None,
            "credential_name": None,
            "error": None,
        }

    except urllib.error.HTTPError as exc:
        logger.warning("n8n credential check failed (HTTP %s): %s", exc.code, exc.reason)
        return {
            "connected": False,
            "credential_id": None,
            "credential_name": None,
            "error": f"n8n API error (HTTP {exc.code})",
        }
    except urllib.error.URLError as exc:
        logger.warning("n8n unreachable: %s", exc.reason)
        return {
            "connected": False,
            "credential_id": None,
            "credential_name": None,
            "error": f"n8n unreachable: {exc.reason}",
        }
    except Exception as exc:
        logger.warning("n8n credential check error: %s", exc)
        return {
            "connected": False,
            "credential_id": None,
            "credential_name": None,
            "error": str(exc),
        }


# ── Registry ────────────────────────────────────────────────────

_registry: dict[str, type[BaseAdapter]] = {}


def register_adapter(provider: str):
    def decorator(cls: type[BaseAdapter]):
        cls.provider = provider
        _registry[provider] = cls
        return cls

    return decorator


def get_adapter(provider: str, **kwargs: Any) -> BaseAdapter:
    cls = _registry.get(provider)
    if cls is None:
        raise KeyError(
            f"No adapter registered for provider '{provider}'. "
            f"Available: {sorted(_registry.keys())}"
        )
    return cls(**kwargs)


def list_adapters() -> list[str]:
    return sorted(_registry.keys())


# ══════════════════════════════════════════════════════════════════════════════
# Retry & Resilience (T23 — Error Handling + Recovery)
# ══════════════════════════════════════════════════════════════════════════════

import time as _time

MAX_RETRIES = 3
BASE_BACKOFF = 1.0  # seconds
MAX_BACKOFF = 60.0


def _attempt_token_refresh(provider: str) -> bool:
    """Attempt to refresh an OAuth token via n8n credential reconnect.

    Calls POST /api/v1/credentials/{n8n_type}/reconnect to trigger
    n8n's built-in OAuth token refresh.

    Returns True if the refresh succeeded, False otherwise.
    """
    api_key = _get_n8n_api_key()
    if not api_key:
        return False

    n8n_type = PROVIDER_TO_N8N_TYPE.get(provider)
    if not n8n_type:
        return False

    try:
        # First, find the credential ID
        req = urllib.request.Request(
            f"{N8N_API_BASE}/credentials",
            headers={"X-N8N-API-KEY": api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=N8N_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cred_id = None
        for cred in data.get("data", []):
            if cred.get("type", "").lower() == n8n_type.lower():
                cred_id = cred.get("id")
                break

        if not cred_id:
            logger.debug("No n8n credential found for %s — can't refresh", provider)
            return False

        # Trigger reconnect
        reconnect_url = f"{N8N_API_BASE}/credentials/{cred_id}/reconnect"
        req = urllib.request.Request(
            reconnect_url,
            method="POST",
            headers={"X-N8N-API-KEY": api_key, "Content-Type": "application/json"},
            data=b"{}",
        )
        with urllib.request.urlopen(req, timeout=N8N_TIMEOUT) as resp:
            if resp.status in (200, 201, 202):
                logger.info("OAuth token refreshed for %s via n8n", provider)
                return True

        logger.warning("Token refresh for %s returned HTTP %s", provider, resp.status)
        return False

    except Exception as exc:
        logger.warning("Token refresh for %s failed: %s", provider, exc)
        return False


def _should_retry(exception: Exception) -> bool:
    """Determine if an exception indicates a transient failure worth retrying."""
    msg = str(exception).lower()
    # Rate limiting
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return True
    # Server errors
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return True
    # Connection/network issues
    if "timeout" in msg or "connection" in msg or "reset" in msg:
        return True
    # OAuth expiry
    if "401" in msg or "unauthorized" in msg or "token expired" in msg:
        return True
    return False


def _is_auth_failure(exception: Exception) -> bool:
    """Check if an exception is an OAuth/auth failure (401, expired token)."""
    msg = str(exception).lower()
    return "401" in msg or "token expired" in msg or "invalid_grant" in msg


def sync_with_retry(
    adapter_fn,
    provider: str,
    *,
    max_retries: int = MAX_RETRIES,
    base_backoff: float = BASE_BACKOFF,
    max_backoff: float = MAX_BACKOFF,
) -> dict:
    """Call adapter_fn with exponential backoff retry and OAuth token refresh.

    Retry strategy:
    - 429 (rate limit) → exponential backoff (1s, 2s, 4s, 8s) → retry
    - 401 (auth expired) → attempt n8n token refresh → retry once
    - 5xx (server error) → exponential backoff → retry
    - Max 3 retries total

    Returns adapter result dict, or error dict if all retries exhausted.
    """
    last_error = None
    token_already_refreshed = False

    for attempt in range(max_retries + 1):
        try:
            result = adapter_fn()
            if attempt > 0:
                logger.info(
                    "Retry %d/%d succeeded for %s", attempt, max_retries, provider
                )
            return result

        except urllib.error.HTTPError as exc:
            last_error = exc
            msg = str(exc)

            if attempt >= max_retries:
                logger.error(
                    "All %d retries exhausted for %s (HTTP %s)",
                    max_retries, provider, exc.code,
                )
                break

            # Auth failure → refresh token once
            if _is_auth_failure(exc) and not token_already_refreshed:
                logger.warning(
                    "Auth failure for %s (HTTP %s) — attempting token refresh",
                    provider, exc.code,
                )
                if _attempt_token_refresh(provider):
                    token_already_refreshed = True
                    _time.sleep(2)  # brief pause after refresh
                    continue
                logger.warning("Token refresh failed for %s", provider)

            # Transient failure → backoff
            if _should_retry(exc):
                delay = min(base_backoff * (2 ** attempt), max_backoff)
                logger.info(
                    "Retry %d/%d for %s in %.1fs (HTTP %s)",
                    attempt + 1, max_retries, provider, delay, exc.code,
                )
                _time.sleep(delay)
                continue

            # Non-transient → don't retry
            break

        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            if attempt >= max_retries:
                logger.error("All %d retries exhausted for %s", max_retries, provider)
                break

            delay = min(base_backoff * (2 ** attempt), max_backoff)
            logger.info(
                "Network error for %s — retry %d/%d in %.1fs: %s",
                provider, attempt + 1, max_retries, delay, exc,
            )
            _time.sleep(delay)
            continue

        except Exception as exc:
            # Unknown errors — don't retry
            last_error = exc
            logger.exception("Non-transient error for %s — not retrying", provider)
            break

    return {
        "synced": 0,
        "cursor": None,
        "status": "error",
        "error": str(last_error) if last_error else "retry exhausted",
    }

