"""Tests for lossless Ichor raw-turn persistence."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from lib.ichor.raw_turns import RawTurnStore


def _messages() -> list[dict[str, object]]:
    return [
        {"role": "system", "content": "You are Hermes."},
        {"role": "user", "content": "Build the Ichor raw turn store."},
        {
            "role": "assistant",
            "content": "Working.",
            "tool_calls": [{"id": "call_1", "function": {"name": "search_files"}}],
        },
        {"role": "tool", "content": "tool result payload", "tool_call_id": "call_1", "name": "search_files"},
    ]


def test_raw_turn_store_migrate_is_idempotent(tmp_path: Path) -> None:
    store = RawTurnStore(tmp_path / "ichor.db")

    first = store.migrate()
    second = store.migrate()

    assert first["tables_ready"] == ["ichor_raw_turns", "ichor_session_frontier"]
    assert second["tables_ready"] == ["ichor_raw_turns", "ichor_session_frontier"]
    with sqlite3.connect(tmp_path / "ichor.db") as conn:
        indexes = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
    assert "idx_ichor_raw_turns_hash" in indexes
    assert "idx_ichor_raw_turns_created" in indexes


def test_raw_turn_store_ingests_lossless_idempotent_messages(tmp_path: Path) -> None:
    store = RawTurnStore(tmp_path / "ichor.db")
    messages = _messages()

    first = store.ingest_messages("session-a", messages)
    second = store.ingest_messages("session-a", messages)

    assert first == {"seen": 4, "inserted": 4, "updated": 0, "last_seq": 3}
    assert second == {"seen": 4, "inserted": 0, "updated": 0, "last_seq": 3}
    rows = store.fetch_range("session-a", 1, 3)
    assert [row.seq for row in rows] == [1, 2, 3]
    assert rows[0].content == "Build the Ichor raw turn store."
    assert rows[1].tool_name == "search_files"
    assert rows[2].tool_call_id == "call_1"
    assert json.loads(rows[2].message_json)["content"] == "tool result payload"
    assert len(rows[2].content_hash) == 64
    assert store.get_frontier("session-a") == {
        "session_id": "session-a",
        "last_ingested_seq": 3,
        "active_tail_start_seq": 0,
    }


def test_raw_turn_store_updates_changed_seq_without_duplication(tmp_path: Path) -> None:
    store = RawTurnStore(tmp_path / "ichor.db")
    messages = _messages()
    store.ingest_messages("session-a", messages)
    changed = list(messages)
    changed[1] = {"role": "user", "content": "Changed exact text."}

    result = store.ingest_messages("session-a", changed)

    assert result == {"seen": 4, "inserted": 0, "updated": 1, "last_seq": 3}
    rows = store.fetch_range("session-a", 1, 1)
    assert rows[0].content == "Changed exact text."
