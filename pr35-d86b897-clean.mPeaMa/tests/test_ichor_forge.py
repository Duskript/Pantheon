"""Tests for the Ichor Forge — Self-Adjusting Harness (ichor_forge.py).

Covers the ForgeAnalyzer, ForgeSmith, and ForgeReport components.
"""

import json
import os
import sys
import tempfile
import time
from typing import Any, Dict, Generator, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ichor_forge import (
    MIN_INTERVENTIONS_FOR_ADJUSTMENT,
    ForgeAdjustment,
    ForgeAnalyzer,
    ForgeFindings,
    ForgeReport,
    ForgeSmith,
    InterventionRecord,
    GateMetrics,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def log_dir() -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as d:
        yield d


def _write_log(log_dir: str, records: List[Dict[str, Any]]) -> str:
    """Write intervention records to the combined log file."""
    log_path = os.path.join(log_dir, "all.jsonl")
    with open(log_path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return log_path


def _make_intervention(
    gate: str = "state_gate",
    passed: bool = False,
    message: str = "blocked: no read",
    model: str = "deepseek-v4-flash",
    user_intent: str = "",
    recovery_hint: str = "read the file first",
    ts_offset: float = 0,
) -> Dict[str, Any]:
    return {
        "timestamp": time.time() - ts_offset,
        "gate": gate,
        "passed": passed,
        "message": message,
        "recovery_hint": recovery_hint,
        "model": model,
        "session_id": "test-session",
        "user_intent": user_intent,
    }


# ===========================================================================
# InterventionRecord Tests
# ===========================================================================


class TestInterventionRecord:
    def test_from_log_entry(self) -> None:
        entry = _make_intervention(gate="state_gate", passed=False)
        record = InterventionRecord(
            timestamp=entry["timestamp"],
            gate=entry["gate"],
            passed=entry["passed"],
            message=entry["message"],
            recovery_hint=entry["recovery_hint"],
            model=entry["model"],
            session_id=entry["session_id"],
            user_intent=entry["user_intent"],
        )
        assert record.gate == "state_gate"
        assert record.passed is False
        assert record.datetime is not None

    def test_passed_intervention(self) -> None:
        entry = _make_intervention(gate="phase_detection_gate", passed=True)
        record = InterventionRecord(**entry)
        assert record.passed is True


# ===========================================================================
# ForgeAnalyzer Tests
# ===========================================================================


class TestForgeAnalyzer:
    def test_load_empty_log(self, log_dir: str) -> None:
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        assert records == []

    def test_load_no_file(self, log_dir: str) -> None:
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        assert records == []

    def test_load_records(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False, ts_offset=100),
            _make_intervention(gate="logic_gate", passed=True, ts_offset=200),
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        assert len(records) == 2

    def test_load_respects_lookback(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(ts_offset=100),  # Recent
            _make_intervention(ts_offset=86400 * 30),  # 30 days ago
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        assert len(records) == 1  # Only the recent one

    def test_compute_metrics(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False),
            _make_intervention(gate="state_gate", passed=False),
            _make_intervention(gate="state_gate", passed=True),
            _make_intervention(gate="logic_gate", passed=True),
            _make_intervention(gate="logic_gate", passed=True),
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)

        assert "state_gate" in metrics
        assert "logic_gate" in metrics
        assert metrics["state_gate"].total == 3
        assert metrics["state_gate"].blocked == 2
        assert metrics["state_gate"].block_rate == pytest.approx(2 / 3)
        assert metrics["logic_gate"].total == 2
        assert metrics["logic_gate"].blocked == 0

    def test_detect_overblocking(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False) for _ in range(10)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)
        patterns = analyzer.detect_patterns(records, metrics)

        assert any("over-blocking" in p for p in patterns)

    def test_detect_repeated_path_blocks(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(
                gate="state_gate",
                passed=False,
                message="State Gate: write_file 'config.yaml' blocked",
            ) for _ in range(5)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)
        patterns = analyzer.detect_patterns(records, metrics)

        assert any("config.yaml" in p for p in patterns)

    def test_detect_model_pattern(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False, model="llama-3-8b")
            for _ in range(10)
        ] + [
            _make_intervention(gate="state_gate", passed=True, model="llama-3-8b")
            for _ in range(2)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)
        patterns = analyzer.detect_patterns(records, metrics)

        assert any("llama-3-8b" in p for p in patterns)

    def test_full_analyze_pipeline(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False),
            _make_intervention(gate="state_gate", passed=True),
            _make_intervention(gate="logic_gate", passed=True),
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        findings = analyzer.analyze(days=7)

        assert findings.total_interventions == 3
        assert findings.overall_block_rate == pytest.approx(1 / 3)
        assert "state_gate" in findings.gates_seen
        assert "logic_gate" in findings.gates_seen
        assert len(findings.models_seen) > 0
        assert findings.timespan_days > 0

    def test_analyze_empty(self, log_dir: str) -> None:
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        findings = analyzer.analyze(days=7)
        assert findings.total_interventions == 0
        assert findings.overall_block_rate == 0.0


# ===========================================================================
# GateMetrics Tests
# ===========================================================================


class TestGateMetrics:
    def test_over_blocking_threshold(self) -> None:
        gm = GateMetrics(
            gate_name="test", total=10, passed=2, blocked=8,
            block_rate=0.8, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
        )
        assert gm.is_over_blocking is True
        assert gm.is_under_blocking is False

    def test_under_blocking_threshold(self) -> None:
        gm = GateMetrics(
            gate_name="test", total=30, passed=29, blocked=1,
            block_rate=0.03, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
        )
        assert gm.is_over_blocking is False
        assert gm.is_under_blocking is True

    def test_normal_blocking(self) -> None:
        gm = GateMetrics(
            gate_name="test", total=10, passed=7, blocked=3,
            block_rate=0.3, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
        )
        assert gm.is_over_blocking is False
        assert gm.is_under_blocking is False


# ===========================================================================
# ForgeSmith Tests
# ===========================================================================


class TestForgeSmith:
    def test_evaluate_empty_findings(self, log_dir: str) -> None:
        smith = ForgeSmith()
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=0,
            timespan_days=0,
            models_seen=[],
            gates_seen=[],
            per_gate={},
            overall_block_rate=0.0,
        )
        adjustments = smith.evaluate(findings)
        assert len(adjustments) == 0

    def test_evaluate_too_few_interventions(self, log_dir: str) -> None:
        smith = ForgeSmith()
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=MIN_INTERVENTIONS_FOR_ADJUSTMENT - 1,
            timespan_days=1,
            models_seen=["test"],
            gates_seen=["state_gate"],
            per_gate={},
            overall_block_rate=0.0,
        )
        adjustments = smith.evaluate(findings)
        assert len(adjustments) == 0

    def test_pending_management(self) -> None:
        smith = ForgeSmith()
        assert smith.get_pending() == []

        adj = ForgeAdjustment(
            target="intent_keywords", action="add", item="deploy",
            reason="test", confidence=0.8,
        )
        smith._pending = [adj]
        assert len(smith.get_pending()) == 1
        smith.clear_pending()
        assert smith.get_pending() == []

    def test_apply_dry_run(self) -> None:
        smith = ForgeSmith()
        adj = ForgeAdjustment(
            target="intent_keywords", action="add", item="kubernetes",
            reason="test", confidence=0.8,
        )
        result = smith.apply_adjustment(adj, dry_run=True)
        assert result["dry_run"] is True
        assert result["applied"] is True


# ===========================================================================
# ForgeReport Tests
# ===========================================================================


class TestForgeReport:
    def test_text_empty(self) -> None:
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=0,
            timespan_days=0,
            models_seen=[],
            gates_seen=[],
            per_gate={},
            overall_block_rate=0.0,
        )
        text = ForgeReport.text(findings)
        assert "no data" in text

    def test_text_with_data(self) -> None:
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=10,
            timespan_days=3.0,
            models_seen=["deepseek-v4-flash"],
            gates_seen=["state_gate"],
            per_gate={
                "state_gate": GateMetrics(
                    gate_name="state_gate", total=10, passed=5, blocked=5,
                    block_rate=0.5, top_block_messages={},
                    top_recovery_hints={}, top_models={}, top_intents={},
                ),
            },
            overall_block_rate=0.5,
            detected_patterns=["⚠️ state_gate is over-blocking (50%)"],
            suggested_adjustments=["add 'deploy' to intent_keywords"],
        )
        text = ForgeReport.text(findings)
        assert "50%" in text
        assert "state_gate" in text
        assert "over-blocking" in text
        assert "Suggested Adjustments" in text

    def test_text_with_patterns(self) -> None:
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=50,
            timespan_days=5.0,
            models_seen=["model-a"],
            gates_seen=["state_gate"],
            per_gate={},
            overall_block_rate=0.3,
            detected_patterns=[
                "🔁 Path 'config.yaml' was blocked 5 times",
                "📊 Model 'model-a' has 60% block rate",
            ],
        )
        text = ForgeReport.text(findings)
        assert "config.yaml" in text
        assert "model-a" in text

    def test_short_status_no_data(self) -> None:
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=0,
            timespan_days=0,
            models_seen=[],
            gates_seen=[],
            per_gate={},
            overall_block_rate=0.0,
        )
        status = ForgeReport.short_status(findings)
        assert "idle" in status

    def test_short_status_with_data(self) -> None:
        findings = ForgeFindings(
            analyzed_at=time.time(),
            total_interventions=100,
            timespan_days=7.0,
            models_seen=["deepseek-v4-flash"],
            gates_seen=["state_gate", "logic_gate"],
            per_gate={},
            overall_block_rate=0.25,
            detected_patterns=["pattern 1"],
            suggested_adjustments=["adj 1"],
        )
        status = ForgeReport.short_status(findings)
        assert "100" in status
        assert "25%" in status or "block rate" in status


# ===========================================================================
# ForgeFindings Tests
# ===========================================================================


class TestForgeFindings:
    def test_default_fields(self) -> None:
        f = ForgeFindings(
            analyzed_at=1000.0,
            total_interventions=0,
            timespan_days=0.0,
            models_seen=[],
            gates_seen=[],
            per_gate={},
            overall_block_rate=0.0,
        )
        assert f.detected_patterns == []
        assert f.suggested_adjustments == []

    def test_with_patterns(self) -> None:
        f = ForgeFindings(
            analyzed_at=1000.0,
            total_interventions=10,
            timespan_days=1.0,
            models_seen=["m"],
            gates_seen=["g"],
            per_gate={},
            overall_block_rate=0.5,
            detected_patterns=["p1", "p2"],
        )
        assert len(f.detected_patterns) == 2


# ===========================================================================
# CLI Smoke Tests
# ===========================================================================


class TestCLI:
    def test_status_command(self) -> None:
        import io
        import sys as sys_mod
        from contextlib import redirect_stdout
        from lib.ichor_forge import main

        with tempfile.TemporaryDirectory() as d:
            sys_mod.argv = ["ichor_forge", "--status", "--days", "1"]
            # Patch log dir to temp
            from lib import ichor_forge
            old_dir = ichor_forge.FORGE_LOG_DIR
            ichor_forge.FORGE_LOG_DIR = d

            f = io.StringIO()
            with redirect_stdout(f):
                main()

            ichor_forge.FORGE_LOG_DIR = old_dir
            output = f.getvalue()
            assert "Forge" in output

    def test_analyze_with_data(self, log_dir: str) -> None:
        import io
        import sys as sys_mod
        from contextlib import redirect_stdout
        from lib.ichor_forge import main

        # Write some test data
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False),
            _make_intervention(gate="state_gate", passed=True),
        ])

        sys_mod.argv = ["ichor_forge", "--analyze", "--days", "7"]

        from lib import ichor_forge
        old_dir = ichor_forge.FORGE_LOG_DIR
        ichor_forge.FORGE_LOG_DIR = log_dir

        f = io.StringIO()
        with redirect_stdout(f):
            main()

        ichor_forge.FORGE_LOG_DIR = old_dir
        output = f.getvalue()
        assert "Interventions:" in output or "block rate" in output
