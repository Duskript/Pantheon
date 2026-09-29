#!/usr/bin/env python3
"""Resolve a FastMCP-compatible server class across MCP SDK generations.

``FastMCP`` used to be shipped by the MCP SDK as ``mcp.server.fastmcp.FastMCP``.
The SDK removed it in ``mcp`` 2.0 and moved the high-level server to
``mcp.server.mcpserver.MCPServer``; the standalone ``fastmcp`` distribution
keeps the old name for callers that have not migrated.

Importing one fixed path breaks the moment the SDK moves -- and it did:
``lib/ichor_mcp.py`` raised ``ModuleNotFoundError: No module named
'mcp.server.fastmcp'`` on every interpreter in the fleet, which took the whole
module (and its entire test file) down with it even though nothing else about
it was broken.

Resolution order, first hit wins:

1. ``mcp.server.MCPServer``           -- mcp >= 2.0 (SDK home, documented import)
2. ``mcp.server.mcpserver.MCPServer`` -- same class, explicit module path
3. ``mcp.server.fastmcp.FastMCP``     -- mcp 1.x SDK
4. ``fastmcp.FastMCP``                -- standalone distribution

All three generations agree on the surface this repo uses: ``Server(name)``,
``@server.tool(description=...)`` (the decorator returns the decorated callable
unchanged) and ``server.run(transport="stdio")``.

``describe_server_class()`` reports which generation resolved, so a probe can
surface it instead of the resolution staying invisible.
"""
from __future__ import annotations

import importlib
from typing import Any, NamedTuple

# (module, attribute) candidates, in resolution order.
_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("mcp.server", "MCPServer"),
    ("mcp.server.mcpserver", "MCPServer"),
    ("mcp.server.fastmcp", "FastMCP"),
    ("fastmcp", "FastMCP"),
)


class ServerClass(NamedTuple):
    """A resolved server class plus the dotted path it came from."""

    cls: type
    source: str


def resolve_server_class() -> ServerClass:
    """Return the best available FastMCP-compatible server class.

    Raises ImportError naming every candidate that was tried when none of them
    resolve. A bare ``ModuleNotFoundError`` for one hardcoded path -- with no
    hint that three other spellings were available -- is exactly what this
    module exists to prevent.
    """
    tried: list[str] = []
    for module_name, attr_name in _CANDIDATES:
        try:
            module = importlib.import_module(module_name)
        except ImportError as exc:  # includes ModuleNotFoundError
            tried.append(f"{module_name} ({exc})")
            continue
        cls = getattr(module, attr_name, None)
        if cls is None:
            tried.append(f"{module_name}.{attr_name} (module has no {attr_name})")
            continue
        return ServerClass(cls, f"{module_name}.{attr_name}")
    raise ImportError(
        "No FastMCP-compatible server class is available; install 'mcp>=2' or "
        "'fastmcp'. Tried: " + "; ".join(tried)
    )


def describe_server_class() -> str:
    """Return the dotted path of the server class that would be resolved.

    Never raises: returns a diagnostic string instead, for callers that want to
    report which generation is live without guarding the call themselves.
    """
    try:
        return resolve_server_class().source
    except ImportError as exc:
        return f"UNRESOLVED ({exc})"


def _accepted_kwargs(cls: type) -> "frozenset[str] | None":
    """Constructor keyword names ``cls`` accepts, or None if it takes **kwargs."""
    import inspect

    try:
        signature = inspect.signature(cls.__init__)
    except (TypeError, ValueError):
        return None
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()):
        return None
    return frozenset(signature.parameters) - {"self"}


def create_server(name: str, **kwargs: object) -> Any:
    """Instantiate the resolved server class, tolerating 1.x-only kwargs.

    The generations do NOT agree on the constructor: ``FastMCP`` (1.x) took
    ``host``/``port`` there, while ``MCPServer`` (2.x) takes them per transport.
    A caller written against 1.x therefore crashes on 2.x with
    ``TypeError: MCPServer.__init__() got an unexpected keyword argument 'host'``
    -- the same class of breakage as the removed import, one layer down.

    Unsupported keywords are dropped rather than raising, and recorded on the
    instance as ``_compat_dropped_kwargs`` so the difference stays visible
    instead of silently ignored. Callers that need HTTP must pass host/port to
    the transport (``run(transport=...)`` / ``streamable_http_app()``) rather
    than relying on the 1.x constructor.
    """
    resolved = resolve_server_class()
    accepted = _accepted_kwargs(resolved.cls)
    if accepted is None:
        supported, dropped = dict(kwargs), {}
    else:
        supported = {key: value for key, value in kwargs.items() if key in accepted}
        dropped = {key: value for key, value in kwargs.items() if key not in accepted}

    server = resolved.cls(name, **supported)
    try:
        server._compat_dropped_kwargs = dropped
        server._compat_server_source = resolved.source
    except AttributeError:  # pragma: no cover - exotic class with __slots__
        pass
    return server
