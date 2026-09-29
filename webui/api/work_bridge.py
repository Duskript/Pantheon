"""
work_bridge.py — Work surface adapter for Olympus UI.

Read-only operational state: active lanes, project ideas, cron jobs,
recent failures, and workflow runs. All backed by real local data
(kanban DB, cron jobs.json, conductor state files).

Endpoints:
  GET /api/work/lanes        → active work lanes from kanban DB
  GET /api/work/ideas        → project ideas from kanban DB
  GET /api/work/cron         → scheduled cron jobs
  GET /api/work/failures     → recent aborted workflow runs
  GET /api/workflows         → Conductor workflow definitions / pipelines
  GET /api/workflows/runs    → all workflow run state
  POST /api/workflows/start  → mint a Conductor workflow run
  POST /api/workflows/pipelines → create a new YAML-backed pipeline definition
"""

from __future__ import annotations

import json
import os
import glob
import mimetypes
import re
import sqlite3
import subprocess
import sys
import uuid
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

PANTHEON_ROOT = Path(__file__).resolve().parents[2]
if str(PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(PANTHEON_ROOT))

import yaml

from api.helpers import bad, j, t

# ── Paths ──────────────────────────────────────────────────────────────────
KANBAN_DB = os.path.expanduser("~/.hermes/kanban.db")
CRON_JOBS_FILE = os.path.expanduser("~/.hermes/cron/jobs.json")
CONDUCTOR_STATE_DIR = os.path.expanduser("~/pantheon/conductor/state")
CONDUCTOR_WORKFLOWS_DIR = os.path.expanduser("~/pantheon/conductor/workflows")
CONDUCTOR_DECISIONS_DIR = os.path.expanduser("~/pantheon/conductor/state/operator-decisions")
CONTENT_TOPIC_BANK_FILE = Path(os.environ.get("CONTENT_TOPIC_BANK_FILE", "~/pantheon/shared/content-topic-bank.json")).expanduser()
CONTENT_TOPIC_REFRESH_SCRIPT = Path("/home/konan/pantheon/scripts/refresh-content-topic-bank.py")
CONTENT_QUEUE_ROOTS = {
    "social": Path(os.environ.get("PHONE_JOB_QUEUE_ROOT", "~/pantheon/phone-queue")).expanduser(),
    "blog": Path(os.environ.get("BLOG_JOB_QUEUE_ROOT", "~/pantheon/blog-queue")).expanduser(),
}
GENERATED_IMAGE_ROOTS = [
    Path(os.environ.get("BLOG_IMAGE_STORAGE_DIR") or os.environ.get("AD_IMAGE_STORAGE_DIR") or "~/pantheon/blog-queue/images").expanduser(),
    Path(os.environ.get("SOCIAL_IMAGE_STORAGE_DIR") or "~/pantheon/phone-queue/images").expanduser(),
]


# ══════════════════════════════════════════════════════════════════════════════
# Lanes — active work items from kanban DB
# ══════════════════════════════════════════════════════════════════════════════

def _get_lanes(limit: int = 20):
    """Read active (non-archived, non-done) tasks from the kanban DB."""
    if not os.path.exists(KANBAN_DB):
        return {"lanes": []}

    try:
        conn = sqlite3.connect(KANBAN_DB)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, title, assignee, status, priority,
                   created_at, updated_at, board_id, column_id
            FROM tasks
            WHERE status NOT IN ('done', 'archived')
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()

        lanes = []
        for r in rows:
            lanes.append({
                "id": r["id"],
                "name": r["title"] if r["title"] else "Untitled",
                "owner": r["assignee"] or "unassigned",
                "status": _map_kanban_status(r["status"]),
                "updatedAt": _iso_or_none(r["updated_at"]),
                "summary": _first_line(r["title"] or "", 100),
                "god": r["assignee"] or None,
            })
        return {"lanes": lanes}
    except Exception as e:
        return {"lanes": [], "error": str(e)}


def _map_kanban_status(s: str) -> str:
    """Map kanban status to LaneDTO status enum."""
    map_ = {
        "todo": "idle",
        "in_progress": "active",
        "blocked": "blocked",
        "review": "review",
    }
    return map_.get(s, "idle")


# ══════════════════════════════════════════════════════════════════════════════
# Project ideas — from kanban DB where kind / tag indicates "idea"
# ══════════════════════════════════════════════════════════════════════════════

def _get_ideas(limit: int = 20):
    """Read project ideas. Falls back to kanban tasks tagged as ideas
    or to the task_events table. If nothing found, returns empty."""
    ideas = []
    if not os.path.exists(KANBAN_DB):
        return {"ideas": []}

    try:
        conn = sqlite3.connect(KANBAN_DB)
        conn.row_factory = sqlite3.Row

        # Try tasks with "idea" in title or low-priority todo items
        rows = conn.execute(
            """
            SELECT id, title, body, created_at
            FROM tasks
            WHERE (title LIKE '%idea%' OR priority <= 2)
              AND status NOT IN ('archived')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        conn.close()

        for r in rows:
            ideas.append({
                "id": r["id"],
                "title": _first_line(r["title"] or "Untitled idea", 80),
                "body": (r["body"] or "")[:500],
                "createdAt": _iso_or_none(r["created_at"]),
            })
    except Exception:
        pass

    return {"ideas": ideas}


# ══════════════════════════════════════════════════════════════════════════════
# Cron jobs — from ~/.hermes/cron/jobs.json
# ══════════════════════════════════════════════════════════════════════════════

def _get_cron_jobs():
    """Read scheduled cron jobs from the jobs manifest."""
    if not os.path.exists(CRON_JOBS_FILE):
        return {"jobs": []}

    try:
        with open(CRON_JOBS_FILE) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"jobs": []}

    jobs_raw = data.get("jobs", []) if isinstance(data, dict) else data
    if not isinstance(jobs_raw, list):
        return {"jobs": []}

    jobs = []
    for j in jobs_raw:
        schedule = j.get("schedule", {})
        display = schedule.get("display", "") if isinstance(schedule, dict) else str(schedule)
        paused = j.get("paused", False)

        jobs.append({
            "id": j.get("id", ""),
            "name": j.get("name", "Unnamed cron job"),
            "schedule": display,
            "status": "paused" if paused else "ok",
            "lastRunAt": j.get("updated_at"),
            "lastExitCode": None,
            "note": j.get("prompt", "")[:120] if j.get("prompt") else None,
        })
    return {"jobs": jobs}


# ══════════════════════════════════════════════════════════════════════════════
# Failures — aborted Conductor workflow runs
# ══════════════════════════════════════════════════════════════════════════════

def _get_failures(limit: int = 10):
    """Read recent aborted workflow runs from conductor state files."""
    if not os.path.isdir(CONDUCTOR_STATE_DIR):
        return {"failures": []}

    try:
        all_files = glob.glob(os.path.join(CONDUCTOR_STATE_DIR, "*.json"))
    except OSError:
        return {"failures": []}

    # Filter to non-aborted-marker, actual state files
    state_files = [f for f in all_files if ".aborted." not in os.path.basename(f)]
    failures = []

    for fp in sorted(state_files, key=os.path.getmtime, reverse=True):
        try:
            with open(fp) as fh:
                d = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        status = d.get("status", "")
        if status != "aborted" and not d.get("error"):
            continue

        failures.append({
            "id": d.get("workflow_id", os.path.basename(fp).replace(".json", "")),
            "runId": d.get("workflow_id", ""),
            "error": str(d.get("error") or d.get("message") or f"Aborted at step: {d.get('current_step', 'unknown')}"),
            "timestamp": d.get("started_at") or d.get("updated_at") or _file_mtime_iso(fp),
            "god": d.get("initiator") or d.get("source_god"),
        })

        if len(failures) >= limit:
            break

    return {"failures": failures}


# ══════════════════════════════════════════════════════════════════════════════
# Workflow runs — all Conductor state files
# ══════════════════════════════════════════════════════════════════════════════

def _get_workflow_runs(limit: int = 50):
    """Read all conductor workflow run state files."""
    if not os.path.isdir(CONDUCTOR_STATE_DIR):
        return {"runs": []}

    try:
        all_files = glob.glob(os.path.join(CONDUCTOR_STATE_DIR, "*.json"))
    except OSError:
        return {"runs": []}

    state_files = [f for f in all_files if ".aborted." not in os.path.basename(f)]
    runs = []

    for fp in sorted(state_files, key=os.path.getmtime, reverse=True):
        try:
            with open(fp) as fh:
                d = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        wf_id = d.get("workflow_id", os.path.basename(fp).replace(".json", ""))
        context = d.get("context_bag") if isinstance(d.get("context_bag"), dict) else {}
        history = d.get("step_history") if isinstance(d.get("step_history"), list) else []
        runs.append({
            "id": wf_id,
            "workflowId": d.get("definition_id", wf_id),
            "status": _map_run_status(d.get("status", "unknown")),
            "startedAt": d.get("created") or d.get("started_at"),
            "finishedAt": d.get("finished_at") or d.get("updated_at"),
            "currentStep": d.get("current_step"),
            "initiator": d.get("initiator"),
            "message": str(d.get("error") or d.get("message") or d.get("original_request") or "")[:500] or None,
            "context": _safe_context(context),
            "stepHistory": _safe_step_history(history),
            "blockers": (d.get("blockers") if isinstance(d.get("blockers"), list) else None)
            or (context.get("blockers") if isinstance(context.get("blockers"), list) else None),
        })

        if len(runs) >= limit:
            break

    return {"runs": runs}


def _safe_context(context: dict) -> dict:
    """Return compact, non-secret workflow context for operator dashboards."""
    allowed = {
        "surface", "topic", "topic_or_link", "topic_id", "topic_title", "topic_lane", "link", "post_type", "surfaces",
        "cadence", "auto_approve", "selected_angle", "feedback", "draft_choice", "research_sources", "is_kairos_recommended", "agent_reach", "topic_signal",
        "event_payload", "signal_brief", "angle_options", "post_draft", "blog_draft",
        "publish_result", "phone_publish_jobs", "blog_publish_result", "blog_publish_jobs",
        "blog_title", "blog_destination", "blog_publish_mode", "include_sources",
        "generate_image", "requires_featured_image", "requires_social_image", "blog_image_result", "social_image_results",
        "blog_image_variants", "social_image_variants", "selected_image_path", "selected_image_url", "selected_images",
        "scheduled_for", "publish_at", "recommended_time", "operator_decisions", "dashboard_status",
    }
    out = {}
    for key, value in context.items():
        if key not in allowed:
            continue
        if key in {"blog_image_result", "blog_image_variants"}:
            out[key] = _safe_image_package(value)
            continue
        if key in {"social_image_results", "social_image_variants"} and isinstance(value, dict):
            out[key] = {str(surface): _safe_image_package(package) for surface, package in value.items()}
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
        elif isinstance(value, (list, dict)):
            safe_text = json.dumps(value, ensure_ascii=False)
            out[key] = json.loads(safe_text[:4000]) if len(safe_text) < 4000 else safe_text[:4000]
    return out


def _safe_image_package(value):
    if not isinstance(value, dict):
        return value
    keys = {
        "ok", "status", "provider", "model", "size", "image_path", "selected_image_path",
        "image_url", "alt", "generated_at", "note", "surface", "workflow_id", "mime_type",
        "title", "label", "variant_index", "error", "variant_label",
    }
    out = {key: value.get(key) for key in keys if key in value}
    if out.get("image_path"):
        out["image_url"] = f"/api/workflows/image?path={urllib.request.pathname2url(str(out['image_path']))}"
    items = value.get("items")
    if isinstance(items, list):
        out["items"] = [_safe_image_package(item) for item in items[:8] if isinstance(item, dict)]
    return out


def _safe_step_history(history: list) -> list:
    """Return compact step history rows for dashboard detail panes."""
    rows = []
    for step in history[-12:]:
        if not isinstance(step, dict):
            continue
        rows.append({
            "stepId": step.get("step_id"),
            "god": step.get("god"),
            "status": step.get("status"),
            "started": step.get("started"),
            "completed": step.get("completed"),
            "summary": str(step.get("output_summary") or "")[:500] or None,
        })
    return rows


def _map_run_status(s: str) -> str:
    """Normalise conductor status strings to frontend enum."""
    s_lower = s.lower() if s else ""
    if "abort" in s_lower or "fail" in s_lower or "error" in s_lower:
        return "failed"
    if "complet" in s_lower or "done" in s_lower or "success" in s_lower:
        return "succeeded"
    if "run" in s_lower or "in_progress" in s_lower or "active" in s_lower:
        return "running"
    if "approv" in s_lower or "wait" in s_lower or "pending" in s_lower:
        return "awaiting-approval"
    return "running"



# ══════════════════════════════════════════════════════════════════════════════
# Workflow definitions / content pipelines — from conductor/workflows/*.yaml
# ══════════════════════════════════════════════════════════════════════════════

_ALLOWED_GODS = {
    "hermes", "athena", "apollo", "thoth", "hephaestus", "hades",
    "kairos", "iris", "marvin", "clara", "operator",
}


def _get_workflows():
    """List Conductor workflow definitions as frontend WorkflowDTO rows."""
    try:
        from conductor.v2.engine import WorkflowRegistry

        registry = WorkflowRegistry(workflows_dir=Path(CONDUCTOR_WORKFLOWS_DIR))
        workflows = [_workflow_to_dto(wf) for wf in registry.all()]
    except Exception as e:
        return {"workflows": [], "total": 0, "error": str(e)}

    workflows.sort(key=lambda w: (w.get("category") != "content-pipeline", w.get("name", "")))
    return {"workflows": workflows, "total": len(workflows)}


def _workflow_to_dto(wf):
    steps = list(getattr(wf, "steps", []) or [])
    owner = next((getattr(s, "god", None) for s in steps if getattr(s, "god", None)), None)
    first_gate = _first_gate(steps)
    source_path = str(getattr(wf, "source_path", ""))
    category = _workflow_category(wf, owner)
    return {
        "id": wf.id,
        "name": wf.name,
        "description": wf.description or "Conductor workflow definition.",
        "kind": "pipeline" if category.endswith("pipeline") or "pipeline" in wf.id else "template",
        "category": category,
        "tags": _workflow_tags(wf, owner, first_gate),
        "difficulty": _workflow_difficulty(steps),
        "updatedAt": _file_mtime_iso(source_path) if source_path else None,
        "ownerGod": owner or "operator",
        "schedule": _workflow_schedule_hint(wf),
        "nextGate": first_gate,
        "sourcePath": os.path.basename(source_path) if source_path else None,
        "stepCount": len(steps),
    }


def _workflow_category(wf, owner: str | None) -> str:
    text = " ".join([wf.id, wf.name, wf.description or ""]).lower()
    if "content" in text or owner == "kairos":
        return "content-pipeline"
    if "brief" in text or "digest" in text:
        return "briefing-pipeline"
    if "lead" in text or "webhook" in text:
        return "lead-pipeline"
    return "conductor-pipeline"


def _workflow_tags(wf, owner: str | None, first_gate: str | None) -> list[str]:
    tags = ["conductor"]
    category = _workflow_category(wf, owner)
    if category:
        tags.append(category)
    if owner:
        tags.append(owner)
    if first_gate:
        tags.append("human-gated")
    return list(dict.fromkeys(tags))


def _workflow_difficulty(steps: list) -> str:
    if len(steps) >= 6:
        return "advanced"
    if len(steps) >= 3:
        return "intermediate"
    return "beginner"


def _workflow_schedule_hint(wf) -> str | None:
    text = (wf.description or "").lower()
    for word in ("daily", "weekly", "monthly", "hourly"):
        if word in text:
            return word
    return None


def _first_gate(steps: list) -> str | None:
    for step in steps:
        gates = getattr(step, "gates", None) or []
        if gates:
            return str(gates[0])
        if getattr(step, "type", "") == "nats_publish":
            return "operator-review"
    return None


def _start_workflow(body: dict):
    """Start a workflow from the dashboard.

    For the Social cockpit, prefer the live Conductor daemon path. The older
    sync path only minted a wf_*.json state file and never executed the first
    step, which made the dashboard look alive while every run stayed stuck.
    """
    workflow_id = str(body.get("workflow_id") or body.get("workflowId") or "").strip()
    if not workflow_id:
        raise ValueError("Missing workflow_id")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    initiator = str(body.get("initiator") or "olympus-ui")[:80]
    original_request = str(body.get("original_request") or body.get("note") or "Started from Olympus pipeline dashboard")[:500]

    live_content_workflows = {"social-content-pipeline", "blog-content-pipeline"}
    if workflow_id in live_content_workflows:
        queued = _queue_workflow_event(
            workflow_id=workflow_id,
            context=context,
            initiator=initiator,
            original_request=original_request,
        )
        if queued.get("ok"):
            return queued
        label = "Social" if workflow_id == "social-content-pipeline" else "Blog"
        raise RuntimeError(
            f"{label} content runs must queue through the live Conductor daemon; "
            f"daemon dispatch failed: {queued.get('error') or 'unknown error'}"
        )

    from conductor.v2.engine import ConductorEngine

    engine = ConductorEngine(workflows_dir=Path(CONDUCTOR_WORKFLOWS_DIR))
    inst = engine.start_workflow_sync(
        workflow_id,
        context=context,
        initiator=initiator,
        original_request=original_request,
    )
    return {"ok": True, "mode": "state-only", "run": _instance_to_run_dto(inst), "instance": inst.to_dict()}


def _queue_workflow_decision_event(decision: dict) -> dict:
    """Queue an operator decision for the live Conductor daemon to resume."""
    event_id = f"evt_decision_{uuid.uuid4().hex[:10]}"
    envelope = {
        "id": event_id,
        "type": "workflow.decision",
        "source": "pantheon-content-dashboard",
        "target": None,
        "subject": "/workflows/decision",
        "context": {},
        "payload": decision,
        "is_external": False,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8088/dispatch",
        data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}
            return {"ok": True, "mode": "daemon-decision-event", "event": {"id": event_id, **data}}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "mode": "daemon-decision-event", "error": str(exc), "event": {"id": event_id}}


def _queue_workflow_event(*, workflow_id: str, context: dict, initiator: str, original_request: str) -> dict:
    """Queue an internal event for the live Conductor daemon to execute."""
    event_id = f"evt_content_{uuid.uuid4().hex[:10]}"
    envelope = {
        "id": event_id,
        "type": "webhook",
        "source": "pantheon-content-dashboard",
        "target": None,
        "subject": "/dispatch",
        "context": context,
        "payload": {
            "workflow_id": workflow_id,
            "summary": original_request,
            "initiator": initiator,
            "context": context,
        },
        "is_external": False,
    }
    req = urllib.request.Request(
        "http://127.0.0.1:8088/dispatch",
        data=json.dumps(envelope).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = {"raw": raw}
            return {
                "ok": True,
                "mode": "daemon-event",
                "event": {"id": event_id, **data},
                "message": "Queued for live Conductor execution",
            }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "mode": "daemon-event", "error": str(exc), "event": {"id": event_id}}


def _instance_to_run_dto(inst):
    d = inst.to_dict() if hasattr(inst, "to_dict") else dict(inst)
    return {
        "id": d.get("workflow_id", ""),
        "workflowId": d.get("definition_id", ""),
        "status": _map_run_status(d.get("status", "running")),
        "startedAt": d.get("created") or d.get("started_at"),
        "finishedAt": d.get("finished_at") or d.get("updated_at"),
        "message": d.get("original_request") or None,
        "blockers": None,
    }


def _record_workflow_decision(body: dict):
    """Record a Hub operator decision for a workflow run.

    This intentionally writes a durable state artifact even before the Conductor
    executor consumes decisions directly. The UI can now capture approvals,
    rewrite feedback, and selected angles without pretending the action vanished.
    """
    workflow_id = str(body.get("workflow_id") or body.get("workflowId") or "").strip()
    run_id = str(body.get("run_id") or body.get("runId") or "").strip()
    action = _slugify(str(body.get("action") or "decision"))[:60]
    if not workflow_id:
        raise ValueError("Missing workflow_id")
    if not run_id:
        raise ValueError("Missing run_id")

    include_sources = body.get("include_sources") if isinstance(body.get("include_sources"), bool) else None
    generate_image = body.get("generate_image") if isinstance(body.get("generate_image"), bool) else None
    selected_image_path = str(body.get("selected_image_path") or "").strip()[:1000]
    selected_image_url = str(body.get("selected_image_url") or "").strip()[:1000]
    selected_images = body.get("selected_images") if isinstance(body.get("selected_images"), dict) else None
    payload = {
        "id": f"decision_{uuid.uuid4().hex[:12]}",
        "workflow_id": workflow_id,
        "run_id": run_id,
        "action": action,
        "stage": str(body.get("stage") or "")[:120],
        "choice": str(body.get("choice") or "")[:1000],
        "feedback": str(body.get("feedback") or "")[:4000],
        "auto_approve": body.get("auto_approve") if isinstance(body.get("auto_approve"), dict) else {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "pantheon-hub-content-dashboard",
    }
    if include_sources is not None:
        payload["include_sources"] = include_sources
    if generate_image is not None:
        payload["generate_image"] = generate_image
    if selected_image_path:
        payload["selected_image_path"] = selected_image_path
    if selected_image_url:
        payload["selected_image_url"] = selected_image_url
    if selected_images is not None:
        payload["selected_images"] = {str(k)[:80]: str(v)[:1000] for k, v in selected_images.items() if v}
    decisions_dir = Path(CONDUCTOR_DECISIONS_DIR).expanduser()
    decisions_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_dir / f"{payload['created_at'].replace(':', '').replace('+', 'Z')}-{run_id}-{action}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    run_update = _apply_decision_to_run_state(payload)
    resume = _queue_workflow_decision_event(payload)
    return {"ok": True, "decision": payload, "path": str(path), "run_update": run_update, "resume": resume}


def _apply_decision_to_run_state(decision: dict) -> dict:
    """Mirror operator decision context without pretending to execute steps.

    The live Conductor daemon consumes the queued workflow.decision event and
    resumes the waiting workflow. This mirror is only for immediate dashboard
    visibility/audit; it must not advance current_step by itself.
    """
    run_id = decision.get("run_id")
    if not run_id:
        return {"applied": False, "reason": "missing run_id"}
    path = Path(CONDUCTOR_STATE_DIR).expanduser() / f"{run_id}.json"
    if not path.exists():
        return {"applied": False, "reason": "run state not found"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return {"applied": False, "reason": str(exc)}

    context = data.setdefault("context_bag", {})
    context.setdefault("operator_decisions", []).append(decision)
    if decision.get("feedback"):
        context["feedback"] = decision.get("feedback")
    action = decision.get("action")
    if action in {"kairos-pick", "select-angle"}:
        context["pending_selected_angle"] = decision.get("choice") or decision.get("feedback") or "Operator requested Kairos pick"
    elif action == "approve":
        context["pending_draft_choice"] = decision.get("choice") or "approved"
        if isinstance(decision.get("include_sources"), bool):
            context["include_sources"] = decision.get("include_sources")
        if isinstance(decision.get("generate_image"), bool):
            context["generate_image"] = decision.get("generate_image")
        if decision.get("selected_image_path"):
            context["selected_image_path"] = decision.get("selected_image_path")
        if decision.get("selected_image_url"):
            context["selected_image_url"] = decision.get("selected_image_url")
        if isinstance(decision.get("selected_images"), dict):
            context["selected_images"] = decision.get("selected_images")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    current = data.get("current_step")
    data.setdefault("step_history", []).append({
        "step_id": decision.get("stage") or current or "operator-decision",
        "god": "operator",
        "status": f"decision-queued:{action}",
        "started": now,
        "completed": now,
        "output_summary": (decision.get("feedback") or action or "operator decision")[:500],
    })
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return {"applied": True, "run_id": run_id, "current_step": data.get("current_step"), "status": data.get("status")}

def _create_pipeline_definition(body: dict):
    """Create a new wizard-authored Conductor workflow YAML file."""
    name = _clean_title(body.get("name") or "Untitled Pipeline")
    description = _clean_description(body.get("description") or body.get("goal") or "Operator-created pipeline.")
    owner = _clean_god(body.get("ownerGod") or body.get("owner_god") or "hermes")
    schedule = _clean_title(body.get("schedule") or "manual")[:80]
    first_prompt = _clean_description(body.get("firstPrompt") or body.get("first_prompt") or description)

    slug = _unique_workflow_slug(_slugify(name))
    workflow_doc = {
        "workflow": {
            "id": slug,
            "name": name,
            "version": "1.0.0",
            "description": f"{description}\n\nSchedule hint: {schedule}. Created from Olympus pipeline dashboard.",
            "context": {
                "required": [],
                "optional": ["topic", "surface", "operator_notes", "approval"],
            },
            "steps": [
                {
                    "id": "draft-output",
                    "god": owner,
                    "skill": "social-content-pipeline" if owner == "kairos" else None,
                    "action": "draft_pipeline_output",
                    "output": "draft_output",
                    "prompt": first_prompt,
                    "timeout": "180s",
                },
                {
                    "id": "operator-review",
                    "type": "nats_publish",
                    "subject": "subspace.konan.inbox",
                    "input_from": "draft-output",
                    "message": "${draft_output}\n\nReply with edits, approval, or stop.",
                },
            ],
        }
    }
    # Drop None fields so the YAML stays clean.
    for step in workflow_doc["workflow"]["steps"]:
        for key in [k for k, v in step.items() if v is None]:
            del step[key]

    workflows_dir = Path(CONDUCTOR_WORKFLOWS_DIR).expanduser()
    workflows_dir.mkdir(parents=True, exist_ok=True)
    path = workflows_dir / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(workflow_doc, sort_keys=False, allow_unicode=True), encoding="utf-8")

    # Validate by loading through the real registry before returning success.
    from conductor.v2.engine import WorkflowRegistry

    registry = WorkflowRegistry(workflows_dir=workflows_dir)
    wf = registry.get(slug)
    if not wf:
        try:
            path.unlink()
        except OSError:
            pass
        raise ValueError("Created pipeline did not validate as a Conductor workflow")
    return {"ok": True, "workflow": _workflow_to_dto(wf), "path": path.name}


# ══════════════════════════════════════════════════════════════════════════════
# Content cockpit: topic bank, scheduled queue, and in-app notifications
# ══════════════════════════════════════════════════════════════════════════════

def _get_topic_bank() -> dict[str, Any]:
    """Read the daily Kairos Topic Bank, creating a degraded seed if absent."""
    if CONTENT_TOPIC_BANK_FILE.exists():
        try:
            data = json.loads(CONTENT_TOPIC_BANK_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("topics", [])
                data.setdefault("counts", _topic_counts(data.get("topics") or []))
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return _fallback_topic_bank("topic bank file missing or unreadable")


def _refresh_topic_bank() -> dict[str, Any]:
    """Run the on-disk refresher so the app can trigger the midnight job manually."""
    if not CONTENT_TOPIC_REFRESH_SCRIPT.exists():
        raise ValueError(f"Topic refresh script missing: {CONTENT_TOPIC_REFRESH_SCRIPT}")
    proc = subprocess.run(
        [sys.executable, str(CONTENT_TOPIC_REFRESH_SCRIPT), "--output", str(CONTENT_TOPIC_BANK_FILE), "--json", "--timeout", "180"],
        cwd=str(PANTHEON_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=240,
        check=False,
    )
    result: dict[str, Any]
    try:
        result = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        result = {"stdout": proc.stdout[-1000:]}
    if proc.returncode != 0:
        raise RuntimeError(result.get("last30daysError") or proc.stderr[-1000:] or "topic refresh failed")
    bank = _get_topic_bank()
    return {"ok": True, "refresh": result, "topicBank": bank}


def _fallback_topic_bank(reason: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    topics = [
        ("business", "⭐ What broke in agent workflows this week", ["personal-linkedin", "business-linkedin"], True),
        ("business", "⭐ The MCP/tooling integration people are quietly standardizing around", ["personal-linkedin", "business-linkedin"], True),
        ("business", "Why mobile-first operator consoles beat desktop dashboards", ["personal-linkedin"], False),
        ("business", "⭐ A small-business workflow that should be a reusable system", ["business-facebook", "business-linkedin"], True),
        ("business", "A free tool/workflow operators can copy this week", ["business-linkedin", "business-facebook"], False),
        ("business", "The privacy/compliance thing normal businesses are underestimating", ["personal-linkedin", "business-linkedin"], False),
        ("business", "⭐ A useful open-source project worth turning into an operator workflow", ["personal-linkedin", "business-linkedin"], True),
        ("business", "The memory/governance problem behind multi-agent systems", ["personal-linkedin"], False),
        ("personal_interest", "A music habit or trend people are talking about now", ["personal-facebook"], False),
        ("personal_interest", "⭐ Retro handhelds are not as outside the tech economy as they feel", ["personal-facebook"], True),
        ("personal_interest", "The rabbit hole people are using to learn something weirdly useful", ["personal-facebook"], False),
        ("personal_interest", "The old story pattern showing up in current internet culture", ["personal-facebook"], False),
        ("personal_interest", "A local-life observation that feels human, not promotional", ["personal-facebook"], False),
        ("personal_interest", "A tiny everyday system that makes life less chaotic", ["personal-facebook"], False),
        ("personal_interest", "⭐ A privacy/security thing normal people should understand without jargon", ["personal-facebook", "personal-linkedin"], True),
        ("personal_interest", "The internet behavior shift that says something about people", ["personal-facebook"], False),
        ("hybrid", "⭐ A tool that is nerdy enough for builders but useful enough for Facebook", ["personal-facebook", "personal-linkedin"], True),
        ("hybrid", "The practical creativity lesson inside a current tool/trend", ["personal-facebook", "personal-linkedin"], False),
        ("hybrid", "One random thing worth learning and why it matters", ["personal-facebook", "personal-linkedin"], False),
        ("hybrid", "⭐ A personal operator lesson without turning into a pitch", ["personal-facebook", "personal-linkedin"], True),
    ]
    rows = []
    for lane, title, destinations, starred in topics:
        clean_title = title.replace("⭐", "").strip()
        rows.append({
            "id": _slugify(f"topic-{lane}-{clean_title}"),
            "title": clean_title,
            "angleSummary": "Refresh seed: run the daily last30days + Agent Reach job for live evidence before drafting.",
            "lane": lane,
            "source": "kairos" if starred else "fallback",
            "researchSources": ["last30days", "agent_reach"],
            "isKairosRecommended": starred,
            "whyNow": f"Fallback seed because {reason}. The midnight refresher replaces this with last30days-backed signal.",
            "audienceFit": "Facebook-friendly personal texture" if lane != "business" else "business/operator authority",
            "personalFit": lane in {"personal_interest", "hybrid"},
            "suggestedDestinations": destinations,
            "confidence": "degraded",
            "tags": [lane.replace("_", "-"), "last30days", "agent-reach"],
            "status": "unused",
            "createdAt": now,
            "refreshedAt": now,
            "agentReach": {"model": "agent_reach_local_fit_v1", "primary_destination": destinations[0], "surface_scores": {dest: 80 for dest in destinations}},
            "evidence": [{"source": "last30days", "summary": reason, "date": now}],
        })
    return {
        "ok": True,
        "version": "fallback",
        "updatedAt": now,
        "timezone": "America/Boise",
        "refreshCadence": "daily at midnight America/Boise",
        "researchContract": {
            "primarySkill": "last30days",
            "fitLayer": "agent_reach",
            "kairosStarRule": "⭐ means Kairos recommendation after signal + fit validation.",
        },
        "sourceStatus": {"ok": False, "error": reason},
        "topics": rows,
        "counts": _topic_counts(rows),
    }


def _topic_counts(topics: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(topics),
        "kairosRecommended": sum(1 for topic in topics if topic.get("isKairosRecommended")),
        "personalOrHybrid": sum(1 for topic in topics if topic.get("lane") in {"personal_interest", "hybrid"}),
        "business": sum(1 for topic in topics if topic.get("lane") == "business"),
    }


def _get_scheduled_queue(limit: int = 100) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for queue_type, root in CONTENT_QUEUE_ROOTS.items():
        for state_dir, status in (("pending", "scheduled"), ("running", "posting"), ("done", "posted"), ("failed", "failed")):
            directory = root / state_dir
            if not directory.is_dir():
                continue
            for path in sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
                item = _queue_file_to_item(path, queue_type, status)
                if item:
                    items.append(item)
    items.sort(key=lambda item: (item.get("scheduledAt") or "", item.get("createdAt") or ""), reverse=True)
    return {"items": items[:limit], "total": len(items), "roots": {key: str(value) for key, value in CONTENT_QUEUE_ROOTS.items()}}


def _queue_file_to_item(path: Path, queue_type: str, status: str) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    title = payload.get("title") or payload.get("surface") or payload.get("platform") or data.get("job_id") or path.stem
    text = payload.get("text") or payload.get("body") or ""
    image_path = None
    if isinstance(payload.get("blog_image"), dict):
        image_path = payload["blog_image"].get("image_path")
    if not image_path and isinstance(payload.get("social_image"), dict):
        image_path = payload["social_image"].get("image_path")
    media_paths = payload.get("media_paths") if isinstance(payload.get("media_paths"), list) else []
    return {
        "id": str(data.get("job_id") or payload.get("queue_item_id") or path.stem),
        "queueType": queue_type,
        "status": status if data.get("status") not in {"failed", "done"} else ("failed" if data.get("status") == "failed" else "posted"),
        "title": str(title)[:160],
        "destination": payload.get("destination") or payload.get("surface") or payload.get("platform") or queue_type,
        "scheduledAt": data.get("due_at") or payload.get("scheduled_for"),
        "createdAt": data.get("created_at"),
        "finishedAt": data.get("finished_at"),
        "workflowId": payload.get("workflow_id"),
        "draftPreview": str(text).strip()[:700],
        "imageStatus": "attached" if image_path or media_paths else ("requested" if payload.get("generate_image") else "none"),
        "imagePath": image_path or (media_paths[0] if media_paths else None),
        "queuePath": str(path),
        "resultStatus": result.get("status"),
        "resultOk": result.get("ok"),
    }


def _get_content_notifications() -> dict[str, Any]:
    notifications: list[dict[str, Any]] = []
    for run in _get_workflow_runs(limit=100).get("runs", []):
        if run.get("workflowId") not in {"social-content-pipeline", "blog-content-pipeline"}:
            continue
        if run.get("status") == "awaiting-approval" or str(run.get("currentStep") or "").startswith("operator-"):
            notifications.append({
                "id": f"approval:{run.get('id')}:{run.get('currentStep')}",
                "type": "approval_ready",
                "title": f"{run.get('workflowId', 'Content')} ready for approval",
                "body": str(run.get("message") or run.get("currentStep") or "Review needed")[:220],
                "severity": "action_required",
                "createdAt": run.get("finishedAt") or run.get("startedAt"),
                "target": {"surface": "approval_inbox", "runId": run.get("id")},
            })
    queue = _get_scheduled_queue(limit=80).get("items", [])
    for item in queue:
        if item.get("status") == "failed":
            notifications.append({
                "id": f"queue-failed:{item.get('id')}",
                "type": "scheduled_post_failed",
                "title": "Scheduled post failed",
                "body": f"{item.get('destination')} · {item.get('title')}",
                "severity": "warning",
                "createdAt": item.get("finishedAt") or item.get("scheduledAt"),
                "target": {"surface": "scheduled_queue", "queueItemId": item.get("id")},
            })
    bank = _get_topic_bank()
    counts = bank.get("counts") or _topic_counts(bank.get("topics") or [])
    notifications.append({
        "id": f"topic-bank:{bank.get('updatedAt')}",
        "type": "topic_bank_refreshed",
        "title": "Topic Bank refreshed",
        "body": f"{counts.get('total', 0)} active topics · {counts.get('kairosRecommended', 0)} starred Kairos picks · {counts.get('personalOrHybrid', 0)} Facebook-friendly personal/hybrid ideas.",
        "severity": "info",
        "createdAt": bank.get("updatedAt"),
        "target": {"surface": "topic_bank", "filter": "kairos_recommended"},
    })
    notifications.sort(key=lambda item: str(item.get("createdAt") or ""), reverse=True)
    return {"notifications": notifications[:50], "total": len(notifications)}


def _clean_title(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:120] or "Untitled Pipeline"


def _clean_description(value: object) -> str:
    text = str(value or "").replace("\r", "").strip()
    return text[:2000] or "Operator-created pipeline."


def _clean_god(value: object) -> str:
    god = re.sub(r"[^a-z0-9_-]", "", str(value or "").strip().lower())
    return god if god in _ALLOWED_GODS else "hermes"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:60] or f"pipeline-{uuid.uuid4().hex[:8]}"


def _unique_workflow_slug(base: str) -> str:
    workflows_dir = Path(CONDUCTOR_WORKFLOWS_DIR).expanduser()
    candidate = base
    i = 2
    while (workflows_dir / f"{candidate}.yaml").exists():
        candidate = f"{base}-{i}"
        i += 1
    return candidate

# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _first_line(text: str, max_len: int = 100) -> str:
    """Take the first meaningful line of text, capped to max_len."""
    if not text:
        return ""
    lines = text.strip().split("\n")
    line = lines[0].strip("# ").strip()
    if len(line) > max_len:
        line = line[: max_len - 1] + "…"
    return line


def _iso_or_none(val) -> str | None:
    """Convert a Unix timestamp (int) or ISO string to ISO. Returns None on failure."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
        except (OSError, ValueError):
            return None
    return str(val) if val else None


def _file_mtime_iso(path: str) -> str | None:
    """Return file modification time as ISO string."""
    try:
        ts = os.path.getmtime(path)
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _resolve_generated_image(raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser().resolve()
    if candidate.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
        raise ValueError("Unsupported image type")
    if not candidate.is_file():
        raise ValueError("Image artifact not found")
    allowed = False
    for root in GENERATED_IMAGE_ROOTS:
        try:
            candidate.relative_to(root.expanduser().resolve())
            allowed = True
            break
        except ValueError:
            continue
    if not allowed:
        raise ValueError("Image artifact is outside generated-image roots")
    return candidate


def _serve_workflow_image(handler, qs: dict):
    raw_path = (qs.get("path") or [""])[0]
    if not raw_path:
        return bad(handler, "Missing image path", status=400)
    try:
        image_path = _resolve_generated_image(raw_path)
    except ValueError as exc:
        return bad(handler, str(exc), status=404)
    mime = mimetypes.guess_type(str(image_path))[0] or "image/png"
    return t(handler, image_path.read_bytes(), content_type=mime)


# ══════════════════════════════════════════════════════════════════════════════
# Route handler — called from routes.py
# ══════════════════════════════════════════════════════════════════════════════

def handle_work(handler, parsed):
    path = parsed.path
    qs = parse_qs(parsed.query or "")

    if path == "/api/work/lanes":
        return j(handler, _get_lanes())

    if path == "/api/work/ideas":
        limit = min(int((qs.get("limit") or ["20"])[0]), 100)
        return j(handler, _get_ideas(limit=limit))

    if path == "/api/work/cron":
        return j(handler, _get_cron_jobs())

    if path == "/api/work/failures":
        limit = min(int((qs.get("limit") or ["10"])[0]), 100)
        return j(handler, _get_failures(limit=limit))

    if path == "/api/workflows":
        return j(handler, _get_workflows())

    if path == "/api/workflows/runs":
        limit = min(int((qs.get("limit") or ["50"])[0]), 200)
        return j(handler, _get_workflow_runs(limit=limit))

    if path == "/api/workflows/topic-bank":
        return j(handler, _get_topic_bank())

    if path == "/api/workflows/scheduled-queue":
        limit = min(int((qs.get("limit") or ["100"])[0]), 200)
        return j(handler, _get_scheduled_queue(limit=limit))

    if path == "/api/workflows/notifications":
        return j(handler, _get_content_notifications())

    if path == "/api/workflows/image":
        return _serve_workflow_image(handler, qs)

    return False


def handle_work_post(handler, parsed, body):
    path = parsed.path
    try:
        if path == "/api/workflows/start":
            return j(handler, _start_workflow(body if isinstance(body, dict) else {}))
        if path == "/api/workflows/pipelines":
            return j(handler, _create_pipeline_definition(body if isinstance(body, dict) else {}), status=201)
        if path == "/api/workflows/decision":
            return j(handler, _record_workflow_decision(body if isinstance(body, dict) else {}), status=201)
        if path == "/api/workflows/topic-bank/refresh":
            return j(handler, _refresh_topic_bank(), status=201)
    except ValueError as exc:
        return bad(handler, str(exc), status=400)
    except Exception as exc:
        return bad(handler, str(exc), status=500)
    return False
