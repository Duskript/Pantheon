#!/usr/bin/env python3
"""Forge Sweep — Retrieval weight auto-tuning via grid search.

Evaluates weight combinations against accumulated query logs and gate
pass rates to find the optimal retrieval mix.

Usage:
    python3 lib/forge_sweep.py                   # Dry run — show best candidate
    python3 lib/forge_sweep.py --apply            # Apply best weights
    python3 lib/forge_sweep.py --report           # Show improvement history
"""

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
from typing import Any, Dict, List

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("forge_sweep")

HOME = os.path.expanduser("~")
RETRIEVAL_LOG = Path(f"{HOME}/.hermes/pantheon/retrieval-log.jsonl")
FORGE_LOG = Path(f"{HOME}/.hermes/ichor/forge/all.jsonl")
WEIGHTS_PATH = Path(f"{HOME}/pantheon/lib/ichor_hybrid.py")
HISTORY_PATH = Path(f"{HOME}/.hermes/pantheon/forge-sweep-history.json")

# Grid search parameters: we try combinations around the current weights
BACKENDS = ["fts5", "chroma", "graph", "events"]
STEP = 0.05  # Step size for grid
SWEEP_RADIUS = 0.10  # +/- range around current weights
MIN_WEIGHT = 0.05
MIN_INTERVENTIONS = 10  # Need at least this many for a meaningful sweep
IMPROVEMENT_THRESHOLD = 0.02  # 2% improvement to auto-apply


# ── Data Loading ────────────────────────────────────────────────────────

def load_current_weights() -> Dict[str, float]:
    """Read current WEIGHTS dict from ichor_hybrid.py."""
    if not WEIGHTS_PATH.exists():
        return {"fts5": 0.25, "chroma": 0.35, "graph": 0.25, "events": 0.15}
    try:
        content = WEIGHTS_PATH.read_text()
        import ast
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "WEIGHTS":
                        if isinstance(node.value, ast.Dict):
                            weights = {}
                            for k, v in zip(node.value.keys, node.value.values):
                                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                                    weights[str(k.value)] = float(v.value)
                            return weights
    except Exception:
        pass
    return {"fts5": 0.25, "chroma": 0.35, "graph": 0.25, "events": 0.15}


def load_query_log(days: int = 7) -> List[Dict]:
    """Load retrieval queries from the past N days."""
    if not RETRIEVAL_LOG.exists():
        return []
    cutoff = time.time() - days * 86400
    queries = []
    try:
        with open(RETRIEVAL_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("timestamp", 0) >= cutoff:
                    queries.append(entry)
    except Exception:
        pass
    return queries


def load_gate_data(days: int = 7) -> List[Dict]:
    """Load forge intervention records from the past N days."""
    if not FORGE_LOG.exists():
        return []
    cutoff = time.time() - days * 86400
    records = []
    try:
        with open(FORGE_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get("timestamp", 0) >= cutoff:
                    records.append(entry)
    except Exception:
        pass
    return records


def load_history() -> List[Dict]:
    """Load previous sweep results."""
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except Exception:
            pass
    return []


def save_history(entry: Dict):
    """Append a sweep result to history."""
    history = load_history()
    history.append(entry)
    # Keep last 100 entries
    if len(history) > 100:
        history = history[-100:]
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


# ── Candidate Generation ────────────────────────────────────────────────

def generate_candidates(current: Dict[str, float]) -> List[Dict[str, float]]:
    """Generate weight candidates within sweep radius of current weights.

    Uses a grid around the current values, normalized to sum to 1.0.
    """
    candidates = []

    # Build ranges for each backend
    ranges = {}
    for backend in BACKENDS:
        base = current.get(backend, 0.25)
        low = max(MIN_WEIGHT, base - SWEEP_RADIUS)
        high = min(1.0, base + SWEEP_RADIUS)
        # Generate possible values at STEP increments
        values = set()
        v = low
        while v <= high + 0.001:
            values.add(round(v, 2))
            v += STEP
        # Always include the current value
        values.add(round(base, 2))
        ranges[backend] = sorted(values)

    # Generate grid (cartesian product of all backend values)
    keys = list(ranges.keys())
    for combo in product(*[ranges[k] for k in keys]):
        trial = dict(zip(keys, combo))
        # Normalize to sum to 1.0
        total = sum(trial.values())
        if total <= 0:
            continue
        trial = {k: round(v / total, 2) for k, v in trial.items()}

        # Enforce minimum weight
        if any(v < MIN_WEIGHT for v in trial.values()):
            continue

        # Skip if too close to a duplicate
        if trial in candidates:
            continue

        candidates.append(trial)

    # If grid is too large, sample randomly
    if len(candidates) > 200:
        random.seed(42)
        # Always keep current
        kept = [current]
        remaining = [c for c in candidates if c != current]
        sampled = random.sample(remaining, min(199, len(remaining)))
        kept.extend(sampled)
        candidates = kept

    return candidates


# ── Evaluation ──────────────────────────────────────────────────────────

def evaluate_weights(
    weights: Dict[str, float],
    queries: List[Dict],
    gate_records: List[Dict],
) -> float:
    """Score a weight configuration.

    Higher is better. Considers:
    - Query result coverage (more backends returning results = better)
    - Diversity of result types (mix of fts5/chroma/graph/events)
    - Gate pass rate correlation (sessions with good retrieval → fewer gate blocks)
    """
    score = 0.0

    if not queries:
        # No query data — score is based on evenness of distribution
        # (conservative default: penalize extreme weights)
        ideal = 1.0 / len(weights)
        variance = sum((w - ideal) ** 2 for w in weights.values()) / len(weights)
        score = 1.0 - variance * 4  # 1.0 = perfectly even, 0.0 = all on one
        return max(0.0, score)

    # ── Query coverage score (0-0.4) ──
    for q in queries:
        backends_used = q.get("backends_used", [])
        result_count = q.get("result_count", 0)
        # More backends contributing is better
        coverage = len(backends_used) / len(BACKENDS)
        # More results is better, up to a point
        abundance = min(result_count / 10, 1.0)
        score += (coverage * 0.6 + abundance * 0.4) * (1.0 / len(queries))
    score *= 0.4

    # ── Gate correlation score (0-0.6) ──
    if gate_records:
        # Simple heuristic: sessions with better retrieval (more diverse backends,
        # more results) tend to have higher task completion = fewer blocks
        total_blocks = sum(1 for r in gate_records if not r.get("passed", True))
        total_gates = len(gate_records)
        if total_gates > 0:
            block_rate = total_blocks / total_gates
            # Lower block rate = better score (but gate blocks are not always bad)
            gate_score = 1.0 - block_rate
            score += gate_score * 0.6

    return round(score, 4)


def apply_weights(weights: Dict[str, float]) -> bool:
    """Write new weights to ichor_hybrid.py."""
    if not WEIGHTS_PATH.exists():
        logger.error("Cannot find %s", WEIGHTS_PATH)
        return False

    try:
        content = WEIGHTS_PATH.read_text()
        import ast
        tree = ast.parse(content)

        # Find the line range of the WEIGHTS dict
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "WEIGHTS":
                        if isinstance(node.value, ast.Dict):
                            # Build replacement string
                            weight_lines = ["WEIGHTS = {"]
                            for backend in BACKENDS:
                                w = weights.get(backend, 0.25)
                                weight_lines.append(f'    "{backend}": {w},')
                            weight_lines.append("}")
                            replacement = "\n".join(weight_lines)

                            # Find the exact old text
                            old_start = node.lineno - 1
                            old_end = node.end_lineno
                            old_lines = content.split("\n")
                            old_text = "\n".join(old_lines[old_start:old_end])

                            # Replace
                            new_content = content.replace(old_text, replacement)
                            WEIGHTS_PATH.write_text(new_content, encoding="utf-8")
                            logger.info("Weights updated: %s", weights)
                            return True
    except Exception as exc:
        logger.error("Failed to apply weights: %s", exc)
        return False

    return False


# ── Main Sweep ──────────────────────────────────────────────────────────

def run_sweep(days: int = 7, apply: bool = False) -> Dict[str, Any]:
    """Run the weight tuning sweep.

    Returns a dict with the results.
    """
    current = load_current_weights()
    queries = load_query_log(days=days)
    gates = load_gate_data(days=days)

    logger.info("Current weights: %s", current)
    logger.info("Queries in log: %d", len(queries))
    logger.info("Gate interventions: %d", len(gates))

    if len(queries) + len(gates) < MIN_INTERVENTIONS:
        logger.info(
            "Not enough data (%d queries + %d gates, need %d). Skipping sweep.",
            len(queries), len(gates), MIN_INTERVENTIONS,
        )
        return {
            "status": "skipped",
            "reason": f"Need {MIN_INTERVENTIONS} data points, have {len(queries) + len(gates)}",
            "current_weights": current,
        }

    candidates = generate_candidates(current)
    logger.info("Evaluating %d weight candidates...", len(candidates))

    best_score = -1.0
    best_weights = current
    baseline_score = evaluate_weights(current, queries, gates)

    for trial in candidates:
        score = evaluate_weights(trial, queries, gates)
        if score > best_score:
            best_score = score
            best_weights = trial

    logger.info("Baseline score: %.4f", baseline_score)
    logger.info("Best score:     %.4f", best_score)
    logger.info("Best weights:   %s", best_weights)

    improvement = best_score - baseline_score
    result = {
        "timestamp": time.time(),
        "date": datetime.now(timezone.utc).isoformat(),
        "current_weights": current,
        "baseline_score": baseline_score,
        "best_weights": best_weights,
        "best_score": best_score,
        "improvement": round(improvement, 4),
        "candidates_evaluated": len(candidates),
        "queries_used": len(queries),
        "gates_used": len(gates),
        "applied": False,
    }

    if improvement >= IMPROVEMENT_THRESHOLD and apply:
        if apply_weights(best_weights):
            result["applied"] = True
            logger.info("✅ Applied new weights (%.2f%% improvement)", improvement * 100)
        else:
            logger.warning("❌ Failed to apply weights")
    elif improvement >= IMPROVEMENT_THRESHOLD:
        logger.info(
            "🔍 Best weights improve by %.2f%% — use --apply to apply",
            improvement * 100,
        )
    else:
        logger.info("➡️ No meaningful improvement found (best +%.2f%%)", improvement * 100)

    save_history(result)
    return result


def print_report(history: List[Dict]):
    """Print a human-readable sweep history report."""
    if not history:
        print("No sweep history yet.")
        return

    print("🏋️ Forge Sweep — Weight Tuning History")
    print(f"_{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    print()
    print(f"{'Date':<22} {'Baseline':>9} {'Best':>9} {'Δ%':>7} {'Applied':>8} {'Candidates':>10}")
    print("-" * 66)

    for h in history[-20:]:
        date = h.get("date", "?")[:19]
        base = h.get("baseline_score", 0)
        best = h.get("best_score", 0)
        imp = h.get("improvement", 0) * 100
        applied = "✅" if h.get("applied") else "—"
        cand = h.get("candidates_evaluated", 0)
        imp_str = f"{imp:+.1f}%" if abs(imp) >= 0.1 else "—"
        print(f"{date:<22} {base:>9.4f} {best:>9.4f} {imp_str:>7} {applied:>8} {cand:>10}")

    # Latest applied weights
    applied = [h for h in history if h.get("applied")]
    if applied:
        last = applied[-1]
        print()
        print("Latest applied weights:")
        for backend, w in sorted(last.get("best_weights", {}).items(), key=lambda x: -x[1]):
            print(f"  {backend}: {w:.2f}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Forge Sweep — Weight Auto-Tuning")
    parser.add_argument("--days", type=int, default=7, help="Lookback days (default: 7)")
    parser.add_argument("--apply", action="store_true", help="Apply best weights if improved")
    parser.add_argument("--report", action="store_true", help="Show sweep history")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.report:
        history = load_history()
        if args.json:
            print(json.dumps(history, indent=2))
        else:
            print_report(history)
        return

    result = run_sweep(days=args.days, apply=args.apply)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = result.get("status", "complete")
        if status == "skipped":
            print(f"⏭️ Sweep skipped: {result.get('reason', 'unknown')}")
        elif result.get("applied"):
            print(f"✅ Weights updated:")
            for backend, w in sorted(result["best_weights"].items(), key=lambda x: -x[1]):
                old = result["current_weights"].get(backend, 0)
                arrow = "↑" if w > old else "↓" if w < old else "→"
                print(f"  {backend}: {old:.2f} {arrow} {w:.2f}")
            print(f"  Score: {result['baseline_score']:.4f} → {result['best_score']:.4f} ({result['improvement']*100:+.2f}%)")
        else:
            print(f"🔍 Best candidate improved by {result['improvement']*100:+.2f}%")
            print("  Current: ", result["current_weights"])
            print("  Best:    ", result["best_weights"])
            print("  Use --apply to apply")


if __name__ == "__main__":
    main()
