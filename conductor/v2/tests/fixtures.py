"""Shared test fixtures and helpers for the Conductor v2 test suite.

Centralizes the boilerplate every test file needs:
  - tmp layout: a fresh conductor/{rules,workflows,pending,state} under
    tempfile.mkdtemp() so tests don't touch real production state
  - real rule/workflow loading: tests verify the real YAML files in
    /home/konan/pantheon/conductor/{rules,workflows}/ load cleanly
  - mock gateway: a stable in-process GatewayClient replacement that
    returns programmable run results
  - mock handoff fixtures: real handoff JSON shape per spec section 3.3

The real production paths are NEVER touched by any test in this suite.
If a test writes to /home/konan/pantheon/conductor/state/ or pending/,
that's a bug — fix it.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock

# Project paths (read-only — tests must not write to these)
ROOT = Path("/home/konan/pantheon").expanduser()
CONDUCTOR_ROOT = ROOT / "conductor"
REAL_RULES_DIR = CONDUCTOR_ROOT / "rules"
REAL_WORKFLOWS_DIR = CONDUCTOR_ROOT / "workflows"
REAL_PENDING_DIR = CONDUCTOR_ROOT / "pending"
REAL_STATE_DIR = CONDUCTOR_ROOT / "state"

# Make the v2 package importable
sys.path.insert(0, str(CONDUCTOR_ROOT))

# Force lazy path resolvers in engine/delivery/service to look at the
# tmp dir, not the real one. This must happen BEFORE any v2 import.
_TEST_TMP = Path(tempfile.mkdtemp(prefix="conductor_v2_tests_"))
import os
os.environ["CONDUCTOR_BASE_DIR"] = str(_TEST_TMP)
# NOTE: this os.environ mutation persists for the rest of the pytest
# process and would pollute v1 contract tests (test_conductor_server.py
# etc.) that run after this v2 session. The pytest_runtest_teardown hook
# in conftest.py restores CONDUCTOR_BASE_DIR to the production default
# after the LAST v2 test finishes. Do not remove this line and do not add
# an atexit restore here — it would not fire in time for v1 tests. The
# conftest hook is the correct mechanism.

# Marvin hygiene #1, Step 1.7 polish: canonical import paths.
# Bare `from v2 import ...` works only because tests run with
# PYTHONPATH=/home/konan/pantheon (so v2/ is on sys.path) — but
# `from conductor.v2 import ...` works in every test invocation,
# including bare pytest from outside the repo. The canonical form
# also matches what every v2 source module already does.
from conductor.v2 import engine as eng  # noqa: E402
from conductor.v2 import gateway as gw_mod  # noqa: E402
from conductor.v2 import delivery as d  # noqa: E402

LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test layout
# ---------------------------------------------------------------------------

@dataclass
class TmpConductor:
    """A fresh conductor layout rooted at a tmp directory. Clean up via
    .cleanup(). Sub-dirs mirror the real production layout:
        {root}/rules, workflows, pending, state

    Each .create() call gets a UNIQUE tmp directory so tests cannot
    leak state into each other.
    """
    root: Path
    rules_dir: Path
    workflows_dir: Path
    pending_dir: Path
    state_dir: Path
    journal_dir: Path
    inbox_dir: Path
    quarantine_dir: Path
    webhooks_dir: Path

    @classmethod
    def create(cls) -> "TmpConductor":
        # Each test gets its own tmp dir AND its own CONDUCTOR_BASE_DIR env
        # so the engine's lazy path resolution looks at the right place.
        root = Path(tempfile.mkdtemp(prefix="conductor_v2_"))
        os.environ["CONDUCTOR_BASE_DIR"] = str(root)
        rules = root / "rules"
        workflows = root / "workflows"
        pending = root / "pending"
        state = root / "state"
        for p in (rules, workflows, pending, state):
            p.mkdir(parents=True, exist_ok=True)
        return cls(
            root=root,
            rules_dir=rules,
            workflows_dir=workflows,
            pending_dir=pending,
            state_dir=state,
            journal_dir=pending / "_journal",
            inbox_dir=pending / "inbox",
            quarantine_dir=pending / "_quarantine",
            webhooks_dir=pending / "_webhooks",
        )

    def copy_real_rules(self) -> list[Path]:
        """Copy the production rules/*.yaml into the tmp rules dir.
        Returns the list of files copied. Used to test the real rule
        files load cleanly and match the expected events."""
        if not REAL_RULES_DIR.exists():
            return []
        copied = []
        for src in sorted(REAL_RULES_DIR.glob("*.yaml")):
            dst = self.rules_dir / src.name
            shutil.copy(src, dst)
            copied.append(dst)
        return copied

    def copy_real_workflows(self) -> list[Path]:
        if not REAL_WORKFLOWS_DIR.exists():
            return []
        copied = []
        for src in sorted(REAL_WORKFLOWS_DIR.glob("*.yaml")):
            dst = self.workflows_dir / src.name
            shutil.copy(src, dst)
            copied.append(dst)
        return copied

    def cleanup(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)


# ---------------------------------------------------------------------------
# Mock gateway
# ---------------------------------------------------------------------------

@dataclass
class MockRun:
    """A run that the mock gateway will return when polled."""
    run_id: str
    output: str = ""
    status: str = "completed"
    error: Optional[str] = None
    elapsed: float = 0.0
    session_id: str = ""


class MockGatewayClient:
    """A programmable mock of the gateway.GatewayClient interface.

    The ConductorEngine only ever calls .submit_run() (returns a run_id)
    and .wait_for_run() (returns a RunResult). Both are async. The mock
    also exposes .calls for assertions.

    Usage:
        gw = MockGatewayClient()
        gw.queue_run(MockRun("run_1", output="hello"))
        gw.queue_run(MockRun("run_2", output="world", status="failed"))
        # ... engine.start_workflow(...).wait ...
        assert len(gw.calls) == 2
    """

    def __init__(self):
        self.queued: list[MockRun] = []
        self.calls: list[dict[str, Any]] = []  # (model, prompt) per submit
        self.submit_counter = 0
        self.fail_submit: Optional[Exception] = None
        self.fail_wait: Optional[Exception] = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    def queue_run(self, run: MockRun) -> None:
        self.queued.append(run)

    def make_run_id(self) -> str:
        self.submit_counter += 1
        return f"run_mock_{self.submit_counter:04d}"

    async def submit_run(
        self,
        input_text: str,
        *,
        model: Optional[str] = None,
        session_id: Optional[str] = None,
        session_key: Optional[str] = None,
        extra: Optional[dict[str, Any]] = None,
    ) -> str:
        self.calls.append({
            "model": model,
            "prompt_preview": input_text[:200],
            "session_id": session_id,
        })
        if self.fail_submit:
            raise self.fail_submit
        return self.make_run_id()

    async def wait_for_run(
        self, run_id: str, *, timeout: Optional[float] = None, poll_interval: Optional[float] = None
    ) -> gw_mod.RunResult:
        if self.fail_wait:
            raise self.fail_wait
        if not self.queued:
            raise AssertionError(f"MockGatewayClient: no queued run for {run_id}")
        run = self.queued.pop(0)
        return gw_mod.RunResult(
            run_id=run_id,
            status=run.status,
            output=run.output,
            error=run.error,
            session_id=run.session_id,
        )

    async def get_run(self, run_id: str) -> gw_mod.RunResult:
        return await self.wait_for_run(run_id)

    async def health(self) -> dict[str, Any]:
        return {"status": "ok", "platform": "mock"}

    async def capabilities(self) -> dict[str, Any]:
        return {"models": ["thoth", "hephaestus", "marvin", "hermes", "iris"]}

    async def stop_run(self, run_id: str) -> dict[str, Any]:
        return {"status": "stopped", "run_id": run_id}

    async def stream_run_events(self, run_id: str):
        if False:
            yield
        return
        yield  # make this an async generator


# ---------------------------------------------------------------------------
# Real handoff fixtures (spec section 3.3)
# ---------------------------------------------------------------------------

def make_handoff(
    *,
    from_god: str = "thoth",
    to_god: str = "hephaestus",
    workflow_id: str = "wf_test",
    step: Optional[str] = None,
    summary: str = "test handoff",
    decisions: Optional[list[str]] = None,
    artifacts: Optional[list[str]] = None,
    gates_passed: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Build a handoff dict matching spec section 3.3 minimal schema."""
    return {
        "handoff_id": f"hof_{eng.utc_now()[:10].replace('-', '')}_test01",
        "workflow_id": workflow_id,
        "from_god": from_god,
        "to_god": to_god,
        "step": step,
        "context": {
            "summary": summary,
            "decisions": decisions or [],
            "artifacts": artifacts or [],
            "gates_passed": gates_passed or [],
        },
    }


def write_handoff_to_pending(
    tmp: TmpConductor,
    handoff: dict[str, Any],
    god: str,
) -> Path:
    """Write a handoff dict to pending/<god>/. Returns the path."""
    god_dir = tmp.pending_dir / god
    god_dir.mkdir(parents=True, exist_ok=True)
    path = god_dir / f"{handoff['handoff_id']}.json"
    path.write_text(json.dumps(handoff, indent=2))
    return path
