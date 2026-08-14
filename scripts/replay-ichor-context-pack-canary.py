#!/usr/bin/env python3
"""Replay-only canary readiness harness for Ichor context packs.

This command runs a bounded matrix through the dry-run context-pack builder,
saves per-case JSON artifacts, and emits a readiness report. It is deliberately
not a live rollout tool: it has no profile/config mutation, no service control,
no session operations, no transcript rewrite, and no model compression call.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HERMES_AGENT = ROOT / "hermes-agent"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERMES_AGENT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT))


@dataclass(frozen=True)
class MatrixCase:
    case_id: str
    god: str
    phase: str
    query: str
    category: str
    min_returned: int = 1
    expected_zero: bool = False


MATRIX: tuple[MatrixCase, ...] = (
    MatrixCase(
        "hermes-operator-followup-status",
        "hermes",
        "ops",
        "where did we leave the Ichor context pack?",
        "operator_followup",
        min_returned=2,
    ),
    MatrixCase(
        "hermes-operator-followup-canary",
        "hermes",
        "ops",
        "should we enable the Ichor context pack canary now?",
        "operator_followup",
        min_returned=1,
    ),
    MatrixCase("hephaestus-conductor-debug", "hephaestus", "debug", "Conductor v2", "golden", min_returned=3),
    MatrixCase("thoth-conductor-research", "thoth", "research", "Conductor v2", "golden", min_returned=3),
    MatrixCase(
        "rheta-pricing-copywriting",
        "rheta",
        "copywriting",
        "Pantheon pricing managed retainer dedicated infrastructure",
        "golden",
        min_returned=2,
    ),
    MatrixCase("hermes-lcm-ops", "hermes", "ops", "LCM", "risk_recall", min_returned=1),
    MatrixCase("thoth-lcm-research", "thoth", "research", "LCM", "risk_recall", min_returned=1),
    MatrixCase("hermes-noop-chat", "hermes", "chat", "random casual hello", "noop", expected_zero=True, min_returned=0),
    MatrixCase("thoth-noop-chat", "thoth", "chat", "random casual hello", "noop", expected_zero=True, min_returned=0),
    MatrixCase("hephaestus-noop-chat", "hephaestus", "chat", "random casual hello", "noop", expected_zero=True, min_returned=0),
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_artifact_dir() -> Path:
    return Path("/tmp") / f"ichor-context-pack-canary-{_utc_stamp()}"


def _estimate_baseline(query: str) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": "Replay-only canary readiness harness."},
        {"role": "user", "content": query},
    ]
    tokens = sum((len(message["content"]) + 3) // 4 for message in messages)
    try:
        from agent.model_metadata import estimate_messages_tokens_rough
        tokens = int(estimate_messages_tokens_rough(messages))
    except Exception:
        pass

    try:
        from agent.context_compressor import ContextCompressor
        compressor = ContextCompressor(
            model="canary-replay-baseline",
            quiet_mode=True,
            config_context_length=128_000,
        )
        return {
            "available": True,
            "engine": compressor.name,
            "tokens_estimated": tokens,
            "source_link_count": 0,
            "llm_calls": 0,
            "api_calls": 0,
            "would_call_model_method": False,
            "would_compress_by_threshold": bool(compressor.should_compress(tokens)),
            "has_compressible_window": bool(compressor.has_content_to_compress(messages)),
        }
    except Exception as exc:
        return {
            "available": False,
            "error": str(exc),
            "tokens_estimated": tokens,
            "source_link_count": 0,
            "llm_calls": 0,
            "api_calls": 0,
            "would_call_model_method": False,
        }


def _row_from_case(case: MatrixCase, artifact_dir: Path) -> tuple[dict[str, Any], Path]:
    from lib.ichor.context_pack import build_context_pack

    started = time.perf_counter()
    pack = build_context_pack(
        case.query,
        god_name=case.god,
        phase=case.phase,
        max_items=8,
        max_tokens=900,
        max_ms=350,
        include_graph=True,
        dry_run=True,
    )
    wall_ms = int((time.perf_counter() - started) * 1000)
    metrics = pack.get("metrics", {})
    coverage = pack.get("coverage", {})
    source_links = pack.get("source_links", []) or []
    baseline = _estimate_baseline(case.query)
    injectable = str(pack.get("injectable_context", "") or "")
    returned = int(coverage.get("returned", 0) or 0)
    db_reads = int(metrics.get("db_reads", 0) or 0)
    tokens_estimated = int(metrics.get("tokens_estimated", 0) or 0)
    source_link_count = len(source_links)

    no_mutation_flags = {
        "would_mutate_runtime": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "would_change_config": False,
        "would_restart_gateway": False,
    }
    zero_ok = (
        returned == 0
        and db_reads == 0
        and tokens_estimated == 0
        and len(injectable) == 0
    )
    source_ok = returned >= case.min_returned and source_link_count >= case.min_returned
    if case.expected_zero:
        quality_ok = zero_ok and coverage.get("status") == "low"
    else:
        quality_ok = source_ok and coverage.get("status") == "ok"

    row = {
        "case_id": case.case_id,
        "god": case.god,
        "phase": case.phase,
        "query": case.query,
        "category": case.category,
        "expected_zero": case.expected_zero,
        "min_returned": case.min_returned,
        "coverage_status": coverage.get("status"),
        "returned": returned,
        "omitted": int(coverage.get("omitted", 0) or 0),
        "warnings": list(coverage.get("warnings", []) or []) + list(pack.get("warnings", []) or []),
        "source_link_count": source_link_count,
        "source_titles": [str(link.get("title", "")) for link in source_links],
        "source_paths": [str(link.get("source_path", "")) for link in source_links],
        "injectable_context_length": len(injectable),
        "tokens_estimated": tokens_estimated,
        "wall_ms": int(metrics.get("wall_ms", wall_ms) or wall_ms),
        "db_reads": db_reads,
        "db_writes": int(metrics.get("db_writes", 0) or 0),
        "llm_calls": int(metrics.get("llm_calls", 0) or 0),
        "api_calls": int(metrics.get("api_calls", 0) or 0),
        "rss_delta_kb": metrics.get("rss_delta_kb"),
        "baseline": baseline,
        "grounding_improved_vs_baseline": source_link_count > int(baseline.get("source_link_count", 0) or 0),
        "row_safety_pass": (
            int(metrics.get("llm_calls", 0) or 0) == 0
            and int(metrics.get("api_calls", 0) or 0) == 0
            and int(metrics.get("db_writes", 0) or 0) == 0
        ),
        "row_quality_pass": quality_ok,
        **no_mutation_flags,
    }
    case_path = artifact_dir / f"{case.case_id}.json"
    case_path.write_text(json.dumps({"row": row, "pack": pack}, indent=2, sort_keys=True), encoding="utf-8")
    return row, case_path


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive_rows = [row for row in rows if not row["expected_zero"]]
    noop_rows = [row for row in rows if row["expected_zero"]]
    all_no_llm_api = all(row["llm_calls"] == 0 and row["api_calls"] == 0 for row in rows)
    all_no_db_writes = all(row["db_writes"] == 0 for row in rows)
    all_safety_flags_false = all(
        not row["would_mutate_runtime"]
        and not row["would_rotate_session"]
        and not row["would_rewrite_transcript"]
        and not row["would_change_config"]
        and not row["would_restart_gateway"]
        for row in rows
    )
    noop_rows_clean = all(row["row_quality_pass"] for row in noop_rows)
    source_backed_rows_ok = all(row["row_quality_pass"] for row in positive_rows)
    operator_followup_rows_ok = all(
        row["row_quality_pass"]
        for row in rows
        if row["category"] == "operator_followup"
    )
    grounding_rows_improved = all(
        row["grounding_improved_vs_baseline"] for row in positive_rows
    )
    safety_pass = all_no_llm_api and all_no_db_writes and all_safety_flags_false
    quality_pass = noop_rows_clean and source_backed_rows_ok and operator_followup_rows_ok and grounding_rows_improved
    blockers: list[str] = []
    if not safety_pass:
        blockers.append("safety_invariants_failed")
    if not noop_rows_clean:
        blockers.append("noop_rows_not_clean")
    if not source_backed_rows_ok:
        blockers.append("source_backed_rows_below_threshold")
    if not grounding_rows_improved:
        blockers.append("source_grounding_not_improved_vs_baseline")

    return {
        "rows_run": len(rows),
        "positive_rows": len(positive_rows),
        "noop_rows": len(noop_rows),
        "safety_pass": safety_pass,
        "quality_pass": quality_pass,
        "canary_ready": safety_pass and quality_pass,
        "all_no_llm_api": all_no_llm_api,
        "all_no_db_writes": all_no_db_writes,
        "all_safety_flags_false": all_safety_flags_false,
        "noop_rows_clean": noop_rows_clean,
        "source_backed_rows_ok": source_backed_rows_ok,
        "operator_followup_rows_ok": operator_followup_rows_ok,
        "grounding_rows_improved": grounding_rows_improved,
        "max_wall_ms": max((int(row["wall_ms"] or 0) for row in rows), default=0),
        "max_tokens_estimated": max((int(row["tokens_estimated"] or 0) for row in rows), default=0),
        "total_db_reads": sum(int(row["db_reads"] or 0) for row in rows),
        "total_db_writes": sum(int(row["db_writes"] or 0) for row in rows),
        "blockers": blockers,
    }


def _format_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Ichor Context-Pack Canary Replay Report",
        "",
        f"Generated: {payload['generated_at']}",
        f"Mode: {payload['mode']}",
        f"Artifact dir: {payload['artifact_dir']}",
        "",
        "## Verdict",
        f"- safety_pass: {str(summary['safety_pass']).lower()}",
        f"- quality_pass: {str(summary['quality_pass']).lower()}",
        f"- canary_ready: {str(summary['canary_ready']).lower()}",
        f"- blockers: {', '.join(summary['blockers']) if summary['blockers'] else 'none'}",
        "",
        "## Safety boundary",
        "- replay-only: true",
        "- live profile mutation: false",
        "- gateway restart: false",
        "- session rotation: false",
        "- transcript rewrite: false",
        "- model/API calls: false",
        "",
        "## Matrix rows",
    ]
    for row in payload["rows"]:
        lines.append(
            f"- {row['case_id']}: {row['coverage_status']} returned={row['returned']} "
            f"sources={row['source_link_count']} noop={str(row['expected_zero']).lower()} "
            f"quality={str(row['row_quality_pass']).lower()}"
        )
    return "\n".join(lines) + "\n"


def run_matrix(artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    case_paths: list[str] = []
    for case in MATRIX:
        row, path = _row_from_case(case, artifact_dir)
        rows.append(row)
        case_paths.append(str(path))

    payload = {
        "mode": "dry_run_replay",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_dir": str(artifact_dir),
        "would_mutate_runtime": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "would_change_config": False,
        "would_restart_gateway": False,
        "rows": rows,
        "summary": _summarize(rows),
        "case_paths": case_paths,
    }
    summary_path = artifact_dir / "summary.json"
    report_path = artifact_dir / "report.md"
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
    payload = run_matrix(args.artifact_dir or _default_artifact_dir())
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_report(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
