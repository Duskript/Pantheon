#!/usr/bin/env python3
"""
Composio Reddit collector — called as fallback from dawn-patrol.py.
Uses the pantheon-mcp JSON-RPC endpoint at localhost:8010/mcp.

Extracts session ID from response headers.

Expected output: markdown-formatted Reddit results, one post per line.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

MCP_URL = "http://localhost:8010/mcp"


def _mcp(method: str, params: dict | None = None,
         timeout: int = 30, session_id: str | None = None,
         return_headers: bool = False) -> tuple[dict, dict | None]:
    """Send a JSON-RPC request, return (body, response_headers)."""
    body = json.dumps({
        "jsonrpc": "2.0",
        "id": "cr-" + str(int(time.time() * 1000)),
        "method": method,
        "params": params or {},
    }).encode()

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    req = urllib.request.Request(
        MCP_URL, data=body, headers=headers, method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            hdrs = dict(resp.headers)
            found = None
            for line in raw.splitlines():
                if line.startswith("data: "):
                    found = json.loads(line[6:])
            if found is None:
                try:
                    found = json.loads(raw)
                except json.JSONDecodeError:
                    found = {"error": f"unparseable: {raw[:300]}"}
            if return_headers:
                return found, hdrs
            return found, None
    except urllib.error.HTTPError as e:
        body_text = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}: {body_text[:300]}"}, dict(e.headers) if return_headers else None
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return {"error": str(e)}, None


def initialize() -> str | None:
    """Initialize MCP session, return session ID."""
    result, headers = _mcp("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "composio-reddit", "version": "1.0"},
    }, timeout=10, return_headers=True)

    if "error" in result:
        return None

    # Extract session ID from header
    sid = None
    if headers:
        for k, v in headers.items():
            if k.lower() == "mcp-session-id":
                sid = v
                break
    # Also try SSE event stream
    ev = result.get("result", {})
    if not sid:
        sid = ev.get("_meta", {}).get("sessionId")
    return sid


def search_reddit(query: str, session_id: str,
                  sort: str = "new", limit: int = 5) -> list[dict]:
    """Search Reddit via Composio MCP tool."""
    resp, _ = _mcp("tools/call", {
        "name": "composio_COMPOSIO_MULTI_EXECUTE_TOOL",
        "arguments": {
            "tools": [{
                "tool_slug": "REDDIT_SEARCH_ACROSS_SUBREDDITS",
                "arguments": {
                    "search_query": query,
                    "restrict_sr": True,
                    "sort": sort,
                    "limit": limit,
                },
            }],
            "sync_response_to_workbench": False,
            "thought": "dawn patrol reddit collection via composio",
            "current_step": "SEARCHING_REDDIT",
            "current_step_metric": "1/1",
        },
    }, timeout=30, session_id=session_id)

    if "error" in resp:
        return [{"error": f"MCP error: {resp['error']}"}]

    # Extract posts from tool result
    content = resp.get("result", {}).get("content", [])
    for c in content:
        if c.get("type") == "text":
            try:
                data = json.loads(c["text"])
                tool_results = data.get("data", {}).get("results", [])
                posts = []
                for r in tool_results:
                    resp_data = r.get("response", {}).get("data", {})
                    for post in resp_data.get("posts", []):
                        if isinstance(post, dict) and post.get("title"):
                            posts.append(post)
                    children = resp_data.get("data", {}).get("children", [])
                    for child in children:
                        if isinstance(child, dict):
                            post = child.get("data", child)
                            if post.get("title"):
                                posts.append(post)
                return posts
            except (json.JSONDecodeError, KeyError, TypeError):
                pass
    return []


def main() -> str:
    """Collect Reddit posts about AI agents, MCP, LLMs via Composio."""
    # Initialize MCP session
    session_id = initialize()
    if not session_id:
        return ("[Reddit: Composio MCP unavailable — "
                "pantheon-mcp service may be down or init failed]")

    queries = [
        ("subreddit:LocalLLaMA OR subreddit:artificial OR subreddit:AI_Agents", "new", 5),
        ("subreddit:MCP OR subreddit:ClaudeAI OR subreddit:OpenAI", "new", 5),
        ("subreddit:selfhosted OR subreddit:RAG OR subreddit:MachineLearning", "new", 5),
        ("new agent framework OR MCP server OR memory system", "new", 5),
    ]

    seen = set()
    results = []

    for query, sort, limit in queries:
        posts = search_reddit(query, session_id, sort, limit)
        if posts and isinstance(posts[0], dict) and "error" in posts[0]:
            return f"[Reddit: Composio error — {posts[0]['error']}]"

        for post in posts:
            if "error" in post:
                return f"[Reddit: Composio error — {post['error']}]"

            title = post.get("title", "")
            if not title or title in seen:
                continue
            seen.add(title)

            sub = post.get("subreddit", post.get("community", "?"))
            score = post.get("score", 0)
            comments = post.get("num_comments", 0)
            permalink = post.get("permalink", "")
            url = f"https://reddit.com{permalink}" if permalink.startswith("/") else (permalink or "")

            results.append(f"- **r/{sub}** [{score}▲ {comments}💬] {title}")
            if url:
                results.append(f"  {url}")

    if not results:
        return "[Reddit: no results from Composio]"

    return "\n".join(results)


if __name__ == "__main__":
    print(main())
