#!/usr/bin/env python3
"""BTST MCP Server — exposes Olympus BTST API tools for Hermes/Pantheon agents.

Usage:
  python3 server.py
  # Or via Hermes MCP config pointing to this file

Connects to the BTST API at BTST_API_URL (default http://127.0.0.1:3137/api/data).
"""

import asyncio
import json
import os
import urllib.request
import urllib.error
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

BTST_BASE = os.environ.get("BTST_API_URL", "http://127.0.0.1:3137/api/data")

server = Server("olympus-btst-mcp")


def _api(path: str, method: str = "GET", body: dict | None = None) -> dict[str, Any]:
    """Call the BTST API."""
    url = f"{BTST_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="ignore")
        return {"error": f"HTTP {e.code}", "detail": err_body[:500]}
    except Exception as e:
        return {"error": str(e)}


TOOLS = [
    Tool(
        name="btst_health",
        description="Check BTST API health and list available plugins.",
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="cms_list_content_types",
        description="List all CMS content types registered in BTST.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="cms_list_content",
        description="List CMS content items of a given type (e.g., ui-builder-page).",
        inputSchema={
            "type": "object",
            "properties": {
                "typeSlug": {"type": "string", "description": "Content type slug"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
            "required": ["typeSlug"],
        },
    ),
    Tool(
        name="blog_list_posts",
        description="List blog posts with optional filters.",
        inputSchema={
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "tagSlug": {"type": "string"},
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
        },
    ),
    Tool(
        name="blog_get_post",
        description="Get a single blog post by ID.",
        inputSchema={
            "type": "object",
            "properties": {"postId": {"type": "string"}},
            "required": ["postId"],
        },
    ),
    Tool(
        name="blog_list_tags",
        description="List all blog tags.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="media_list_assets",
        description="List media assets, optionally filtered by folder.",
        inputSchema={
            "type": "object",
            "properties": {
                "folderId": {"type": "string"},
                "limit": {"type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0},
            },
        },
    ),
    Tool(
        name="media_list_folders",
        description="List media folders.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="forms_list",
        description="List forms from the form builder plugin.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 20},
                "offset": {"type": "integer", "default": 0},
            },
        },
    ),
    Tool(
        name="forms_get",
        description="Get a single form by ID.",
        inputSchema={
            "type": "object",
            "properties": {"formId": {"type": "string"}},
            "required": ["formId"],
        },
    ),
    Tool(
        name="kanban_list_boards",
        description="List all kanban boards.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="kanban_get_board",
        description="Get a single kanban board with columns and tasks.",
        inputSchema={
            "type": "object",
            "properties": {"boardId": {"type": "string"}},
            "required": ["boardId"],
        },
    ),
    Tool(
        name="comments_list",
        description="List comments, optionally filtered by resource or status.",
        inputSchema={
            "type": "object",
            "properties": {
                "resourceId": {"type": "string"},
                "resourceType": {"type": "string"},
                "status": {"type": "string", "default": "approved"},
                "limit": {"type": "integer", "default": 50},
                "offset": {"type": "integer", "default": 0},
            },
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    result: dict[str, Any] = {}

    if name == "btst_health":
        ct = _api("/content-types")
        result = {
            "status": "ok",
            "base_url": BTST_BASE,
            "content_types": len(ct) if isinstance(ct, list) else 0,
            "plugins": ["blog", "cms", "comments", "form-builder", "kanban", "media", "ui-builder"],
        }

    elif name == "cms_list_content_types":
        result = _api("/content-types")

    elif name == "cms_list_content":
        slug = arguments["typeSlug"]
        limit = arguments.get("limit", 20)
        offset = arguments.get("offset", 0)
        result = _api(f"/content/{slug}?limit={limit}&offset={offset}")

    elif name == "blog_list_posts":
        params = []
        for key in ("slug", "tagSlug", "query"):
            if arguments.get(key):
                params.append(f"{key}={arguments[key]}")
        params.append(f"limit={arguments.get('limit', 20)}&offset={arguments.get('offset', 0)}")
        result = _api(f"/posts?{'&'.join(params)}")

    elif name == "blog_get_post":
        result = _api(f"/posts/{arguments['postId']}")

    elif name == "blog_list_tags":
        result = _api("/tags")

    elif name == "media_list_assets":
        params = f"limit={arguments.get('limit', 50)}&offset={arguments.get('offset', 0)}"
        if arguments.get("folderId"):
            params += f"&folderId={arguments['folderId']}"
        result = _api(f"/media/assets?{params}")

    elif name == "media_list_folders":
        result = _api("/media/folders")

    elif name == "forms_list":
        result = _api(f"/forms?limit={arguments.get('limit', 20)}&offset={arguments.get('offset', 0)}")

    elif name == "forms_get":
        result = _api(f"/forms/{arguments['formId']}")

    elif name == "kanban_list_boards":
        result = _api("/kanban/boards")

    elif name == "kanban_get_board":
        result = _api(f"/kanban/boards/{arguments['boardId']}")

    elif name == "comments_list":
        params = f"limit={arguments.get('limit', 50)}&offset={arguments.get('offset', 0)}"
        for key in ("resourceId", "resourceType", "status"):
            if arguments.get(key):
                params += f"&{key}={arguments[key]}"
        result = _api(f"/comments?{params}")

    else:
        result = {"error": f"Unknown tool: {name}"}

    return [TextContent(type="text", text=json.dumps(result, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
