#!/usr/bin/env python3
"""Pitfall #26 — Abort stuck Conductor workflows.

Background
==========
The engine fix mid-flight at 2026-06-16 13:55Z left ~20 workflows
in stuck state. The state file was written but the dispatch file
in pending/<god>/ was NOT — the daemon never saw the work.

**Why dispatch-file re-fire doesn't work (lesson learned):**
The dispatch file model is for **inter-step handoffs** between gods
in an already-running workflow. The daemon's `watch_pending` awatch
loop synthesizes a `handoff.completed` event when it sees a new
file in `pending/<god>/` and routes it through the rule engine.
But the rule engine has no rule matching `from_god=conductor →
to_god=thoth` — the morning-briefing workflow is only started by
the `schedule.cron` event from the cron scheduler. Writing
`pending/<god>/<wf>_<step>.json` for a stuck workflow causes the
daemon to fire 14 events that all get dropped with:
  `WARNING conductor.v2.engine: unmatched internal event
   handoff.completed/conductor — dropping`

The right fix is to abort the stuck workflows and let the next cron
tick (or manual `bridge.Conductor.start_workflow`) re-fire them.

What this script does
=====================
Dynamically scans `conductor/state/wf_*.json` for stuck workflows
(`status in {in_progress, waiting_for_ack}` + `current_step is set`
+ dispatched_to=None OR status=waiting_for_ack) and writes
`conductor/state/<wf>.aborted.json` manifests for each.

The state file itself is also updated to `status="aborted"` so
future scans don't re-flag the same workflow.

Usage
=====
    python3 /home/konan/pantheon/conductor/scripts/refire-stuck-workflows.py --dry-run
    python3 /home/konan/pantheon/conductor/scripts/refire-stuck-workflows.py --execute
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

CONDUCTOR_ROOT = Path("/home/konan/pantheon/conductor")
STATE_DIR = CONDUCTOR_ROOT / "state"
PENDING_DIR = CONDUCTOR_ROOT / "pending"
WORKFLOWS_DIR = CONDUCTOR_ROOT / "workflows"

STUCK_STATUSES = {"in_progress", "waiting_for_ack"}


def _load_workflow(def_id: str) -> dict | None:
    p = WORKFLOWS_DIR / f"{def_id}.yaml"
    if not p.exists():
        return None
    try:
        return yaml.safe_load(p.read_text())["workflow"]
    except Exception as e:
        print(f"  WARN: could not load {p}: {e}", file=sys.stderr)
        return None


def _find_stuck_workflows() -> list[tuple[str, dict, dict, dict]]:
    """Scan state/ for stuck workflows. Returns list of
    (wf_id, state, workflow_def, step_def)."""
    stuck = []
    cutoff_mtime = time.time() - (7 * 24 * 3600)
    for p in sorted(STATE_DIR.glob("wf_*.json")):
        if ".aborted" in p.stem:
            continue
        # Skip test artifacts (>7 days old OR name starts with wf_test_/wf_thothq)
        if p.stat().st_mtime < cutoff_mtime:
            continue
        if p.stem.startswith("wf_test_") or p.stem.startswith("wf_thothq"):
            continue
        try:
            state = json.loads(p.read_text())
        except Exception:
            continue
        status = state.get("status")
        cur_step = state.get("current_step")
        is_stuck = (
            status in STUCK_STATUSES
            and cur_step is not None
            and (
                state.get("dispatched_to") in (None, "None", "?")
                or status == "waiting_for_ack"
            )
        )
        if not is_stuck:
            continue
        def_id = state.get("definition_id")
        wf = _load_workflow(def_id) if def_id else None
        if not wf:
            continue
        step_def = next((s for s in wf.get("steps", []) if s["id"] == cur_step), None)
        if not step_def:
            continue
        stuck.append((p.stem, state, wf, step_def))
    return stuck


def _abort_stuck(wf_id: str, reason: str, *, dry_run: bool) -> tuple[bool, str]:
    state_path = STATE_DIR / f"{wf_id}.json"
    if not state_path.exists():
        return False, "state file missing"
    state = json.loads(state_path.read_text())
    aborted_path = STATE_DIR / f"{wf_id}.aborted.json"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if aborted_path.exists():
        return False, f"already aborted at {aborted_path}"

    manifest = {
        "workflow_id": wf_id,
        "definition_id": state.get("definition_id", "?"),
        "status": "aborted",
        "failed_step": state.get("current_step", "?"),
        "failure_reason": reason,
        "aborted_at": now_iso,
        "aborted_by": "refire-stuck-workflows.py (pitfall #26 fix)",
        "requires_manual_review": True,
        "note": (
            "Engine fix mid-flight at 2026-06-16 13:55Z left this workflow "
            "in a stuck state. The dispatch file in pending/<god>/ was never "
            "written, so the daemon never saw the work. Manual review required."
        ),
    }
    if dry_run:
        return True, f"DRY-RUN: would write {aborted_path}"

    # Write the manifest.
    aborted_path.write_text(json.dumps(manifest, indent=2))

    # Update the state file so the dynamic scan no longer flags it.
    state["status"] = "aborted"
    state["aborted_by"] = "refire-stuck-workflows.py (pitfall #26 fix)"
    state["aborted_at"] = now_iso
    state_path.write_text(json.dumps(state, indent=2))

    return True, f"WROTE {aborted_path} + state status=aborted"


def main() -> int:
    parser = argparse.ArgumentParser(description="Pitfall #26 stuck-workflow abort")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Print actions without writing files (default)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually write the .aborted.json manifests")
    args = parser.parse_args()
    dry_run = not args.execute

    print("=" * 60)
    if dry_run:
        print("DRY-RUN. Pass --execute to actually write files.")
    else:
        print("EXECUTING (--execute). Will write files to:")
        print(f"  {STATE_DIR}/<wf>.aborted.json  (abort manifest)")
        print(f"  {STATE_DIR}/<wf>.json  (status update)")
    print("=" * 60)

    stuck = _find_stuck_workflows()
    if not stuck:
        print("\nNo stuck workflows found. Exiting.")
        return 0

    abort_count = 0
    print(f"\nFound {len(stuck)} stuck workflow(s):\n")

    for wf_id, state, wf_def, step_def in stuck:
        def_id = state.get("definition_id", "?")
        cur_step = state.get("current_step", "?")
        step_type = step_def.get("type", "god")
        step_god = step_def.get("god", "-")
        status = state.get("status", "?")
        dispatched_to = state.get("dispatched_to", "?")
        reason = (
            f"stuck at {cur_step} (step type={step_type}, god={step_god}, "
            f"status={status}, dispatched_to={dispatched_to}; engine fix "
            f"mid-flight at 2026-06-16 13:55Z broke the dispatch file write)"
        )
        ok, msg = _abort_stuck(wf_id, reason, dry_run=dry_run)
        abort_count += 1
        print(f"  {wf_id:14s} def={def_id:50s} step={cur_step:25s} type={step_type:14s} god={step_god:8s} status={status:18s} dispatched={str(dispatched_to):6s} -> ABORT: {msg}")

    print()
    print("=" * 60)
    print(f"Total: {abort_count} aborted, {len(stuck)} total")
    if dry_run:
        print("DRY-RUN complete. Pass --execute to actually write files.")
    else:
        print("EXECUTE complete. Restart the conductor daemon if needed.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
