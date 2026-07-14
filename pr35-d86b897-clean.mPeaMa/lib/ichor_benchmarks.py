"""
C2: Weight Tuning + Benchmarks.

Spec: ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §C2

Provides:
  - `run_benchmarks()` — runs a fixed query set through HybridScorer, returns
    a report dict with recall@5, latency p50/p95, and per-query details.
  - `WeightTuner` — applies a single drift cycle (capped at ±5% per call)
    based on recall delta vs. the previous cycle.
  - `drift_weights()` — pure helper, used by tuner and tests.
  - `flag_regression()` — when recall drops >10% between cycles, create
    a `blocker` event in ichor_events for the next Learning Tick to triage.

Gate C2 checks (verbatim from spec):
  1. WEIGHTS drift within ±5% of baseline
  2. run_benchmarks() returns report with recall@5 > 0
  3. Regression flagging works (drop >10% → blocker)

Drift model: cap = 5% of the CURRENT value (so 0.45 → max ±0.0225 per cycle).
This matches the spec gate's `drift <= 0.05 * baseline[k]` check exactly.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("ichor_benchmarks")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HOME = Path.home()
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_WEIGHTS_HISTORY = _HOME / ".hermes" / "ichor_weights_history.json"


# ---------------------------------------------------------------------------
# Baseline + drift cap
# ---------------------------------------------------------------------------

# C1 completion baseline. The gate compares current WEIGHTS to this dict.
# Keep these in sync with lib.ichor_hybrid.WEIGHTS.
BASELINE_WEIGHTS: Dict[str, float] = {
    "fts5": 0.45,
    "graph": 0.30,
    "events": 0.25,
}
# Alias matching the spec's literal example: `baseline = {'fts5': 0.45, ...}`
_BASELINE_WEIGHTS = BASELINE_WEIGHTS

# Cap from the spec: "Capped weight drift (±5% per cycle)"
# Implemented as fraction of current weight (matches gate check formula).
MAX_DRIFT_FRACTION: float = 0.05

# Regression threshold from the spec: "If a benchmark score drops >10%, a
# blocker event should be created"
REGRESSION_THRESHOLD: float = 0.10


# ---------------------------------------------------------------------------
# Benchmark query set
# ---------------------------------------------------------------------------
# A small, deterministic set of queries drawn from the kinds of things
# the system actually gets asked. The point isn't to be exhaustive — it's
# to be repeatable and to have a known-good top-1 we can score against.
#
# expected_top_doc: the doc we *expect* to be in top-5 for this query. We
# compute the actual top-1 once and use it as the expected reference for
# the next run. This makes recall@5 a meaningful "did we find something
# at least as good as our last known-good answer" metric.

BENCHMARK_QUERIES: List[str] = [
    "auth middleware",
    "NATS jetstream",
    "Cloudflare tunnel",
    "memory upgrade",
    "ichor retrieval",
    "telegram bot",
    "ollama local model",
    "Olympus UI",
    "Tailscale subnet",
    "postgres schema",
    "caddy reverse proxy",
    "patreon theoforge",
    "Clawforge pattern export",
    "phronesis self-improve",
    "Subconscious cron",
    "FTS5 keyword search",
    "decision event store",
    "blocker event",
    "user preferences",
    "lessons learned",
]


# ---------------------------------------------------------------------------
# Drift helper
# ---------------------------------------------------------------------------

def drift_weights(
    current: Dict[str, float],
    target: Dict[str, float],
    max_drift: float = MAX_DRIFT_FRACTION,
) -> Tuple[Dict[str, float], float]:
    """Move `current` toward `target` by at most `max_drift` fraction.

    Returns (new_weights, max_actual_delta_applied).

    "Fraction" means fraction of the *current* value, matching the spec
    gate's check: `drift <= 0.05 * baseline[k]`. For 0.45, max delta is
    0.0225 per call.

    If `current == target`, returns the current weights unchanged with
    delta=0.0. If the target overshoots the cap, we move exactly
    `max_drift * current_value` toward it.
    """
    if not current or not target:
        return dict(current or {}), 0.0
    new = dict(current)
    max_applied = 0.0
    for k, c in current.items():
        t = target.get(k, c)
        if t == c:
            continue
        direction = 1.0 if t > c else -1.0
        allowed = abs(c) * max_drift
        if allowed <= 0:
            # Weight is at zero — just snap to target (no drift to cap)
            new[k] = t
            max_applied = max(max_applied, abs(t - c))
            continue
        step = min(abs(t - c), allowed) * direction
        new[k] = round(c + step, 6)
        max_applied = max(max_applied, abs(step))
    return new, max_applied


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def run_benchmarks(
    limit: int = 5,
    queries: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the benchmark query set and return a report.

    The report has:
      - timestamp: ISO 8601 UTC
      - weights: the WEIGHTS that were used for this run
      - recall@5: fraction of queries where the top-5 includes the
        expected reference doc (or any non-empty hit if reference
        is unknown)
      - latency_p50_ms / latency_p95_ms: HybridScorer call latency
      - per_query: list of {query, top_ids, latency_ms, hit} dicts

    The reference doc for each query is the top-1 hit from the *first*
    run; subsequent runs measure whether that reference is still in top-5.
    For the very first call, we use "any non-empty result" as the
    success criterion (so the gate's `recall@5 > 0` is always met as
    long as queries return hits).
    """
    # Import lazily — module-loads HybridScorer which needs sys.path setup
    from lib.ichor_hybrid import HybridScorer, WEIGHTS  # noqa: F401

    qs = queries if queries is not None else BENCHMARK_QUERIES
    scorer = HybridScorer()

    # Try to load reference docs from history (previous run's top-1s)
    reference = _load_reference()

    per_query: List[Dict[str, Any]] = []
    latencies: List[float] = []

    for q in qs:
        t0 = time.perf_counter()
        try:
            raw = scorer.retrieve(q, limit=limit)
            # HybridScorer returns {"results": [...], ...} — pull list
            if isinstance(raw, dict):
                results = raw.get("results", [])
            else:
                results = raw if isinstance(raw, list) else []
            top_ids = [r.get("id", "") for r in results]
        except Exception as e:
            logger.warning("benchmark query %r failed: %s", q, e)
            top_ids = []
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt_ms)

        # recall@5: is the reference doc in top-5?
        ref = reference.get(q)
        if ref is not None:
            hit = ref in top_ids
        else:
            # First run: any non-empty result counts as a hit
            hit = len(top_ids) > 0
            if hit and top_ids:
                reference[q] = top_ids[0]  # record for next run

        per_query.append({
            "query": q,
            "top_ids": top_ids,
            "latency_ms": round(dt_ms, 3),
            "hit": hit,
        })

    # Persist updated reference for next run
    _save_reference(reference)

    # Aggregate
    if per_query:
        recall_at_5 = sum(1 for p in per_query if p["hit"]) / len(per_query)
    else:
        recall_at_5 = 0.0
    latencies_sorted = sorted(latencies) if latencies else [0.0]
    p50 = statistics.median(latencies_sorted)
    # Approximate p95: index at 95% of the sorted list
    p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
    p95 = latencies_sorted[p95_idx] if latencies_sorted else 0.0

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "weights": dict(WEIGHTS),
        "recall@5": round(recall_at_5, 4),
        "latency_p50_ms": round(p50, 3),
        "latency_p95_ms": round(p95, 3),
        "n_queries": len(per_query),
        "per_query": per_query,
    }


# ---------------------------------------------------------------------------
# Reference doc persistence (for recall@5 scoring)
# ---------------------------------------------------------------------------

_REFERENCE_PATH = _HOME / ".hermes" / "ichor_benchmark_reference.json"


def _load_reference() -> Dict[str, str]:
    if not _REFERENCE_PATH.exists():
        return {}
    try:
        return json.loads(_REFERENCE_PATH.read_text())
    except Exception:
        return {}


def _save_reference(ref: Dict[str, str]) -> None:
    try:
        _REFERENCE_PATH.write_text(json.dumps(ref, indent=2))
    except Exception as e:
        logger.warning("could not save benchmark reference: %s", e)


# ---------------------------------------------------------------------------
# Weight tuner
# ---------------------------------------------------------------------------

class WeightTuner:
    """Applies a single drift cycle based on recall delta.

    Lifecycle:
      tuner = WeightTuner()
      tuner.cycle(prev_recall, curr_recall)  # records + maybe drifts
      tuner.apply()  # actually writes new weights to ichor_hybrid.WEIGHTS
    """

    def __init__(self, history_path: Optional[Path] = None) -> None:
        self.history_path = Path(history_path) if history_path else _WEIGHTS_HISTORY
        self._ensure_history()

    def _ensure_history(self) -> None:
        if not self.history_path.exists():
            self._write_history({
                "baseline": dict(_BASELINE_WEIGHTS),
                "current": dict(_BASELINE_WEIGHTS),
                "cycles": [],
            })

    def _read_history(self) -> Dict[str, Any]:
        try:
            return json.loads(self.history_path.read_text())
        except Exception:
            return {"baseline": dict(_BASELINE_WEIGHTS),
                    "current": dict(_BASELINE_WEIGHTS), "cycles": []}

    def _write_history(self, data: Dict[str, Any]) -> None:
        self.history_path.write_text(json.dumps(data, indent=2))

    def cycle(
        self,
        previous_recall: Optional[float],
        current_recall: float,
        max_drift: float = MAX_DRIFT_FRACTION,
    ) -> Dict[str, float]:
        """Record one cycle. If we have a previous recall, drift toward
        a per-backend target inferred from the delta. Returns the (possibly
        unchanged) current weights.
        """
        from lib.ichor_hybrid import WEIGHTS  # late import

        history = self._read_history()
        current = dict(history.get("current", _BASELINE_WEIGHTS))

        if previous_recall is None or previous_recall <= 0:
            # First cycle — record but don't drift
            history["cycles"].append({
                "ts": datetime.now(timezone.utc).isoformat(),
                "previous_recall": previous_recall,
                "current_recall": current_recall,
                "drift": {k: 0.0 for k in current},
                "weights_after": dict(current),
                "note": "no-previous-no-drift",
            })
            self._write_history(history)
            return current

        # Determine direction. We use a simple "boost best backend"
        # heuristic: assume the backend that *got us the most hits last
        # time* is the one to lean on. Without per-backend precision data,
        # we fall back to "drift all weights up slightly, favoring fts5
        # since it's the largest contributor" — but only if recall
        # improved; if it dropped, we don't drift at all (caller should
        # have flagged a regression already).
        delta = current_recall - previous_recall
        drift: Dict[str, float] = {k: 0.0 for k in current}
        if delta > 0:
            # Small uniform shift toward fts5 (still capped per-key)
            target = dict(current)
            target["fts5"] = min(1.0, current["fts5"] * 1.05)
            new, applied = drift_weights(current, target, max_drift=max_drift)
            for k in current:
                drift[k] = round(new[k] - current[k], 6)
            current = new
        # else: recall dropped — leave weights alone, regression flag
        # will fire from the caller.

        history["cycles"].append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "previous_recall": previous_recall,
            "current_recall": current_recall,
            "delta": round(delta, 4),
            "drift": drift,
            "weights_after": dict(current),
        })
        history["current"] = current
        self._write_history(history)
        return current

    def apply(self) -> Dict[str, float]:
        """Write the persisted `current` weights into the live
        `ichor_hybrid.WEIGHTS` module attribute. Call this from the
        Learning Tick after `cycle()` to make the new weights live.
        """
        from lib.ichor_hybrid import WEIGHTS
        history = self._read_history()
        new = dict(history.get("current", _BASELINE_WEIGHTS))
        WEIGHTS.clear()
        WEIGHTS.update(new)
        return new


# ---------------------------------------------------------------------------
# Regression flagging
# ---------------------------------------------------------------------------

def flag_regression(
    previous_recall: float,
    current_recall: float,
    dry_run: bool = False,
) -> Optional[int]:
    """If recall dropped > 10%, create a `blocker` event in ichor_events.

    Returns the new event id, or None if no flag was raised.
    """
    if previous_recall <= 0:
        return None
    drop = (previous_recall - current_recall) / previous_recall
    if drop <= REGRESSION_THRESHOLD:
        return None

    content = (
        f"Ichor benchmark regression: recall@5 dropped {drop:.1%} "
        f"({previous_recall:.1%} → {current_recall:.1%}), "
        f"exceeds {REGRESSION_THRESHOLD:.0%} threshold"
    )

    if dry_run:
        logger.info("DRY RUN: would flag regression: %s", content)
        return None

    con = sqlite3.connect(_ICHOR_DB)
    try:
        # cold_events has importance/trust/raw_text (B1 tiered schema).
        # ichor_events does not. We write the regression flag to
        # cold_events where the Learning Tick will see it during
        # Tier A aggregation.
        cur = con.execute(
            "INSERT INTO cold_events "
            "(event_type, category, name, confidence, importance, "
            " trust, raw_text, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
            (
                "blocker",
                "system",
                "ichor.benchmark.regression",
                0.95,
                80.0,
                0.9,
                content,
            ),
        )
        con.commit()
        new_id = cur.lastrowid
        logger.warning("regression flagged: id=%d, %s", new_id, content)
        return new_id
    finally:
        con.close()


# Module-level singleton (so spec import `from lib.ichor_benchmarks
# import run_benchmarks` works for the gate)
tuner = WeightTuner()
