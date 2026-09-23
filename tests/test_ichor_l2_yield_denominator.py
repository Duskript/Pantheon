"""Phase 2 metric contract: the extraction yield's DENOMINATOR.

`extraction_log` recorded how much came OUT of a batch and never how much went
IN, so "yield per batch" could not be normalised across the adaptive batch sizes
(10 vs 20) and was not a rate at all. The denominator existed only in journald,
which rotates.

These tests pin the two things that make the metric real:
  1. the columns exist on a fresh DB and the migration is idempotent
  2. the write path actually records the denominator and the producer
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.l2_llm import _store_extraction  # noqa: E402
from lib.ichor.entities.schema import get_conn, migrate  # noqa: E402


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "ichor.db"
    migrate(path)
    con = get_conn(path)
    yield con
    con.close()


def _parsed(entities=()):
    return {"entities": list(entities), "relationships": [], "relationship_types": []}


def test_fresh_db_has_the_denominator_columns(db):
    cols = [c[1] for c in db.execute("PRAGMA table_info(extraction_log)").fetchall()]
    assert "events_in_batch" in cols
    assert "writer" in cols


def test_migration_upgrades_a_legacy_table_and_is_idempotent(tmp_path):
    """On a FRESH db the columns come from CREATE TABLE, so the ALTER path is
    never exercised — calling migrate() on an empty file proves nothing about
    the upgrade. Build a legacy table explicitly, the way a live DB looks."""
    path = tmp_path / "ichor.db"
    con = get_conn(path)
    con.execute(
        "CREATE TABLE extraction_log ("
        " id INTEGER PRIMARY KEY,"
        " entity_id INTEGER, relationship_id INTEGER, fact_id INTEGER,"
        " method TEXT NOT NULL, source_text TEXT, source_session_id TEXT,"
        " confidence REAL DEFAULT 1.0, created_at TEXT DEFAULT (datetime('now')))"
    )
    con.commit()
    cols = [c[1] for c in con.execute("PRAGMA table_info(extraction_log)").fetchall()]
    assert "events_in_batch" not in cols, "the legacy table must start without it"
    con.close()

    applied = migrate(path).get("migrations_applied", [])
    assert "extraction_log.events_in_batch" in applied
    assert "extraction_log.writer" in applied

    con = get_conn(path)
    cols = [c[1] for c in con.execute("PRAGMA table_info(extraction_log)").fetchall()]
    con.close()
    assert "events_in_batch" in cols
    assert "writer" in cols

    # idempotent: a second pass applies nothing
    assert migrate(path).get("migrations_applied", []) == []


def test_write_path_records_the_denominator_and_the_writer(db):
    _store_extraction(
        db,
        _parsed([{"name": "Tallon", "type": "person"}]),
        source_text="t", provisional=True,
        events_in_batch=20, writer="test_suite",
    )
    db.commit()
    row = db.execute(
        "SELECT events_in_batch, writer, source_text FROM extraction_log "
        "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["events_in_batch"] == 20
    assert row["writer"] == "test_suite"
    assert "L2 pass:" in row["source_text"]


def test_yield_per_event_is_computable_from_the_row(db):
    """The whole point: a rate needs its denominator."""
    _store_extraction(
        db,
        _parsed([{"name": f"E{i}", "type": "concept"} for i in range(7)]),
        source_text="t", provisional=True,
        events_in_batch=10, writer="test_suite",
    )
    db.commit()
    row = db.execute(
        "SELECT events_in_batch, source_text FROM extraction_log "
        "ORDER BY id DESC LIMIT 1").fetchone()
    import re
    m = re.search(r"(\d+) entities, (\d+) relationships", row["source_text"])
    assert m, row["source_text"]
    yield_per_event = (int(m.group(1)) + int(m.group(2))) / row["events_in_batch"]
    assert yield_per_event > 0


def test_denominator_is_null_when_the_caller_does_not_supply_it(db):
    """Honest default: an unknown denominator is NULL, never a fabricated 1.

    A defaulted denominator would silently turn every un-instrumented row into a
    fake rate — the class-1 failure this contract exists to prevent.
    """
    _store_extraction(db, _parsed(), source_text="t", provisional=True)
    db.commit()
    row = db.execute(
        "SELECT events_in_batch, writer FROM extraction_log ORDER BY id DESC LIMIT 1").fetchone()
    assert row["events_in_batch"] is None
    assert row["writer"] == "l2_llm"          # a real default, but not a fake count
