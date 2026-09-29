#!/usr/bin/env python3
"""
thoth-dawn-mcp.py — Pantheon MCP fetch helper for the Thoth Dawn Patrol archive cron.

WHY THIS EXISTS
---------------
The Thoth dawn-patrol cron job runs with a Hermes profile (`thoth`) whose MCP tool
registrations are NOT loaded into the cron session. The Pantheon MCP server is still
running on 127.0.0.1:8010, so we drive it directly over StreamableHTTP with curl
(see skill: pantheon-mcp-client). Per that skill, a hand-rolled `urllib.request` POST
can 404 where the identical curl succeeds, so curl is the transport here.

PROTOCOL NOTES (from pantheon-mcp-client skill, verified 2026-06-26)
--------------------------------------------------------------------
  * Endpoint is POST http://localhost:8010/mcp  (NOT /, /sse, or /messages)
  * Handshake: initialize -> grab `Mcp-Session-Id` HEADER -> notifications/initialized
    -> tools/call with the same `mcp-session-id` header.
  * Response shape: {result: {content:[{type,text}], structuredContent:{result:<json
    string>}, isError:bool}} — the payload lives 2 levels deep, in
    `result.structuredContent.result`. We fall back to content[0].text.
  * Server may reply with bare JSON or an SSE stream ("data: {...}") — handle both.

WHAT IT COLLECTS
----------------
  1. system_health        — Pantheon component status table
  2. ichor_health         — FTS5 / ChromaDB / Graph / Events backend health
  3. hades_get_report     — NOTE: known-stale cache; the cron also reads the newest
                            hades-*.md on disk directly for the authoritative copy
  4. ichor_brief          — ranked brief across ALL gods, limit 10

USAGE
-----
    python3 /home/konan/pantheon/scripts/thoth-dawn-mcp.py

Prints a single JSON object keyed by tool name. Exit code 1 if the MCP session
handshake fails entirely (server down / not listening on 8010).
"""
import json
import subprocess
import sys

MCP_URL = "http://localhost:8010/mcp"
HDRS = ["-H", "Content-Type: application/json",
        "-H", "Accept: application/json, text/event-stream"]


def _curl(body, session=None, show_headers=False):
    """POST a JSON-RPC body to the MCP endpoint via curl. Returns raw stdout."""
    cmd = ["curl", "-sS", "-N"]
    if show_headers:
        cmd.append("-i")
    cmd += ["-X", "POST", MCP_URL] + HDRS
    if session:
        cmd += ["-H", "mcp-session-id: " + session]
    cmd += ["-d", json.dumps(body)]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return res.stdout


def parse(raw):
    """Parse either a bare-JSON body or an SSE 'data:' stream into a dict."""
    raw = (raw or "").strip()
    if raw.startswith("{"):
        try:
            return json.loads(raw)
        except Exception:
            pass
    chunks = [ln.strip()[5:].strip() for ln in raw.splitlines()
              if ln.strip().startswith("data:")]
    if chunks:
        try:
            return json.loads("".join(chunks))
        except Exception:
            return None
    return None


def init_session():
    """Run the MCP handshake. Returns (session_id, error_string_or_None)."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "thoth-dawn-patrol", "version": "0.2"}}}
    raw = _curl(body, show_headers=True)
    sid = None
    for line in raw.splitlines():
        if line.lower().startswith("mcp-session-id:"):
            sid = line.split(":", 1)[1].strip()
            break
    if not sid:
        return None, raw[:600]
    _curl({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    return sid, None


def call(name, args=None, session=None):
    """Call one MCP tool and unwrap the nested response shape."""
    sid = session
    if sid is None:
        sid, err = init_session()
        if err:
            return {"error": "session init failed", "detail": err}
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": name, "arguments": args or {}}}
    parsed = parse(_curl(body, sid))
    if not parsed:
        return {"error": "no parseable response"}
    if "error" in parsed:
        return {"error": parsed["error"]}
    res = parsed.get("result", {})
    if res.get("isError"):
        return {"error": "isError=true", "content": res.get("content")}
    sc = res.get("structuredContent") or {}
    if isinstance(sc, dict) and "result" in sc:
        return sc["result"]
    content = res.get("content") or []
    if content:
        return content[0].get("text", "")
    return res


def main():
    sid, err = init_session()
    if err:
        print(json.dumps({"fatal": "SESSION_INIT_FAILED", "detail": err}, indent=1))
        sys.exit(1)
    out = {"_session": "ok"}
    for name, args in [("system_health", {}),
                       ("ichor_health", {}),
                       ("hades_get_report", {}),
                       ("ichor_brief", {"include_all_gods": True, "limit": 10})]:
        try:
            out[name] = call(name, args, sid)
        except Exception as exc:  # noqa: BLE001 - report per-tool failure, keep going
            out[name] = {"error": str(exc)}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
