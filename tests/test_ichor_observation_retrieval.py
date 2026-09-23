"""Observation retrieval contract tests (Phase 4).

After consolidation, ``ObservationsBackend.search(..., include_sources=True)``
returns ``observation:<id>`` results carrying proof_count, trend, source_ids,
tags, and rank_reasons.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402
from lib.ichor.retrieval_observations import ObservationsBackend  # noqa: E402
from lib.ichor_observations import ObservationConsolidator  # noqa: E402

RAW_1 = "Konan prefers event-driven over polling. LLMs fire only when a reply is needed."
RAW_2 = "Konan prefers event-driven over polling. LLMs should only fire when a reply is needed."


@pytest.fixture
def consolidated_db(tmp_path):
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
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
    yield db_path
    db.close()


def test_search_returns_observation_result_shape(consolidated_db) -> None:
    backend = ObservationsBackend(db_path=consolidated_db)
    hits = backend.search("konan", limit=5, include_sources=True)

    assert hits, "expected at least one observation hit"
    obs = hits[0]
    assert obs["id"].startswith("observation:")
    assert obs["backend"] == "observations"
    assert obs["type"] == "observation"
    assert int(obs["proof_count"]) >= 2
    assert obs["trend"] in {"new", "stable", "strengthening", "weakening", "stale"}
    assert obs["source_ids"], "observation must carry source ids"
    assert all(s.startswith(("fts5:", "conclusion:")) for s in obs["source_ids"])
    assert "user:konan" in obs.get("tags", [])
    assert "observation" in obs.get("rank_reasons", [])
    assert "proof_count:" in " ".join(obs.get("rank_reasons", []))


def test_search_include_sources_attaches_quotes(consolidated_db) -> None:
    backend = ObservationsBackend(db_path=consolidated_db)
    hits = backend.search("konan", limit=5, include_sources=True)
    sources = hits[0].get("sources") or []
    assert len(sources) >= 2
    quotes = {s.get("quote") for s in sources}
    assert RAW_1 in quotes
    assert RAW_2 in quotes
    for src in sources:
        assert src.get("source_session_id") in {"s1", "s2"}
        assert src.get("source_god_name") in {"thoth", "hermes"}


def test_search_respects_strict_tags(consolidated_db) -> None:
    backend = ObservationsBackend(db_path=consolidated_db)
    konan = backend.search("konan", limit=5, tags=["user:konan"], tags_match="any_strict")
    assert len(konan) >= 1
    other = backend.search("konan", limit=5, tags=["user:other"], tags_match="any_strict")
    assert other == [], "observation must be invisible under a foreign user scope"
