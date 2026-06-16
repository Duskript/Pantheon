"""Tests for the v2 routing marker in Conductor.submit_handoff (Step 1.2 Option C).

These tests pin the telemetry marker `v2_definition_known` that submit_handoff
emits in its return dict. The marker is a cheap, lossy "v2 knows this workflow
definition" lookup — it is NEVER a blocker, and the v1 dispatch path below it
must keep working even if v2 import/lookup fails (the try/except guard
exists precisely to enforce that invariant).

Run: /home/konan/.hermes/hermes-agent/venv/bin/python3 -m pytest \
        conductor/v2/tests/test_v2_marker.py -v
"""

from __future__ import annotations

import sys
import unittest
import uuid
from pathlib import Path

# _ROOT = parent of conductor/ (i.e., the pantheon checkout root), so that
# `from v2.tests import fixtures` and `import conductor.conductor_server`
# both resolve. Same convention as test_conductor_bridge.py.
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from v2.tests import fixtures as cf  # noqa: E402

import conductor.conductor_server as bridge  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# handoff_id must match the validator regex ^hof_\d{8}_[a-z0-9]{6,8}$
# (see /home/konan/pantheon/shared/handoffs/schema.json:32). A static, valid
# id keeps the test output deterministic.
_HANDOFF_ID = "hof_20260614_mkr2tst"


def _make_handoff(
    *,
    workflow_definition: str | None,
    include_routing: bool = True,
) -> dict:
    """Build a minimal valid handoff dict per the handoff schema.

    Required fields per schema (handoffs/schema.json:90-97):
        handoff_id, workflow_id, from_god, to_god, step, context
    `routing` is optional (per the schema, additionalProperties: false only
    applies to the handoff object itself; `routing` is an optional property
    of the handoff — see lines 119-135). When include_routing=False, we
    deliberately omit the entire `routing` key.
    """
    handoff: dict = {
        "handoff_id": _HANDOFF_ID,
        "workflow_id": f"wf_marker_{uuid.uuid4().hex[:8]}",
        "from_god": "thoth",
        "to_god": "hephaestus",
        "step": "step1",
        "context": {
            "summary": "v2 marker test handoff",
            "decisions": [],
            "artifacts": [],
            "gates_passed": [],
        },
    }
    if include_routing and workflow_definition is not None:
        handoff["routing"] = {"workflow_definition": workflow_definition}
    return handoff


def _build_conductor_with_real_workflows(
    tmp: cf.TmpConductor,
) -> bridge.Conductor:
    """Create a Conductor bound to the tmp layout, with real workflows copied in.

    `cf.TmpConductor.create()` already sets `CONDUCTOR_BASE_DIR=tmp.root`,
    so the engine's lazy `_workflows_dir()` resolver returns
    `tmp.root/workflows/`. After the Step 1.6 lazy fix (see
    v2/engine.py:WorkflowRegistry docstring), the bridge's `_v2_engine()`
    builds a fresh `ConductorEngine()` whose `WorkflowRegistry` reads
    from that lazy-resolved path. So we MUST copy the real workflows
    into `tmp.workflows_dir` for the bridge path to find them.

    We also seed `eng.WORKFLOWS_DIR` (the session-level frozen
    constant) for safety, in case any v2-direct test code in the same
    pytest run reads from that path.
    """
    # Mirror test_conductor_bridge.py: copy the real workflows into the
    # bridge's lazy-resolved dir (the per-test tmp) so the WorkflowRegistry
    # loads them. Also seed the session-level eng.WORKFLOWS_DIR for
    # v2-direct-path readers.
    from conductor.v2 import engine as eng  # noqa: E402  # canonical import
    eng.WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
    tmp.workflows_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    for src in sorted((cf.REAL_WORKFLOWS_DIR).glob("*.yaml")):
        # Per-test tmp copy — what the bridge path reads from
        dst = tmp.workflows_dir / src.name
        if not dst.exists():
            shutil.copy(src, dst)
        # Session-level eng.WORKFLOWS_DIR copy — what direct-engine
        # readers (e.g. test_engine.py) read from
        dst_eng = eng.WORKFLOWS_DIR / src.name
        if not dst_eng.exists():
            shutil.copy(src, dst_eng)
    return bridge.Conductor(base_dir=tmp.root)


# ===========================================================================
# 1. Marker is True when v2 actually knows the workflow definition
# ===========================================================================

class TestMarkerTrueWhenDefinitionKnown(unittest.TestCase):
    """routing.workflow_definition points at a real v2 workflow → marker is True."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.conductor = _build_conductor_with_real_workflows(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marker_true_when_workflow_definition_known(self):
        handoff = _make_handoff(workflow_definition="morning-briefing")

        result = self.conductor.submit_handoff(handoff)

        # The marker key MUST be present and True for a known definition.
        self.assertIn(
            "v2_definition_known", result,
            "submit_handoff must return a v2_definition_known marker",
        )
        self.assertIs(
            result["v2_definition_known"], True,
            f"expected True for known workflow 'morning-briefing', got {result!r}",
        )
        # Sanity: the dispatch path still ran (marker is telemetry only,
        # it MUST NOT block the v1 dispatch below it).
        self.assertEqual(result["status"], "dispatched")


# ===========================================================================
# 2. Marker is False when the definition is unknown
# ===========================================================================

class TestMarkerFalseWhenDefinitionUnknown(unittest.TestCase):
    """routing.workflow_definition is a bogus id → marker is False, no crash."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.conductor = _build_conductor_with_real_workflows(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marker_false_when_workflow_definition_unknown(self):
        handoff = _make_handoff(workflow_definition="no-such-workflow-xyz")

        result = self.conductor.submit_handoff(handoff)

        self.assertIn("v2_definition_known", result)
        self.assertIs(
            result["v2_definition_known"], False,
            f"expected False for unknown workflow, got {result!r}",
        )
        # The dispatch path still ran (Unknown definition_id only means the
        # marker is False; the handoff is still recorded + dispatched to
        # the god named in routing/to_god, or recorded if no next step).
        self.assertIn(result["status"], ("dispatched", "recorded"))


# ===========================================================================
# 3. Marker is False when routing is missing entirely
# ===========================================================================

class TestMarkerFalseWhenRoutingMissing(unittest.TestCase):
    """No `routing` key at all → marker is False, no exception raised."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.conductor = _build_conductor_with_real_workflows(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marker_false_when_routing_missing(self):
        handoff = _make_handoff(workflow_definition=None, include_routing=False)
        # Sanity: confirm we really omitted routing
        self.assertNotIn("routing", handoff)

        # The whole point of this test: no exception is raised.
        result = self.conductor.submit_handoff(handoff)

        self.assertIn("v2_definition_known", result)
        self.assertIs(
            result["v2_definition_known"], False,
            f"expected False when routing is missing, got {result!r}",
        )
        # Dispatch path still ran
        self.assertIn(result["status"], ("dispatched", "recorded"))


# ===========================================================================
# 4. Marker is False when v2 engine is broken (the try/except guard)
# ===========================================================================

class TestMarkerFalseWhenV2EngineBroken(unittest.TestCase):
    """If _v2_engine() raises, the try/except guard MUST keep marker=False
    and the call MUST NOT propagate the exception. This is the load-bearing
    invariant: v2 can never poison the v1 dispatch path."""

    def setUp(self):
        self.tmp = cf.TmpConductor.create()
        self.conductor = _build_conductor_with_real_workflows(self.tmp)

    def tearDown(self):
        self.tmp.cleanup()

    def test_marker_false_when_v2_engine_broken(self):
        def _broken_v2_engine():
            raise ImportError("simulated v2 failure")

        # Patch the bound method on the instance. This is the exact
        # method the marker code at conductor_server.py:329 calls.
        self.conductor._v2_engine = _broken_v2_engine  # type: ignore[method-assign]

        handoff = _make_handoff(workflow_definition="morning-briefing")

        # If the try/except guard is missing or wrong, this will raise
        # ImportError. The whole point of this test: it MUST NOT raise.
        result = self.conductor.submit_handoff(handoff)

        self.assertIn("v2_definition_known", result)
        self.assertIs(
            result["v2_definition_known"], False,
            f"expected False when v2 engine raises, got {result!r}",
        )
        # And the v1 dispatch path completed normally.
        self.assertIn(result["status"], ("dispatched", "recorded"))


if __name__ == "__main__":
    unittest.main()
