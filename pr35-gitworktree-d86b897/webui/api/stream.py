"""Hermes WebUI — Codex-Stream data API.

Reads entity, edge, and metric data from the Ichor knowledge graph DB
and the full Athenaeum, serving it as JSON for the Olympus UI Stream
Dashboard (T17).

Primary data sources:
  - Ichor graph DB (~/.hermes/pantheon/graph.db) — 9K+ nodes, 147K+ edges
  - Full Athenaeum filesystem (~/athenaeum/) — storage size, codex count
  - Codex-Stream hotness.json — fallback when graph DB is unavailable
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
ATHENAEUM_ROOT = Path(os.path.expanduser("~/athenaeum"))
GRAPH_DB = Path(os.path.expanduser("~/.hermes/pantheon/graph.db"))

# ── Graph DB helpers ──────────────────────────────────────────────

# Map node types to KnowledgeGraph categories for the frontend
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
    "concept": "concept",
    "place": "place",
    "media": "media",
}


def _get_graph_db() -> sqlite3.Connection | None:
    """Open the Ichor graph database, return None if unavailable."""
    try:
        if GRAPH_DB.exists():
            conn = sqlite3.connect(str(GRAPH_DB))
            conn.row_factory = sqlite3.Row
            return conn
    except Exception:
        pass
    return None


def _graph_entity_count(db: sqlite3.Connection) -> int:
    """Count focus-type nodes in the graph."""
    try:
        focus = ('tool', 'project', 'person', 'organization', 'system',
                  'skill', 'event', 'fact', 'preference', 'decision',
                  'concept', 'place', 'media')
        placeholders = ",".join("?" for _ in focus)
        row = db.execute(
            f"SELECT COUNT(*) as cnt FROM nodes WHERE type IN ({placeholders}) AND label != ''",
            list(focus),
        ).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def _graph_edge_count(db: sqlite3.Connection) -> int:
    """Count edges in the graph."""
    try:
        row = db.execute("SELECT COUNT(*) as cnt FROM edges").fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def _graph_top_entity(db: sqlite3.Connection) -> str | None:
    """Return the label of the most-connected node."""
    try:
        row = db.execute("""
            SELECT n.label FROM nodes n
            JOIN edges e ON e.source_id = n.id
            WHERE n.label != ''
            GROUP BY n.id
            ORDER BY COUNT(*) DESC
            LIMIT 1
        """).fetchone()
        return row["label"] if row else None
    except Exception:
        return None


# ── Codex-Stream JSON helpers (fallback) ──────────────────────────

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


# ── Public API ────────────────────────────────────────────────────

def get_stream_entities() -> dict:
    """Return entities from the Ichor graph DB, falling back to hotness.json."""
    db = _get_graph_db()
    entities = []

    if db is not None:
        try:
            focus_types = ('tool', 'project', 'person', 'organization', 'system',
                            'skill', 'event', 'fact', 'preference', 'decision',
                            'concept', 'place', 'media')
            placeholders = ",".join("?" for _ in focus_types)
            rows = db.execute(f"""
                SELECT n.label, n.type, COUNT(e.target_id) as edge_count
                FROM nodes n
                LEFT JOIN edges e ON e.source_id = n.id
                WHERE n.type IN ({placeholders})
                  AND n.label != ''
                GROUP BY n.id
                ORDER BY edge_count DESC
                LIMIT 200
            """, list(focus_types)).fetchall()

            for row in rows:
                name = row["label"].rstrip(":")
                entities.append({
                    "name": name,
                    "mentions": max(1, row["edge_count"]),
                    "promoted": row["edge_count"] >= 10,
                    "category": _NODE_TYPE_TO_CATEGORY.get(row["type"], "unknown"),
                })
            entities.sort(key=lambda e: e["mentions"], reverse=True)
        except Exception as exc:
            logger.warning("Graph DB entity query failed: %s", exc)
        finally:
            try:
                db.close()
            except Exception:
                pass

    # Fallback to hotness.json if graph DB returned nothing
    if not entities:
        hotness = _read_json(STREAM_ROOT / "hotness.json")
        entities = _get_entities_list(hotness)

    return {"entities": entities, "total": len(entities)}


def get_stream_edges() -> dict:
    """Return edges from the Ichor graph DB, falling back to cooccurrence.jsonl."""
    db = _get_graph_db()
    edges = []
    seen = set()

    if db is not None:
        try:
            # Get focused entity IDs
            focus_types = ('tool', 'project', 'person', 'organization', 'system',
                            'skill', 'event', 'fact', 'preference', 'decision',
                            'concept', 'place', 'media')
            placeholders = ",".join("?" for _ in focus_types)
            node_rows = db.execute(f"""
                SELECT id, label FROM nodes
                WHERE type IN ({placeholders}) AND label != ''
            """, list(focus_types)).fetchall()

            id_to_label = {row["id"]: row["label"] for row in node_rows}
            entity_ids = list(id_to_label.keys())

            if entity_ids:
                eids_ph = ",".join("?" for _ in entity_ids)
                edge_rows = db.execute(f"""
                    SELECT source_id, target_id, type, weight
                    FROM edges
                    WHERE source_id IN ({eids_ph})
                      AND target_id IN ({eids_ph})
                      AND source_id != target_id
                    ORDER BY weight DESC
                    LIMIT 500
                """, entity_ids + entity_ids).fetchall()

                for row in edge_rows:
                    source = id_to_label.get(row["source_id"], row["source_id"])
                    target = id_to_label.get(row["target_id"], row["target_id"])
                    key = f"{source}|{target}"
                    if key not in seen and source and target:
                        seen.add(key)
                        edges.append({
                            "source": source,
                            "target": target,
                            "weight": max(1, int(row["weight"] * 10)),
                        })
        except Exception as exc:
            logger.warning("Graph DB edge query failed: %s", exc)
        finally:
            try:
                db.close()
            except Exception:
                pass

    # Fallback to cooccurrence.jsonl
    if not edges:
        edges_file = STREAM_ROOT / "cooccurrence.jsonl"
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
    """Return dashboard metrics from the full Pantheon system."""
    metrics = {
        "storage_mb": 0,
        "sources": 0,
        "chunks": 0,
        "entities": 0,
        "connections": 0,
        "trending": None,
    }

    # Storage size — full Athenaeum (not just Codex-Stream)
    try:
        result = subprocess.run(
            ["du", "-sm", str(ATHENAEUM_ROOT)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            metrics["storage_mb"] = int(result.stdout.split()[0])
    except Exception:
        # Fall back to Codex-Stream only
        try:
            result = subprocess.run(
                ["du", "-sm", str(STREAM_ROOT)],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                metrics["storage_mb"] = int(result.stdout.split()[0])
        except Exception:
            pass

    # Sources — count codex directories in the Athenaeum
    try:
        if ATHENAEUM_ROOT.exists():
            metrics["sources"] = len([
                d for d in ATHENAEUM_ROOT.iterdir()
                if d.is_dir() and d.name.startswith("Codex-")
            ])
    except Exception:
        pass

    # Chunks — total .md files in the Athenaeum
    try:
        if ATHENAEUM_ROOT.exists():
            metrics["chunks"] = len(list(ATHENAEUM_ROOT.rglob("*.md")))
    except Exception:
        pass

    # Entities and connections from the graph DB
    db = _get_graph_db()
    if db is not None:
        try:
            metrics["entities"] = _graph_entity_count(db)
            metrics["connections"] = _graph_edge_count(db)
            top = _graph_top_entity(db)
            if top:
                metrics["trending"] = top.rstrip(":")
        except Exception as exc:
            logger.warning("Graph DB metrics query failed: %s", exc)
        finally:
            try:
                db.close()
            except Exception:
                pass

    # Fallback: if graph DB gave no entities, use hotness + cooccurrence
    if metrics["entities"] == 0:
        hotness = _read_json(STREAM_ROOT / "hotness.json")
        entities = _get_entities_list(hotness)
        metrics["entities"] = len(entities)
        if entities:
            metrics["trending"] = entities[0]["name"]

    if metrics["connections"] == 0:
        edges_resp = get_stream_edges()
        metrics["connections"] = edges_resp["total"]

    # Also count raw sources as a floor
    raw_dir = STREAM_ROOT / "raw"
    if raw_dir.exists():
        raw_sources = len([d for d in raw_dir.iterdir() if d.is_dir()])
        metrics["sources"] = max(metrics["sources"], raw_sources)

    return metrics


# ── Ichor Knowledge Graph ─────────────────────────────────────────

def get_ichor_graph() -> dict:
    """Query the Ichor knowledge graph for entities and relationships.

    Returns:
        {"entities": [...], "edges": [...], "total_entities": int, "total_edges": int}
    """
    db = _get_graph_db()
    if db is None:
        return {"entities": [], "edges": [], "total_entities": 0, "total_edges": 0}

    try:
        # Entities: nodes with meaningful types, exclude sessions/codexes
        focus_types = ('tool', 'project', 'person', 'organization', 'system',
                        'skill', 'event', 'fact', 'preference', 'decision',
                        'concept', 'place', 'media')
        placeholders = ",".join("?" for _ in focus_types)
        query = f"""
            SELECT id, type, label, codex FROM nodes
            WHERE type IN ({placeholders})
              AND label != ''
            ORDER BY updated_at DESC
            LIMIT 200
        """
        rows = db.execute(query, list(focus_types)).fetchall()

        # Build entity list
        entity_ids = set()
        entities = []
        for row in rows:
            entity_ids.add(row["id"])
            entities.append({
                "name": row["label"],
                "mentions": 1,
                "promoted": False,
                "category": _NODE_TYPE_TO_CATEGORY.get(row["type"], "unknown"),
            })

        # Edges between these entities
        if entity_ids:
            eids_list = list(entity_ids)
            placeholders = ",".join("?" for _ in eids_list)
            edge_rows = db.execute(f"""
                SELECT e.source_id, e.target_id, e.type, e.weight
                FROM edges e
                WHERE e.source_id IN ({placeholders})
                  AND e.target_id IN ({placeholders})
                  AND e.source_id != e.target_id
                ORDER BY e.weight DESC
                LIMIT 500
            """, eids_list + eids_list).fetchall()
        else:
            edge_rows = []

        # Build edge label map
        id_to_label = {row["id"]: row["label"] for row in rows}

        seen_edges = set()
        edges = []
        for row in edge_rows:
            source_label = id_to_label.get(row["source_id"], row["source_id"])
            target_label = id_to_label.get(row["target_id"], row["target_id"])
            key = f"{source_label}|{target_label}"
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append({
                    "source": source_label,
                    "target": target_label,
                    "weight": max(1, int(row["weight"] * 10)),
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
