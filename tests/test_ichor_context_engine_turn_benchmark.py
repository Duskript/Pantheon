"""Tests for IchorContextEngine per-turn token economy benchmark.

These tests lock Thoth's course-correction marker into executable gates:
benchmark the default-off IchorContextEngine on tokens sent per turn, not only
post-threshold compression size. The benchmark must remain offline and must not
flip profile/fleet defaults.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark-ichor-context-engine-turns.py"


def load_module():
    spec = importlib.util.spec_from_file_location("benchmark_ichor_context_engine_turns", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_turn_benchmark_shows_ichor_sends_fewer_tokens_per_turn(tmp_path: Path) -> None:
    module = load_module()
    payload = module.run_benchmark(tmp_path)
    summary = payload["summary"]

    assert payload["mode"] == "ichor_context_engine_turn_benchmark"
    assert summary["rows_run"] >= 4
    assert summary["default_compressor_exercised_rows"] >= 1
    assert "long-threshold-compressor-pressure" in summary["threshold_crossing_case_ids"]
    assert summary["benchmark_ready"] is True
    assert summary["baseline_label"] == "full transcript resend baseline until compressor threshold"
    assert summary["token_estimate_method"] == "len_div_4_heuristic"
    assert summary["ichor_total_tokens"] < summary["default_total_tokens"]
    assert summary["ichor_avg_tokens_per_turn"] < summary["default_avg_tokens_per_turn"]
    assert summary["all_ichor_no_llm_api"] is True
    assert summary["all_noop_rows_clean"] is True
    assert summary["all_rows_have_expand_handles"] is True
    assert summary["blockers"] == []


def test_turn_benchmark_cli_writes_private_artifacts(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "turn-benchmark"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--artifact-dir", str(artifact_dir), "--format", "json"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    summary = payload["summary"]

    assert payload["mode"] == "ichor_context_engine_turn_benchmark"
    assert summary["benchmark_ready"] is True
    assert summary["default_compressor_exercised_rows"] >= 1
    assert summary["token_estimate_method"] == "len_div_4_heuristic"
    assert Path(payload["summary_path"]).exists()
    assert Path(payload["report_path"]).exists()
    assert artifact_dir.stat().st_mode & 0o777 == 0o700
