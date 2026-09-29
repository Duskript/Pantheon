#!/usr/bin/env python3
"""Lane-drop experiment: does removing a lane cost recall, and what does it buy?

## The question

At the tuned weights (`fts5 0.09 / vector 0.05 / graph 0.73 / events 0.03 /
reference 0.10`) the full 70-query fusion costs ~2.7 s per query. Two lanes are
suspicious:

* `events` reads the same corpus as `fts5` (both `ichor_events` +
  `ichor_events_fts`) and earned **zero** top-k results under the tuned weights
  — the tuner priced it at 0.03. Its single-lane profile is the slowest of the
  five (~2.6 s), so it may be paying a large latency bill for nothing.
* `vector` costs ~1 s for a 0.05 weight and 19 top-k results.

"Redundant" and "too slow to keep" are hypotheses, not findings. This script
turns them into a measurement: the same weights, the same 70 labeled queries,
the same process — only the lane set changes. Recall (text + entity-linked) and
latency are both reported, because a lane that costs 2 s must buy something.

## Configurations

| label | lanes | why |
|---|---|---|
| `default` | fts5, vector, graph, events | production reference point |
| `drop-vector` | fts5, graph, events | vector is the second most expensive |
| `drop-events` | fts5, vector, graph | events duplicates fts5 and earned 0 top-k |
| `drop-both` | fts5, graph | the latency hypothesis taken to its conclusion |
| `plus-reference` | fts5, vector, graph, events, reference | the revived reference lane |
| `lean-reference` | fts5, graph, reference | drop-both plus the revived lane |

## Usage

```
cd /home/konan/pantheon
export PYTHONPATH=/home/konan/.hermes/vendor/zvec:/home/konan/pantheon
export ATHENAEUM_EMBED_API_KEY=ollama ATHENAEUM_EMBED_MODEL=nomic-embed-text
export ATHENAEUM_EMBED_URL=http://localhost:11434/api/embeddings
/usr/local/lib/hermes-agent/venv/bin/python3 scripts/ichor_lane_drop_experiment.py
```

Run it on a quiet machine: the latency column is part of the decision, and
concurrent work on `ichor.db` reads as lane cost.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

FIX_DIR = REPO / "shared" / "handoffs" / "ichor-relational-recall-fix"

CONFIGS = [
    {"label": "default", "backends": None,
     "why": "production reference point (4-lane default list)"},
    {"label": "drop-vector", "backends": ["fts5", "graph", "events"],
     "why": "vector: ~1 s for weight 0.05"},
    {"label": "drop-events", "backends": ["fts5", "vector", "graph"],
     "why": "events: duplicates fts5 corpus, 0 top-k at weight 0.03"},
    {"label": "drop-both", "backends": ["fts5", "graph"],
     "why": "latency hypothesis taken to its conclusion"},
    {"label": "plus-reference", "backends": ["fts5", "vector", "graph", "events", "reference"],
     "why": "adds the revived reference lane"},
    {"label": "lean-reference", "backends": ["fts5", "graph", "reference"],
     "why": "drop-both plus the revived reference lane"},
]


def _row(rep: dict, base: dict, label: str, why: str) -> dict:
    k = rep["k"]
    return {
        "label": label,
        "why": why,
        "backends": rep.get("backends"),
        "queries": rep["queries"],
        "text_hit_at_1": rep["hit_at_1"],
        "text_hit_at_3": rep["hit_at_3"],
        f"text_hit_at_{k}": rep.get(f"hit_at_{k}"),
        "text_mrr": rep["mrr"],
        f"linked_hit_at_{k}": rep.get(f"linked_hit_at_{k}"),
        "linked_mrr": rep["linked_mrr"],
        "latency_mean_ms": rep["latency_mean_ms"],
        "latency_p50_ms": rep["latency_p50_ms"],
        "latency_delta_ms": round(rep["latency_mean_ms"] - base["latency_mean_ms"], 1),
        "text_hit_delta": round(rep.get(f"hit_at_{k}", 0) - base.get(f"hit_at_{k}", 0), 4),
        "linked_hit_delta": round(
            rep.get(f"linked_hit_at_{k}", 0) - base.get(f"linked_hit_at_{k}", 0), 4
        ),
        "lane_results": rep["lane_results"],
        "lane_candidates": rep["lane_candidates"],
        "lane_hits": rep["lane_hits"],
        "lane_offered_in_topk": rep["lane_offered_in_topk"],
        "lane_set_used": rep.get("lane_set_used"),
    }


def main() -> int:
    ev = _load_eval()
    weights = ev.current_weights()
    print(f"# Lane-drop experiment — weights {json.dumps(weights, sort_keys=True)}")
    print(f"# golden set: {FIX_DIR / 'golden-queries.json'}")
    print(f"# started {time.strftime('%Y-%m-%d %H:%M:%S')}\n")

    rows = []
    base = None
    for cfg in CONFIGS:
        t0 = time.monotonic()
        rep = ev.evaluate(weights, k=5, limit=10, backends=cfg["backends"])
        wall = time.monotonic() - t0
        if base is None:
            base = rep
        row = _row(rep, base, cfg["label"], cfg["why"])
        row["wall_s"] = round(wall, 1)
        rows.append(row)
        print(
            f"{cfg['label']:<15} text@5={row['text_hit_at_5']:.3f} "
            f"linked@5={row['linked_hit_at_5']:.3f} "
            f"lat={row['latency_mean_ms']:>8.1f}ms "
            f"({row['latency_delta_ms']:+.1f})  wall={wall:.0f}s"
        )
        print(f"                lanes={row['lane_set_used']}")
        print(f"                top-k by lane={row['lane_offered_in_topk']}")

    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "weights": weights,
        "k": 5,
        "limit": 10,
        "queries": base["queries"],
        "rows": rows,
    }
    path = FIX_DIR / f"lane-drop-{time.strftime('%Y%m%d-%H%M%S')}.json"
    path.write_text(json.dumps(out, indent=2))
    print(f"\nreport -> {path}")
    return 0


def _load_eval():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ichor_recall_eval", str(REPO / "scripts" / "ichor_recall_eval.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ichor_recall_eval"] = mod
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    raise SystemExit(main())
