"""``prefer_observations`` dedup contract tests (Phase 4).

When observations and raw events are both in the candidate pool and
``prefer_observations=True``, raw rows that are PROVEN sources of a returned
observation are suppressed (metadata: ``prefer_observations_dropped_raw_count``).

Conservative behavior note: at ``limit=1`` (below the candidate count) the
dedup is strict — the returned result is the observation and no sourced raw
rows survive. At larger limits the backfill pass may re-introduce lower-ranked
rows, so this test pins the strict case.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import lib.ichor_hybrid as ih  # noqa: E402
from lib.ichor_db import IchorDB  # noqa: E402
from lib.ichor_observations import ObservationConsolidator  # noqa: E402

RAW_1 = "Konan prefers event-driven over polling. LLMs fire only when a reply is needed."
RAW_2 = "Konan prefers event-driven over polling. LLMs should only fire when a reply is needed."


@pytest.fixture
def hybrid_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
    monkeypatch.setattr(ih, "_ICHOR_DB", Path(db_path))
    monkeypatch.setattr(ih, "_RETRIEVAL_LOG", tmp_path / "retrieval-log.jsonl")
    monkeypatch.setattr(ih, "_GRAPH_DB", tmp_path / "graph.db")
    db.insert_event(
        session_id="s1", event_type="preference", subject="Konan",
        object="event-driven over polling", confidence=0.9,
        raw_text=RAW_1, god_name="thoth", tags=["user:konan", "scope:pantheon"],
    )
    db.insert_event(
        session_id="s2", event_type="preference", subject="Konan",
        object="event-driven over polling", confidence=0.85,
        raw_text=RAW_2, god_name="hermes", tags=["user:konan", "scope:pantheon"],
    )
    ObservationConsolidator(db_path=db_path).consolidate_events(limit=100, dry_run=False)
    yield db, db_path
    db.close()


def test_prefer_observations_suppresses_sourced_raw_rows(hybrid_env) -> None:
    _db, _db_path = hybrid_env
    result = ih.MemoryTrait().retrieve(
        "konan",
        limit=1,
        backends="observations,fts5,events",
        prefer_observations=True,
        tags=["user:konan"],
        tags_match="any_strict",
    )
    assert "prefer_observations_dropped_raw_count" in result
    assert result["prefer_observations_dropped_raw_count"] >= 1, (
        "expected at least one sourced raw row dropped"
    )
    assert result["results"], "expected the observation to survive"
    obs = result["results"][0]
    assert obs["backend"] == "observations"
    reasons = obs.get("rank_reasons") or []
    assert any(r.startswith("supersedes_raw:") for r in reasons), (
        "observation should carry the supersedes_raw rank reason"
    )
    # No raw sourced duplicate may survive in the strict (limit=1) case.
    raw_ids = set(obs.get("source_ids") or [])
    for r in result["results"]:
        if r["backend"] in ("fts5", "events"):
            assert r["id"] not in raw_ids, (
                f"raw sourced duplicate survived: {r['id']}"
            )


def test_prefer_observations_false_keeps_raw_rows(hybrid_env) -> None:
    _db, _db_path = hybrid_env
    result = ih.MemoryTrait().retrieve(
        "konan",
        limit=10,
        backends="observations,fts5,events",
        prefer_observations=False,
        tags=["user:konan"],
        tags_match="any_strict",
    )
    backends = {r.get("backend") for r in result["results"]}
    assert "observations" in backends
    assert "fts5" in backends, "raw fts5 rows must survive when not preferred"


def test_prefer_observations_metadata_present_without_observations(hybrid_env) -> None:
    _db, _db_path = hybrid_env
    result = ih.MemoryTrait().retrieve(
        "konan",
        limit=5,
        backends="fts5,events",
        prefer_observations=True,
        tags=["user:konan"],
        tags_match="any_strict",
    )
    assert "prefer_observations_dropped_raw_count" in result
    assert "results" in result
