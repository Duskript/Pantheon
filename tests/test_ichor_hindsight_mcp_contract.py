"""MCP old/new retrieve contract tests for Hindsight kwargs."""
from __future__ import annotations

import importlib.machinery
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _load_mcp(home: Path, module_name: str):
    loader = importlib.machinery.SourceFileLoader(
        module_name, str(REPO_ROOT / "lib" / "ichor_mcp.py")
    )
    return loader.load_module()


def test_mcp_old_and_full_new_retrieve_calls_return_results(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    mod = _load_mcp(home, "ichor_mcp_contract_test")

    old = json.loads(mod.ichor_retrieve("x", limit=1))
    assert "error" not in old
    assert "results" in old

    new = json.loads(mod.ichor_retrieve(
        "x", limit=1, backends="observations,fts5,events",
        budget="low", max_tokens=128, types=["observation"],
        include_sources=True, include_raw=True, prefer_observations=True,
        query_timestamp="2026-08-06T00:00:00Z",
        tags=["user:konan"], tags_match="any_strict",
        min_scores={"final": 0.0}, include_inactive=False, rerank=None,
    ))
    assert "error" not in new
    assert "results" in new
    for key in (
        "candidate_counts", "token_budget", "estimated_tokens_returned",
        "results_dropped_for_token_budget", "rerank_status",
    ):
        assert key in new
    mod._drain_recall_log_writes()
