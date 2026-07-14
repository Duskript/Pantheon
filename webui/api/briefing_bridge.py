"""
briefing_bridge.py — Dawn Patrol read-only adapter for Olympus UI.

Exposes the latest Dawn Patrol digest, history, and source-health
indicators without exposing credentials or raw cron internals.

Endpoints:
  GET /api/briefing/latest       → latest markdown digest
  GET /api/briefing/history      → paginated list of past briefings
  GET /api/briefing/source-health → X / GitHub / arXiv / Reddit status
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from datetime import datetime, timezone

from api.helpers import bad, j

DAWN_PATROL_OUTPUT_DIR = os.path.expanduser("~/.hermes/cron/output/82d117ac1566")
COLLECTOR_SCRIPT = os.path.expanduser("~/.hermes/scripts/dawn-patrol-digest-collector.py")


def _latest_briefing_file():
    root = Path(DAWN_PATROL_OUTPUT_DIR)
    if not root.is_dir():
        return None
    md_files = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return md_files[0] if md_files else None


def _parse_briefing(content):
    sections = {}
    current_section = "_header"
    lines = []
    for line in content.split("\n"):
        if line.startswith("## ") or line.startswith("# "):
            if current_section:
                sections[current_section] = "\n".join(lines).strip()
            current_section = line.lstrip("#").strip().lower().replace(" ", "_")
            lines = []
        else:
            lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(lines).strip()
    return sections


def _source_health(content):
    health = {
        "x": {"status": "unknown", "items": 0},
        "github": {"status": "unknown", "items": 0},
        "arxiv": {"status": "unknown", "items": 0},
        "reddit": {"status": "unknown", "items": 0},
        "web": {"status": "unknown", "items": 0},
    }
    lower = content.lower()
    for source in ("x", "github", "arxiv", "reddit", "web"):
        matches = re.findall(re.escape(source), lower, re.IGNORECASE)
        health[source]["items"] = len(matches)
        health[source]["status"] = "ok" if matches else "degraded"
    return health


def handle_briefing(handler, parsed):
    path = parsed.path
    if path == "/api/briefing/latest":
        return _handle_latest(handler)
    if path == "/api/briefing/history":
        return _handle_history(handler, parsed)
    if path == "/api/briefing/source-health":
        return _handle_source_health(handler)
    return False


def _handle_latest(handler):
    latest = _latest_briefing_file()
    if not latest:
        return bad(handler, "No Dawn Patrol briefings found", status=404)
    try:
        content = latest.read_text(encoding="utf-8")
        sections = _parse_briefing(content)
        mtime = datetime.fromtimestamp(latest.stat().st_mtime, tz=timezone.utc).isoformat()
        return j(handler, {
            "briefing": {
                "file": latest.name,
                "generated_at": mtime,
                "sections": sections,
                "source_health": _source_health(content),
            }
        })
    except Exception as exc:
        return bad(handler, "Failed to read briefing: {}".format(exc), status=500)


def _handle_history(handler, parsed):
    from urllib.parse import parse_qs
    root = Path(DAWN_PATROL_OUTPUT_DIR)
    if not root.is_dir():
        return j(handler, {"briefings": [], "total": 0})
    qs = parse_qs(parsed.query or "")
    limit = min(int((qs.get("limit") or ["20"])[0]), 100)
    offset = int((qs.get("offset") or ["0"])[0])
    md_files = sorted(root.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    total = len(md_files)
    items = []
    for f in md_files[offset:offset + limit]:
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat()
        items.append({"file": f.name, "generated_at": mtime, "size_bytes": f.stat().st_size})
    return j(handler, {"briefings": items, "total": total, "limit": limit, "offset": offset})


def _handle_source_health(handler):
    latest = _latest_briefing_file()
    if not latest:
        return bad(handler, "No Dawn Patrol briefings found", status=404)
    try:
        content = latest.read_text(encoding="utf-8")
        health = _source_health(content)
        collector_exists = os.path.isfile(COLLECTOR_SCRIPT)
        return j(handler, {
            "source_health": health,
            "collector": {"exists": collector_exists, "path": COLLECTOR_SCRIPT if collector_exists else None},
            "based_on": latest.name,
        })
    except Exception as exc:
        return bad(handler, "Failed to check source health: {}".format(exc), status=500)
