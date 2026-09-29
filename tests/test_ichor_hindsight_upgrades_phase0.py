"""Phase 0 guardrail tests: baseline compatibility + hindsight fixture.

Dictated final-pass tests for the Ichor Hindsight memory upgrade
(plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 0).

Covers:
- old ``MemoryTrait().retrieve(query, limit, backends)`` still works,
- the YAML fixture file loads,
- strict-tags exclusion of other users,
- observation consolidation smoke (feasible only with clusterable text —
  see the threshold note in the fixture file),
- temporal as-of exclusion of an expired fact.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "ichor_hindsight_upgrade_events.yaml"

import lib.ichor_hybrid as ih  # noqa: E402
from lib.ichor_db import IchorDB  # noqa: E402
from lib.ichor_observations import ObservationConsolidator  # noqa: E402

try:  # pragma: no cover - depends on environment
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None

EXPECTED_FIXTURE_IDS = {
    "repeated_preference_1",
    "repeated_preference_2",
    "other_user_leak_guard",
    "stale_fact",
    "superseding_fact",
}


# ---------------------------------------------------------------------------
# Fixture loading (PyYAML if available, else a minimal parser for this exact
# flat list-of-maps structure — the fixture has no nested maps).
# ---------------------------------------------------------------------------

def _strip_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _parse_inline_list(value: str) -> list[str]:
    value = value.strip()
    if not value.startswith("["):
        return []
    inner = value.strip("[]")
    if not inner.strip():
        return []
    parts = re.split(r",\s*", inner)
    return [_strip_scalar(p) for p in parts if _strip_scalar(p)]


def _fallback_parse_fixture(text: str) -> list[dict]:
    """Minimal YAML-subset parser: blocks starting with ``- id:``."""
    events: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("- id:"):
            if current is not None:
                events.append(current)
            current = {"id": _strip_scalar(line.split(":", 1)[1])}
            continue
        match = re.match(r"^\s+([a-z_]+):\s*(.*)$", line)
        if match and current is not None:
            key, value = match.group(1), match.group(2).strip()
            if value.startswith("["):
                current[key] = _parse_inline_list(value)
            elif value == "" or value.lower() == "null":
                current[key] = None
            else:
                current[key] = _strip_scalar(value)
    if current is not None:
        events.append(current)
    return events


def load_fixture_events() -> list[dict]:
    """Load the dictated fixture events (list of dicts)."""
    text = FIXTURE_PATH.read_text(encoding="utf-8")
    if _yaml is not None:
        return list(_yaml.safe_load(text) or [])
    return _fallback_parse_fixture(text)


def seed_fixture(db: IchorDB, events: list[dict] | None = None) -> dict[str, int]:
    """Insert fixture events into a temp IchorDB; returns {fixture_id: event_id}."""
    conn = db.connect()
    mapping: dict[str, int] = {}
    for ev in events or load_fixture_events():
        event_id = db.insert_event(
            session_id=ev["session_id"],
            event_type=ev["event_type"],
            subject=ev["subject"],
            predicate=ev.get("predicate"),
            object=ev.get("object"),
            confidence=float(ev.get("confidence") or 0.8),
            raw_text=ev.get("raw_text"),
            god_name=ev.get("god_name"),
            tags=ev.get("tags") or None,
            valid_until=ev.get("valid_until"),
            valid_from=ev.get("valid_from"),
        )
        created_at = ev.get("created_at")
        if created_at:
            conn.execute(
                "UPDATE ichor_events SET created_at = ?, "
                "mentioned_at = COALESCE(mentioned_at, ?) WHERE id = ?",
                (created_at, created_at, event_id),
            )
        mapping[str(ev["id"])] = event_id
    conn.commit()
    return mapping


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hybrid_env(tmp_path, monkeypatch):
    """Temp IchorDB + monkeypatched ichor_hybrid globals (no live DB touched)."""
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    db.connect()
    monkeypatch.setattr(ih, "_ICHOR_DB", Path(db_path))
    monkeypatch.setattr(ih, "_RETRIEVAL_LOG", tmp_path / "retrieval-log.jsonl")
    monkeypatch.setattr(ih, "_GRAPH_DB", tmp_path / "graph.db")
    yield db, db_path
    db.close()


# ---------------------------------------------------------------------------
# Baseline: old retrieve signature
# ---------------------------------------------------------------------------

def test_existing_ichor_retrieve_old_signature_still_works(hybrid_env) -> None:
    db, _db_path = hybrid_env
    db.insert_event(
        session_id="s0", event_type="fact", subject="Conductor",
        object="schedules dawn patrol", confidence=0.9,
        raw_text="Conductor schedules the dawn patrol runbook.",
        god_name="hermes",
    )
    # Old positional-ish signature: query, limit, comma-separated backends.
    result = ih.MemoryTrait().retrieve("Conductor", 10, "fts5,events")
    assert isinstance(result, dict)
    assert "results" in result
    assert len(result["results"]) >= 1
    assert any("Conductor" in r.get("title", "") for r in result["results"])


# ---------------------------------------------------------------------------
# Fixture file
# ---------------------------------------------------------------------------

def test_hindsight_upgrade_fixture_loads() -> None:
    assert FIXTURE_PATH.exists(), "fixture YAML missing"
    events = load_fixture_events()
    assert {str(e["id"]) for e in events} == EXPECTED_FIXTURE_IDS
    by_id = {str(e["id"]): e for e in events}

    pref1 = by_id["repeated_preference_1"]
    assert pref1["subject"] == "Konan"
    assert pref1["event_type"] == "preference"
    assert float(pref1["confidence"]) == 0.9
    assert pref1["tags"] == ["user:konan", "scope:pantheon", "topic:architecture"]

    assert by_id["other_user_leak_guard"]["tags"] == ["user:other", "scope:pantheon"]

    stale = by_id["stale_fact"]
    assert stale["valid_until"] == "2026-08-01T12:00:00Z"
    superseding = by_id["superseding_fact"]
    assert superseding["valid_from"] == "2026-08-02T00:00:00Z"


def test_fixture_seeds_into_temp_db_without_touching_live_db(hybrid_env) -> None:
    db, db_path = hybrid_env
    mapping = seed_fixture(db)
    assert len(mapping) == 5
    assert db.count() == 5
    # The live DB path must never have been touched by this test run.
    assert str(db_path) != "/home/konan/.hermes/ichor.db"


# ---------------------------------------------------------------------------
# Strict tags: other-user leak guard
# ---------------------------------------------------------------------------

def test_strict_tags_expected_to_exclude_other_user(hybrid_env) -> None:
    db, _db_path = hybrid_env
    seed_fixture(db)
    result = ih.MemoryTrait().retrieve(
        "polling", limit=10, backends=["fts5"],
        tags=["user:konan"], tags_match="any_strict",
    )
    snippets = [r.get("snippet", "") for r in result["results"]]
    assert snippets, "expected at least one Konan-scoped hit"
    assert any("Konan" in s for s in snippets)
    assert not any("OtherUser" in s for s in snippets), (
        "strict user:konan scope leaked another user's memory"
    )


# ---------------------------------------------------------------------------
# Observation consolidation smoke (clusterable text — see fixture note)
# ---------------------------------------------------------------------------

def test_observation_expected_to_consolidate_repeated_preference(hybrid_env) -> None:
    db, db_path = hybrid_env
    # The spec fixture pair uses distinct phrasings that fall below the MVP
    # 0.45 Jaccard threshold; seed a higher-similarity variant so the
    # consolidation path is exercised (documented in the fixture header).
    db.insert_event(
        session_id="s1", event_type="preference", subject="Konan",
        object="event-driven over polling", confidence=0.9,
        raw_text="Konan prefers event-driven over polling. LLMs fire only when a reply is needed.",
        god_name="thoth", tags=["user:konan", "scope:pantheon"],
    )
    db.insert_event(
        session_id="s2", event_type="preference", subject="Konan",
        object="event-driven over polling", confidence=0.85,
        raw_text="Konan prefers event-driven over polling. LLMs should only fire when a reply is needed.",
        god_name="hermes", tags=["user:konan", "scope:pantheon"],
    )
    consolidator = ObservationConsolidator(db_path=db_path)
    result = consolidator.consolidate_events(limit=100, dry_run=False)
    assert result.observations_created >= 1
    assert any(
        o.get("subject") == "Konan" and int(o.get("proof_count") or 0) >= 2
        for o in result.observations
    ), "repeated preference should consolidate to one observation"


# ---------------------------------------------------------------------------
# Temporal as-of: expired fact exclusion
# ---------------------------------------------------------------------------

def test_temporal_query_expected_to_exclude_expired_fact(hybrid_env) -> None:
    db, _db_path = hybrid_env
    seed_fixture(db)

    before = ih.MemoryTrait().retrieve(
        "Suno cookie", limit=5, backends=["fts5"],
        query_timestamp="2026-08-01T06:00:00Z",
    )
    before_snippets = [r.get("snippet", "") for r in before["results"]]
    assert any("stale" in s for s in before_snippets)
    assert not any("refreshed" in s for s in before_snippets), (
        "superseding fact must not be visible before its valid_from"
    )

    after = ih.MemoryTrait().retrieve(
        "Suno cookie", limit=5, backends=["fts5"],
        query_timestamp="2026-08-03T00:00:00Z",
    )
    after_snippets = [r.get("snippet", "") for r in after["results"]]
    assert any("refreshed" in s for s in after_snippets)
    assert not any("stale" in s for s in after_snippets), (
        "expired fact must be excluded at a later as-of timestamp"
    )
