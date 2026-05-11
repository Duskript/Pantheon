"""GraphClient — SQLite entity-relationship graph for the Pantheon.

Stores Codex-scoped nodes and typed edges. Supports:
- Node creation (files, sessions, entities, codexes)
- Edge creation (references, contains, mentioned_in, derived_from, etc.)
- Query: find connected nodes, pathfinding (BFS), search
- FTS5 full-text search on node labels and metadata

Hades will use this for consolidation decisions.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Default database path
_REAL_HOME = os.path.expanduser("~konan")
_DEFAULT_DB_PATH = f"{_REAL_HOME}/.hermes/pantheon/graph.db"

# Node types — extended with Thoth-style entity types
NODE_TYPE_FILE = "file"
NODE_TYPE_SESSION = "session"
NODE_TYPE_ENTITY = "entity"
NODE_TYPE_CODEX = "codex"
NODE_TYPE_URL = "url"
NODE_TYPE_CONCEPT = "concept"
NODE_TYPE_PERSON = "person"
NODE_TYPE_PROJECT = "project"
NODE_TYPE_TOOL = "tool"
NODE_TYPE_SYSTEM = "system"
NODE_TYPE_ORGANIZATION = "organization"
NODE_TYPE_PLACE = "place"
NODE_TYPE_EVENT = "event"
NODE_TYPE_DECISION = "decision"
NODE_TYPE_PREFERENCE = "preference"
NODE_TYPE_MEDIA = "media"
NODE_TYPE_SKILL = "skill"
NODE_TYPE_FACT = "fact"
VALID_NODE_TYPES = {
    NODE_TYPE_FILE, NODE_TYPE_SESSION, NODE_TYPE_ENTITY,
    NODE_TYPE_CODEX, NODE_TYPE_URL, NODE_TYPE_CONCEPT,
    NODE_TYPE_PERSON, NODE_TYPE_PROJECT, NODE_TYPE_TOOL,
    NODE_TYPE_SYSTEM, NODE_TYPE_ORGANIZATION, NODE_TYPE_PLACE,
    NODE_TYPE_EVENT, NODE_TYPE_DECISION, NODE_TYPE_PREFERENCE,
    NODE_TYPE_MEDIA, NODE_TYPE_SKILL, NODE_TYPE_FACT,
}

# Edge types — extended with full Thoth-style directional relations
EDGE_REFERENCES = "references"
EDGE_CONTAINS = "contains"
EDGE_MENTIONED_IN = "mentioned_in"
EDGE_DERIVED_FROM = "derived_from"
EDGE_ARCHIVED_TO = "archived_to"
EDGE_INGESTED_FROM = "ingested_from"
EDGE_RELATED_TO = "related_to"
EDGE_LINKS_TO = "links_to"
# Dependency
EDGE_DEPENDS_ON = "depends_on"
EDGE_REQUIRES = "requires"
EDGE_IMPLEMENTS = "implements"
EDGE_ENABLES = "enables"
EDGE_BLOCKS = "blocks"
# Ownership
EDGE_BUILT_BY = "built_by"
EDGE_CREATED_BY = "created_by"
EDGE_MANAGED_BY = "managed_by"
EDGE_MAINTAINED_BY = "maintained_by"
EDGE_OWNED_BY = "owned_by"
# Deployment
EDGE_DEPLOYED_ON = "deployed_on"
EDGE_RUNS_ON = "runs_on"
EDGE_HOSTED_AT = "hosted_at"
EDGE_CONFIGURED_IN = "configured_in"
# Heirarchy / composition
EDGE_PARENT_OF = "parent_of"
EDGE_CHILD_OF = "child_of"
EDGE_PART_OF = "part_of"
# Provenance
EDGE_INSPIRED_BY = "inspired_by"
EDGE_BASED_ON = "based_on"
EDGE_FORKED_FROM = "forked_from"
# Temporal
EDGE_PRECEDES = "precedes"
EDGE_FOLLOWS = "follows"
EDGE_SUPERSEDES = "supersedes"
EDGE_REPLACES = "replaces"
EDGE_TRIGGERS = "triggers"
# Knowledge
EDGE_CITES = "cites"
EDGE_EXTRACTED_FROM = "extracted_from"
EDGE_BUILDS_ON = "builds_on"
EDGE_EXTENDS = "extends"
EDGE_CONTRADICTS = "contradicts"
# Usage
EDGE_USES = "uses"
EDGE_CONSUMES = "consumes"
EDGE_GENERATES = "generates"
EDGE_PRODUCES = "produces"
EDGE_CONFIGURES = "configures"
# Evaluation
EDGE_PREFERRED_OVER = "preferred_over"
EDGE_ALTERNATE_TO = "alternate_to"
EDGE_RECOMMENDS = "recommends"
EDGE_CRITIQUES = "critiques"
# Spatial
EDGE_LOCATED_IN = "located_in"
EDGE_CONNECTS_TO = "connects_to"
EDGE_COMMUNICATES_WITH = "communicates_with"
# Generic impact
EDGE_IMPACTS = "impacts"
EDGE_INFLUENCES = "influences"
EDGE_SUPPORTS = "supports"
EDGE_ALIGNS_WITH = "aligns_with"

VALID_EDGE_TYPES = {
    # Original
    EDGE_REFERENCES, EDGE_CONTAINS, EDGE_MENTIONED_IN,
    EDGE_DERIVED_FROM, EDGE_ARCHIVED_TO, EDGE_INGESTED_FROM,
    EDGE_RELATED_TO, EDGE_LINKS_TO,
    # Dependency
    EDGE_DEPENDS_ON, EDGE_REQUIRES, EDGE_IMPLEMENTS, EDGE_ENABLES, EDGE_BLOCKS,
    # Ownership
    EDGE_BUILT_BY, EDGE_CREATED_BY, EDGE_MANAGED_BY, EDGE_MAINTAINED_BY, EDGE_OWNED_BY,
    # Deployment
    EDGE_DEPLOYED_ON, EDGE_RUNS_ON, EDGE_HOSTED_AT, EDGE_CONFIGURED_IN,
    # Heirarchy
    EDGE_PARENT_OF, EDGE_CHILD_OF, EDGE_PART_OF,
    # Provenance
    EDGE_INSPIRED_BY, EDGE_BASED_ON, EDGE_FORKED_FROM,
    # Temporal
    EDGE_PRECEDES, EDGE_FOLLOWS, EDGE_SUPERSEDES, EDGE_REPLACES, EDGE_TRIGGERS,
    # Knowledge
    EDGE_CITES, EDGE_EXTRACTED_FROM, EDGE_BUILDS_ON, EDGE_EXTENDS, EDGE_CONTRADICTS,
    # Usage
    EDGE_USES, EDGE_CONSUMES, EDGE_GENERATES, EDGE_PRODUCES, EDGE_CONFIGURES,
    # Evaluation
    EDGE_PREFERRED_OVER, EDGE_ALTERNATE_TO, EDGE_RECOMMENDS, EDGE_CRITIQUES,
    # Spatial
    EDGE_LOCATED_IN, EDGE_CONNECTS_TO, EDGE_COMMUNICATES_WITH,
    # Generic impact
    EDGE_IMPACTS, EDGE_INFLUENCES, EDGE_SUPPORTS, EDGE_ALIGNS_WITH,
}

# Vague / non-specific relations that are rejected before save (Thoth pattern)
BANNED_EDGE_TYPES = {
    "related_to", "associated_with", "connected_to",
    "linked_to", "has_relation", "involves", "correlates_with",
    "tied_to", "coupled_with", "bound_to",
}


class GraphClient:
    """SQLite-backed entity-relationship graph.

    Thread-safe: uses WAL mode and per-operation connections
    (or a single shared connection with a lock).
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._conn: Optional[sqlite3.Connection] = None

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the database connection and ensure schema exists."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def _ensure_schema(self) -> None:
        """Create tables if they don't exist."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                codex TEXT,
                label TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                target_id TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                weight REAL DEFAULT 1.0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                UNIQUE(source_id, target_id, type)
            );

            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
            CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
            CREATE INDEX IF NOT EXISTS idx_nodes_codex ON nodes(codex);
            CREATE INDEX IF NOT EXISTS idx_nodes_label ON nodes(label);
        """)

        # FTS5 for full-text search on node labels + metadata
        try:
            self._conn.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    node_id UNINDEXED,
                    label,
                    metadata_text,
                    content='nodes',
                    content_rowid='rowid'
                );
            """)
        except sqlite3.OperationalError as exc:
            if "already exists" not in str(exc):
                logger.debug("FTS5 setup: %s", exc)

        self._conn.commit()

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def upsert_node(
        self,
        node_id: str,
        type_: str,
        label: str,
        *,
        codex: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create or update a node. Returns the node ID."""
        if type_ not in VALID_NODE_TYPES:
            raise ValueError(f"Invalid node type: {type_}. Valid: {', '.join(sorted(VALID_NODE_TYPES))}")

        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        now = self._now()
        meta_json = json.dumps(metadata or {})

        existing = self._conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()

        if existing:
            self._conn.execute(
                "UPDATE nodes SET label=?, codex=?, metadata=?, updated_at=? WHERE id=?",
                (label, codex, meta_json, now, node_id),
            )
        else:
            self._conn.execute(
                "INSERT INTO nodes (id, type, codex, label, metadata, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (node_id, type_, codex, label, meta_json, now, now),
            )

        # Sync FTS index
        self._sync_fts(node_id)
        self._conn.commit()
        return node_id

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by ID."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()

        if not row:
            return None
        return self._row_to_dict(row)

    def delete_node(self, node_id: str) -> bool:
        """Delete a node and all its edges. Returns True if existed."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        # Edges are cascade-deleted by FK; FTS5 content-sync handles the FTS cleanup
        self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        self._conn.commit()
        return self._conn.total_changes > 0

    def find_nodes(
        self,
        *,
        type_: Optional[str] = None,
        codex: Optional[str] = None,
        label_contains: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Find nodes by filters. All filters are optional."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        query = "SELECT * FROM nodes WHERE 1=1"
        params: list = []

        if type_:
            query += " AND type = ?"
            params.append(type_)
        if codex:
            query += " AND codex = ?"
            params.append(codex)
        if label_contains:
            query += " AND label LIKE ?"
            params.append(f"%{label_contains}%")

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def search_nodes(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Full-text search on node labels and metadata using FTS5."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        try:
            rows = self._conn.execute(
                """SELECT n.* FROM nodes n
                   JOIN nodes_fts fts ON n.id = fts.node_id
                   WHERE nodes_fts MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                (query, limit),
            ).fetchall()
            return [self._row_to_dict(r) for r in rows]
        except sqlite3.OperationalError:
            # FTS not available or no results
            return self.find_nodes(label_contains=query, limit=limit)

    def _sync_fts(self, node_id: str) -> None:
        """Sync a single node's data into the FTS index."""
        if not self._conn:
            return
        try:
            row = self._conn.execute(
                "SELECT id, label, metadata FROM nodes WHERE id = ?",
                (node_id,),
            ).fetchone()
            if row:
                meta_text = ""
                try:
                    meta = json.loads(row["metadata"])
                    if isinstance(meta, dict):
                        meta_text = " ".join(str(v) for v in meta.values() if isinstance(v, str))
                except (json.JSONDecodeError, TypeError):
                    meta_text = str(row["metadata"])
                self._conn.execute(
                    "INSERT OR REPLACE INTO nodes_fts (node_id, label, metadata_text) VALUES (?, ?, ?)",
                    (row["id"], row["label"], meta_text),
                )
        except sqlite3.OperationalError:
            pass

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        type_: str,
        *,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create an edge between two nodes. Returns edge ID."""
        if type_ not in VALID_EDGE_TYPES:
            raise ValueError(f"Invalid edge type: {type_}. Valid: {', '.join(sorted(VALID_EDGE_TYPES))}")

        # Reject vague / non-specific relations (Thoth pattern)
        if type_ in BANNED_EDGE_TYPES:
            raise ValueError(f"Banned vague relation type: '{type_}' — use a specific typed relation instead")

        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        # Ensure both nodes exist
        existing_src = self._conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (source_id,)
        ).fetchone()
        if not existing_src:
            raise ValueError(f"Source node not found: {source_id}")

        existing_tgt = self._conn.execute(
            "SELECT id FROM nodes WHERE id = ?", (target_id,)
        ).fetchone()
        if not existing_tgt:
            raise ValueError(f"Target node not found: {target_id}")

        now = self._now()
        edge_id = self._new_id()
        meta_json = json.dumps(metadata or {})

        try:
            self._conn.execute(
                "INSERT INTO edges (id, source_id, target_id, type, weight, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (edge_id, source_id, target_id, type_, weight, meta_json, now),
            )
        except sqlite3.IntegrityError:
            # Edge already exists — update weight
            self._conn.execute(
                "UPDATE edges SET weight = ?, metadata = ?, created_at = ? "
                "WHERE source_id = ? AND target_id = ? AND type = ?",
                (weight, meta_json, now, source_id, target_id, type_),
            )

        self._conn.commit()
        return edge_id

    def remove_edge(self, source_id: str, target_id: str, type_: str) -> bool:
        """Remove a specific edge."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        self._conn.execute(
            "DELETE FROM edges WHERE source_id = ? AND target_id = ? AND type = ?",
            (source_id, target_id, type_),
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def get_edges(
        self,
        *,
        node_id: Optional[str] = None,
        type_: Optional[str] = None,
        direction: str = "both",  # 'out', 'in', 'both'
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get edges, optionally filtered by node, type, and direction.

        Args:
            node_id: Filter edges connected to this node.
            type_: Filter by edge type.
            direction: 'out' (source=node_id), 'in' (target=node_id), 'both'.
            limit: Max edges to return.
        """
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        if node_id:
            if direction == "out":
                query = "SELECT * FROM edges WHERE source_id = ?"
                params: list = [node_id]
            elif direction == "in":
                query = "SELECT * FROM edges WHERE target_id = ?"
                params = [node_id]
            else:
                query = "SELECT * FROM edges WHERE source_id = ? OR target_id = ?"
                params = [node_id, node_id]
        else:
            query = "SELECT * FROM edges WHERE 1=1"
            params = []

        if type_:
            query += " AND type = ?"
            params.append(type_)

        query += " ORDER BY weight DESC, created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_neighbors(
        self,
        node_id: str,
        *,
        edge_type: Optional[str] = None,
        max_depth: int = 1,
    ) -> List[Dict[str, Any]]:
        """Get neighboring nodes connected by edges.

        At depth 1, returns direct neighbors.
        At depth >1, does BFS traversal (returns all reachable nodes up to depth).
        """
        if max_depth == 1:
            return self._get_direct_neighbors(node_id, edge_type)
        return self._bfs(node_id, edge_type, max_depth)

    def _get_direct_neighbors(
        self, node_id: str, edge_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get nodes directly connected to *node_id*."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        query = """
            SELECT DISTINCT n.*, e.type as edge_type, e.weight as edge_weight
            FROM nodes n
            JOIN edges e ON (e.source_id = n.id OR e.target_id = n.id)
            WHERE (e.source_id = ? OR e.target_id = ?)
              AND n.id != ?
        """
        params: list = [node_id, node_id, node_id]

        if edge_type:
            query += " AND e.type = ?"
            params.append(edge_type)

        query += " ORDER BY e.weight DESC"
        rows = self._conn.execute(query, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _bfs(
        self, start_id: str, edge_type: Optional[str] = None, max_depth: int = 3
    ) -> List[Dict[str, Any]]:
        """BFS traversal from *start_id* up to *max_depth* steps."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        visited: Set[str] = {start_id}
        results: List[Dict[str, Any]] = []
        current_level = [start_id]

        for depth in range(1, max_depth + 1):
            next_level: Set[str] = set()
            for node in current_level:
                neighbors = self._get_direct_neighbors(node, edge_type)
                for n in neighbors:
                    nid = n.get("id", "")
                    if nid and nid not in visited:
                        visited.add(nid)
                        n["_depth"] = depth
                        results.append(n)
                        next_level.add(nid)
            current_level = list(next_level)
            if not current_level:
                break

        return results

    def shortest_path(
        self, start_id: str, end_id: str, max_depth: int = 10
    ) -> Optional[List[Dict]]:
        """BFS shortest path between two nodes.

        Returns ordered list of edges forming the path, or None if no path exists.
        """
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        if start_id == end_id:
            return []

        # BFS tracking: for each node, store (parent_node, edge_to_parent)
        visited: Set[str] = {start_id}
        parent: Dict[str, Tuple[str, Dict]] = {}  # child -> (parent, edge_info)
        queue = [start_id]

        while queue:
            current = queue.pop(0)

            if current == end_id:
                break

            # Get all edges from current
            edges = self._conn.execute(
                """SELECT * FROM edges
                   WHERE source_id = ? OR target_id = ?""",
                (current, current),
            ).fetchall()

            for edge in edges:
                edge_dict = self._row_to_dict(edge)
                neighbor = edge_dict["target_id"] if edge_dict["source_id"] == current else edge_dict["source_id"]

                if neighbor not in visited and len(visited) < 500:
                    visited.add(neighbor)
                    parent[neighbor] = (current, edge_dict)
                    queue.append(neighbor)

        if end_id not in parent and start_id != end_id:
            return None  # No path

        # Reconstruct path
        path = []
        current = end_id
        while current in parent:
            p, edge = parent[current]
            path.append(edge)
            current = p

        path.reverse()
        return path[:max_depth]

    # ------------------------------------------------------------------
    # Convenience: ingest hooks
    # ------------------------------------------------------------------

    def register_file(self, relative_path: str, codex: str) -> str:
        """Register a file in the graph. Creates node + edge to its Codex.
        Returns node ID.
        """
        node_id = f"file:{relative_path}"
        self.upsert_node(
            node_id,
            NODE_TYPE_FILE,
            Path(relative_path).name,
            codex=codex,
            metadata={"path": relative_path},
        )

        # Link to its Codex
        codex_id = f"codex:{codex}"
        self.upsert_node(codex_id, NODE_TYPE_CODEX, codex)
        self.add_edge(codex_id, node_id, EDGE_CONTAINS)

        return node_id

    def register_session(self, session_id: str, metadata: Optional[Dict] = None) -> str:
        """Register a session in the graph. Returns node ID."""
        node_id = f"session:{session_id[:16]}"
        self.upsert_node(
            node_id,
            NODE_TYPE_SESSION,
            f"Session {session_id[:8]}",
            codex="Codex-Forge",
            metadata=metadata or {},
        )
        return node_id

    def register_entity(self, name: str, codex: str = "") -> str:
        """Register an entity (concept, person, topic). Returns node ID."""
        slug = name.lower().replace(" ", "-").replace("'", "")[:60]
        node_id = f"entity:{slug}"
        self.upsert_node(
            node_id,
            NODE_TYPE_ENTITY,
            name,
            codex=codex,
        )
        return node_id

    def link_file_to_entity(self, file_path: str, entity_name: str) -> None:
        """Link a file to an entity with a 'mentions' edge."""
        file_id = f"file:{file_path}"
        slug = entity_name.lower().replace(" ", "-").replace("'", "")[:60]
        entity_id = f"entity:{slug}"
        self.add_edge(file_id, entity_id, EDGE_MENTIONED_IN)

    def link_session_to_file(self, session_id: str, file_path: str) -> None:
        """Link a session to a file it references."""
        session_node = f"session:{session_id[:16]}"
        file_node = f"file:{file_path}"
        self.add_edge(session_node, file_node, EDGE_REFERENCES)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return graph statistics."""
        if not self._conn:
            raise RuntimeError("GraphClient not connected")

        node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edge_count = self._conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]

        type_counts = {
            row["type"]: row["cnt"]
            for row in self._conn.execute(
                "SELECT type, COUNT(*) as cnt FROM nodes GROUP BY type ORDER BY cnt DESC"
            ).fetchall()
        }

        edge_type_counts = {
            row["type"]: row["cnt"]
            for row in self._conn.execute(
                "SELECT type, COUNT(*) as cnt FROM edges GROUP BY type ORDER BY cnt DESC"
            ).fetchall()
        }

        codex_counts = {
            row["codex"] or "_none": row["cnt"]
            for row in self._conn.execute(
                "SELECT codex, COUNT(*) as cnt FROM nodes WHERE codex IS NOT NULL AND codex != '' GROUP BY codex ORDER BY cnt DESC"
            ).fetchall()
        }

        return {
            "nodes": node_count,
            "edges": edge_count,
            "by_type": type_counts,
            "by_edge_type": edge_type_counts,
            "by_codex": codex_counts,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        # Parse metadata JSON
        if "metadata" in d and isinstance(d["metadata"], str):
            try:
                d["metadata"] = json.loads(d["metadata"])
            except (json.JSONDecodeError, TypeError):
                pass
        return d
