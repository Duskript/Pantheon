#!/usr/bin/env python3
"""Standalone Ichor MCP server.

Phase A of the unified-upgrade plan: expose the existing Ichor memory
surface over MCP stdio, add lightweight audit/fold support, and keep the
old Pantheon server running in parallel.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from mcp.server.fastmcp import FastMCP

from lib.ichor_gates import GatePipeline, LogicGate, PhaseDetectionGate, ReadCache, StateGate
from lib.ichor_hybrid import MemoryTrait

logger = logging.getLogger("ichor-mcp")

_HOME = Path(os.path.expanduser("~"))
_ICHOR_DB = _HOME / ".hermes" / "ichor.db"
_AUDIT_TABLE = "ichor_mcp_audit"
_FOLDS_TABLE = "episodic_folds"

TOOL_NAMES = [
    "ichor_store",
    "ichor_retrieve",
    "ichor_health",
    "ichor_stats",
    "ichor_audit",
    "ichor_gate_check",
    "ichor_fold",
    "ichor_expand",
    "ichor_compare",
]

mcp = FastMCP("Ichor MCP")


@contextmanager
def _db_conn() -> Iterable[sqlite3.Connection]:
    _ICHOR_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_ICHOR_DB))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_support_tables() -> None:
    with _db_conn() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_AUDIT_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                ok INTEGER NOT NULL,
                latency_ms REAL NOT NULL,
                input_json TEXT NOT NULL,
                output_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_FOLDS_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                fold_type TEXT NOT NULL DEFAULT 'turn',
                summary TEXT,
                full_content TEXT NOT NULL,
                token_count INTEGER,
                folded_at TEXT NOT NULL DEFAULT (datetime('now')),
                expanded_at TEXT,
                expand_count INTEGER NOT NULL DEFAULT 0,
                parent_fold_id INTEGER REFERENCES {_FOLDS_TABLE}(id)
            )
            """
        )
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_FOLDS_TABLE}_session ON {_FOLDS_TABLE}(session_id)")
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{_FOLDS_TABLE}_expanded ON {_FOLDS_TABLE}(expanded_at)")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def _json_dumps(value: Any) -> str:
    return json.dumps(_jsonable(value), indent=2, sort_keys=True, default=str)


def _parse_backends(backends: str | list[str] | None) -> list[str]:
    if backends is None:
        return ["fts5", "vector", "events", "reference"]
    if isinstance(backends, list):
        return [str(b).strip() for b in backends if str(b).strip()]
    return [part.strip() for part in str(backends).split(",") if part.strip()]


def _audit(tool_name: str, payload: dict[str, Any], result: Any, ok: bool, started_at: float) -> None:
    try:
        _ensure_support_tables()
        with _db_conn() as conn:
            conn.execute(
                f"INSERT INTO {_AUDIT_TABLE} (created_at, tool_name, ok, latency_ms, input_json, output_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _now(),
                    tool_name,
                    1 if ok else 0,
                    round((time.perf_counter() - started_at) * 1000.0, 3),
                    _json_dumps(payload)[:4000],
                    _json_dumps(result)[:4000],
                ),
            )
    except Exception as exc:
        logger.debug("audit write failed for %s: %s", tool_name, exc)


def _memory_trait() -> MemoryTrait:
    return MemoryTrait()


def _fold_row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "fold_type": row["fold_type"],
        "summary": row["summary"],
        "full_content": row["full_content"],
        "token_count": row["token_count"],
        "folded_at": row["folded_at"],
        "expanded_at": row["expanded_at"],
        "expand_count": row["expand_count"],
        "parent_fold_id": row["parent_fold_id"],
    }


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = ?", (table,)).fetchone()
    if not row:
        return 0
    try:
        return int(conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()["cnt"])
    except Exception:
        return 0


def _latest_audit_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        f"SELECT COUNT(*) AS cnt, AVG(latency_ms) AS avg_latency_ms, MAX(latency_ms) AS max_latency_ms FROM {_AUDIT_TABLE}"
    ).fetchone()
    if not row:
        return {"count": 0, "avg_latency_ms": 0.0, "max_latency_ms": 0.0}
    return {
        "count": int(row["cnt"] or 0),
        "avg_latency_ms": float(row["avg_latency_ms"] or 0.0),
        "max_latency_ms": float(row["max_latency_ms"] or 0.0),
    }


def _filter_historical(results: list[dict[str, Any]], include_historical: bool) -> list[dict[str, Any]]:
    if include_historical:
        return results
    filtered: list[dict[str, Any]] = []
    for item in results:
        flags = [
            item.get("retired"),
            item.get("archived"),
            item.get("superseded"),
            item.get("deprecated"),
        ]
        status = str(item.get("status", "")).lower()
        if any(bool(flag) for flag in flags) or status in {"retired", "archived", "superseded", "deprecated"}:
            continue
        filtered.append(item)
    return filtered


@mcp.tool(description="Store an Ichor memory event.")
def ichor_store(
    namespace: str = "default",
    key: str = "",
    content: str = "",
    category: str = "fact",
    session_id: str = "",
    god_name: str = "",
    reconcile: bool = False,
) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {
        "namespace": namespace,
        "key": key,
        "content": content,
        "category": category,
        "session_id": session_id,
        "god_name": god_name,
        "reconcile": reconcile,
    }
    try:
        result = _memory_trait().store(
            namespace=namespace,
            key=key,
            content=content,
            category=category,
            session_id=session_id,
            god_name=god_name,
            reconcile=reconcile,
        )
        _audit("ichor_store", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_store failed: {exc}"}
        _audit("ichor_store", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Retrieve fused Ichor memory results.")
def ichor_retrieve(
    query: str,
    limit: int = 10,
    backends: str | list[str] | None = None,
    min_score: float = 0.0,
    active_god: str = "",
    include_historical: bool = False,
) -> str:
    started_at = time.perf_counter()
    backend_list = _parse_backends(backends)
    payload = {
        "query": query,
        "limit": limit,
        "backends": backend_list,
        "min_score": min_score,
        "active_god": active_god,
        "include_historical": include_historical,
    }
    try:
        result = _memory_trait().retrieve(
            query=query,
            limit=limit,
            backends=backend_list,
            min_score=min_score,
            active_god=active_god or None,
        )
        if isinstance(result, dict) and "results" in result:
            result = dict(result)
            result["results"] = _filter_historical(list(result.get("results") or []), include_historical)
            result["returned"] = len(result["results"])
        _audit("ichor_retrieve", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_retrieve failed: {exc}"}
        _audit("ichor_retrieve", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Check Ichor backend health and support-table readiness.")
def ichor_health() -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload: dict[str, Any] = {}
    try:
        trait_health = _memory_trait().health_check()
        with _db_conn() as conn:
            support = {
                "events": _table_count(conn, "ichor_events"),
                "warm_entities": _table_count(conn, "warm_entities"),
                "cold_events": _table_count(conn, "cold_events"),
                "reference_knowledge": _table_count(conn, "reference_knowledge"),
                "event_embeddings": _table_count(conn, "event_embeddings"),
                "strategic_goals": _table_count(conn, "strategic_goals"),
                "episodic_folds": _table_count(conn, _FOLDS_TABLE),
                "audit_entries": _table_count(conn, _AUDIT_TABLE),
            }
        result = {
            "healthy": bool(trait_health.get("healthy", False)),
            "trait_health": trait_health,
            "support": support,
            "db_path": str(_ICHOR_DB),
        }
        _audit("ichor_health", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_health failed: {exc}"}
        _audit("ichor_health", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Return Ichor stats, table counts, and audit latency info.")
def ichor_stats() -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload: dict[str, Any] = {}
    try:
        with _db_conn() as conn:
            result = {
                "db_path": str(_ICHOR_DB),
                "tables": {
                    "ichor_events": _table_count(conn, "ichor_events"),
                    "warm_entities": _table_count(conn, "warm_entities"),
                    "cold_events": _table_count(conn, "cold_events"),
                    "reference_knowledge": _table_count(conn, "reference_knowledge"),
                    "event_embeddings": _table_count(conn, "event_embeddings"),
                    "strategic_goals": _table_count(conn, "strategic_goals"),
                    "episodic_folds": _table_count(conn, _FOLDS_TABLE),
                    "audit_entries": _table_count(conn, _AUDIT_TABLE),
                },
                "audit": _latest_audit_stats(conn),
                "generated_at": _now(),
            }
        _audit("ichor_stats", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_stats failed: {exc}"}
        _audit("ichor_stats", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Return the recent Ichor MCP audit trail.")
def ichor_audit(limit: int = 20) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {"limit": limit}
    try:
        with _db_conn() as conn:
            rows = conn.execute(
                f"SELECT id, created_at, tool_name, ok, latency_ms, input_json, output_json FROM {_AUDIT_TABLE} ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            ).fetchall()
            result = {
                "count": len(rows),
                "entries": [
                    {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "tool_name": row["tool_name"],
                        "ok": bool(row["ok"]),
                        "latency_ms": row["latency_ms"],
                        "input": json.loads(row["input_json"]) if row["input_json"] else {},
                        "output": json.loads(row["output_json"]) if row["output_json"] else {},
                    }
                    for row in rows
                ],
            }
        _audit("ichor_audit", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_audit failed: {exc}"}
        _audit("ichor_audit", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Check whether a tool call would be blocked by the Ichor gate pipeline.")
def ichor_gate_check(
    tool_name: str,
    params: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {"tool_name": tool_name, "params": params or {}, "context": context or {}}
    try:
        pipeline = GatePipeline()
        pipeline.register(StateGate(pipeline.read_cache))
        pipeline.register(LogicGate())
        pipeline.register(PhaseDetectionGate())
        result_gate = pipeline.run_pre_call(tool_name, params or {}, context or {})
        if result_gate is None:
            result = {"passed": True, "blocked": False, "tool_name": tool_name}
        else:
            result = {
                "passed": bool(result_gate.passed),
                "blocked": not result_gate.passed,
                "gate": result_gate.gate_name,
                "message": result_gate.message,
                "recovery_hint": result_gate.recovery_hint,
                "intervention": result_gate.intervention,
                "tool_name": tool_name,
            }
        _audit("ichor_gate_check", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_gate_check failed: {exc}"}
        _audit("ichor_gate_check", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Store a folded Ichor context block.")
def ichor_fold(
    session_id: str,
    content: str,
    summary: str,
    token_count: int,
    fold_type: str = "turn",
    parent_fold_id: int | None = None,
) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {
        "session_id": session_id,
        "fold_type": fold_type,
        "summary": summary,
        "token_count": token_count,
        "parent_fold_id": parent_fold_id,
    }
    try:
        with _db_conn() as conn:
            cur = conn.execute(
                f"""
                INSERT INTO {_FOLDS_TABLE} (session_id, fold_type, summary, full_content, token_count, expanded_at, expand_count, parent_fold_id)
                VALUES (?, ?, ?, ?, ?, NULL, 0, ?)
                """,
                (
                    session_id,
                    fold_type,
                    summary,
                    content,
                    int(token_count),
                    parent_fold_id,
                ),
            )
            fold_id = int(cur.lastrowid)
            row = conn.execute(
                f"SELECT * FROM {_FOLDS_TABLE} WHERE id = ?",
                (fold_id,),
            ).fetchone()
        result = {"stored": True, "fold": _fold_row_to_dict(row)}
        _audit("ichor_fold", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_fold failed: {exc}"}
        _audit("ichor_fold", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Expand a stored Ichor fold by id.")
def ichor_expand(fold_id: int) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {"fold_id": fold_id}
    try:
        with _db_conn() as conn:
            row = conn.execute(
                f"SELECT * FROM {_FOLDS_TABLE} WHERE id = ?",
                (int(fold_id),),
            ).fetchone()
            if row is None:
                result = {"error": f"fold {fold_id} not found"}
                _audit("ichor_expand", payload, result, False, started_at)
                return _json_dumps(result)
            conn.execute(
                f"UPDATE {_FOLDS_TABLE} SET expanded_at = COALESCE(expanded_at, ?), expand_count = expand_count + 1 WHERE id = ?",
                (_now(), int(fold_id)),
            )
            updated = conn.execute(
                f"SELECT * FROM {_FOLDS_TABLE} WHERE id = ?",
                (int(fold_id),),
            ).fetchone()
        result = {"expanded": True, "fold": _fold_row_to_dict(updated)}
        _audit("ichor_expand", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_expand failed: {exc}"}
        _audit("ichor_expand", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Compare legacy and tiered Ichor retrieval results for a query.")
def ichor_compare(
    query: str,
    limit: int = 10,
    backends: str | list[str] | None = None,
    min_score: float = 0.0,
    active_god: str = "",
) -> str:
    started_at = time.perf_counter()
    backend_list = _parse_backends(backends)
    payload = {
        "query": query,
        "limit": limit,
        "backends": backend_list,
        "min_score": min_score,
        "active_god": active_god,
    }
    try:
        trait = _memory_trait()
        legacy = trait.retrieve(
            query=query,
            limit=limit,
            backends=backend_list,
            min_score=min_score,
            mode="legacy",
            active_god=active_god or None,
        )
        tiered = trait.retrieve(
            query=query,
            limit=limit,
            backends=backend_list,
            min_score=min_score,
            mode="tiered",
            active_god=active_god or None,
        )
        legacy_results = list(legacy.get("results") or []) if isinstance(legacy, dict) else []
        tiered_results = list(tiered.get("results") or []) if isinstance(tiered, dict) else []

        def _key(item: dict[str, Any]) -> str:
            return str(item.get("id") or item.get("event_id") or item.get("title") or item.get("snippet") or "")

        legacy_ids = {_key(item) for item in legacy_results}
        tiered_ids = {_key(item) for item in tiered_results}
        shared = sorted(legacy_ids & tiered_ids)
        result = {
            "query": query,
            "legacy": legacy,
            "tiered": tiered,
            "diff": {
                "legacy_only": sorted(legacy_ids - tiered_ids),
                "tiered_only": sorted(tiered_ids - legacy_ids),
                "shared": shared,
            },
        }
        _audit("ichor_compare", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_compare failed: {exc}"}
        _audit("ichor_compare", payload, result, False, started_at)
        return _json_dumps(result)


def list_tools() -> list[str]:
    return list(TOOL_NAMES)


# Keep a quick manifest for tests and future server introspection.
REGISTERED_TOOL_NAMES = list_tools()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ichor MCP server")
    parser.add_argument("--list-tools", action="store_true", help="Print registered tools and exit")
    parser.add_argument("--stdio", action="store_true", help="Run in stdio mode (default)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    _ensure_support_tables()

    if args.list_tools:
        print(_json_dumps({"tools": REGISTERED_TOOL_NAMES, "count": len(REGISTERED_TOOL_NAMES)}))
        return

    logger.info("Ichor MCP server ready on stdio")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
