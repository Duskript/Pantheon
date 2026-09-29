#!/usr/bin/env python3
"""Ichor recall evaluation harness — labeled golden set + weight scoring.

Why this exists
---------------
`lib/forge_sweep.py` already grid-searches retrieval weights, but it scores them
against the *unlabeled* query log (`outcome: "pending"` on every row), so it is
optimising a proxy. This harness gives weight tuning ground truth: a labeled set
of queries with the entities a good recall path must surface, and a metric that
moves only when recall actually improves.

Run it in the interpreter that has the real backends (sqlite-vec + embedder) —
the hermes venv degrades to FTS5-only and cannot score the vector lane:

    PYTHONPATH=/home/konan/.hermes/vendor/zvec:/home/konan/pantheon \\
    ATHENAEUM_EMBED_API_KEY=ollama ATHENAEUM_EMBED_MODEL=nomic-embed-text \\
    ATHENAEUM_EMBED_URL=http://localhost:11434/api/embeddings \\
    /usr/local/lib/hermes-agent/venv/bin/python3 scripts/ichor_recall_eval.py

Usage
-----
    ... ichor_recall_eval.py --build-golden      # (re)generate the labeled set
    ... ichor_recall_eval.py                     # score the pinned weights
    ... ichor_recall_eval.py --baseline          # score + save a baseline file
    ... ichor_recall_eval.py --weights '{"fts5":0.3,"vector":0.3,"graph":0.2,"events":0.1,"reference":0.1}'
    ... ichor_recall_eval.py --k 5 --limit 10 --json /tmp/eval.json
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PANTHEON = Path("/home/konan/pantheon")
if str(PANTHEON) not in sys.path:
    sys.path.insert(0, str(PANTHEON))

from lib.ichor_hybrid import HybridScorer, current_weights, use_weights  # noqa: E402

DB = Path("/home/konan/.hermes/ichor.db")
FIX_DIR = PANTHEON / "shared/handoffs/ichor-relational-recall-fix"
GOLDEN_PATH = FIX_DIR / "golden-queries.json"
LANES = ("fts5", "vector", "graph", "events", "reference")

# Hand-written relation/phrase queries. These are the ones a person actually
# asks, and the ones the descriptor-only render path used to answer with filler.
# `expect` is validated against the live graph at build time (the entity must
# exist) — a label that matches nothing is dropped, not silently scored.
HAND_WRITTEN: List[Dict[str, Any]] = [
    {"query": "who is konan's brother", "expect": ["Tallon"]},
    {"query": "konan's partner relationship", "expect": ["Fia"]},
    {"query": "what memory system does konan want to improve", "expect": ["ichor memory system", "Ichor"]},
    {"query": "multi-hop graph query tool", "expect": ["ichor_graph_query"]},
    {"query": "which service exposes pantheon tools over mcp", "expect": ["pantheon-mcp"]},
    {"query": "workflow engine with retries and inboxes", "expect": ["Conductor v2", "conductor"]},
    {"query": "how do gods hand work to each other", "expect": ["handoff", "Conductor"]},
    {"query": "sqlite journal mode for concurrency", "expect": ["WAL"]},
    {"query": "cloudflare tunnel for public access", "expect": ["Cloudflare Tunnel"]},
    {"query": "embedding model used for vector search", "expect": ["nomic-embed-text", "vector"]},
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _degree_map(conn: sqlite3.Connection) -> Dict[int, int]:
    rows = conn.execute(
        """SELECT entity_id, COUNT(*) AS deg FROM (
               SELECT source_id AS entity_id FROM relationships WHERE valid_to IS NULL
               UNION ALL SELECT target_id FROM relationships WHERE valid_to IS NULL
           ) GROUP BY entity_id"""
    ).fetchall()
    return {int(r["entity_id"]): int(r["deg"]) for r in rows}


def _name_tokens(name: str) -> List[str]:
    return [t for t in re.split(r"[^A-Za-z0-9]+", name.lower()) if len(t) > 2]


def _expected_ids(conn: sqlite3.Connection, entity_id: int, name: str,
                  max_edges: int = 60, max_events: int = 40) -> List[str]:
    """Result ids that a correct retrieval may return for this entity.

    The text metric ("does the name appear in the result text") structurally
    penalises semantic lanes: a vector hit that is *about* the entity rarely
    repeats its name. These ids are entity-linked instead — the graph lane's
    incident-edge ids, plus event ids whose text mentions the entity — so a
    correct-but-unnamed hit still counts.
    """
    ids: List[str] = []
    rows = conn.execute(
        "SELECT source_id, target_id, type_id FROM relationships "
        "WHERE (source_id = ? OR target_id = ?) AND valid_to IS NULL LIMIT ?",
        (entity_id, entity_id, max_edges),
    ).fetchall()
    for r in rows:
        other = r["target_id"] if int(r["source_id"]) == entity_id else r["source_id"]
        if other is None or int(other) == entity_id:
            continue
        ids.append(f"graph:{int(other)}:{r['type_id']}")
    try:
        for r in conn.execute(
            "SELECT rowid FROM ichor_events_fts WHERE ichor_events_fts MATCH ? LIMIT ?",
            (f'"{name.lower()}"', max_events),
        ).fetchall():
            ids.append(f"fts5:{int(r['rowid'])}")
            ids.append(f"events:{int(r['rowid'])}")
    except Exception:  # noqa: BLE001 — FTS unavailable must not break the build
        pass
    return sorted(set(ids))


def build_golden(limit_entities: int = 60, min_words: int = 4) -> Dict[str, Any]:
    """Derive paraphrase queries from live summaries; validate hand-written ones."""
    conn = _connect()
    try:
        deg = _degree_map(conn)
        rows = conn.execute(
            "SELECT id, name, type_id, summary FROM entities "
            "WHERE status='active' AND summary IS NOT NULL AND TRIM(summary) <> '' "
            "ORDER BY id"
        ).fetchall()
        names_present = {
            str(r["name"]).lower() for r in conn.execute("SELECT name FROM entities WHERE status='active'")
        }
    finally:
        conn.close()

    entries: List[Dict[str, Any]] = []
    conn2 = _connect()
    candidates = sorted(
        (r for r in rows if deg.get(int(r["id"]), 0) >= 5 and len(str(r["name"])) >= 4),
        key=lambda r: -deg.get(int(r["id"]), 0),
    )[:limit_entities]

    for r in candidates:
        name = str(r["name"])
        summary = str(r["summary"])
        # The query must not contain the entity name, or keyword lanes would
        # match trivially and the metric would measure nothing.
        stripped = summary
        for tok in _name_tokens(name):
            stripped = re.sub(rf"\b{re.escape(tok)}\b", " ", stripped, flags=re.IGNORECASE)
        words = [w for w in re.split(r"\s+", re.sub(r"[^A-Za-z0-9\s'-]", " ", stripped)) if len(w) > 1][:12]
        if len(words) < min_words:
            continue
        entries.append({
            "query": " ".join(words),
            "expect": [name],
            "kind": "summary_paraphrase",
            "expect_entity_id": int(r["id"]),
            "expect_type": str(r["type_id"]),
            "degree": deg.get(int(r["id"]), 0),
            "expect_ids": _expected_ids(conn2, int(r["id"]), name),
        })

    for hw in HAND_WRITTEN:
        kept = [n for n in hw["expect"] if n.lower() in names_present]
        if not kept:
            continue
        entries.append({
            "query": hw["query"],
            "expect": kept,
            "kind": "hand_written",
            "degree": None,
        })

    conn2.close()
    golden = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "db": str(DB),
        "notes": (
            "expect = entity name(s) that must appear in the top-k results of a healthy "
            "recall path. Names are matched against each result's title/snippet/id text."
        ),
        "count": len(entries),
        "by_kind": {
            k: sum(1 for e in entries if e["kind"] == k)
            for k in {e["kind"] for e in entries}
        },
        "queries": entries,
    }
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(golden, indent=2))
    return golden


def load_golden() -> Dict[str, Any]:
    if not GOLDEN_PATH.exists():
        return build_golden()
    return json.loads(GOLDEN_PATH.read_text())


# Fields that may carry the matched text. Vector/FTS results are inconsistent
# about which one is populated, and scoring only `title` understated recall
# badly (a hit that is *about* the entity but does not repeat its name in the
# title read as a miss).
_TEXT_FIELDS = ("title", "snippet", "content", "text", "raw_text", "body", "brief", "outline", "value")


def _result_text(r: Dict[str, Any]) -> str:
    parts = [str(r.get(f) or "") for f in _TEXT_FIELDS]
    parts.append(str(r.get("id") or ""))
    return " ".join(parts).lower()


def _first_hit_rank(results: List[Dict[str, Any]], expect: List[str]) -> Optional[int]:
    for i, r in enumerate(results, start=1):
        text = _result_text(r)
        for name in expect:
            if re.search(rf"\b{re.escape(name.lower())}\b", text):
                return i
    return None


def sample_queries(entries: List[Dict[str, Any]], n: Optional[int]) -> List[Dict[str, Any]]:
    """Deterministic subset: stride-sample so tuning runs are reproducible.

    A grid search re-retrieves for every candidate, so search uses a bounded
    subset while the final verdict re-runs the full set.
    """
    if not n or n >= len(entries):
        return entries
    stride = len(entries) / n
    picked = [entries[int(i * stride)] for i in range(n)]
    return picked


def evaluate(
    weights: Optional[Dict[str, float]] = None,
    *,
    k: int = 5,
    limit: int = 10,
    golden: Optional[Dict[str, Any]] = None,
    verbose: bool = False,
    queries: Optional[int] = None,
    backends: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Score one weight configuration against the labeled set.

    `backends` overrides the lane set for the run (default: the production
    4-lane list inside HybridScorer). This is what makes "does dropping a lane
    cost recall?" a measurement instead of an argument.
    """
    golden = golden or load_golden()
    scorer = HybridScorer()
    entries = sample_queries(golden["queries"], queries)

    hits = {1: 0, 3: 0, k: 0}
    ranks: List[int] = []
    latencies: List[float] = []
    lane_results: Dict[str, int] = {lane: 0 for lane in LANES}
    lane_candidates: Dict[str, int] = {lane: 0 for lane in LANES}
    # Attribution: which lane supplied the top-k result that matched. A lane can
    # look busy (thousands of candidates) while never producing a correct hit —
    # that is the difference between "working" and "earning its weight".
    lane_hits: Dict[str, int] = {lane: 0 for lane in LANES}
    lane_offered: Dict[str, int] = {lane: 0 for lane in LANES}
    linked_hits = {1: 0, 3: 0, k: 0}
    linked_ranks: List[int] = []
    linked_considered = 0
    misses: List[Dict[str, Any]] = []

    # Lane set actually attempted per query (production default vs an explicit
    # override), so a lane-drop result is attributable rather than assumed.
    lane_set_used: Dict[str, int] = {}

    for e in entries:
        t0 = time.monotonic()
        # The lane set is part of the measured configuration. "This lane is
        # redundant" and "this lane is too slow to keep" are hypotheses, and
        # this is how they get tested: recall delta + latency delta, same
        # weights, same query set, same process.
        with use_weights(weights):
            res = scorer.retrieve(e["query"], limit=limit, backends=backends)
        latencies.append((time.monotonic() - t0) * 1000.0)

        for lane in res.get("backends_used", []) or []:
            lane_set_used[lane] = lane_set_used.get(lane, 0) + 1

        results = res.get("results", []) or []
        for lane, count in (res.get("candidate_counts") or {}).items():
            lane_candidates[lane] = lane_candidates.get(lane, 0) + int(count or 0)
        for r in results:
            lane = r.get("backend", "unknown")
            lane_results[lane] = lane_results.get(lane, 0) + 1

        for r in results[:k]:
            lane = r.get("backend", "unknown")
            lane_offered[lane] = lane_offered.get(lane, 0) + 1

        expect_ids = set(e.get("expect_ids") or [])
        if expect_ids:
            linked_considered += 1
            lrank = next((i for i, r in enumerate(results[:k], start=1)
                          if str(r.get("id")) in expect_ids), None)
            if lrank:
                linked_hits[1] += lrank == 1
                linked_hits[3] += lrank <= 3
                linked_hits[k] += 1
                linked_ranks.append(lrank)
            else:
                linked_ranks.append(0)

        rank = _first_hit_rank(results[:k], e["expect"])
        if rank:
            hits[1] += rank == 1
            hits[3] += rank <= 3
            hits[k] += 1
            ranks.append(rank)
            winner_lane = results[rank - 1].get("backend", "unknown")
            lane_hits[winner_lane] = lane_hits.get(winner_lane, 0) + 1
        else:
            ranks.append(0)
            if verbose:
                misses.append({
                    "query": e["query"][:80],
                    "expect": e["expect"],
                    "got": [str(r.get("id"))[:30] for r in results[:3]],
                })

    n = max(len(entries), 1)
    mrr = sum(1.0 / r for r in ranks if r) / n
    return {
        "weights": weights or current_weights(),
        "k": k,
        "limit": limit,
        "queries": len(entries),
        "backends": backends or "default",
        "lane_set_used": lane_set_used,
        "hit_at_1": round(hits[1] / n, 4),
        "hit_at_3": round(hits[3] / n, 4),
        f"hit_at_{k}": round(hits[k] / n, 4),
        "mrr": round(mrr, 4),
        "linked_queries": linked_considered,
        "linked_hit_at_1": round(linked_hits[1] / max(linked_considered, 1), 4),
        "linked_hit_at_3": round(linked_hits[3] / max(linked_considered, 1), 4),
        f"linked_hit_at_{k}": round(linked_hits[k] / max(linked_considered, 1), 4),
        "linked_mrr": round(
            sum(1.0 / r for r in linked_ranks if r) / max(linked_considered, 1), 4
        ),
        "latency_mean_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "latency_p50_ms": round(statistics.median(latencies), 1) if latencies else 0.0,
        "lane_results": lane_results,
        "lane_candidates": lane_candidates,
        "lane_hits": lane_hits,
        "lane_offered_in_topk": lane_offered,
        "offline_lanes": sorted(
            lane for lane in LANES
            if lane_results.get(lane, 0) == 0 and lane_candidates.get(lane, 0) == 0
        ),
        "misses": misses,
    }


def lane_profile(queries: int = 5, limit: int = 10) -> Dict[str, Any]:
    """Cost + yield per lane, measured in isolation.

    Fusion latency hides which lane is expensive, and a lane that returns
    thousands of candidates can dominate the second while contributing nothing.
    One single-lane retrieval per golden query answers both.
    """
    golden = load_golden()
    entries = sample_queries(golden["queries"], queries)
    scorer = HybridScorer()
    out: Dict[str, Any] = {"queries": len(entries), "lanes": {}}
    for lane in LANES:
        times: List[float] = []
        candidates = 0
        results = 0
        empty = 0
        for e in entries:
            t0 = time.monotonic()
            res = scorer.retrieve(e["query"], limit=limit, backends=[lane])
            times.append((time.monotonic() - t0) * 1000.0)
            cand = int((res.get("candidate_counts") or {}).get(lane, 0) or 0)
            got = len(res.get("results", []) or [])
            candidates += cand
            results += got
            if not got:
                empty += 1
        out["lanes"][lane] = {
            "mean_ms": round(statistics.mean(times), 1) if times else 0.0,
            "p50_ms": round(statistics.median(times), 1) if times else 0.0,
            "candidates_total": candidates,
            "results_total": results,
            "empty_queries": empty,
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--build-golden", action="store_true")
    ap.add_argument("--lane-profile", type=int, default=None, metavar="N",
                    help="time each lane in isolation over N golden queries")
    ap.add_argument("--weights", default=None, help="JSON weight dict to score")
    ap.add_argument("--baseline", action="store_true", help="save the result as a baseline file")
    ap.add_argument("--json", default=None, help="write the full report here")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--verbose", action="store_true", help="list misses")
    ap.add_argument("--queries", type=int, default=None,
                    help="stride-sample this many golden queries (default: all)")
    ap.add_argument("--backends", default=None,
                    help="comma-separated lane set to measure (default: production "
                         "4-lane list). Lane-drop experiments run through this.")
    args = ap.parse_args()

    if args.build_golden:
        golden = build_golden()
        print(json.dumps({"golden": str(GOLDEN_PATH), "count": golden["count"],
                          "by_kind": golden["by_kind"]}, indent=2))
        return 0

    if args.lane_profile is not None:
        prof = lane_profile(queries=args.lane_profile, limit=args.limit)
        print(f"lane profile over {prof['queries']} queries (single-lane retrieval)")
        print(f"  {'lane':11} {'mean_ms':>9} {'p50_ms':>9} {'candidates':>11} {'results':>8} {'empty':>6}")
        for lane, s in prof["lanes"].items():
            print(f"  {lane:11} {s['mean_ms']:>9.1f} {s['p50_ms']:>9.1f} "
                  f"{s['candidates_total']:>11} {s['results_total']:>8} {s['empty_queries']:>6}")
        if args.json:
            Path(args.json).write_text(json.dumps(prof, indent=2))
            print(f"  report -> {args.json}")
        return 0

    weights = json.loads(args.weights) if args.weights else None
    lane_set = [b.strip() for b in args.backends.split(",") if b.strip()] if args.backends else None
    report = evaluate(weights, k=args.k, limit=args.limit, verbose=args.verbose,
                      queries=args.queries, backends=lane_set)

    kk = report["k"]
    hit_at_k = report.get(f"hit_at_{kk}", 0.0)
    print(f"queries={report['queries']}  k={kk}  limit={report['limit']}")
    print(f"  text-match: hit@1={report['hit_at_1']:.3f}  hit@3={report['hit_at_3']:.3f}  "
          f"hit@{kk}={hit_at_k:.3f}  mrr={report['mrr']:.3f}")
    if report.get("linked_queries"):
        print(f"  entity-linked: hit@1={report['linked_hit_at_1']:.3f}  "
              f"hit@3={report['linked_hit_at_3']:.3f}  "
              f"hit@{kk}={report.get(f'linked_hit_at_{kk}', 0):.3f}  "
              f"mrr={report['linked_mrr']:.3f}  ({report['linked_queries']} labeled)")
    print(f"  latency mean={report['latency_mean_ms']}ms p50={report['latency_p50_ms']}ms")
    print(f"  weights={report['weights']}")
    print(f"  lanes   ={report.get('backends')}  attempted={report.get('lane_set_used')}")
    print(f"  lane results    ={report['lane_results']}")
    print(f"  lane candidates ={report['lane_candidates']}")
    if report["offline_lanes"]:
        print(f"  ⚠ offline lanes (no candidates — cannot be tuned): {report['offline_lanes']}")
    for m in report["misses"][:8]:
        print(f"   MISS {m['query']!r} expect={m['expect']} got={m['got']}")

    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2))
        print(f"  report -> {args.json}")
    if args.baseline:
        path = FIX_DIR / f"eval-baseline-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(report, indent=2))
        print(f"  baseline -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
