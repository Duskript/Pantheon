#!/usr/bin/env python3
"""Benchmark default-off IchorContextEngine on tokens sent per turn.

This is the measurement gate for the course-correction marker: compare per-turn
prompt economy, not just post-threshold compression size. It is offline,
default-off, and does not mutate live Hermes profile/fleet configuration.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HERMES_AGENT = ROOT / "hermes-agent"
for candidate in (str(HERMES_AGENT), str(ROOT)):
    if candidate in sys.path:
        sys.path.remove(candidate)
for candidate in (str(ROOT), str(HERMES_AGENT)):
    sys.path.insert(0, candidate)


@dataclass(frozen=True)
class TurnCase:
    case_id: str
    query: str
    turns: int
    expect_pack: bool
    filler_topic: str
    payload_repeat: int = 26
    context_length: int = 128_000


CASES = (
    TurnCase(
        case_id="ichor-engine-build",
        query="Build the default-off IchorContextEngine prototype and benchmark tokens per turn.",
        turns=7,
        expect_pack=True,
        filler_topic="Ichor precision context engine benchmark source-backed recall frontier",
    ),
    TurnCase(
        case_id="pr138-comparison",
        query="Compare PR #138 with the Ichor context engine replacement path.",
        turns=7,
        expect_pack=True,
        filler_topic="PR #138 compressor-weight benchmark context pack default compressor comparison",
    ),
    TurnCase(
        case_id="casual-noop",
        query="ok",
        turns=7,
        expect_pack=False,
        filler_topic="casual acknowledgement unrelated filler weather chatter low signal",
    ),
    TurnCase(
        case_id="long-threshold-compressor-pressure",
        query="Ichor context engine must preserve decisions after the default compressor threshold fires.",
        turns=14,
        expect_pack=True,
        filler_topic="long transcript threshold pressure exact recall default compressor comparison",
        payload_repeat=80,
        context_length=64_000,
    ),
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_artifact_dir() -> Path:
    return Path("/tmp") / f"ichor-context-engine-turn-benchmark-{_utc_stamp()}"


def _ensure_private_artifact_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)


def _estimate_text_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4) if text else 0


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    return sum(_estimate_text_tokens(str(message.get("content", ""))) for message in messages)


def _long_payload(case: TurnCase, turn: int, role: str) -> str:
    core = (
        f"{case.filler_topic} | turn={turn} | role={role} | "
        "This is accumulated historical context that should remain exactly recallable "
        "without being resent in full every turn. "
    )
    if case.expect_pack:
        core += (
            "Relevant durable constraints: Ichor is the lossless memory substrate; "
            "IchorContextEngine is the bounded per-turn selector; compaction is fallback. "
        )
    else:
        core += "No durable memory context should be selected for the current no-op acknowledgement. "
    return core * case.payload_repeat


def _assistant_payload(case: TurnCase, turn: int) -> str:
    return (
        f"Assistant response for {case.case_id} turn {turn}. "
        "Keep exact raw-turn expansion possible while avoiding stale prompt cargo. "
    ) * 18


def _fake_summary(case: TurnCase, counter: dict[str, int], _self: Any, turns: list[dict[str, Any]], focus_topic: str | None = None) -> str:
    counter["llm_calls"] += 1
    return "\n".join([
        "## Historical Task Snapshot",
        f"Default-compressor fake summary for {case.case_id}.",
        f"Focus topic: {focus_topic or case.query}.",
        f"Compressed turns: {len(turns)}.",
        "## Key Decisions",
        "- Ichor should reduce tokens per turn by selecting only relevant source-backed context.",
        "- Default compressor remains the measured baseline, not the destination.",
    ])


def _new_default_compressor(case: TurnCase) -> tuple[Any, dict[str, int]]:
    from agent.context_compressor import ContextCompressor

    compressor = ContextCompressor(
        model="ichor-context-engine-turn-benchmark",
        quiet_mode=True,
        config_context_length=case.context_length,
    )
    counter = {"llm_calls": 0}

    def bound_fake_summary(self: Any, turns: list[dict[str, Any]], focus_topic: str | None = None, **_kwargs: Any) -> str:
        return _fake_summary(case, counter, self, turns, focus_topic)

    compressor._generate_summary = MethodType(bound_fake_summary, compressor)  # type: ignore[attr-defined]
    return compressor, counter


def _new_ichor_engine(case: TurnCase) -> Any:
    import importlib

    for loaded in list(sys.modules):
        if loaded == "plugins" or loaded.startswith("plugins.context_engine"):
            del sys.modules[loaded]
    if str(HERMES_AGENT) in sys.path:
        sys.path.remove(str(HERMES_AGENT))
    sys.path.insert(0, str(HERMES_AGENT))
    module = importlib.import_module("plugins.context_engine.ichor")
    engine = module.IchorContextEngine(fresh_tail_turns=6, max_pack_tokens=700, max_pack_ms=120)
    engine.update_model(
        model="ichor-context-engine-turn-benchmark",
        context_length=case.context_length,
    )
    engine.on_session_start("turn-benchmark")
    return engine


def _simulate_default(case: TurnCase) -> dict[str, Any]:
    compressor, counter = _new_default_compressor(case)
    active_messages: list[dict[str, str]] = [{"role": "system", "content": "Default compressor per-turn benchmark."}]
    per_turn: list[dict[str, Any]] = []
    for turn in range(1, case.turns + 1):
        active_messages.append({"role": "user", "content": _long_payload(case, turn, "user") + "\nCurrent request: " + case.query})
        before = estimate_messages_tokens(active_messages)
        compressed_this_turn = False
        if compressor.should_compress(before) and compressor.has_content_to_compress(active_messages):
            active_messages = compressor.compress(copy.deepcopy(active_messages), current_tokens=before, focus_topic=case.query, force=True)
            compressed_this_turn = True
        sent = estimate_messages_tokens(active_messages)
        per_turn.append({"turn": turn, "tokens_sent": sent, "compressed": compressed_this_turn})
        active_messages.append({"role": "assistant", "content": _assistant_payload(case, turn)})
    return {
        "engine": "full_transcript_baseline_until_threshold",
        "label": "full transcript resend baseline until compressor threshold",
        "token_estimate_method": "len_div_4_heuristic",
        "total_tokens": sum(row["tokens_sent"] for row in per_turn),
        "avg_tokens_per_turn": round(sum(row["tokens_sent"] for row in per_turn) / len(per_turn), 2),
        "compressions": sum(1 for row in per_turn if row["compressed"]),
        "llm_calls": counter["llm_calls"],
        "api_calls": 0,
        "per_turn": per_turn,
    }


def _simulate_ichor(case: TurnCase) -> dict[str, Any]:
    engine = _new_ichor_engine(case)
    raw_messages: list[dict[str, str]] = [{"role": "system", "content": "Ichor context engine per-turn benchmark."}]
    per_turn: list[dict[str, Any]] = []
    injected_any = False
    noop_clean = True
    handles_all = True
    handles_any = False
    llm_calls = 0
    api_calls = 0
    for turn in range(1, case.turns + 1):
        raw_messages.append({"role": "user", "content": _long_payload(case, turn, "user") + "\nCurrent request: " + case.query})
        assembled = engine.compress(copy.deepcopy(raw_messages), current_tokens=estimate_messages_tokens(raw_messages), focus_topic=case.query)
        sent = estimate_messages_tokens(assembled)
        joined = "\n".join(str(message.get("content", "")) for message in assembled)
        status = engine.get_status()
        metrics = status["last_pack_metrics"]
        llm_calls += int(metrics.get("llm_calls", 0) or 0)
        api_calls += int(metrics.get("api_calls", 0) or 0)
        injected = bool(status.get("last_injected"))
        injected_any = injected_any or injected
        if not case.expect_pack:
            noop_clean = noop_clean and not injected and int(metrics.get("db_reads", 0) or 0) == 0
        frontier_omitted = len([message for message in raw_messages if message.get("role") != "system"]) > engine.fresh_tail_turns
        has_handle = "Available Ichor expansions" in joined
        if frontier_omitted:
            handles_all = handles_all and has_handle
            handles_any = handles_any or has_handle
        per_turn.append({
            "turn": turn,
            "tokens_sent": sent,
            "injected": injected,
            "db_reads": int(metrics.get("db_reads", 0) or 0),
            "frontier_omitted": frontier_omitted,
            "has_expand_handle": has_handle,
        })
        raw_messages.append({"role": "assistant", "content": _assistant_payload(case, turn)})
    return {
        "engine": "ichor_context_engine",
        "token_estimate_method": "len_div_4_heuristic",
        "total_tokens": sum(row["tokens_sent"] for row in per_turn),
        "avg_tokens_per_turn": round(sum(row["tokens_sent"] for row in per_turn) / len(per_turn), 2),
        "injected_any": injected_any,
        "noop_clean": noop_clean,
        "all_turns_have_expand_handles": handles_all and handles_any,
        "llm_calls": llm_calls,
        "api_calls": api_calls,
        "per_turn": per_turn,
    }


def run_case(case: TurnCase, artifact_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    default = _simulate_default(case)
    ichor = _simulate_ichor(case)
    row_ready = ichor["total_tokens"] < default["total_tokens"]
    if case.expect_pack:
        row_ready = row_ready and bool(ichor["injected_any"])
    else:
        row_ready = row_ready and bool(ichor["noop_clean"])
    row = {
        "case_id": case.case_id,
        "query": case.query,
        "turns": case.turns,
        "expect_pack": case.expect_pack,
        "default_compressor": default,
        "ichor_context_engine": ichor,
        "tokens_saved": default["total_tokens"] - ichor["total_tokens"],
        "tokens_saved_ratio": round((default["total_tokens"] - ichor["total_tokens"]) / max(default["total_tokens"], 1), 4),
        "row_ready": row_ready,
        "wall_ms": int((time.perf_counter() - started) * 1000),
        "would_mutate_runtime": False,
        "would_change_config": False,
        "would_enable_lcm": False,
        "would_flip_fleet_default": False,
        "default_compressor_exercised": default["compressions"] > 0,
    }
    (artifact_dir / f"{case.case_id}.json").write_text(json.dumps(row, indent=2, sort_keys=True), encoding="utf-8")
    return row


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    default_total = sum(row["default_compressor"]["total_tokens"] for row in rows)
    ichor_total = sum(row["ichor_context_engine"]["total_tokens"] for row in rows)
    turns = sum(int(row["turns"]) for row in rows)
    blockers: list[str] = []
    if ichor_total >= default_total:
        blockers.append("ichor_not_lower_total_tokens")
    if not all(row["row_ready"] for row in rows):
        blockers.append("row_not_ready")
    if not all(row["ichor_context_engine"]["llm_calls"] == 0 and row["ichor_context_engine"]["api_calls"] == 0 for row in rows):
        blockers.append("ichor_hot_path_llm_or_api")
    noop_rows = [row for row in rows if not row["expect_pack"]]
    if not all(row["ichor_context_engine"]["noop_clean"] for row in noop_rows):
        blockers.append("noop_not_clean")
    threshold_rows = [row for row in rows if row["default_compressor"]["compressions"] > 0]
    if not threshold_rows:
        blockers.append("default_compressor_never_exercised")
    if not all(row["ichor_context_engine"]["all_turns_have_expand_handles"] for row in rows):
        blockers.append("missing_expand_handles")
    return {
        "rows_run": len(rows),
        "turns_run": turns,
        "default_compressor_exercised_rows": len(threshold_rows),
        "threshold_crossing_case_ids": [row["case_id"] for row in threshold_rows],
        "baseline_label": "full transcript resend baseline until compressor threshold",
        "token_estimate_method": "len_div_4_heuristic",
        "default_total_tokens": default_total,
        "ichor_total_tokens": ichor_total,
        "tokens_saved": default_total - ichor_total,
        "tokens_saved_ratio": round((default_total - ichor_total) / max(default_total, 1), 4),
        "default_avg_tokens_per_turn": round(default_total / max(turns, 1), 2),
        "ichor_avg_tokens_per_turn": round(ichor_total / max(turns, 1), 2),
        "all_ichor_no_llm_api": all(row["ichor_context_engine"]["llm_calls"] == 0 and row["ichor_context_engine"]["api_calls"] == 0 for row in rows),
        "all_noop_rows_clean": all(row["ichor_context_engine"]["noop_clean"] for row in noop_rows),
        "all_rows_have_expand_handles": all(row["ichor_context_engine"]["all_turns_have_expand_handles"] for row in rows),
        "all_no_runtime_mutation": all(not row["would_mutate_runtime"] and not row["would_change_config"] and not row["would_enable_lcm"] and not row["would_flip_fleet_default"] for row in rows),
        "blockers": blockers,
        "benchmark_ready": not blockers,
    }


def _write_report(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# IchorContextEngine Tokens-Per-Turn Benchmark",
        "",
        f"- Benchmark ready: `{summary['benchmark_ready']}`",
        f"- Baseline: `{summary['baseline_label']}`",
        f"- Token estimate method: `{summary['token_estimate_method']}`",
        f"- Default/baseline estimated tokens: `{summary['default_total_tokens']}`",
        f"- Ichor estimated tokens: `{summary['ichor_total_tokens']}`",
        f"- Tokens saved ratio: `{summary['tokens_saved_ratio']}`",
        f"- Ichor avg tokens/turn: `{summary['ichor_avg_tokens_per_turn']}`",
        "",
        "| Case | Default total | Ichor total | Saved ratio | Ready |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['default_compressor']['total_tokens']} | "
            f"{row['ichor_context_engine']['total_tokens']} | {row['tokens_saved_ratio']} | {row['row_ready']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark(artifact_dir: Path | None = None) -> dict[str, Any]:
    artifact_dir = artifact_dir or _default_artifact_dir()
    _ensure_private_artifact_dir(artifact_dir)
    rows = [run_case(case, artifact_dir) for case in CASES]
    summary = _summarize(rows)
    summary_path = artifact_dir / "summary.json"
    report_path = artifact_dir / "BENCHMARK.md"
    payload = {
        "mode": "ichor_context_engine_turn_benchmark",
        "artifact_dir": str(artifact_dir),
        "summary": summary,
        "rows": rows,
        "summary_path": str(summary_path),
        "report_path": str(report_path),
    }
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_report(report_path, summary, rows)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "text"), default="text")
    args = parser.parse_args(argv)
    payload = run_benchmark(args.artifact_dir)
    if args.format == "json":
        print(json.dumps(payload, sort_keys=True))
    else:
        summary = payload["summary"]
        print(f"benchmark_ready={summary['benchmark_ready']} artifact_dir={payload['artifact_dir']}")
    return 0 if payload["summary"]["benchmark_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
