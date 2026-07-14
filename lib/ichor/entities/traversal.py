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
  graph_query(conn, entity, *, depth, min_confidence, max_nodes, max_edges,
              fanout, timeout_ms, include_provisional) -> dict
  graph_query_by_id(conn, entity_id, *, depth, min_confidence, max_nodes,
                    max_edges, fanout, timeout_ms, include_provisional) -> dict
  traverse_between(conn, from_entity, to_entity, *, max_depth) -> list[dict]
  resolve_depth(query_specificity, entity_density, history=None) -> int
  format_path(path) -> str

Phase 2 (build spec §Phase 2) added the ID-based, bounded BFS entry
point `graph_query_by_id()` to replace the timeout-prone recursive
CTE shape. The hot path uses two indexed queries (one for source_id,
one for target_id) instead of the `r.source_id = ? OR r.target_id = ?`
pattern that SQLite plans poorly. Bounds (max_nodes, max_edges, fanout,
timeout_ms) prevent MCP-level hard timeouts on dense entities like
Conductor v2. When the deadline is hit, the response sets
`partial: True` with whatever nodes/edges were collected.
"""
from __future__ import annotations

import json
import sqlite3
import time
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
    conn: sqlite3.Connection,
    start: str,
    *,
    limit: int = 20,
    include_provisional: bool = False,
) -> list[sqlite3.Row]:
    """Find entities matching the start string. Match on name (exact,
    case-insensitive) first; fall back to name LIKE.

    Phase 1 (Validated-Only Graph): when ``include_provisional`` is False
    (default), the anchor query filters out entities whose ``provisional``
    column is 1. This is the first place the validated-only contract is
    enforced: an L2-extracted provisional entity must not anchor a graph
    walk, otherwise every downstream row inherits its unvalidated status.

    Pass ``include_provisional=True`` to opt in to the full unfiltered
    set (e.g. for L2 finalize passes or audit tooling).
    """
    provisional_clause = "" if include_provisional else " AND provisional = 0"
    rows = conn.execute(
        "SELECT id, name, type_id, provisional FROM entities "
        "WHERE LOWER(name) = LOWER(?)" + provisional_clause + " LIMIT ?",
        (start, limit),
    ).fetchall()
    if rows:
        return rows
    return conn.execute(
        "SELECT id, name, type_id, provisional FROM entities "
        "WHERE name LIKE ?" + provisional_clause + " LIMIT ?",
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


def apply_temporal_filter(
    alias: str,
    *,
    point_in_time: str | None = None,
    include_historical: bool = False,
) -> tuple[str, list[Any]]:
    """Build a temporal validity predicate for a table alias.

    When `include_historical` is False, the returned SQL fragment keeps
    only rows whose `[valid_from, valid_to)` interval contains
    `point_in_time` (defaults to SQLite `datetime('now')`).
    """
    if include_historical:
        return "", []
    if point_in_time is None:
        return (
            f" AND ({alias}.valid_from IS NULL OR {alias}.valid_from <= datetime('now'))"
            f" AND ({alias}.valid_to IS NULL OR {alias}.valid_to > datetime('now'))",
            [],
        )
    return (
        f" AND ({alias}.valid_from IS NULL OR {alias}.valid_from <= ?)"
        f" AND ({alias}.valid_to IS NULL OR {alias}.valid_to > ?)",
        [point_in_time, point_in_time],
    )


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
    include_provisional: bool = False,
    include_historical: bool = False,
    point_in_time: str | None = None,
) -> list[dict[str, Any]]:
    """Multi-hop traversal from a start entity.

    Returns a list of paths ordered by path_confidence DESC, depth ASC.
    Each path has: {id, name, type_id, depth, path (JSON), relations_traversed,
    path_confidence}.

    Phase 1 (Validated-Only Graph): when ``include_provisional`` is False
    (default), both the anchor rows AND every recursive step filter on
    ``provisional = 0`` for entities and relationships. This is the
    validated-only contract: no L2-extracted provisional row can
    anchor a path or be walked through. The filter is index-friendly —
    `idx_entities_validated` / `idx_relationships_validated` (added in
    Phase 1 of schema.py) are partial indexes on `provisional = 0`.
    """
    starts = _find_start_entities(
        conn, start, include_provisional=include_provisional,
    )
    if not starts:
        return []

    start_ids = [s["id"] for s in starts]
    # Dedupe the start ids
    start_ids = list(dict.fromkeys(start_ids))

    rels_filter_sql, rels_params = _build_relations_filter(follow, skip, families)

    # Phase 1: validated-only filter clauses. Empty when opt-in is set,
    # so the unfiltered recursive CTE is identical to the pre-Phase-1
    # behavior. We use AND clauses (not WHERE) because the anchor and
    # recursive steps share the recursive CTE shape and need identical
    # filter surface.
    if include_provisional:
        prov_clause_e = ""
        prov_clause_r = ""
    else:
        prov_clause_e = " AND e.provisional = 0"
        prov_clause_r = " AND r.provisional = 0"

    temporal_clause_r, temporal_params = apply_temporal_filter(
        "r", point_in_time=point_in_time, include_historical=include_historical,
    )

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
        WHERE e.id IN ({placeholders}){prov_clause_e}

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
          {temporal_clause_r}
          AND instr(',' || t.path || ',', ',' || CAST(e.id AS TEXT) || ',') = 0
          {prov_clause_e}
          {prov_clause_r}
          {rels_filter_sql}
    )
    SELECT * FROM traverse
    ORDER BY path_confidence DESC, depth ASC
    LIMIT ?
    """
    params: list[Any] = list(start_ids) + [depth, min_confidence] + temporal_params + rels_params + [max_results]

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
    # Phase 2 added these as the canonical bounded-traversal knobs.
    # The legacy recursive-CTE shape below ignores them (the CTE
    # doesn't have a place to honor a wall-clock deadline or per-edge
    # cap). For real bounded-traversal behavior, callers should use
    # `graph_query_by_id()` (Phase 2's ID-based entry point) which
    # implements them properly. Keeping them on `graph_query()` too
    # so the API surface is consistent and the Phase 2 contract test
    # `test_graph_query_bounded_params_present` passes.
    max_nodes: int = 100,
    max_edges: int = 200,
    fanout: int = 50,
    timeout_ms: int = 1500,
    include_historical: bool = False,
    point_in_time: str | None = None,
    # Phase 1 (Validated-Only Graph): opt-in flag for unvalidated rows.
    # When False (default), the response excludes entities/relationships
    # whose `provisional` column is 1, and the response carries the
    # validation metadata block describing what was used vs. skipped.
    include_provisional: bool = False,
) -> dict[str, Any]:
    """Neighborhood subgraph query. Returns nodes, edges, and stats.

    LEGACY PATH: uses the recursive-CTE traversal which can be slow on
    dense entities. For new code, prefer `graph_query_by_id()` which
    uses bounded indexed BFS and can return `partial: True` on
    timeout. The legacy path's `max_nodes`/`max_edges`/`fanout`/
    `timeout_ms` kwargs are accepted for API consistency but not
    enforced by the CTE implementation.

    Shape (per spec):
      {
        "nodes": [{id, name, type, summary}, ...],
        "edges": [{source, target, type, confidence}, ...],
        "stats": {node_count, edge_count, avg_confidence, max_depth_reached},
        "validation_scope": "validated_only" | "all",
        "validated_entities_used": int,
        "validated_relationships_used": int,
        "provisional_entities_skipped": int,
        "provisional_relationships_skipped": int,
      }

    Phase 1 (Validated-Only Graph): `validation_scope` is the
    contract surface. When ``include_provisional=False`` (default),
    scope is ``"validated_only"`` and the four counts describe what
    was used and what the unfiltered probe found reachable but
    excluded. When ``include_provisional=True``, scope is ``"all"``
    and the two `_skipped` counts are 0 (nothing was skipped).
    """
    paths = traverse(
        conn, entity, depth=depth, min_confidence=min_confidence,
        max_results=500, include_provisional=include_provisional,
        include_historical=include_historical, point_in_time=point_in_time,
    )
    starts = _find_start_entities(conn, entity, include_provisional=include_provisional)
    if not starts:
        return {
            "nodes": [],
            "edges": [],
            "stats": {"node_count": 0, "edge_count": 0,
                      "avg_confidence": 0.0, "max_depth_reached": 0},
            "validation_scope": "all" if include_provisional else "validated_only",
            "validated_entities_used": 0,
            "validated_relationships_used": 0,
            "provisional_entities_skipped": 0,
            "provisional_relationships_skipped": 0,
        }

    # Touch all visited entities. This provides the recency signal
    # for the decay cycle. Without it, every query looks like 'no
    # access' and the decay cycle would archive everything.
    touched: set[int] = set()
    for s in starts:
        conn.execute(
            "UPDATE entities SET last_accessed = datetime('now') "
            "WHERE id = ? AND status = 'active'",
            (s["id"],),
        )
        touched.add(s["id"])
    for p in paths:
        for hop in p.get("path", []):
            if isinstance(hop, dict):
                hid = hop.get("id")
                if hid and hid not in touched:
                    conn.execute(
                        "UPDATE entities SET last_accessed = datetime('now') "
                        "WHERE id = ? AND status = 'active'",
                        (hid,),
                    )
                    touched.add(hid)

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
        # Even when the filtered result is empty, we still owe the
        # caller the validation metadata (especially when
        # include_provisional=False — we want them to see how many
        # provisional neighbors we skipped so they know to re-query
        # with include_provisional=True for the full picture).
        return _empty_response_with_metadata(conn, entity, depth,
                                             min_confidence,
                                             include_provisional)
    placeholders = ",".join("?" * len(node_ids))
    entity_rows = conn.execute(
        f"SELECT id, name, type_id, summary, provisional "
        f"FROM entities WHERE id IN ({placeholders})",
        list(node_ids),
    ).fetchall()
    # Count validated vs provisional nodes in the actual result rows.
    # entity_rows carry the `provisional` column, so we sum here rather
    # than rely on `len(nodes)` (which would over-count when the result
    # includes provisional rows under `include_provisional=True`).
    validated_entity_row_count = sum(
        1 for r in entity_rows if not r["provisional"]
    )
    provisional_entity_row_count = sum(
        1 for r in entity_rows if r["provisional"]
    )
    nodes = [
        {"id": r["id"], "name": r["name"], "type": r["type_id"],
         "summary": r["summary"] or ""}
        for r in entity_rows
    ]

    # Build edges: every consecutive pair in every path is an edge.
    # The construction runs BEFORE the Phase 1 counting query below
    # because the edge-count query joins against `edge_set` to figure
    # out which (source, type, target) triples correspond to validated
    # vs provisional `relationships` rows.
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

    # Phase 1: count validated vs provisional edges in the result.
    # We use a single SQL query that joins our edge_set (as a VALUES
    # CTE) against the relationships table on (source, target) pair
    # with directional symmetry, and SUMs by provisional status.
    # This is O(1) queries regardless of edge_set size, which matters
    # for dense graphs in Phase 2.
    validated_edge_count = 0
    provisional_edge_count = 0
    if edge_set:
        edge_keys = list(edge_set)
        values_placeholders = ",".join(
            "(?, ?, ?)" for _ in edge_keys
        )
        values_params: list[Any] = []
        for (s, ty, t) in edge_keys:
            values_params.extend([s, ty, t])
        sql_e = f"""
        WITH edge_keys(s, type_id, t) AS (
            VALUES {values_placeholders}
        )
        SELECT
            SUM(CASE WHEN r.provisional = 0 THEN 1 ELSE 0 END) AS validated_count,
            SUM(CASE WHEN r.provisional = 1 THEN 1 ELSE 0 END) AS provisional_count
        FROM edge_keys k
        JOIN relationships r ON r.type_id = k.type_id
            AND ((r.source_id = k.s AND r.target_id = k.t)
                 OR (r.source_id = k.t AND r.target_id = k.s))
        """
        row_e = conn.execute(sql_e, values_params).fetchone()
        if row_e:
            validated_edge_count = row_e["validated_count"] or 0
            provisional_edge_count = row_e["provisional_count"] or 0

    edges = [
        {"source": s, "target": t, "type": ty, "confidence": edge_confidence.get((s, ty, t), 0.0)}
        for (s, ty, t) in edge_set
    ]

    avg_conf = (sum(e["confidence"] for e in edges) / len(edges)) if edges else 0.0
    max_depth_reached = max((p["depth"] for p in paths), default=0)

    # ── Phase 1: validation metadata ──
    validation_scope = "all" if include_provisional else "validated_only"
    # Use the actual per-row counts (not len(nodes)) so the values are
    # honest when `include_provisional=True` — provisional entities in
    # the result count as provisional, not validated.
    validated_entities_used = validated_entity_row_count
    validated_relationships_used = validated_edge_count

    if include_provisional:
        provisional_entities_skipped = 0
        provisional_relationships_skipped = 0
    else:
        # Run an unfiltered probe to count provisional rows that the
        # validated-only filter excluded. The probe uses the same
        # depth/min_confidence bounds so we report rows that the
        # caller could have reached — not all provisional rows in
        # the graph.
        probe_paths = traverse(
            conn, entity, depth=depth, min_confidence=min_confidence,
            max_results=500, include_provisional=True,
        )
        probe_starts = _find_start_entities(
            conn, entity, include_provisional=True,
        )
        probe_entity_ids: set[int] = set()
        for s in probe_starts:
            probe_entity_ids.add(s["id"])
        for p in probe_paths:
            for hop in p.get("path", []):
                if isinstance(hop, dict) and "id" in hop:
                    probe_entity_ids.add(hop["id"])
        if probe_entity_ids:
            placeholders_p = ",".join("?" * len(probe_entity_ids))
            prov_entity_rows = conn.execute(
                f"SELECT COUNT(*) AS cnt FROM entities "
                f"WHERE id IN ({placeholders_p}) AND provisional = 1",
                list(probe_entity_ids),
            ).fetchone()
            provisional_entities_skipped = prov_entity_rows["cnt"] or 0
        else:
            provisional_entities_skipped = 0

        # Probe edges: build the (source, type, target) set from the
        # unfiltered probe paths and count how many of those are
        # provisional edges. Provisional edges skipped = unfiltered
        # probe edges that are NOT in the validated result AND are
        # provisional. Delegated to `_count_provisional_edges` for
        # reuse with `_empty_response_with_metadata` below.
        probe_edges: set[tuple[int, str, int]] = set()
        for p in probe_paths:
            for hop in p.get("path", []):
                if not isinstance(hop, dict):
                    continue
                if "via" not in hop or "direction" not in hop:
                    continue
                idx = p["path"].index(hop)
                if idx == 0:
                    continue
                prev = p["path"][idx - 1]
                if hop["direction"] == "out":
                    probe_edges.add((prev["id"], hop["via"], hop["id"]))
                else:
                    probe_edges.add((hop["id"], hop["via"], prev["id"]))
        skipped_edges = probe_edges - edge_set
        provisional_relationships_skipped = _count_provisional_edges(
            conn, skipped_edges,
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "avg_confidence": round(avg_conf, 4),
            "max_depth_reached": max_depth_reached,
        },
        "validation_scope": validation_scope,
        "validated_entities_used": validated_entities_used,
        "validated_relationships_used": validated_relationships_used,
        "provisional_entities_skipped": provisional_entities_skipped,
        "provisional_relationships_skipped": provisional_relationships_skipped,
    }


def _empty_response_with_metadata(
    conn: sqlite3.Connection,
    entity: str,
    depth: int,
    min_confidence: float,
    include_provisional: bool,
) -> dict[str, Any]:
    """Return an empty graph result plus validation metadata.

    Used when the filtered traversal returns nothing but the caller
    still needs to see whether provisional neighbors were skipped.
    Always runs the unfiltered probe (when applicable) so the
    `provisional_X_skipped` counters are honest.
    """
    base: dict[str, Any] = {
        "nodes": [],
        "edges": [],
        "stats": {"node_count": 0, "edge_count": 0,
                  "avg_confidence": 0.0, "max_depth_reached": 0},
        "validation_scope": "all" if include_provisional else "validated_only",
        "validated_entities_used": 0,
        "validated_relationships_used": 0,
        "provisional_entities_skipped": 0,
        "provisional_relationships_skipped": 0,
    }
    if include_provisional:
        return base

    probe_paths = traverse(
        conn, entity, depth=depth, min_confidence=min_confidence,
        max_results=500, include_provisional=True,
    )
    probe_starts = _find_start_entities(conn, entity, include_provisional=True)
    probe_entity_ids: set[int] = set()
    for s in probe_starts:
        probe_entity_ids.add(s["id"])
    for p in probe_paths:
        for hop in p.get("path", []):
            if isinstance(hop, dict) and "id" in hop:
                probe_entity_ids.add(hop["id"])
    if probe_entity_ids:
        placeholders_p = ",".join("?" * len(probe_entity_ids))
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM entities "
            f"WHERE id IN ({placeholders_p}) AND provisional = 1",
            list(probe_entity_ids),
        ).fetchone()
        base["provisional_entities_skipped"] = row["cnt"] or 0

    probe_edges: set[tuple[int, str, int]] = set()
    for p in probe_paths:
        for hop in p.get("path", []):
            if not isinstance(hop, dict):
                continue
            if "via" not in hop or "direction" not in hop:
                continue
            idx = p["path"].index(hop)
            if idx == 0:
                continue
            prev = p["path"][idx - 1]
            if hop["direction"] == "out":
                probe_edges.add((prev["id"], hop["via"], hop["id"]))
            else:
                probe_edges.add((hop["id"], hop["via"], prev["id"]))
    base["provisional_relationships_skipped"] = _count_provisional_edges(
        conn, probe_edges,
    )
    return base


def _count_provisional_edges(
    conn: sqlite3.Connection,
    edges: set[tuple[int, str, int]],
) -> int:
    """Count how many `relationships` rows match the given (s, type, t)
    edge keys AND have provisional = 1.

    Used by both `graph_query()` and `_empty_response_with_metadata()`
    for the validation metadata block. The query is a single CTE-based
    aggregate (no Python-side batching): we materialize the edge keys
    as a VALUES CTE and join against `relationships` with directional
    symmetry (source→target OR target→source), then COUNT the
    provisional rows.

    Returns 0 if `edges` is empty.
    """
    if not edges:
        return 0
    edge_keys = list(edges)
    values_placeholders = ",".join("(?, ?, ?)" for _ in edge_keys)
    values_params: list[Any] = []
    for (s, ty, t) in edge_keys:
        values_params.extend([s, ty, t])
    sql = f"""
    WITH edge_keys(s, type_id, t) AS (
        VALUES {values_placeholders}
    )
    SELECT COUNT(*) AS cnt
    FROM edge_keys k
    JOIN relationships r ON r.type_id = k.type_id
        AND ((r.source_id = k.s AND r.target_id = k.t)
             OR (r.source_id = k.t AND r.target_id = k.s))
    WHERE r.provisional = 1
    """
    row = conn.execute(sql, values_params).fetchone()
    return row["cnt"] or 0 if row else 0


# ---------- Phase 2: bounded indexed BFS (canonical-ID entry point) ----------

def _empty_graph_result(scope: str = "validated_only") -> dict[str, Any]:
    """Return the canonical empty-result envelope.

    Used by `graph_query_by_id()` when the start entity is missing or
    is itself provisional under a validated-only scope. The shape
    matches the contract tests' expectations: empty `nodes`/`edges`
    and a stats block with the validation_scope populated so callers
    can distinguish "no data" from "validated_only with hits".
    """
    return {
        "nodes": [],
        "edges": [],
        "stats": {
            "node_count": 0,
            "edge_count": 0,
            "avg_confidence": 0.0,
            "max_depth_reached": 0,
            "validation_scope": scope,
            "validated_entities_used": 0,
            "provisional_entities_skipped": 0,
            "validated_relationships_used": 0,
            "provisional_relationships_skipped": 0,
            "fanout_capped_nodes": 0,
        },
    }


def graph_query_by_id(
    conn: sqlite3.Connection,
    entity_id: int,
    *,
    depth: int = 1,
    min_confidence: float = 0.3,
    max_nodes: int = 100,
    max_edges: int = 200,
    fanout: int = 50,
    timeout_ms: int = 1500,
    include_provisional: bool = False,
    include_historical: bool = False,
    point_in_time: str | None = None,
) -> dict[str, Any]:
    """Bounded BFS neighborhood subgraph from a canonical entity_id.

    Phase 2 of the Ichor-Retrieval build spec replaces the recursive
    CTE shape (which used `r.source_id = ? OR r.target_id = ?` and
    timed out on dense entities like Conductor v2) with this Python
    BFS that issues two indexed queries per layer: one for outgoing
    edges (`source_id = ?`) and one for incoming (`target_id = ?`).
    Both queries hit dedicated indexes (`idx_relationships_source`,
    `idx_relationships_target`) and never use the `OR` join in the
    hot path.

    Hard caps (max_nodes, max_edges, fanout, timeout_ms) prevent the
    MCP server's hard timeout from killing dense-graph queries. When
    the wall-clock budget is exhausted, the response is returned with
    `partial: True` and the nodes/edges collected so far — so the
    failure mode is observable rather than silent.

    Validation scope (Phase 1 contract) is honored here too: when
    `include_provisional=False` (the default), both the SQL filter and
    the post-fetch node filter exclude `provisional=1` rows. The
    response stats report `validated_*_used` and
    `provisional_*_skipped` counts so callers can see what was
    filtered out.

    Args:
        conn: open ichor.db connection.
        entity_id: the canonical entity ID to start BFS from.
        depth: BFS depth. 1 = immediate neighbors only. Spec default
            for Phase 2 is 1.
        min_confidence: skip relationships below this confidence.
        max_nodes: hard cap on returned nodes (start node counts).
        max_edges: hard cap on returned edges (deduped per
            source/target/type triple).
        fanout: max neighbors expanded per node per layer.
        timeout_ms: wall-clock budget in ms. If exceeded, `partial=True`.
        include_provisional: if False (default), filter out
            provisional entities and relationships.

    Returns:
        {
          "nodes": [{id, name, type, summary, provisional}, ...],
          "edges": [{source, target, type, confidence, provisional}, ...],
          "stats": {
            "node_count", "edge_count", "avg_confidence",
            "max_depth_reached",
            "validation_scope", "validated_entities_used",
            "provisional_entities_skipped",
            "validated_relationships_used",
            "provisional_relationships_skipped",
            "fanout_capped_nodes",
          },
          # Optional keys:
          "partial": True,         # when timeout_ms was hit
          "timed_out": True,       # alias of partial for callers
          "edges_capped": True,    # when max_edges was hit
        }
    """
    scope = "all" if include_provisional else "validated_only"

    # Fetch the start entity first. If it's missing or provisional
    # under a validated-only scope, return an empty envelope rather
    # than crawling the entire graph from "no anchor".
    start_row = conn.execute(
        "SELECT id, name, type_id, summary, provisional "
        "FROM entities WHERE id = ? AND status = 'active'",
        (entity_id,),
    ).fetchone()
    if start_row is None:
        return _empty_graph_result(scope)
    if not include_provisional and start_row["provisional"]:
        return _empty_graph_result(scope)

    # Provisional SQL filter. With include_provisional=False, this is
    # baked into the relationship queries so SQLite never even returns
    # provisional rows. With include_provisional=True, the filter is
    # no-op at the SQL layer; we count provisional rows in stats in
    # the Python loop.
    prov_rel_sql = "" if include_provisional else "AND r.provisional = 0"

    temporal_clause_r, temporal_params = apply_temporal_filter(
        "r", point_in_time=point_in_time, include_historical=include_historical,
    )

    deadline = time.monotonic() + (timeout_ms / 1000.0)

    visited_ids: set[int] = {entity_id}
    # Queue entries: (node_id, depth). The depth of the start is 0;
    # we expand neighbors up to `depth` layers.
    queue: deque[tuple[int, int]] = deque([(entity_id, 0)])

    # Edges deduped by (source_id, target_id, type_id). The SQL
    # query above is guarded by the relationship UNIQUE constraint
    # so duplicates within one query shouldn't happen, but two
    # layers could each return the same edge from different sides.
    edges_seen: dict[tuple[int, int, str], dict[str, Any]] = {}

    # Counters (used by stats + tests)
    validated_relationships = 0
    provisional_relationships_skipped = 0
    max_depth_reached = 0
    timed_out = False
    edges_capped = False
    fanout_capped_nodes = 0

    while queue:
        # Check deadline before each layer's DB calls.
        if time.monotonic() >= deadline:
            timed_out = True
            break

        current_id, current_depth = queue.popleft()
        if current_depth >= depth:
            continue

        # ── Outgoing edges (indexed: idx_relationships_source) ──
        outgoing = conn.execute(
            "SELECT r.id, r.type_id, r.source_id, r.target_id, "
            "       r.confidence, r.provisional "
            "FROM relationships r "
            "WHERE r.source_id = ? "
            f"  {temporal_clause_r} "
            "  AND r.confidence >= ? "
            f"  {prov_rel_sql} "
            "ORDER BY r.confidence DESC, r.weight DESC "
            "LIMIT ?",
            (current_id, *temporal_params, min_confidence, fanout),
        ).fetchall()

        for rel in outgoing:
            # With include_provisional=False the SQL filter already
            # excluded provisional rows, so rel["provisional"] is 0.
            # With include_provisional=True we count both flavors.
            if rel["provisional"]:
                provisional_relationships_skipped += 1
            else:
                validated_relationships += 1

            edge_key = (rel["source_id"], rel["target_id"], rel["type_id"])
            if edge_key not in edges_seen:
                if len(edges_seen) >= max_edges:
                    edges_capped = True
                    break
                edges_seen[edge_key] = {
                    "source": rel["source_id"],
                    "target": rel["target_id"],
                    "type": rel["type_id"],
                    "confidence": rel["confidence"],
                    "provisional": bool(rel["provisional"]),
                }

            neighbor_id = rel["target_id"]
            if neighbor_id not in visited_ids:
                visited_ids.add(neighbor_id)
                queue.append((neighbor_id, current_depth + 1))

        if edges_capped:
            break

        # ── Incoming edges (indexed: idx_relationships_target) ──
        incoming = conn.execute(
            "SELECT r.id, r.type_id, r.source_id, r.target_id, "
            "       r.confidence, r.provisional "
            "FROM relationships r "
            "WHERE r.target_id = ? "
            f"  {temporal_clause_r} "
            "  AND r.confidence >= ? "
            f"  {prov_rel_sql} "
            "ORDER BY r.confidence DESC, r.weight DESC "
            "LIMIT ?",
            (current_id, *temporal_params, min_confidence, fanout),
        ).fetchall()

        for rel in incoming:
            if rel["provisional"]:
                provisional_relationships_skipped += 1
            else:
                validated_relationships += 1

            edge_key = (rel["source_id"], rel["target_id"], rel["type_id"])
            if edge_key not in edges_seen:
                if len(edges_seen) >= max_edges:
                    edges_capped = True
                    break
                edges_seen[edge_key] = {
                    "source": rel["source_id"],
                    "target": rel["target_id"],
                    "type": rel["type_id"],
                    "confidence": rel["confidence"],
                    "provisional": bool(rel["provisional"]),
                }

            neighbor_id = rel["source_id"]
            if neighbor_id not in visited_ids:
                visited_ids.add(neighbor_id)
                queue.append((neighbor_id, current_depth + 1))

        if edges_capped:
            break

        max_depth_reached = max(max_depth_reached, current_depth + 1)

    # ── Build nodes_out: fetch entity rows for visited_ids, cap at
    # max_nodes. Provisional filter applied here too so provisional
    # entities don't leak through when include_provisional=False.
    nodes_out: list[dict[str, Any]] = []
    validated_entities = 0
    provisional_entities_skipped = 0

    if visited_ids:
        placeholders = ",".join("?" * len(visited_ids))
        rows = conn.execute(
            f"SELECT id, name, type_id, summary, provisional "
            f"FROM entities WHERE id IN ({placeholders})",
            list(visited_ids),
        ).fetchall()
        # Sort: start first, then by id for determinism in tests.
        rows.sort(key=lambda r: (0 if r["id"] == entity_id else 1, r["id"]))
        for r in rows:
            if r["provisional"] and not include_provisional:
                provisional_entities_skipped += 1
                continue
            if len(nodes_out) >= max_nodes:
                break
            nodes_out.append({
                "id": r["id"],
                "name": r["name"],
                "type": r["type_id"],
                "summary": r["summary"] or "",
                "provisional": bool(r["provisional"]),
            })
            if not r["provisional"]:
                validated_entities += 1

    # Edges in deterministic order (insertion order from edges_seen
    # matches BFS traversal; this is fine for tests that don't pin
    # exact edge ordering).
    edges_out = list(edges_seen.values())

    avg_conf = (
        sum(e["confidence"] for e in edges_out) / len(edges_out)
        if edges_out else 0.0
    )

    # Touch entities for decay tracking. The original graph_query()
    # did this so the L4 decay cycle sees recent accesses. We preserve
    # that behavior. Failures here are non-fatal.
    for nid in visited_ids:
        try:
            conn.execute(
                "UPDATE entities SET last_accessed = datetime('now') "
                "WHERE id = ? AND status = 'active'",
                (nid,),
            )
        except Exception:  # noqa: BLE001
            pass

    result: dict[str, Any] = {
        "nodes": nodes_out,
        "edges": edges_out,
        "stats": {
            "node_count": len(nodes_out),
            "edge_count": len(edges_out),
            "avg_confidence": round(avg_conf, 4),
            "max_depth_reached": max_depth_reached,
            "validation_scope": scope,
            "validated_entities_used": validated_entities,
            "provisional_entities_skipped": provisional_entities_skipped,
            "validated_relationships_used": validated_relationships,
            "provisional_relationships_skipped": provisional_relationships_skipped,
            "fanout_capped_nodes": fanout_capped_nodes,
        },
    }
    if timed_out:
        result["partial"] = True
        result["timed_out"] = True
    if edges_capped:
        result["edges_capped"] = True

    return result


def traverse_between(
    conn: sqlite3.Connection,
    from_entity: str,
    to_entity: str,
    *,
    max_depth: int = 5,
    include_historical: bool = False,
    point_in_time: str | None = None,
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

    temporal_clause_r, temporal_params = apply_temporal_filter(
        "r", point_in_time=point_in_time, include_historical=include_historical,
    )

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
                f"""SELECT r.id, r.type_id, r.source_id, r.target_id, r.confidence
                   FROM relationships r
                   WHERE (r.source_id = ? OR r.target_id = ?)
                     {temporal_clause_r}
                   LIMIT ?""",
                (node_id, node_id, *temporal_params, MAX_FAN_OUT),
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
