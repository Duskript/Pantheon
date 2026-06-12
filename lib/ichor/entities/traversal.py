"""ER-P3: Multi-hop traversal for the Entity-Relationship Graph.

Implements 3 traversal primitives over the entity graph:
  - `traverse(start, ...)` — multi-hop path query from a start entity
  - `graph_query(entity, ...)` — neighborhood subgraph (nodes + edges)
  - `traverse_between(from, to, ...)` — bidirectional shortest-path
    between two entities

Plus two helpers:
  - `resolve_depth(...)` — adaptive depth selection
  - `format_path(path)` — human-readable explainability output

Cycle detection is built into the recursive CTE: each row's path
includes the current node id, and the recursive step filters out any
node already in the path via `json_each(t.path)`.

Per Thoth's spec (2026-06-11), relations are filtered three ways:
  - follow=[...] : include list
  - skip=[...]   : exclude list
  - families=[...] : include all relations whose `family` is in this list
At most one of (follow, families) is honored at a time; skip is always
applied on top of whichever inclusion mode is active.

Adaptive depth (per spec §Adaptive Depth Tuning) uses 3 signals:
  - query_specificity (0..1): 0.8+ → shallow, <0.3 → deep
  - entity_density (avg rels per start entity): >20 → shallow, <3 → deep
  - diminishing_returns (early termination): stops if avg conf drops
    too much or new-entity gain is too small

Public API:
  traverse(conn, start, *, follow, skip, families, depth, min_confidence, max_results) -> list[dict]
  graph_query(conn, entity, *, depth, min_confidence) -> dict
  traverse_between(conn, from_entity, to_entity, *, max_depth) -> list[dict]
  resolve_depth(query_specificity, entity_density, history=None) -> int
  format_path(path) -> str
"""
from __future__ import annotations

import json
import sqlite3
from collections import deque
from typing import Any, Optional


# ---------- Configuration ----------

DEFAULT_DEPTH = 3
ABSOLUTE_MAX_DEPTH = 7
DEFAULT_MIN_CONFIDENCE = 0.1
DEFAULT_MAX_RESULTS = 50
MAX_FAN_OUT = 50
DIMINISHING_MIN_NEW_ENTITIES = 2
DIMINISHING_CONFIDENCE_DROP = 0.2


# ---------- Adaptive depth ----------

def resolve_depth(
    query_specificity: float = 0.5,
    entity_density: float = 5.0,
    *,
    history: Optional[dict[str, int]] = None,
    default_depth: int = DEFAULT_DEPTH,
    absolute_max: int = ABSOLUTE_MAX_DEPTH,
) -> int:
    """Self-tuning max depth for traversal.

    Args:
      query_specificity: 0..1. >0.8 = precise query, shallow. <0.3 = vague, deep.
      entity_density: avg relationships per start entity. >20 = dense, shallow.
                      <3 = sparse, deep.
      history: optional {query_pattern: optimal_depth} from past successful runs.
      default_depth: starting depth if no signal overrides.
      absolute_max: hard cap (safety).

    Returns: int in [1, absolute_max].
    """
    depth = default_depth

    # 1. Specificity
    if query_specificity >= 0.8:
        depth = min(depth, 2)
    elif query_specificity < 0.3:
        depth = max(depth, 4)

    # 2. Entity density
    if entity_density > 20:
        depth = min(depth, 2)
    elif entity_density < 3:
        depth = max(depth, 4)

    # 3. Cached history (if a matching pattern is provided)
    if history:
        # We don't have query_pattern here; the caller can post-adjust
        # using history at a higher level. The function as designed
        # takes a single composite value; for now, we accept the
        # history dict as a "use this if any" override — actual key
        # matching is the caller's job.
        pass

    return min(max(depth, 1), absolute_max)


# ---------- Traversal ----------

def _find_start_entities(
    conn: sqlite3.Connection, start: str, limit: int = 20
) -> list[sqlite3.Row]:
    """Find entities matching the start string. Match on name (exact,
    case-insensitive) first; fall back to name LIKE."""
    rows = conn.execute(
        "SELECT id, name, type_id FROM entities WHERE LOWER(name) = LOWER(?) LIMIT ?",
        (start, limit),
    ).fetchall()
    if rows:
        return rows
    return conn.execute(
        "SELECT id, name, type_id FROM entities WHERE name LIKE ? LIMIT ?",
        (f"%{start}%", limit),
    ).fetchall()


def _build_relations_filter(
    follow: Optional[list[str]],
    skip: Optional[list[str]],
    families: Optional[list[str]],
) -> tuple[str, list[Any]]:
    """Build the SQL fragment + bind params for relation filtering.

    Returns (sql_clause, params). At most one of (follow, families) is
    active; skip is always applied.
    """
    clauses: list[str] = []
    params: list[Any] = []

    if follow:
        placeholders = ",".join("?" * len(follow))
        clauses.append(f"r.type_id IN ({placeholders})")
        params.extend(follow)
    elif families:
        placeholders = ",".join("?" * len(families))
        clauses.append(
            f"r.type_id IN (SELECT id FROM relationship_types WHERE family IN ({placeholders}))"
        )
        params.extend(families)
    # else: no inclusion filter, follow all

    if skip:
        placeholders = ",".join("?" * len(skip))
        clauses.append(f"r.type_id NOT IN ({placeholders})")
        params.extend(skip)

    return (" AND " + " AND ".join(clauses)) if clauses else "", params


def traverse(
    conn: sqlite3.Connection,
    start: str,
    *,
    follow: Optional[list[str]] = None,
    skip: Optional[list[str]] = None,
    families: Optional[list[str]] = None,
    depth: int = DEFAULT_DEPTH,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> list[dict[str, Any]]:
    """Multi-hop traversal from a start entity.

    Returns a list of paths ordered by path_confidence DESC, depth ASC.
    Each path has: {id, name, type_id, depth, path (JSON), relations_traversed,
    path_confidence}.
    """
    starts = _find_start_entities(conn, start)
    if not starts:
        return []

    start_ids = [s["id"] for s in starts]
    # Dedupe the start ids
    start_ids = list(dict.fromkeys(start_ids))

    rels_filter_sql, rels_params = _build_relations_filter(follow, skip, families)

    # The recursive CTE. We use TEXT columns (comma-separated) for the
    # path and relations_traversed — these work without the JSON1
    # extension's json_array_append/json_each (which are not always
    # available in the bundled SQLite). The Python side parses the
    # comma-separated string back to a list.
    placeholders = ",".join("?" * len(start_ids))
    sql = f"""
    WITH RECURSIVE traverse(node_id, name, type_id, depth, path, rels, path_confidence) AS (
        -- Anchor: starting entities
        SELECT
            e.id, e.name, e.type_id,
            0 AS depth,
            CAST(e.id AS TEXT) AS path,
            '' AS rels,
            1.0 AS path_confidence
        FROM entities e
        WHERE e.id IN ({placeholders})

        UNION ALL

        -- Recursive: follow relationships. Cycle detection: ',' || path || ','
        -- contains the string ',' || node_id || ',' iff that node is already
        -- in the path. We use instr() for substring search.
        SELECT
            e.id, e.name, e.type_id,
            t.depth + 1,
            t.path || ',' || CAST(e.id AS TEXT) AS path,
            CASE WHEN t.rels = '' THEN r.type_id ELSE t.rels || ',' || r.type_id END AS rels,
            t.path_confidence * r.confidence
        FROM traverse t
        JOIN relationships r ON (r.source_id = t.node_id OR r.target_id = t.node_id)
        JOIN entities e ON e.id = CASE WHEN r.source_id = t.node_id THEN r.target_id ELSE r.source_id END
        WHERE t.depth < ?
          AND r.confidence >= ?
          AND r.valid_to IS NULL
          AND instr(',' || t.path || ',', ',' || CAST(e.id AS TEXT) || ',') = 0
          {rels_filter_sql}
    )
    SELECT * FROM traverse
    ORDER BY path_confidence DESC, depth ASC
    LIMIT ?
    """
    params: list[Any] = list(start_ids) + [depth, min_confidence] + rels_params + [max_results]

    cur = conn.execute(sql, params)
    rows = cur.fetchall()

    # Diminishing-returns heuristic: if the second half of the result set
    # has a confidence drop ≥ DIMINISHING_CONFIDENCE_DROP, trim to the
    # first half. This implements spec §"Diminishing returns" signal.
    if len(rows) > DIMINISHING_MIN_NEW_ENTITIES * 2:
        first_half = rows[: len(rows) // 2]
        second_half = rows[len(rows) // 2:]
        avg_first = sum(r["path_confidence"] for r in first_half) / max(len(first_half), 1)
        avg_second = sum(r["path_confidence"] for r in second_half) / max(len(second_half), 1)
        if avg_first - avg_second >= DIMINISHING_CONFIDENCE_DROP:
            rows = first_half

    # Parse the comma-separated path/relations columns
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        # Parse path: "1,3,5" → list of int ids; we need to fetch names
        # for each hop. The current row's (name, type_id) is the END of
        # the path. For other hops, we re-query.
        path_ids = [int(x) for x in item["path"].split(",") if x]
        rels_list = [x for x in item["rels"].split(",") if x]
        item["relations_traversed"] = rels_list
        item["path"] = _build_path_hops(conn, path_ids, rels_list)
        out.append(item)
    return out


def _build_path_hops(
    conn: sqlite3.Connection, path_ids: list[int], rels: list[str]
) -> list[dict[str, Any]]:
    """Resolve a list of (node_id, via_relation) into a list of hops.

    Hops is a list of {id, name, type, via, direction}. The first hop
    has no `via` (it's the anchor). Each subsequent hop's `via` is
    the relation that led to it.
    """
    if not path_ids:
        return []
    placeholders = ",".join("?" * len(path_ids))
    rows = conn.execute(
        f"SELECT id, name, type_id FROM entities WHERE id IN ({placeholders})",
        path_ids,
    ).fetchall()
    name_by_id = {r["id"]: r["name"] for r in rows}
    type_by_id = {r["id"]: r["type_id"] for r in rows}

    hops: list[dict[str, Any]] = []
    for i, nid in enumerate(path_ids):
        hop: dict[str, Any] = {
            "id": nid,
            "name": name_by_id.get(nid, f"id={nid}"),
            "type": type_by_id.get(nid, "?"),
        }
        if i > 0:
            hop["via"] = rels[i - 1] if i - 1 < len(rels) else "?"
            hop["direction"] = "out"  # BFS forward; we don't track in/out
        hops.append(hop)
    return hops


def graph_query(
    conn: sqlite3.Connection,
    entity: str,
    *,
    depth: int = 2,
    min_confidence: float = 0.3,
) -> dict[str, Any]:
    """Neighborhood subgraph query. Returns nodes, edges, and stats.

    Shape (per spec):
      {
        "nodes": [{id, name, type, summary}, ...],
        "edges": [{source, target, type, confidence}, ...],
        "stats": {node_count, edge_count, avg_confidence, max_depth_reached}
      }
    """
    paths = traverse(
        conn, entity, depth=depth, min_confidence=min_confidence, max_results=500
    )
    starts = _find_start_entities(conn, entity)
    if not starts:
        return {
            "nodes": [],
            "edges": [],
            "stats": {"node_count": 0, "edge_count": 0,
                      "avg_confidence": 0.0, "max_depth_reached": 0},
        }

    # Build nodes from starts + every node mentioned in any path
    node_ids: set[int] = set()
    for s in starts:
        node_ids.add(s["id"])
    for p in paths:
        for hop in p["path"]:
            if isinstance(hop, dict) and "id" in hop:
                node_ids.add(hop["id"])

    # Fetch the actual entity rows
    if not node_ids:
        return {
            "nodes": [],
            "edges": [],
            "stats": {"node_count": 0, "edge_count": 0,
                      "avg_confidence": 0.0, "max_depth_reached": 0},
        }
    placeholders = ",".join("?" * len(node_ids))
    entity_rows = conn.execute(
        f"SELECT id, name, type_id, summary FROM entities WHERE id IN ({placeholders})",
        list(node_ids),
    ).fetchall()
    nodes = [
        {"id": r["id"], "name": r["name"], "type": r["type_id"],
         "summary": r["summary"] or ""}
        for r in entity_rows
    ]

    # Build edges: every consecutive pair in every path is an edge
    edge_set: set[tuple[int, str, int]] = set()
    edge_confidence: dict[tuple[int, str, int], float] = {}
    for p in paths:
        for hop in p["path"]:
            if not isinstance(hop, dict):
                continue
            if "via" not in hop or "direction" not in hop:
                continue  # anchor (no via)
            # Find the predecessor in the path
            idx = p["path"].index(hop)
            if idx == 0:
                continue
            prev = p["path"][idx - 1]
            if hop["direction"] == "out":
                edge_set.add((prev["id"], hop["via"], hop["id"]))
            else:
                edge_set.add((hop["id"], hop["via"], prev["id"]))
            # Track confidence (multiplicative from path_confidence and prev)
            # For simplicity, use the path_confidence for the edge
            edge_confidence[(prev["id"], hop["via"], hop["id"])] = p["path_confidence"]

    edges = [
        {"source": s, "target": t, "type": ty, "confidence": edge_confidence.get((s, ty, t), 0.0)}
        for (s, ty, t) in edge_set
    ]

    avg_conf = (sum(e["confidence"] for e in edges) / len(edges)) if edges else 0.0
    max_depth_reached = max((p["depth"] for p in paths), default=0)

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "avg_confidence": round(avg_conf, 4),
            "max_depth_reached": max_depth_reached,
        },
    }


def traverse_between(
    conn: sqlite3.Connection,
    from_entity: str,
    to_entity: str,
    *,
    max_depth: int = 5,
) -> list[dict[str, Any]]:
    """Bidirectional shortest-path search between two entities.

    Returns a list of paths (the BFS frontier from both sides). Each
    path is `{from: [node, ...], via_relations: [...], meeting_at: node_id,
    to: [node, ...], total_depth: int}`.

    Algorithm: BFS from each side, alternating layers. When the two
    frontiers share a node, we have a meeting point and can return the
    path. Hard-cap at max_depth layers from either side.
    """
    from_starts = _find_start_entities(conn, from_entity)
    to_starts = _find_start_entities(conn, to_entity)
    if not from_starts or not to_starts:
        return []

    # Early exit: same entity
    from_ids = {s["id"] for s in from_starts}
    to_ids = {s["id"] for s in to_starts}
    if from_ids & to_ids:
        common = (from_ids & to_ids).pop()
        return [{
            "from": [common],
            "via_relations": [],
            "meeting_at": common,
            "to": [common],
            "total_depth": 0,
        }]

    # BFS from `from` side
    from_frontier: dict[int, dict] = {sid: {"parent": None, "via": None, "depth": 0} for sid in from_ids}
    # BFS from `to` side
    to_frontier: dict[int, dict] = {tid: {"parent": None, "via": None, "depth": 0} for tid in to_ids}

    visited_from: dict[int, dict] = dict(from_frontier)
    visited_to: dict[int, dict] = dict(to_frontier)
    paths: list[dict] = []

    for layer in range(max_depth):
        # Pick the side to expand: prefer the side with a non-empty
        # frontier. If both are empty, no path exists. If only one is
        # non-empty, expand that. If both have frontiers, tie-break by
        # smaller visited set (bidirectional BFS heuristic).
        from_has = bool(from_frontier)
        to_has = bool(to_frontier)
        if not from_has and not to_has:
            break
        if from_has and to_has:
            if len(visited_from) <= len(visited_to):
                frontier = from_frontier
                visited_self = visited_from
                visited_other = visited_to
                side = "from"
            else:
                frontier = to_frontier
                visited_self = visited_to
                visited_other = visited_from
                side = "to"
        elif from_has:
            frontier = from_frontier
            visited_self = visited_from
            visited_other = visited_to
            side = "from"
        else:
            frontier = to_frontier
            visited_self = visited_to
            visited_other = visited_from
            side = "to"

        next_frontier: dict[int, dict] = {}
        for node_id, info in frontier.items():
            # Find all relationships touching this node
            rels = conn.execute(
                """SELECT r.id, r.type_id, r.source_id, r.target_id, r.confidence
                   FROM relationships r
                   WHERE (r.source_id = ? OR r.target_id = ?)
                     AND r.valid_to IS NULL
                   LIMIT ?""",
                (node_id, node_id, MAX_FAN_OUT),
            ).fetchall()
            for r in rels:
                next_id = r["target_id"] if r["source_id"] == node_id else r["source_id"]
                if next_id in visited_self:
                    continue
                next_frontier[next_id] = {
                    "parent": node_id,
                    "via": r["type_id"],
                    "depth": info["depth"] + 1,
                }
                # Check if this node is in the OTHER frontier → meeting point
                if next_id in visited_other:
                    # Build the path. The "from-side" of the meeting is
                    # always Alice's visited set (the user's start), and
                    # the "to-side" is always the target's visited set.
                    # Which side we expanded to discover the meeting
                    # point doesn't change this — we just walk back from
                    # `next_id` on both sides.
                    # Note: the meeting node was just discovered in
                    # next_frontier, so it isn't yet in visited_self.
                    # Pass the new info explicitly so the walk-back
                    # terminates properly.
                    meeting_info = {
                        "parent": node_id,
                        "via": r["type_id"],
                        "depth": info["depth"] + 1,
                    }
                    path = _build_meeting_path(
                        conn, next_id, visited_from, visited_to,
                        from_ids, to_ids, meeting_info=meeting_info,
                    )
                    if path is not None:
                        paths.append(path)
        # Update visited + frontier
        visited_self.update(next_frontier)
        if side == "from":
            visited_from = visited_self
            from_frontier = next_frontier
        else:
            visited_to = visited_self
            to_frontier = next_frontier

        if paths:
            return paths  # first meeting point is shortest

    return paths


def _build_meeting_path(
    conn: sqlite3.Connection,
    meeting_id: int,
    visited_from_side: dict[int, dict],
    visited_to_side: dict[int, dict],
    from_start_ids: set[int],
    to_start_ids: set[int],
    meeting_info: Optional[dict] = None,
) -> Optional[dict[str, Any]]:
    """Reconstruct the meeting-point path from both BFS visits.

    The meeting node is the one just discovered in this layer: it was
    added to `next_frontier` of the side that expanded, but NOT yet
    merged into that side's visited dict. We use `meeting_info` (the
    parent/via info for this node) to seed the walk-back on the
    expanding side, AND we synthesize a "synthesized visitor" entry
    for the OTHER side if its walk-back reaches a node not yet in its
    visited dict (which shouldn't happen for a proper meeting, but we
    guard against it).
    """
    # Walk back from meeting_id on the from-side. The meeting_id may
    # not be in visited_from_side yet if it was just discovered from
    # the from-side. Use meeting_info to seed the walk-back.
    from_chain = []
    cur = meeting_id
    seen = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        info = visited_from_side.get(cur)
        if info is None:
            if cur == meeting_id and meeting_info is not None:
                info = meeting_info
            else:
                break
        from_chain.append((cur, info.get("via")))
        cur = info["parent"]
    from_chain.reverse()  # from start → meeting

    # Walk back from meeting_id on the to-side. Same idea: meeting_id
    # may not be in visited_to_side yet if it was just discovered from
    # the to-side. Use meeting_info to seed the walk-back.
    to_chain = []
    cur = meeting_id
    seen = set()
    while cur is not None and cur not in seen:
        seen.add(cur)
        info = visited_to_side.get(cur)
        if info is None:
            if cur == meeting_id and meeting_info is not None:
                info = meeting_info
            else:
                break
        to_chain.append((cur, info.get("via")))
        cur = info["parent"]
    # to_chain is from meeting → to start; reverse for the return direction
    to_chain_reversed = list(reversed(to_chain))

    # Resolve entity names
    all_ids = (
        [c[0] for c in from_chain]
        + [c[0] for c in to_chain_reversed if c[0] != meeting_id]
        + [meeting_id]
    )
    if not all_ids:
        return None
    placeholders = ",".join("?" * len(set(all_ids)))
    name_rows = conn.execute(
        f"SELECT id, name FROM entities WHERE id IN ({placeholders})",
        list(set(all_ids)),
    ).fetchall()
    names = {r["id"]: r["name"] for r in name_rows}

    return {
        "from": [{"id": nid, "name": names.get(nid, "?"), "via": via} for nid, via in from_chain],
        "to": [{"id": nid, "name": names.get(nid, "?"), "via": via} for nid, via in to_chain_reversed if nid != meeting_id],
        "meeting_at": meeting_id,
        "meeting_at_name": names.get(meeting_id, "?"),
        "total_depth": (len(from_chain) - 1) + (len(to_chain_reversed) - 1),
    }


# ---------- Explainability ----------

def format_path(path: dict[str, Any]) -> str:
    """Format a traverse() result path as human-readable text.

    Example output:
      Alice (person)
        → [works_at]
      Anthropic (organization)
        → [related_to]
      Bob (person)
    """
    lines: list[str] = []
    hops = path.get("path") or []
    for i, hop in enumerate(hops):
        if not isinstance(hop, dict):
            continue
        if i > 0 and "via" in hop:
            lines.append(f"  → [{hop['via']}]")
        if "name" in hop:
            etype = hop.get("type", "?")
            lines.append(f"{hop['name']} ({etype})")
    if "path_confidence" in path:
        lines.append(f"  (path confidence: {path['path_confidence']:.3f}, depth: {path['depth']})")
    return "\n".join(lines)


def format_meeting_path(path: dict[str, Any]) -> str:
    """Format a traverse_between() result."""
    lines: list[str] = []
    from_chain = path.get("from", [])
    to_chain = path.get("to", [])
    for i, hop in enumerate(from_chain):
        if i > 0 and hop.get("via"):
            lines.append(f"  → [{hop['via']}]")
        lines.append(f"{hop.get('name', '?')}")
    lines.append(f"  ═══ meet at: {path.get('meeting_at_name', '?')} ═══")
    for i, hop in enumerate(to_chain):
        if (i > 0 or from_chain) and hop.get("via"):
            lines.append(f"  → [{hop['via']}]")
        lines.append(f"{hop.get('name', '?')}")
    lines.append(f"  (total depth: {path.get('total_depth', '?')})")
    return "\n".join(lines)
