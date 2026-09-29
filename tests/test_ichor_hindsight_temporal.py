"""Time-aware/as-of retrieval contract tests (Phase 7)."""
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
    db.insert_event(
        session_id="stale", event_type="fact", subject="RoutingMode",
        object="legacy polling", raw_text="RoutingMode uses legacy polling.",
        confidence=0.9, god_name="thoth", tags=["user:konan"],
        valid_until="2026-08-01T12:00:00Z",
    )
    db.insert_event(
        session_id="current", event_type="fact", subject="RoutingMode",
        object="event driven", raw_text="RoutingMode now uses event driven delivery.",
        confidence=0.9, god_name="hermes", tags=["user:konan"],
        valid_from="2026-08-02T00:00:00Z",
    )
    db.insert_event(
        session_id="inactive", event_type="fact", subject="InactiveMode",
        object="archived routing", raw_text="InactiveMode archived routing fact.",
        confidence=0.8, god_name="hermes", tags=["user:konan"], status="archived",
    )
    yield db
    db.close()


def _snippets(result: dict) -> str:
    return "\n".join(str(r.get("snippet") or r.get("title") or "") for r in result.get("results", []))


def test_query_timestamp_excludes_expired_and_keeps_current(hybrid_env) -> None:
    result = ih.MemoryTrait().retrieve(
        "RoutingMode",
        limit=10,
        backends="fts5,events",
        tags=["user:konan"],
        tags_match="any_strict",
        query_timestamp="2026-08-06T00:00:00Z",
    )
    text = _snippets(result)
    assert "event driven" in text
    assert "legacy polling" not in text
    assert result["temporal_filter_dropped_count"] >= 1


def test_no_query_timestamp_excludes_inactive_status_only(hybrid_env) -> None:
    result = ih.MemoryTrait().retrieve(
        "InactiveMode routing",
        limit=10,
        backends="fts5,events",
        tags=["user:konan"],
        tags_match="any_strict",
    )
    assert "archived routing" not in _snippets(result)
