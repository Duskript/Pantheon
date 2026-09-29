"""Observations retrieval backend for Ichor hybrid retrieval.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 4).

Returns consolidated observation rows with the same result shape as the
FTS5/events backends plus observation-specific evidence metadata:

    id           "observation:<id>"
    backend      "observations"
    type         "observation"
    source       "ichor_observations"
    proof_count, trend, status, first_seen, last_seen,
    source_ids, tags, rank_reasons

Tag filters are applied in SQL BEFORE ranking/truncation; temporal
validity (``is_active_at``) is applied before ranking as well.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.ichor_tags import build_tag_filter_sql, normalize_tags
from lib.ichor_temporal import is_active_at, temporal_rank_boost

# Feature flag — safe rollback: setting ICHOR_OBSERVATIONS_ENABLED=false
# disables the backend without a service restart.
def _observations_enabled() -> bool:
    return os.environ.get("ICHOR_OBSERVATIONS_ENABLED", "true").strip().lower() != "false"


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class ObservationsBackend:
    """FTS5-backed retrieval over consolidated ichor_observations rows."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".hermes" / "ichor.db"
        self.db_path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            # Use IchorDB so additive schema migrations always run first.
            from lib.ichor_db import IchorDB

            db = IchorDB(db_path=self.db_path)
            db.connect()
            conn = db._conn
            if conn is None:  # pragma: no cover - connect() always sets it
                raise sqlite3.OperationalError("ichor db connection unavailable")
            self._conn = conn
        return self._conn

    def enabled(self) -> bool:
        return _observations_enabled()

    def health(self) -> bool:
        """Health probe: table exists and is queryable (read-only)."""
        try:
            conn = self._connect()
            conn.execute("SELECT 1 FROM ichor_observations LIMIT 1")
            return True
        except Exception:
            return False

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: list[str] | None = None,
        tags_match: str = "any",
        query_timestamp: str | None = None,
        include_sources: bool = False,
        include_inactive: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search observations, applying tag/temporal filters before ranking.

        Returns result dicts shaped like other Ichor backends (see module
        docstring). Empty on any failure — retrieval must never crash.
        """
        if not _observations_enabled():
            return []
        try:
            conn = self._connect()
            normalized = normalize_tags(tags)
            tag_sql, tag_params = build_tag_filter_sql(
                "o",
                "ichor_observation_tags",
                "id",
                "observation_id",
                normalized,
                tags_match,  # type: ignore[arg-type]
            )
            where = ["ichor_observations_fts MATCH ?"]
            params: List[Any] = [query]
            if tag_sql:
                where.append(tag_sql)
                params.extend(tag_params)
            # Status filtering in SQL (before ranking). Temporal validity
            # windows (valid_from/valid_until) are checked in Python below.
            if include_inactive:
                where.append("o.status IS NOT NULL")
            else:
                where.append("(o.status IS NULL OR o.status = 'active')")

            sql = (
                "SELECT o.*, fts.rank AS fts_rank "
                "FROM ichor_observations o "
                "JOIN ichor_observations_fts fts ON o.id = fts.rowid "
                "WHERE " + " AND ".join(where) + " "
                "ORDER BY fts.rank LIMIT ?"
            )
            params.append(max(1, int(limit)))
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

            if not rows:
                return []

            # Proof/recency boosts + temporal filtering are cheap in Python.
            strict = bool(tags_match and tags_match.endswith("_strict"))
            results: List[Dict[str, Any]] = []
            for row in rows:
                if not is_active_at(row, query_timestamp):
                    continue
                results.append(
                    self._row_to_result(row, query_timestamp, include_sources, strict=strict)
                )

            results.sort(key=lambda r: r["score"], reverse=True)
            return results[:limit]
        except Exception:
            return []

    def _row_to_result(
        self,
        row: Dict[str, Any],
        query_timestamp: str | None,
        include_sources: bool,
        strict: bool = False,
    ) -> Dict[str, Any]:
        """Convert one observation row into a backend result dict."""
        obs_id = int(row["id"])
        proof_count = int(row.get("proof_count") or 1)
        base = float(row.get("confidence") or 0.5)
        # FTS rank (lower is better) folded into a small relevance bonus.
        fts_rank = row.get("fts_rank")
        if isinstance(fts_rank, (int, float)):
            base = _clamp(base + 0.10 / (1.0 + abs(float(fts_rank))))
        proof_boost = min(0.15, 0.03 * (proof_count - 1))
        temporal_boost, temporal_reasons = temporal_rank_boost(row, query_timestamp)
        score = _clamp(base + proof_boost + temporal_boost)

        conn = self._conn
        tag_rows = []
        source_rows = []
        if conn is not None:
            try:
                tag_rows = conn.execute(
                    "SELECT tag FROM ichor_observation_tags WHERE observation_id = ? ORDER BY tag",
                    (obs_id,),
                ).fetchall()
                source_rows = conn.execute(
                    "SELECT event_id, conclusion_id, quote, source_session_id, source_god_name, "
                    "source_timestamp FROM ichor_observation_sources "
                    "WHERE observation_id = ? ORDER BY source_timestamp, event_id",
                    (obs_id,),
                ).fetchall()
            except Exception:
                tag_rows, source_rows = [], []

        tags = [str(r["tag"]) for r in tag_rows]
        source_ids: List[str] = []
        sources: List[Dict[str, Any]] = []
        for s in source_rows:
            if s["event_id"] is not None:
                source_ids.append(f"fts5:{int(s['event_id'])}")
            if s["conclusion_id"] is not None:
                source_ids.append(f"conclusion:{int(s['conclusion_id'])}")
            sources.append({
                "event_id": s["event_id"],
                "conclusion_id": s["conclusion_id"],
                "quote": str(s["quote"] or ""),
                "source_session_id": s["source_session_id"],
                "source_god_name": s["source_god_name"],
                "source_timestamp": s["source_timestamp"],
            })

        reasons = ["observation", f"proof_count:{proof_count}"]
        if tags:
            reasons.append("strict_tags" if strict else "tagged")
        reasons.extend(temporal_reasons)

        result: Dict[str, Any] = {
            "id": f"observation:{obs_id}",
            "backend": "observations",
            "type": "observation",
            "title": str(row.get("content") or row.get("subject") or "")[:200],
            "snippet": str(row.get("content") or "")[:500],
            "score": round(score, 4),
            "confidence": round(float(row.get("confidence") or 0.0), 4),
            "proof_count": proof_count,
            "trend": row.get("trend") or "new",
            "status": row.get("status") or "active",
            "first_seen": row.get("first_seen"),
            "last_seen": row.get("last_seen"),
            "evidence_span_days": row.get("evidence_span_days") or 0,
            "source_ids": source_ids,
            "source": "ichor_observations",
            "god_name": _observation_god_name(source_rows),
            "tags": tags,
            "rank_reasons": reasons,
            "category": row.get("category") or "",
            "observation_id": obs_id,
        }
        if include_sources:
            result["sources"] = sources
        return result


def _observation_god_name(source_rows: list) -> str:
    """Best-effort god attribution from source rows (most common)."""
    counts: Dict[str, int] = {}
    for s in source_rows:
        g = s["source_god_name"]
        if g:
            counts[str(g)] = counts.get(str(g), 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: kv[1])[0]


def search_observations(
    query: str,
    limit: int = 10,
    tags: list[str] | None = None,
    tags_match: str = "any",
    query_timestamp: str | None = None,
    include_sources: bool = False,
    db_path: str | Path | None = None,
) -> List[Dict[str, Any]]:
    """Module-level convenience wrapper around ObservationsBackend.search."""
    backend = ObservationsBackend(db_path=db_path)
    return backend.search(
        query=query,
        limit=limit,
        tags=tags,
        tags_match=tags_match,
        query_timestamp=query_timestamp,
        include_sources=include_sources,
    )
