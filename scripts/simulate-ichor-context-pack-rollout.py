#!/usr/bin/env python3
"""Controlled prompt-injection simulation for Ichor context packs.

This is the gate after replay readiness and before any live/default-on wiring.
It composes prompt-shaped messages with the candidate Ichor context pack inserted
as an extra system message only when source-backed memory is actually returned.

Safety boundary:
- no model calls
- no config writes
- no gateway/service control
- no session rotation
- no transcript rewrite
- no runtime DB writes

The simulation validates source titles for prompt hygiene. Source paths are
recorded raw in artifacts for provenance/debugging and are intentionally not
render-sanitized here; the builder remains responsible for generating safe
injectable prompt text.
"""
from __future__ import annotations

import argparse
import json
import sys
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
class SimulationCase:
    case_id: str
    god: str
    phase: str
    query: str
    expected_injection: bool
    min_sources: int = 1
    max_items: int = 8
    max_tokens: int = 900
    max_ms: int = 350


MATRIX: tuple[SimulationCase, ...] = (
    SimulationCase(
        case_id="hermes-context-pack-followup",
        god="hermes",
        phase="ops",
        query="where did we leave the Ichor context pack?",
        expected_injection=True,
        min_sources=2,
    ),
    SimulationCase(
        case_id="hermes-canary-decision",
        god="hermes",
        phase="ops",
        query="should we enable the Ichor context pack canary now?",
        expected_injection=True,
        min_sources=1,
    ),
    SimulationCase("hephaestus-conductor-debug", "hephaestus", "debug", "Conductor v2", True, min_sources=3),
    SimulationCase("thoth-conductor-research", "thoth", "research", "Conductor v2", True, min_sources=3),
    SimulationCase("rheta-pricing-copywriting", "rheta", "copywriting", "Pantheon pricing managed retainer dedicated infrastructure", True, min_sources=2),
    SimulationCase("hermes-noop-chat", "hermes", "chat", "random casual hello", False, min_sources=0),
    SimulationCase("thoth-noop-chat", "thoth", "chat", "random casual hello", False, min_sources=0),
    SimulationCase("hephaestus-noop-chat", "hephaestus", "chat", "random casual hello", False, min_sources=0),
)


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_artifact_dir() -> Path:
    return Path("/tmp") / f"ichor-context-pack-rollout-sim-{_utc_stamp()}"


def _estimate_tokens_text(text: str) -> int:
    try:
        from agent.model_metadata import estimate_tokens_rough

        return int(estimate_tokens_rough(text))
    except Exception:
        return max(0, (len(text) + 3) // 4)


def _estimate_messages_tokens(messages: list[dict[str, str]]) -> int:
    try:
        from agent.model_metadata import estimate_messages_tokens_rough

        return int(estimate_messages_tokens_rough(messages))
    except Exception:
        return sum(_estimate_tokens_text(message.get("content", "")) for message in messages)


def _base_messages(case: SimulationCase) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                f"You are {case.god}, a Pantheon operator. Phase: {case.phase}. "
                "Use supplied source-backed context when present; ignore it when absent."
            ),
        },
        {"role": "user", "content": case.query},
    ]


def _context_message(injectable_context: str) -> dict[str, str]:
    return {
        "role": "system",
        "content": (
            "The following block is a dry-run Ichor context pack candidate. "
            "It is source-backed and bounded; do not treat it as a runtime mutation.\n\n"
            f"{injectable_context}"
        ),
    }


def _source_titles_clean(source_links: list[dict[str, Any]]) -> bool:
    forbidden = ("```", "\n", "http://", "https://", "www.", "|")
    for link in source_links:
        title = str(link.get("title", ""))
        if not title.strip():
            return False
        lowered = title.lower()
        if any(token in lowered for token in forbidden):
            return False
    return True


def simulate_case(case: SimulationCase, artifact_dir: Path) -> tuple[dict[str, Any], Path]:
    from lib.ichor.context_pack import build_context_pack

    artifact_dir.mkdir(parents=True, exist_ok=True)
    before_messages = _base_messages(case)
    before_tokens = _estimate_messages_tokens(before_messages)
    pack = build_context_pack(
        case.query,
        god_name=case.god,
        phase=case.phase,
        max_items=case.max_items,
        max_tokens=case.max_tokens,
        max_ms=case.max_ms,
        include_graph=True,
        dry_run=True,
    )
    injectable = str(pack.get("injectable_context", "") or "")
    coverage = pack.get("coverage", {})
    metrics = pack.get("metrics", {})
    source_links = list(pack.get("source_links") or [])
    injected = bool(injectable and int(coverage.get("returned", 0) or 0) > 0)
    after_messages = list(before_messages)
    if injected:
        after_messages.insert(1, _context_message(injectable))
    after_tokens = _estimate_messages_tokens(after_messages)
    source_link_count = len(source_links)
    source_quality_ok = source_link_count >= case.min_sources and _source_titles_clean(source_links)
    noop_clean = (
        not case.expected_injection
        and not injected
        and source_link_count == 0
        and int(metrics.get("db_reads", 0) or 0) == 0
        and int(metrics.get("tokens_estimated", 0) or 0) == 0
        and not injectable
    )
    injection_quality_ok = injected and source_quality_ok and after_tokens > before_tokens
    row_quality_pass = injection_quality_ok if case.expected_injection else noop_clean
    row = {
        "case_id": case.case_id,
        "god": case.god,
        "phase": case.phase,
        "query": case.query,
        "expected_injection": case.expected_injection,
        "injected": injected,
        "coverage_status": coverage.get("status"),
        "returned": int(coverage.get("returned", 0) or 0),
        "source_link_count": source_link_count,
        "source_titles": [str(link.get("title", "")) for link in source_links],
        "source_paths": [str(link.get("source_path", "")) for link in source_links],
        "source_titles_clean": _source_titles_clean(source_links),
        "prompt_message_count_before": len(before_messages),
        "prompt_message_count_after": len(after_messages),
        "prompt_tokens_before": before_tokens,
        "prompt_tokens_after": after_tokens,
        "prompt_token_delta": after_tokens - before_tokens,
        "injectable_context_length": len(injectable),
        "tokens_estimated": int(metrics.get("tokens_estimated", 0) or 0),
        "db_reads": int(metrics.get("db_reads", 0) or 0),
        "db_writes": int(metrics.get("db_writes", 0) or 0),
        "llm_calls": int(metrics.get("llm_calls", 0) or 0),
        "api_calls": int(metrics.get("api_calls", 0) or 0),
        "wall_ms": int(metrics.get("wall_ms", 0) or 0),
        "would_mutate_runtime": False,
        "would_change_config": False,
        "would_restart_gateway": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "row_safety_pass": (
            int(metrics.get("db_writes", 0) or 0) == 0
            and int(metrics.get("llm_calls", 0) or 0) == 0
            and int(metrics.get("api_calls", 0) or 0) == 0
        ),
        "row_quality_pass": row_quality_pass,
    }
    case_path = artifact_dir / f"{case.case_id}.json"
    case_path.write_text(
        json.dumps({"row": row, "pack": pack, "messages_before": before_messages, "messages_after": after_messages}, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return row, case_path


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    noop_rows = [row for row in rows if not row["expected_injection"]]
    injection_rows = [row for row in rows if row["expected_injection"]]
    all_no_llm_api = all(row["llm_calls"] == 0 and row["api_calls"] == 0 for row in rows)
    all_no_db_writes = all(row["db_writes"] == 0 for row in rows)
    all_safety_flags_false = all(
        not row["would_mutate_runtime"]
        and not row["would_change_config"]
        and not row["would_restart_gateway"]
        and not row["would_rotate_session"]
        and not row["would_rewrite_transcript"]
        for row in rows
    )
    injection_rows_ok = all(row["row_quality_pass"] for row in injection_rows)
    noop_rows_clean = all(row["row_quality_pass"] for row in noop_rows)
    safety_pass = all_no_llm_api and all_no_db_writes and all_safety_flags_false
    quality_pass = injection_rows_ok and noop_rows_clean
    blockers: list[str] = []
    if not safety_pass:
        blockers.append("safety_invariants_failed")
    if not injection_rows_ok:
        blockers.append("injection_rows_failed_quality")
    if not noop_rows_clean:
        blockers.append("noop_rows_not_clean")
    return {
        "rows_run": len(rows),
        "injection_rows": len(injection_rows),
        "noop_rows": len(noop_rows),
        "safety_pass": safety_pass,
        "quality_pass": quality_pass,
        "rollout_sim_ready": safety_pass and quality_pass,
        "all_no_llm_api": all_no_llm_api,
        "all_no_db_writes": all_no_db_writes,
        "all_safety_flags_false": all_safety_flags_false,
        "injection_rows_ok": injection_rows_ok,
        "noop_rows_clean": noop_rows_clean,
        "max_prompt_token_delta": max((row["prompt_token_delta"] for row in rows), default=0),
        "max_prompt_tokens_after": max((row["prompt_tokens_after"] for row in rows), default=0),
        "total_db_reads": sum(row["db_reads"] for row in rows),
        "total_db_writes": sum(row["db_writes"] for row in rows),
        "blockers": blockers,
    }


def format_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# Ichor Context-Pack Prompt Injection Simulation",
        "",
        f"Generated: {payload['generated_at']}",
        f"Mode: {payload['mode']}",
        f"Artifact dir: {payload['artifact_dir']}",
        "",
        "## Verdict",
        f"- safety_pass: {str(summary['safety_pass']).lower()}",
        f"- quality_pass: {str(summary['quality_pass']).lower()}",
        f"- rollout_sim_ready: {str(summary['rollout_sim_ready']).lower()}",
        f"- blockers: {', '.join(summary['blockers']) if summary['blockers'] else 'none'}",
        "",
        "## Safety boundary",
        "- prompt simulation only: true",
        "- live profile mutation: false",
        "- gateway restart: false",
        "- session rotation: false",
        "- transcript rewrite: false",
        "- model/API calls: false",
        "",
        "## Rows",
    ]
    for row in payload["rows"]:
        lines.append(
            f"- {row['case_id']}: injected={str(row['injected']).lower()} "
            f"sources={row['source_link_count']} prompt_delta={row['prompt_token_delta']} "
            f"quality={str(row['row_quality_pass']).lower()}"
        )
    return "\n".join(lines) + "\n"


def run_simulation(artifact_dir: Path) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    case_paths: list[str] = []
    for case in MATRIX:
        row, path = simulate_case(case, artifact_dir)
        rows.append(row)
        case_paths.append(str(path))
    payload = {
        "mode": "prompt_injection_simulation",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifact_dir": str(artifact_dir),
        "would_mutate_runtime": False,
        "would_change_config": False,
        "would_restart_gateway": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "rows": rows,
        "summary": summarize(rows),
        "case_paths": case_paths,
    }
    summary_path = artifact_dir / "summary.json"
    report_path = artifact_dir / "report.md"
    payload["summary_path"] = str(summary_path)
    payload["report_path"] = str(report_path)
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    report_path.write_text(format_report(payload), encoding="utf-8")
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=None)
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    payload = run_simulation(args.artifact_dir or _default_artifact_dir())
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(format_report(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
