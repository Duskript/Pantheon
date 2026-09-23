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
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

if __package__ in (None, ""):
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

# FastMCP moved out of the MCP SDK in ``mcp`` 2.0 (the high-level server now
# lives at ``mcp.server.mcpserver.MCPServer``), so the old hardcoded
# ``from mcp.server.fastmcp import FastMCP`` raised ModuleNotFoundError on every
# interpreter in the fleet and took this module's entire test file with it.
# ``lib.mcp_compat`` resolves whichever generation is installed, adapts the
# constructor, and reports the path it used; ``MCP_SERVER_SOURCE`` is surfaced
# by the health guardian.
from lib.mcp_compat import create_server, describe_server_class

MCP_SERVER_SOURCE = describe_server_class()

from lib.ichor.entities import entity_resolve
from lib.ichor_gates import GatePipeline, LogicGate, PhaseDetectionGate, ReadCache, StateGate
from lib.ichor_hybrid import MemoryTrait
# Resolve through the account home, not `$HOME`: a god's gateway session runs
# with HOME set to its profile sandbox, so `Path.home()` silently points at a
# DIFFERENT DB — a shadow `ichor.db` was written in production this way.
from lib.pantheon_path import account_home as _account_home  # noqa: E402
logger = logging.getLogger("ichor-mcp")

_HOME = _account_home()
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
    "ichor_entity_resolve",
    "ichor_recall_stats",
]

# Server instance. The class comes from whichever MCP SDK generation is
# installed (see the import block above); the decorator surface this module uses
# -- ``@mcp.tool(description=...)`` and ``mcp.run(transport="stdio")`` -- is
# identical across all of them.
mcp = create_server("Ichor MCP")


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


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """Return True when ``table`` already has ``column`` (SQLite PRAGMA)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return False
    return any(str(row[1]) == column for row in rows)


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to an existing table only when it is absent."""
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


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
        # Phase 3D — Recall Audit Trail. One row per ichor_retrieve call,
        # written asynchronously so the caller is never blocked.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS recall_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_text TEXT NOT NULL,
                god_name TEXT DEFAULT 'unknown',
                lanes_used TEXT DEFAULT '[]',
                per_lane_latency_ms TEXT DEFAULT '{}',
                total_ms REAL NOT NULL DEFAULT 0,
                top_result_ids TEXT DEFAULT '[]',
                top_result_scores TEXT DEFAULT '[]',
                retrieved_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        # Hindsight upgrade (Phase 11): additive JSON/text metadata columns on
        # recall_log so new retrieval metadata is stored without breaking
        # existing rows or the async writer.
        _add_column_if_missing(conn, "recall_log", "retrieval_metadata_json", "TEXT DEFAULT '{}'")
        _add_column_if_missing(conn, "recall_log", "backends_requested_json", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "recall_log", "candidate_counts_json", "TEXT DEFAULT '{}'")
        _add_column_if_missing(conn, "recall_log", "strict_scope_excluded_counts_json", "TEXT DEFAULT '{}'")
        _add_column_if_missing(conn, "recall_log", "warnings_json", "TEXT DEFAULT '[]'")
        _add_column_if_missing(conn, "recall_log", "rerank_status", "TEXT DEFAULT 'unknown'")


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


def _json_dumps_for_audit(value: Any, max_chars: int = 4000) -> str:
    """Return valid JSON that fits the audit table's compact payload budget.

    Audit rows are diagnostic breadcrumbs, not the source of truth. If a tool
    output is too large, store a valid JSON summary instead of slicing the JSON
    string mid-token; otherwise later audit readers cannot parse their own rows.
    """

    text = _json_dumps(value)
    if len(text) <= max_chars:
        return text

    preview_budget = max(0, max_chars - 240)
    summary = {
        "_truncated": True,
        "_original_chars": len(text),
        "preview": text[:preview_budget],
    }
    bounded = _json_dumps(summary)
    if len(bounded) <= max_chars:
        return bounded
    return json.dumps({
        "_truncated": True,
        "_original_chars": len(text),
        "preview": text[: max(0, max_chars - 120)],
    }, sort_keys=True)


def _parse_backends(backends: str | list[str] | None) -> list[str]:
    if backends is None:
        # Mirror the scorer's default lane set (it previously omitted `graph`,
        # the dominant lane, while listing the then-dead `reference` lane).
        return ["fts5", "graph", "reference", "warm"]
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
                    _json_dumps_for_audit(payload),
                    _json_dumps_for_audit(result),
                ),
            )
    except Exception as exc:
        logger.debug("audit write failed for %s: %s", tool_name, exc)


# ---------------------------------------------------------------------------
# Phase 3D — Recall Audit Trail (async writer)
# ---------------------------------------------------------------------------

# Module-level registry of in-flight recall_log writer threads so callers
# (tests, shutdown paths) can drain pending async writes deterministically.
# Production stays fire-and-forget (never blocks the caller); tests call
# _drain_recall_log_writes() before tearing down temp DB dirs so the WAL
# writer can't re-create -wal/-shm files inside a directory being rmtree'd.
_RECALL_WRITER_THREADS: list[threading.Thread] = []


def _drain_recall_log_writes(timeout: float = 5.0) -> int:
    """Join all in-flight recall_log writer threads. Returns how many joined."""
    threads = list(_RECALL_WRITER_THREADS)
    joined = 0
    for t in threads:
        try:
            t.join(timeout=timeout)
            joined += 1
        except Exception:
            pass
    _RECALL_WRITER_THREADS.clear()
    return joined


def _write_recall_log(query, god_name, result, total_ms, fallback_lanes) -> None:
    """Write one recall_log row (run in a daemon thread — never blocks the
    caller). Query text is truncated to 300 chars; full text is never stored.
    valid_to/valid_until are untouched here — only the triggers write those.

    Hindsight upgrade: additive retrieval metadata (budget, token ceilings,
    candidate/temporal/strict-scope counts, warnings, rerank status) is
    derived from the result payload and stored in the JSON/TEXT columns.
    """
    try:
        _ensure_support_tables()
        lanes = list(result.get("backends_used") or fallback_lanes or []) if isinstance(result, dict) else list(fallback_lanes or [])
        results = list(result.get("results") or []) if isinstance(result, dict) else []

        # Per-lane timing: sum latency_ms per backend from result rows when
        # present; otherwise fall back to splitting total_ms evenly.
        per_lane: dict[str, float] = {}
        for r in results:
            backend = str(r.get("backend") or "unknown")
            ms = r.get("latency_ms")
            if isinstance(ms, (int, float)):
                per_lane[backend] = per_lane.get(backend, 0.0) + float(ms)
        if not per_lane and lanes:
            share = float(total_ms) / max(1, len(lanes))
            per_lane = {b: round(share, 3) for b in lanes}

        top_ids = [str(r.get("id") or "") for r in results[:10]]
        top_scores = []
        for r in results[:10]:
            s = r.get("score")
            if s is None:
                s = r.get("fused_score")
            top_scores.append(round(float(s), 4) if isinstance(s, (int, float)) else 0.0)

        # Hindsight metadata: honor an explicit result["metadata"] dict, else
        # assemble one from the well-known top-level recall-control keys.
        metadata: dict[str, Any] = {}
        if isinstance(result, dict):
            nested = result.get("metadata")
            if isinstance(nested, dict):
                metadata = nested
        if not metadata and isinstance(result, dict):
            metadata = {
                k: result[k]
                for k in (
                    "budget",
                    "max_tokens",
                    "token_budget",
                    "estimated_tokens_returned",
                    "results_dropped_for_token_budget",
                    "prefer_observations_dropped_raw_count",
                    "temporal_filter_dropped_count",
                    "rerank_status",
                    "tags",
                    "tags_match",
                    "warnings",
                )
                if k in result and result[k] is not None
            }

        if isinstance(result, dict):
            backends_requested = result.get("backends_requested") or fallback_lanes or []
            candidate_counts = result.get("candidate_counts") or metadata.get("candidate_counts") or {}
            strict_counts = result.get("strict_scope_excluded_counts") or metadata.get("strict_scope_excluded_counts") or {}
            warnings = result.get("warnings") or metadata.get("warnings") or []
            rerank_status = str(result.get("rerank_status") or metadata.get("rerank_status") or "unknown")
        else:
            backends_requested = list(fallback_lanes or [])
            candidate_counts = metadata.get("candidate_counts") or {}
            strict_counts = metadata.get("strict_scope_excluded_counts") or {}
            warnings = metadata.get("warnings") or []
            rerank_status = str(metadata.get("rerank_status") or "unknown")

        with _db_conn() as conn:
            conn.execute(
                "INSERT INTO recall_log (query_text, god_name, lanes_used, "
                "per_lane_latency_ms, total_ms, top_result_ids, top_result_scores, "
                "retrieval_metadata_json, backends_requested_json, candidate_counts_json, "
                "strict_scope_excluded_counts_json, warnings_json, rerank_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(query)[:300],
                    str(god_name or "unknown"),
                    _json_dumps(lanes),
                    _json_dumps(per_lane),
                    round(float(total_ms), 3),
                    _json_dumps(top_ids),
                    _json_dumps(top_scores),
                    _json_dumps(metadata),
                    _json_dumps(backends_requested),
                    _json_dumps(candidate_counts),
                    _json_dumps(strict_counts),
                    _json_dumps(warnings),
                    rerank_status,
                ),
            )
    except Exception as exc:
        logger.debug("recall_log write failed: %s", exc)

def _write_recall_log_async(query, god_name, result, total_ms, fallback_lanes) -> None:
    """Enqueue a recall_log write on a daemon thread (fire-and-forget).

    Registers the thread in the module-level _RECALL_WRITER_THREADS registry so
    _drain_recall_log_writes() can deterministically join pending async writes
    before a caller tears down a temporary DB directory. Without the registry,
    a still-running writer thread re-creates SQLite -wal/-shm files inside a
    directory that is mid-rmtree, causing flaky TemporaryDirectory cleanup
    failures in tests (and the same hazard in any shutdown path).
    """
    try:
        t = threading.Thread(
            target=_write_recall_log,
            args=(query, god_name, result, total_ms, fallback_lanes),
            daemon=True,
        )
        _RECALL_WRITER_THREADS.append(t)
        t.start()
    except Exception as exc:
        logger.debug("recall_log async enqueue failed: %s", exc)


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
    budget: str | None = None,
    max_tokens: int | None = None,
    types: list[str] | None = None,
    include_sources: bool = False,
    include_raw: bool = False,
    prefer_observations: bool = False,
    query_timestamp: str | None = None,
    tags: list[str] | None = None,
    tags_match: str | None = None,
    min_scores: dict[str, float] | None = None,
    include_inactive: bool = False,
    rerank: str | None = None,
    requesting_person_id: str | None = None,
    target_person: str | None = None,
    person_context_domain: str = "profile",
    person_fact_type: str = "private",
    person_purpose: str = "general_retrieval",
    source_platform: str | None = None,
    channel_id: str | None = None,
) -> str:
    started_at = time.perf_counter()
    backend_list = _parse_backends(backends)
    payload = _jsonable(
        {
            "query": query,
            "limit": limit,
            "backends": backend_list,
            "min_score": min_score,
            "active_god": active_god,
            "include_historical": include_historical,
            "budget": budget,
            "max_tokens": max_tokens,
            "types": types,
            "include_sources": include_sources,
            "include_raw": include_raw,
            "prefer_observations": prefer_observations,
            "query_timestamp": query_timestamp,
            "tags": tags,
            "tags_match": tags_match,
            "min_scores": min_scores,
            "include_inactive": include_inactive,
            "rerank": rerank,
            "requesting_person_id": requesting_person_id,
            "target_person": target_person,
            "person_context_domain": person_context_domain,
            "person_fact_type": person_fact_type,
            "person_purpose": person_purpose,
            "source_platform": source_platform,
            "channel_id": channel_id,
        }
    )
    try:
        result = _memory_trait().retrieve(
            query=query,
            limit=limit,
            backends=backend_list,
            min_score=min_score,
            active_god=active_god or None,
            budget=budget,
            max_tokens=max_tokens,
            types=types,
            include_sources=include_sources,
            include_raw=include_raw,
            prefer_observations=prefer_observations,
            query_timestamp=query_timestamp,
            tags=tags,
            tags_match=tags_match,
            min_scores=min_scores,
            include_inactive=include_inactive,
            rerank=rerank,
            requesting_person_id=requesting_person_id,
            target_person=target_person,
            person_context_domain=person_context_domain,
            person_fact_type=person_fact_type,
            person_purpose=person_purpose,
            source_platform=source_platform,
            channel_id=channel_id,
        )
        if isinstance(result, dict) and "results" in result:
            result = dict(result)
            result["results"] = _filter_historical(list(result.get("results") or []), include_historical)
            result["returned"] = len(result["results"])
        _audit("ichor_retrieve", payload, result, True, started_at)
        # The async recall writer derives metadata (budget, token ceilings,
        # strict-scope counts, warnings, rerank status) from the result itself.
        _write_recall_log_async(
            query=query,
            god_name=active_god or "unknown",
            result=result,
            total_ms=(time.perf_counter() - started_at) * 1000.0,
            fallback_lanes=backend_list,
        )
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_retrieve failed: {exc}"}
        _audit("ichor_retrieve", payload, result, False, started_at)
        # Failed retrievals still get a recall_log row (zero-hit signal).
        _write_recall_log_async(
            query=query,
            god_name=active_god or "unknown",
            result={},
            total_ms=(time.perf_counter() - started_at) * 1000.0,
            fallback_lanes=backend_list,
        )
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


@mcp.tool(description="Run Ichor entity resolution (Phase 2D dedup pass). Dry-run by default; apply=True performs the merge.")
def ichor_entity_resolve(apply: bool = False) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {"apply": apply}
    try:
        result = entity_resolve.run(dry_run=not apply)
        _audit("ichor_entity_resolve", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_entity_resolve failed: {exc}"}
        _audit("ichor_entity_resolve", payload, result, False, started_at)
        return _json_dumps(result)


@mcp.tool(description="Return Ichor recall-audit statistics from recall_log (avg/p95 latency, slowest lane, zero-hit rate, top events).")
def ichor_recall_stats(recent: int = 200) -> str:
    _ensure_support_tables()
    started_at = time.perf_counter()
    payload = {"recent": recent}
    try:
        n = max(1, int(recent))
        with _db_conn() as conn:
            rows = conn.execute(
                "SELECT query_text, god_name, lanes_used, per_lane_latency_ms, "
                "total_ms, top_result_ids, top_result_scores, retrieved_at "
                "FROM recall_log ORDER BY id DESC LIMIT ?",
                (n,),
            ).fetchall()

        totals = [float(r["total_ms"] or 0.0) for r in rows]
        avg_total_ms = round(sum(totals) / len(totals), 3) if totals else 0.0
        p95_total_ms = 0.0
        if totals:
            s = sorted(totals)
            idx = min(len(s) - 1, int(round(0.95 * (len(s) - 1))))
            p95_total_ms = round(s[idx], 3)

        # Per-lane averages across the window.
        lane_sums: dict[str, float] = {}
        lane_counts: dict[str, int] = {}
        for r in rows:
            try:
                per = json.loads(r["per_lane_latency_ms"] or "{}")
            except Exception:
                per = {}
            if not isinstance(per, dict):
                per = {}
            for lane, ms in per.items():
                if isinstance(ms, (int, float)):
                    lane_sums[str(lane)] = lane_sums.get(str(lane), 0.0) + float(ms)
                    lane_counts[str(lane)] = lane_counts.get(str(lane), 0) + 1
        lane_avgs = {
            lane: round(lane_sums[lane] / lane_counts[lane], 3)
            for lane in lane_sums
        }
        slowest_lane = None
        if lane_avgs:
            name, avg = max(lane_avgs.items(), key=lambda kv: kv[1])
            slowest_lane = {"lane": name, "avg_latency_ms": avg}

        # Zero-hit rate: queries whose top_result_ids came back empty.
        zero_hits = 0
        event_counts: dict[str, int] = {}
        for r in rows:
            try:
                ids = json.loads(r["top_result_ids"] or "[]")
            except Exception:
                ids = []
            if not ids:
                zero_hits += 1
            for i in ids:
                event_counts[str(i)] = event_counts.get(str(i), 0) + 1
        zero_hit_rate_pct = round(100.0 * zero_hits / len(rows), 2) if rows else 0.0

        top_events = [
            {"id": eid, "count": cnt}
            for eid, cnt in sorted(event_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]
        ]

        result = {
            "recent": n,
            "queries_in_window": len(rows),
            "avg_total_ms": avg_total_ms,
            "p95_total_ms": p95_total_ms,
            "slowest_lane": slowest_lane,
            "per_lane_avg_ms": lane_avgs,
            "zero_hit_rate_pct": zero_hit_rate_pct,
            "top_retrieved_events": top_events,
            "generated_at": _now(),
        }
        _audit("ichor_recall_stats", payload, result, True, started_at)
        return _json_dumps(result)
    except Exception as exc:
        result = {"error": f"ichor_recall_stats failed: {exc}"}
        _audit("ichor_recall_stats", payload, result, False, started_at)
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
