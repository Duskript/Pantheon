"""Ichor Retrieval Hydration + Ranking Modifiers (Phase 4).

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 4 (Vector Hydration + Safer Ranking)

Phase 4 says: vector hits must be inspectable BEFORE they can win.
No unhydrated vector result should rank highly.

The hydration pipeline has four stages (per spec):

    collect candidates
        ↓
    hydrate candidates        ← this module: hydrate_event_ids()
        ↓
    infer metadata            ← this module: infer_metadata()
        ↓
    score/rerank              ← this module: apply_rank_modifiers()
        ↓
    dedupe                    (lives in lib/ichor_hybrid)
        ↓
    return

What "hydrate" means here:

  Vector hits arrive with only an `event_id` (sqlite-vec returns
  KNN hits with the source event rowid). Hydration is the act of
  fetching that row's snippet / title / metadata from cold_events
  and attaching it to the result dict. Without hydration, the vector
  hit is a black box — no title, no snippet, no source path, no way
  for a caller to judge relevance.

  After hydration, every result carries:

      hydrated:           bool       (False if event_id has no cold row)
      snippet:            str        (first 300 chars of raw_text/brief)
      title:              str        (name column, or fallback)
      source_path:        str        (session_id or god_name)
      metadata:           dict       (event_type, category, importance, ...)

  The `hydrated` flag is the trigger for the #1-floor enforcement
  in apply_rank_modifiers(): unhydrated vector hits get a heavy
  penalty that pushes them below any inspectable result.

What "rank modifiers" means here:

  After backend fusion produces a fused_score, we apply additive
  boosts/penalties based on:

      + exact phrase / title match       boost
      + current decision / correction    boost
      + spec / roadmap / distilled doc   boost
      − noisy line fragment              penalty
      − stale / superseded               penalty
      − generic INDEX.md                 penalty (unless index query)
      − unhydrated vector hit            HEAVY penalty (#1-floor)

  Each modifier adds a string to `rank_reasons` so the operator
  can see WHY a result ranked where it did. This is the article-
  cited observability fix: retrieval failures must be visible, not
  silent.

The functions in this module are pure (no DB writes, no state) —
they take a list of result dicts and a connection, mutate them
in place, and return them. This keeps them unit-testable without
mocking the whole HybridScorer.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# The cold_events columns we fetch for hydration. The spec §Phase 4 lists
# these explicitly. Keeping the column list narrow makes the SQL fast and
# the result dicts small.
HYDRATION_COLUMNS: Tuple[str, ...] = (
    "id",
    "event_type",
    "category",
    "name",
    "raw_text",
    "brief",
    "god_name",
    "session_id",
    "created_at",
    "importance",
    "confidence",
    "trust",
)

# Snippet budget — keep results compact. 300 chars matches the FTS5 backend.
_SNIPPET_MAX = 300

# How many event_ids we hydrate in one SQL roundtrip. The cold_events
# table has 130k+ rows; IN(...) with thousands of params works but blows
# up query parse time. 500 is the sweet spot.
HYDRATE_BATCH = 500


def hydrate_event_ids(
    conn: sqlite3.Connection,
    event_ids: Sequence[int],
) -> Dict[int, Dict[str, Any]]:
    """One batch SQL fetch from cold_events by id.

    Returns a dict mapping event_id → row dict. Missing rows (no
    cold_events row for that event_id) are simply absent from the
    return — the caller checks `if event_id in lookup` to decide
    whether a vector hit was hydrated.

    Why one batch instead of N roundtrips:
      The vector backend can return up to `limit` event_ids per
      query. Doing N SELECTs would defeat the point of having a
      single SQL connection. SQLite's `IN (...)` handles 500 ids
      cleanly (the spec calls this out as the expected cap).

    Graceful degradation:
      If cold_events doesn't exist or the columns mismatch (e.g.
      during a schema migration), returns {} and logs. The caller
      treats empty as "no hydration possible" — vector hits remain
      unhydrated and the ranking floor kicks in, which is exactly
      the desired behavior for partial-schema states.

    Args:
        conn: An open sqlite3.Connection (row_factory = sqlite3.Row OK).
        event_ids: List of cold_events.id values to hydrate.

    Returns:
        Dict mapping event_id → row dict (only present event_ids).
    """
    if not event_ids:
        return {}

    # Dedupe + cap. The vector backend already dedupes event_ids, but
    # a defensive dedupe here keeps the SQL clean.
    unique_ids = list({int(eid) for eid in event_ids if eid is not None})
    if not unique_ids:
        return {}

    lookup: Dict[int, Dict[str, Any]] = {}
    # Split into batches if needed — 500 ids is the safe upper bound
    # for SQLite's parameter limit on this build.
    for start in range(0, len(unique_ids), HYDRATE_BATCH):
        batch = unique_ids[start : start + HYDRATE_BATCH]
        placeholders = ",".join("?" * len(batch))
        cols = ", ".join(HYDRATION_COLUMNS)
        try:
            rows = conn.execute(
                f"SELECT {cols} FROM cold_events WHERE id IN ({placeholders})",
                batch,
            ).fetchall()
        except sqlite3.OperationalError:
            # cold_events missing (legacy DB) — return what we have so far
            return lookup
        except Exception:
            # Any other error (schema mismatch, locked DB, etc.) — degrade
            return lookup
        for r in rows:
            try:
                row_dict = {k: r[k] for k in r.keys()}  # sqlite3.Row
            except (AttributeError, IndexError):
                row_dict = {"id": r[0]}
            lookup[int(row_dict.get("id", batch[0]))] = row_dict
    return lookup


def _build_snippet(row: Dict[str, Any]) -> str:
    """Pick the best text snippet for a hydrated event.

    Prefer `raw_text` (full content). Fall back to `brief`. Truncate
    to _SNIPPET_MAX chars so result dicts stay compact.
    """
    raw = (row.get("raw_text") or "").strip()
    if raw:
        return raw[:_SNIPPET_MAX]
    brief = (row.get("brief") or "").strip()
    if brief:
        return brief[:_SNIPPET_MAX]
    return ""


def _build_title(row: Dict[str, Any]) -> str:
    """Pick the best title for a hydrated event.

    Prefer `name` (often a session subject or codex label). Fall back
    to the first line of brief, then a generic label.
    """
    name = (row.get("name") or "").strip()
    if name and len(name) < 200:
        return name
    brief = (row.get("brief") or "").strip()
    if brief:
        first = brief.splitlines()[0].strip()
        if first:
            return first[:200]
    return f"cold_event:{row.get('id', '?')}"


def hydrate_vector_results(
    vector_hits: List[Dict[str, Any]],
    lookup: Dict[int, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach snippet / title / metadata to vector hits.

    Each input vector hit has shape:
        {"id": "vec:N", "score": float, "backend": "vector",
         "event_id": N, "distance": float}

    Output adds:
        "hydrated":       bool
        "snippet":        str
        "title":          str
        "source":         str (session_id or god_name)
        "metadata":       dict (event_type, category, importance, ...)
        "rank_reasons":   list[str] (starts with hydration flag)

    Pure function on its inputs (mutates each hit dict). Returns the
    same list, in the same order, for chaining.
    """
    for hit in vector_hits:
        eid = hit.get("event_id")
        if eid is None:
            hit["hydrated"] = False
            hit["snippet"] = ""
            hit["title"] = ""
            hit["source"] = ""
            hit["metadata"] = {}
            hit.setdefault("rank_reasons", [])
            hit["rank_reasons"].append("vector_unhydrated_no_event_id")
            continue
        row = lookup.get(int(eid))
        if row is None:
            hit["hydrated"] = False
            hit["snippet"] = ""
            hit["title"] = ""
            hit["source"] = ""
            hit["metadata"] = {}
            hit.setdefault("rank_reasons", [])
            hit["rank_reasons"].append("vector_unhydrated_no_cold_event")
            continue
        hit["hydrated"] = True
        hit["snippet"] = _build_snippet(row)
        hit["title"] = _build_title(row)
        hit["source"] = row.get("session_id") or row.get("god_name") or ""
        hit["metadata"] = {
            "event_type": row.get("event_type", ""),
            "category": row.get("category", ""),
            "importance": row.get("importance", 0),
            "confidence": row.get("confidence", 0),
            "trust": row.get("trust", 0),
            "god_name": row.get("god_name", ""),
        }
        hit.setdefault("rank_reasons", [])
        hit["rank_reasons"].append("hydrated_vector")
    return vector_hits


# ---------------------------------------------------------------------------
# Metadata inference — runs on every result (not just vector)
# ---------------------------------------------------------------------------
#
# Spec §Phase 4 lists modifier conditions:
#
#   + exact phrase/title match       boost
#   + current decision/correction    boost
#   + spec/roadmap/distilled doc     boost
#   - noisy line fragment            penalty
#   - stale/superseded               penalty
#   - generic INDEX.md               penalty (unless index query)
#
# We compute these as plain boolean/string fields on each result so
# apply_rank_modifiers() can decide what to do without re-parsing the
# raw_text/title.
#
# No LLM in the hot path — every inference is a cheap substring/keyword
# check against the result dict's existing fields. That keeps retrieval
# fast and deterministic.

# Tokens that mean "the user is asking for an index/inventory".
# When the query contains one of these, we DON'T penalize INDEX.md
# results (the spec: "generic INDEX.md → penalty unless index query").
_INDEX_QUERY_TOKENS = (
    "index", "codex", "inventory", "list", "overview", "table of contents",
)

# Source paths that signal a high-quality doc per spec §Phase 4
# ("spec/roadmap/distilled doc → boost"). Substring match keeps it
# simple — path starts with these prefixes get the boost.
_SPEC_PATHS = (
    "/distilled/",
    "/specs/",
    "/plans/",
    "/reports/",
    "/sessions/",
    "/shared/active/",
    "/shared/decisions/",
)

# Event types that earn the "current decision / correction / hard rule"
# boost. These are the categories that, if recent and on-topic, should
# outrank vague semantic neighbors.
_DECISION_CATEGORIES = (
    "decision",
    "correction",
    "hard_rule",
    "commitment",
    "blocker",
)

# Very short raw_text fragments are likely code snippets or table rows —
# noisy in retrieval output. The 60-char threshold is empirical; below
# that, the snippet doesn't carry enough context to be useful as evidence.
_NOISY_SNIPPET_LEN = 60

# Stale = created_at older than this. 30 days is the spec convention
# (anything older is likely superseded by newer events on the same topic).
_STALE_DAYS = 30


def infer_metadata(result: Dict[str, Any], query: str) -> Dict[str, Any]:
    """Compute the metadata flags that drive rank modifiers.

    Sets a `metadata_inference` dict on the result with booleans/strings
    the rank modifier pass consumes. Pure function: reads from the result
    and the query, writes into result["metadata_inference"]. Returns
    the result for chaining.

    Args:
        result: A retrieval result dict (already hydrated if vector).
        query:  The original query string (lowercased inside).

    Returns:
        The same result dict (modified in place + returned).

    Note: this does NOT touch fused_score. That's apply_rank_modifiers' job.
    """
    snippet = (result.get("snippet") or "").strip()
    title = (result.get("title") or "").strip()
    source = (result.get("source") or "").strip()
    raw_text = snippet  # for non-vector, snippet IS the raw_text excerpt
    backend = result.get("backend", "")
    event_type = (result.get("metadata", {}).get("event_type")
                  or result.get("type", "") or "").lower()
    category = (result.get("metadata", {}).get("category") or "").lower()
    query_lower = (query or "").lower()
    query_tokens = [t for t in re.findall(r"[a-z0-9_]+", query_lower) if len(t) > 2]

    # Exact phrase match — the query appears verbatim in title or snippet.
    # We check both: phrase match (full query string) and per-token match.
    exact_phrase = bool(query_lower) and (
        (title and query_lower in title.lower())
        or (snippet and query_lower in snippet.lower())
    )

    # Current decision / correction / hard rule — event type matches
    # one of the high-stakes categories.
    is_decision_or_correction = (
        event_type in _DECISION_CATEGORIES
        or category in _DECISION_CATEGORIES
    )

    # Spec / roadmap / distilled doc — source path contains one of the
    # high-quality prefixes (athenaeum / shared / etc).
    is_spec_or_distilled = any(p in source for p in _SPEC_PATHS)

    # Noisy line fragment — snippet is very short OR consists mostly of
    # code syntax (lots of operators, few word chars).
    is_noisy = False
    if snippet:
        if len(snippet) < _NOISY_SNIPPET_LEN:
            is_noisy = True
        else:
            word_chars = sum(1 for c in snippet if c.isalnum() or c.isspace())
            if word_chars / max(len(snippet), 1) < 0.55:
                is_noisy = True

    # Stale / superseded — created_at is older than _STALE_DAYS, OR the
    # result is explicitly marked superseded_by / archived. cold_events
    # doesn't have those columns, but we honor them when present (so
    # graph/entities results still trigger the penalty).
    from datetime import datetime as _dt, timezone as _tz
    created_at = result.get("created_at") or ""
    is_stale = False
    if created_at:
        try:
            from datetime import timedelta
            ts = created_at.replace("T", " ").replace("Z", "")[:19]
            event_dt = _dt.fromisoformat(ts)
            if event_dt.tzinfo is None:
                event_dt = event_dt.replace(tzinfo=_tz.utc)
            if (_dt.now(_tz.utc) - event_dt) > timedelta(days=_STALE_DAYS):
                is_stale = True
        except (ValueError, ImportError):
            # Unparseable timestamp → assume fresh (don't false-positive)
            is_stale = False
    if result.get("superseded_by") is not None:
        is_stale = True
    if (result.get("status") or "").lower() in ("archived", "merged"):
        is_stale = True

    # Generic INDEX.md — title or source ends with INDEX.md / index.md.
    # Penalized unless the query itself is asking for an index.
    title_lc = title.lower()
    source_lc = source.lower()
    is_generic_index = (
        title_lc.endswith("index.md")
        or source_lc.endswith("index.md")
        or "/index.md" in source_lc
    )
    is_index_query = any(tok in query_lower for tok in _INDEX_QUERY_TOKENS)

    # Hydration flag — vector backend has a dedicated code path; this
    # just reflects what hydrate_vector_results set.
    is_unhydrated_vector = (
        backend == "vector"
        and not result.get("hydrated", False)
    )

    result["metadata_inference"] = {
        "exact_phrase": exact_phrase,
        "is_decision_or_correction": is_decision_or_correction,
        "is_spec_or_distilled": is_spec_or_distilled,
        "is_noisy": is_noisy,
        "is_stale": is_stale,
        "is_generic_index": is_generic_index,
        "is_index_query": is_index_query,
        "is_unhydrated_vector": is_unhydrated_vector,
        "query_tokens": query_tokens,
    }
    return result


# ---------------------------------------------------------------------------
# Rank modifiers — apply additive boosts/penalties to fused_score
# ---------------------------------------------------------------------------
#
# Why additive instead of multiplicative:
#   Multipliers stack badly (0.5 * 0.5 * 0.7 = 0.175 → score collapse).
#   Additive modifiers are bounded and easier to reason about. The base
#   fused_score already encodes backend weight × raw relevance; modifiers
#   layer "is this the right kind of result" signal on top.
#
# Why a #1-floor for unhydrated vectors:
#   Spec §Phase 4 AC#2: "Vector hit with null snippet cannot rank #1".
#   The cleanest enforcement is a heavy penalty (-1.0) that drops the
#   fused_score below any positive non-vector result. If all results
#   are unhydrated vectors (degenerate case), the #1 floor is moot —
#   unhydrated still gets penalized but it would be the top of its
#   own negative-score pile, which is acceptable per the spec wording
#   ("cannot rank #1 unless no better evidence exists").

# Boost amounts — additive on top of fused_score (which is in [0, 1]).
BOOST_EXACT_PHRASE: float = 0.10
BOOST_DECISION_OR_CORRECTION: float = 0.08
BOOST_SPEC_OR_DISTILLED: float = 0.06

# Penalty amounts.
PENALTY_NOISY: float = -0.15
PENALTY_STALE: float = -0.20
PENALTY_GENERIC_INDEX: float = -0.10

# Heavy penalty for unhydrated vector hits — drops score below any
# inspectable result so the hit cannot rank #1 when better evidence exists.
PENALTY_VECTOR_UNHYDRATED: float = -1.0


def apply_rank_modifiers(
    results: List[Dict[str, Any]],
    query: str = "",
) -> List[Dict[str, Any]]:
    """Apply boost/penalty modifiers and append rank_reasons.

    Reads `metadata_inference` (set by infer_metadata). Mutates each
    result's `fused_score` and `rank_reasons`. Returns the same list.

    Args:
        results: Result dicts with `fused_score` already set by
                 _compute_fused_score. They must also have
                 `metadata_inference` set (call infer_metadata first).
        query:  Original query string (already used in infer_metadata;
                here it's only re-read for the index-query exemption
                when metadata_inference isn't present).

    Returns:
        The same list (modified in place + returned for chaining).
    """
    for r in results:
        meta = r.get("metadata_inference")
        if meta is None:
            # Inference wasn't run — run it now (cheap, idempotent).
            infer_metadata(r, query)
            meta = r.get("metadata_inference", {})
        reasons: List[str] = r.setdefault("rank_reasons", [])
        fused = float(r.get("fused_score", r.get("score", 0.0)))

        # Boosts first (positive signals raise good evidence).
        if meta.get("exact_phrase"):
            fused += BOOST_EXACT_PHRASE
            reasons.append("boost_exact_phrase")
        if meta.get("is_decision_or_correction"):
            fused += BOOST_DECISION_OR_CORRECTION
            reasons.append("boost_decision_correction")
        if meta.get("is_spec_or_distilled"):
            fused += BOOST_SPEC_OR_DISTILLED
            reasons.append("boost_spec_distilled")

        # Penalties (negative signals lower weak/noisy evidence).
        if meta.get("is_noisy"):
            fused += PENALTY_NOISY
            reasons.append("penalty_noisy")
        if meta.get("is_stale"):
            fused += PENALTY_STALE
            reasons.append("penalty_stale")
        # Generic INDEX.md penalty only when the query is NOT asking for index.
        if meta.get("is_generic_index") and not meta.get("is_index_query"):
            fused += PENALTY_GENERIC_INDEX
            reasons.append("penalty_generic_index")

        # Vector-specific: unhydrated hits get the #1-floor penalty.
        # This is the Phase 4 AC#2 enforcement.
        if meta.get("is_unhydrated_vector"):
            fused += PENALTY_VECTOR_UNHYDRATED
            reasons.append("penalty_vector_unhydrated")

        r["fused_score"] = round(fused, 4)

    return results


# ---------------------------------------------------------------------------
# Convenience: full hydration pipeline (collect → hydrate → infer → rerank)
# ---------------------------------------------------------------------------


def hydrate_pipeline(
    results: List[Dict[str, Any]],
    query: str,
    conn: Optional[sqlite3.Connection] = None,
) -> List[Dict[str, Any]]:
    """Run the full hydration pipeline on a list of retrieval results.

    Stage 1: collect event_ids from vector hits.
    Stage 2: hydrate_event_ids() in one batch SQL.
    Stage 3: hydrate_vector_results() attaches snippet/title/metadata.
    Stage 4: infer_metadata() sets flags for rank modifiers.
    Stage 5: apply_rank_modifiers() updates fused_score + rank_reasons.

    Pure function — mutates the result dicts in place and returns
    the list. Caller is responsible for sorting the final list
    (which is just `sorted(results, key=lambda r: r['fused_score'], reverse=True)`).

    Args:
        results: A list of result dicts, possibly including vector hits
                 (each must have `event_id` set). Non-vector results are
                 passed through inference + modifier stages untouched
                 on the hydration fields.
        query:   The original query string (used for inference + modifiers).
        conn:    An open sqlite3 connection. If None, opens a fresh
                 connection to ichor.db (slow path; prefer to pass one in).

    Returns:
        The same list (modified + returned for chaining).
    """
    own_conn = False
    if conn is None:
        conn = sqlite3.connect(str(Path.home() / ".hermes" / "ichor.db"))
        conn.row_factory = sqlite3.Row
        own_conn = True
    try:
        # Stage 1+2: collect vector event_ids, hydrate them in one batch.
        vector_event_ids: List[int] = [
            r["event_id"] for r in results
            if r.get("backend") == "vector" and r.get("event_id") is not None
        ]
        lookup = hydrate_event_ids(conn, vector_event_ids)

        # Stage 3: hydrate vector results in place.
        vector_hits = [r for r in results if r.get("backend") == "vector"]
        hydrate_vector_results(vector_hits, lookup)

        # Stage 4: metadata inference for every result.
        for r in results:
            infer_metadata(r, query)

        # Stage 5: apply rank modifiers.
        apply_rank_modifiers(results, query)

        return results
    finally:
        if own_conn:
            conn.close()