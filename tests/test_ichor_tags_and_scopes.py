"""Strict tag/scope retrieval contract tests (Phase 5).

- ``any_strict`` excludes other-user AND untagged rows.
- ``any`` includes untagged rows (and rows carrying any requested tag).
- Filters are applied before ranking/truncation (SQL-level).
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
from lib.ichor_tags import build_tag_filter_sql, normalize_tags  # noqa: E402


@pytest.fixture
def hybrid_env(tmp_path, monkeypatch):
    db_path = str(tmp_path / "ichor.db")
    db = IchorDB(db_path=db_path)
    conn = db.connect()
    monkeypatch.setattr(ih, "_ICHOR_DB", Path(db_path))
    monkeypatch.setattr(ih, "_RETRIEVAL_LOG", tmp_path / "retrieval-log.jsonl")
    monkeypatch.setattr(ih, "_GRAPH_DB", tmp_path / "graph.db")

    db.insert_event(
        session_id="s1", event_type="fact", subject="Konan",
        object="widget architecture", confidence=0.9,
        raw_text="Konan prefers the widget architecture.", god_name="thoth",
        tags=["user:konan", "scope:pantheon"],
    )
    db.insert_event(
        session_id="s3", event_type="fact", subject="OtherUser",
        object="widget loops", confidence=0.9,
        raw_text="OtherUser prefers widget loops.", god_name="thoth",
        tags=["user:other", "scope:pantheon"],
    )
    # Genuinely untagged row (raw SQL — insert_event always infers god/session).
    conn.execute(
        "INSERT INTO ichor_events (session_id, event_type, subject, object, raw_text, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            "s9", "fact", "GlobalNote", "widget convention",
            "Global widget convention note.", 0.8,
        ),
    )
    conn.commit()
    yield db, db_path
    db.close()


def _titles(result) -> list[str]:
    return [r.get("title", "") for r in result.get("results", [])]


def test_any_strict_excludes_other_user_and_untagged(hybrid_env) -> None:
    _db, _db_path = hybrid_env
    result = ih.MemoryTrait().retrieve(
        "widget", limit=10, backends=["fts5"],
        tags=["user:konan"], tags_match="any_strict",
    )
    titles = _titles(result)
    assert "Konan" in titles
    assert "OtherUser" not in titles, "other-user memory leaked under strict scope"
    assert "GlobalNote" not in titles, "untagged row leaked under strict scope"


def test_any_includes_untagged(hybrid_env) -> None:
    _db, _db_path = hybrid_env
    result = ih.MemoryTrait().retrieve(
        "widget", limit=10, backends=["fts5"],
        tags=["user:konan"], tags_match="any",
    )
    titles = _titles(result)
    assert "Konan" in titles
    assert "GlobalNote" in titles, "'any' must include untagged rows"
    assert "OtherUser" not in titles, "'any' must still exclude foreign-user rows"


def test_no_tags_preserves_legacy_behavior(hybrid_env) -> None:
    _db, _db_path = hybrid_env
    result = ih.MemoryTrait().retrieve("widget", limit=10, backends=["fts5"])
    titles = _titles(result)
    assert "Konan" in titles and "OtherUser" in titles and "GlobalNote" in titles


def test_build_tag_filter_sql_modes() -> None:
    sql, params = build_tag_filter_sql(
        "e", "ichor_event_tags", "id", "event_id",
        normalize_tags(["user:konan"]), "any_strict",
    )
    assert "EXISTS" in sql
    assert params == ["user:konan"]

    sql_any, params_any = build_tag_filter_sql(
        "e", "ichor_event_tags", "id", "event_id",
        normalize_tags(["user:konan"]), "any",
    )
    assert "NOT EXISTS" in sql_any, "'any' mode must include untagged rows"

    sql_all_strict, params_all_strict = build_tag_filter_sql(
        "e", "ichor_event_tags", "id", "event_id",
        normalize_tags(["user:konan", "scope:pantheon"]), "all_strict",
    )
    assert "COUNT(DISTINCT t.tag)" in sql_all_strict
    assert len(params_all_strict) == 3  # 2 tags + expected distinct count
