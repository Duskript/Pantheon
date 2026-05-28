"""
Pantheon Sync Adapter Framework (T12).

Provider-specific sync adapters that fetch data from external
sources and canonicalize it to Markdown + metadata.

Usage:
    from adapters import get_adapter, list_adapters

    adapter = get_adapter("gmail")
    result = adapter.sync()
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

# Auto-register built-in adapters
from adapters import gmail   # noqa: E402, F401
from adapters import github  # noqa: E402, F401
from adapters import slack   # noqa: E402, F401
