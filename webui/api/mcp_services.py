"""
MCP Services API — Quick-Connect MCP server management backed by Hermes CLI.

Delegates all server lifecycle to `hermes mcp add/remove/list/test`.
No config.yaml parsing, no gateway reload logic — Hermes handles it.
"""

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
_HERMES_HOME = Path(os.path.expanduser("~/.hermes"))
_CATALOG_PATH = Path(os.path.expanduser("~/pantheon/data/mcp-catalog.yaml"))
# Alternative: check under ~/pantheon/webui/ too
_WEBUI_CATALOG_PATH = Path(os.path.expanduser("~/pantheon/webui/data/mcp-catalog.yaml"))

HERMES_CMD = "hermes"


# ── CLI Wrappers ─────────────────────────────────────────────────────────────

def _run_hermes(args, timeout=30, input_data=None):
    """Run a hermes CLI command and return (ok, stdout, stderr)."""
    cmd = [HERMES_CMD] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                timeout=timeout, input=input_data)
        ok = result.returncode == 0
        return ok, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except FileNotFoundError:
        return False, "", f"Command not found: {HERMES_CMD}"
    except Exception as e:
        return False, "", str(e)


def _mcp_list():
    """Parse `hermes mcp list` output into a list of dicts.

    Output format (space-separated columns, last two are tools and status):
      Name             Transport                      Tools        Status
      ──────────────── ────────────────────────────── ──────────── ──────────
      pantheon         http://127.0.0.1:8010/mcp      all          ✓ enabled
      sequential-thinking npx @modelcontextprotocol...   all          ✓ enabled
    """
    ok, stdout, stderr = _run_hermes(["mcp", "list"], timeout=15)
    if not ok or not stdout:
        logger.warning("hermes mcp list failed: %s", stderr)
        return []

    servers = []
    lines = stdout.strip().split("\n")

    # Use regex: name, then transport (everything until 2+ spaces before tools),
    # then tools (word), then status (rest of line)
    pattern = re.compile(r"^\s+(\S+)\s+(.+?)\s{2,}(\S+)\s+(.+)$")

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("─") or stripped.startswith("-"):
            continue
        if stripped.startswith("Name") or stripped.startswith("MCP Servers"):
            continue

        m = pattern.match(line)
        if not m:
            continue

        name = m.group(1)
        transport = m.group(2).strip()
        tools = m.group(3)
        raw_status = m.group(4).strip()

        # Parse status
        if "✓" in raw_status or "enabled" in raw_status:
            status = "active"
        elif "✗" in raw_status or "disabled" in raw_status:
            status = "disabled"
        elif "error" in raw_status or "failed" in raw_status:
            status = "error"
        else:
            status = "configured"

        servers.append({
            "name": name,
            "transport": transport,
            "tools": tools,
            "status": status,
            "reachable": "✓" in raw_status,
        })

    return servers


def _mcp_add(name, command, args, env_vars=None):
    """Add an MCP server via hermes mcp add."""
    cmd = ["mcp", "add", name, "--command", command]
    for a in (args or []):
        cmd.append(f"--args={a}")
    if env_vars:
        for k, v in env_vars.items():
            if v:
                cmd += ["--env", f"{k}={v}"]
    # Auto-accept the "Enable all tools? [Y/n/select]" prompt
    return _run_hermes(cmd, timeout=90, input_data="Y\n")


def _mcp_remove(name):
    """Remove an MCP server via hermes mcp remove."""
    return _run_hermes(["mcp", "remove", name], timeout=15)


# ── Catalog Loading ──────────────────────────────────────────────────────────

def _load_catalog():
    """Load service catalog from YAML."""
    for path in [_CATALOG_PATH, _WEBUI_CATALOG_PATH]:
        if path.exists():
            try:
                with open(path, "r") as f:
                    data = yaml.safe_load(f)
                    return data if isinstance(data, list) else []
            except Exception as e:
                logger.warning("Failed to load catalog from %s: %s", path, e)
                return []
    logger.warning("No catalog file found at %s", _CATALOG_PATH)
    return []


# ── Send / Read helpers (same pattern as connectors.py) ──────────────────────

def _send_json(handler, data, status=200):
    body = json.dumps(data, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _read_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    if not length:
        return {}
    try:
        return json.loads(handler.rfile.read(length))
    except Exception:
        return {}


# ── Handlers ─────────────────────────────────────────────────────────────────

def handle_get_catalog(handler):
    """GET /api/mcp-services/catalog"""
    catalog = _load_catalog()
    installed_map = {}

    # Get currently installed servers from hermes mcp list
    installed_servers = _mcp_list()
    for s in installed_servers:
        installed_map[s["name"]] = s

    # Enrich catalog entries with install status
    enriched = []
    for svc in catalog:
        s = dict(svc)
        s["hermes_args"] = None  # don't leak CLI args to frontend
        name = svc["id"]
        if name in installed_map:
            info = installed_map[name]
            s["installed"] = True
            s["status"] = info.get("status", "configured")
            s["reachable"] = info.get("reachable", False)
        else:
            s["installed"] = False
            s["status"] = "disconnected"
            s["reachable"] = False
        enriched.append(s)

    # Build category counts
    categories = {}
    for s in enriched:
        cat = s.get("category", "Other")
        if cat not in categories:
            categories[cat] = {"total": 0, "connected": 0}
        categories[cat]["total"] += 1
        if s.get("installed"):
            categories[cat]["connected"] += 1

    return _send_json(handler, {
        "services": enriched,
        "categories": list(categories.keys()),
        "category_counts": categories,
        "catalog_version": 1,
    })


def handle_get_status(handler):
    """GET /api/mcp-services/status"""
    servers = _mcp_list()
    return _send_json(handler, {"servers": servers})


def handle_post_install(handler):
    """POST /api/mcp-services/install"""
    req = _read_body(handler)

    service_id = (req.get("id") or "").strip()
    env_vars = req.get("env") or {}

    if not service_id:
        return _send_json(handler, {"error": "Missing service id"}, 400)

    # Look up the service in catalog
    catalog = _load_catalog()
    svc = next((s for s in catalog if s["id"] == service_id), None)
    if not svc:
        return _send_json(handler, {"error": f"Unknown service: {service_id}"}, 404)

    hermes_args = svc.get("hermes_args", {})
    command = hermes_args.get("command", "npx")
    args = hermes_args.get("args", [])

    # Build env dict: start with what the user provided, filter to only what the service needs
    env_for_service = {}
    auth_fields = svc.get("auth_fields") or []
    for field in auth_fields:
        key = field["key"]
        if key in env_vars and env_vars[key]:
            env_for_service[key] = env_vars[key]

    # Check if zero-config service has all required fields
    has_all_keys = True
    for field in auth_fields:
        key = field["key"]
        if key not in env_for_service or not env_for_service[key]:
            has_all_keys = False
            break

    if svc.get("tier") == "paste-key" and not has_all_keys:
        missing = [f["key"] for f in auth_fields
                   if f["key"] not in env_for_service or not env_for_service[f["key"]]]
        return _send_json(handler, {
            "error": "Missing required credentials",
            "missing_fields": missing,
            "auth_fields": auth_fields,
        }, 400)

    # Run hermes mcp add
    ok, stdout, stderr = _mcp_add(service_id, command, args, env_for_service)

    if ok:
        # Brief wait for process to register
        time.sleep(2)
        # Verify it shows up
        servers = _mcp_list()
        match = next((s for s in servers if s["name"] == service_id), None)
        return _send_json(handler, {
            "status": "installed",
            "service_id": service_id,
            "server_info": match,
        })
    else:
        return _send_json(handler, {
            "error": f"Installation failed: {stderr or stdout}",
        }, 500)


def handle_post_uninstall(handler):
    """POST /api/mcp-services/uninstall"""
    req = _read_body(handler)

    service_id = (req.get("id") or "").strip()
    if not service_id:
        return _send_json(handler, {"error": "Missing service id"}, 400)

    ok, stdout, stderr = _mcp_remove(service_id)

    if ok:
        return _send_json(handler, {"status": "uninstalled", "service_id": service_id})
    else:
        return _send_json(handler, {
            "error": f"Uninstall failed: {stderr or stdout}",
        }, 500)
