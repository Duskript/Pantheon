"""Tests for the Ichor RALPH 5-Gate Harness (ichor_gates.py).

Covers all 5 gates, the pipeline, read cache, forge logger, and
handoff manifest system.
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# Make sure we can import from lib/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.ichor_gates import (
    RALPHPhase,
    PHASE_PROMPTS,
    PHASE_TOOLS,
    ReadCache,
    StateGate,
    LogicGate,
    IntentInjectionGate,
    PhaseDetectionGate,
    HandoffGate,
    HandoffManifest,
    GatePipeline,
    ForgeLogger,
    GateResult,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def cache() -> ReadCache:
    return ReadCache()


@pytest.fixture
def state_gate(cache: ReadCache) -> StateGate:
    return StateGate(cache)


@pytest.fixture
def logic_gate() -> LogicGate:
    return LogicGate()


@pytest.fixture
def phase_gate() -> PhaseDetectionGate:
    return PhaseDetectionGate()


@pytest.fixture
def temp_dir() -> Generator[str, None, None]:
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def pipeline() -> GatePipeline:
    return GatePipeline()


@pytest.fixture
def forge_logger() -> Generator[ForgeLogger, None, None]:
    with tempfile.TemporaryDirectory() as d:
        yield ForgeLogger(log_dir=d)


# ===========================================================================
# ReadCache Tests
# ===========================================================================


class TestReadCache:
    def test_mark_and_has_read(self, cache: ReadCache) -> None:
        cache.mark_read("/tmp/test.py")
        assert cache.has_read("/tmp/test.py") is True

    def test_not_read(self, cache: ReadCache) -> None:
        assert cache.has_read("/nonexistent/path.py") is False

    def test_resolve_relative_path(self, cache: ReadCache) -> None:
        cache.mark_read("setup.py")
        abs_path = os.path.abspath("setup.py")
        assert cache.has_read("setup.py") is True
        assert cache.has_read(abs_path) is True

    def test_reset(self, cache: ReadCache) -> None:
        cache.mark_read("/tmp/test.py")
        cache.reset()
        assert cache.has_read("/tmp/test.py") is False

    def test_snapshot(self, cache: ReadCache) -> None:
        cache.mark_read("/tmp/a.py")
        cache.mark_read("/tmp/b.py")
        snap = cache.snapshot()
        assert snap["count"] == 2
        assert "/tmp/a.py" in snap["read_files"]

    def test_merge(self, cache: ReadCache) -> None:
        cache.mark_read("/tmp/a.py")
        other = ReadCache()
        other.mark_read("/tmp/b.py")
        cache.merge(other.snapshot())
        assert cache.has_read("/tmp/a.py")
        assert cache.has_read("/tmp/b.py")
        assert cache.snapshot()["count"] == 2

    def test_exists_on_disk(self, cache: ReadCache, temp_dir: str) -> None:
        test_file = os.path.join(temp_dir, "existing.py")
        Path(test_file).touch()
        assert cache.exists_on_disk(test_file) is True

    def test_not_exists_on_disk(self, cache: ReadCache) -> None:
        assert cache.exists_on_disk("/definitely/not/here.py") is False


# ===========================================================================
# Gate 1: StateGate Tests
# ===========================================================================


class TestStateGate:
    def test_blocks_write_without_read(
        self, state_gate: StateGate, temp_dir: str
    ) -> None:
        """Write to an existing file without prior read → blocked."""
        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()

        result = state_gate.pre_call("write_file", {"path": path}, {})
        assert result is not None
        assert result.passed is False
        assert result.intervention is True
        assert "blocked" in result.message

    def test_allows_write_after_read(
        self, state_gate: StateGate, cache: ReadCache, temp_dir: str
    ) -> None:
        """Write after read → allowed."""
        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()
        cache.mark_read(path)

        result = state_gate.pre_call("write_file", {"path": path}, {})
        assert result is None  # Passthrough

    def test_allows_new_file(
        self, state_gate: StateGate, temp_dir: str
    ) -> None:
        """Creating a new file does not require prior read."""
        path = os.path.join(temp_dir, "new.py")
        assert not os.path.exists(path)

        result = state_gate.pre_call("write_file", {"path": path}, {})
        assert result is None  # Passthrough

    def test_ignores_read_only_tools(
        self, state_gate: StateGate
    ) -> None:
        """Non-write tools are not blocked."""
        for tool in ("read_file", "web_search", "terminal"):
            result = state_gate.pre_call(tool, {"path": "x.py"}, {})
            assert result is None

    def test_blocks_patch_without_read(
        self, state_gate: StateGate, temp_dir: str
    ) -> None:
        """patch tool also requires prior read."""
        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()

        result = state_gate.pre_call("patch", {"path": path}, {})
        assert result is not None
        assert result.passed is False

    def test_allows_patch_after_read(
        self, state_gate: StateGate, cache: ReadCache, temp_dir: str
    ) -> None:
        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()
        cache.mark_read(path)

        result = state_gate.pre_call("patch", {"path": path}, {})
        assert result is None


# ===========================================================================
# Gate 2: LogicGate Tests
# ===========================================================================


class TestLogicGate:
    def test_valid_python_passes(self, logic_gate: LogicGate) -> None:
        result = logic_gate.post_call(
            "write_file",
            {"path": "test.py", "content": "x = 1\nprint(x)\n"},
            None, {},
        )
        assert result is None  # Passed

    def test_invalid_python_blocked(self, logic_gate: LogicGate) -> None:
        result = logic_gate.post_call(
            "write_file",
            {"path": "test.py", "content": "x = 1\n  indent error\n"},
            None, {},
        )
        assert result is not None
        assert result.passed is False
        assert "syntax error" in result.recovery_hint.lower()

    def test_bare_except_detected(self, logic_gate: LogicGate) -> None:
        content = """
try:
    x = 1 / 0
except:
    pass
"""
        result = logic_gate.post_call(
            "write_file",
            {"path": "test.py", "content": content},
            None, {},
        )
        assert result is not None
        assert result.passed is False
        assert "bare" in result.recovery_hint.lower()

    def test_todo_detected(self, logic_gate: LogicGate) -> None:
        content = "# TODO: fix this later\nx = 1\n"
        result = logic_gate.post_call(
            "write_file",
            {"path": "test.py", "content": content},
            None, {},
        )
        assert result is not None
        assert result.passed is False
        assert "TODO" in result.recovery_hint

    def test_fixme_detected(self, logic_gate: LogicGate) -> None:
        content = "# FIXME: this is broken\ny = 2\n"
        result = logic_gate.post_call(
            "write_file",
            {"path": "test.py", "content": content},
            None, {},
        )
        assert result is not None
        assert "FIXME" in result.recovery_hint

    def test_valid_json_passes(self, logic_gate: LogicGate) -> None:
        content = '{"name": "test", "value": 42}'
        result = logic_gate.post_call(
            "write_file",
            {"path": "config.json", "content": content},
            None, {},
        )
        assert result is None

    def test_invalid_json_blocked(self, logic_gate: LogicGate) -> None:
        content = '{"name": "test", broken}'
        result = logic_gate.post_call(
            "write_file",
            {"path": "config.json", "content": content},
            None, {},
        )
        assert result is not None
        assert result.passed is False

    def test_ignores_unknown_ext(self, logic_gate: LogicGate) -> None:
        result = logic_gate.post_call(
            "write_file",
            {"path": "data.bin", "content": b"\x00\x01\x02"},
            None, {},
        )
        assert result is None  # No check for .bin

    def test_intervention_cap(self, logic_gate: LogicGate) -> None:
        """After cap, passes through with warning.

        Uses unique paths per call so the 60s dedup window doesn't
        short-circuit the test (added in P2a).
        """
        bad_content = "invalid python {{{"
        limit = 3

        for i in range(limit):
            result = logic_gate.post_call(
                "write_file",
                {"path": f"test_{i}.py", "content": bad_content},
                None, {},
            )
            assert result is not None
            assert result.passed is False

        # This one should pass through (cap reached)
        result = logic_gate.post_call(
            "write_file",
            {"path": "test_cap.py", "content": bad_content},
            None, {},
        )
        assert result is not None
        assert result.intervention is False
        assert "cap reached" in result.message


# ===========================================================================
# Gate 3: IntentInjectionGate Tests
# ===========================================================================


class TestIntentInjectionGate:
    def test_no_injection_without_keywords(self) -> None:
        gate = IntentInjectionGate(base_path=".")
        result = gate.on_session_start({"user_message": "hello world"})
        assert result is None or "injected_context" not in result

    def test_inject_on_config_keyword(self, temp_dir: str) -> None:
        # Create a config file
        config_path = os.path.join(temp_dir, "config.yaml")
        with open(config_path, "w") as f:
            f.write("key: value\n")

        gate = IntentInjectionGate(
            rules={"config": ["config.yaml"]},
            base_path=temp_dir,
        )
        result = gate.on_session_start(
            {"user_message": "update the config file"}
        )
        assert result is not None
        assert "injected_context" in result
        assert "config.yaml" in result["injected_context"]

    def test_no_match_returns_none(self) -> None:
        gate = IntentInjectionGate(base_path=".")
        result = gate.on_session_start(
            {"user_message": "draw me a picture"}
        )
        assert result is None

    def test_deduplicates(self, temp_dir: str) -> None:
        config_path = os.path.join(temp_dir, "config.yaml")
        with open(config_path, "w") as f:
            f.write("key: value\n")

        gate = IntentInjectionGate(
            rules={"config": ["config.yaml"]},
            base_path=temp_dir,
        )
        # First call
        r1 = gate.on_session_start({"user_message": "update config"})
        assert r1 is not None

        # Second call — should not re-inject same file
        r2 = gate.on_session_start({"user_message": "update config again"})
        assert r2 is None or "injected_context" not in r2

    def test_resolves_absolute_path(self) -> None:
        path = __file__  # This test file exists
        gate = IntentInjectionGate(
            rules={"test": [path]},
            base_path=".",
        )
        result = gate.on_session_start({"user_message": "test the code"})
        assert result is not None
        assert "injected_context" in result


# ===========================================================================
# Gate 4: PhaseDetectionGate Tests
# ===========================================================================


class TestPhaseDetectionGate:
    def test_detect_reasoning(self, phase_gate: PhaseDetectionGate) -> None:
        phase = phase_gate.detect_phase("find the root cause of the bug")
        assert phase == RALPHPhase.REASONING

    def test_detect_action(self, phase_gate: PhaseDetectionGate) -> None:
        phase = phase_gate.detect_phase("create a new file for the config")
        assert phase == RALPHPhase.ACTION

    def test_detect_logic(self, phase_gate: PhaseDetectionGate) -> None:
        phase = phase_gate.detect_phase("verify the tests pass")
        assert phase == RALPHPhase.LOGIC

    def test_detect_planning(self, phase_gate: PhaseDetectionGate) -> None:
        phase = phase_gate.detect_phase("plan the architecture first")
        assert phase == RALPHPhase.PLANNING

    def test_detect_handoff(self, phase_gate: PhaseDetectionGate) -> None:
        phase = phase_gate.detect_phase("handoff to hephaestus")
        assert phase == RALPHPhase.HANDOFF

    def test_unknown_phase(self, phase_gate: PhaseDetectionGate) -> None:
        phase = phase_gate.detect_phase("how are you today?")
        assert phase == RALPHPhase.UNKNOWN

    def test_phase_transition(self, phase_gate: PhaseDetectionGate) -> None:
        context = {"user_message": "create a new route"}
        result = phase_gate.pre_call("write_file", {}, context)
        assert result is not None
        assert result.intervention is True
        assert result.passed is True
        assert "ACTION" in result.message

    def test_no_transition_on_same_phase(
        self, phase_gate: PhaseDetectionGate
    ) -> None:
        context = {"user_message": "search for docs"}
        r1 = phase_gate.pre_call("read_file", {}, context)
        assert r1 is not None  # First trigger → REASONING

        r2 = phase_gate.pre_call("read_file", {}, context)
        assert r2 is None  # Same phase, no transition

    def test_get_allowed_tools(self, phase_gate: PhaseDetectionGate) -> None:
        phase_gate.current_phase = RALPHPhase.ACTION
        tools = phase_gate.get_allowed_tools()
        assert tools is not None
        assert "write_file" in tools
        assert "terminal" in tools

    def test_get_allowed_tools_unknown(
        self, phase_gate: PhaseDetectionGate
    ) -> None:
        assert phase_gate.current_phase == RALPHPhase.UNKNOWN
        assert phase_gate.get_allowed_tools() is None

    def test_phase_prompt(self, phase_gate: PhaseDetectionGate) -> None:
        phase_gate.current_phase = RALPHPhase.LOGIC
        prompt = phase_gate.get_phase_prompt()
        assert "VERIFY" in prompt

    def test_phase_history(self, phase_gate: PhaseDetectionGate) -> None:
        context = {"user_message": "find the answer"}
        phase_gate.pre_call("read_file", {}, context)
        context["user_message"] = "build the solution"
        phase_gate.pre_call("write_file", {}, context)

        assert len(phase_gate.phase_history) == 2
        assert phase_gate.phase_history[0][0] == RALPHPhase.REASONING
        assert phase_gate.phase_history[1][0] == RALPHPhase.ACTION


# ===========================================================================
# Gate 5: HandoffGate Tests
# ===========================================================================


class TestHandoffGate:
    def test_generates_manifest(self, temp_dir: str) -> None:
        gate = HandoffGate(base_path=temp_dir)
        manifest = gate.generate_manifest("hermes", "hephaestus", tier="bronze")
        assert manifest.source_god == "hermes"
        assert manifest.target_god == "hephaestus"
        assert manifest.tier in ("full", "bronze")
        assert manifest.signature != ""

    def test_manifest_has_all_checks(self, temp_dir: str) -> None:
        gate = HandoffGate(base_path=temp_dir)
        manifest = gate.generate_manifest("hermes", "hephaestus")
        expected = {
            "GIT_CLEAN", "TESTS_GREEN", "TODOS_RESOLVED",
            "LINT_CLEAN", "BLOCKS_RESOLVED", "STATE_EXPORTED",
        }
        assert set(manifest.check_results.keys()) == expected

    def test_manifest_signature_deterministic(self, temp_dir: str) -> None:
        """Same manifest object → same signature on repeated call."""
        gate = HandoffGate(base_path=temp_dir)
        m = gate.generate_manifest("a", "b")
        sig1 = m.generate_signature()
        sig2 = m.generate_signature()
        assert sig1 == sig2

    def test_signature_changes_with_source(self) -> None:
        """Different source god → different signatures (same timestamp)."""
        ts = 1000.0
        m1 = HandoffManifest("a", "b", ts, {"count": 0}, {"ok": True}, "full")
        m2 = HandoffManifest("c", "b", ts, {"count": 0}, {"ok": True}, "full")
        m1.signature = m1.generate_signature()
        m2.signature = m2.generate_signature()
        assert m1.signature != m2.signature

    def test_registered_intervention_blocks(self, temp_dir: str) -> None:
        gate = HandoffGate(base_path=temp_dir)
        gate.register_intervention(
            GateResult(
                gate_name="state_gate",
                passed=False,
                intervention=True,
                message="Blocked",
            )
        )
        passed, _ = gate._check_blocks_resolved()
        assert passed is False

    def test_no_interventions_clean(self, temp_dir: str) -> None:
        gate = HandoffGate(base_path=temp_dir)
        passed, msg = gate._check_blocks_resolved()
        assert passed is True
        assert "No" in msg or "All" in msg


# ===========================================================================
# GatePipeline Tests
# ===========================================================================


class TestGatePipeline:
    def test_pipeline_empty_pre_call(self, pipeline: GatePipeline) -> None:
        result = pipeline.run_pre_call("read_file", {"path": "x.py"})
        assert result is None

    def test_pipeline_empty_post_call(
        self, pipeline: GatePipeline
    ) -> None:
        results = pipeline.run_post_call(
            "read_file", {"path": "x.py"}, "content"
        )
        assert len(results) == 0

    def test_pipeline_state_gate_blocks(
        self, pipeline: GatePipeline, temp_dir: str
    ) -> None:
        from lib.ichor_gates import StateGate

        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()

        pipeline.register(StateGate(pipeline.read_cache))
        result = pipeline.run_pre_call(
            "write_file", {"path": path}
        )
        assert result is not None
        assert result.passed is False

    def test_pipeline_state_gate_passes(
        self, pipeline: GatePipeline, temp_dir: str
    ) -> None:
        from lib.ichor_gates import StateGate

        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()

        pipeline.register(StateGate(pipeline.read_cache))
        pipeline.read_cache.mark_read(path)
        result = pipeline.run_pre_call(
            "write_file", {"path": path}
        )
        assert result is None

    def test_pipeline_logic_gate_catches(
        self, pipeline: GatePipeline
    ) -> None:
        from lib.ichor_gates import LogicGate

        pipeline.register(LogicGate())
        results = pipeline.run_post_call(
            "write_file",
            {"path": "bad.py", "content": "invalid {{syn tax}}"},
            None,
        )
        assert len(results) > 0
        assert results[0].passed is False

    def test_pipeline_handoff_manifest(
        self, pipeline: GatePipeline
    ) -> None:
        manifest = pipeline.generate_handoff_manifest(
            "hermes", "hephaestus"
        )
        assert manifest.signature != ""
        assert len(manifest.check_results) == 6

    def test_pipeline_logs_interventions(
        self, pipeline: GatePipeline, temp_dir: str
    ) -> None:
        from lib.ichor_gates import StateGate

        path = os.path.join(temp_dir, "existing.py")
        Path(path).touch()

        pipeline.register(StateGate(pipeline.read_cache))
        pipeline.run_pre_call("write_file", {"path": path})

        # Intervention should be registered in handoff gate
        passed, _ = pipeline._handoff_gate._check_blocks_resolved()
        assert passed is False


# ===========================================================================
# HandoffManifest Tests
# ===========================================================================


class TestHandoffManifest:
    def test_minimal_manifest(self) -> None:
        m = HandoffManifest(
            source_god="a",
            target_god="b",
            timestamp=1000.0,
            state_snapshot={"count": 0},
            check_results={"ok": True},
            tier="full",
        )
        assert m.source_god == "a"
        assert m.target_god == "b"

    def test_signature_generation(self) -> None:
        m = HandoffManifest(
            source_god="a",
            target_god="b",
            timestamp=1000.0,
            state_snapshot={"count": 0},
            check_results={"ok": True},
            tier="full",
        )
        sig = m.generate_signature()
        assert len(sig) == 16
        m.signature = sig
        assert m.signature == sig

    def test_to_dict(self) -> None:
        m = HandoffManifest(
            source_god="a",
            target_god="b",
            timestamp=1000.0,
            state_snapshot={"count": 0},
            check_results={"ok": True},
            tier="bronze",
        )
        d = m.to_dict()
        assert d["source_god"] == "a"
        assert d["tier"] == "bronze"


# ===========================================================================
# GateResult Tests
# ===========================================================================


class TestGateResult:
    def test_minimal_gate_result(self) -> None:
        r = GateResult(gate_name="test", passed=True)
        assert r.passed is True
        assert bool(r) is True

    def test_gate_result_bool(self) -> None:
        r = GateResult(gate_name="test", passed=False)
        assert bool(r) is False

    def test_gate_result_to_dict(self) -> None:
        r = GateResult(
            gate_name="test",
            passed=False,
            intervention=True,
            message="blocked",
            recovery_hint="try again",
        )
        d = r.to_dict()
        assert d["gate"] == "test"
        assert d["intervention"] is True

    def test_default_values(self) -> None:
        r = GateResult(gate_name="test", passed=True)
        assert r.message == ""
        assert r.intervention is False
        assert r.recovery_hint == ""
        assert r.payload is None


# ===========================================================================
# ForgeLogger Tests
# ===========================================================================


class TestForgeLogger:
    def test_log_and_retrieve(self, forge_logger: ForgeLogger) -> None:
        forge_logger.log_intervention(
            gate_name="state_gate",
            result=GateResult(
                gate_name="state_gate",
                passed=False,
                intervention=True,
                message="blocked write",
            ),
            model="deepseek-v4-flash",
            session_id="sess-001",
        )
        stats = forge_logger.get_stats("deepseek-v4-flash")
        assert stats["total"] == 1
        assert stats["blocked"] == 1

    def test_multiple_logs(self, forge_logger: ForgeLogger) -> None:
        for i in range(5):
            forge_logger.log_intervention(
                gate_name="logic_gate",
                result=GateResult(
                    gate_name="logic_gate",
                    passed=i % 2 == 0,
                    intervention=True,
                ),
                model="llama-3-8b",
            )
        stats = forge_logger.get_stats("llama-3-8b")
        assert stats["total"] == 5
        assert stats["passed"] == 3
        assert stats["blocked"] == 2

    def test_model_stats_tracking(self, forge_logger: ForgeLogger) -> None:
        """Each model gets its own stats tracked separately."""
        forge_logger.log_intervention(
            gate_name="state_gate",
            result=GateResult(gate_name="state_gate", passed=False),
            model="model-a",
        )
        forge_logger.log_intervention(
            gate_name="logic_gate",
            result=GateResult(gate_name="logic_gate", passed=True),
            model="model-b",
        )

        a_stats = forge_logger.get_stats("model-a")
        b_stats = forge_logger.get_stats("model-b")
        assert a_stats["total"] == 1
        assert b_stats["total"] == 1
        assert a_stats["blocked"] == 1
        assert b_stats["passed"] == 1

    def test_all_log(self, forge_logger: ForgeLogger) -> None:
        forge_logger.log_intervention(
            gate_name="state_gate",
            result=GateResult(gate_name="state_gate", passed=False),
        )
        stats = forge_logger.get_stats("all")
        assert stats["total"] == 1

    def test_empty_stats(self, forge_logger: ForgeLogger) -> None:
        stats = forge_logger.get_stats("nonexistent-model")
        assert stats["total"] == 0

    def test_gate_level_breakdown(
        self, forge_logger: ForgeLogger
    ) -> None:
        forge_logger.log_intervention(
            gate_name="state_gate",
            result=GateResult(gate_name="state_gate", passed=False),
        )
        forge_logger.log_intervention(
            gate_name="logic_gate",
            result=GateResult(gate_name="logic_gate", passed=True),
        )
        forge_logger.log_intervention(
            gate_name="state_gate",
            result=GateResult(gate_name="state_gate", passed=False),
        )

        stats = forge_logger.get_stats("all")
        assert stats["gates"]["state_gate"]["total"] == 2
        assert stats["gates"]["state_gate"]["blocked"] == 2
        assert stats["gates"]["logic_gate"]["total"] == 1
        assert stats["gates"]["logic_gate"]["blocked"] == 0


# ===========================================================================
# PHASE_TOOLS / PHASE_PROMPTS Integrity Tests
# ===========================================================================


class TestPhaseData:
    def test_all_phases_have_tools(self) -> None:
        """Every phase except UNKNOWN has non-empty tool lists."""
        for phase in RALPHPhase:
            if phase == RALPHPhase.UNKNOWN:
                continue
            tools = PHASE_TOOLS.get(phase, [])
            assert len(tools) > 0, f"{phase} has no tools defined"

    def test_all_phases_have_prompts(self) -> None:
        """Every phase has a system prompt."""
        for phase in RALPHPhase:
            if phase == RALPHPhase.UNKNOWN:
                continue
            prompt = PHASE_PROMPTS.get(phase, "")
            assert prompt, f"{phase} has no prompt defined"

# ===========================================================================
# CLI Smoke Test
# ===========================================================================


class TestCLI:
    def test_cli_phase_detection(self) -> None:
        """Smoke test: CLI phase detection via main()."""
        import io
        from contextlib import redirect_stdout

        from lib.ichor_gates import main

        sys.argv = ["ichor_gates", "--test-phase", "find the bug"]
        f = io.StringIO()
        with redirect_stdout(f):
            main()
        output = f.getvalue()
        assert "REASONING" in output

    def test_cli_handoff_smoke(self) -> None:
        """Smoke test: CLI handoff via main()."""
        import io
        from contextlib import redirect_stdout

        from lib.ichor_gates import main

        sys.argv = [
            "ichor_gates", "--test-handoff", "bronze",
            "--source-god", "hermes", "--target-god", "hephaestus",
        ]
        f = io.StringIO()
        with redirect_stdout(f):
            main()
        output = f.getvalue()
        assert "hermes" in output
        assert "hephaestus" in output
