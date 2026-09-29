"""Deterministic retrieval ladder: pages → observations → events/graph → LCM.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 9).

The ladder is the intended retrieval order for a god asking a question:

    1. knowledge_pages   cheap standing answer / projection
    2. observations      consolidated belief with proof count
    3. events + graph    raw Ichor evidence and relationships
    4. lcm_expand        exact source expansion OUTSIDE Ichor

Ichor NEVER calls LCM internally — when ``require_exact=True`` it returns
``lcm_expand_hint`` objects so the caller can invoke LCM with exact refs.
No autonomous LLM loop is introduced.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from lib.ichor_budget import resolve_budget
from lib.ichor_knowledge_pages import KnowledgePageStore
from lib.ichor_tags import default_tags_match, normalize_tags


@dataclass
class LadderStep:
    """One rung of the retrieval ladder."""

    name: str
    attempted: bool
    result_count: int
    enough: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class RecallLadderResult:
    """Fused ladder outcome with per-step visibility."""

    results: List[Dict[str, Any]] = field(default_factory=list)
    steps: List[LadderStep] = field(default_factory=list)
    source_expansion_hints: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": self.results,
            "steps": [
                {
                    "name": s.name,
                    "attempted": s.attempted,
                    "result_count": s.result_count,
                    "enough": s.enough,
                    "reasons": s.reasons,
                }
                for s in self.steps
            ],
            "source_expansion_hints": self.source_expansion_hints,
            "warnings": self.warnings,
        }


# Stop early when a step returns at least this many results and exact
# evidence is not required.
_ENOUGH_RESULTS = 3


def _source_ids_from_results(results: List[Dict[str, Any]]) -> List[str]:
    """Collect raw source ids (events/observations) for LCM expansion hints."""
    ids: List[str] = []
    for r in results:
        rid = r.get("id")
        if rid:
            ids.append(str(rid))
        for sid in r.get("source_ids") or []:
            if str(sid) not in ids:
                ids.append(str(sid))
    return ids[:20]


def recall_with_ladder(
    query: str,
    *,
    tags: list[str] | None = None,
    tags_match: str = "any_strict",
    budget: str = "mid",
    max_tokens: int = 4096,
    require_exact: bool = False,
    db_path: str | None = None,
) -> RecallLadderResult:
    """Run the deterministic retrieval ladder.

    Args:
        query: The question to answer.
        tags: Scope tags (e.g. ``["user:konan", "scope:pantheon"]``).
        tags_match: ``any_strict`` default (ladder is scoped by default).
        budget: low | mid | high (candidate effort).
        max_tokens: payload ceiling for fused results.
        require_exact: when True, the ladder does NOT stop early and returns
            ``lcm_expand_hint`` objects instead of pretending Ichor proof is
            exact transcript proof.
        db_path: Optional explicit ichor.db path (tests use temp DBs).

    Returns:
        RecallLadderResult with fused results, per-step stats, and (when
        required) LCM expansion hints.
    """
    resolve_budget(budget, max_tokens)  # validates early, fails clearly
    normalized_tags = normalize_tags(tags)
    # ``default_tags_match`` returns None when no tags are supplied ("no
    # opinion"), and a truthiness ``or`` fallback then promoted the call to the
    # STRICTEST mode -- so a no-tag query inherited _strict semantics it never
    # asked for, and the graph lane (which cannot prove tags) was discarded
    # wholesale. With no tags there is no tag filter to apply at all, so the
    # non-strict mode is the correct no-op. Explicit tags_match is still honored
    # whenever tags exist.
    effective_match = default_tags_match(normalized_tags, tags_match) or "any"
    result = RecallLadderResult()
    collected: List[Dict[str, Any]] = []
    warnings = result.warnings

    # ── Step 1: knowledge pages ───────────────────────────────────────────
    page_step = LadderStep("knowledge_pages", attempted=False, result_count=0, enough=False)
    try:
        store = KnowledgePageStore(db_path=db_path or "~/.hermes/ichor.db")
        pages = store.search_pages(
            query, tags=normalized_tags, tags_match=effective_match, limit=_ENOUGH_RESULTS
        )
        page_step.attempted = True
        page_step.result_count = len(pages)
        for p in pages:
            p = dict(p)
            p["id"] = f"page:{p.get('key')}"
            p["backend"] = "knowledge_pages"
            p["type"] = "knowledge_page"
            p.setdefault("rank_reasons", ["knowledge_page"])
            collected.append(p)
        # A knowledge page is a PROJECTION of the observation store, so by
        # construction it cannot contain anything the observations lane cannot
        # also return -- with less provenance and no evidence rows. Letting it
        # satisfy "enough" therefore trades real evidence for a summary of that
        # evidence. That was latent while the table was empty (`>= 3` matches can
        # never happen on zero rows); wiring the writer on 2026-09-21 made it
        # live: three weak token-overlap hits would have returned three page
        # snippets and skipped observations, events and graph entirely.
        #
        # So pages still run first (they are the cheapest step) and still land in
        # `collected`, but they never terminate the ladder.
        page_step.enough = False
        page_step.reasons.append("projection_is_derived")
    except Exception as exc:
        warnings.append(f"knowledge_pages step failed: {exc}")
    result.steps.append(page_step)
    if page_step.enough:
        result.results = collected[: max(1, int(max_tokens // 256))]
        return result

    # ── Step 2: observations ──────────────────────────────────────────────
    obs_step = LadderStep("observations", attempted=False, result_count=0, enough=False)
    try:
        from lib.ichor.retrieval_observations import ObservationsBackend

        backend = ObservationsBackend(db_path=db_path or "~/.hermes/ichor.db")
        observations = backend.search(
            query=query,
            limit=max(1, int(max_tokens // 512)),
            tags=normalized_tags,
            tags_match=effective_match,
            include_sources=True,
        )
        obs_step.attempted = True
        obs_step.result_count = len(observations)
        collected.extend(observations)
        obs_step.enough = len(observations) >= _ENOUGH_RESULTS and not require_exact
        if obs_step.enough:
            obs_step.reasons.append("early_stop")
    except Exception as exc:
        warnings.append(f"observations step failed: {exc}")
    result.steps.append(obs_step)
    if obs_step.enough:
        result.results = collected[: max(1, int(max_tokens // 256))]
        return result

    # ── Step 3: events + graph ────────────────────────────────────────────
    ev_step = LadderStep("events_graph", attempted=True, result_count=0, enough=False)
    try:
        from lib.ichor_hybrid import MemoryTrait

        trait = MemoryTrait()
        raw = trait.retrieve(
            query=query,
            limit=10,
            backends=["fts5", "events", "graph"],
            tags=normalized_tags,
            tags_match=effective_match,
            budget=budget,
            max_tokens=max_tokens,
            include_sources=True,
        )
        events_results = list(raw.get("results") or [])
        ev_step.result_count = len(events_results)
        collected.extend(events_results)
        ev_step.enough = len(events_results) >= _ENOUGH_RESULTS and not require_exact
        if ev_step.enough:
            ev_step.reasons.append("early_stop")
    except Exception as exc:
        warnings.append(f"events+graph step failed: {exc}")
    result.steps.append(ev_step)
    if ev_step.enough:
        result.results = collected[: max(1, int(max_tokens // 256))]
        return result

    # ── Step 4: LCM expansion hints (exact evidence boundary) ─────────────
    if require_exact or not collected:
        hint = {
            "kind": "lcm_expand_hint",
            "reason": "exact evidence requested" if require_exact else "no_ladder_evidence",
            "source_ids": _source_ids_from_results(collected),
            "note": "Caller should use lcm_expand/include_exact_ref for exact wording.",
        }
        result.source_expansion_hints.append(hint)
        lcm_step = LadderStep(
            "lcm_expand", attempted=True, result_count=len(hint["source_ids"]),
            enough=False, reasons=["exact_evidence_boundary"],
        )
        result.steps.append(lcm_step)
    else:
        result.steps.append(
            LadderStep("lcm_expand", attempted=False, result_count=0, enough=False)
        )

    # Fuse collected results: dedupe by id, keep best score per id.
    best: Dict[str, Dict[str, Any]] = {}
    for r in collected:
        rid = str(r.get("id") or r.get("key") or "")
        if not rid:
            continue
        if rid not in best or float(r.get("score") or 0) > float(best[rid].get("score") or 0):
            best[rid] = r
    fused = sorted(best.values(), key=lambda r: float(r.get("score") or 0), reverse=True)
    result.results = fused[: max(1, int(max_tokens // 256))]
    return result
