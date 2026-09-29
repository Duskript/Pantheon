"""MCP recall_log metadata observability contract tests (Phase 11)."""
from __future__ import annotations

import importlib.machinery
import json
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def test_mcp_retrieve_writes_recall_metadata_columns(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    loader = importlib.machinery.SourceFileLoader(
        "ichor_mcp_observability_test", str(REPO_ROOT / "lib" / "ichor_mcp.py")
    )
    mod = loader.load_module()

    payload = json.loads(mod.ichor_retrieve(
        "nothing", limit=1, backends="observations,fts5,events",
        budget="low", max_tokens=128, tags=["user:konan"],
        tags_match="any_strict", prefer_observations=True,
        query_timestamp="2026-08-06T00:00:00Z",
    ))
    assert "results" in payload
    mod._drain_recall_log_writes()

    db_path = home / ".hermes" / "ichor.db"
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT retrieval_metadata_json, backends_requested_json, candidate_counts_json, "
            "strict_scope_excluded_counts_json, warnings_json, rerank_status FROM recall_log "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert row is not None
    metadata = json.loads(row["retrieval_metadata_json"])
    assert metadata["budget"] == "low"
    assert metadata["token_budget"] == 128
    assert json.loads(row["backends_requested_json"]) == ["observations", "fts5", "events"]
    assert isinstance(json.loads(row["candidate_counts_json"]), dict)
    assert isinstance(json.loads(row["strict_scope_excluded_counts_json"]), dict)
    assert isinstance(json.loads(row["warnings_json"]), list)
    assert row["rerank_status"] == "disabled"
