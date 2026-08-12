#!/usr/bin/env python3
"""Dry-run measurement scaffold for Ichor context packs.

This command builds the candidate pack for reporting only. It measures a
bounded synthetic transcript and, when requested, compares cheap default
ContextCompressor feasibility metrics without calling the compression method.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HERMES_AGENT = ROOT / "hermes-agent"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "ichor_golden_queries.yaml"

if str(HERMES_AGENT) not in sys.path:
    sys.path.insert(0, str(HERMES_AGENT))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _rss_kb() -> int | None:
    try:
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, IndexError, ValueError):
        pass

    try:
        import psutil
    except ImportError:
        return None
    return int(psutil.Process().memory_info().rss // 1024)


def _peak_rss_kb() -> int | None:
    try:
        import resource
    except ImportError:
        return None
    peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return peak if peak >= 0 else None


def _load_fixture_queries(warnings: list[str]) -> list[dict[str, Any]]:
    try:
        import yaml
    except ImportError:
        warnings.append("PyYAML unavailable; using synthetic query only")
        return []

    try:
        with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError:
        warnings.append(f"golden query fixture missing: {FIXTURE_PATH}")
        return []
    except (OSError, yaml.YAMLError) as exc:
        warnings.append(f"golden query fixture could not be loaded: {exc}")
        return []

    queries = data.get("queries") if isinstance(data, dict) else None
    if not isinstance(queries, list):
        warnings.append("golden query fixture has no queries list")
        return []
    return [item for item in queries if isinstance(item, dict)]


def _synthetic_messages(args: argparse.Namespace, warnings: list[str]) -> tuple[list[dict[str, str]], int]:
    queries = _load_fixture_queries(warnings)
    selected = [
        item for item in queries
        if str(item.get("query", "")).lower() == args.query.lower()
    ][: max(args.max_items, 0)]
    if not selected:
        selected = [{
            "query": args.query,
            "god": args.god,
            "phase": args.phase,
            "must_include": [],
            "notes": "synthetic dry-run transcript row",
        }]

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": "Synthetic Phase 0 dry-run transcript. No runtime state is attached.",
        }
    ]
    for row in selected:
        must_include = ", ".join(str(token) for token in row.get("must_include", []) or [])
        notes = str(row.get("notes", "") or "")
        messages.append({
            "role": "user",
            "content": (
                f"[{row.get('god', args.god)}:{row.get('phase', args.phase)}] "
                f"{row.get('query', args.query)}"
            ),
        })
        messages.append({
            "role": "assistant",
            "content": f"Fixture expectations: {must_include}. Notes: {notes}",
        })
    return messages, len(selected)


def _estimate_tokens(messages: list[dict[str, str]], warnings: list[str]) -> int:
    try:
        from agent.model_metadata import estimate_messages_tokens_rough
    except Exception as exc:
        warnings.append(f"default token estimator unavailable: {exc}")
        return sum((len(message.get("content", "")) + 3) // 4 for message in messages)
    return int(estimate_messages_tokens_rough(messages))


def _default_compressor_baseline(messages: list[dict[str, str]], tokens: int, warnings: list[str]) -> dict[str, Any]:
    try:
        from agent.context_compressor import ContextCompressor
    except Exception as exc:
        warnings.append(f"default compressor unavailable: {exc}")
        return {
            "available": False,
            "tokens_estimated": tokens,
            "llm_calls": 0,
        }

    compressor = ContextCompressor(
        model="phase0-dry-run",
        quiet_mode=True,
        config_context_length=128_000,
    )
    return {
        "available": True,
        "engine": compressor.name,
        "model": compressor.model,
        "context_length": compressor.context_length,
        "threshold_tokens": compressor.threshold_tokens,
        "tail_token_budget": compressor.tail_token_budget,
        "tokens_estimated": tokens,
        "has_compressible_window": bool(compressor.has_content_to_compress(messages)),
        "would_compress_by_threshold": bool(compressor.should_compress(tokens)),
        "would_call_compress_method": False,
        "llm_calls": 0,
        "api_calls": 0,
    }


def _build_payload(args: argparse.Namespace) -> dict[str, Any]:
    warnings: list[str] = []
    rss_before = _rss_kb()
    started = time.perf_counter()

    messages, rows_examined = _synthetic_messages(args, warnings)
    tokens = _estimate_tokens(messages, warnings)
    try:
        from lib.ichor.context_pack import build_context_pack
        candidate_context_pack = build_context_pack(
            args.query,
            god_name=args.god,
            phase=args.phase,
            max_items=args.max_items,
            dry_run=True,
        )
    except Exception as exc:
        warnings.append(f"context pack builder unavailable: {exc}")
        candidate_context_pack = {
            "query": args.query,
            "god": args.god,
            "phase": args.phase,
            "injectable_context": "",
            "coverage": {
                "status": "unknown",
                "returned": 0,
                "omitted": 0,
                "warnings": ["context_pack_builder_unavailable"],
            },
            "current_decisions": [],
            "hard_constraints": [],
            "relevant_files": [],
            "risks": [],
            "related_entities": [],
            "recent_changes": [],
            "source_links": [],
            "omitted": {"count": 0, "reasons": ["builder_unavailable"]},
            "metrics": {
                "wall_ms": 0,
                "db_reads": 0,
                "db_writes": 0,
                "rows_examined": 0,
                "tokens_estimated": 0,
                "llm_calls": 0,
                "api_calls": 0,
                "rss_delta_kb": None,
                "mode": "dry_run",
            },
        }

    payload: dict[str, Any] = {
        "mode": "dry_run",
        "god": args.god,
        "phase": args.phase,
        "query": args.query,
        "max_items": args.max_items,
        "would_mutate_runtime": False,
        "would_rotate_session": False,
        "would_rewrite_transcript": False,
        "would_change_config": False,
        "would_restart_gateway": False,
        "warnings": warnings,
    }
    payload["candidate_context_pack"] = candidate_context_pack
    if args.compare_default_compressor:
        payload["default_compressor_baseline"] = _default_compressor_baseline(
            messages, tokens, warnings,
        )

    rss_after = _rss_kb()
    peak_rss_kb = _peak_rss_kb() or rss_after
    wall_ms = int((time.perf_counter() - started) * 1000)
    rss_delta_kb = None if rss_before is None or rss_after is None else rss_after - rss_before
    if rss_before is None or rss_after is None:
        warnings.append("RSS metrics unavailable")

    payload["metrics"] = {
        "wall_ms": wall_ms,
        "rss_delta_kb": rss_delta_kb,
        "peak_rss_kb": peak_rss_kb,
        "db_reads": candidate_context_pack["metrics"]["db_reads"],
        "db_writes": 0,
        "fixture_reads": 1 if FIXTURE_PATH.exists() else 0,
        "rows_examined": rows_examined + candidate_context_pack["metrics"]["rows_examined"],
        "tokens_estimated": tokens + candidate_context_pack["metrics"]["tokens_estimated"],
        "llm_calls": 0,
        "api_calls": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    return payload


def _format_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Ichor Context Pack Dry Run",
        "",
        f"mode: {payload['mode']}",
        f"god: {payload['god']}",
        f"phase: {payload['phase']}",
        f"query: {payload['query']}",
        f"would_mutate_runtime: {str(payload['would_mutate_runtime']).lower()}",
        f"would_rotate_session: {str(payload['would_rotate_session']).lower()}",
        f"would_rewrite_transcript: {str(payload['would_rewrite_transcript']).lower()}",
        f"would_change_config: {str(payload['would_change_config']).lower()}",
        f"would_restart_gateway: {str(payload['would_restart_gateway']).lower()}",
        "",
        "## Metrics",
    ]
    for key, value in payload["metrics"].items():
        lines.append(f"{key}: {value}")
    if "default_compressor_baseline" in payload:
        lines.extend(["", "## Default Compressor Baseline"])
        for key, value in payload["default_compressor_baseline"].items():
            lines.append(f"{key}: {value}")
    if "candidate_context_pack" in payload:
        lines.extend(["", "## Candidate Context Pack"])
        for key, value in payload["candidate_context_pack"].items():
            lines.append(f"{key}: {value}")
    if payload.get("warnings"):
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in payload["warnings"])
    return "\n".join(lines) + "\n"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--god", required=True)
    parser.add_argument("--phase", default="")
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--compare-default-compressor", action="store_true")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    payload = _build_payload(args)
    if args.format == "json":
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_markdown(payload), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
