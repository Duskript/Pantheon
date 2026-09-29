"""Event write-path contract tests (Phase 2).

``IchorDB.insert_event`` must persist tags + temporal/lifecycle fields when
supplied, and legacy calls without the new args must keep working (with safe
god/session tag inference and ``mentioned_at`` defaulting to ``created_at``).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402


@pytest.fixture
def db(tmp_path) -> IchorDB:
    ichor = IchorDB(db_path=str(tmp_path / "ichor.db"))
    ichor.connect()
    yield ichor
    ichor.close()


def test_insert_event_persists_tags_and_temporal_fields(db: IchorDB) -> None:
    event_id = db.insert_event(
        session_id="s-write",
        event_type="fact",
        subject="Suno cookie",
        predicate="status",
        object="refreshed",
        confidence=0.8,
        raw_text="The Suno cookie was refreshed via in-app login.",
        god_name="hermes",
        tags=["user:konan", "scope:pantheon"],
        occurred_start="2026-08-02T00:00:00Z",
        occurred_end="2026-08-02T01:00:00Z",
        mentioned_at="2026-08-02T00:30:00Z",
        valid_from="2026-08-02T00:00:00Z",
        valid_until="2026-09-02T00:00:00Z",
        status="active",
    )
    assert event_id >= 1

    tags = db.get_event_tags(event_id)
    assert tags == ["scope:pantheon", "user:konan"]

    row = db._conn.execute(
        "SELECT occurred_start, occurred_end, mentioned_at, valid_from, valid_until, status "
        "FROM ichor_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    assert row["occurred_start"] == "2026-08-02T00:00:00Z"
    assert row["occurred_end"] == "2026-08-02T01:00:00Z"
    assert row["mentioned_at"] == "2026-08-02T00:30:00Z"
    assert row["valid_from"] == "2026-08-02T00:00:00Z"
    assert row["valid_until"] == "2026-09-02T00:00:00Z"
    assert row["status"] == "active"


def test_old_insert_without_new_args_still_works(db: IchorDB) -> None:
    event_id = db.insert_event(
        session_id="s-legacy",
        event_type="decision",
        subject="Zeus",
        predicate="decided",
        object="to summon council",
        confidence=0.95,
        raw_text="Zeus decided to summon the council of gods.",
        god_name="Zeus",
    )
    row = db._conn.execute(
        "SELECT status, mentioned_at, created_at FROM ichor_events WHERE id = ?",
        (event_id,),
    ).fetchone()
    assert row["status"] == "active"
    # mentioned_at defaults to the row creation time.
    assert row["mentioned_at"] == row["created_at"]
    assert row["mentioned_at"] is not None

    # Safe god:/session: tags are inferred (never user:<id>).
    tags = db.get_event_tags(event_id)
    assert "god:zeus" in tags
    assert "session:s-legacy" in tags
    assert not any(t.startswith("user:") for t in tags)


def test_superseded_by_persists(db: IchorDB) -> None:
    old_id = db.insert_event(
        session_id="s-sup", event_type="fact", subject="Suno cookie",
        object="stale", raw_text="The Suno cookie is stale.",
        valid_until="2026-08-01T12:00:00Z",
    )
    new_id = db.insert_event(
        session_id="s-sup", event_type="fact", subject="Suno cookie",
        object="refreshed", raw_text="The Suno cookie was refreshed.",
        superseded_by=old_id,
    )
    row = db._conn.execute(
        "SELECT superseded_by FROM ichor_events WHERE id = ?", (new_id,)
    ).fetchone()
    assert row["superseded_by"] == old_id
