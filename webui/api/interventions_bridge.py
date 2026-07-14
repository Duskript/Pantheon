
"""interventions_bridge.py — Ichor Forge / Gate interventions adapter.

Read-only summary of recent code-quality blocks, gate interventions,
and recurring failure patterns. No destructive operations.

Endpoints:
  GET /api/work/interventions → recent intervention summary
"""

from __future__ import annotations

import json
import os
import glob
from pathlib import Path
from datetime import datetime, timezone

from api.helpers import bad, j

FORGE_LOG_DIR = os.path.expanduser("~/pantheon/logs")
GATE_LOG_PATTERN = "ichor_gate_*.jsonl"


def _parse_gate_logs(limit=50):
    """Read recent gate intervention log entries."""
    pattern = os.path.join(FORGE_LOG_DIR, GATE_LOG_PATTERN)
    log_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    
    entries = []
    for log_file in log_files[:3]:  # Only scan 3 most recent log files
        try:
            with open(log_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        entries.append({
                            "timestamp": entry.get("timestamp"),
                            "gate": entry.get("gate"),
                            "kind": entry.get("kind"),
                            "god": entry.get("god"),
                            "file": entry.get("file"),
                            "message": entry.get("message", "")[:200],
                            "status": entry.get("status"),
                        })
                    except json.JSONDecodeError:
                        continue
        except Exception:
            continue
        if len(entries) >= limit:
            break

    entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
    return entries[:limit]


def _forge_summary():
    """Get a quick Forge stats summary."""
    gate_files = glob.glob(os.path.join(FORGE_LOG_DIR, GATE_LOG_PATTERN))
    return {
        "log_files_count": len(gate_files),
        "log_dir_exists": os.path.isdir(FORGE_LOG_DIR),
    }


def _get_interventions(parsed):
    from urllib.parse import parse_qs
    qs = parse_qs(parsed.query or "")
    limit = min(int((qs.get("limit") or ["50"])[0]), 200)

    entries = _parse_gate_logs(limit=limit)
    forge = _forge_summary()

    # Group by kind
    by_kind = {}
    for e in entries:
        kind = e.get("kind", "unknown")
        by_kind.setdefault(kind, 0)
        by_kind[kind] += 1

    return {
        "interventions": entries,
        "total": len(entries),
        "by_kind": by_kind,
        "forge": forge,
    }


def handle_interventions(handler, parsed):
    path = parsed.path
    if path == "/api/work/interventions":
        return j(handler, _get_interventions(parsed))
    return False
