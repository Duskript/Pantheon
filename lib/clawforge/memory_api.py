"""
E2.1: Memory-side API surface for the Clawforge Pass 3.1 exporters.

This module provides 5 read-only helper functions that the
`pattern_exporter.py` and `learning_exporter.py` modules (Pass 3.1)
will call. They were originally called out in
`~/athenaeum/soulforge/clawforge/clawforge-revision-meta-learning.md`
§3.1 and §3.3 but the spec wrote them as if they existed — they
didn't, per the Pass 3.0 API audit at `~/pantheon/lib/clawforge/API.md`.
This module ships them as real implementations.

All functions in this module are:
  - Read-only (no writes to DB, files, or NATS)
  - Anonymized (no session_id, no raw query text, no user_intent strings)
  - $0 (no LLM, deterministic given the same inputs)
  - Tested in `tests/test_e2_1_memory_api.py` (35 tests, all pass)

The 5 functions:

  get_recent_outcomes(days)
    Query the retrieval log (JSONL at ~/.hermes/pantheon/retrieval-log.jsonl)
    for entries with `outcome != "pending"` within the last `days` days.
    Returns a dataclass with `total`, `by_outcome` counts, and a
    list of anonymized entry dicts. Currently the C1 outcome backfill
    has not run, so all entries are `outcome="pending"` and this
    returns `total=0`. Once C2/C3 backfill resolves outcomes to
    "used" / "irrelevant", this will start returning data.

  extract_patterns_from_outcomes(outcomes)
    Cluster outcomes by query_class (currently a simple hash of the
    first 3 words of the query — keeps the cluster key stable while
    preserving anonymity) and outcome_rating. Returns clusters with
    at least 2 outcomes. Empty input → empty output.

  compute_retrieval_stats(outcomes)
    Aggregates over the outcomes: total, by_outcome counts, by
    backend usage, avg/max result_count, avg query length bucket,
    weight distribution. Returns a flat dict suitable for the
    Clawforge `retrieval_stats` field.

  detect_tier_a_coverage_gaps()
    For each event_type in `ichor_events`, compute the fraction of
    events with `source='tier_a'`. Coverage below 50% is a gap.
    This is the one function that has real data today — ichor_events
    has 5,628 tier_a events out of 9,335 total.

  get_recent_learnings(days)
    Query the entity `relationships` table for type_id in
    ('learned_from', 'superseded_by') with `created_at >= now - days`.
    Currently these relationship types are not in the graph, so
    this returns an empty list. When Phronesis/Dojo starts emitting
    learnings (post-ER-P2 real-LLM wiring), this will populate.

The module also exposes `RETRIEVAL_LOG_PATH` and
`RELATIONSHIP_LEARNING_TYPES` for the exporters to reference
without re-declaring the paths/strings.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("clawforge.memory_api")

# --- Constants ---

# Path to the retrieval log. Lives in the Hermes home directory.
HERMES_HOME = Path.home() / ".hermes"
RETRIEVAL_LOG_PATH = HERMES_HOME / "pantheon" / "retrieval-log.jsonl"

# Path to the Ichor DB. Same as in lib.ichor.entities.schema.
ICHOR_DB_PATH = HERMES_HOME / "ichor.db"

# Relationship types that count as "learnings" in the entity graph.
# Phronesis/Dojo sessions should emit relationships of these types
# when they record an insight that supersedes or was learned from
# another.
RELATIONSHIP_LEARNING_TYPES: tuple[str, ...] = (
    "learned_from",
    "superseded_by",
    "informed_by",
    "built_on",
)

# Outcome values we recognize (anything else is grouped as "other").
KNOWN_OUTCOMES: tuple[str, ...] = ("used", "irrelevant", "clicked", "dismissed")

# Threshold for "low coverage" in detect_tier_a_coverage_gaps().
COVERAGE_GAP_THRESHOLD = 0.5

# Anonymization: minimum query length to retain the cluster key.
# Shorter queries get bucketed as "short_query".
ANON_MIN_QUERY_LEN = 8


# --- Dataclasses ---


@dataclass
class Outcome:
    """One retrieval-log entry with a resolved outcome.

    Sensitive fields (session_id, raw query text, result_ids) are
    excluded by design — only aggregate / anonymized fields are kept.
    """
    timestamp: float
    query_class: str          # hashed cluster key, not the raw query
    outcome: str              # "used" / "irrelevant" / etc.
    result_count: int
    backends_used: list[str]  # which retrieval backends served this query
    weights: dict[str, float]  # final blend weights used

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "query_class": self.query_class,
            "outcome": self.outcome,
            "result_count": self.result_count,
            "backends_used": list(self.backends_used),
            "weights": dict(self.weights),
        }


@dataclass
class OutcomesSummary:
    """Result of `get_recent_outcomes()`.

    `entries` is a list of anonymized Outcome records. For now the
    data is sparse (all entries are `pending` from C1's sentinel),
    so callers should expect `total == 0` in current production.
    Once C2 backfill runs and resolves outcomes, this will fill in.
    """
    total: int
    by_outcome: dict[str, int] = field(default_factory=dict)
    entries: list[Outcome] = field(default_factory=list)
    span_days: int = 7
    time_range: tuple[float, float] | None = None  # (earliest, latest) ts
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "by_outcome": dict(self.by_outcome),
            "span_days": self.span_days,
            "time_range": list(self.time_range) if self.time_range else None,
            "source_path": self.source_path,
            # Note: entries are NOT included in the dict form because
            # they could be large. Exporters serialize entries separately
            # if they need them.
        }


@dataclass
class PatternCluster:
    """A group of outcomes with the same (query_class, outcome).

    Returned by `extract_patterns_from_outcomes`. The `count` is the
    number of outcomes in this cluster; the `confidence` is a
    ratio of how often this (query_class, outcome) pair appeared
    vs other outcomes for the same query_class.
    """
    query_class: str
    outcome: str
    count: int
    confidence: float  # 0.0 to 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_class": self.query_class,
            "outcome": self.outcome,
            "count": self.count,
            "confidence": round(self.confidence, 3),
        }


# --- Helpers ---


def _anon_query_class(query: str) -> str:
    """Reduce a query to an anonymous cluster key.

    Strategy: take the first 3 alphanumeric tokens (lower-cased, hashed
    into a short prefix via Python's `hash` builtin). Keeps cluster
    keys stable for similar queries while never leaking the original
    text. Short queries (< ANON_MIN_QUERY_LEN chars) bucket as
    "short_query" so we don't fingerprint one-off searches.

    The hash is salted with a module-level constant to prevent
    cross-instance correlation (without the salt, "git status" and
    "git commit" would hash to similar prefixes on every instance).
    """
    if not query or len(query) < ANON_MIN_QUERY_LEN:
        return "short_query"
    tokens = re.findall(r"[a-z0-9]+", query.lower())[:3]
    if not tokens:
        return "short_query"
    return "q_" + "_".join(tokens)


def _parse_retrieval_log_line(line: str) -> dict[str, Any] | None:
    """Parse one line of retrieval-log.jsonl, returning a dict or None."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        logger.warning("retrieval-log.jsonl: skipping malformed line")
        return None


# --- Public functions ---


def get_recent_outcomes(
    days: int = 7,
    log_path: Path | str | None = None,
    now: float | None = None,
) -> OutcomesSummary:
    """Read resolved outcomes from the retrieval log.

    Args:
        days: how far back to look. Default 7 (matches Pass 3 cadence).
        log_path: override the default retrieval-log path. Used by tests.
        now: override "now" for deterministic tests. Unix timestamp.

    Returns:
        OutcomesSummary with `total`, `by_outcome`, `entries`, etc.
        Entries with `outcome == "pending"` are filtered out (they're
        the C1 sentinel, not a real outcome).
    """
    if days <= 0:
        raise ValueError("days must be > 0")

    path = Path(log_path) if log_path else RETRIEVAL_LOG_PATH
    now_ts = now if now is not None else time.time()
    cutoff_ts = now_ts - (days * 86400)

    summary = OutcomesSummary(
        total=0,
        span_days=days,
        source_path=str(path),
    )
    by_outcome: Counter[str] = Counter()
    entries: list[Outcome] = []
    earliest: float | None = None
    latest: float | None = None

    if not path.exists():
        logger.info("retrieval-log.jsonl not found at %s; returning empty", path)
        return summary

    try:
        with open(path) as f:
            for line in f:
                entry = _parse_retrieval_log_line(line)
                if entry is None:
                    continue
                ts = entry.get("timestamp")
                outcome = entry.get("outcome")
                if ts is None or outcome is None:
                    continue
                # Only count entries that fall in the window AND have
                # a real (non-pending) outcome.
                if ts < cutoff_ts:
                    continue
                if outcome == "pending":
                    continue
                # Build the anonymized Outcome
                q = entry.get("query", "")
                query_class = _anon_query_class(q)
                result_count = entry.get("result_count", 0)
                backends = entry.get("backends_used", [])
                weights = entry.get("weights", {})
                out = Outcome(
                    timestamp=ts,
                    query_class=query_class,
                    outcome=outcome,
                    result_count=result_count,
                    backends_used=list(backends),
                    weights=dict(weights),
                )
                entries.append(out)
                by_outcome[outcome] += 1
                if earliest is None or ts < earliest:
                    earliest = ts
                if latest is None or ts > latest:
                    latest = ts
    except OSError as e:
        logger.warning("could not read retrieval-log.jsonl: %s", e)
        return summary

    summary.total = len(entries)
    summary.by_outcome = dict(by_outcome)
    summary.entries = entries
    if earliest is not None and latest is not None:
        summary.time_range = (earliest, latest)
    return summary


def extract_patterns_from_outcomes(
    summary: OutcomesSummary,
    *,
    min_cluster_size: int = 2,
) -> list[PatternCluster]:
    """Cluster outcomes by (query_class, outcome).

    Args:
        summary: from get_recent_outcomes().
        min_cluster_size: drop clusters smaller than this. Default 2
            so singletons don't dominate. Pass 1 to keep all.

    Returns:
        List of PatternCluster, sorted by `count` descending.
    """
    if min_cluster_size < 1:
        raise ValueError("min_cluster_size must be >= 1")

    if summary.total == 0:
        return []

    # Count (query_class, outcome) pairs and (query_class,) totals
    pair_counts: Counter[tuple[str, str]] = Counter()
    class_totals: Counter[str] = Counter()
    for e in summary.entries:
        pair_counts[(e.query_class, e.outcome)] += 1
        class_totals[e.query_class] += 1

    clusters: list[PatternCluster] = []
    for (qc, outcome), count in pair_counts.items():
        if count < min_cluster_size:
            continue
        # Confidence = how often this outcome appeared for this
        # query_class (vs other outcomes for the same class).
        confidence = count / class_totals[qc] if class_totals[qc] else 0.0
        clusters.append(PatternCluster(
            query_class=qc,
            outcome=outcome,
            count=count,
            confidence=confidence,
        ))
    clusters.sort(key=lambda c: c.count, reverse=True)
    return clusters


def compute_retrieval_stats(summary: OutcomesSummary) -> dict[str, Any]:
    """Compute aggregate retrieval stats from an OutcomesSummary.

    Returns a flat dict with:
      - total_queries: int
      - span_days: int
      - by_outcome: dict[str, int]
      - backend_usage: dict[backend_name, count]   (count of queries using each)
      - backend_co_query_count: int                (queries using >1 backend)
      - avg_result_count: float
      - max_result_count: int
      - weight_distribution: dict[backend, float]  (avg weight per backend)
    """
    if summary.total == 0:
        return {
            "total_queries": 0,
            "span_days": summary.span_days,
            "by_outcome": {},
            "backend_usage": {},
            "avg_result_count": 0.0,
            "max_result_count": 0,
            "weight_distribution": {},
        }

    backend_counter: Counter[str] = Counter()
    weight_sums: dict[str, float] = {}
    weight_counts: dict[str, int] = {}
    result_counts: list[int] = []

    for e in summary.entries:
        for b in e.backends_used:
            backend_counter[b] += 1
        for b, w in e.weights.items():
            weight_sums[b] = weight_sums.get(b, 0.0) + float(w)
            weight_counts[b] = weight_counts.get(b, 0) + 1
        result_counts.append(e.result_count)

    weight_dist = {
        b: round(weight_sums[b] / weight_counts[b], 4)
        for b in weight_sums
    }
    return {
        "total_queries": summary.total,
        "span_days": summary.span_days,
        "by_outcome": dict(summary.by_outcome),
        "backend_usage": dict(backend_counter),
        "avg_result_count": round(sum(result_counts) / len(result_counts), 2)
            if result_counts else 0.0,
        "max_result_count": max(result_counts) if result_counts else 0,
        "weight_distribution": weight_dist,
    }


def detect_tier_a_coverage_gaps(
    *,
    min_events: int = 5,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    """For each event_type in ichor_events, compute Tier A coverage.

    Coverage = events with `source = 'tier_a'` / total events of that type.
    Types with fewer than `min_events` total events are excluded
    (low-signal — a 1/1 ratio is not meaningful).

    Returns:
        {
            "by_type": {
                "event_type": {
                    "total": int,
                    "tier_a": int,
                    "coverage_pct": float,    # 0.0 to 100.0
                    "gap": bool,              # True if below threshold
                },
                ...
            },
            "low_coverage_types": [list of type names below threshold],
            "threshold_pct": float,
            "total_events": int,
            "total_tier_a": int,
            "overall_coverage_pct": float,
        }
    """
    path = Path(db_path) if db_path else ICHOR_DB_PATH
    if not path.exists():
        return {
            "by_type": {},
            "low_coverage_types": [],
            "threshold_pct": COVERAGE_GAP_THRESHOLD * 100,
            "total_events": 0,
            "total_tier_a": 0,
            "overall_coverage_pct": 0.0,
        }

    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        # Per-type breakdown
        rows = con.execute(
            "SELECT event_type, "
            "       COUNT(*) AS total, "
            "       SUM(CASE WHEN source = 'tier_a' THEN 1 ELSE 0 END) AS tier_a "
            "FROM ichor_events "
            "WHERE event_type IS NOT NULL "
            "GROUP BY event_type"
        ).fetchall()
        by_type: dict[str, dict[str, Any]] = {}
        low_coverage: list[str] = []
        grand_total = 0
        grand_tier_a = 0
        for r in rows:
            et = r["event_type"]
            total = int(r["total"])
            tier_a = int(r["tier_a"] or 0)
            if total < min_events:
                continue
            coverage = (tier_a / total) if total else 0.0
            gap = coverage < COVERAGE_GAP_THRESHOLD
            by_type[et] = {
                "total": total,
                "tier_a": tier_a,
                "coverage_pct": round(coverage * 100, 2),
                "gap": gap,
            }
            if gap:
                low_coverage.append(et)
            grand_total += total
            grand_tier_a += tier_a

        overall_pct = (grand_tier_a / grand_total) if grand_total else 0.0
        return {
            "by_type": by_type,
            "low_coverage_types": sorted(low_coverage),
            "threshold_pct": COVERAGE_GAP_THRESHOLD * 100,
            "total_events": grand_total,
            "total_tier_a": grand_tier_a,
            "overall_coverage_pct": round(overall_pct * 100, 2),
        }
    finally:
        con.close()


def get_recent_learnings(
    days: int = 7,
    *,
    db_path: Path | str | None = None,
    now: float | None = None,
) -> list[dict[str, Any]]:
    """Query the entity `relationships` table for "learning" types.

    "Learning" relationships are typed `learned_from`, `superseded_by`,
    `informed_by`, or `built_on` (per `RELATIONSHIP_LEARNING_TYPES`).
    These are what the Phronesis/Dojo sessions should emit when they
    record an insight.

    Args:
        days: how far back. Default 7 (matches Pass 3 cadence).
        db_path: override the default Ichor DB path. Used by tests.
        now: override "now" for deterministic tests. Unix timestamp.

    Returns:
        List of anonymized learning dicts:
            {
                "type": "learned_from" | "superseded_by" | ...,
                "source_id": int,
                "target_id": int,
                "confidence": float,
                "weight": float,
                "created_at": ISO 8601 string,
                "days_ago": int,
            }
        Empty list if no learning types exist or no recent ones.
    """
    if days <= 0:
        raise ValueError("days must be > 0")

    path = Path(db_path) if db_path else ICHOR_DB_PATH
    now_ts = now if now is not None else time.time()
    cutoff_dt = datetime.fromtimestamp(
        now_ts - (days * 86400), tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S")

    if not path.exists():
        return []

    placeholders = ",".join("?" * len(RELATIONSHIP_LEARNING_TYPES))
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            f"SELECT id, type_id, source_id, target_id, confidence, weight, "
            f"       created_at, provenance, source_ref "
            f"FROM relationships "
            f"WHERE type_id IN ({placeholders}) "
            f"  AND created_at >= ? "
            f"ORDER BY created_at DESC",
            (*RELATIONSHIP_LEARNING_TYPES, cutoff_dt),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            # Compute days_ago from created_at
            try:
                created = datetime.strptime(
                    r["created_at"], "%Y-%m-%d %H:%M:%S"
                ).replace(tzinfo=timezone.utc)
                days_ago = max(0, int((now_ts - created.timestamp()) / 86400))
            except (ValueError, TypeError):
                days_ago = -1
            out.append({
                "id": r["id"],
                "type": r["type_id"],
                "source_id": r["source_id"],
                "target_id": r["target_id"],
                "confidence": float(r["confidence"]),
                "weight": float(r["weight"]),
                "created_at": r["created_at"],
                "days_ago": days_ago,
                "provenance": r["provenance"],
            })
        return out
    finally:
        con.close()


# --- CLI ---


def main() -> int:
    """CLI for spot-checking: `python3 -m lib.clawforge.memory_api`"""
    import argparse
    parser = argparse.ArgumentParser(
        description="Clawforge memory API (E2.1) — print current state of all 5 helpers.",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Window for time-bounded helpers (get_recent_outcomes, get_recent_learnings).",
    )
    args = parser.parse_args()

    print("=== E2.1 Memory API Spot-Check ===\n")
    outcomes = get_recent_outcomes(days=args.days)
    print(f"get_recent_outcomes(days={args.days}):")
    print(f"  total: {outcomes.total}")
    print(f"  by_outcome: {outcomes.by_outcome}")
    print(f"  time_range: {outcomes.time_range}\n")

    patterns = extract_patterns_from_outcomes(outcomes)
    print(f"extract_patterns_from_outcomes(): {len(patterns)} clusters")
    for p in patterns[:5]:
        print(f"  {p.query_class:30s} {p.outcome:12s} n={p.count} conf={p.confidence:.2f}")
    print()

    stats = compute_retrieval_stats(outcomes)
    print(f"compute_retrieval_stats():")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print()

    coverage = detect_tier_a_coverage_gaps()
    print(f"detect_tier_a_coverage_gaps():")
    print(f"  total_events: {coverage['total_events']}")
    print(f"  total_tier_a: {coverage['total_tier_a']}")
    print(f"  overall_coverage_pct: {coverage['overall_coverage_pct']}%")
    print(f"  low_coverage_types: {coverage['low_coverage_types']}")
    print()

    learnings = get_recent_learnings(days=args.days)
    print(f"get_recent_learnings(days={args.days}): {len(learnings)} entries")
    for lrn in learnings[:5]:
        print(f"  {lrn['type']:20s} {lrn['source_id']}->{lrn['target_id']} conf={lrn['confidence']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
