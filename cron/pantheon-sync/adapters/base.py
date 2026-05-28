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
    """Abstract base for provider adapters."""

    provider: str = ""

    @abstractmethod
    def sync(self, cursor: str | None = None) -> SyncResult:
        ...

    @abstractmethod
    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        ...

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} provider={self.provider!r}>"


# Shared registry
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
