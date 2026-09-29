"""Observation consolidation contract tests (Phase 3).

Repeated preference events with matching tags consolidate into ONE observation
with ``proof_count >= 2`` and exact-quote source rows. Re-running is
idempotent for creation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402
from lib.ichor_observations import ObservationConsolidator  # noqa: E402

RAW_1 = "Konan prefers event-driven over polling. LLMs fire only when a reply is needed."
RAW_2 = "Konan prefers event-driven over polling. LLMs should only fire when a reply is needed."
TAGS = ["user:konan", "scope:pantheon"]


@pytest.fixture
def seeded_db(tmp_path):
    db = IchorDB(db_path=str(tmp_path / "ichor.db"))
    db.connect()
    db.insert_event(
        session_id="s1", event_type="preference", subject="Konan",
        object="event-driven over polling", confidence=0.9,
        raw_text=RAW_1, god_name="thoth", tags=list(TAGS),
    )
    db.insert_event(
        session_id="s2", event_type="preference", subject="Konan",
        object="event-driven over polling", confidence=0.85,
        raw_text=RAW_2, god_name="hermes", tags=list(TAGS),
    )
    yield db, str(tmp_path / "ichor.db")
    db.close()


def test_repeated_preference_consolidates_to_one_observation(seeded_db) -> None:
    _db, db_path = seeded_db
    consolidator = ObservationConsolidator(db_path=db_path)
    result = consolidator.consolidate_events(limit=100, dry_run=False)

    assert result.observations_created == 1
    assert len(result.observations) == 1
    obs = result.observations[0]
    assert obs["subject"] == "Konan"
    assert int(obs["proof_count"]) >= 2
    assert obs["status"] == "active"
    assert obs["trend"] in {"new", "stable", "strengthening", "weakening", "stale"}


def test_observation_sources_hold_exact_quotes(seeded_db) -> None:
    _db, db_path = seeded_db
    consolidator = ObservationConsolidator(db_path=db_path)
    result = consolidator.consolidate_events(limit=100, dry_run=False)
    obs = result.observations[0]

    assert len(obs.get("sources") or []) >= 2
    quotes = {s["quote"] for s in obs["sources"]}
    assert RAW_1 in quotes, "exact quote from first event missing"
    assert RAW_2 in quotes, "exact quote from second event missing"
    assert all(len(q) <= 500 for q in quotes), "quotes exceed QUOTE_MAX_CHARS"


def test_observation_tags_are_union_of_event_tags(seeded_db) -> None:
    _db, db_path = seeded_db
    consolidator = ObservationConsolidator(db_path=db_path)
    result = consolidator.consolidate_events(limit=100, dry_run=False)
    obs = result.observations[0]
    assert "user:konan" in obs.get("tags", [])
    assert "scope:pantheon" in obs.get("tags", [])


def test_consolidation_is_idempotent(seeded_db) -> None:
    _db, db_path = seeded_db
    consolidator = ObservationConsolidator(db_path=db_path)
    first = consolidator.consolidate_events(limit=100, dry_run=False)
    second = consolidator.consolidate_events(limit=100, dry_run=False)

    assert second.observations_created == 0, "re-run must not create duplicates"
    assert second.observations_updated >= 0
    assert len(first.observations) == len(second.observations) == 1
    assert first.observations[0]["proof_count"] == second.observations[0]["proof_count"]


def test_dry_run_reports_without_writing(seeded_db) -> None:
    _db, db_path = seeded_db
    consolidator = ObservationConsolidator(db_path=db_path)
    result = consolidator.consolidate_events(limit=100, dry_run=True)
    assert result.dry_run is True
    assert result.written is False
    assert result.events_processed == 2
    assert result.clusters_found >= 1
    assert result.observations_created == 0

    # Nothing persisted by dry-run.
    obs_count = IchorDB(db_path=db_path).connect().execute(
        "SELECT COUNT(*) FROM ichor_observations"
    ).fetchone()[0]
    assert obs_count == 0


def _event_ids(db_path: str) -> list[int]:
    conn = IchorDB(db_path=db_path).connect()
    rows = conn.execute("SELECT id FROM ichor_events ORDER BY id").fetchall()
    return [int(r[0]) for r in rows]


def test_consolidation_after_id_advances_through_corpus(tmp_path) -> None:
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
    for idx in range(4):
        db.insert_event(
            session_id=f"s{idx}", event_type="preference", subject="Konan",
            object="cursor batching over repeated prefixes",
            raw_text=f"Konan prefers cursor batching over repeated prefixes proof {idx}.",
            god_name="hermes", tags=["scope:pantheon"], confidence=0.8,
        )
    db.close()
    ids = _event_ids(db_path)

    consolidator = ObservationConsolidator(db_path=db_path)
    first = consolidator.consolidate_events(limit=2, dry_run=True)
    second = consolidator.consolidate_events(limit=2, after_id=ids[1], dry_run=True)

    assert first.events_processed == 2
    assert first.min_event_id_processed == ids[0]
    assert first.max_event_id_processed == ids[1]
    assert second.events_processed == 2
    assert second.min_event_id_processed == ids[2]
    assert second.max_event_id_processed == ids[3]


def test_only_unsourced_skips_events_already_attached_to_sources(tmp_path) -> None:
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
    for idx in range(4):
        db.insert_event(
            session_id=f"s{idx}", event_type="preference", subject="Konan",
            object="unsourced cursor support",
            raw_text=f"Konan prefers unsourced cursor support with proof {idx}.",
            god_name="hermes", tags=["scope:pantheon"], confidence=0.8,
        )
    db.close()

    consolidator = ObservationConsolidator(db_path=db_path)
    first = consolidator.consolidate_events(limit=2, dry_run=False)
    assert first.sources_written == 2

    remaining = consolidator.consolidate_events(limit=10, only_unsourced=True, dry_run=True)
    assert remaining.events_processed == 2
    assert remaining.min_event_id_processed is not None
    assert remaining.min_event_id_processed > int(first.max_event_id_processed or 0)

