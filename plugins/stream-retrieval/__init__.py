"""Stream Retrieval Plugin — 6 search tools for Codex-Stream data.

Registers tools that let Hermes agents search ingested content chunks,
filter by source/date, look up entities, find trending topics, walk the
Ichor knowledge graph, and fetch full chunk content.

All tools return empty lists on missing data — never crash.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("stream_retrieval_plugin")

# Tool schemas (JSON Schema for function calling)
SCHEMAS = {
    "stream_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query text"},
            "max_results": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            "source": {"type": "string", "description": "Filter by source provider (gmail, github, slack, etc.)"},
        },
        "required": ["query"],
    },
    "stream_filter": {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source provider filter (gmail, github, slack, etc.)"},
            "date_from": {"type": "string", "description": "ISO date lower bound (YYYY-MM-DD)"},
            "date_to": {"type": "string", "description": "ISO date upper bound (YYYY-MM-DD)"},
            "max_results": {"type": "integer", "description": "Max results (default 20)", "default": 20},
        },
        "required": [],
    },
    "stream_entity": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string", "description": "Entity name to look up"},
        },
        "required": ["entity_name"],
    },
    "stream_trending": {
        "type": "object",
        "properties": {
            "min_mentions": {"type": "integer", "description": "Minimum mention count (default 3)", "default": 3},
            "max_results": {"type": "integer", "description": "Max results (default 20)", "default": 20},
        },
        "required": [],
    },
    "stream_connections": {
        "type": "object",
        "properties": {
            "entity_name": {"type": "string", "description": "Entity to find connections for"},
        },
        "required": ["entity_name"],
    },
    "stream_fetch_chunks": {
        "type": "object",
        "properties": {
            "chunk_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of chunk file paths or IDs to fetch",
                "minItems": 1,
                "maxItems": 20,
            },
        },
        "required": ["chunk_ids"],
    },
}


def register(ctx):
    """Register all 6 stream retrieval tools."""
    from .tools import (
        stream_search,
        stream_filter,
        stream_entity,
        stream_trending,
        stream_connections,
        stream_fetch_chunks,
    )

    tools = [
        ("stream_search", "stream_retrieval", stream_search, "Search ingested content chunks by keyword"),
        ("stream_filter", "stream_retrieval", stream_filter, "Filter chunks by source provider and date range"),
        ("stream_entity", "stream_retrieval", stream_entity, "Look up all chunks and co-occurring entities for an entity"),
        ("stream_trending", "stream_retrieval", stream_trending, "Get top trending entities by mention count"),
        ("stream_connections", "stream_retrieval", stream_connections, "Find entity neighbors in the Ichor knowledge graph"),
        ("stream_fetch_chunks", "stream_retrieval", stream_fetch_chunks, "Fetch full content of specific chunks by path"),
    ]

    for name, toolset, handler, desc in tools:
        ctx.register_tool(
            name=name,
            toolset=toolset,
            schema=SCHEMAS[name],
            handler=handler,
            description=desc,
            emoji="📡",
        )

    logger.info("Stream Retrieval plugin: registered 6 tools (stream_search, stream_filter, stream_entity, stream_trending, stream_connections, stream_fetch_chunks)")
