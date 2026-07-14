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
  GET /api/workflows/runs    → all workflow run state
"""

from __future__ import annotations

import json
import os
import glob
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qs

from api.helpers import bad, j

# ── Paths ──────────────────────────────────────────────────────────────────
KANBAN_DB = os.path.expanduser("~/.hermes/kanban.db")
CRON_JOBS_FILE = os.path.expanduser("~/.hermes/cron/jobs.json")
CONDUCTOR_STATE_DIR = os.path.expanduser("~/pantheon/conductor/state")


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
        runs.append({
            "id": wf_id,
            "workflowId": d.get("definition_id", wf_id),
            "status": _map_run_status(d.get("status", "unknown")),
            "startedAt": d.get("started_at"),
            "finishedAt": d.get("finished_at") or d.get("updated_at"),
            "message": str(d.get("error") or d.get("message") or "")[:200] or None,
            "blockers": d.get("blockers") if isinstance(d.get("blockers"), list) else None,
        })

        if len(runs) >= limit:
            break

    return {"runs": runs}


def _map_run_status(s: str) -> str:
    """Normalise conductor status strings to frontend enum."""
    s_lower = s.lower() if s else ""
    if "abort" in s_lower:
        return "failed"
    if "complet" in s_lower or "done" in s_lower or "success" in s_lower:
        return "completed"
    if "run" in s_lower or "in_progress" in s_lower or "active" in s_lower:
        return "running"
    if "approv" in s_lower or "wait" in s_lower or "pending" in s_lower:
        return "awaiting-approval"
    return "running"


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

    if path == "/api/workflows/runs":
        limit = min(int((qs.get("limit") or ["50"])[0]), 200)
        return j(handler, _get_workflow_runs(limit=limit))

    return False
