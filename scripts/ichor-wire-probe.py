#!/usr/bin/env python3
"""ichor-wire-probe.py — prove recalled memory reaches the WIRE BYTES.

WHY THIS EXISTS
    ichor-health.py asserts the *effect* (fenced blocks in state.db carry
    payload). This probe asserts the *mechanism* end to end, in one process,
    against the real code paths:

        provider._format_context()          <- must return BARE text
          -> build_memory_context_block()   <- the HOST fences, once
            -> interior of that block       <- must carry the payload

    Both halves matter. A provider that self-wraps is hollowed out by
    sanitize_context() (919 chars in, 0 out, measured 2026-09-20); a fix that
    produced an empty return would pass a naive "no fence" check while
    delivering nothing.

WHAT IT ALSO GUARDS (regressions)
    * strict tag scoping must STILL exclude the graph lane when tags exist --
      the fix gates strictness on tags existing, it does not disable strictness.
    * the retrieval ladder must return non-empty results for a natural-language
      question (its graph lane used to be fetched and then discarded whole).

USAGE
    python3 ~/pantheon/scripts/ichor-wire-probe.py           # human report
    python3 ~/pantheon/scripts/ichor-wire-probe.py --json    # machine report

EXIT CODES
    0  all probes pass
    1  one or more probes FAILED (the mechanism is broken)

READ-ONLY: imports and calls the retrieval path with write-side effects
neutralised (_apply_score / _reinforce_edges / _llm_synthesize stubbed), so it
never mutates ichor.db and never spends an LLM call.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HOME = Path("/home/konan")
os.environ["HOME"] = str(HOME)

HERMES = HOME / ".hermes"
PANTHEON = HOME / "pantheon"
PLUGINS = HERMES / "plugins"
LIVE_TREE = HERMES / "runtimes" / "fleet" / "hermes-agent"

FENCE = "<memory-context>"
CLOSE = "</memory-context>"
MIN_PAYLOAD = 20

QUERY = "How does Ichor handle memory for Konan?"


def _bootstrap_path() -> None:
    """Replicate production import order: the installed fleet tree resolves
    hermes_cli BEFORE the ichor plugin prepends ~/pantheon to sys.path.

    Each insert(0) pushes earlier entries right, so insert in REVERSE order.
    Remove-then-insert unconditionally: PYTHONPATH may already contain these
    paths, and an `if p not in sys.path` guard would silently skip the reorder
    and leave pantheon's stub hermes_cli shadowing the real package.
    """
    for p in (str(PANTHEON), str(PLUGINS), str(LIVE_TREE)):
        while p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)


def _interior(block: str) -> str:
    """Body of the first fenced block, with the host's system-note line removed."""
    start = block.find(FENCE)
    end = block.find(CLOSE)
    if start == -1 or end <= start:
        return ""
    body = block[start + len(FENCE):end].strip()
    if body.startswith("[System note:"):
        close = body.find("]")
        body = body[close + 1:] if close != -1 else ""
    return body.strip()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Ichor wire-delivery probe")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    checks = []

    def record(name, ok, detail, data=None):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "data": data or {}})

    _bootstrap_path()
    try:
        from agent.memory_manager import build_memory_context_block
        from ichor import provider as P
    except Exception as exc:
        record("import", False, f"{type(exc).__name__}: {exc}")
        return _report(checks, args.json)

    # ── 1. _format_context returns BARE text ────────────────────────────────
    synthetic = [
        {"backend": "graph", "title": "PROBE-MARKER-ENTITY",
         "snippet": "PROBE-MARKER-PAYLOAD: recalled memory must survive intact."},
        {"backend": "fts5", "title": "second", "snippet": "another row"},
    ]
    try:
        raw = P.IchorMemoryProvider._format_context(None, synthetic)
    except Exception as exc:
        record("bare_return", False, f"_format_context raised {type(exc).__name__}: {exc}")
        return _report(checks, args.json)

    self_wrapped = FENCE in raw or "System note" in raw
    record(
        "bare_return", not self_wrapped and "PROBE-MARKER-PAYLOAD" in raw,
        ("self-wrapped (fence/system-note present) -> WILL BE HOLLOWED"
         if self_wrapped else
         f"bare text, {len(raw)} chars, marker present"),
        {"chars": len(raw), "self_wrapped": self_wrapped},
    )

    # ── 2. the HOST fences it and the payload survives ──────────────────────
    block = build_memory_context_block(raw)
    body = _interior(block)
    ok = "PROBE-MARKER-PAYLOAD" in body and len(body) >= MIN_PAYLOAD
    record(
        "wire_payload", ok,
        (f"host block carries {len(body)} payload chars" if ok else
         f"payload LOST: interior is {len(body)} chars: {body[:60]!r}"),
        {"block_chars": len(block), "interior_chars": len(body)},
    )

    # ── 3. LIVE prefetch through the real provider ──────────────────────────
    try:
        prov = P.IchorMemoryProvider()
    except Exception as exc:
        record("live_prefetch", False, f"provider init failed: {type(exc).__name__}: {exc}")
        return _report(checks, args.json)

    prov._apply_score = lambda *a, **k: None          # no writes
    prov._reinforce_edges = lambda *a, **k: None      # no writes
    prov._llm_synthesize = lambda *a, **k: ""         # no API spend
    prov._cache.clear()                               # no stale hollow hits  # noqa: SLF001

    try:
        live_raw = prov.prefetch(QUERY)
    except Exception as exc:
        record("live_prefetch", False, f"prefetch raised {type(exc).__name__}: {exc}")
        live_raw = ""

    live_block = build_memory_context_block(live_raw) if live_raw else ""
    live_body = _interior(live_block)
    ok = bool(live_raw) and not (FENCE in live_raw) and len(live_body) >= MIN_PAYLOAD
    record(
        "live_prefetch", ok,
        (f"live recall: {len(live_raw)} chars provider -> {len(live_body)} payload chars on wire"
         if ok else
         f"live recall hollow or empty (provider={len(live_raw)}, payload={len(live_body)}, "
         f"self_wrapped={FENCE in live_raw})"),
        {"provider_chars": len(live_raw), "payload_chars": len(live_body),
         "self_wrapped": FENCE in live_raw},
    )

    # ── 4. strict scoping still excludes graph when tags EXIST ──────────────
    from lib.ichor_hybrid import MemoryTrait
    trait = MemoryTrait()
    try:
        no_tags = trait.retrieve(query=QUERY, limit=10, backends=["fts5", "events", "graph"],
                                 tags=[], tags_match="any_strict", budget="mid",
                                 max_tokens=4096, include_sources=True)
        no_tags_excluded = (no_tags.get("strict_scope_excluded_counts") or {}).get("graph_untagged", 0)
        no_tags_results = len(list(no_tags.get("results") or []))
        backends_used = list(no_tags.get("backends_used") or [])
        ok = no_tags_excluded == 0 and no_tags_results > 0
        record(
            "ladder_no_tags", ok,
            (f"no-tag call keeps graph: {no_tags_results} results, 0 excluded, "
             f"backends={backends_used}"
             if ok else
             f"no-tag call still discards the graph lane: {no_tags_excluded} excluded, "
             f"{no_tags_results} results"),
            {"excluded": no_tags_excluded, "results": no_tags_results,
             "backends_used": backends_used},
        )

        with_tags = trait.retrieve(query=QUERY, limit=10, backends=["fts5", "events", "graph"],
                                   tags=["user:konan"], tags_match="any_strict", budget="mid",
                                   max_tokens=4096, include_sources=True)
        with_tags_excluded = (with_tags.get("strict_scope_excluded_counts") or {}).get("graph_untagged", 0)
        record(
            "strict_still_enforced", with_tags_excluded > 0,
            (f"tags present: {with_tags_excluded} untagged graph candidates still excluded "
             f"(strict semantics intact)"
             if with_tags_excluded > 0 else
             "REGRESSION: strict scoping no longer excludes anything with tags present"),
            {"excluded": with_tags_excluded},
        )
    except Exception as exc:
        record("ladder_no_tags", False, f"hybrid retrieve failed: {type(exc).__name__}: {exc}")

    # ── 5. the ladder returns evidence for a natural-language question ──────
    try:
        from lib.ichor_recall_ladder import recall_with_ladder
        ladder = recall_with_ladder(QUERY, tags=None, budget="mid", max_tokens=4096)
        n = len(list(ladder.results or []))
        steps = {s.name: s.result_count for s in ladder.steps}
        record(
            "ladder_results", n > 0,
            (f"{n} results; steps={steps}" if n > 0 else
             f"ladder returned 0 results; steps={steps}; warnings={ladder.warnings}"),
            {"results": n, "steps": steps, "warnings": list(ladder.warnings or [])},
        )
    except Exception as exc:
        record("ladder_results", False, f"recall_with_ladder failed: {type(exc).__name__}: {exc}")

    return _report(checks, args.json)


def _report(checks, as_json: bool) -> int:
    failed = [c for c in checks if not c["ok"]]
    if as_json:
        print(json.dumps({"failed": len(failed), "checks": checks}, indent=2, ensure_ascii=False))
    else:
        print("Ichor wire-delivery probe")
        print("=" * 72)
        for c in checks:
            print(f"[{'  ok ' if c['ok'] else ' FAIL'}] {c['check']:<22} {c['detail']}")
        print("-" * 72)
        print(f"{len(checks)} probes — {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
