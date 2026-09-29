"""Schema contract tests for the Ichor Hindsight memory upgrade (Phase 1).

Verifies the additive schema: temporal/lifecycle columns on ``ichor_events``
and the new tags/observations/knowledge-page tables. Migration idempotency is
checked by connecting twice to the same temp DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402

EVENT_TEMPORAL_COLUMNS = [
    "occurred_start",
    "occurred_end",
    "mentioned_at",
    "valid_from",
    "valid_until",
    "status",
    "superseded_by",
]

NEW_TABLES = [
    "ichor_event_tags",
    "ichor_observations",
    "ichor_observation_sources",
    "ichor_observation_tags",
    "ichor_knowledge_pages",
    "ichor_knowledge_page_versions",
]


def _columns(conn, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_names(conn) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {str(r[0]) for r in rows}


@pytest.fixture
def db_path(tmp_path) -> str:
    return str(tmp_path / "ichor.db")


def test_events_temporal_columns_exist(db_path) -> None:
    db = IchorDB(db_path=db_path)
    conn = db.connect()
    cols = _columns(conn, "ichor_events")
    for column in EVENT_TEMPORAL_COLUMNS:
        assert column in cols, f"ichor_events missing column {column}"
    db.close()


def test_hindsight_tables_exist(db_path) -> None:
    db = IchorDB(db_path=db_path)
    conn = db.connect()
    tables = _table_names(conn)
    for table in NEW_TABLES:
        assert table in tables, f"missing table {table}"
    db.close()


def test_connect_twice_is_idempotent(db_path) -> None:
    """Calling connect() twice (two IchorDB instances) must not error or dup."""
    first = IchorDB(db_path=db_path)
    conn1 = first.connect()
    cols_before = _columns(conn1, "ichor_events")
    first.close()

    second = IchorDB(db_path=db_path)
    conn2 = second.connect()
    cols_after = _columns(conn2, "ichor_events")
    assert sorted(cols_after) == sorted(cols_before)
    for column in EVENT_TEMPORAL_COLUMNS:
        assert column in cols_after
    second.close()


def test_observation_fts_and_triggers_exist(db_path) -> None:
    db = IchorDB(db_path=db_path)
    conn = db.connect()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','trigger') AND name LIKE 'ichor_observations_%'"
    ).fetchall()
    names = {str(r[0]) for r in rows}
    assert "ichor_observations_fts" in names
    for trigger in ("ichor_observations_ai", "ichor_observations_ad", "ichor_observations_au"):
        assert trigger in names, f"missing observation FTS trigger {trigger}"
    db.close()


def test_event_tag_indexes_exist(db_path) -> None:
    db = IchorDB(db_path=db_path)
    conn = db.connect()
    idx = {
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ichor_events'"
        ).fetchall()
    }
    for index in ("idx_ichor_events_valid_until", "idx_ichor_events_status", "idx_ichor_events_mentioned_at"):
        assert index in idx, f"missing index {index}"
    db.close()
