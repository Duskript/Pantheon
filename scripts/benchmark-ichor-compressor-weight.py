#!/usr/bin/env python3
"""Offline compressor-weight benchmark for Ichor context packs.

This is the missing Phase 0/2 gate from the original handoff: exercise Hermes'
default ``ContextCompressor`` on synthetic long transcripts that actually cross
its threshold, then compare the Ichor context-pack candidate as a bounded memory
augmentation. The default compressor path uses a deterministic fake summary so
this benchmark never calls an LLM provider or mutates runtime state.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HERMES_AGENT = ROOT / "hermes-agent"
if str(HERMES_AGENT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MAX_PACK_TOKENS = 900


@dataclass(frozen=True)
class BenchmarkCase:
    """One benchmark row for compressor-vs-Ichor measurement."""

    case_id: str
    god: str
    phase: str
    query: str
    expect_injection: bool
    min_sources: int
    max_pack_tokens: int = MAX_PACK_TOKENS


CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        "hermes-lcm-risk-long-thread",
        "hermes",
        "ops",
        "LCM risk recall and Ichor compressor replacement",
        True,
        2,
    ),
    BenchmarkCase(
        "thoth-lcm-risk-long-thread",
        "thoth",
        "research",
        "LCM risk recall and Ichor context-pack compressor augmentation",
        True,
        2,
    ),
    BenchmarkCase(
        "hephaestus-conductor-long-debug-thread",
        "hephaestus",
        "debug",
        "Conductor v2",
        True,
        3,
    ),
    BenchmarkCase(
        "rheta-pricing-long-copy-thread",
        "rheta",
        "copywriting",
        "Pantheon pricing managed retainer dedicated infrastructure",
        True,
        2,
    ),
    BenchmarkCase(
        "casual-long-noop",
        "hermes",
        "chat",
        "random casual hello",
        False,
        0,
    ),
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_artifact_dir() -> Path:
    return Path("/tmp") / f"ichor-compressor-weight-benchmark-{_utc_stamp()}"


def _ensure_private_artifact_dir(artifact_dir: Path) -> None:
    """Create artifact directory with owner-only permissions.

    Case JSON artifacts include internal source paths/titles. Keep the benchmark
    dry-run, but avoid making that metadata world-readable under shared /tmp.
    """
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.chmod(0o700)


def _rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return None


def _estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    try:
        from agent.model_metadata import estimate_messages_tokens_rough
    except Exception:
        return sum((len(str(message.get("content", ""))) + 3) // 4 for message in messages)
    return int(estimate_messages_tokens_rough(messages))


def _estimate_text_tokens(text: str) -> int:
    return (len(text) + 3) // 4 if text else 0


def _long_content(case: BenchmarkCase, turn: int, role: str) -> str:
    topic = case.query
    repeated = (
        f"{topic} | Ichor memory expansion | compressor-weight benchmark | "
        f"source grounding | no LCM re-enable | turn {turn} | role {role}. "
    )
    if case.expect_injection:
        anchor = (
            "The durable constraint is that Ichor should provide LCM-like recall "
            "by selecting source-backed memory while the default compressor remains "
            "the baseline until benchmark proof exists. "
        )
    else:
        anchor = (
            "Casual filler for a long transcript that should compress normally, "
            "but should not trigger Ichor memory selection for the current query. "
        )
    return (anchor + repeated) * 18


def _make_long_transcript(case: BenchmarkCase, threshold_tokens: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "Synthetic long transcript for the Ichor compressor-weight benchmark. "
                "It is offline fixture data and carries no live runtime state."
            ),
        }
    ]
    turn = 0
    while True:
        turn += 1
        messages.append({"role": "user", "content": _long_content(case, turn, "user")})
        messages.append({"role": "assistant", "content": _long_content(case, turn, "assistant")})
        if turn >= 42 and _estimate_messages_tokens(messages) > threshold_tokens + 12_000:
            return messages
        if turn >= 90:
            return messages


def _fake_summary(case: BenchmarkCase, call_counter: dict[str, int], _self: Any, turns: list[dict[str, Any]], focus_topic: str | None = None) -> str:
    call_counter["llm_calls"] += 1
    first = str(turns[0].get("content", ""))[:180] if turns else ""
    last = str(turns[-1].get("content", ""))[:180] if turns else ""
    return "\n".join(
        [
            "## Historical Task Snapshot",
            f"Synthetic benchmark summary for {case.case_id}.",
            f"Focus topic: {focus_topic or case.query}.",
            f"Compressed turns: {len(turns)}.",
            "## Key Decisions",
            "- Preserve source-backed Ichor memory context without re-enabling LCM.",
            "- Keep default compressor as measured baseline until benchmark gates pass.",
            "## Evidence Samples",
            f"- First compressed sample: {first}",
            f"- Last compressed sample: {last}",
        ]
    )


def _run_default_compressor(case: BenchmarkCase) -> dict[str, Any]:
    started = time.perf_counter()
    rss_before = _rss_kb()
    try:
        from agent.context_compressor import ContextCompressor
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "api_calls": 0,
            "llm_calls": 0,
            "called_compress_method": False,
        }

    compressor = ContextCompressor(
        model="compressor-weight-benchmark",
        quiet_mode=True,
        config_context_length=128_000,
    )
    messages = _make_long_transcript(case, compressor.threshold_tokens)
    tokens_before = _estimate_messages_tokens(messages)
    call_counter = {"llm_calls": 0}

    def bound_fake_summary(self: Any, turns: list[dict[str, Any]], focus_topic: str | None = None) -> str:
        return _fake_summary(case, call_counter, self, turns, focus_topic)

    compressor._generate_summary = MethodType(bound_fake_summary, compressor)  # type: ignore[attr-defined]
    would_compress = bool(compressor.should_compress(tokens_before))
    has_window = bool(compressor.has_content_to_compress(messages))
    compressed = compressor.compress(copy.deepcopy(messages), current_tokens=tokens_before, force=True)
    tokens_after = _estimate_messages_tokens(compressed)
    rss_after = _rss_kb()
    return {
        "available": True,
        "engine": compressor.name,
        "threshold_tokens": compressor.threshold_tokens,
        "tail_token_budget": compressor.tail_token_budget,
        "tokens_before": tokens_before,
        "tokens_after": tokens_after,
        "tokens_saved": tokens_before - tokens_after,
        "message_count_before": len(messages),
        "message_count_after": len(compressed),
        "would_compress_by_threshold": would_compress,
        "has_compressible_window": has_window,
        "called_compress_method": True,
        "compression_count": compressor.compression_count,
        "summary_fallback_used": bool(getattr(compressor, "_last_summary_fallback_used", False)),
        "summary_dropped_count": int(getattr(compressor, "_last_summary_dropped_count", 0) or 0),
        "llm_calls": int(call_counter["llm_calls"]),
        "api_calls": 0,
        "wall_ms": int((time.perf_counter() - started) * 1000),
        "rss_delta_kb": None if rss_before is None or rss_after is None else rss_after - rss_before,
    }


def _failed_ichor_pack(error: str, started: float) -> dict[str, Any]:
    """Return a fail-closed candidate row when Ichor pack generation is unavailable."""
    return {
        "coverage_status": "error",
        "returned": 0,
        "omitted": 0,
        "warnings": [error],
        "injected": False,
        "injectable_context_length": 0,
        "source_link_count": 0,
        "source_titles": [],
        "source_paths": [],
        "tokens_estimated": 0,
        "db_reads": 0,
        "db_writes": 0,
        "rows_examined": 0,
        "llm_calls": 0,
        "api_calls": 0,
        "wall_ms": int((time.perf_counter() - started) * 1000),
        "rss_delta_kb": None,
        "pack": {"error": error},
    }


def _run_ichor_context_pack(case: BenchmarkCase) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        from lib.ichor.context_pack import build_context_pack
    except Exception as exc:
        return _failed_ichor_pack(f"context_pack_import_failed: {exc}", started)

    try:
        pack = build_context_pack(
            case.query,
            god_name=case.god,
            phase=case.phase,
            max_items=8,
            max_tokens=case.max_pack_tokens,
            max_ms=350,
            include_graph=True,
            dry_run=True,
        )
    except Exception as exc:
        return _failed_ichor_pack(f"context_pack_build_failed: {exc}", started)
    coverage = pack.get("coverage", {})
    metrics = pack.get("metrics", {})
    source_links = pack.get("source_links", []) or []
    injectable = str(pack.get("injectable_context", "") or "")
    return {
        "coverage_status": coverage.get("status"),
        "returned": int(coverage.get("returned", 0) or 0),
        "omitted": int(coverage.get("omitted", 0) or 0),
        "warnings": list(coverage.get("warnings", []) or []) + list(pack.get("warnings", []) or []),
        "injected": bool(injectable),
        "injectable_context_length": len(injectable),
        "source_link_count": len(source_links),
        "source_titles": [str(link.get("title", "")) for link in source_links],
        "source_paths": [str(link.get("source_path", "")) for link in source_links],
        "tokens_estimated": int(metrics.get("tokens_estimated", 0) or 0),
        "db_reads": int(metrics.get("db_reads", 0) or 0),
        "db_writes": int(metrics.get("db_writes", 0) or 0),
        "rows_examined": int(metrics.get("rows_examined", 0) or 0),
        "llm_calls": int(metrics.get("llm_calls", 0) or 0),
        "api_calls": int(metrics.get("api_calls", 0) or 0),
        "wall_ms": int(metrics.get("wall_ms", int((time.perf_counter() - started) * 1000)) or 0),
        "rss_delta_kb": metrics.get("rss_delta_kb"),
        "pack": pack,
    }


def run_case(case: BenchmarkCase, artifact_dir: Path) -> tuple[dict[str, Any], Path]:
    _ensure_private_artifact_dir(artifact_dir)
    default = _run_default_compressor(case)
    candidate = _run_ichor_context_pack(case)
    no_mutation_flags = {
        "would_mutate_runtime": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "would_change_config": False,
        "would_restart_gateway": False,
    }

    default_ok = (
        bool(default.get("available"))
        and bool(default.get("would_compress_by_threshold"))
        and bool(default.get("has_compressible_window"))
        and bool(default.get("called_compress_method"))
        and int(default.get("api_calls", 0) or 0) == 0
        and int(default.get("llm_calls", 0) or 0) == 1
        and int(default.get("tokens_after", 0) or 0) < int(default.get("tokens_before", 0) or 0)
        and int(default.get("message_count_after", 0) or 0) < int(default.get("message_count_before", 0) or 0)
    )
    if case.expect_injection:
        candidate_quality_ok = (
            candidate["injected"]
            and candidate["source_link_count"] >= case.min_sources
            and candidate["coverage_status"] == "ok"
        )
    else:
        candidate_quality_ok = (
            not candidate["injected"]
            and candidate["source_link_count"] == 0
            and candidate["db_reads"] == 0
            and candidate["tokens_estimated"] == 0
        )
    candidate_safety_ok = (
        candidate["llm_calls"] == 0
        and candidate["api_calls"] == 0
        and candidate["db_writes"] == 0
        and candidate["tokens_estimated"] <= case.max_pack_tokens
    )

    tokens_after = int(default.get("tokens_after", 0) or 0)
    pack_tokens = int(candidate["tokens_estimated"] or 0)
    hybrid_tokens = tokens_after + pack_tokens
    row = {
        "case_id": case.case_id,
        "god": case.god,
        "phase": case.phase,
        "query": case.query,
        "expect_injection": case.expect_injection,
        "min_sources": case.min_sources,
        "max_pack_tokens": case.max_pack_tokens,
        "default_compressor": default,
        "ichor_context_pack": {k: v for k, v in candidate.items() if k != "pack"},
        "hybrid_projection": {
            "tokens_after_default_plus_pack": hybrid_tokens,
            "pack_overhead_tokens": pack_tokens,
            "pack_overhead_pct_of_default_after": round((pack_tokens / tokens_after * 100), 2) if tokens_after else None,
            "would_rewrite_static_prefix": False,
        },
        "default_ok": default_ok,
        "candidate_quality_ok": candidate_quality_ok,
        "candidate_safety_ok": candidate_safety_ok,
        "row_ready": default_ok and candidate_quality_ok and candidate_safety_ok,
        **no_mutation_flags,
    }
    case_path = artifact_dir / f"{case.case_id}.json"
    case_path.write_text(json.dumps({"row": row, "pack": candidate["pack"]}, indent=2, sort_keys=True), encoding="utf-8")
    return row, case_path


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if row["expect_injection"]]
    noop_rows = [row for row in rows if not row["expect_injection"]]
    default_exercised = [
        row for row in rows
        if row["default_compressor"].get("called_compress_method")
        and row["default_compressor"].get("has_compressible_window")
        and row["default_compressor"].get("would_compress_by_threshold")
    ]
    all_default_rows_reduced_tokens = all(
        int(row["default_compressor"].get("tokens_after", 0) or 0)
        < int(row["default_compressor"].get("tokens_before", 0) or 0)
        for row in rows
    )
    all_no_runtime_mutation = all(
        not row["would_mutate_runtime"]
        and not row["would_rotate_session"]
        and not row["would_rewrite_transcript"]
        and not row["would_change_config"]
        and not row["would_restart_gateway"]
        for row in rows
    )
    all_candidate_no_llm_api = all(
        row["ichor_context_pack"]["llm_calls"] == 0
        and row["ichor_context_pack"]["api_calls"] == 0
        for row in rows
    )
    all_candidate_no_db_writes = all(row["ichor_context_pack"]["db_writes"] == 0 for row in rows)
    all_pack_tokens_bounded = all(
        row["ichor_context_pack"]["tokens_estimated"] <= row["max_pack_tokens"]
        for row in rows
    )
    positive_rows_source_backed = all(
        row["ichor_context_pack"]["source_link_count"] >= row["min_sources"]
        and row["ichor_context_pack"]["injected"]
        for row in positive_rows
    )
    noop_rows_clean = all(
        not row["ichor_context_pack"]["injected"]
        and row["ichor_context_pack"]["db_reads"] == 0
        and row["ichor_context_pack"]["tokens_estimated"] == 0
        for row in noop_rows
    )
    row_ready_all = all(row["row_ready"] for row in rows)
    blockers: list[str] = []
    if len(default_exercised) < len(positive_rows):
        blockers.append("default_compressor_not_exercised_on_positive_rows")
    if not all_default_rows_reduced_tokens:
        blockers.append("default_compressor_did_not_reduce_tokens")
    if not all_no_runtime_mutation:
        blockers.append("runtime_mutation_flag_set")
    if not all_candidate_no_llm_api:
        blockers.append("candidate_used_llm_or_api")
    if not all_candidate_no_db_writes:
        blockers.append("candidate_wrote_db")
    if not all_pack_tokens_bounded:
        blockers.append("candidate_pack_exceeded_token_budget")
    if not positive_rows_source_backed:
        blockers.append("positive_rows_not_source_backed")
    if not noop_rows_clean:
        blockers.append("noop_rows_not_clean")
    if not row_ready_all:
        blockers.append("one_or_more_rows_not_ready")

    return {
        "rows_run": len(rows),
        "positive_rows": len(positive_rows),
        "noop_rows": len(noop_rows),
        "default_compressor_exercised_rows": len(default_exercised),
        "all_default_rows_reduced_tokens": all_default_rows_reduced_tokens,
        "all_no_runtime_mutation": all_no_runtime_mutation,
        "all_candidate_no_llm_api": all_candidate_no_llm_api,
        "all_candidate_no_db_writes": all_candidate_no_db_writes,
        "all_pack_tokens_bounded": all_pack_tokens_bounded,
        "positive_rows_source_backed": positive_rows_source_backed,
        "noop_rows_clean": noop_rows_clean,
        "max_default_wall_ms": max((int(row["default_compressor"].get("wall_ms", 0) or 0) for row in rows), default=0),
        "max_candidate_wall_ms": max((int(row["ichor_context_pack"].get("wall_ms", 0) or 0) for row in rows), default=0),
        "max_candidate_tokens": max((int(row["ichor_context_pack"].get("tokens_estimated", 0) or 0) for row in rows), default=0),
        "total_candidate_db_reads": sum(int(row["ichor_context_pack"].get("db_reads", 0) or 0) for row in rows),
        "total_candidate_db_writes": sum(int(row["ichor_context_pack"].get("db_writes", 0) or 0) for row in rows),
        "blockers": blockers,
        "benchmark_ready": not blockers,
    }


def _format_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Ichor Compressor-Weight Benchmark",
        "",
        f"mode: {payload['mode']}",
        f"benchmark_ready: {str(summary['benchmark_ready']).lower()}",
        f"rows_run: {summary['rows_run']}",
        f"default_compressor_exercised_rows: {summary['default_compressor_exercised_rows']}",
        f"all_default_rows_reduced_tokens: {str(summary['all_default_rows_reduced_tokens']).lower()}",
        f"all_candidate_no_llm_api: {str(summary['all_candidate_no_llm_api']).lower()}",
        f"all_candidate_no_db_writes: {str(summary['all_candidate_no_db_writes']).lower()}",
        f"noop_rows_clean: {str(summary['noop_rows_clean']).lower()}",
        f"max_candidate_tokens: {summary['max_candidate_tokens']}",
        "",
        "## Rows",
    ]
    for row in payload["rows"]:
        default = row["default_compressor"]
        candidate = row["ichor_context_pack"]
        lines.extend(
            [
                f"### {row['case_id']}",
                f"row_ready: {str(row['row_ready']).lower()}",
                (
                    "default: "
                    f"{default.get('tokens_before')} → {default.get('tokens_after')} tokens, "
                    f"messages {default.get('message_count_before')} → {default.get('message_count_after')}, "
                    f"llm_calls={default.get('llm_calls')} api_calls={default.get('api_calls')}"
                ),
                (
                    "ichor: "
                    f"injected={str(candidate.get('injected')).lower()} "
                    f"sources={candidate.get('source_link_count')} "
                    f"tokens={candidate.get('tokens_estimated')} "
                    f"db_reads={candidate.get('db_reads')}"
                ),
                "",
            ]
        )
    if summary["blockers"]:
        lines.extend(["## Blockers", *[f"- {blocker}" for blocker in summary["blockers"]]])
    return "\n".join(lines).rstrip() + "\n"


def run_benchmark(artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    case_paths: list[str] = []
    for case in CASES:
        row, case_path = run_case(case, artifact_dir)
        rows.append(row)
        case_paths.append(str(case_path))
    summary = _summarize(rows)
    payload = {
        "mode": "compressor_weight_benchmark",
        "artifact_dir": str(artifact_dir),
        "would_mutate_runtime": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "would_change_config": False,
        "would_restart_gateway": False,
        "summary": summary,
        "rows": rows,
        "case_paths": case_paths,
    }
    summary_path = artifact_dir / "summary.json"
    report_path = artifact_dir / "BENCHMARK.md"
    payload["summary_path"] = str(summary_path)
    payload["report_path"] = str(report_path)
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(_format_report(payload), encoding="utf-8")
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    payload = run_benchmark(args.artifact_dir or _default_artifact_dir())
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_report(payload), end="")
    return 0 if payload["summary"]["benchmark_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
