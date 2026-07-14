"""Ichor retrieval coverage / total_matching — Phase 3 helper module.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 3 (Retrieval Coverage / `total_matching`)

The motivating problem (from spec §Key Article Principle — Error Observability
Collapse): a retrieval that returns 5 results can either mean "5 of 5
candidates" (full coverage) or "5 of 200 candidates" (2.5% coverage). The
caller cannot tell which from the current `total` field — both look like
`"total": 5`. That makes low-coverage answers look authoritative.

This module fixes that by:

  1. Providing per-backend candidate counts via `count_candidates_*()`.
     Each backend has its own count mechanism (see spec §Backend Counting
     Notes). We never fabricate counts; if a backend cannot cheaply
     count, the count returns None and `coverage_confidence` flips to
     "unknown".

  2. Providing a `CoverageStats` dataclass that packages per-backend
     returned/total/coverage_pct/confidence into a structured shape.

  3. Providing `aggregate_coverage()` that computes the overall coverage
     block across all backends — `returned`, `total_matching`,
     `coverage_pct`, `coverage_confidence`. The aggregate confidence is
     "known" only if every backend with results is known; "partial" if
     some known and some unknown; "unknown" if no backend can count.

Pure module: no DB writes, no side effects, no global state. Safe to
import from anywhere. Backends call `count_candidates_<name>(query)`
to get their candidate count; HybridScorer wraps everything in
`aggregate_coverage()` for the response shape.

Usage:

    from lib.ichor.retrieval_coverage import (
        CoverageStats,
        count_candidates_fts5,
        count_candidates_events,
        count_candidates_graph,
        count_candidates_vector,
        count_candidates_reference,
        aggregate_coverage,
    )

    fts5_stats = CoverageStats(
        returned=3,
        total_matching=count_candidates_fts5("conductor"),
        coverage_confidence="known",
    )
    coverage = aggregate_coverage({
        "fts5": fts5_stats,
        "vector": CoverageStats(returned=0, total_matching=None,
                                coverage_confidence="unknown"),
    })

Per-backend count mechanisms (spec §Phase 3 Backend Counting Notes):

  - FTS5:      `SELECT COUNT(*) FROM ichor_events_fts WHERE MATCH ?`
               Cheap because FTS5 already maintains the index.
  - Events:    `SELECT COUNT(*) FROM ichor_events WHERE LIKE %q%`
               Normal SQL count over subject + raw_text.
  - Graph:     `SELECT COUNT(*) FROM nodes WHERE label LIKE %q%`
               Bounded to matching nodes, NOT the global node count.
  - Vector:    Count of vectors within a configurable distance threshold.
               If embedding model is unavailable or DB has no embeddings,
               returns None (unknown). Threshold defaults to 0.7
               cosine-equivalent distance; configurable via
               `VECTOR_COVERAGE_DISTANCE_THRESHOLD` env var.
  - Reference: `SELECT COUNT(*) FROM warm_entities + reference_knowledge
               + l2_scenarios WHERE LIKE %pat%`
               Cheap because tables are small (≤60K rows today).

The spec is explicit: "Do not fabricate counts." All count functions
return Optional[int] and swallow exceptions → None. Callers must
inspect None and propagate `coverage_confidence="unknown"`.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("ichor.retrieval_coverage")

# ──────────────────────────────────────────────────────────────────────
# Paths — mirrors ichor_hybrid.py constants
# ──────────────────────────────────────────────────────────────────────

_HOME = Path.home()
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_GRAPH_DB = _HOME / ".hermes" / "pantheon" / "graph.db"

# Vector count: cosine-equivalent distance threshold. Vectors closer
# than this are counted as "matching" candidates. Conservative default
# (0.7) — only counts vectors that are reasonably semantically close.
# Tunable via env so the Forge can adjust without code changes.
_VECTOR_DISTANCE_THRESHOLD = float(
    os.environ.get("VECTOR_COVERAGE_DISTANCE_THRESHOLD", "0.7")
)
_VECTOR_COUNT_LIMIT = int(
    os.environ.get("VECTOR_COVERAGE_COUNT_LIMIT", "500")
)


# ──────────────────────────────────────────────────────────────────────
# CoverageStats
# ──────────────────────────────────────────────────────────────────────


@dataclass
class CoverageStats:
    """Per-backend retrieval coverage.

    Attributes:
        returned: Number of results actually returned for this backend
                  in the current retrieve() call. Integer ≥ 0.
        total_matching: Number of candidates this backend matched for
                  the query. None when the backend cannot cheaply
                  count — callers MUST mark `coverage_confidence` as
                  "unknown" in that case. Spec: "Do not fabricate counts."
        coverage_pct: returned / total_matching * 100. None when
                  total_matching is None (unknown) or zero (no
                  candidates → coverage undefined).
        coverage_confidence: "known" if total_matching is a real int,
                  "unknown" if total_matching is None, "partial" if
                  total_matching is approximate (currently unused —
                  reserved for future backends).
    """

    returned: int
    total_matching: Optional[int]
    coverage_confidence: str = "known"
    coverage_pct: Optional[float] = field(default=None)

    def __post_init__(self) -> None:
        # Auto-compute coverage_pct when both inputs are valid
        if self.coverage_pct is None and self.total_matching not in (None, 0):
            self.coverage_pct = round(
                100.0 * self.returned / self.total_matching, 2
            )
        # Auto-fix confidence: if total_matching is None and caller
        # forgot to set unknown, fix it. Don't silently mask a typo
        # though — if caller explicitly set "known" while total is
        # None, that's a bug and we surface it.
        if self.total_matching is None and self.coverage_confidence != "unknown":
            logger.debug(
                "CoverageStats: total_matching is None but "
                "coverage_confidence=%r; auto-correcting to 'unknown'",
                self.coverage_confidence,
            )
            self.coverage_confidence = "unknown"
        # Sanity: coverage_confidence must be one of the allowed values
        if self.coverage_confidence not in ("known", "partial", "unknown"):
            raise ValueError(
                f"coverage_confidence must be 'known', 'partial', or "
                f"'unknown' — got {self.coverage_confidence!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to JSON-safe dict."""
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────
# Per-backend count functions
#
# Each function returns Optional[int]:
#   - int: the number of candidates the backend matched for this query
#   - None: the count is unknown / not cheaply computable
#
# Each function is best-effort: exceptions are caught and logged,
# returning None. The spec is clear — never fabricate a count.
# ──────────────────────────────────────────────────────────────────────


def _fts_sanitize(query: str) -> str:
    """Sanitize a user query for FTS5 MATCH syntax.

    FTS5 has special characters (":*()^" —, AND/OR/NOT/NEAR) that
    break MATCH. Strip them; if everything got stripped, return ""
    so the caller knows the query is unsafe.
    """
    if not query or not isinstance(query, str):
        return ""
    cleaned = re.sub(r'["\*\(\)\^\-]', " ", query)
    cleaned = re.sub(r"\b(AND|OR|NOT|NEAR)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def count_candidates_fts5(query: str, db_path: Optional[Path] = None) -> Optional[int]:
    """Count FTS5 candidates matching `query`.

    Uses `ichor_events_fts MATCH ?` — FTS5 already maintains the
    inverted index, so the count is O(matches) not O(rows).

    Returns None if the query is empty/unsafe, the table doesn't
    exist, or any SQLite error occurs.
    """
    cleaned = _fts_sanitize(query)
    if not cleaned:
        return None
    db_path = db_path or _ICHOR_DB
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM ichor_events_fts "
                "WHERE ichor_events_fts MATCH ?",
                (cleaned,),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("count_candidates_fts5 failed: %s", exc)
        return None


def count_candidates_events(
    query: str, db_path: Optional[Path] = None
) -> Optional[int]:
    """Count ichor_events rows matching the query via LIKE.

    Mirrors the EventsBackend.search() LIKE pattern (subject or
    raw_text contains the query). Normal SQL count — cheap on
    indexed columns. Returns None on any error.
    """
    if not query or not query.strip():
        return None
    db_path = db_path or _ICHOR_DB
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            pattern = f"%{query.strip()}%"
            row = conn.execute(
                "SELECT COUNT(*) FROM ichor_events "
                "WHERE subject LIKE ? OR raw_text LIKE ?",
                (pattern, pattern),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("count_candidates_events failed: %s", exc)
        return None


def count_candidates_graph(
    query: str, db_path: Optional[Path] = None
) -> Optional[int]:
    """Count graph nodes matching the query via LIKE on label.

    Spec §Phase 3 Backend Counting Notes: "Graph: count traversed/
    eligible edges/nodes within bound, not global graph count."
    We count matching nodes (LIKE on label) — that's the set the
    GraphBackend would actually search over. Cheap because label
    is indexed. Returns None on any error.
    """
    if not query or not query.strip():
        return None
    db_path = db_path or _GRAPH_DB
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            pattern = f"%{query.strip()}%"
            row = conn.execute(
                "SELECT COUNT(*) FROM nodes WHERE label LIKE ? OR id LIKE ?",
                (pattern, pattern),
            ).fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("count_candidates_graph failed: %s", exc)
        return None


def count_candidates_vector(
    query_text: str,
    db_path: Optional[Path] = None,
    distance_threshold: Optional[float] = None,
    count_limit: Optional[int] = None,
) -> Optional[int]:
    """Count vector matches within a distance threshold.

    Spec §Phase 3 Backend Counting Notes:
        "Vector: count above/under a configured distance threshold
        if feasible; otherwise unknown."

    Implementation: embed the query, KNN-search with a high limit
    (default 500), count the hits closer than the threshold
    (default 0.7 cosine-equivalent distance).

    Returns None if:
      - the embedder is unavailable (model not loaded)
      - the vector DB has no embeddings
      - sqlite-vec is not loadable
      - any other error

    Configurable via env: VECTOR_COVERAGE_DISTANCE_THRESHOLD,
    VECTOR_COVERAGE_COUNT_LIMIT.
    """
    if not query_text or not query_text.strip():
        return None
    threshold = distance_threshold if distance_threshold is not None else _VECTOR_DISTANCE_THRESHOLD
    limit = count_limit if count_limit is not None else _VECTOR_COUNT_LIMIT
    db_path = db_path or _ICHOR_DB
    try:
        # Lazy-import embedder + vector backend to keep this module
        # importable in environments where fastembed/sqlite_vec are
        # not installed (e.g. minimal test envs).
        from lib.ichor.embedder import embed_one
        from lib.ichor.vector_backend import VectorBackend
    except Exception as exc:
        logger.debug("count_candidates_vector: import failed: %s", exc)
        return None
    try:
        qvec = embed_one(query_text)
        if not qvec:
            return None
        backend = VectorBackend(db_path=db_path)
        # KNN search with high limit; count hits within threshold.
        hits = backend.search(qvec, limit=limit)
        if not hits:
            # No hits at all — could mean the DB is empty, NOT unknown.
            # Return 0 so the caller marks coverage_confidence="known"
            # with total_matching=0.
            return 0
        matched = sum(1 for h in hits if float(h.get("distance", 1.0)) < threshold)
        return matched
    except Exception as exc:
        logger.debug("count_candidates_vector failed: %s", exc)
        return None


def _reference_pattern(query: str) -> str:
    """Convert query to a LIKE-friendly pattern (mirrors L2ReferenceBackend)."""
    stop = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "this", "that", "these", "those", "it", "its", "to", "of",
        "in", "for", "on", "with", "and", "or", "but", "as", "by",
        "at", "from", "into", "out", "up", "down", "over", "under",
        "we", "i", "you", "they", "he", "she", "our", "your", "their",
        "do", "does", "did", "have", "has", "had", "will", "would",
        "could", "should", "can", "may", "might", "must", "shall",
    }
    tokens: list[str] = []
    for tok in re.findall(r"[a-z0-9_]+", (query or "").lower()):
        if len(tok) <= 2 or tok in stop:
            continue
        tokens.append(tok)
        if len(tokens) >= 6:
            break
    if not tokens:
        return ""
    return "%" + "%".join(tokens) + "%"


def count_candidates_reference(
    query: str, db_path: Optional[Path] = None
) -> Optional[int]:
    """Count L2 reference backend candidates (warm_entities + reference_knowledge).

    Mirrors L2ReferenceBackend._like_pattern() to produce the same
    LIKE pattern the search path uses. Counts matching rows across
    both tables. l2_scenarios is intentionally NOT counted here —
    it has its own count path in the search and the L2 scenarios
    query module is a separate concern; including it would inflate
    counts without matching the search() output.

    Returns None on any error.
    """
    pattern = _reference_pattern(query)
    if not pattern:
        return None
    db_path = db_path or _ICHOR_DB
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            warm = conn.execute(
                "SELECT COUNT(*) FROM warm_entities "
                "WHERE name LIKE ? OR value LIKE ? "
                "OR brief LIKE ? OR outline LIKE ?",
                (pattern, pattern, pattern, pattern),
            ).fetchone()
            ref = conn.execute(
                "SELECT COUNT(*) FROM reference_knowledge "
                "WHERE title LIKE ? OR body LIKE ? "
                "OR brief LIKE ? OR outline LIKE ? OR slug LIKE ?",
                (pattern, pattern, pattern, pattern, pattern),
            ).fetchone()
            return int(warm[0]) + int(ref[0])
        finally:
            conn.close()
    except Exception as exc:
        logger.debug("count_candidates_reference failed: %s", exc)
        return None


# ──────────────────────────────────────────────────────────────────────
# Aggregate coverage
# ──────────────────────────────────────────────────────────────────────


def aggregate_coverage(
    by_backend: Dict[str, CoverageStats],
) -> Dict[str, Any]:
    """Compute the overall coverage block across all backends.

    Args:
        by_backend: Mapping of backend name → CoverageStats. Backends
            with zero returned results are still included so the caller
            can see "vector returned 0 of 47 candidates".

    Returns:
        Dict with the response shape:
            {
                "returned": <int>,            # total returned across backends
                "total_matching": <int|None>, # sum of per-backend totals; None if any unknown
                "coverage_pct": <float|None>,
                "coverage_confidence": "known"|"partial"|"unknown",
                "by_backend": {<name>: <CoverageStats.to_dict()>, ...},
            }

    Aggregate confidence rules (spec §Phase 3):
        - "known" if every backend that returned ≥1 result has a known
          count, AND at least one backend has a known count.
        - "partial" if some backends are known and some unknown.
        - "unknown" if no backend has a known count, OR if every
          backend returned zero results and at least one is unknown.

    Aggregate total_matching:
        - int sum of all known per-backend totals.
        - None if any contributing backend is unknown.
        - 0 if all backends have known totals that sum to 0.
    """
    # Defensive copy + filter
    if not by_backend:
        return {
            "returned": 0,
            "total_matching": 0,
            "coverage_pct": None,
            "coverage_confidence": "unknown",
            "by_backend": {},
        }

    total_returned = sum(s.returned for s in by_backend.values())
    known_totals = [
        s.total_matching for s in by_backend.values()
        if s.total_matching is not None
    ]
    has_unknown = any(
        s.total_matching is None for s in by_backend.values()
    )

    if known_totals and not has_unknown:
        total_matching: Optional[int] = sum(known_totals)
        confidence = "known"
    elif known_totals and has_unknown:
        # Per spec: partial means "we know some, not all".
        # Sum the known ones as a lower bound; flag the unknown ones.
        total_matching = sum(known_totals)
        confidence = "partial"
    else:
        total_matching = None
        confidence = "unknown"

    # Aggregate coverage_pct
    if total_matching in (None, 0):
        coverage_pct: Optional[float] = None
    else:
        coverage_pct = round(100.0 * total_returned / total_matching, 2)

    return {
        "returned": total_returned,
        "total_matching": total_matching,
        "coverage_pct": coverage_pct,
        "coverage_confidence": confidence,
        "by_backend": {name: s.to_dict() for name, s in by_backend.items()},
    }


# ──────────────────────────────────────────────────────────────────────
# Backend-name → count-function dispatch table
# ──────────────────────────────────────────────────────────────────────


COUNT_FUNCTIONS = {
    "fts5":      count_candidates_fts5,
    "vector":    count_candidates_vector,
    "graph":     count_candidates_graph,
    "events":    count_candidates_events,
    "reference": count_candidates_reference,
}


def count_for_backend(backend_name: str, query: str) -> Optional[int]:
    """Dispatch count_candidates to the right per-backend function.

    Returns None for unknown backend names — HybridScorer uses this to
    mark coverage_confidence="unknown" without raising.
    """
    fn = COUNT_FUNCTIONS.get(backend_name)
    if fn is None:
        return None
    try:
        return fn(query)
    except Exception as exc:
        logger.debug("count_for_backend(%s) raised: %s", backend_name, exc)
        return None
