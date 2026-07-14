"""
Pantheon Sync Adapter Framework.

Provider-specific sync adapters that fetch data from external
sources and canonicalize it to Markdown + metadata.

Usage:
    from adapters import get_adapter, list_adapters

    adapter = get_adapter("gmail")
    result = adapter.sync(connection, cursor="2026-01-01")
    for record in result.records:
        print(record.content)
"""

# Re-export base types
from adapters.base import (  # noqa: E402, F401
    BaseAdapter,
    SyncRecord,
    SyncResult,
    get_adapter,
    list_adapters,
    register_adapter,
)

# Auto-register all built-in adapters
from adapters import gmail              # noqa: E402, F401
from adapters import github             # noqa: E402, F401
from adapters import slack              # noqa: E402, F401
from adapters import google_calendar    # noqa: E402, F401
from adapters import outlook            # noqa: E402, F401
from adapters import microsoft_teams    # noqa: E402, F401
from adapters import notion             # noqa: E402, F401
from adapters import discord            # noqa: E402, F401
