"""Tests for the real compressor-weight benchmark gate.

These assert the handoff's missing measurement: default ContextCompressor must be
exercised on long transcripts, not merely threshold-probed on tiny replay rows.
"""
from __future__ import annotations

import builtins
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "benchmark-ichor-compressor-weight.py"


def load_module():
    spec = importlib.util.spec_from_file_location("benchmark_ichor_compressor_weight", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_benchmark_case_exercises_default_compressor_without_api_calls(tmp_path: Path) -> None:
    module = load_module()

    row, artifact = module.run_case(
        module.BenchmarkCase(
            case_id="hermes-lcm-risk-long-thread",
            god="hermes",
            phase="ops",
            query="LCM risk recall and Ichor compressor replacement",
            expect_injection=True,
            min_sources=2,
        ),
        tmp_path,
    )

    assert artifact.exists()
    baseline = row["default_compressor"]
    assert baseline["available"] is True
    assert baseline["would_compress_by_threshold"] is True
    assert baseline["has_compressible_window"] is True
    assert baseline["called_compress_method"] is True
    assert baseline["api_calls"] == 0
    assert baseline["llm_calls"] == 1
    assert baseline["tokens_after"] < baseline["tokens_before"]
    assert baseline["message_count_after"] < baseline["message_count_before"]

    candidate = row["ichor_context_pack"]
    assert candidate["injected"] is True
    assert candidate["source_link_count"] >= 2
    assert candidate["llm_calls"] == 0
    assert candidate["api_calls"] == 0
    assert candidate["db_writes"] == 0
    assert candidate["tokens_estimated"] <= row["max_pack_tokens"]

    assert row["would_mutate_runtime"] is False
    assert row["would_rotate_session"] is False
    assert row["would_rewrite_transcript"] is False
    assert row["would_change_config"] is False
    assert row["would_restart_gateway"] is False
    assert row["row_ready"] is True


def test_noop_case_stays_zero_read_zero_injection(tmp_path: Path) -> None:
    module = load_module()

    row, artifact = module.run_case(
        module.BenchmarkCase(
            case_id="casual-long-noop",
            god="hermes",
            phase="chat",
            query="random casual hello",
            expect_injection=False,
            min_sources=0,
        ),
        tmp_path,
    )

    assert artifact.exists()
    candidate = row["ichor_context_pack"]
    assert candidate["injected"] is False
    assert candidate["source_link_count"] == 0
    assert candidate["db_reads"] == 0
    assert candidate["tokens_estimated"] == 0
    assert row["row_ready"] is True


def test_cli_writes_benchmark_artifacts_and_summary(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "benchmark"
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--artifact-dir",
            str(artifact_dir),
            "--format",
            "json",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(proc.stdout)
    summary = payload["summary"]

    assert payload["mode"] == "compressor_weight_benchmark"
    assert payload["would_mutate_runtime"] is False
    assert summary["rows_run"] >= 4
    assert summary["benchmark_ready"] is True
    assert summary["default_compressor_exercised_rows"] >= 3
    assert summary["all_default_rows_reduced_tokens"] is True
    assert summary["all_no_runtime_mutation"] is True
    assert summary["all_candidate_no_llm_api"] is True
    assert summary["all_candidate_no_db_writes"] is True
    assert summary["noop_rows_clean"] is True
    assert summary["blockers"] == []
    assert Path(payload["summary_path"]).exists()
    assert Path(payload["report_path"]).exists()
    assert len(payload["case_paths"]) == summary["rows_run"]
    assert artifact_dir.stat().st_mode & 0o777 == 0o700


def test_ichor_pack_import_failure_is_reported_as_failing_row(tmp_path: Path) -> None:
    module = load_module()
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "lib.ichor.context_pack":
            raise ImportError("synthetic context-pack import miss")
        return real_import(name, globals, locals, fromlist, level)

    with patch("builtins.__import__", side_effect=fake_import):
        row, artifact = module.run_case(
            module.BenchmarkCase(
                case_id="hermes-lcm-risk-long-thread",
                god="hermes",
                phase="ops",
                query="LCM risk recall and Ichor compressor replacement",
                expect_injection=True,
                min_sources=2,
            ),
            tmp_path,
        )

    assert artifact.exists()
    candidate = row["ichor_context_pack"]
    assert candidate["coverage_status"] == "error"
    assert candidate["injected"] is False
    assert candidate["llm_calls"] == 0
    assert candidate["api_calls"] == 0
    assert candidate["db_writes"] == 0
    assert any("context_pack_import_failed" in warning for warning in candidate["warnings"])
    assert row["candidate_quality_ok"] is False
    assert row["candidate_safety_ok"] is True
    assert row["row_ready"] is False
