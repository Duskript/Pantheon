"""Hermes WebUI — Codex-Stream data API.

Reads entity, edge, and metric data from ~/athenaeum/Codex-Stream/
and serves it as JSON for the Olympus UI Stream Dashboard (T17).
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

STREAM_ROOT = Path(os.path.expanduser("~/athenaeum/Codex-Stream"))


def _read_json(path: Path) -> dict:
    """Read a JSON file, return empty dict on any error."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_entities_list(hotness: dict) -> list:
    """Extract entities as a flat list from hotness.json (handles both list and dict formats)."""
    entities_data = hotness.get("entities", [])
    result = []
    if isinstance(entities_data, list):
        for entry in entities_data:
            if isinstance(entry, dict):
                result.append({
                    "name": entry.get("name", ""),
                    "mentions": entry.get("mentions", 0),
                    "promoted": entry.get("promoted", False),
                    "category": entry.get("category", "unknown"),
                })
    elif isinstance(entities_data, dict):
        for name, data in entities_data.items():
            if isinstance(data, dict):
                result.append({
                    "name": name,
                    "mentions": data.get("mentions", 0),
                    "promoted": data.get("promoted", False),
                    "category": data.get("category", "unknown"),
                })
            else:
                result.append({
                    "name": name,
                    "mentions": data if isinstance(data, (int, float)) else 0,
                    "promoted": False,
                    "category": "unknown",
                })
    result.sort(key=lambda e: e["mentions"], reverse=True)
    return result


def get_stream_entities() -> dict:
    """Return entities with hotness from hotness.json."""
    hotness = _read_json(STREAM_ROOT / "hotness.json")
    entities = _get_entities_list(hotness)
    return {"entities": entities, "total": len(entities)}


def get_stream_edges() -> dict:
    """Return co-occurrence edges from cooccurrence.jsonl."""
    edges_file = STREAM_ROOT / "cooccurrence.jsonl"
    edges = []
    seen = set()
    try:
        if edges_file.exists():
            for line in edges_file.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                try:
                    edge = json.loads(line)
                    source = edge.get("source", "")
                    target = edge.get("target", "")
                    weight = edge.get("weight", 1)
                    key = f"{source}|{target}"
                    if key not in seen and source and target:
                        seen.add(key)
                        edges.append({
                            "source": source,
                            "target": target,
                            "weight": weight,
                        })
                except (ValueError, KeyError):
                    continue
    except Exception:
        pass
    return {"edges": edges, "total": len(edges)}


def get_stream_metrics() -> dict:
    """Return dashboard metrics."""
    metrics = {
        "storage_mb": 0,
        "sources": 0,
        "chunks": 0,
        "entities": 0,
        "connections": 0,
        "trending": None,
    }

    # Storage size
    try:
        result = subprocess.run(
            ["du", "-sm", str(STREAM_ROOT)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            metrics["storage_mb"] = int(result.stdout.split()[0])
    except Exception:
        pass

    # Sources (provider dirs in raw/)
    raw_dir = STREAM_ROOT / "raw"
    if raw_dir.exists():
        metrics["sources"] = len([d for d in raw_dir.iterdir() if d.is_dir()])

    # Chunks (recursive .md count in raw/)
    try:
        metrics["chunks"] = len(list(raw_dir.rglob("*.md")))
    except Exception:
        pass

    # Entities
    hotness = _read_json(STREAM_ROOT / "hotness.json")
    entities = _get_entities_list(hotness)
    metrics["entities"] = len(entities)
    if entities:
        metrics["trending"] = entities[0]["name"]

    # Connections (edges)
    edges = get_stream_edges()
    metrics["connections"] = edges["total"]

    return metrics
