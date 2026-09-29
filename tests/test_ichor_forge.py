"""Tests for the Ichor Forge — Self-Adjusting Harness (ichor_forge.py).

Covers the ForgeAnalyzer, ForgeSmith, and ForgeReport components.
"""

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Generator, List

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ichor_forge import (
    MIN_INTERVENTIONS_FOR_ADJUSTMENT,
    EVAL_RETENTION_DAYS,
    EvalCounts,
    EvalRecorder,
    ForgeAdjustment,
    ForgeAnalyzer,
    ForgeFindings,
    ForgeReport,
    ForgeSmith,
    InterventionRecord,
    GateMetrics,
    load_eval_counts,
    load_model_counts,
    prune_evals,
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


def _write_evals(log_dir: str, entries: List[Dict[str, Any]]) -> str:
    """Write eval records (the forge's denominator) to evals.jsonl."""
    path = os.path.join(log_dir, "evals.jsonl")
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return path


def _make_eval(
    gate: str = "logic_gate",
    failed: bool = False,
    age_days: float = 0,
) -> Dict[str, Any]:
    return {
        "t": time.time() - age_days * 86400,
        "g": gate,
        "f": 1 if failed else 0,
        "god": "hermes",
    }


# ===========================================================================
# Eval Records — the denominator behind block_rate
# ===========================================================================
# `all.jsonl` is append-only for *failures*, so `blocked / total` over it is
# always 1.0. Eval records capture every check a gate performed, pass or
# fail, which is what makes a real block rate computable.


class TestEvalRecorder:
    def test_record_appends_one_line(self, log_dir: str) -> None:
        recorder = EvalRecorder(path=os.path.join(log_dir, "evals.jsonl"))
        assert recorder.record(gate="logic_gate", failed=False, god="hermes")
        assert recorder.record(gate="logic_gate", failed=True, god="hermes")

        lines = Path(recorder.path).read_text().strip().split("\n")
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["g"] == "logic_gate"
        assert first["f"] == 0
        assert first["god"] == "hermes"
        assert json.loads(lines[1])["f"] == 1

    def test_record_failure_is_swallowed(self) -> None:
        """A bad path must return False, never raise into a god's tool loop."""
        recorder = EvalRecorder(path="/dev/null/nope/evals.jsonl")
        assert recorder.record(gate="logic_gate", failed=False) is False

    def test_load_aggregates_pass_and_fail(self, log_dir: str) -> None:
        _write_evals(log_dir, [
            _make_eval(failed=False),
            _make_eval(failed=False),
            _make_eval(failed=False),
            _make_eval(failed=True),
            _make_eval(gate="state_gate", failed=True),
        ])
        counts = load_eval_counts(os.path.join(log_dir, "evals.jsonl"))

        assert counts["logic_gate"].checked == 4
        assert counts["logic_gate"].failed == 1
        assert counts["logic_gate"].passed == 3
        assert counts["logic_gate"].block_rate == pytest.approx(0.25)
        assert counts["logic_gate"].has_denominator is True
        assert counts["state_gate"].checked == 1

    def test_load_skips_malformed_lines(self, log_dir: str) -> None:
        path = os.path.join(log_dir, "evals.jsonl")
        Path(path).write_text(
            "not json at all\n"
            "\n"
            "[1, 2, 3]\n"
            '{"no_gate": true}\n'
            '{"g": "logic_gate", "f": 0, "t": 1}\n'
        )
        counts = load_eval_counts(path)
        assert list(counts) == ["logic_gate"]
        assert counts["logic_gate"].checked == 1

    def test_load_respects_lookback(self, log_dir: str) -> None:
        _write_evals(log_dir, [
            _make_eval(failed=False, age_days=1),
            _make_eval(failed=False, age_days=30),
        ])
        path = os.path.join(log_dir, "evals.jsonl")
        assert load_eval_counts(path, days=7)["logic_gate"].checked == 1
        assert load_eval_counts(path)["logic_gate"].checked == 2

    def test_load_missing_file_is_empty(self, log_dir: str) -> None:
        assert load_eval_counts(os.path.join(log_dir, "absent.jsonl")) == {}

    def test_prune_drops_only_old_records(self, log_dir: str) -> None:
        path = os.path.join(log_dir, "evals.jsonl")
        _write_evals(log_dir, [
            _make_eval(failed=False, age_days=1),
            _make_eval(failed=True, age_days=2),
            _make_eval(failed=False, age_days=EVAL_RETENTION_DAYS + 10),
        ])
        assert prune_evals(path, max_age_days=EVAL_RETENTION_DAYS) == 1
        assert len(Path(path).read_text().strip().split("\n")) == 2
        assert prune_evals(path, max_age_days=EVAL_RETENTION_DAYS) == 0


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
        """A per-model rate needs eval records, not just failures.

        Historically this test injected `passed=True` intervention records to
        give the ratio a denominator — records that never occur in
        production, where all.jsonl only receives failures. The denominator
        now comes from eval records, so the test supplies them.
        """
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False, model="llama-3-8b")
            for _ in range(10)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)

        assert not any("llama-3-8b" in p for p in
                       analyzer.detect_patterns(records, metrics))

        patterns = analyzer.detect_patterns(
            records, metrics,
            {"llama-3-8b": EvalCounts(gate="llama-3-8b", checked=12, failed=10)},
        )
        assert any("llama-3-8b" in p for p in patterns)
        assert any("10/12 checks" in p for p in patterns)

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
    """Rate-based alerts must be backed by a denominator.

    `rate_reliable` is True only when eval records supplied the number of
    checks performed. Without it the old code reported a 100% block rate
    for any gate that had ever fired once, and flagged it as over-blocking.
    """

    def test_over_blocking_threshold(self) -> None:
        gm = GateMetrics(
            gate_name="test", total=10, passed=2, blocked=8,
            block_rate=0.8, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
            checked=10, rate_reliable=True,
        )
        assert gm.is_over_blocking is True
        assert gm.is_under_blocking is False

    def test_under_blocking_threshold(self) -> None:
        gm = GateMetrics(
            gate_name="test", total=30, passed=29, blocked=1,
            block_rate=0.03, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
            checked=30, rate_reliable=True,
        )
        assert gm.is_over_blocking is False
        assert gm.is_under_blocking is True

    def test_normal_blocking(self) -> None:
        gm = GateMetrics(
            gate_name="test", total=10, passed=7, blocked=3,
            block_rate=0.3, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
            checked=10, rate_reliable=True,
        )
        assert gm.is_over_blocking is False
        assert gm.is_under_blocking is False

    def test_unreliable_rate_raises_no_alert(self) -> None:
        """Interventions-only metrics never alert, whatever the ratio."""
        gm = GateMetrics(
            gate_name="logic_gate", total=198, passed=0, blocked=198,
            block_rate=1.0, top_block_messages={},
            top_recovery_hints={}, top_models={}, top_intents={},
        )
        assert gm.rate_reliable is False
        assert gm.checked == 0
        assert gm.is_over_blocking is False
        assert gm.is_under_blocking is False


# ===========================================================================
# Eval-backed metrics — totals come from checks, not from failures
# ===========================================================================
# `all.jsonl` records failures only, so any rate derived from it alone reads
# 100% by construction. These tests pin the denominator semantics: with eval
# records the rate is real; without them no over-blocking alert is raised.


class TestEvalBackedMetrics:
    def test_compute_metrics_uses_eval_denominator(
        self, log_dir: str,
    ) -> None:
        """Two failures out of ten checks is a 20% rate, not 100%."""
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False),
            _make_intervention(gate="logic_gate", passed=False),
        ])
        evals = [_make_eval(failed=True) for _ in range(2)]
        evals += [_make_eval(failed=False) for _ in range(8)]
        _write_evals(log_dir, evals)

        analyzer = ForgeAnalyzer(log_dir=log_dir)
        counts = load_eval_counts(
            os.path.join(log_dir, "evals.jsonl"), days=7,
        )
        metrics = analyzer.compute_metrics(
            analyzer.load_records(days=7), counts,
        )["logic_gate"]

        assert (metrics.checked, metrics.total, metrics.blocked) == (10, 10, 2)
        assert metrics.block_rate == pytest.approx(0.2)
        assert metrics.rate_reliable is True
        assert metrics.is_over_blocking is False

    def test_compute_metrics_without_evals_is_unreliable(
        self, log_dir: str,
    ) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False),
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        metrics = analyzer.compute_metrics(analyzer.load_records(days=7))

        assert metrics["logic_gate"].rate_reliable is False
        assert metrics["logic_gate"].checked == 0
        assert metrics["logic_gate"].is_over_blocking is False

    def test_overblocking_alert_requires_evals(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="state_gate", passed=False)
            for _ in range(10)
        ])
        _write_evals(log_dir, [
            _make_eval(gate="state_gate", failed=True) for _ in range(10)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(
            records,
            load_eval_counts(os.path.join(log_dir, "evals.jsonl")),
        )
        patterns = analyzer.detect_patterns(records, metrics)

        assert any("over-blocking" in p for p in patterns)
        assert any("10 checks" in p for p in patterns)

    def test_failures_without_evals_raise_no_false_alarm(
        self, log_dir: str,
    ) -> None:
        """The original bug: failures-only data claimed a 100% block rate."""
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False)
            for _ in range(10)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)
        patterns = analyzer.detect_patterns(records, metrics)

        assert not any("over-blocking" in p for p in patterns)
        assert any("block rate unavailable" in p for p in patterns)

    def test_analyze_reports_real_rate_with_evals(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False),
        ])
        evals = [_make_eval(failed=True)]
        evals += [_make_eval(failed=False) for _ in range(3)]
        _write_evals(log_dir, evals)

        findings = ForgeAnalyzer(log_dir=log_dir).analyze(days=7)

        assert findings.checks_total == 4
        assert findings.rate_reliable is True
        assert findings.overall_block_rate == pytest.approx(0.25)

    def test_analyze_without_evals_reports_no_rate(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False),
        ])
        findings = ForgeAnalyzer(log_dir=log_dir).analyze(days=7)

        assert findings.checks_total == 0
        assert findings.rate_reliable is False

        report = ForgeReport.text(findings)
        assert "n/a" in report
        assert "100%" not in report


# ===========================================================================
# Per-model rates — same denominator rule, joined on the model name
# ===========================================================================
# Interventions carry a model; without eval records the per-model ratio is
# failures / failures. These tests pin that a model claim — and the threshold
# change it stages — requires real checks.


class TestEvalModelDenominator:
    def test_record_carries_the_model(self, log_dir: str) -> None:
        recorder = EvalRecorder(path=os.path.join(log_dir, "evals.jsonl"))
        recorder.record(
            gate="logic_gate", failed=False, god="hermes",
            model="deepseek-v4.1-flash",
        )
        recorder.record(gate="logic_gate", failed=True, god="hermes")

        raw = Path(recorder.path).read_text().strip().split("\n")
        entries = [json.loads(line) for line in raw]
        assert entries[0]["m"] == "deepseek-v4.1-flash"
        assert "m" not in entries[1]

    def test_load_model_counts_ignores_records_without_a_model(
        self, log_dir: str,
    ) -> None:
        path = os.path.join(log_dir, "evals.jsonl")
        now = time.time()
        Path(path).write_text(
            json.dumps({"t": now, "g": "logic_gate", "f": 0, "m": "mini"}) + "\n"
            + json.dumps({"t": now, "g": "logic_gate", "f": 1, "m": "mini"}) + "\n"
            + json.dumps({"t": now, "g": "logic_gate", "f": 1}) + "\n"
        )
        counts = load_model_counts(path)

        assert list(counts) == ["mini"]
        assert counts["mini"].checked == 2
        assert counts["mini"].failed == 1
        assert counts["mini"].block_rate == pytest.approx(0.5)

    def test_model_pattern_requires_checks(self, log_dir: str) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False, model="mini")
            for _ in range(10)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)

        without_evals = analyzer.detect_patterns(records, metrics)
        assert not any("Model '" in p for p in without_evals)

        with_evals = analyzer.detect_patterns(
            records, metrics,
            {"mini": EvalCounts(gate="mini", checked=10, failed=10)},
        )
        assert any("Model 'mini'" in p and "10 checks" in p for p in with_evals)

    def test_model_threshold_change_requires_checks(
        self, log_dir: str,
    ) -> None:
        _write_log(log_dir, [
            _make_intervention(gate="logic_gate", passed=False, model="mini")
            for _ in range(12)
        ])
        analyzer = ForgeAnalyzer(log_dir=log_dir)
        records = analyzer.load_records(days=7)
        metrics = analyzer.compute_metrics(records)
        patterns = analyzer.detect_patterns(records, metrics)

        without_evals = analyzer.suggest_adjustments(records, patterns)
        assert not any(a.target == "model_thresholds" for a in without_evals)

        with_evals = analyzer.suggest_adjustments(
            records, patterns,
            {"mini": EvalCounts(gate="mini", checked=12, failed=9)},
        )
        staged = [a for a in with_evals if a.target == "model_thresholds"]
        assert len(staged) == 1
        assert "9/12 checks blocked" in staged[0].reason


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

    def test_pending_management(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        smith = ForgeSmith()
        assert smith.get_pending() == []

        pending_dir = tmp_path / ".hermes" / "clawforge"
        pending_dir.mkdir(parents=True, exist_ok=True)
        pending_file = pending_dir / "pending-recommendations.json"
        pending_file.write_text(
            json.dumps([
                {
                    "pattern_id": "forge-model-threshold-unknown",
                    "type": "model_threshold",
                    "patch": {
                        "gate": "logic_gate",
                        "target": "model:unknown",
                        "reason": "test",
                    },
                    "confidence": 0.8,
                    "instances_validated": None,
                    "summary": "test",
                }
            ]) + "\n"
        )

        loaded = smith.get_pending()
        assert len(loaded) == 1
        assert loaded[0].target == "model_thresholds"
        assert loaded[0].item == "unknown"
        assert loaded[0].reason == "test"

        smith.clear_pending()
        assert smith.get_pending() == []
        assert not pending_file.exists()

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
            checks_total=10,
            rate_reliable=True,
            per_gate={
                "state_gate": GateMetrics(
                    gate_name="state_gate", total=10, passed=5, blocked=5,
                    block_rate=0.5, top_block_messages={},
                    top_recovery_hints={}, top_models={}, top_intents={},
                    checked=10, rate_reliable=True,
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
            checks_total=100,
            rate_reliable=True,
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
