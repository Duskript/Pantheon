#!/usr/bin/env python3
"""
Push a briefing to Notion via Composio MCP HTTP API.
Uses NOTION_FETCH_DATA with broad query for duplicate detection
and the `markdown` parameter for proper Notion-flavored markdown content.

Usage: python3 notion-briefing-poster.py [--force]
  --force: skip duplicate check and create anyway
"""
import argparse, json, os, sys, urllib.request

# --- Config ---
PARENT_PAGE_ID = "38aff934-3bb9-81c1-b7dc-cc8b4b52512b"
MCP_URL = "https://connect.composio.dev/mcp"

BRIEFING_LABEL = "Dawn Patrol"
BRIEFING_DATE = "2026-07-30"
PAGE_TITLE = f"{BRIEFING_LABEL} - {BRIEFING_DATE}"
ICON_EMOJI = "\U0001f305"  # 🌅
SEARCH_QUERY = f"{BRIEFING_LABEL} {BRIEFING_DATE[:4]}"  # "Dawn Patrol 2026"

BODY_MARKDOWN = """## Observations

### GitHub: Ops AI & Agent Tools

- **ongridio/ongrid** (Go, ⭐573) — Ops AI Agent that understands infrastructure, finds root cause, and fixes from Slack/Telegram.
- **receptron/mulmoterminal** (TypeScript, ⭐70) — Run multiple Claude Code and Codex sessions in parallel via browser terminal grid.
- **NousResearch/hermes-agent** (Python, ⭐222597) — The agent that grows with you.

### MCP Servers & Tools

- **nickjlamb/pubcrawl** (TypeScript, ⭐12) — MCP server for PubMed & biomedical literature search.
- **BrokkAi/bifrost** (Rust, ⭐10) — Multi-language static analysis for agents and large repos.
- **oomkapwn/enquire-mcp** (TypeScript, ⭐26) — Obsidian MCP for AI memory and local document intelligence.
- **markhuangai/dense-mem** (Go, ⭐35) — Self-hosted AI agent memory server with MCP, evidence provenance, typed claims, conflict detection.
- **MrPeppersDev/agent-infrastructure-landscape** (HTML, ⭐3) — 912-system × 68-column catalog of agent memory & infrastructure.

### Knowledge Graphs & RAG

- **ttmens/ai-radar-wiki** (HTML, ⭐8) — Self-evolving AI knowledge base with 4-pillar system.
- **Deus-corp/cks-runtime** (Python, ⭐2) — Sessions, transactions, and version history for knowledge graphs.
- **ongridio/ongrid** (also RAG) — Cross-listed ops AI agent.
- **amemhq/amem** (TypeScript, ⭐3) — Agentic-memory stack with graph linking, hybrid retrieval, LLM-driven evolution.

### MCP Server Ecosystem

- Official SDKs now cover: C#, Go, Java, Kotlin, PHP, Python, Ruby, Rust, Swift, TypeScript.
- Notable new servers:
  - Correctover/mcp-server — Contract validation + self-healing failover for LLM APIs (6-dim verification, 22µs P50, 87 rules, L3 failover in 949ms).
  - ddg-agent-payable-services — Pay-per-call x402 gateway with 90+ agent tools + OpenAI-compatible LLM gateway.
  - coinopai-mcp — x402-powered paid crypto intelligence with preflight checks and trade decisions.
"""


def mcp_init(headers):
    payload = json.dumps({
        "jsonrpc": "2.0", "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "notion-briefing-poster", "version": "1.2"}
        },
        "id": 1
    }).encode()
    req = urllib.request.Request(MCP_URL, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=15) as f:
        return f.headers.get("Mcp-Session-Id", "") or f.headers.get("mcp-session-id", "")


def mcp_notify(headers):
    try:
        payload = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
        req = urllib.request.Request(MCP_URL, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def call_composio_tool(headers, tool_slug, tool_args):
    """Call a single Composio tool and return the parsed response dict."""
    payload = json.dumps({
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {
            "name": "COMPOSIO_MULTI_EXECUTE_TOOL",
            "arguments": {
                "tools": [{"tool_slug": tool_slug, "arguments": tool_args}],
                "thought": tool_slug,
                "current_step": "1/1",
                "current_step_metric": "1/1",
                "sync_response_to_workbench": False,
            }
        },
        "id": 2
    }).encode()
    req = urllib.request.Request(MCP_URL, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as f:
        body = f.read().decode()

    # Parse SSE - find the first data: line with content
    for line in body.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            d = json.loads(line[6:])
            result_wrapper = d.get("result", {})
            for c in result_wrapper.get("content", []):
                txt = c.get("text", "")
                if txt:
                    inner = json.loads(txt)
                    # Drill into results
                    for entry in inner.get("data", {}).get("results", []):
                        rd = entry.get("response", {})
                        return rd
    return {"successful": False, "error": "No data in SSE response"}


def page_title_from_props(page):
    """Extract the title text from a Notion page's properties dict."""
    props = page.get("properties", {})
    for prop_name, prop_val in props.items():
        if isinstance(prop_val, dict) and prop_val.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop_val.get("title", []))
    return ""


def find_page_by_title(headers, base_args, query, target_title):
    """
    Search for a page with the exact target title using NOTION_FETCH_DATA.
    Returns the page dict if found, None otherwise.
    """
    search_args = {
        **base_args,
        "query": query,
        "fetch_type": "pages",
    }

    result = call_composio_tool(headers, "NOTION_FETCH_DATA", search_args)

    if result.get("successful"):
        data = result.get("data", {})
        results = data.get("results", [])
        for page in results:
            if page.get("archived"):
                continue
            page_title = page_title_from_props(page)
            if page_title == target_title:
                return page
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Skip duplicate check")
    args = parser.parse_args()

    ak = os.environ.get("COMPOSIO_AUTH_TOKEN", "")
    ck = os.environ.get("COMPOSIO_CONSUMER_KEY", "")
    account_id = os.environ.get("COMPOSIO_ACCOUNT_ID", "")

    if not ak or not ck:
        print("ERROR: COMPOSIO_AUTH_TOKEN and COMPOSIO_CONSUMER_KEY required", file=sys.stderr)
        sys.exit(1)

    print(f"INFO: Posting '{PAGE_TITLE}' to Notion...", file=sys.stderr)

    headers = {
        "Authorization": f"Bearer {ak}",
        "x-consumer-api-key": ck,
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }

    session_id = mcp_init(headers)
    if not session_id:
        print("ERROR: Failed to initialize MCP session", file=sys.stderr)
        sys.exit(1)
    headers["Mcp-Session-Id"] = session_id
    mcp_notify(headers)

    base_args = {}
    if account_id:
        base_args["account"] = account_id

    # --- Duplicate detection using broad query + exact title match ---
    if not args.force:
        print(f"DEBUG: Searching for existing '{PAGE_TITLE}' via NOTION_FETCH_DATA (query='{SEARCH_QUERY}')...", file=sys.stderr)

        existing = find_page_by_title(headers, base_args, SEARCH_QUERY, PAGE_TITLE)
        if existing:
            page_id = existing.get("id")
            print(f"DUPLICATE: Page '{PAGE_TITLE}' already exists (id={page_id})")
            print("RESULT: Skipped - already posted")
            sys.exit(0)

        # Fallback: also try with label-only query in case Notion index hasn't caught up
        print(f"DEBUG: Fallback search with query='{BRIEFING_LABEL}'...", file=sys.stderr)
        existing = find_page_by_title(headers, base_args, BRIEFING_LABEL, PAGE_TITLE)
        if existing:
            page_id = existing.get("id")
            print(f"DUPLICATE: Page '{PAGE_TITLE}' already exists (id={page_id})")
            print("RESULT: Skipped - already posted")
            sys.exit(0)
    else:
        print("DEBUG: --force set, skipping duplicate check", file=sys.stderr)

    # --- Create the page with markdown ---
    print(f"DEBUG: Creating page with markdown content...", file=sys.stderr)

    create_args = {
        **base_args,
        "parent_id": PARENT_PAGE_ID,
        "title": PAGE_TITLE,
        "icon": ICON_EMOJI,
        "markdown": BODY_MARKDOWN,
    }

    result = call_composio_tool(headers, "NOTION_CREATE_NOTION_PAGE", create_args)

    if not result.get("successful"):
        error_msg = result.get("error", "unknown error")
        data_msg = result.get("data", {}).get("message", "")
        print(f"ERROR: {error_msg}", file=sys.stderr)
        if data_msg:
            print(f"  Detail: {data_msg}", file=sys.stderr)
        sys.exit(1)

    data = result.get("data", {})
    page_id = data.get("id", "unknown")
    page_url = data.get("url", data.get("public_url", f"https://notion.so/{page_id}"))
    print(f"PAGE_CREATED:{page_id}")
    print(f"PAGE_URL:{page_url}")
    print("RESULT: Created successfully")


if __name__ == "__main__":
    main()
