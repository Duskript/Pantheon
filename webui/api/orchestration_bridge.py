
"""orchestration_bridge.py — Conductor workflow engine adapter for Olympus UI.

Read-only health, handoff, run, and rule data. No destructive operations.

Endpoints:
  GET /api/orchestration/health   → Conductor + NATS health
  GET /api/orchestration/handoffs → pending handoffs
  GET /api/orchestration/runs     → recent workflow runs
  GET /api/orchestration/rules    → active rule definitions
"""

from __future__ import annotations

import json
import os
import glob
from pathlib import Path
from datetime import datetime, timezone

from api.helpers import bad, j

CONDUCTOR_DIR = os.path.expanduser("~/pantheon/conductor")
STATE_DIR = os.path.join(CONDUCTOR_DIR, "state")
RULES_DIR = os.path.join(CONDUCTOR_DIR, "rules")
WORKFLOWS_DIR = os.path.join(CONDUCTOR_DIR, "workflows")
CONDUCTOR_URL = "http://127.0.0.1:8088"


def _http_get(url, timeout=3):
    from urllib.request import Request, urlopen
    from urllib.error import URLError
    try:
        req = Request(url, headers={"User-Agent": "Olympus-UI/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            return {"status_code": resp.status, "body": resp.read().decode("utf-8", errors="replace")}
    except Exception as e:
        return {"status_code": 0, "error": str(e)}


def _count_files(glob_pattern):
    return len(glob.glob(glob_pattern))


def _get_health():
    health = _http_get(CONDUCTOR_URL + "/health")
    nats_running = False
    try:
        import subprocess
        result = subprocess.run(["systemctl", "is-active", "nats-server"], capture_output=True, text=True, timeout=5)
        nats_running = result.stdout.strip() == "active"
    except Exception:
        pass

    return {
        "conductor": {
            "url": CONDUCTOR_URL,
            "healthy": health.get("status_code") == 200,
            "response": health.get("body", ""),
        },
        "nats": {
            "running": nats_running,
            "url": "nats://127.0.0.1:4222",
        },
        "rules_count": _count_files(os.path.join(RULES_DIR, "*.yaml")),
        "workflows_count": _count_files(os.path.join(WORKFLOWS_DIR, "*.yaml")),
        "state_files": _count_files(os.path.join(STATE_DIR, "*.json")),
    }


def _get_handoffs(parsed):
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query or "")
    limit = min(int((qs.get("limit") or ["20"])[0]), 100)

    handoff_dir = os.path.join(CONDUCTOR_DIR, "handoffs")
    if not os.path.isdir(handoff_dir):
        return {"handoffs": [], "total": 0}

    items = []
    try:
        files = sorted(Path(handoff_dir).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
                items.append({
                    "id": data.get("workflow_id", f.stem),
                    "state": data.get("state", "unknown"),
                    "updated_at": mtime,
                })
            except Exception:
                items.append({"id": f.stem, "state": "unreadable", "updated_at": None})
    except Exception:
        pass

    return {"handoffs": items, "total": len(items)}


def _get_runs(parsed):
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query or "")
    limit = min(int((qs.get("limit") or ["20"])[0]), 100)

    if not os.path.isdir(STATE_DIR):
        return {"runs": [], "total": 0}

    items = []
    try:
        files = sorted(
            [f for f in Path(STATE_DIR).glob("*.json") if not f.name.endswith(".aborted.json")],
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
                items.append({
                    "workflow_id": data.get("workflow_id", f.stem),
                    "status": data.get("status", "unknown"),
                    "current_step": data.get("current_step"),
                    "started_at": data.get("started_at"),
                    "updated_at": mtime,
                })
            except Exception:
                items.append({"workflow_id": f.stem, "status": "unreadable"})
    except Exception:
        pass

    return {"runs": items, "total": len(items)}


def _get_rules():
    if not os.path.isdir(RULES_DIR):
        return {"rules": [], "total": 0}
    items = []
    for f in sorted(Path(RULES_DIR).glob("*.yaml")):
        try:
            import yaml
            with open(f) as fh:
                data = yaml.safe_load(fh)
            items.append({"name": f.stem, "definition": data})
        except Exception:
            items.append({"name": f.stem, "error": "unreadable"})
    return {"rules": items, "total": len(items)}


def handle_orchestration(handler, parsed):
    path = parsed.path
    if path == "/api/orchestration/health":
        return j(handler, _get_health())
    if path == "/api/orchestration/handoffs":
        return j(handler, _get_handoffs(parsed))
    if path == "/api/orchestration/runs":
        return j(handler, _get_runs(parsed))
    if path == "/api/orchestration/rules":
        return j(handler, _get_rules())
    return False
