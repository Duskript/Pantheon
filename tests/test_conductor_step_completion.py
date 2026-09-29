"""Regression tests for Conductor workflow step-history completion.

Content pipeline operator gates can revisit a god step after angle reselection or
rewrite feedback. The engine must complete the newest in-progress attempt, not an
older completed attempt for the same step id.
"""

from conductor.v2.engine import ConductorEngine, WorkflowInstance, WorkflowStep
from conductor.v2.gateway import RunResult


def test_record_step_completion_updates_latest_in_progress_attempt():
    """A repeated god step should not leave its newest history row in_progress."""
    engine = object.__new__(ConductorEngine)
    inst = WorkflowInstance(
        workflow_id="wf_test",
        definition_id="social-content-pipeline",
        definition_version="2.0.0",
        current_step="rheta-draft-selected-angle",
        step_history=[
            {
                "step_id": "rheta-draft-selected-angle",
                "god": "rheta",
                "status": "completed",
                "started": "2026-08-10T20:29:36Z",
                "completed": "2026-08-10T20:30:57Z",
                "output_summary": "first draft",
            },
            {
                "step_id": "operator-approve-draft",
                "god": "operator",
                "status": "decision:select-angle",
                "started": "2026-08-10T20:30:58Z",
                "completed": "2026-08-10T20:30:58Z",
                "output_summary": "operator picked a different angle",
            },
            {
                "step_id": "rheta-draft-selected-angle",
                "god": "rheta",
                "status": "in_progress",
                "started": "2026-08-10T20:31:00Z",
                "completed": None,
                "output_summary": None,
            },
        ],
    )
    step = WorkflowStep(id="rheta-draft-selected-angle", god="rheta", output="post_draft")
    result = RunResult(run_id="run_test", status="completed", output="second draft")

    engine._record_step_completion(inst, step, result)

    assert inst.step_history[0]["status"] == "completed"
    assert inst.step_history[0]["output_summary"] == "first draft"
    assert inst.step_history[2]["status"] == "completed"
    assert inst.step_history[2]["completed"] is not None
    assert inst.step_history[2]["output_summary"] == "second draft"
    assert inst.context_bag["post_draft"] == "second draft"


def test_record_step_failure_updates_latest_in_progress_attempt():
    """A repeated god step failure should mark the current attempt, not history."""
    engine = object.__new__(ConductorEngine)
    inst = WorkflowInstance(
        workflow_id="wf_test",
        definition_id="social-content-pipeline",
        definition_version="2.0.0",
        current_step="rheta-draft-selected-angle",
        step_history=[
            {
                "step_id": "rheta-draft-selected-angle",
                "god": "rheta",
                "status": "completed",
                "started": "2026-08-10T20:29:36Z",
                "completed": "2026-08-10T20:30:57Z",
                "output_summary": "first draft",
            },
            {
                "step_id": "rheta-draft-selected-angle",
                "god": "rheta",
                "status": "in_progress",
                "started": "2026-08-10T20:31:00Z",
                "completed": None,
                "output_summary": None,
            },
        ],
    )
    step = WorkflowStep(id="rheta-draft-selected-angle", god="rheta", output="post_draft")

    engine._record_step_failure(inst, step, "gateway exploded")

    assert inst.step_history[0]["status"] == "completed"
    assert inst.step_history[0]["output_summary"] == "first draft"
    assert inst.step_history[1]["status"] == "failed"
    assert inst.step_history[1]["completed"] is not None
    assert inst.step_history[1]["output_summary"] == "FAILED: gateway exploded"



def test_content_dashboard_rule_routes_by_payload_workflow_id():
    from pathlib import Path

    from conductor.v2.engine import Event, Rule

    blog_rule = Rule.from_dict({
        "id": "content-dashboard-blog-start",
        "when": {
            "event_type": "webhook",
            "source": "pantheon-content-dashboard",
            "subject": "/dispatch",
            "payload.workflow_id": "blog-content-pipeline",
        },
        "then": {"dispatch_workflow": "blog-content-pipeline"},
    }, Path("content-dashboard.yaml"))
    social_rule = Rule.from_dict({
        "id": "content-dashboard-social-start",
        "when": {
            "event_type": "webhook",
            "source": "pantheon-content-dashboard",
            "subject": "/dispatch",
            "payload.workflow_id": "social-content-pipeline",
        },
        "then": {"dispatch_workflow": "social-content-pipeline"},
    }, Path("content-dashboard.yaml"))

    event = Event(
        type="webhook",
        source="pantheon-content-dashboard",
        subject="/dispatch",
        payload={
            "workflow_id": "blog-content-pipeline",
            "summary": "Blog content from approved current-signal research",
            "context": {"blog_destination": "ghost-draft"},
        },
    )

    assert blog_rule.matches(event)
    assert not social_rule.matches(event)
