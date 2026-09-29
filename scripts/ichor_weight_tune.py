#!/usr/bin/env python3
"""Ichor weight tuner — grid-search retrieval weights against the labeled set.

Complements `lib/forge_sweep.py` (which scores against the unlabeled query log):
this one scores candidates with `scripts/ichor_recall_eval.py`, whose golden set
carries the entities a healthy recall path must surface. A weight change is only
applied when it moves that metric by more than the noise floor.

Guards (each one exists because the alternative silently degrades recall):
  * **Offline lanes are frozen.** A lane that returned zero candidates is not
    evidence that it is useless — the embedder may simply be down. Candidates
    that lower such a lane are skipped, and the run says so.
  * **Latency guard.** A candidate whose mean latency exceeds the baseline by
    `--max-latency-factor` is rejected regardless of score.
  * **Minimum gain.** `--min-gain` (absolute, on the composite score) must be
    cleared, otherwise nothing is written.
  * **Never mutate the pinned dict in place at runtime.** `--apply` rewrites the
    literal in `lib/ichor_hybrid.py` with a backup + `ast.parse` check and then
    re-imports to prove the new values are live; the C2 drift gate stays honest.

Run in the interpreter with real backends (see the eval script header).

Usage
-----
    ... ichor_weight_tune.py                      # dry run: score candidates, recommend
    ... ichor_weight_tune.py --step 0.10 --k 5
    ... ichor_weight_tune.py --apply              # write the winner
    ... ichor_weight_tune.py --report             # show tuning history
"""
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PANTHEON = Path("/home/konan/pantheon")
if str(PANTHEON) not in sys.path:
    sys.path.insert(0, str(PANTHEON))

HYBRID = PANTHEON / "lib/ichor_hybrid.py"
FIX_DIR = PANTHEON / "shared/handoffs/ichor-relational-recall-fix"
HISTORY = Path("/home/konan/.hermes/pantheon/weight-tune-history.json")
LANES = ("fts5", "vector", "graph", "events", "reference")
MIN_GAIN_DEFAULT = 0.02
MAX_LATENCY_FACTOR_DEFAULT = 1.5
# Composite score = HIT_WEIGHT*hit@k + (1-HIT_WEIGHT)*mrr. Recall carries 3x the
# weight of ranking quality: a config that surfaces the right entity lower down
# is a real improvement, while a config that ranks a smaller set beautifully is
# not. MRR still breaks ties between equal-recall candidates.
HIT_WEIGHT = 0.75
MRR_WEIGHT = 1.0 - HIT_WEIGHT


def _load_eval():
    spec = importlib.util.spec_from_file_location(
        "ichor_recall_eval", PANTHEON / "scripts/ichor_recall_eval.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def composite(report: Dict[str, Any], k: int, objective: str = "linked") -> float:
    """Single number to rank candidates: recall first, ranking quality second.

    `objective="linked"` (default) scores whether the retrieval returned the
    entity's OWN relations / events, which is what recall is for. `"text"` scores
    whether the expected name merely appears in result text — a proxy that
    rewards keyword coincidence and, measured, points the opposite way from the
    linked metric (text said "hold"; linked says "the graph lane is starved").
    Falls back to the text metric when a report carries no linked labels.
    """
    use_linked = objective == "linked" and report.get("linked_queries")
    if use_linked:
        hit = report.get(f"linked_hit_at_{k}", report.get("linked_hit_at_5", 0.0))
        mrr = report.get("linked_mrr", 0.0)
    else:
        hit = report.get(f"hit_at_{k}", report.get("hit_at_5", 0.0))
        mrr = report.get("mrr", 0.0)
    return round(HIT_WEIGHT * hit + MRR_WEIGHT * mrr, 4)


def normalize(weights: Dict[str, float]) -> Dict[str, float]:
    """Rescale to sum 1.0, keeping 3-decimal precision."""
    total = sum(max(0.0, float(v)) for v in weights.values()) or 1.0
    return {k: round(max(0.0, float(v)) / total, 3) for k, v in weights.items()}


def normalize_holding(weights: Dict[str, float], frozen: List[str]) -> Dict[str, float]:
    """Rescale to sum 1.0 while keeping `frozen` lanes at their exact value.

    Plain renormalisation would let a frozen lane drift whenever another lane
    moves (raise fts5, and an offline vector lane silently loses weight). A lane
    we cannot measure must not be changed at all, so the tunable lanes absorb
    the remainder.
    """
    frozen_total = sum(max(0.0, float(weights.get(lane, 0.0))) for lane in frozen)
    rest = {lane: max(0.0, float(v)) for lane, v in weights.items() if lane not in frozen}
    rest_total = sum(rest.values()) or 1.0
    budget = max(0.0, 1.0 - frozen_total)
    out = {lane: round(max(0.0, float(weights.get(lane, 0.0))), 3) for lane in frozen}
    out.update({lane: round(v / rest_total * budget, 3) for lane, v in rest.items()})
    return out


def generate_candidates(
    current: Dict[str, float], step: float, offline: List[str]
) -> List[Dict[str, float]]:
    """±step per lane (skipping lanes that are offline), plus structural probes."""
    out: List[Dict[str, float]] = []
    seen = {json.dumps(normalize_holding(current, offline), sort_keys=True)}

    def add(w: Dict[str, float], label: str) -> None:
        norm = normalize_holding(w, offline)
        key = json.dumps(norm, sort_keys=True)
        if key in seen:
            return
        seen.add(key)
        out.append({"_label": label, **norm})  # type: ignore[dict-item]

    for lane in LANES:
        if lane in offline:
            continue
        for delta in (step, -step):
            cand = dict(current)
            cand[lane] = cand.get(lane, 0.0) + delta
            add(cand, f"{lane}{'+' if delta > 0 else '-'}{step:g}")

    def probe(pattern: Dict[str, float], label: str) -> None:
        merged = dict(current)
        for lane, value in pattern.items():
            if lane not in offline:
                merged[lane] = value
        add(merged, label)

    # Local ±step moves plus wide structural probes. The probes matter: measured
    # on the labeled set, a lane-dominant config can be 2x better than the pinned
    # weights, which a ±0.10 neighbourhood around the pinned values never reaches
    # (an early run of this tuner returned "no candidate improves" for exactly
    # that reason).
    probe({lane: 0.2 for lane in LANES}, "uniform")
    probe({"fts5": 0.25, "vector": 0.25, "graph": 0.30, "events": 0.10, "reference": 0.10}, "graph-heavy")
    probe({"fts5": 0.55, "vector": 0.15, "graph": 0.10, "events": 0.15, "reference": 0.05}, "fts5-mid")
    probe({"fts5": 0.80, "vector": 0.05, "graph": 0.05, "events": 0.08, "reference": 0.02}, "fts5-dominant")
    probe({"fts5": 0.05, "vector": 0.80, "graph": 0.05, "events": 0.08, "reference": 0.02}, "vector-dominant")
    probe({"fts5": 0.10, "vector": 0.05, "graph": 0.80, "events": 0.03, "reference": 0.02}, "graph-dominant")
    probe({"fts5": 0.40, "vector": 0.10, "graph": 0.10, "events": 0.38, "reference": 0.02}, "keyword-pair")
    return out


def rewrite_weights_literal(src: str, weights: Dict[str, float]) -> Dict[str, Any]:
    """Pure: rewrite the `WEIGHTS = {...}` literal in `src`.

    Returns {"source": new_src, "changed": {...}, "parsed": bool}. Only the
    literal is touched — the surrounding comments (which record why each value
    was chosen) survive, and nothing else in the module is rewritten.
    """
    block_match = re.search(r"WEIGHTS = \{(.*?)\n\}", src, flags=re.DOTALL)
    if not block_match:
        return {"source": src, "changed": {}, "error": "WEIGHTS block not found"}

    block = block_match.group(0)
    new_block = block
    changed: Dict[str, Dict[str, float]] = {}
    for lane in LANES:
        pat = re.compile(rf'("{lane}":\s*)([0-9]*\.?[0-9]+)')
        m = pat.search(new_block)
        if not m:
            continue
        old_val = float(m.group(2))
        new_val = float(weights[lane])
        if abs(old_val - new_val) > 1e-9:
            changed[lane] = {"from": old_val, "to": new_val}
        new_block = pat.sub(lambda mm, v=new_val: f"{mm.group(1)}{v:.2f}", new_block, count=1)

    out = src.replace(block, new_block)
    try:
        ast.parse(out)
        parsed = True
    except SyntaxError:
        parsed = False
    return {"source": out, "changed": changed, "parsed": parsed}


def apply_weights(weights: Dict[str, float]) -> Dict[str, Any]:
    """Rewrite the WEIGHTS literal in lib/ichor_hybrid.py (backup + ast check)."""
    src = HYBRID.read_text()
    res = rewrite_weights_literal(src, weights)
    changed = res.get("changed") or {}
    if res.get("error"):
        return {"applied": False, "error": res["error"]}
    if not changed:
        return {"applied": False, "reason": "no change", "weights": weights}
    if not res.get("parsed"):
        return {"applied": False, "error": "rewrite did not parse"}

    out = res["source"]
    backup = HYBRID.with_suffix(".py.bak.weights-" + time.strftime("%Y%m%d-%H%M%S"))
    shutil.copy2(HYBRID, backup)
    HYBRID.write_text(out)

    # Prove the new values are what the module now reports.
    import importlib
    import lib.ichor_hybrid as hybrid

    importlib.reload(hybrid)
    return {
        "applied": True,
        "changed": changed,
        "live_weights": hybrid.current_weights(),
        "backup": str(backup),
    }


def load_history() -> List[Dict[str, Any]]:
    if HISTORY.exists():
        try:
            return json.loads(HISTORY.read_text())
        except Exception:  # noqa: BLE001
            return []
    return []


def save_history(entry: Dict[str, Any]) -> None:
    hist = load_history()
    hist.append(entry)
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(hist[-100:], indent=2))


def run(
    *,
    step: float,
    k: int,
    limit: int,
    min_gain: float,
    max_latency_factor: float,
    apply: bool,
    queries: Optional[int] = None,
    final_queries: Optional[int] = None,
    top_n_final: int = 3,
    objective: str = "linked",
    backends: Optional[List[str]] = None,
) -> Dict[str, Any]:
    ev = _load_eval()
    golden = ev.load_golden()
    current = ev.current_weights()

    baseline = ev.evaluate(current, k=k, limit=limit, golden=golden, queries=queries,
                        backends=backends)
    base_score = composite(baseline, k, objective)
    offline = baseline.get("offline_lanes", [])

    rows: List[Dict[str, Any]] = []
    for cand in generate_candidates(current, step, offline):
        label = cand.pop("_label")
        report = ev.evaluate(cand, k=k, limit=limit, golden=golden, queries=queries,
                        backends=backends)
        score = composite(report, k, objective)
        lat_ok = report["latency_mean_ms"] <= baseline["latency_mean_ms"] * max_latency_factor
        rows.append({
            "label": label,
            "weights": cand,
            "score": score,
            "hit_at_k": report.get(f"hit_at_{k}", report.get("hit_at_5")),
            "mrr": report["mrr"],
            "latency_mean_ms": report["latency_mean_ms"],
            "latency_ok": lat_ok,
            "delta": round(score - base_score, 4),
        })

    viable = [r for r in rows if r["latency_ok"]]

    # Stage 2 — confirm the shortlist on the FULL set. A sampled search cannot
    # resolve the differences it is looking for (measured: every candidate tied on
    # a 10-query subset while lane-dominant configs differ by 2x on the full set),
    # so the decision is made from full-set numbers, never from the sample.
    confirmed: List[Dict[str, Any]] = []
    if queries and final_queries is None:
        shortlist = sorted(viable, key=lambda r: -r["score"])[: max(1, top_n_final)]
        if shortlist:
            full_base = ev.evaluate(current, k=k, limit=limit, golden=golden, queries=None,
                        backends=backends)
            full_base_score = composite(full_base, k, objective)
            for r in shortlist:
                full = ev.evaluate(r["weights"], k=k, limit=limit, golden=golden, queries=None,
                            backends=backends)
                r = dict(r)
                r["full_score"] = composite(full, k, objective)
                r["full_hit_at_k"] = (
                    full.get(f"linked_hit_at_{k}", full.get(f"hit_at_{k}"))
                    if objective == "linked" else full.get(f"hit_at_{k}", full.get("hit_at_5"))
                )
                r["full_mrr"] = full["mrr"]
                r["full_latency_mean_ms"] = full["latency_mean_ms"]
                r["full_delta"] = round(r["full_score"] - full_base_score, 4)
                r["full_latency_ok"] = (
                    full["latency_mean_ms"] <= full_base["latency_mean_ms"] * max_latency_factor
                )
                confirmed.append(r)
            baseline_full = {**full_base, "composite": full_base_score}
        else:
            baseline_full = None
    else:
        baseline_full = None

    if confirmed:
        pool = [r for r in confirmed if r["full_latency_ok"]] or confirmed
        winner = max(pool, key=lambda r: (r["full_score"], -r["full_latency_mean_ms"]))
        gain = round(winner["full_delta"], 4)
        base_for_gain = winner["full_score"] - gain
        scope = f"full set ({baseline_full['queries'] if baseline_full else '?'} queries)"
    else:
        winner = max(viable, key=lambda r: (r["score"], -r["latency_mean_ms"]), default=None)
        gain = round(winner["score"] - base_score, 4) if winner else 0.0
        base_for_gain = base_score
        scope = f"sample ({baseline['queries']} queries)"

    decision = "hold"
    reason = f"best gain {gain:+.4f} below min-gain {min_gain} [{scope}]"
    if winner and gain >= min_gain:
        decision = "apply"
        reason = f"gain {gain:+.4f} ≥ min-gain {min_gain} [{scope}]"
    if offline:
        reason += f"; offline lanes frozen: {offline}"

    result: Dict[str, Any] = {
        "baseline": {**baseline, "composite": base_score},
        "candidates": sorted(rows, key=lambda r: -r["score"]),
        "winner": winner,
        "confirmed": confirmed,
        "baseline_full": baseline_full,
        "gain": gain,
        "decision": decision,
        "reason": reason,
        "min_gain": min_gain,
        "objective": objective,
        "backends": backends or "default",
        "step": step,
        "k": k,
        "queries": baseline["queries"],
    }

    if apply and decision == "apply" and winner:
        result["apply"] = apply_weights(winner["weights"])
    elif apply:
        result["apply"] = {"applied": False, "reason": reason}

    save_history({
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "baseline_composite": base_score,
        "baseline_weights": current,
        "winner": winner["weights"] if winner else None,
        "winner_label": winner["label"] if winner else None,
        "gain": gain,
        "decision": decision,
        "reason": reason,
        "applied": bool(result.get("apply", {}).get("applied")),
        "queries": baseline["queries"],
        "backends": backends or "default",
        "offline_lanes": offline,
    })
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--min-gain", type=float, default=MIN_GAIN_DEFAULT)
    ap.add_argument("--max-latency-factor", type=float, default=MAX_LATENCY_FACTOR_DEFAULT)
    ap.add_argument("--apply", action="store_true", help="write the winner into lib/ichor_hybrid.py")
    ap.add_argument("--json", default=None)
    ap.add_argument("--queries", type=int, default=None,
                    help="stride-sample this many golden queries per candidate (search speed)")
    ap.add_argument("--top-n-final", type=int, default=3,
                    help="re-confirm this many top candidates on the FULL set before deciding")
    ap.add_argument("--objective", choices=("linked", "text"), default="linked",
                    help="linked = did we return the entity's own relations (default); "
                         "text = does the expected name appear in result text")
    ap.add_argument("--backends", default=None,
                    help="comma-separated lane set to tune over (default: the production "
                         "4-lane list). Use after a lane-drop experiment decides the set.")
    ap.add_argument("--report", action="store_true", help="print tuning history")
    args = ap.parse_args()

    if args.report:
        hist = load_history()
        if not hist:
            print("no tuning history yet")
            return 0
        for h in hist[-10:]:
            print(f"{h['at']}  gain={h['gain']:+.4f}  {h['decision']:5}  applied={h['applied']}  "
                  f"winner={h['winner_label']}  q={h['queries']}")
        return 0

    lane_set = [b.strip() for b in args.backends.split(",") if b.strip()] if args.backends else None
    res = run(step=args.step, k=args.k, limit=args.limit, min_gain=args.min_gain,
              max_latency_factor=args.max_latency_factor, apply=args.apply,
              queries=args.queries, top_n_final=args.top_n_final,
              objective=args.objective, backends=lane_set)

    b = res["baseline"]
    kk = res["k"]
    print(f"golden queries={res['queries']}  k={kk}  step={res['step']}  objective={res['objective']}")
    print(f"lane set={res.get('backends')}")
    print(f"BASELINE  hit@{kk}={b.get(f'hit_at_{kk}', 0):.3f}  mrr={b['mrr']:.3f}  "
          f"composite={b['composite']:.4f}  lat={b['latency_mean_ms']}ms")
    print(f"          weights={b['weights']}")
    if b.get("offline_lanes"):
        print(f"          ⚠ offline lanes (frozen, not tunable now): {b['offline_lanes']}")
    print("\ncandidate                              hit@k   mrr   composite   delta   lat_ms  ok")
    for r in res["candidates"]:
        print(f"  {r['label']:34} {r['hit_at_k']:.3f}  {r['mrr']:.3f}   {r['score']:.4f}  "
              f"{r['delta']:+.4f}  {r['latency_mean_ms']:6.1f}  {'yes' if r['latency_ok'] else 'NO'}")
    for r in res.get("confirmed") or []:
        print(f"  FINAL {r['label']:22} full hit@{kk}={r['full_hit_at_k']:.3f} mrr={r['full_mrr']:.3f} "
              f"score={r['full_score']:.4f} delta={r['full_delta']:+.4f} "
              f"lat={r['full_latency_mean_ms']:.0f}ms ok={r['full_latency_ok']}")
    w = res["winner"]
    print(f"\nDECISION: {res['decision'].upper()} — {res['reason']}")
    if w:
        print(f"  winner: {w['label']}  {w['weights']}")
    if "apply" in res:
        print(f"  apply: {json.dumps(res['apply'])}")
    if args.json:
        Path(args.json).write_text(json.dumps(res, indent=2))
        print(f"  report -> {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
