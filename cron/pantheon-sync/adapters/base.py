"""
Pantheon Sync Adapter — Base classes and data types.

Separated from __init__.py to avoid circular imports
when adapters import from the package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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

    Each adapter syncs data from one external provider (Gmail, GitHub, etc.)
    via the user's Composio BYOK connection.
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


# ─── Composio helper ──────────────────────────────────────────────

def _get_composio_client(connection: dict[str, Any]):
    """Create a Composio client from connection config.

    Returns None if no API key is configured (user hasn't set up Composio yet).
    """
    try:
        from composio import Composio
    except ImportError:
        return None

    api_key = (
        connection.get("composio_api_key")
        or connection.get("auth", {}).get("api_key")
    )
    if not api_key:
        return None

    try:
        return Composio(api_key=str(api_key))
    except Exception:
        return None


def _get_connected_account_id(
    client, provider: str, connection: dict[str, Any]
) -> str | None:
    """Find a connected account ID for the given provider.

    Checks connection config first, then queries Composio's API.
    """
    # Check if connection already has a stored account ID
    stored = connection.get("composio_account_id") or connection.get(
        "auth", {}
    ).get("connected_account_id")
    if stored:
        return str(stored)

    # Try to discover from Composio
    try:
        accounts = client.connected_accounts.list()
        for acct in accounts:
            app_name = getattr(acct, "app_name", "") or getattr(
                acct, "appId", ""
            )
            if app_name.lower() == provider.lower():
                return str(getattr(acct, "id", ""))
    except Exception:
        pass

    return None


def _exec_composio_tool(
    client,
    connected_account_id: str,
    tool_slug: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | None:
    """Execute a Composio tool and return the parsed result."""
    try:
        result = client.tools.execute(
            slug=tool_slug,
            arguments=arguments,
            connected_account_id=connected_account_id,
        )
        # result.data is the raw response — extract what we need
        if hasattr(result, "data"):
            return result.data
        return result
    except Exception:
        return None


# ─── Registry ─────────────────────────────────────────────────────

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
