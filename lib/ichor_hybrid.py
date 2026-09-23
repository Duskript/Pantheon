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

import contextlib
import json
import logging
import math
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
# Resolve through the account home, not `$HOME`: a god's gateway session runs
# with HOME set to its profile sandbox, so `Path.home()` silently points at a
# DIFFERENT DB — a shadow `ichor.db` was written in production this way.
from lib.pantheon_path import account_home as _account_home  # noqa: E402

logger = logging.getLogger("ichor_hybrid")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_HOME = _account_home()
_PANTHEON_LIB = _HOME / "pantheon" / "lib"
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_GRAPH_DB = _HOME / ".hermes" / "pantheon" / "graph.db"

# The live entity graph. `_GRAPH_DB` above is the legacy Codex graph — a 0-byte
# file — so the `graph` lane returned zero candidates while holding 0.15 of the
# fusion weight (measured 2026-09-19: 0 candidates across a 70-query labeled eval
# set). Entities/relationships actually live in `_ICHOR_DB`, the same graph the
# per-turn provider walks; `_LIVE_ICHOR_DB` exists as a self-documenting alias.
_LIVE_ICHOR_DB = _ICHOR_DB
_LIVE_GRAPH_MAX_NODES = 25
_LIVE_GRAPH_MAX_EDGES = 40
_LIVE_GRAPH_FANOUT = 12
_LIVE_GRAPH_TIMEOUT_MS = 250

# Candidate pool ceiling for the FTS-backed lanes. Fusion uses `limit` results
# per lane, but ranking/ordering the ENTIRE match set first is what made these
# lanes slow (584 ms fts5 / 2.1 s events on prose queries). Bound the pool, then
# rank inside it: recall at limit=10 does not need 50k candidates.
_FTS_POOL_CAP = 400

# Anchor scoring: query words that carry no discriminative signal for entity
# matching. Kept deliberately small -- over-filtering removes real vocabulary
# from paraphrase queries.
_ANCHOR_STOP = frozenset({
    "the", "and", "for", "with", "that", "this", "from", "into", "their", "there",
    "what", "which", "who", "when", "where", "how", "why", "was", "were", "are",
    "has", "have", "had", "not", "but", "all", "any", "can", "may", "use", "used",
    "using", "one", "two", "its", "his", "her", "our", "you", "your", "about",
})
_ANCHOR_CACHE_MAX = 256

# Weight of the summary term in anchor scoring (name x3, aliases x2, summary xN).
# Exposed because the corpus changes underneath it: after the 2026-09-20 summary
# backfill (13,849 entities filled), 18.6k active entities carry summaries and any
# of them can reach the anchor list through this term alone. Set to 0 to emulate a
# summary-less corpus without reverting the data.
ANCHOR_SUMMARY_WEIGHT_DEFAULT = 8.0


# Whether the graph lane renders a neighbour's `summary` as the result snippet
# (falling back to "<type> linked to <anchor> via '<rel>'"). Exposed for the same
# reason as the anchor weight: the 2026-09-20 summary backfill changed what this
# renders for ~13.8k nodes, which changes dedup keys and the text metric.
GRAPH_SNIPPET_SUMMARY_DEFAULT = True


def _graph_snippet_uses_summary() -> bool:
    """Whether graph results use the neighbour's summary as their snippet."""
    raw = os.environ.get("ICHOR_GRAPH_SNIPPET_SUMMARY")
    if raw is None or raw == "":
        return GRAPH_SNIPPET_SUMMARY_DEFAULT
    return raw.strip().lower() not in ("0", "false", "no", "off")


# Summary overlap is scored by inverse document frequency, not by matched-token
# count. Why (measured 2026-09-20, after the full-corpus summary backfill filled
# 13,849 long-tail summaries from one prompt template):
#
#   * a raw count is length-biased — the generated summaries list 2-3 relations in
#     a fixed template, so they match more query tokens than the curated ones for
#     no better reason, and low-degree long-tail entities displaced the hubs that
#     actually connect to the answer (mean walked-anchor degree 32 -> 17,
#     walked anchor useful in 55/70 queries -> 48/70);
#   * structural vocabulary ("part of", "related to", "used by") appears in
#     thousands of summaries and carries no anchoring signal.
#
# IDF prices both out: a token in half the corpus is worth ~0.1 of a distinctive
# one. A plain document-frequency cutoff was measured too and did not recover the
# ranking (linked MRR 0.321 at a 5% cutoff vs 0.367 unfiltered) — the length bias
# needs weighting, not exclusion.
#
# Weight 8 is the sweep winner (scripts/_anchor_weight_by_kind.py, per-subset so a
# paraphrase gain cannot hide a named-query loss). IDF sums are ~1.0 per
# distinctive token, so this is ~8 points for a three-token distinctive match
# against 3 per name token:
#
#   weight  paraphrase text@5/MRR  paraphrase linked@5/MRR  hand-written text@5/MRR
#   1(raw)      0.471 / 0.373         0.383 / 0.208             —  (raw count, no IDF)
#   5           0.933 / 0.893         0.817 / 0.689           0.500 / 0.375
#   8           0.950 / 0.922         0.850 / 0.744           0.500 / 0.375
#   12          0.950 / 0.922         0.833 / 0.757           0.600 / 0.425
#
# 8 and 12 tie on paraphrase text and 8 leads on linked hit@5, with no measured
# cost to the hand-written queries at either — 8 is the plateau start, not a peak.
ANCHOR_SUMMARY_IDF_DEFAULT = True


def _anchor_summary_idf_enabled() -> bool:
    """Whether summary overlap is IDF-weighted (env override, default on)."""
    raw = os.environ.get("ICHOR_ANCHOR_SUMMARY_IDF")
    if raw is None or raw == "":
        return ANCHOR_SUMMARY_IDF_DEFAULT
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _anchor_summary_weight() -> float:
    """Summary-term weight for anchor scoring (env override, default 1.0)."""
    raw = os.environ.get("ICHOR_ANCHOR_SUMMARY_WEIGHT")
    if raw is None or raw == "":
        return ANCHOR_SUMMARY_WEIGHT_DEFAULT
    try:
        return max(0.0, float(raw))
    except ValueError:
        return ANCHOR_SUMMARY_WEIGHT_DEFAULT


def _anchor_tokens(text: str) -> set:
    """Lowercased word set for anchor scoring (no stemming: entity names are short)."""
    return {
        t for t in re.split(r"[^0-9a-z]+", (text or "").lower())
        if len(t) > 2 and t not in _ANCHOR_STOP
    }

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
# NOTE (2026-09-20): `vector` and `events` are no longer in the default lane
# list — measured at zero recall contribution for ~3.1 s of the ~3.1 s per-query
# fusion cost. Their weights are RETAINED so explicit opt-in (`backends=["vector"]`)
# still scores them as before; the drift gate pins the key set either way.
WEIGHTS = {
    "fts5": 0.09,      # Phase 4 rebalance
    "vector": 0.05,    # opt-in lane (dropped from the default list 2026-09-20)
    "graph": 0.73,
    "events": 0.03,    # opt-in lane (dropped from the default list 2026-09-20)
    "reference": 0.10,  # revived 2026-09-20 (L2ReferenceBackend)
}

# Hindsight upgrade (Phase 4): extra weights for optional backends. These are
# applied ONLY when the backend is present in the candidate pool, and never
# mutate the exported WEIGHTS dict — the C2 weight-drift gate (which pins
# WEIGHTS keys to the benchmark baseline) stays stable.
_EXTRA_BACKEND_WEIGHTS = {
    "observations": 0.35,
    "knowledge_pages": 0.35,
    "person_roots": 0.32,
    # Warm-tier entity lookup (2026-09-20). Lives here rather than in WEIGHTS
    # because it is an opt-in lane: the extra dict is applied only when the
    # backend is in the candidate pool, so the exported WEIGHTS dict — and the
    # C2 drift gate that pins its keys — never changes. Without an entry here the
    # lane scored 0.0 and contributed zero top-k results (measured: it was
    # attempted on all 70 queries and surfaced nothing).
    "warm": 0.35,
}


# --- Tunable weight surface (eval / tuning only) ---------------------------
# The exported WEIGHTS dict is NEVER mutated at runtime: the C2 weight-drift
# gate pins its keys to the benchmark baseline. Experimentation therefore runs
# through an override that is set for the duration of a measurement and always
# restored (see `use_weights`), so a tuner can score candidate configurations
# against a labeled query set without touching production defaults.
_WEIGHT_OVERRIDE: Optional[Dict[str, float]] = None
_EXTRA_WEIGHT_OVERRIDE: Optional[Dict[str, float]] = None


def _active_weights() -> Dict[str, float]:
    """Fusion weights in effect: the tuner's override, else the pinned WEIGHTS."""
    return _WEIGHT_OVERRIDE if _WEIGHT_OVERRIDE is not None else WEIGHTS


def _active_extra_weights() -> Dict[str, float]:
    """Optional-backend weights in effect (observations/pages/person_roots)."""
    return _EXTRA_WEIGHT_OVERRIDE if _EXTRA_WEIGHT_OVERRIDE is not None else _EXTRA_BACKEND_WEIGHTS


def current_weights() -> Dict[str, float]:
    """The pinned production weights (read-only copy, for reports/baselines)."""
    return dict(WEIGHTS)


@contextlib.contextmanager
def use_weights(weights: Optional[Dict[str, float]] = None,
                extra: Optional[Dict[str, float]] = None):
    """Temporarily fuse with `weights` / `extra`. Always restores on exit.

    Single-process, single-threaded use (the eval harness and the weight tuner).
    Anything holding a live conversation must not enter this context.
    """
    global _WEIGHT_OVERRIDE, _EXTRA_WEIGHT_OVERRIDE
    prev, prev_extra = _WEIGHT_OVERRIDE, _EXTRA_WEIGHT_OVERRIDE
    _WEIGHT_OVERRIDE = dict(weights) if weights is not None else None
    _EXTRA_WEIGHT_OVERRIDE = dict(extra) if extra is not None else None
    try:
        yield
    finally:
        _WEIGHT_OVERRIDE, _EXTRA_WEIGHT_OVERRIDE = prev, prev_extra

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
    "person_roots": "🧬 Person Roots (ACL)",
}


def _ensure_imports() -> None:
    """Ensure ~/pantheon/ is on sys.path."""
    pantheon_root = str(_HOME / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


# ===================================================================
# Backend Connectors
# ===================================================================


_FTS_OPERATOR_WORDS = frozenset({"and", "or", "not", "near"})


def _fts_match_expr(query: str, *, mode: str = "or", max_terms: int = 8) -> str:
    """Build a safe FTS5 MATCH expression from a natural-language query.

    A raw user query is not an FTS5 expression. Two failure modes follow from
    passing one through: punctuation raises a MATCH syntax error (swallowed by the
    caller's except -> empty result), and default AND semantics mean a prose
    question matches no row at all. Measured on the labeled set: the fts5 lane
    returned nothing for 4 of 5 queries, and the events lane LIKE-scanned 1.82M
    rows twice (2.5 s) to find the same nothing.

    Tokenise, drop FTS5 operator words, quote every term, then join. `mode="and"`
    is the precise first attempt; `mode="or"` is the broadening fallback. An empty
    return means the query has no usable terms — the caller must not run MATCH.
    """
    tokens = [t for t in re.split(r"[^0-9A-Za-z]+", (query or "").lower()) if len(t) > 1]
    tokens = [t for t in tokens if t not in _FTS_OPERATOR_WORDS][:max_terms]
    if not tokens:
        return ""
    joiner = " AND " if mode == "and" else " OR "
    return joiner.join(f'"{t}"' for t in tokens)


def _fts_match_ladder(query: str, top_n: int = 4, max_terms: int = 8) -> List[str]:
    """Ordered MATCH expressions, precise -> broad. Stop at the first hit.

    A raw OR over every token of a prose question is a huge posting-list union:
    measured over 1.8M documents, that cost 1.9 s on the fts5 lane and 4.2 s on
    the events lane. AND over every token is cheap but matched nothing on prose.
    The ladder keeps both properties by trying the cheap precise forms first:

      1. AND over all usable tokens      -- exact-ish, tiny match set
      2. AND over the longest `top_n`    -- drops filler ("the", "and", "what")
      3. OR  over the longest `top_n`    -- last resort, bounded breadth

    Returns [] when the query has no usable terms (caller must not run MATCH).
    """
    tokens = [t for t in re.split(r"[^0-9A-Za-z]+", (query or "").lower()) if len(t) > 1]
    tokens = [t for t in tokens if t not in _FTS_OPERATOR_WORDS][:max_terms]
    if not tokens:
        return []
    longest = sorted(tokens, key=len, reverse=True)[:top_n]
    # Longest first keeps the most discriminative token in every rung.
    longest = sorted(longest, key=lambda t: (-len(t), t))

    ladder = [
        _fts_match_expr(query, mode="and", max_terms=max_terms),
        " AND ".join(f'"{t}"' for t in longest),
        " OR ".join(f'"{t}"' for t in longest),
    ]
    out: List[str] = []
    for expr in ladder:
        if expr and expr not in out:
            out.append(expr)
    return out


class FTS5Backend:
    """Keyword search over ichor_events via SQLite FTS5."""

    def __init__(self) -> None:
        self._db = None
        # Which rung of the match ladder produced the last non-empty result set
        # ("and" = precise, "or" = broadened). Ops/eval telemetry.
        self._last_match_mode = ""
        # Hindsight Phase 7 (temporal as-of recall): count of rows dropped
        # by is_active_at validity-window filtering in the most recent
        # search call. HybridScorer reads this for the retrieval metadata
        # block (`temporal_filter_dropped_count`).
        self._last_temporal_dropped = 0

    def _connect(self):
        if self._db is None:
            _ensure_imports()
            from lib.ichor_db import IchorDB  # type: ignore[import-untyped]
            self._db = IchorDB(db_path=str(_ICHOR_DB))
            self._db.connect()
        return self._db

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        query_timestamp: Optional[str] = None,
        include_inactive: bool = False,
        include_raw: bool = False,
        include_sources: bool = False,
    ) -> List[Dict[str, Any]]:
        """FTS5 full-text search across ichor_events.

        Hindsight upgrade (Phase 5/7): optional tag filters (SQL, before
        ranking/truncation) and temporal validity filtering. When no tags or
        query_timestamp are supplied the behavior is unchanged from the
        legacy path except that ``status != 'active'`` rows are excluded
        (matching the observations backend contract).
        """
        try:
            db = self._connect()
            conn = db._conn
            from lib.ichor_tags import build_tag_filter_sql, normalize_tags
            from lib.ichor_temporal import is_active_at

            normalized = normalize_tags(tags)
            tag_sql, tag_params = build_tag_filter_sql(
                "e", "ichor_event_tags", "id", "event_id", normalized,
                tags_match or "any_strict",  # type: ignore[arg-type]
            )
            exprs = _fts_match_ladder(query)
            if not exprs:
                return []
            # placeholder order: subquery MATCH, subquery pool cap, tags..., limit
            where: List[str] = []          # the MATCH lives in the subquery
            params: List[Any] = [exprs[0], max(int(limit) * 20, _FTS_POOL_CAP)]
            if tag_sql:
                where.append(tag_sql)
                params.extend(tag_params)
            if not include_inactive:
                where.append("(e.status IS NULL OR e.status = 'active')")

            sql = (
                "SELECT e.* FROM ichor_events e "
                "JOIN (SELECT rowid, rank FROM ichor_events_fts "
                "      WHERE ichor_events_fts MATCH ? ORDER BY rank LIMIT ?) fts "
                "  ON e.id = fts.rowid "
                "WHERE " + " AND ".join(where) + " "
                "ORDER BY fts.rank LIMIT ?"
            )
            params.append(max(1, int(limit)))
            rows: List[Dict[str, Any]] = []
            for expr in exprs:  # precise -> broad, stop at the first non-empty
                attempt = list(params)
                attempt[0] = expr
                rows = [dict(r) for r in conn.execute(sql, attempt).fetchall()]
                if rows:
                    self._last_match_mode = "and" if " AND " in expr else "or"
                    break

            max_score = max((e.get("confidence", 0) for e in rows), default=1.0)
            results: List[Dict[str, Any]] = []
            for ev in rows:
                if not include_inactive and not is_active_at(ev, query_timestamp):
                    self._last_temporal_dropped += 1
                    continue
                result = {
                    "id": f"fts5:{ev['id']}",
                    "score": round(ev.get("confidence", 0.5) / max(max_score, 1e-9), 3),
                    "backend": "fts5",
                    "type": ev.get("event_type", ""),
                    "title": ev.get("subject", ""),
                    "snippet": (ev.get("raw_text") or "")[:300],
                    "source": ev.get("session_id", ""),
                    "created_at": ev.get("created_at", ""),
                    "god_name": ev.get("god_name", ""),
                    "rank_reasons": ["fts5"],
                }
                if include_raw:
                    result["raw_text"] = ev.get("raw_text") or ""
                if normalized and tags_match and tags_match.endswith("_strict"):
                    result["scope_status"] = "strict_scope_match"
                results.append(result)
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
                "weights": dict(_active_weights()),
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
            "weights": dict(_active_weights()),
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
                    "god_name": r.get("god_name", ""),
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
        # Which rung of the match ladder produced the last non-empty result set
        # ("and" = precise, "or" = broadened). Ops/eval telemetry.
        self._last_match_mode = ""
        # Hindsight Phase 7 (temporal as-of recall): count of rows dropped
        # by is_active_at validity-window filtering in the most recent
        # search call. HybridScorer reads this for retrieval metadata.
        self._last_temporal_dropped = 0

    def _connect(self):
        if self._db is None:
            _ensure_imports()
            from lib.ichor_db import IchorDB
            self._db = IchorDB(db_path=str(_ICHOR_DB))
            self._db.connect()
        return self._db

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        query_timestamp: Optional[str] = None,
        include_inactive: bool = False,
        include_raw: bool = False,
        include_sources: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search by matching query against subject or raw_text, ranked by confidence.

        Hindsight upgrade (Phase 5/7): tag filters are enforced in SQL
        before ranking/truncation; temporal validity filtering runs in
        Python afterwards (same contract as the FTS5 backend).
        """
        try:
            db = self._connect()
            conn = db._conn
            from lib.ichor_tags import build_tag_filter_sql, normalize_tags
            from lib.ichor_temporal import is_active_at

            normalized = normalize_tags(tags)
            tag_sql, tag_params = build_tag_filter_sql(
                "e", "ichor_event_tags", "id", "event_id", normalized,
                tags_match or "any_strict",  # type: ignore[arg-type]
            )
            # Text match goes through the FTS index rather than a LIKE scan: this
            # lane used to full-scan 1.82M rows twice (measured 2.5 s/query) and
            # still returned almost nothing, because LIKE '%prose question%'
            # matches no row. Same table, index-backed, ~50 ms.
            exprs = _fts_match_ladder(query)
            if not exprs:
                return []
            # Cap the pool inside the subquery: the outer query orders by
            # confidence/created_at, and sorting an unbounded match set was the
            # 2.1 s. Recall at limit=10 never needs more than a few hundred.
            where = [
                "(e.id IN (SELECT rowid FROM ichor_events_fts "
                "          WHERE ichor_events_fts MATCH ? LIMIT ?))"
            ]
            params: List[Any] = [exprs[0], max(int(limit) * 20, _FTS_POOL_CAP)]
            if tag_sql:
                where.append(tag_sql)
                params.extend(tag_params)
            if not include_inactive:
                where.append("(e.status IS NULL OR e.status = 'active')")

            sql = (
                "SELECT e.* FROM ichor_events e WHERE "
                + " AND ".join(where)
                + " ORDER BY e.confidence DESC, e.created_at DESC LIMIT ?"
            )
            params.append(max(1, int(limit)))
            rows: List[Dict[str, Any]] = []
            for expr in exprs:  # precise -> broad, stop at the first non-empty
                attempt = list(params)
                attempt[0] = expr
                rows = [dict(r) for r in conn.execute(sql, attempt).fetchall()]
                if rows:
                    self._last_match_mode = "and" if " AND " in expr else "or"
                    break

            max_conf = max((r.get("confidence", 0.5) for r in rows), default=1.0)
            results: List[Dict[str, Any]] = []
            for r in rows:
                if not include_inactive and not is_active_at(r, query_timestamp):
                    self._last_temporal_dropped += 1
                    continue
                result = {
                    "id": f"events:{r['id']}",
                    "score": round(r.get("confidence", 0.5) / max(max_conf, 1e-9), 3),
                    "backend": "events",
                    "type": r.get("event_type", ""),
                    "title": r.get("subject", ""),
                    "snippet": (r.get("raw_text") or "")[:300],
                    "source": r.get("session_id", ""),
                    "created_at": r.get("created_at", ""),
                    "god_name": r.get("god_name", ""),
                    "rank_reasons": ["events"],
                }
                if include_raw:
                    result["raw_text"] = r.get("raw_text") or ""
                if normalized and tags_match and tags_match.endswith("_strict"):
                    result["scope_status"] = "strict_scope_match"
                results.append(result)
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


class KnowledgePagesBackend:
    """Knowledge-page projection backend (Phase 8).

    Wraps ``KnowledgePageStore.search_pages`` and shapes results like the
    other Ichor backends. Pages are rebuildable projections, never a source
    of truth; strict tag scoping is enforced inside the store.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or str(_ICHOR_DB)
        self._last_temporal_dropped = 0

    def _store(self):
        from lib.ichor_knowledge_pages import KnowledgePageStore

        return KnowledgePageStore(db_path=self.db_path)

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        query_timestamp: Optional[str] = None,
        include_inactive: bool = False,
        include_raw: bool = False,
        include_sources: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search knowledge pages by question/content token overlap."""
        try:
            store = self._store()
            pages = store.search_pages(
                query,
                tags=tags,
                tags_match=tags_match or "any_strict",
                limit=max(1, int(limit)),
            )
            results: List[Dict[str, Any]] = []
            for p in pages:
                key = str(p.get("key") or "")
                results.append({
                    "id": f"page:{key}",
                    "backend": "knowledge_pages",
                    "type": "knowledge_page",
                    "title": str(p.get("question") or key),
                    "snippet": str(p.get("content_md") or "")[:300],
                    "score": round(float(p.get("score") or 0.5), 4),
                    "source": "ichor_knowledge_pages",
                    "created_at": p.get("created_at", ""),
                    "version": p.get("version"),
                    "scope_tags": p.get("scope_tags") or [],
                    "source_observation_ids": p.get("source_observation_ids") or [],
                    "rank_reasons": ["knowledge_page"],
                    "key": key,
                })
                if include_raw:
                    results[-1]["content_md"] = str(p.get("content_md") or "")
            return results
        except Exception as exc:
            logger.debug("KnowledgePages search failed: %s", exc)
            return []

    def health(self) -> bool:
        try:
            store = self._store()
            conn = store._connect()
            conn.execute("SELECT 1 FROM ichor_knowledge_pages LIMIT 1")
            return True
        except Exception:
            return False


class L2ReferenceBackend:
    """Curated-reference lane: `reference_knowledge` + `l2_scenarios` (P5d).

    `reference` has carried a fusion weight since the 4-backend era, but no
    backend ever registered under that name — `self._backends.get("reference")`
    returned None, so the lane could not produce a result and the harness
    correctly reported it as offline (0 candidates, 0 ms). This wires it for
    real.

    Scope is deliberate: the two *small* curated corpora only.

      * `reference_knowledge` — curated Athenaeum indexes / distilled concepts
        (~30 rows).
      * `l2_scenarios` — Forge cross-session patterns, status='active' (~26).

    `warm_entities` (188k rows) is also counted in the reference coverage
    helper, but a LIKE scan over it is exactly the fault the keyword lanes
    were just fixed for. Both tables here are tens of rows, so the lane does a
    bounded fetch and scores by token overlap in Python: no LIKE ordering, no
    full-table scan, sub-millisecond.

    Scoring follows the anchor fix (overlap, not substring): each query token
    present in the row scores title x3, slug/source x2, body/brief/outline x1.
    """

    _STOP = frozenset(
        "the a an of to in on for and or with that this is are was were be been "
        "it its as at by from into over under who what which when where how "
        "does do did not no we you they he she them our your".split()
    )
    _ROW_CAP = 500

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db = Path(db_path) if db_path is not None else _LIVE_ICHOR_DB
        self._last_temporal_dropped = 0

    def _connect(self):
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def _tokens(cls, text: Any) -> List[str]:
        return [
            t for t in re.findall(r"[a-z0-9]{3,}", str(text or "").lower())
            if t not in cls._STOP
        ]

    def _rows(self, conn) -> List[Dict[str, Any]]:
        """Bounded fetch of both curated corpora (tens of rows each)."""
        rows: List[Dict[str, Any]] = []
        try:
            for r in conn.execute(
                "SELECT slug, title, body, brief, outline, source, created_at "
                "FROM reference_knowledge LIMIT ?",
                (self._ROW_CAP,),
            ):
                rows.append({
                    "id": f"ref:{r['slug']}",
                    "kind": "reference_knowledge",
                    "title": r["title"] or r["slug"] or "",
                    "key": r["slug"] or "",
                    "source": r["source"] or "",
                    "body": r["body"] or "",
                    "brief": r["brief"] or "",
                    "outline": r["outline"] or "",
                    "created_at": r["created_at"] or "",
                    "type": "reference_knowledge",
                })
        except Exception as exc:
            logger.debug("reference_knowledge fetch failed: %s", exc)
        try:
            for r in conn.execute(
                "SELECT id, slug, pattern_type, title, body, confidence, "
                "event_count, session_count, last_seen FROM l2_scenarios "
                "WHERE status = 'active' LIMIT ?",
                (self._ROW_CAP,),
            ):
                rows.append({
                    "id": f"l2-scenario:{r['id']}",
                    "kind": "l2_scenario",
                    "title": r["title"] or r["slug"] or "",
                    "key": r["slug"] or "",
                    "source": r["slug"] or "",
                    "body": r["body"] or "",
                    "brief": "",
                    "outline": "",
                    "created_at": r["last_seen"] or "",
                    "confidence": float(r["confidence"] or 0.5),
                    "pattern_type": r["pattern_type"] or "",
                    "type": f"l2_scenario_{r['pattern_type'] or 'cross_session'}",
                })
        except Exception as exc:
            logger.debug("l2_scenarios fetch failed: %s", exc)
        return rows

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        query_timestamp: Optional[str] = None,
        include_inactive: bool = False,
        include_raw: bool = False,
        include_sources: bool = False,
    ) -> List[Dict[str, Any]]:
        """Token-overlap search over the two curated reference corpora."""
        toks = self._tokens(query)
        if not toks:
            return []
        try:
            conn = self._connect()
            try:
                rows = self._rows(conn)
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("L2Reference search failed: %s", exc)
            return []

        scored: List[tuple] = []
        for r in rows:
            title_t = set(self._tokens(r.get("title")))
            key_t = set(self._tokens(r.get("key"))) | set(self._tokens(r.get("source")))
            body_t = (
                set(self._tokens(r.get("body")))
                | set(self._tokens(r.get("brief")))
                | set(self._tokens(r.get("outline")))
            )
            overlap = [t for t in toks if t in title_t or t in key_t or t in body_t]
            if not overlap:
                continue
            raw = sum(
                3 if t in title_t else (2 if t in key_t else 1) for t in overlap
            )
            # L2 scenarios are validated patterns, not raw facts: keep the
            # documented 0.7 base + 0.3 * confidence floor from the L2 query
            # module so a scenario cannot outrank a direct curated match.
            if r["kind"] == "l2_scenario":
                raw += 0.7 + 0.3 * float(r.get("confidence") or 0.0)
            scored.append((raw, r))

        if not scored:
            return []
        scored.sort(key=lambda p: (-p[0], str(p[1]["id"])))
        best = scored[0][0] or 1.0
        out: List[Dict[str, Any]] = []
        for raw, r in scored[: max(1, int(limit))]:
            item: Dict[str, Any] = {
                "id": r["id"],
                "backend": "reference",
                "type": r["type"],
                "title": str(r.get("title") or "")[:200],
                "snippet": str(r.get("body") or r.get("brief") or "")[:300],
                "score": round(min(1.0, raw / best), 4),
                "source": str(r.get("source") or ""),
                "created_at": str(r.get("created_at") or ""),
                "rank_reasons": ["reference_overlap"],
            }
            if r["kind"] == "l2_scenario":
                item["l2_metadata"] = {
                    "maturity": "scenario",
                    "importance": 80,
                    "trust": 80,
                    "pattern_type": r.get("pattern_type") or "",
                }
            if include_raw:
                item["raw_text"] = str(r.get("body") or "")
            out.append(item)
        return out

    def health(self) -> bool:
        try:
            conn = self._connect()
            try:
                conn.execute("SELECT 1 FROM reference_knowledge LIMIT 1")
                return True
            finally:
                conn.close()
        except Exception:
            return False


class WarmEntitiesBackend:
    """Warm-tier entity lookup over `warm_entities` — the tier that never existed.

    Since the ChromaDB removal the per-turn provider's T2 slot has documented
    itself as "semantic search is replaced by FTS5 (memory_fts) + WARM entity
    lookup", but nothing ever read `warm_entities` (`_query_chroma` still returns
    `[]`), and the table had no index beyond `category`/`importance`. The tier was
    absent, not slow.

    Indexed path: `warm_entities_fts`, an external-content FTS5 table over
    (name, value, brief, outline) kept in sync by triggers — see
    `lib/ichor/migrations/v2_warm_entities_fts.py`. No LIKE scan: a scan over
    188,762 rows is the ~1-2 s fault the keyword lanes were fixed for.

    Quality gate — measured, not aesthetic. 183,921 of 188,762 rows (97.4%) carry
    a `value` that is the category echoed in front of a raw text fragment
    ("blocker crash", "commitment TODO", "fact db is"): the naive extractor's
    signature. Injecting those into a turn presents fragments as knowledge, so the
    gate keeps the 3,981 entity-shaped rows — `OAuth — An authentication
    protocol…`, `ChromaDB — A vector database that is not coming back…`. The gate
    lives in the query, so the decision is auditable and reversible.
    """

    _POOL = 300
    # Rows scoring below this fraction of the best row's overlap are dropped:
    # loose OR-rung matches must not occupy context slots.
    _MIN_REL = 0.5

    # Explicit LIKE checks rather than a GLOB character class: `]` and backslash
    # inside a GLOB class are escape-sensitive, and a gate that silently stops
    # filtering is worse than a verbose one.
    _QUALITY = (
        "trim(w.name) GLOB '[A-Za-z0-9]*' "
        "AND length(trim(w.name)) BETWEEN 3 AND 60 "
        "AND w.name NOT LIKE '%' || char(10) || '%' "
        "AND w.name NOT LIKE '%' || char(9) || '%' "
        "AND w.name NOT LIKE '%{%' AND w.name NOT LIKE '%}%' "
        "AND w.name NOT LIKE '%\"%' AND w.name NOT LIKE '%|%' "
        "AND w.name NOT LIKE '%`%' AND w.name NOT LIKE '%<%' "
        "AND w.name NOT LIKE '%>%' AND w.name NOT LIKE '%*%' "
        "AND w.name NOT LIKE '%[%' AND w.name NOT LIKE '%]%' "
        "AND (length(trim(w.name)) - length(replace(trim(w.name), ' ', ''))) <= 5 "
        "AND NOT (w.value LIKE w.category || ' %') "
        "AND (length(trim(coalesce(w.brief, ''))) + length(trim(coalesce(w.outline, ''))) >= 20)"
    )

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db = Path(db_path) if db_path is not None else _LIVE_ICHOR_DB
        self._last_temporal_dropped = 0

    def _connect(self):
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        return conn

    def _has_fts(self, conn) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='warm_entities_fts'"
        ).fetchone()
        return bool(row)

    def search(
        self,
        query: str,
        limit: int = 10,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        query_timestamp: Optional[str] = None,
        include_inactive: bool = False,
        include_raw: bool = False,
        include_sources: bool = False,
    ) -> List[Dict[str, Any]]:
        """Token-overlap lookup over the quality-gated warm entity set."""
        exprs = _fts_match_ladder(query, top_n=4, max_terms=8)
        if not exprs:
            return []
        q_tokens = _anchor_tokens(query)
        if not q_tokens:
            return []

        try:
            conn = self._connect()
            try:
                if not self._has_fts(conn):
                    # No index: refuse to fall back to a 188k-row LIKE scan.
                    logger.debug("warm_entities_fts missing — warm lane skipped")
                    return []
                rows = []
                for expr in exprs:
                    rows = conn.execute(
                        "SELECT w.id, w.category, w.name, w.value, w.brief, w.outline, "
                        "       w.importance, w.trust, w.maturity, w.updated_at "
                        "FROM warm_entities_fts f "
                        "JOIN warm_entities w ON w.id = f.rowid "
                        "WHERE warm_entities_fts MATCH ? AND (" + self._QUALITY + ") "
                        "ORDER BY f.rank LIMIT ?",
                        (expr, max(self._POOL, int(limit) * 20)),
                    ).fetchall()
                    if rows:
                        break
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("WarmEntities search failed: %s", exc)
            return []
        if not rows:
            return []

        scored: List[tuple] = []
        for r in rows:
            name_t = _anchor_tokens(r["name"])
            brief_t = _anchor_tokens(r["brief"]) | _anchor_tokens(r["outline"])
            value_t = _anchor_tokens(r["value"])
            overlap = [t for t in q_tokens if t in name_t or t in brief_t or t in value_t]
            if not overlap:
                continue
            raw = sum(
                3 if t in name_t else (2 if t in brief_t else 1) for t in overlap
            )
            scored.append((raw, r))
        if not scored:
            return []
        scored.sort(key=lambda pr: (-pr[0], int(pr[1]["id"])))
        best = scored[0][0] or 1.0

        # Relevance floor: the OR rung of the MATCH ladder matches loosely, so a
        # paraphrase query can pull in rows sharing one incidental token. Without
        # a floor those fill context slots and dilute the ones that answered the
        # query — measured on the golden set: ~40% of returned rows sat below half
        # the top row's overlap score. Keep only rows within half of the best.
        floor = best * self._MIN_REL

        out: List[Dict[str, Any]] = []
        for raw, r in scored[: max(1, int(limit))]:
            if raw < floor:
                continue
            body = (r["brief"] or "").strip() or (r["outline"] or "").strip() or (r["value"] or "")
            item: Dict[str, Any] = {
                "id": f"warm:{r['id']}",
                "backend": "warm",
                "type": r["category"] or "entity",
                "title": str(r["name"] or "")[:200],
                "snippet": str(body)[:300],
                "score": round(min(1.0, raw / best), 4),
                "source": "ichor_warm_entities",
                "created_at": str(r["updated_at"] or ""),
                "importance": r["importance"],
                "maturity": r["maturity"],
                "rank_reasons": ["warm_entity_overlap"],
            }
            if include_raw:
                item["raw_text"] = str(r["value"] or "")
            out.append(item)
        return out

    def health(self) -> bool:
        try:
            conn = self._connect()
            try:
                return self._has_fts(conn)
            finally:
                conn.close()
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
    # Observations / knowledge pages live in _EXTRA_BACKEND_WEIGHTS so the
    # exported WEIGHTS dict (pinned by the C2 drift gate) never changes.
    weight = _active_weights().get(backend, _active_extra_weights().get(backend, 0.0))
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


class LiveGraphBackend:
    """Entity-relationship search over the LIVE ichor.db graph.

    `GraphBackend` targets `_GRAPH_DB` (a 0-byte legacy file), so the lane
    silently returned nothing. This walks the graph that carries the data, using
    the same bounded BFS as the per-turn provider
    (`lib.ichor.entities.traversal.graph_query_by_id`) so a dense hub cannot
    stall a retrieval.

    Bounded on purpose: anchors come from a name -> alias -> summary prefilter
    (cheapest indexed match first), then one depth-1 walk per anchor with hard
    node/edge/fanout/timeout caps.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self._db = Path(db_path) if db_path is not None else _LIVE_ICHOR_DB
        # Query -> anchors memo. Anchor scoring scans active entities, and the
        # eval harness re-retrieves the same query under many weight configs.
        self._anchor_cache: Dict[str, List[Dict[str, Any]]] = {}
        # Summary-token IDF table (computed lazily; None = not built yet).
        self._summary_idf: Optional[Dict[str, float]] = None

    def _connect(self):
        conn = sqlite3.connect(str(self._db))
        conn.row_factory = sqlite3.Row
        return conn

    def _summary_token_idf(self, conn) -> Dict[str, float]:
        """IDF of each summary token across the active corpus (built once per instance).

        `idf(t) = log(N / (1 + df(t))) / log(N)`, so a token unique to one summary
        is ~1.0 and a token in half the corpus is ~0.1 — the price of matching a
        template word instead of a distinctive one.
        """
        if self._summary_idf is not None:
            return self._summary_idf
        if not _anchor_summary_idf_enabled():
            self._summary_idf = {}
            return self._summary_idf
        rows = conn.execute(
            "SELECT summary FROM entities WHERE status='active' "
            "AND summary IS NOT NULL AND TRIM(summary) <> ''"
        ).fetchall()
        df: Dict[str, int] = {}
        n = 0
        for r in rows:
            tokens = _anchor_tokens(str(r["summary"] or ""))
            if not tokens:
                continue
            n += 1
            for token in tokens:
                df[token] = df.get(token, 0) + 1
        if not n:
            self._summary_idf = {}
            return self._summary_idf
        denom = math.log(n) or 1.0
        self._summary_idf = {
            token: math.log(n / (1 + count)) / denom for token, count in df.items()
        }
        logger.debug(
            "anchor summary idf: %d tokens over %d summaries", len(self._summary_idf), n
        )
        return self._summary_idf

    def _anchors(self, conn, query: str, limit: int = 4) -> List[Dict[str, Any]]:
        """Anchor entities for a query by token-overlap score, not substring match.

        Substring matching anchors on whatever shares a word with the query text:
        for "group of gods that develop code and have a universal license" it picks
        Marvin/Hephaestus (their names appear in the query) and walks THEIR
        neighbourhood, never reaching Pantheon. That is why the entity-linked
        metric stalled at 4-9% even with the graph lane dominant.

        Scoring: query tokens vs name (x3), aliases (x2), summary (x1). Cheap — one
        pass over active entities, memoised per query — and it degrades to
        substring behaviour when the query does contain a literal name.
        """
        q = (query or "").strip().lower()
        if not q:
            return []
        cached = self._anchor_cache.get(q)
        if cached is not None:
            return cached

        qtokens = _anchor_tokens(q)
        if not qtokens:
            return []

        rows = conn.execute(
            "SELECT id, name, type_id, summary, aliases FROM entities "
            "WHERE status = 'active'"
        ).fetchall()
        scored: List[tuple] = []
        summary_weight = _anchor_summary_weight()
        idf = self._summary_token_idf(conn)
        for r in rows:
            score = 0
            score += 3 * len(qtokens & _anchor_tokens(str(r["name"] or "")))
            score += 2 * len(qtokens & _anchor_tokens(str(r["aliases"] or "")))
            if summary_weight:
                matched = qtokens & _anchor_tokens(str(r["summary"] or ""))
                if matched:
                    if idf:
                        score += summary_weight * sum(idf.get(t, 0.0) for t in matched)
                    else:
                        score += summary_weight * len(matched)
            if score:
                scored.append((score, int(r["id"]), dict(r)))
        scored.sort(key=lambda t: (-t[0], t[1]))
        out = [{k: v for k, v in item.items() if k != "score"} for _, _, item in scored[: limit + 2]]
        # keep the score for downstream ranking/debugging
        for (score, _, item), target in zip(scored[: limit + 2], out):
            target["_anchor_score"] = score

        if len(self._anchor_cache) < _ANCHOR_CACHE_MAX:
            self._anchor_cache[q] = out
        return out

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            conn = self._connect()
        except Exception as exc:  # noqa: BLE001
            logger.debug("live graph backend open failed: %s", exc)
            return []
        try:
            try:
                from lib.ichor.entities import traversal  # type: ignore[import-untyped]
            except Exception as exc:  # noqa: BLE001
                logger.debug("live graph traversal import failed: %s", exc)
                return []

            anchors = self._anchors(conn, query)
            if not anchors:
                return []

            results: List[Dict[str, Any]] = []
            seen_keys: set = set()
            for a in anchors:
                aid = int(a["id"])
                try:
                    sub = traversal.graph_query_by_id(
                        conn,
                        aid,
                        depth=1,
                        min_confidence=0.5,
                        max_nodes=_LIVE_GRAPH_MAX_NODES,
                        max_edges=_LIVE_GRAPH_MAX_EDGES,
                        fanout=_LIVE_GRAPH_FANOUT,
                        timeout_ms=_LIVE_GRAPH_TIMEOUT_MS,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("live graph walk(%s) failed: %s", aid, exc)
                    continue

                nodes = {n.get("id"): n for n in sub.get("nodes", [])}
                anchor_name = (nodes.get(aid) or {}).get("name") or a.get("name") or aid
                for edge in sub.get("edges", []):
                    src_id, tgt_id = edge.get("source"), edge.get("target")
                    other = tgt_id if src_id == aid else src_id
                    if other is None or int(other) == aid:
                        continue
                    node = nodes.get(int(other))
                    if node is None:
                        continue
                    rel = edge.get("type") or "related_to"
                    key = (int(other), rel)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    snippet = (node.get("summary") or "").strip() if _graph_snippet_uses_summary() else ""
                    if not snippet:
                        snippet = (f"{node.get('type', 'entity')} linked to {anchor_name} "
                                   f"via '{rel}'")
                    results.append({
                        "id": f"graph:{other}:{rel}",
                        "score": float(edge.get("confidence") or 0.0),
                        "backend": "graph",
                        "type": node.get("type", "entity"),
                        "title": f"{anchor_name} --{rel}--> {node.get('name') or other}",
                        "snippet": snippet[:300],
                        "source": "ichor.db",
                    })
                    if len(results) >= limit * 3:
                        break
                if len(results) >= limit * 3:
                    break

            results.sort(key=lambda r: r["score"], reverse=True)
            return results[:limit]
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    def health(self) -> bool:
        try:
            conn = self._connect()
            try:
                conn.execute("SELECT 1 FROM entities LIMIT 1")
                return True
            finally:
                conn.close()
        except Exception:
            return False


class HybridScorer:
    """Fused search across remaining backends.

    P4a removed ChromaBackend (vector search). P4b will remove GraphBackend.
    For now, search runs across FTS5 + Graph + Events, gracefully degrading
    if a backend is down. P4c will collapse this to FTS5 + Events only.
    """

    def __init__(self) -> None:
        self._fts5 = FTS5Backend()
        # The legacy graph.db is a 0-byte file; prefer the live ER graph when it
        # is present so the `graph` lane actually contributes candidates.
        self._graph = LiveGraphBackend() if _LIVE_ICHOR_DB.exists() else GraphBackend()
        self._events = EventsBackend()
        try:
            from lib.ichor.vector_backend import VectorBackend
            self._vector = VectorBackend()
        except Exception as exc:
            logger.debug("VectorBackend not available: %s", exc)
            self._vector = None
        self._backends = {
            "fts5": self._fts5,
            "graph": self._graph,
            "events": self._events,
        }
        if self._vector is not None:
            self._backends["vector"] = self._vector

        # `reference` carried a fusion weight with no backend behind it, so the
        # lane was inert (no result could ever carry backend="reference").
        # Registered here so it is measurable; it stays OUT of the default
        # backend list until the labeled harness shows it earns its weight.
        # Env flag allows rollback without a service restart.
        self._reference = None
        try:
            if os.environ.get("ICHOR_REFERENCE_ENABLED", "true").strip().lower() != "false":
                self._reference = L2ReferenceBackend()
                self._backends["reference"] = self._reference
        except Exception as exc:
            logger.debug("L2ReferenceBackend not available: %s", exc)
            self._reference = None

        # Warm-tier entity lookup (the never-written "WARM entity lookup" the
        # provider's T2 docstring has referenced since P4a). Registered and
        # measurable; stays out of the default lane list until the harness shows
        # it earns a place, same rule as `reference`.
        self._warm = None
        try:
            if os.environ.get("ICHOR_WARM_ENABLED", "true").strip().lower() != "false":
                self._warm = WarmEntitiesBackend()
                self._backends["warm"] = self._warm
        except Exception as exc:
            logger.debug("WarmEntitiesBackend not available: %s", exc)
            self._warm = None

        # Hindsight upgrade (Phase 4/8): optional backends registered when
        # their env flags are not explicitly disabled (rollback without a
        # service restart). They are only QUERIED when a caller explicitly
        # requests them via `backends` (or `prefer_observations=True`) —
        # the default backend list is unchanged, so legacy calls behave
        # exactly as before.
        self._observations = None
        self._knowledge_pages = None
        self._person_roots = None
        try:
            if os.environ.get("ICHOR_OBSERVATIONS_ENABLED", "true").strip().lower() != "false":
                from lib.ichor.retrieval_observations import ObservationsBackend
                self._observations = ObservationsBackend(db_path=str(_ICHOR_DB))
                self._backends["observations"] = self._observations
        except Exception as exc:
            logger.debug("ObservationsBackend not available: %s", exc)
            self._observations = None
        try:
            if os.environ.get("ICHOR_KNOWLEDGE_PAGES_ENABLED", "true").strip().lower() != "false":
                self._knowledge_pages = KnowledgePagesBackend(db_path=str(_ICHOR_DB))
                self._backends["knowledge_pages"] = self._knowledge_pages
        except Exception as exc:
            logger.debug("KnowledgePagesBackend not available: %s", exc)
            self._knowledge_pages = None
        try:
            if os.environ.get("ICHOR_PERSON_ROOTS_ENABLED", "true").strip().lower() != "false":
                from lib.ichor.person_roots_backend import PersonRootsBackend
                self._person_roots = PersonRootsBackend()
                self._backends["person_roots"] = self._person_roots
        except Exception as exc:
            logger.debug("PersonRootsBackend not available: %s", exc)
            self._person_roots = None

    def retrieve(
        self,
        query: str,
        limit: int = 10,
        backends: Optional[List[str]] = None,
        min_score: float = 0.0,
        active_god: Optional[str] = None,
        mode: Optional[str] = None,
        budget: Optional[str] = None,
        max_tokens: Optional[int] = None,
        types: Optional[List[str]] = None,
        include_sources: bool = False,
        include_raw: bool = False,
        prefer_observations: bool = False,
        query_timestamp: Optional[str] = None,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        min_scores: Optional[Dict[str, float]] = None,
        include_inactive: bool = False,
        rerank: Optional[str] = None,
        requesting_person_id: Optional[str] = None,
        target_person: Optional[str] = None,
        person_context_domain: str = "profile",
        person_fact_type: str = "private",
        person_purpose: str = "general_retrieval",
        source_platform: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Fused search across selected backends.

        Hindsight upgrade (Phases 4-11) extends the legacy signature with
        optional recall controls: budget/max_tokens (Phase 6), tags and
        strict scoping (Phase 5), as-of temporal queries (Phase 7),
        observations and knowledge pages (Phases 4/8), prefer_observations
        dedup (Phase 4), and the disabled-by-default reranker (Phase 10).
        All new arguments are additive - legacy calls without them behave
        exactly as before.

        Args:
            query: Search query.
            limit: Max results to return.
            backends: Which backends to query (default: the 4 legacy
                backends). Observations / knowledge pages are only queried
                when explicitly requested here (or via prefer_observations).
            min_score: Minimum fused score threshold (legacy float).
            active_god: God asking (god-scoped boost, no-op when empty).
            mode: 'legacy' (default) or 'tiered'.
            budget: 'low' | 'mid' | 'high' - candidate effort multiplier.
            max_tokens: Payload ceiling (in estimated tokens) for results.
            types: Optional whitelist of result types, e.g.
                ['observation', 'event', 'entity'].
            include_sources: Attach source quote rows to observations.
            include_raw: Attach full raw_text to raw event results.
            prefer_observations: Suppress raw event rows that are PROVEN
                sources of returned observations (then backfill).
            query_timestamp: As-of anchor for temporal validity filtering.
            tags: Scope tags (scope:value form) applied before ranking.
            tags_match: any | all | any_strict | all_strict. Defaults to
                any_strict when tags are supplied and no explicit value is
                given.
            min_scores: Optional per-stage thresholds, e.g. {"final": 0.0}.
            include_inactive: Include archived/superseded rows.
            rerank: Optional rerank mode ('heuristic'); only honored when
                ICHOR_RERANK_ENABLED=true or explicitly requested.
            requesting_person_id / target_person / person_context_domain /
                person_fact_type / person_purpose / source_platform /
                channel_id: ACL context for the optional person_roots backend.

        Returns:
            Dict with 'results' (sorted list), 'backends_used', 'total',
            'mode', plus additive hindsight metadata: candidate_counts,
            token_budget, estimated_tokens_returned,
            results_dropped_for_token_budget,
            prefer_observations_dropped_raw_count,
            temporal_filter_dropped_count, strict_scope_excluded_counts,
            rerank_status, warnings.
        """
        # Resolve mode: explicit arg > env var > default 'legacy'
        if mode is None:
            mode = (
                "tiered"
                if os.environ.get("ICHOR_TIERED_ENABLED", "").lower() == "true"
                else "legacy"
            )
        if backends is None:
            # Lane set decided by measurement, not by inheritance. The 70-query
            # labeled set at these weights (scripts/ichor_lane_drop_experiment.py):
            #
            #   lanes                        text@5  linked@5  latency
            #   fts5+vector+graph+events      0.629    0.517    3113 ms  (old)
            #   fts5+graph                    0.629    0.517     625 ms
            #   fts5+graph+reference          0.643    0.517     732 ms  (now)
            #
            # `vector` cost ~1.0 s and `events` ~2.1 s per query for ZERO measured
            # recall: both were in the top-k but never supplied a matching hit.
            # They stay registered and opt-in (weights retained in WEIGHTS), so an
            # explicit `backends=["vector"]` call still scores exactly as before.
            #
            # `warm` (2026-09-20) is the revived warm-entity tier. Added to the
            # default set on measurement: 37 top-k results across the 70 labeled
            # queries, text hit@5 0.643 -> 0.657 and MRR 0.576 -> 0.590 at +25 ms
            # p50. The entity-linked metric is FLAT (0.517) because warm rows are
            # neither graph edges nor events, so that metric is structurally blind
            # to this lane — its own profile is the evidence (70/70 queries return
            # curated rows, 18 ms mean).
            backends = ["fts5", "graph", "reference", "warm"]
        elif isinstance(backends, str):
            # Legacy callers may pass a comma-separated string.
            backends = [b.strip() for b in backends.split(",") if b.strip()]

        # Hindsight: normalize tags + resolve the effective match mode.
        from lib.ichor_tags import normalize_tags

        normalized_tags = normalize_tags(tags)
        if normalized_tags and not tags_match:
            tags_match = "any_strict"
        # Strictness only means something when tags actually EXIST to filter on.
        #
        # Deriving it from the mode string alone (`tags_match.endswith("_strict")`)
        # dropped the entire graph lane. Graph rows cannot prove tags, so under a
        # no-tag call that merely carried a "_strict" mode string the lane was
        # fetched in full and then excluded in full. Measured 2026-09-20 on
        # "How does Ichor handle memory for Konan?": under any_strict the ladder
        # returned 1 result (fts5 only) with 50 graph_untagged candidates
        # excluded; under any it returned 10 results, all 10 from graph.
        #
        # The plugin fixed this exact class on 2026-09-17; the ladder and the
        # no-tag callers kept it. See also lib/ichor_recall_ladder.py, which had
        # the same defect one layer up via its `or "any_strict"` fallback.
        is_strict = bool(
            normalized_tags and tags_match and tags_match.endswith("_strict")
        )

        # Hindsight: observations join the candidate pool when requested.
        if prefer_observations and "observations" not in backends:
            backends = list(backends) + ["observations"]

        # Person Roots: keep legacy default retrieval unchanged, but auto-join
        # the ACL-gated backend when the caller supplies person-context intent.
        person_context_requested = bool(
            requesting_person_id
            or target_person
            or person_context_domain != "profile"
            or person_fact_type != "private"
            or person_purpose != "general_retrieval"
            or source_platform
            or channel_id
        )
        if person_context_requested and "person_roots" not in backends:
            backends = list(backends) + ["person_roots"]

        # Hindsight Phase 6: budget resolves candidate fetch effort and the
        # token ceiling for the returned payload.
        from lib.ichor_budget import candidate_limit as _candidate_limit
        from lib.ichor_budget import resolve_budget

        rb = resolve_budget(budget, max_tokens)
        cand_limit = _candidate_limit(limit, rb)
        token_budget = rb.default_max_tokens if max_tokens is None else int(max_tokens)

        all_results: List[Dict[str, Any]] = []
        backends_used: List[str] = []
        attempted_backends: List[str] = []
        backend_errors: Dict[str, str] = {}
        candidate_counts: Dict[str, int] = {}
        strict_scope_excluded_counts: Dict[str, int] = {}
        temporal_filter_dropped_count = 0
        warnings: List[str] = []

        # In tiered mode, replace the FTS5 backend's search with TieredRetriever
        tiered_retriever = TieredRetriever() if mode == "tiered" else None

        for name in backends:
            # Tiered path: replace FTS5 backend with TieredRetriever
            if name == "fts5" and tiered_retriever is not None:
                attempted_backends.append("fts5")
                try:
                    tiered_results = tiered_retriever.search(query, limit=cand_limit)
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
                            "rank_reasons": ["fts5_tiered"],
                        })
                    if tiered_results:
                        backends_used.append("fts5_tiered")
                        candidate_counts["fts5_tiered"] = len(tiered_results)
                except Exception as exc:
                    backend_errors["fts5_tiered"] = str(exc)
                    logger.debug("Tiered FTS5 failed: %s", exc)
                continue
            be = self._backends.get(name)
            if be is None:
                continue
            attempted_backends.append(name)
            try:
                if name == "person_roots":
                    batch = be.search(
                        query,
                        limit=cand_limit,
                        requesting_person_id=requesting_person_id,
                        target_person=target_person,
                        context_domain=person_context_domain,
                        fact_type=person_fact_type,
                        purpose=person_purpose,
                        source_platform=source_platform,
                        channel_id=channel_id,
                        actor_god=active_god,
                    )
                else:
                    batch = be.search(
                        query,
                        limit=cand_limit,
                        tags=normalized_tags or None,
                        tags_match=tags_match,
                        query_timestamp=query_timestamp,
                        include_inactive=include_inactive,
                        include_raw=include_raw,
                        include_sources=include_sources,
                    )
            except TypeError:
                # Backend with a legacy search signature (e.g. VectorBackend)
                # - fall back to the positional-only call.
                try:
                    batch = be.search(query, limit=cand_limit)
                except Exception as exc:
                    backend_errors[name] = str(exc)
                    logger.debug("Backend '%s' failed: %s", name, exc)
                    continue
            except Exception as exc:
                backend_errors[name] = str(exc)
                logger.debug("Backend '%s' failed: %s", name, exc)
                continue
            if not batch:
                continue
            if name == "graph" and is_strict:
                # Graph rows cannot prove tags - excluded under strict scopes
                # (spec Phase 5: prefer exclusion + metadata over guessing).
                strict_scope_excluded_counts["graph_untagged"] = (
                    strict_scope_excluded_counts.get("graph_untagged", 0) + len(batch)
                )
                continue
            backends_used.append(name)
            candidate_counts[name] = candidate_counts.get(name, 0) + len(batch)
            temporal_filter_dropped_count += int(
                getattr(be, "_last_temporal_dropped", 0) or 0
            )
            all_results.extend(batch)

        if not all_results:
            from lib.ichor.retrieval_coverage import (
                CoverageStats, aggregate_coverage, count_for_backend,
            )
            by_backend_stats: Dict[str, Any] = {}
            for name in attempted_backends:
                tm = count_for_backend(name, query)
                by_backend_stats[name] = CoverageStats(returned=0, total_matching=tm)
            cb = aggregate_coverage(by_backend_stats)
            return {
                "results": [],
                "query": query,
                "backends_used": backends_used,
                "backend_errors": backend_errors,
                "returned": 0,
                "total_matching": cb["total_matching"],
                "coverage_pct": cb["coverage_pct"],
                "coverage_confidence": cb["coverage_confidence"],
                "by_backend": cb["by_backend"],
                "total": 0,
                "weights": _active_weights(),
                "mode": mode,
                "budget": rb.name,
                "token_budget": token_budget,
                "max_tokens": max_tokens,
                "estimated_tokens_returned": 0,
                "results_dropped_for_token_budget": 0,
                "candidate_counts": candidate_counts,
                "candidate_limit": cand_limit,
                "tags": normalized_tags,
                "tags_match": tags_match,
                "strict_scope_excluded_counts": strict_scope_excluded_counts,
                "prefer_observations": prefer_observations,
                "prefer_observations_dropped_raw_count": 0,
                "query_timestamp": query_timestamp,
                "temporal_filter_dropped_count": temporal_filter_dropped_count,
                "rerank_status": "disabled",
                "warnings": warnings,
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

        from lib.ichor.retrieve_fusion import apply_god_boost
        apply_god_boost(deduped, active_god=active_god)
        deduped = sorted(deduped, key=lambda x: x["fused_score"], reverse=True)

        # Hindsight Phase 13: types whitelist (post-fusion filter).
        if types:
            wanted = set(types)
            deduped = [r for r in deduped if r.get("type") in wanted]

        # Thresholds: legacy float min_score, or per-stage min_scores dict.
        threshold = min_score
        if min_scores and isinstance(min_scores, dict):
            threshold = float(min_scores.get("final", min_score))
        if threshold > 0:
            deduped = [r for r in deduped if r.get("fused_score", 0) >= threshold]

        # Hindsight Phase 4: prefer_observations dedup - drop raw event rows
        # that are PROVEN sources of returned observations, then backfill.
        prefer_observations_dropped_raw_count = 0
        if prefer_observations and "observations" in backends:
            obs_source_ids: Dict[int, set] = {}
            for obs in deduped:
                if obs.get("backend") != "observations":
                    continue
                ids: set = set()
                for sid in obs.get("source_ids") or []:
                    s = str(sid)
                    if s.startswith("fts5:"):
                        ids.add(s[len("fts5:"):])
                    elif s.startswith("events:"):
                        ids.add(s[len("events:"):])
                if ids:
                    obs_source_ids[id(obs)] = ids
            if obs_source_ids:
                all_source_ids: set = set()
                for ids in obs_source_ids.values():
                    all_source_ids |= ids
                kept: List[Dict[str, Any]] = []
                dropped_raw: List[Dict[str, Any]] = []
                for r in deduped:
                    rid = str(r.get("id") or "")
                    if r.get("backend") in ("fts5", "events") and rid.split(":", 1)[-1] in all_source_ids:
                        dropped_raw.append(r)
                    else:
                        kept.append(r)
                prefer_observations_dropped_raw_count = len(dropped_raw)
                # Backfill from lower-ranked candidates to preserve limit.
                if dropped_raw and len(kept) < limit:
                    seen = {str(r.get("id")) for r in kept}
                    for r in deduped:
                        if len(kept) >= limit:
                            break
                        if str(r.get("id")) in seen:
                            continue
                        kept.append(r)
                        seen.add(str(r.get("id")))
                # Rank reason per observation: supersedes_raw:<count>.
                for obs in kept:
                    if obs.get("backend") != "observations":
                        continue
                    superseded = len(
                        obs_source_ids.get(id(obs), set())
                        & {str(r.get("id") or "").split(":", 1)[-1] for r in dropped_raw}
                    )
                    if superseded:
                        reasons = obs.setdefault("rank_reasons", [])
                        marker = f"supersedes_raw:{superseded}"
                        if marker not in reasons:
                            reasons.append(marker)
                deduped = kept

        # Hindsight Phase 10: optional reranker (disabled by default).
        rerank_status = "disabled"
        try:
            from lib.ichor_rerank import rerank_results
            deduped, rerank_status = rerank_results(deduped, query, requested_mode=rerank)
        except Exception as exc:
            logger.debug("rerank failed: %s", exc)
            rerank_status = "passthrough"

        # Person Roots: when the caller supplied explicit person-context
        # intent, preserve the best ACL decision/source-of-truth row in the
        # returned window even if generic FTS memories outscore it. This does
        # not affect legacy/default retrieval because person_context_requested
        # is false unless person-root context params were provided.
        if person_context_requested:
            root_indices = [
                idx for idx, item in enumerate(deduped)
                if item.get("backend") == "person_roots"
            ]
            if root_indices and root_indices[0] >= limit:
                root_item = deduped.pop(root_indices[0])
                root_item.setdefault("rank_reasons", []).append("pinned_person_context")
                insert_at = min(max(limit - 1, 0), len(deduped))
                deduped.insert(insert_at, root_item)

        # Hindsight Phase 6: token-budget truncation (always keep top result).
        from lib.ichor_budget import _result_tokens, truncate_for_token_budget
        top, dropped_for_tokens, _used = truncate_for_token_budget(
            deduped, token_budget, include_sources=include_sources
        )
        top = top[:limit]
        estimated_tokens_returned = sum(
            _result_tokens(r, include_sources) for r in top
        )

        # ---- Phase 4 hydration pipeline (rank_reasons, snippets) ----
        try:
            from lib.ichor.retrieval_hydration import hydrate_pipeline
            hydrate_pipeline(top, query)
        except Exception as exc:
            logger.debug("Phase 4 hydration pipeline failed: %s", exc)
        # Guarantee rank_reasons exists on every result so downstream
        # consumers (and Phase 4 contract tests) never see a missing key.
        for r in top:
            if "rank_reasons" not in r:
                r.setdefault("rank_reasons", [])

        # ---- Phase 3 coverage block ----
        from lib.ichor.retrieval_coverage import (
            CoverageStats, aggregate_coverage, count_for_backend,
        )
        per_backend_returned: Dict[str, int] = {}
        for r in top:
            be = r.get("backend", "unknown")
            per_backend_returned[be] = per_backend_returned.get(be, 0) + 1
        by_backend_stats: Dict[str, Any] = {}
        for name in attempted_backends:
            tm = count_for_backend(name, query)
            by_backend_stats[name] = CoverageStats(
                returned=per_backend_returned.get(name, 0),
                total_matching=tm,
            )
        coverage_block = aggregate_coverage(by_backend_stats)

        # ---- Log query for forge weight tuning (Hindsight metadata) ----
        try:
            entry = {
                "timestamp": time.time(),
                "query": query[:200],
                "weights": dict(_active_weights()),
                "mode": mode,
                "result_count": len(top),
                "outcome": "pending",  # C1: lazy outcome - set to "used" when a later store() correlates
                "result_ids": [r.get("id", "")[:80] for r in top[:10]],
                "backends_used": backends_used,
                "budget": rb.name,
                "max_tokens": max_tokens,
                "token_budget": token_budget,
                "tags": normalized_tags,
                "tags_match": tags_match,
                "backends_requested": backends,
                "candidate_counts": candidate_counts,
                "strict_scope_excluded_counts": strict_scope_excluded_counts,
                "prefer_observations_dropped_raw_count": prefer_observations_dropped_raw_count,
                "estimated_tokens_returned": estimated_tokens_returned,
                "temporal_filter_dropped_count": temporal_filter_dropped_count,
                "rerank_status": rerank_status,
                "warnings": warnings,
            }
            _RETRIEVAL_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(_RETRIEVAL_LOG, "a") as _f:
                _f.write(json.dumps(entry) + "\n")
        except Exception:
            pass  # Non-fatal - don't break retrieval for logging

        return {
            "results": top,
            "query": query,
            "backends_used": backends_used,
            "backend_errors": backend_errors,
            "returned": coverage_block["returned"],
            "total_matching": coverage_block["total_matching"],
            "coverage_pct": coverage_block["coverage_pct"],
            "coverage_confidence": coverage_block["coverage_confidence"],
            "by_backend": coverage_block["by_backend"],
            "total": len(top),
            "weights": _active_weights(),
            "mode": mode,
            "budget": rb.name,
            "token_budget": token_budget,
            "max_tokens": max_tokens,
            "estimated_tokens_returned": estimated_tokens_returned,
            "results_dropped_for_token_budget": dropped_for_tokens,
            "candidate_counts": candidate_counts,
            "candidate_limit": cand_limit,
            "tags": normalized_tags,
            "tags_match": tags_match,
            "strict_scope_excluded_counts": strict_scope_excluded_counts,
            "prefer_observations": prefer_observations,
            "prefer_observations_dropped_raw_count": prefer_observations_dropped_raw_count,
            "query_timestamp": query_timestamp,
            "temporal_filter_dropped_count": temporal_filter_dropped_count,
            "rerank_status": rerank_status,
            "warnings": warnings,
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
                    "weight": _active_weights().get(name, 0),
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
        reconcile: bool = False,
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
            result = {
                "stored": True,
                "backend": "fts5",
                "id": f"fts5:{event_id}",
                "namespace": namespace,
                "contradiction_warning": contradiction_warning,
            }
            if reconcile:
                from lib.ichor.reconcile import reconcile_memory_event
                result["reconciliation"] = reconcile_memory_event(
                    db,
                    namespace=namespace,
                    key=key,
                    content=content,
                    category=category,
                    session_id=session_id,
                    god_name=god_name,
                    inserted_event_id=event_id,
                )
            return result

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
        active_god: str | None = None,
        output_format: str = "json",
        mode: Optional[str] = None,
        budget: Optional[str] = None,
        max_tokens: Optional[int] = None,
        types: Optional[List[str]] = None,
        include_sources: bool = False,
        include_raw: bool = False,
        prefer_observations: bool = False,
        query_timestamp: Optional[str] = None,
        tags: Optional[List[str]] = None,
        tags_match: Optional[str] = None,
        min_scores: Optional[Dict[str, float]] = None,
        include_inactive: bool = False,
        rerank: Optional[str] = None,
        requesting_person_id: Optional[str] = None,
        target_person: Optional[str] = None,
        person_context_domain: str = "profile",
        person_fact_type: str = "private",
        person_purpose: str = "general_retrieval",
        source_platform: Optional[str] = None,
        channel_id: Optional[str] = None,
    ) -> Any:
        """Unified retrieval across all backends (delegates to HybridScorer).

        Hindsight upgrade: all new recall controls (budget, max_tokens,
        types, include_sources, include_raw, prefer_observations,
        query_timestamp, tags, tags_match, min_scores, include_inactive,
        rerank, mode) are passed through to HybridScorer.retrieve
        additively — legacy calls with only query/limit/backends/min_score
        behave exactly as before. ``backends`` may be a comma-separated
        string or a list.

        Args:
            query: Search query.
            limit: Max results.
            backends: Which backends to search (default: all legacy).
            min_score: Minimum fused score.
            output_format: 'json' or 'markdown'.
            mode: 'legacy' (default) or 'tiered'.

        Returns:
            JSON dict or formatted markdown string.
        """
        result = self._scorer.retrieve(
            query=query,
            limit=limit,
            backends=backends,
            min_score=min_score,
            active_god=active_god or None,
            mode=mode,
            budget=budget,
            max_tokens=max_tokens,
            types=types,
            include_sources=include_sources,
            include_raw=include_raw,
            prefer_observations=prefer_observations,
            query_timestamp=query_timestamp,
            tags=tags,
            tags_match=tags_match,
            min_scores=min_scores,
            include_inactive=include_inactive,
            rerank=rerank,
            requesting_person_id=requesting_person_id,
            target_person=target_person,
            person_context_domain=person_context_domain,
            person_fact_type=person_fact_type,
            person_purpose=person_purpose,
            source_platform=source_platform,
            channel_id=channel_id,
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
