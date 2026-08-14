"""Controlled rollout simulation tests for Ichor context packs.

The replay harness proves the builder is safe and source-backed. The next gate is
slightly closer to rollout: compose a prompt-shaped message list that includes
an Ichor context pack only when memory is actually needed, while still staying
fully offline/read-only.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "simulate-ichor-context-pack-rollout.py"


def load_module():
    spec = importlib.util.spec_from_file_location("simulate_ichor_context_pack_rollout", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_positive_case_injects_source_backed_context_without_live_mutation(tmp_path: Path) -> None:
    module = load_module()

    row, artifact = module.simulate_case(
        module.SimulationCase(
            case_id="hermes-context-pack-followup",
            god="hermes",
            phase="ops",
            query="where did we leave the Ichor context pack?",
            expected_injection=True,
            min_sources=2,
        ),
        tmp_path,
    )

    assert artifact.exists()
    assert row["injected"] is True
    assert row["source_link_count"] >= 2
    assert row["prompt_message_count_after"] == row["prompt_message_count_before"] + 1
    assert row["prompt_token_delta"] > 0
    assert row["llm_calls"] == 0
    assert row["api_calls"] == 0
    assert row["db_writes"] == 0
    assert row["would_mutate_runtime"] is False
    assert row["would_change_config"] is False
    assert row["would_restart_gateway"] is False
    assert row["would_rotate_session"] is False
    assert row["would_rewrite_transcript"] is False


def test_noop_case_does_not_inject_or_read_memory(tmp_path: Path) -> None:
    module = load_module()

    row, artifact = module.simulate_case(
        module.SimulationCase(
            case_id="hermes-casual-noop",
            god="hermes",
            phase="chat",
            query="random casual hello",
            expected_injection=False,
            min_sources=0,
        ),
        tmp_path,
    )

    assert artifact.exists()
    assert row["injected"] is False
    assert row["source_link_count"] == 0
    assert row["prompt_message_count_after"] == row["prompt_message_count_before"]
    assert row["prompt_token_delta"] == 0
    assert row["db_reads"] == 0
    assert row["tokens_estimated"] == 0


def test_cli_writes_rollout_simulation_artifacts_and_summary(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "rollout-sim"
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

    assert payload["mode"] == "prompt_injection_simulation"
    assert summary["rows_run"] >= 6
    assert summary["safety_pass"] is True
    assert summary["quality_pass"] is True
    assert summary["rollout_sim_ready"] is True
    assert summary["all_no_llm_api"] is True
    assert summary["all_no_db_writes"] is True
    assert summary["noop_rows_clean"] is True
    assert payload["would_mutate_runtime"] is False
    assert payload["would_change_config"] is False
    assert payload["would_restart_gateway"] is False
    assert Path(payload["summary_path"]).exists()
    assert Path(payload["report_path"]).exists()
    assert len(payload["case_paths"]) == summary["rows_run"]
