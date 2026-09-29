"""Optional reranker lane contract tests (Phase 10)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_rerank import rerank_results  # noqa: E402


def _candidates():
    return [
        {"id": "a", "score": 0.2, "confidence": 0.95, "proof_count": 5, "rank_reasons": []},
        {"id": "b", "score": 0.9, "confidence": 0.1, "proof_count": 1, "rank_reasons": []},
    ]


def test_rerank_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ICHOR_RERANK_ENABLED", raising=False)
    results, status = rerank_results(_candidates(), "query")
    assert status == "disabled"
    assert [r["id"] for r in results] == ["a", "b"]


def test_heuristic_opt_in_no_model_download(monkeypatch) -> None:
    monkeypatch.setenv("ICHOR_RERANK_ENABLED", "true")
    monkeypatch.setenv("ICHOR_RERANK_MODE", "heuristic")
    results, status = rerank_results(_candidates(), "query")
    assert status == "heuristic"
    assert all("heuristic_rerank" in r.get("rank_reasons", []) for r in results)
    assert all("final_score" in r for r in results)
