"""Hermes WebUI — Codex-Stream data API.

Reads entity, edge, and metric data from ~/athenaeum/Codex-Stream/
and serves it as JSON for the Olympus UI Stream Dashboard (T17).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
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


# ── Ichor Knowledge Graph ──────────────────────────────────


GRAPH_DB = Path(os.path.expanduser("~/.hermes/pantheon/graph.db"))

# Map node types to KnowledgeGraph categories
_NODE_TYPE_TO_CATEGORY: dict[str, str] = {
    "tool": "technology",
    "project": "project",
    "person": "person",
    "organization": "company",
    "system": "technology",
    "skill": "technology",
    "event": "unknown",
    "fact": "unknown",
    "preference": "unknown",
    "decision": "unknown",
}


def _get_graph_db() -> sqlite3.Connection | None:
    """Open the Ichor graph database, return None if unavailable."""
    try:
        if GRAPH_DB.exists():
            return sqlite3.connect(str(GRAPH_DB))
    except Exception:
        pass
    return None


def get_ichor_graph() -> dict:
    """Query the Ichor knowledge graph for entities and relationships.

    Returns:
        {"entities": [...], "edges": [...], "total_entities": int, "total_edges": int}
    """
    db = _get_graph_db()
    if db is None:
        return {"entities": [], "edges": [], "total_entities": 0, "total_edges": 0}

    try:
        c = db.cursor()

        # Entities: nodes with meaningful types, exclude sessions/codexes
        focus_types = ('tool', 'project', 'person', 'organization', 'system',
                        'skill', 'event', 'fact', 'preference', 'decision')
        placeholders = ",".join("?" for _ in focus_types)
        query = f"""
            SELECT id, type, label, codex FROM nodes
            WHERE type IN ({placeholders})
              AND label != ''
            ORDER BY updated_at DESC
            LIMIT 200
        """
        c.execute(query, list(focus_types))
        nodes = c.fetchall()

        # Build entity list
        entity_ids = set()
        entities = []
        for nid, ntype, label, codex in nodes:
            entity_ids.add(nid)
            entities.append({
                "name": label,
                "mentions": 1,
                "category": _NODE_TYPE_TO_CATEGORY.get(ntype, "unknown"),
            })

        # Edges between these entities
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            edge_query = f"""
                SELECT e.source_id, e.target_id, e.type, e.weight
                FROM edges e
                WHERE e.source_id IN ({placeholders})
                  AND e.target_id IN ({placeholders})
                  AND e.source_id != e.target_id
                ORDER BY e.weight DESC
                LIMIT 500
            """
            c.execute(edge_query, list(entity_ids) + list(entity_ids))
            edge_rows = c.fetchall()
        else:
            edge_rows = []

        # Build edge label map — resolve source/target IDs to names
        # (we need a reverse lookup from id → label)
        id_to_label = {row[0]: row[2] for row in nodes}

        seen_edges = set()
        edges = []
        for src, tgt, rtype, weight in edge_rows:
            source_label = id_to_label.get(src, src)
            target_label = id_to_label.get(tgt, tgt)
            key = f"{source_label}|{target_label}"
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({
                    "source": source_label,
                    "target": target_label,
                    "weight": max(1, int(weight * 10)),
                })

        db.close()
        return {
            "entities": entities,
            "edges": edges,
            "total_entities": len(entities),
            "total_edges": len(edges),
        }
    except Exception as exc:
        try:
            db.close()
        except Exception:
            pass
        return {
            "entities": [],
            "edges": [],
            "total_entities": 0,
            "total_edges": 0,
            "error": str(exc),
        }
