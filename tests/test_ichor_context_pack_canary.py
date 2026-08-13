"""Canary readiness replay harness tests for Ichor context packs.

These tests guard the next step after the dry-run surface: a replay-only
canary readiness harness that produces artifacts and a yes/no gate without
wiring any live profile or gateway path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
CANARY_SCRIPT = _ROOT / "scripts" / "replay-ichor-context-pack-canary.py"
CANARY_DOC = _ROOT / "docs" / "ichor-context-pack-canary.md"


def _run_harness(artifact_dir: Path) -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_ROOT)
    proc = subprocess.run(
        [
            sys.executable,
            str(CANARY_SCRIPT),
            "--artifact-dir",
            str(artifact_dir),
            "--format",
            "json",
        ],
        cwd=_ROOT,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(proc.stdout)


def test_canary_harness_writes_replay_artifacts_without_live_mutation(tmp_path: Path) -> None:
    """The harness should write a report, not mutate runtime/live state."""
    payload = _run_harness(tmp_path / "artifacts")
    summary = payload["summary"]

    assert payload["mode"] == "dry_run_replay"
    assert summary["rows_run"] >= 8
    assert summary["safety_pass"] is True
    assert summary["all_no_llm_api"] is True
    assert summary["all_no_db_writes"] is True
    assert summary["all_safety_flags_false"] is True
    assert summary["noop_rows_clean"] is True
    assert payload["would_change_config"] is False
    assert payload["would_restart_gateway"] is False
    assert payload["would_mutate_runtime"] is False
    assert payload["would_rotate_session"] is False
    assert payload["would_rewrite_transcript"] is False

    artifact_dir = Path(payload["artifact_dir"])
    assert artifact_dir.exists()
    assert Path(payload["summary_path"]).exists()
    assert Path(payload["report_path"]).exists()
    assert len(payload["case_paths"]) == summary["rows_run"]
    for case_path in payload["case_paths"]:
        assert Path(case_path).exists()


def test_canary_harness_scores_quality_and_noop_rows(tmp_path: Path) -> None:
    """Quality/readiness is scored separately from safety."""
    payload = _run_harness(tmp_path / "artifacts")
    summary = payload["summary"]

    assert "quality_pass" in summary
    assert "canary_ready" in summary
    assert summary["operator_followup_rows_ok"] is True
    assert summary["source_backed_rows_ok"] is True
    assert summary["noop_rows_clean"] is True

    noop_rows = [row for row in payload["rows"] if row["expected_zero"]]
    assert noop_rows, "matrix must include casual/no-op rows"
    for row in noop_rows:
        assert row["coverage_status"] == "low"
        assert row["returned"] == 0
        assert row["db_reads"] == 0
        assert row["tokens_estimated"] == 0
        assert row["injectable_context_length"] == 0

    operator_rows = [row for row in payload["rows"] if row["category"] == "operator_followup"]
    assert operator_rows, "matrix must include operator follow-up rows"
    for row in operator_rows:
        assert row["coverage_status"] == "ok"
        assert row["returned"] >= row["min_returned"]
        assert row["source_link_count"] >= row["min_returned"]


def test_canary_harness_static_boundary_has_no_live_escape_hatch() -> None:
    """The harness must not expose live/canary mutation operations."""
    script = CANARY_SCRIPT.read_text(encoding="utf-8")
    forbidden = (
        "dry_run=False",
        "context.engine",
        "compression.*",
        "systemctl",
        "hermes-gateway",
        "SessionDB",
        ".end_session(",
        "_compress_context",
        ".compress(",
        'subprocess.run(["git',
    )
    for token in forbidden:
        assert token not in script


def test_canary_plan_doc_names_rollback_and_non_goals() -> None:
    """The operator doc must preserve the dry-run/replay boundary."""
    text = CANARY_DOC.read_text(encoding="utf-8").lower()
    for token in (
        "replay-only",
        "no live profile",
        "no gateway restart",
        "no lcm",
        "rollback",
        "canary_ready",
        "source grounding",
    ):
        assert token in text
