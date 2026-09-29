"""Budget/max_tokens recall metadata contract (Phase 6)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import lib.ichor_hybrid as ih  # noqa: E402
from lib.ichor_db import IchorDB  # noqa: E402


@pytest.fixture
def hybrid_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
    monkeypatch.setattr(ih, "_ICHOR_DB", Path(db_path))
    monkeypatch.setattr(ih, "_RETRIEVAL_LOG", tmp_path / "retrieval-log.jsonl")
    monkeypatch.setattr(ih, "_GRAPH_DB", tmp_path / "graph.db")
    for i in range(6):
        db.insert_event(
            session_id=f"s{i}",
            event_type="fact",
            subject=f"BudgetFact{i}",
            object="apollo recall budget",
            confidence=0.8,
            raw_text=("Apollo recall budget evidence " * 12) + str(i),
            god_name="hermes",
            tags=["user:konan", "scope:pantheon"],
        )
    yield db
    db.close()


def test_budgeted_recall_returns_token_metadata(hybrid_env) -> None:
    result = ih.MemoryTrait().retrieve(
        "apollo budget",
        limit=5,
        backends="fts5,events",
        budget="low",
        max_tokens=64,
        tags=["user:konan"],
        tags_match="any_strict",
    )
    assert result["budget"] == "low"
    assert result["token_budget"] == 64
    assert isinstance(result["candidate_counts"], dict)
    assert "estimated_tokens_returned" in result
    assert "results_dropped_for_token_budget" in result
    assert result["returned"] >= 1
    assert result["estimated_tokens_returned"] > 0
