"""Ichor Hybrid Scorer + Memory Trait Contract.

P4a: ChromaDB removed. Currently fuses 3 backends:
  - FTS5    (keyword search via SQLite)
  - Graph   (entity relationships via graph.db — P4b removes this)
  - Events  (structured events from ichor.db)

P4c will collapse to FTS5 + Events only, sorted by ichor_score.

Legacy 4-backend weights (for reference):
  | FTS5     | 0.20 | Keyword     |
  | ChromaDB | 0.35 | Semantic    |  ← removed P4a
  | Graph    | 0.25 | Relationship|
  | Events   | 0.20 | Structured  |

Memory Trait Contract provides four unified tools:
  - ichor_store(namespace, key, content, category) → stores content
  - ichor_retrieve(query, limit, backends) → fused search across backends
  - ichor_forget(namespace, key) → deletes from all backends
  - ichor_health() → checks all backends

Usage:
    from lib.ichor_hybrid import HybridScorer, MemoryTrait
    scorer = HybridScorer()
    results = scorer.retrieve("SSL cert expiry", limit=10)
    health = MemoryTrait().health_check()
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ichor_hybrid")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HOME = Path.home()
_PANTHEON_LIB = _HOME / "pantheon" / "lib"
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_GRAPH_DB = _HOME / ".hermes" / "pantheon" / "graph.db"

# Retrieval query log — append-only JSONL for forge weight tuning
_RETRIEVAL_LOG = _HOME / ".hermes" / "pantheon" / "retrieval-log.jsonl"

# Weights for fused scoring
#
# History: pre-P4a (ChromaDB-backed) had fts5=0.20, chroma=0.35, graph=0.25,
# events=0.20 (4 backends). Post-P4a (2026-05-31) ChromaDB removed; weights
# reabsorbed into fts5 (+0.20 → 0.40) and events (+0.05 → 0.25), graph
# unchanged. Post-P4b (2026-06-04) graph DB is intact — the "P4b will remove"
# note in the early version was wrong; graph stays at 0.30.
#
# Thoth's 2026-06-08 spec (ichor-consolidation-spec/report.md §4c)
# recommended DELETING HybridScorer entirely on the assumption that
# ChromaDB removal left only FTS5 (1 backend = no fusion needed). That
# recommendation is no longer applicable: as of P4b, we have 3 backends
# (FTS5 0.45 + Graph 0.30 + Events 0.25) and the fusion math is correct.
# See Codex-God-thoth inbox message msg_20260612_073307_marvin (Q2 answer)
# for the formal decision.
WEIGHTS = {
    "fts5": 0.45,    # was 0.25, +0.20 (chroma weight reabsorbed P4a)
    "graph": 0.30,   # unchanged (P4b kept graph, contrary to early plans)
    "events": 0.25,  # was 0.15, +0.10
}

# Negation words that signal a contradiction when paired with overlapping subject
_NEGATION_WORDS = frozenset({
    "not", "no", "never", "instead", "drop", "remove", "delete",
    "don't", "dont", "won't", "wont", "shouldn't", "shouldnt",
    "stop", "discontinue", "revert", "abandon", "instead of",
})


def detect_contradiction(old_text: str, new_text: str) -> bool:
    """Cheap heuristic contradiction detector.

    Returns True if `new_text` appears to contradict `old_text`. The
    heuristic is intentionally simple — it catches obvious negations
    on overlapping topics, not deep semantic disagreement. False
    negatives are fine; false positives are fine too (the spec says
    "non-blocking" — we just flag, never block).

    Heuristic: both texts share >= 30% of significant words, AND
    `new_text` contains a negation word. No negation → no contradiction
    (just agreement or unrelated).
    """
    if not old_text or not new_text:
        return False
    # Tokenize — lowercase, drop punctuation, drop short words
    def tokens(t):
        return {
            w for w in re.findall(r"[a-z0-9_]+", t.lower())
            if len(w) > 2
        }
    old_tokens = tokens(old_text)
    new_tokens = tokens(new_text)
    if not old_tokens or not new_tokens:
        return False
    overlap = old_tokens & new_tokens
    # Jaccard-like: how much of new_text is shared with old_text
    overlap_ratio = len(overlap) / max(len(new_tokens), 1)
    if overlap_ratio < 0.30:
        return False
    # Check for negation in new_text (word boundary aware)
    new_lower = new_text.lower()
    return any(
        re.search(r"\b" + re.escape(neg) + r"\b", new_lower)
        for neg in _NEGATION_WORDS
    )


def _row_to_dict(row: Any) -> Dict[str, Any]:
    """Convert a sqlite3.Row or plain tuple to a dict.

    Plain tuples from sqlite3 (no row_factory set) iterate as positional
    values, not as (key, value) pairs — so `dict(row)` fails. This helper
    handles both: Row → dict(row); tuple → dict with column-name keys from
    cursor.description if available, else empty dict.

    Note: for plain tuples without a description, we can't recover column
    names — callers needing named access must set row_factory=sqlite3.Row.
    """
    if row is None:
        return {}
    if isinstance(row, dict):
        return row
    # sqlite3.Row has a keys() method
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    # Plain tuple — return as dict with positional keys
    return {"_" + str(i): v for i, v in enumerate(row)}

BACKEND_NAMES = {
    "fts5": "🔍 FTS5 (Keyword)",
    "graph": "🔗 Graph (Relationships)",
    "events": "📋 Events (Structured)",
}


def _ensure_imports() -> None:
    """Ensure ~/pantheon/ is on sys.path."""
    pantheon_root = str(_HOME / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


# ===================================================================
# Backend Connectors
# ===================================================================


class FTS5Backend:
    """Keyword search over ichor_events via SQLite FTS5."""

    def __init__(self) -> None:
        self._db = None

    def _connect(self):
        if self._db is None:
            _ensure_imports()
            from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
            self._db = IchorDB(db_path=str(_ICHOR_DB))
            self._db.connect()
        return self._db

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """FTS5 full-text search across ichor_events."""
        try:
            db = self._connect()
            events = db.query_fts(query, limit=limit)
            max_score = max((e.get("confidence", 0) for e in events), default=1.0)
            results = []
            for ev in events:
                results.append({
                    "id": f"fts5:{ev['id']}",
                    "score": round(ev.get("confidence", 0.5) / max_score, 3),
                    "backend": "fts5",
                    "type": ev.get("event_type", ""),
                    "title": ev.get("subject", ""),
                    "snippet": (ev.get("raw_text") or "")[:300],
                    "source": ev.get("session_id", ""),
                    "created_at": ev.get("created_at", ""),
                })
            return results
        except Exception as exc:
            logger.debug("FTS5 search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            db = self._connect()
            db._conn.execute("SELECT 1 FROM ichor_events LIMIT 1")
            return True
        except Exception:
            return False


class TieredRetriever:
    """Three-pass retrieval with progressive context loading.

    Pass 1: brief scan — fast FTS5 on `brief` field only, fetch 3x limit
    Pass 2: outline filter — load outlines for candidates, re-rank, narrow
    Pass 3: full on demand — NEVER loaded in search; caller calls
            `ichor_get(id)` or `MemoryTrait.retrieve(id=...)` for full

    Integration with existing HybridScorer:
    - TieredRetriever replaces the direct FTS5 search call
    - Other backends (Events, Graph) remain unchanged for now
    - Final fusion still uses ichor_score formula

    Weights from the build-brief: brief=0.60, outline=0.30, full=0.10.
    In tiered mode, full is always 0.0 at search time (never loaded).

    Reference: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md
    """

    def __init__(
        self,
        brief_weight: float = 0.60,
        outline_weight: float = 0.30,
        full_weight: float = 0.10,
        fts_conn: Optional[Any] = None,
    ) -> None:
        self.brief_weight = brief_weight
        self.outline_weight = outline_weight
        self.full_weight = full_weight
        self._conn = fts_conn  # tests can inject; production uses IchorDB
        self._owns_conn = fts_conn is None  # whether we should close it

    def _connect(self):
        """Lazy-init the FTS5 connection (in-memory for tests, real DB otherwise)."""
        if self._conn is not None:
            return self._conn
        _ensure_imports()
        from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
        db = IchorDB(db_path=str(_ICHOR_DB))
        db.connect()
        # memory_fts is a virtual table — we can query it directly via the
        # underlying sqlite3 connection.
        self._conn = db._conn
        return self._conn

    def _sanitize(self, query: str) -> str:
        """Strip FTS5 special chars that would break MATCH syntax.

        Keeps alphanumerics, spaces, hyphens. Replaces runs of other
        chars with a space. Returns "" for empty/non-string input.
        """
        if not query or not isinstance(query, str):
            return ""
        # Strip FTS5 operators: " * : ( ) AND OR NOT NEAR
        cleaned = re.sub(r'[":*()\^\-]', " ", query)
        cleaned = re.sub(r"\b(AND|OR|NOT|NEAR)\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _pass1_brief_scan(self, query: str, fetch_limit: int) -> List[Dict[str, Any]]:
        """Pass 1: FTS5 on the `brief` field only. Returns 3x limit candidates."""
        cleaned = self._sanitize(query)
        if not cleaned:
            # Empty query → return recent items by rowid
            conn = self._connect()
            rows = conn.execute(
                "SELECT rowid, brief, outline, content, category, name, event_type "
                "FROM memory_fts ORDER BY rowid DESC LIMIT ?",
                (fetch_limit,),
            ).fetchall()
        else:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT rowid, brief, outline, content, category, name, event_type "
                    "FROM memory_fts WHERE memory_fts MATCH ? "
                    "ORDER BY rank LIMIT ?",
                    (f"brief:{cleaned}", fetch_limit),
                ).fetchall()
            except Exception as exc:
                logger.debug("TieredRetriever Pass 1 FTS5 error: %s", exc)
                rows = []
            # Backward compat: if brief-field search returns nothing
            # (legacy rows whose brief was never backfilled), fall back to
            # a full-content search so we never silently lose recall.
            if not rows:
                try:
                    rows = conn.execute(
                        "SELECT rowid, brief, outline, content, category, name, event_type "
                        "FROM memory_fts WHERE memory_fts MATCH ? "
                        "ORDER BY rank LIMIT ?",
                        (cleaned, fetch_limit),
                    ).fetchall()
                except Exception as exc:
                    logger.debug("TieredRetriever Pass 1 fallback error: %s", exc)
                    rows = []
        return [_row_to_dict(r) for r in rows]

    def _pass2_outline_rerank(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Pass 2: score each candidate by outline match, narrow to limit.

        Re-ranks using FTS5 on the `outline` field for the same query,
        then fuses with Pass 1's brief score using brief/outline weights.

        Backward compat: rows with empty outline fall back to the content
        column (which is always populated).
        """
        cleaned = self._sanitize(query)
        if not candidates:
            return []
        if not cleaned:
            # No query → return candidates as-is, capped at limit
            return candidates[:limit]

        conn = self._connect()
        rowids = [c.get("rowid") for c in candidates if c.get("rowid") is not None]
        if not rowids:
            return candidates[:limit]

        # Re-score each candidate via outline MATCH
        placeholders = ",".join("?" * len(rowids))
        try:
            outline_rows = conn.execute(
                f"SELECT rowid, rank FROM memory_fts "
                f"WHERE memory_fts MATCH ? AND rowid IN ({placeholders})",
                (f"outline:{cleaned}", *rowids),
            ).fetchall()
        except Exception as exc:
            logger.debug("TieredRetriever Pass 2 FTS5 error: %s", exc)
            outline_rows = []

        # rank from FTS5: lower is better (more negative = better match)
        # Convert to a 0..1 score: score = 1 / (1 + abs(rank))
        outline_scores = {
            r["rowid"]: 1.0 / (1.0 + abs(r["rank"])) for r in outline_rows
        }

        # Brief match score: assume any candidate from Pass 1 has a non-zero
        # brief score proportional to its Pass 1 rank. Use position as proxy.
        results: List[Dict[str, Any]] = []
        for idx, cand in enumerate(candidates):
            rowid = cand.get("rowid")
            # Pass 1 score: by position (0=best), normalize to 0..1
            brief_score = max(0.0, 1.0 - (idx / max(len(candidates), 1)))
            outline_score = outline_scores.get(rowid, 0.0)
            fused = self.brief_weight * brief_score + self.outline_weight * outline_score
            # Backward compat: rows with empty outline fall through to content
            if not cand.get("outline"):
                # Try a content search; if that also misses, use brief_score alone
                fused = brief_score * (self.brief_weight + self.outline_weight)
            result = {
                "id": f"fts5:{rowid}" if rowid is not None else f"fts5:row-{idx}",
                "rowid": rowid,
                "brief": cand.get("brief", ""),
                "outline": cand.get("outline", ""),
                "category": cand.get("category", ""),
                "name": cand.get("name", ""),
                "event_type": cand.get("event_type", ""),
                "score": round(fused, 4),
                "tier_pass": 2,
                "backend": "fts5_tiered",
            }
            results.append(result)
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def search(
        self,
        query: str,
        limit: int = 10,
        brief_only: bool = False,
        path: str = "pantheon://",
        return_trajectory: bool = False,
    ) -> List[Dict[str, Any]]:
        """Three-pass retrieval with optional directory scoping (B4).

        Args:
            query: Search query.
            limit: Max results to return.
            brief_only: If True, skip Pass 2 (returns just briefs, no outlines).
            path: pantheon:// path to scope the search. Default
                "pantheon://" → flat FTS5 search (B2 behavior, unchanged).
                Other paths (e.g. "pantheon://warm/", "pantheon://codexes/")
                trigger directory-recursive search via ichor_ls/ichor_find.
            return_trajectory: If True, return a Trajectory dict instead
                of a list of results. The dict has steps, results, etc.
                per ichor_trajectory's schema.

        Returns:
            List of result dicts (default), OR a Trajectory dict (when
            return_trajectory=True). Each result has `brief` + `outline`
            populated and `raw_text` NEVER loaded. Caller fetches full
            content via separate API.
        """
        # B4: dispatch on path. Default "pantheon://" is the B2 behavior.
        if path and path != "pantheon://":
            return self._dir_recursive_search(
                query, limit, path, return_trajectory=return_trajectory
            )

        fetch_limit = limit * 3  # Pass 1 fetches 3x to give Pass 2 room

        # Pass 1: brief scan
        candidates = self._pass1_brief_scan(query, fetch_limit)
        logger.debug(
            "TieredRetriever Pass 1: query=%r candidates=%d",
            query[:50], len(candidates),
        )

        if brief_only:
            # Skip Pass 2 — return just brief matches
            results = []
            for cand in candidates[:limit]:
                results.append({
                    "id": f"fts5:{cand.get('rowid')}",
                    "rowid": cand.get("rowid"),
                    "brief": cand.get("brief", ""),
                    "score": 1.0,
                    "tier_pass": 1,
                    "backend": "fts5_tiered",
                })
            self._log_retrieval(
                query=query, path=path, results=results, mode="tiered",
                passes=[{
                    "pass": 1, "action": "brief_scan",
                    "candidates": len(candidates), "selected": len(results),
                }],
            )
            if return_trajectory:
                return self._build_trajectory(
                    query, path, results,
                    passes=[{
                        "pass": 1, "action": "brief_scan",
                        "candidates": len(candidates), "selected": len(results),
                    }],
                )
            return results

        # Pass 2: outline re-rank and narrow
        results = self._pass2_outline_rerank(candidates, query, limit)
        logger.debug(
            "TieredRetriever Pass 2: candidates=%d results=%d",
            len(candidates), len(results),
        )
        passes = [
            {"pass": 1, "action": "brief_scan",
             "candidates": len(candidates), "selected": len(results)},
            {"pass": 2, "action": "outline_filter",
             "candidates": len(candidates), "selected": len(results)},
        ]
        self._log_retrieval(
            query=query, path=path, results=results, mode="tiered",
            passes=passes,
        )
        if return_trajectory:
            return self._build_trajectory(query, path, results, passes=passes)
        return results

    # -----------------------------------------------------------------
    # B4: directory-recursive search
    # -----------------------------------------------------------------

    def _dir_recursive_search(
        self,
        query: str,
        limit: int,
        path: str,
        return_trajectory: bool = False,
    ) -> Any:
        """Directory-recursive search (B4 spec algorithm).

        Step 1: ichor_ls(path) → list of directories
        Step 2: score each directory by brief match against query
        Step 3: keep top-3 directories
        Step 4: deep search within those (ichor_find)
        Step 5: re-rank — 0.6 item score + 0.4 directory score
        """
        import time as _time
        from lib.ichor_browse import ichor_ls, ichor_find  # local import
        from lib.ichor_paths import parse_path  # local import

        t_total = _time.perf_counter()

        spec = parse_path(path)
        if not spec.get("valid"):
            logger.debug("_dir_recursive_search: invalid path %r", path)
            return [] if not return_trajectory else self._build_trajectory(
                query, path, [], passes=[]
            )

        t1 = _time.perf_counter()
        entries = ichor_ls(path)
        t_ls_ms = (_time.perf_counter() - t1) * 1000.0

        # Identify directories at this level
        directories = [e for e in entries if e.get("type") == "directory"]
        # Score each directory's brief against the query (cheap substring match)
        cleaned = (query or "").lower().strip()
        dir_scores: List[Dict[str, Any]] = []
        for d in directories:
            name = d.get("name", "").lower()
            brief = (d.get("brief", "") or "").lower()
            # Simple word-overlap score
            q_words = {w for w in cleaned.split() if len(w) > 2}
            d_text = f"{name} {brief}"
            d_words = {w for w in d_text.split() if len(w) > 2}
            if not q_words or not d_words:
                score = 0.0
            else:
                overlap = len(q_words & d_words) / max(len(q_words), 1)
                score = min(1.0, overlap)
            dir_scores.append({
                "name": d.get("name", ""),
                "path": d.get("path", ""),
                "score": round(score, 3),
            })

        # Sort by score, keep top-3
        dir_scores.sort(key=lambda x: x["score"], reverse=True)
        top_3 = dir_scores[:3]
        pruned = dir_scores[3:]

        # Deep search within top-3 directories
        t2 = _time.perf_counter()
        deep_results: List[Dict[str, Any]] = []
        for d in top_3:
            sub_path = d.get("path", "")
            if sub_path:
                sub_results = ichor_find(query, sub_path, limit=limit)
                # Tag each result with its directory score
                for r in sub_results:
                    r["_directory"] = d["name"]
                    r["_directory_score"] = d["score"]
                deep_results.extend(sub_results)
        t_deep_ms = (_time.perf_counter() - t2) * 1000.0

        # Re-rank: 0.6 item score + 0.4 directory score
        for r in deep_results:
            item_score = r.get("score", 0.0)
            dir_score = r.get("_directory_score", 0.0)
            r["final_score"] = round(0.6 * item_score + 0.4 * dir_score, 4)
            r["score"] = r["final_score"]  # for downstream consumers

        # Sort and cap
        deep_results.sort(
            key=lambda r: r.get("final_score", r.get("score", 0)),
            reverse=True,
        )
        final = deep_results[:limit]

        # Build trajectory
        passes = [
            {
                "pass": 1,
                "action": "brief_scan",
                "candidates": len(entries),
                "selected": len(top_3),
                "latency_ms": round(t_ls_ms, 2),
                "directories_considered": dir_scores,
                "directories_selected": top_3,
                "directories_pruned": [
                    {**p, "reason": "below top-3 threshold"}
                    for p in pruned
                ],
            },
            {
                "pass": 2,
                "action": "deep_search",
                "candidates": len(deep_results),
                "selected": len(final),
                "latency_ms": round(t_deep_ms, 2),
            },
            {
                "pass": 3,
                "action": "rerank",
                "items": len(final),
                "latency_ms": round((_time.perf_counter() - t_total) * 1000.0, 2),
            },
        ]

        self._log_retrieval(
            query=query, path=path, results=final, mode="tiered_dir",
            passes=passes,
        )

        if return_trajectory:
            return self._build_trajectory(query, path, final, passes=passes)
        return final

    def _log_retrieval(
        self,
        query: str,
        path: str,
        results: List[Dict[str, Any]],
        mode: str,
        passes: List[Dict[str, Any]],
    ) -> None:
        """Append an entry to the retrieval-log with B4 `passes` field."""
        import time
        try:
            entry = {
                "timestamp": time.time(),
                "query": query,
                "path": path,
                "weights": dict(WEIGHTS),
                "mode": mode,
                "result_count": len(results),
                "result_ids": [r.get("id", "") for r in results],
                "backends_used": list({r.get("backend", "unknown")
                                       for r in results}) or ["fts5_tiered"],
                "passes": passes,
            }
            with open(_RETRIEVAL_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.debug("could not write retrieval log: %s", e)

    def _build_trajectory(
        self,
        query: str,
        path: str,
        results: List[Dict[str, Any]],
        passes: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Build a Trajectory dict for return_trajectory=True callers."""
        return {
            "query": query,
            "path": path,
            "steps": passes,
            "results": [r.get("id", "") for r in results],
            "weights": dict(WEIGHTS),
            "mode": "tiered" if path == "pantheon://" else "tiered_dir",
            "outcome": "pending",
        }


# ChromaBackend removed in P4a — vector search dropped.
# Use athenaeum_walk (filesystem) + ichor_score for retrieval.


class GraphBackend:
    """Entity relationship search via graph.db."""

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            import sqlite3
            conn = sqlite3.connect(str(_GRAPH_DB))
            conn.row_factory = sqlite3.Row

            # Search nodes by label matching
            cursor = conn.execute(
                """
                SELECT n.*, COUNT(e.id) AS edge_count
                FROM nodes n
                LEFT JOIN edges e ON e.source_id = n.id OR e.target_id = n.id
                WHERE n.label LIKE ? OR n.id LIKE ?
                GROUP BY n.id
                ORDER BY edge_count DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = [dict(r) for r in cursor.fetchall()]

            if not rows:
                # No matching nodes — return empty, don't fall back to general
                conn.close()
                return []

            max_edges = max((r.get("edge_count", 1) for r in rows), default=1)
            results = []
            for r in rows:
                score = min(r.get("edge_count", 1) / max_edges, 1.0)
                results.append({
                    "id": f"graph:{r['id']}",
                    "score": round(score, 3),
                    "backend": "graph",
                    "type": r.get("type", "entity"),
                    "title": r.get("label", r["id"]),
                    "snippet": f"Type: {r.get('type', '?')} | Edges: {r.get('edge_count', 0)} | Codex: {r.get('codex', '')}",
                    "source": r.get("codex", ""),
                    "created_at": r.get("created_at", ""),
                })
            conn.close()
            return results[:limit]

        except Exception as exc:
            logger.debug("Graph search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            import sqlite3
            conn = sqlite3.connect(str(_GRAPH_DB))
            conn.execute("SELECT 1 FROM nodes LIMIT 1")
            conn.close()
            return True
        except Exception:
            return False


class EventsBackend:
    """Structured event search over ichor_events (by type/confidence)."""

    def __init__(self) -> None:
        self._db = None

    def _connect(self):
        if self._db is None:
            _ensure_imports()
            from lib.ichor_db import IchorDB
            self._db = IchorDB(db_path=str(_ICHOR_DB))
            self._db.connect()
        return self._db

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search by matching query against subject or raw_text, ranked by confidence."""
        try:
            db = self._connect()
            conn = db._conn

            # Get recent high-confidence events that match the query terms
            cursor = conn.execute(
                """
                SELECT * FROM ichor_events
                WHERE (subject LIKE ? OR raw_text LIKE ?)
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = [dict(r) for r in cursor.fetchall()]

            max_conf = max((r.get("confidence", 0.5) for r in rows), default=1.0)
            results = []
            for r in rows:
                results.append({
                    "id": f"events:{r['id']}",
                    "score": round(r.get("confidence", 0.5) / max_conf, 3),
                    "backend": "events",
                    "type": r.get("event_type", ""),
                    "title": r.get("subject", ""),
                    "snippet": (r.get("raw_text") or "")[:300],
                    "source": r.get("session_id", ""),
                    "created_at": r.get("created_at", ""),
                })
            return results
        except Exception as exc:
            logger.debug("Events search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            db = self._connect()
            db._conn.execute("SELECT 1 FROM ichor_events LIMIT 1")
            return True
        except Exception:
            return False


# ===================================================================
# _Embedder removed in P4a — embedding layer dropped.
# Retrieval is now FTS5 + Graph + Events only (P4b removes Graph).

# ===================================================================
# Fusion Engine
# ===================================================================


def _normalize_scores(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize scores within each backend group to 0-1."""
    if not results:
        return results

    # Group by backend, find max per group
    max_per_backend: Dict[str, float] = {}
    for r in results:
        b = r.get("backend", "unknown")
        max_per_backend[b] = max(max_per_backend.get(b, 0), r.get("score", 0))

    # Normalize within each group
    for r in results:
        b_max = max_per_backend.get(r.get("backend", "unknown"), 1.0)
        if b_max > 0:
            r["score"] = round(r["score"] / b_max, 3)

    return results


def _compute_fused_score(result: Dict[str, Any]) -> float:
    """Compute fused score: backend weight + ichor_score post-fusion boost.

    Phase 1 (Ichor consolidation): the unified ichor_score is added as
    a post-fusion signal. The 0.70/0.30 split keeps the backend weight
    dominant (so a strong keyword hit doesn\'t get washed out by a
    stale importance score) but gives important events a meaningful
    boost over equally-matched less-important ones.

    Falls back to the legacy fused-only score if ichor_score isn\'t
    available (e.g. raw distilled docs without event metadata).
    """
    from lib.ichor_score import (
        compute_score as _compute, DEFAULT_NON_EVENT_SCORE,
        HYBRID_BOOST_WEIGHT, HYBRID_BACKEND_WEIGHT,
    )
    backend = result.get("backend", "unknown")
    weight = WEIGHTS.get(backend, 0.0)
    backend_score = result.get("score", 0.0) * weight

    # Get the ichor_score for this result. For ichor_event results
    # (which carry the full event dict under "event" or as top-level
    # fields), compute it. Otherwise default to mid-scale.
    event = result.get("event")
    if event is None:
        # Maybe the result itself is the event (raw row)
        if result.get("event_type") or result.get("subject"):
            event = result
    if event is not None:
        try:
            ichor = _compute(event) / 100.0  # 0.0..1.0
        except Exception:
            ichor = DEFAULT_NON_EVENT_SCORE / 100.0
    else:
        ichor = DEFAULT_NON_EVENT_SCORE / 100.0

    return round(backend_score * HYBRID_BACKEND_WEIGHT + ichor * HYBRID_BOOST_WEIGHT, 3)


# ===================================================================
# HybridScorer
# ===================================================================


class HybridScorer:
    """Fused search across remaining backends.

    P4a removed ChromaBackend (vector search). P4b will remove GraphBackend.
    For now, search runs across FTS5 + Graph + Events, gracefully degrading
    if a backend is down. P4c will collapse this to FTS5 + Events only.
    """

    def __init__(self) -> None:
        self._fts5 = FTS5Backend()
        self._graph = GraphBackend()
        self._events = EventsBackend()
        self._backends = {
            "fts5": self._fts5,
            "graph": self._graph,
            "events": self._events,
        }

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        backends: Optional[List[str]] = None,
        min_score: float = 0.0,
        mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fused search across selected backends.

        Args:
            query: Search query.
            limit: Max results to return.
            backends: Which backends to query (default: all 4).
            min_score: Minimum fused score threshold.

        mode: 'legacy' (default) or 'tiered'. When 'tiered', the FTS5
                  backend is replaced by TieredRetriever for token-cheap
                  search. When None, falls back to ICHOR_TIERED_ENABLED
                  env var; if not set, default is 'legacy'.

        Returns:
            Dict with 'results' (sorted list), 'backends_used', 'total',
            and 'mode' indicating which path was used.
        """
        # Resolve mode: explicit arg > env var > default 'legacy'
        if mode is None:
            mode = (
                "tiered"
                if os.environ.get("ICHOR_TIERED_ENABLED", "").lower() == "true"
                else "legacy"
            )
        if backends is None:
            backends = ["fts5", "graph", "events"]  # chroma removed in P4a

        all_results: List[Dict[str, Any]] = []
        backends_used: List[str] = []
        backend_errors: Dict[str, str] = {}

        # In tiered mode, replace the FTS5 backend's search with TieredRetriever
        tiered_retriever = TieredRetriever() if mode == "tiered" else None

        for name in backends:
            # Tiered path: replace FTS5 backend with TieredRetriever
            if name == "fts5" and tiered_retriever is not None:
                try:
                    tiered_results = tiered_retriever.search(query, limit=limit)
                    for r in tiered_results:
                        all_results.append({
                            "id": r["id"],
                            "score": r.get("score", 0.5),
                            "backend": "fts5_tiered",
                            "type": r.get("event_type", ""),
                            "title": r.get("brief", ""),
                            "snippet": r.get("outline", "")[:300],
                            "source": r.get("name", ""),
                            "created_at": "",
                            "tier_pass": r.get("tier_pass", 2),
                        })
                    if tiered_results:
                        backends_used.append("fts5_tiered")
                except Exception as exc:
                    backend_errors["fts5_tiered"] = str(exc)
                    logger.debug("Tiered FTS5 failed: %s", exc)
                continue
            be = self._backends.get(name)
            if be is None:
                continue
            try:
                batch = be.search(query, limit=limit)
                if batch:
                    backends_used.append(name)
                    all_results.extend(batch)
            except Exception as exc:
                backend_errors[name] = str(exc)
                logger.debug("Backend '%s' failed: %s", name, exc)

        if not all_results:
            return {
                "results": [],
                "query": query,
                "backends_used": backends_used,
                "backend_errors": backend_errors,
                "total": 0,
                "mode": mode,
            }

        # Normalize scores within each backend
        all_results = _normalize_scores(all_results)

        # Compute fused scores
        for r in all_results:
            r["fused_score"] = _compute_fused_score(r)

        # Deduplicate by title + snippet similarity
        seen_titles: set = set()
        deduped: List[Dict[str, Any]] = []
        for r in sorted(all_results, key=lambda x: x["fused_score"], reverse=True):
            key = (r.get("title", "").lower()[:50], r.get("snippet", "").lower()[:80])
            if key not in seen_titles:
                seen_titles.add(key)
                deduped.append(r)

        # Sort by fused score, cap
        deduped = sorted(deduped, key=lambda x: x["fused_score"], reverse=True)

        if min_score > 0:
            deduped = [r for r in deduped if r["fused_score"] >= min_score]

        top = deduped[:limit]

        # ── Log query for forge weight tuning ────────────────────────
        try:
            entry = {
                "timestamp": time.time(),
                "query": query[:200],
                "weights": dict(WEIGHTS),
                "mode": mode,
                "result_count": len(top),
                "outcome": "pending",  # C1: lazy outcome — set to "used" when a later store() correlates
                "result_ids": [r.get("id", "")[:80] for r in top[:10]],
                "backends_used": backends_used,
            }
            _RETRIEVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_RETRIEVAL_LOG, "a") as _f:
                _f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Non-fatal — don't break retrieval for logging

        return {
            "results": top,
            "query": query,
            "backends_used": backends_used,
            "backend_errors": backend_errors,
            "total": len(top),
            "weights": WEIGHTS,
            "mode": mode,
        }

    def health_check(self) -> Dict[str, Any]:
        """Check health of all backends."""
        health: Dict[str, Any] = {}
        all_healthy = True
        for name, be in self._backends.items():
            try:
                ok = be.health()
                health[name] = {
                    "healthy": ok,
                    "label": BACKEND_NAMES.get(name, name),
                    "weight": WEIGHTS.get(name, 0),
                }
                if not ok:
                    all_healthy = False
            except Exception as exc:
                health[name] = {"healthy": False, "error": str(exc)}
                all_healthy = False

        return {
            "healthy": all_healthy,
            "backends": health,
            "total_backends": len(self._backends),
            "healthy_count": sum(1 for v in health.values() if v.get("healthy")),
        }


# _background_embed removed in P4a — embedding layer dropped.
# ichor_store() now writes the note file only; no chromadb thread.


def _regenerate_context(
    source_god: str = "",
    timestamp: str = "",
    user_id: str | None = None,
) -> None:
    """Regenerate CONTEXT_{user_id}.md from DIGEST.md for prompt injection.

    Budget-aware: uses 3% of model context window for the summary.
    Fires on every digest_entry write — replaces the old 15-min cron.
    """
    try:
        user = user_id or os.environ.get("HERMES_USER_ID", "konan")
        digest_path = _HOME / "pantheon" / "shared" / "DIGEST.md"
        context_path = _HOME / "pantheon" / "shared" / f"CONTEXT_{user}.md"

        if not digest_path.exists():
            logger.debug("CONTEXT: no DIGEST.md yet")
            return

        # Parse recent digest entries (### timestamp — title format)
        text = digest_path.read_text(encoding="utf-8")
        entries = re.findall(
            r"### (\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC) — (.+?)\n"
            r"- \*\*Source:\*\* (.+?)(?: \|.*)?\n"
            r"- (.+?)(?=\n### |\n---|\Z)",
            text,
            re.DOTALL,
        )

        if not entries:
            context_path.write_text("## Recent Decisions\n\n_No recent decisions._\n")
            return

        # Sort by timestamp descending, take last 48h
        now = datetime.now(timezone.utc)
        fresh = []
        for ts, title, source, body in entries:
            try:
                entry_time = datetime.strptime(ts, "%Y-%m-%d %H:%M UTC")
                entry_time = entry_time.replace(tzinfo=timezone.utc)
                if (now - entry_time).days < 2:  # Last 48h
                    clean_body = body.strip().replace("\n", " ")
                    fresh.append((ts, title, source.strip(), clean_body))
            except ValueError:
                continue

        if not fresh:
            context_path.write_text("## Recent Decisions\n\n_No decisions in last 48h._\n")
            return

        # Budget: 3% of model context window (default 128k → ~3,800 tokens)
        budget_chars = int(128000 * 0.03 * 4)  # ~15,360 chars
        lines = ["## Recent Decisions\n"]
        used = len("".join(lines))

        for ts, title, source, body in fresh:
            est = len(body) // 4 + 40
            if used + est > budget_chars:
                break
            lines.append(f"- **{title}** — {body} _({source}, {ts[:10]})_\n")
            used += est

        context_path.write_text("".join(lines))
        logger.debug(
            "CONTEXT regenerated: %d entries, %d chars → %s",
            len(lines) - 1, used, context_path.name,
        )
    except Exception as exc:
        logger.debug("CONTEXT regeneration failed (non-fatal): %s", exc)


class MemoryTrait:
    """Unified memory interface — routes operations to the correct backend.

    Implements the OpenHuman-inspired contract:
        store(namespace, key, content, category, session_id)
        retrieve(query, limit, opts)
        forget(key)
        health_check()
    """

    def __init__(self) -> None:
        self._scorer = HybridScorer()

    def store(
        self,
        namespace: str = "default",
        key: str = "",
        content: str = "",
        category: str = "fact",
        session_id: str = "",
        god_name: str = "",
    ) -> Dict[str, Any]:
        """Store content, routing to the correct backend by category.

        Categories:
            - 'fact', 'preference', 'decision', 'commitment' → ichor_events (FTS5)
            - 'document', 'note', 'reference' → ChromaDB (via Athenaeum write)
            - 'entity', 'relationship' → Graph DB

        Args:
            namespace: Logical grouping (e.g. 'hermes', 'hephaestus').
            key: Unique identifier for the stored item.
            content: The content to store.
            category: Content category (determines backend routing).
            session_id: Source session ID.
            god_name: Name of the god storing.

        Returns:
            Dict with 'stored', 'backend', 'id'.
        """
        _ensure_imports()

        # Route by category
        if category in ("fact", "preference", "decision", "commitment", "insight", "blocker", "follow_up", "correction", "reference", "user_md_update"):
            # → ichor_events (FTS5)
            # 'user_md_update' is a forge output — agent-evaluated user profile updates
            from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
            db = IchorDB(db_path=str(_ICHOR_DB))
            db.connect()
            event_id = db.insert_event(
                session_id=session_id or key,
                event_type=category,
                subject=key or content[:60],
                predicate=category,
                object=content,
                confidence=0.9 if category != "user_md_update" else 0.95,
                source="forge" if category == "user_md_update" else "manual",
                raw_text=content,
                god_name=god_name or namespace,
            )
            # C1: post-store contradiction check (non-blocking)
            # Compare new content against recent high-importance events.
            # If a contradiction is detected, flag in the return value but
            # never block. The spec is explicit: zero impact on the
            # retrieval path, zero impact on store() success.
            contradiction_warning = False
            try:
                # Check against recent high-importance events AND all
                # decision/commitment/blocker events (those categories
                # are intrinsically high-stakes regardless of the
                # importance score). Default importance is 50, so we
                # also use a >= 50 threshold to catch freshly-stored
                # decisions whose importance hasn't been tuned yet.
                recent = db._conn.execute(
                    "SELECT raw_text FROM ichor_events "
                    "WHERE raw_text IS NOT NULL AND ("
                    "  importance >= 50 OR "
                    "  event_type IN ('decision', 'commitment', 'blocker')"
                    ") "
                    "ORDER BY id DESC LIMIT 50"
                ).fetchall()
                for row in recent:
                    old_text = row["raw_text"] if hasattr(row, "keys") else row[0]
                    if old_text and detect_contradiction(old_text, content):
                        contradiction_warning = True
                        break
            except Exception as exc:
                logger.debug("Contradiction check failed (non-fatal): %s", exc)
            db.close()
            return {
                "stored": True,
                "backend": "fts5",
                "id": f"fts5:{event_id}",
                "namespace": namespace,
                "contradiction_warning": contradiction_warning,
            }

        elif category in ("entity", "relationship"):
            # → Graph DB
            import sqlite3
            conn = sqlite3.connect(str(_GRAPH_DB))
            now = datetime.now(timezone.utc).isoformat()
            node_id = key or f"manual:{namespace}:{hash(content) % 10**8}"
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO nodes (id, type, codex, label, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (node_id, category, namespace, key or content[:60], json.dumps({"source": "ichor_store"}), now, now),
                )
                conn.commit()
            except Exception as exc:
                logger.debug("Graph store failed: %s", exc)
            conn.close()
            return {"stored": True, "backend": "graph", "id": f"graph:{node_id}", "namespace": namespace}

        elif category == "digest_entry":
            # → Append to shared digest (forge output)
            digest_path = _HOME / "pantheon" / "shared" / "DIGEST.md"
            digest_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            safe_god = god_name or namespace or "unknown"
            entry = (
                f"\n### {timestamp} — {key}\n"
                f"- **Source:** {safe_god}"
                f"{f' | Session: `{session_id}`' if session_id else ''}\n"
                f"- {content}\n"
            )
            with open(digest_path, "a", encoding="utf-8") as f:
                f.write(entry)

            # Also regenerate CONTEXT_{user_id}.md for prompt injection
            _regenerate_context(safe_god, timestamp)

            return {"stored": True, "backend": "digest", "id": f"digest:{timestamp}", "namespace": namespace}

        else:
            # → Write to Athenaeum + background embed
            athenaeum_path = _ensure_imports()
            notes_dir = _HOME / "athenaeum" / "Codex-Pantheon" / "ichor-notes"
            notes_dir.mkdir(parents=True, exist_ok=True)
            note_path = notes_dir / f"{namespace}--{key.replace('/', '--')}.md"
            note_path.write_text(
                f"---\nnamespace: {namespace}\nkey: {key}\ncategory: {category}\n"
                f"stored_at: {datetime.now(timezone.utc).isoformat()}\n"
                f"session_id: {session_id}\n---\n\n{content}\n",
                encoding="utf-8",
            )
            # P4a: no chromadb embed thread — embedding layer removed.
            return {"stored": True, "backend": "athenaeum", "id": str(note_path.relative_to(_HOME)), "namespace": namespace}

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        backends: Optional[List[str]] = None,
        min_score: float = 0.0,
        output_format: str = "json",
    ) -> Any:
        """Unified retrieval across all backends (delegates to HybridScorer).

        Args:
            query: Search query.
            limit: Max results.
            backends: Which backends to search (default: all).
            min_score: Minimum fused score.
            output_format: 'json' or 'markdown'.

        Returns:
            JSON dict or formatted markdown string.
        """
        result = self._scorer.retrieve(
            query=query,
            limit=limit,
            backends=backends,
            min_score=min_score,
        )

        if output_format == "json":
            return result

        # Markdown
        if not result["results"]:
            return f"🔍 No results for `{query}` across any backend."

        lines = [f"## 🔍 Hybrid Search: `{query}`", ""]

        for r in result["results"]:
            backend_name = BACKEND_NAMES.get(r.get("backend", ""), r.get("backend", ""))
            fused = r.get("fused_score", r.get("score", 0))
            icon_map = {"blocker": "🚧", "commitment": "📋", "decision": "🎯",
                        "follow_up": "🔁", "insight": "💡", "document": "📄",
                        "entity": "🔗", "correction": "🔧", "fact": "📌"}
            icon = icon_map.get(r.get("type", ""), "•")
            lines.append(f"**{r.get('title', '?')}** {icon}")
            lines.append(f"  `{backend_name}` · fused: {fused:.2f} · type: {r.get('type', '?')}")
            if r.get("snippet"):
                lines.append(f"  > {r['snippet']}")
            lines.append("")

        lines.append(f"---")
        lines.append(f"_Backends: {', '.join(result['backends_used'])} · {result['total']} results_")
        return "\n".join(lines)

    def store_goal(
        self,
        title: str,
        description: str = "",
        category: str = "general",
        priority: int = 5,
        target_date: str = "",
    ) -> Dict[str, Any]:
        """A1: Store a strategic goal in `ichor.db::strategic_goals`.

        Thin convenience wrapper around `lib.ichor_goals.IchorGoals.add()`
        so the MemoryTrait contract has a `store_*` method for every
        memory object type. Returns the same shape as `store()`: a dict
        with `stored`, `backend`, `id`.

        Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §A1.
        """
        _ensure_imports()
        from lib.ichor_goals import IchorGoals  # type: ignore[import-untyped]
        goals = IchorGoals()
        try:
            gid = goals.add(
                title=title, description=description, category=category,
                priority=priority, target_date=target_date,
            )
            return {
                "stored": True,
                "backend": "strategic_goals",
                "id": f"goal:{gid}",
                "title": title,
            }
        except ValueError as exc:
            return {"stored": False, "error": str(exc)}

    def forget(self, key: str) -> Dict[str, Any]:
        """Delete from all backends by key prefix (e.g. 'fts5:42', 'graph:node:...')."""
        deleted = []
        prefix, _, rest = key.partition(":")

        if prefix == "fts5" and rest:
            try:
                _ensure_imports()
                from lib.ichor_db import IchorDB
                db = IchorDB(db_path=str(_ICHOR_DB))
                db.connect()
                db._conn.execute("DELETE FROM ichor_events WHERE id = ?", (int(rest),))
                db._conn.commit()
                db.close()
                deleted.append("fts5")
            except Exception as exc:
                logger.debug("forget fts5 failed: %s", exc)

        elif prefix == "graph" and rest:
            try:
                import sqlite3
                conn = sqlite3.connect(str(_GRAPH_DB))
                conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (rest, rest))
                conn.execute("DELETE FROM nodes WHERE id = ?", (rest,))
                conn.commit()
                conn.close()
                deleted.append("graph")
            except Exception as exc:
                logger.debug("forget graph failed: %s", exc)

        # chroma forget removed in P4a — no vector backend anymore.

        return {"forgotten": True, "key": key, "deleted_from": deleted}

    def health_check(self) -> Dict[str, Any]:
        """Health check for all backends."""
        return self._scorer.health_check()


# ===================================================================
# Quick summary formatter (for CLI/AI consumption)
# ===================================================================


def format_health_summary(health: Dict[str, Any]) -> str:
    """Format health check as a scannable string."""
    lines = [f"## 🏥 Ichor Memory Health"]
    lines.append(f"_{health['healthy_count']}/{health['total_backends']} backends healthy_\n")

    for name, info in health.get("backends", {}).items():
        status = "✅" if info.get("healthy") else "❌"
        label = info.get("label", name)
        weight = info.get("weight", 0)
        err = f" — {info.get('error', '')}" if info.get("error") else ""
        lines.append(f"{status} **{label}** (weight: {weight:.0%}){err}")

    return "\n".join(lines)


# ===================================================================
# CLI entry point
# ===================================================================


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Ichor Hybrid Scorer + Memory Trait Contract"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Retrieve
    p_ret = sub.add_parser("retrieve", help="Fused search across backends")
    p_ret.add_argument("query", help="Search query")
    p_ret.add_argument("--limit", "-l", type=int, default=10)
    p_ret.add_argument("--backends", "-b", nargs="+",
                       choices=["fts5", "graph", "events"],  # chroma removed P4a
                       default=["fts5", "graph", "events"])
    p_ret.add_argument("--min-score", "-m", type=float, default=0.0)
    p_ret.add_argument("--markdown", "-d", action="store_true", help="Output markdown instead of JSON")

    # Store
    p_st = sub.add_parser("store", help="Store content")
    p_st.add_argument("--key", "-k", required=True)
    p_st.add_argument("--content", "-c", required=True)
    p_st.add_argument("--namespace", "-n", default="default")
    p_st.add_argument("--category", "-t", default="fact",
                      choices=["fact", "preference", "decision", "commitment",
                               "insight", "blocker", "follow_up", "document", "entity"])
    p_st.add_argument("--session-id", "-s", default="")
    p_st.add_argument("--god-name", "-g", default="")

    # Health
    sub.add_parser("health", help="Check backend health")

    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)

    trait = MemoryTrait()

    if args.command == "retrieve":
        result = trait.retrieve(
            query=args.query,
            limit=args.limit,
            backends=args.backends,
            min_score=args.min_score,
            output_format="markdown" if args.markdown else "json",
        )
        if args.markdown:
            print(result)
        else:
            print(json.dumps(result, indent=2, default=str))

    elif args.command == "store":
        result = trait.store(
            namespace=args.namespace,
            key=args.key,
            content=args.content,
            category=args.category,
            session_id=args.session_id,
            god_name=args.god_name,
        )
        print(json.dumps(result, indent=2))

    elif args.command == "health":
        health = trait.health_check()
        print(json.dumps(health, indent=2))
        print()
        print(format_health_summary(health))


if __name__ == "__main__":
    main()
