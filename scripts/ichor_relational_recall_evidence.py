#!/usr/bin/env python3
"""Ichor relational recall — Fix A + Fix C live evidence.**

Produces the before/after proof the handoff asks for:
  1. which fixes landed (caller supplies the file:line)
  2. before/after `all_results` for a relationship query through `prefetch`
  3. `SELECT COUNT(*) FROM entity_aliases` before/after
  4. Konan / Cybermage resolving to one entity id

Runs against the LIVE ichor.db.  Reads only -- the Fix C migration is applied by
scripts/ichor_identity_alias_seed.py --apply, never from here.

    ~/.hermes/hermes-agent/.venv/bin/python3 \\
        scripts/ichor_relational_recall_evidence.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from pathlib import Path

PANTHEON_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_ROOT = Path("/home/konan/.hermes/plugins")
HERMES_AGENT = Path("/home/konan/.hermes/hermes-agent")
for _p in (str(PANTHEON_ROOT), str(PLUGIN_ROOT), str(HERMES_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lib.ichor.entities.entity_resolve import resolve  # noqa: E402

LIVE_DB = Path("/home/konan/.hermes/ichor.db")

QUERIES = [
    "What is my relationship to Fia?",
    "How is my brother doing?",
    "Is Cybermage working on TheoForge with Tallon?",
    "Tell me about Konan's partner and Amber",
    "Who does konan work with at VTC?",
]


def rule(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def aliases_count(db: Path) -> int:
    conn = sqlite3.connect(db)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM entity_aliases").fetchone()[0])
    finally:
        conn.close()


def section_fix_c() -> dict:
    rule("FIX C — nickname/alias resolution")
    probes = [
        "Cybermage", "Konan", "konan", "Konan Ross Rudolph I", "Konan Rudolph",
        "The Cybermage", "thecybermage", "180817012619083776",
        "konan.rudolph@gmail.com", "konan.rudolph@proton.me", "KONAN",
    ]
    resolved = {}
    for p in probes:
        resolved[p] = resolve(p, db_path=str(LIVE_DB))
        print(f"  resolve({p!r:30}) -> {resolved[p]}")

    ids = {v for v in resolved.values() if v is not None}
    verdict = "PASS — single canonical id" if ids == {614} else f"FAIL — {ids}"
    print(f"\n  distinct ids: {ids}  =>  {verdict}")
    print(f"  entity_aliases rows: {aliases_count(LIVE_DB)}")
    return {"resolve": resolved, "distinct_ids": sorted(i for i in ids if i)}


def section_fix_a(provider) -> dict:
    rule("FIX A — T3 graph tier (before/after per query)")
    out = {}
    for q in QUERIES:
        entities = provider._extract_named_entities(q)
        # BEFORE: the P4b shim
        before = []
        # AFTER: the wired tier
        t0 = time.monotonic()
        after = provider._query_graph(entities, depth=2)
        elapsed_ms = (time.monotonic() - t0) * 1000.0

        print(f"\n  query: {q!r}")
        print(f"    extracted entities : {entities}")
        print(f"    T3 before (shim)   : {len(before)} results")
        print(f"    T3 after  (wired)  : {len(after)} results   [{elapsed_ms:.0f} ms]")
        for hit in after[:6]:
            print(f"        - {hit['title']}   (conf {hit['score']})")
        out[q] = {
            "entities": entities,
            "before": len(before),
            "after": len(after),
            "ms": round(elapsed_ms, 1),
            "titles": [h["title"] for h in after],
        }
    return out


def section_prefetch(provider) -> dict:
    rule("PREFETCH — all_results before/after")

    low = [{
        "id": "fts5:1", "score": 0.4, "backend": "fts5", "type": "fact",
        "title": "weak keyword hit", "snippet": "tangential text",
        "direction": "unknown",
    }]

    real_qg = provider._query_graph
    query = "What is my relationship to Fia and my brother?"

    # BEFORE — shim
    provider._cache.clear()
    provider._query_fts5 = lambda query, limit=5: list(low)
    provider._query_chroma = lambda query, limit=5: []
    provider._query_graph = lambda entities, depth=2: []
    t0 = time.monotonic()
    before_ctx = provider.prefetch(query, session_id="evidence-before")
    before_ms = (time.monotonic() - t0) * 1000.0

    # AFTER — wired
    provider._cache.clear()
    captured = []

    def _spy(entities, depth=2):
        res = real_qg(entities, depth=depth)
        captured.append((entities, len(res)))
        return res

    provider._query_graph = _spy
    t0 = time.monotonic()
    after_ctx = provider.prefetch(query, session_id="evidence-after")
    after_ms = (time.monotonic() - t0) * 1000.0

    print(f"\n  query: {query!r}")
    print(f"\n  BEFORE (T3 = P4b shim, {before_ms:.0f} ms):")
    print("    " + (before_ctx.replace("\n", "\n    ") or "<empty context>"))
    print(f"\n  AFTER  (T3 wired, {after_ms:.0f} ms):")
    print("    " + (after_ctx.replace("\n", "\n    ") or "<empty context>"))
    print(f"\n  prefetch output changed: {before_ctx != after_ctx}")
    print(f"  T3 calls: {captured}")
    return {
        "changed": before_ctx != after_ctx,
        "before_ctx": before_ctx,
        "after_ctx": after_ctx,
        "t3_calls": captured,
        "before_ms": round(before_ms, 1),
        "after_ms": round(after_ms, 1),
    }


def section_fix_e(provider) -> dict:
    rule("FIX E — OOD gate non-terminal (Wave-1 acceptance #2)")
    print(
        "  Before Fix E the gate at provider.py returned empty context the\n"
        "  moment T1 was empty or scored < 0.3, so T2/T3/T4 never ran in exactly\n"
        "  the case they exist for.  Wave-1 acceptance item #2 asks for a\n"
        "  relationship query that FTS5 ALONE misses to still produce\n"
        "  all_results.  Demonstration:\n"
    )
    calls = []
    real_qg = provider._query_graph
    provider._cache.clear()
    provider._query_fts5 = lambda query, limit=5: []          # FTS5 finds nothing
    provider._query_chroma = lambda query, limit=5: []
    provider._query_graph = lambda entities, depth=2: (
        calls.append(entities) or real_qg(entities, depth=2)
    )
    ctx = provider.prefetch("Who is my brother?", session_id="evidence-fixe")
    provider._cache.clear()

    print(f"\n    query: 'Who is my brother?'   (FTS5 returns [])")
    print(f"    T3 invocations : {calls}")
    print(f"    prefetch output: {'NON-EMPTY ✅' if ctx else 'EMPTY ❌'}")
    if ctx:
        print("    " + ctx.replace("\n", "\n    "))
    return {"t3_calls": calls, "non_empty": bool(ctx), "ctx": ctx}


def section_latency(provider) -> dict:
    rule("HOT-PATH LATENCY (T3 now runs on every weak-T1 turn)")
    import statistics

    queries = [
        "How is my brother doing?",
        "What is my relationship to Fia?",
        "Who does konan work with at VTC?",
        "Zzzznotathing qqqq wwww",  # all-miss: worst case for resolution
    ]
    out = {}
    for q in queries:
        times = []
        for i in range(5):
            provider._cache.clear()
            t0 = time.monotonic()
            provider._query_graph(provider._extract_named_entities(q), depth=2)
            times.append((time.monotonic() - t0) * 1000.0)
        cold, warm = times[0], statistics.median(times[1:])
        out[q] = {"cold_ms": round(cold, 1), "warm_ms": round(warm, 1)}
        print(f"  {q[:42]:44} cold {cold:6.1f} ms | warm {warm:6.1f} ms")
    return out


def main() -> int:
    from ichor.provider import IchorMemoryProvider

    provider = IchorMemoryProvider()
    report = {
        "db": str(LIVE_DB),
        "fix_c": section_fix_c(),
        "fix_a": section_fix_a(provider),
        "prefetch": section_prefetch(provider),
        "fix_e": section_fix_e(provider),
        "latency": section_latency(provider),
    }

    rule("SUMMARY (json)")
    summary = {
        "aliases_rows": aliases_count(LIVE_DB),
        "konan_aliases_resolve_to": report["fix_c"]["distinct_ids"],
        "t3_before_total": sum(v["before"] for v in report["fix_a"].values()),
        "t3_after_total": sum(v["after"] for v in report["fix_a"].values()),
        "prefetch_changed": report["prefetch"]["changed"],
        "fts5_miss_now_non_empty": report["fix_e"]["non_empty"],
        "worst_cold_ms": max(v["cold_ms"] for v in report["latency"].values()),
        "worst_warm_ms": max(v["warm_ms"] for v in report["latency"].values()),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
