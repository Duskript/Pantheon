"""Lossless raw-turn storage for the Ichor context engine.

This module is intentionally small and deterministic. It owns only exact raw
message persistence and a compact session frontier; derived extraction belongs
to later Ichor enrichment lanes.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_TABLES = ["ichor_raw_turns", "ichor_session_frontier"]

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ichor_raw_turns (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    message_json TEXT NOT NULL,
    tool_name TEXT,
    tool_call_id TEXT,
    source TEXT NOT NULL DEFAULT 'context_engine',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_ichor_raw_turns_hash ON ichor_raw_turns(content_hash);
CREATE INDEX IF NOT EXISTS idx_ichor_raw_turns_created ON ichor_raw_turns(created_at DESC);

CREATE TABLE IF NOT EXISTS ichor_session_frontier (
    session_id TEXT PRIMARY KEY,
    last_ingested_seq INTEGER NOT NULL,
    active_tail_start_seq INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


@dataclass(frozen=True)
class RawTurn:
    """One exact stored message from a Hermes session."""

    session_id: str
    seq: int
    role: str
    content: str
    content_hash: str
    message_json: str
    tool_name: str | None = None
    tool_call_id: str | None = None
    source: str = "context_engine"
    created_at: str | None = None


class RawTurnStore:
    """SQLite repository for exact raw turns and session frontiers."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def migrate(self) -> dict[str, object]:
        """Create raw-turn tables and indexes. Idempotent."""
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            ready = [
                table
                for table in SCHEMA_TABLES
                if conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()
            ]
        return {"tables_ready": ready}

    def ingest_messages(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        source: str = "context_engine",
        active_tail_start_seq: int = 0,
    ) -> dict[str, int]:
        """Idempotently persist exact messages by ``(session_id, seq)``.

        Existing rows are updated only when the content hash changes. Replaying
        the same transcript therefore stays a no-op after the first insert.
        """
        self.migrate()
        inserted = 0
        updated = 0
        last_seq = len(messages) - 1
        with self._connect() as conn:
            for seq, message in enumerate(messages):
                normalized = self._normalize_message(message)
                existing = conn.execute(
                    "SELECT content_hash FROM ichor_raw_turns WHERE session_id=? AND seq=?",
                    (session_id, seq),
                ).fetchone()
                params = (
                    session_id,
                    seq,
                    normalized["role"],
                    normalized["content_hash"],
                    normalized["content"],
                    normalized["message_json"],
                    normalized["tool_name"],
                    normalized["tool_call_id"],
                    source,
                )
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO ichor_raw_turns (
                            session_id, seq, role, content_hash, content,
                            message_json, tool_name, tool_call_id, source
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        params,
                    )
                    inserted += 1
                elif existing["content_hash"] != normalized["content_hash"]:
                    conn.execute(
                        """
                        UPDATE ichor_raw_turns
                        SET role=?, content_hash=?, content=?, message_json=?,
                            tool_name=?, tool_call_id=?, source=?, updated_at=datetime('now')
                        WHERE session_id=? AND seq=?
                        """,
                        (
                            normalized["role"],
                            normalized["content_hash"],
                            normalized["content"],
                            normalized["message_json"],
                            normalized["tool_name"],
                            normalized["tool_call_id"],
                            source,
                            session_id,
                            seq,
                        ),
                    )
                    updated += 1
            conn.execute(
                """
                INSERT INTO ichor_session_frontier (
                    session_id, last_ingested_seq, active_tail_start_seq
                ) VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_ingested_seq=excluded.last_ingested_seq,
                    active_tail_start_seq=excluded.active_tail_start_seq,
                    updated_at=datetime('now')
                """,
                (session_id, last_seq, max(0, int(active_tail_start_seq))),
            )
            conn.commit()
        return {"seen": len(messages), "inserted": inserted, "updated": updated, "last_seq": last_seq}

    def fetch_range(self, session_id: str, start_seq: int, end_seq: int) -> list[RawTurn]:
        """Fetch exact raw turns for ``session_id`` in sequence order."""
        self.migrate()
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, seq, role, content, content_hash, message_json,
                       tool_name, tool_call_id, source, created_at
                FROM ichor_raw_turns
                WHERE session_id=? AND seq BETWEEN ? AND ?
                ORDER BY seq ASC
                """,
                (session_id, int(start_seq), int(end_seq)),
            ).fetchall()
        return [RawTurn(**dict(row)) for row in rows]

    def get_frontier(self, session_id: str) -> dict[str, Any] | None:
        """Return compact frontier state without volatile timestamp fields."""
        self.migrate()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT session_id, last_ingested_seq, active_tail_start_seq
                FROM ichor_session_frontier WHERE session_id=?
                """,
                (session_id,),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _normalize_message(message: dict[str, Any]) -> dict[str, str | None]:
        message_json = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, sort_keys=True)
        content_hash = hashlib.sha256(message_json.encode("utf-8")).hexdigest()
        role = str(message.get("role") or "unknown")
        tool_name = RawTurnStore._tool_name(message)
        tool_call_id = message.get("tool_call_id")
        return {
            "role": role,
            "content": content,
            "content_hash": content_hash,
            "message_json": message_json,
            "tool_name": str(tool_name) if tool_name else None,
            "tool_call_id": str(tool_call_id) if tool_call_id else None,
        }

    @staticmethod
    def _tool_name(message: dict[str, Any]) -> str | None:
        if message.get("name"):
            return str(message["name"])
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            first = tool_calls[0]
            if isinstance(first, dict):
                function = first.get("function")
                if isinstance(function, dict) and function.get("name"):
                    return str(function["name"])
        return None
