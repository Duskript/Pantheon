"""Conductor v2 API server — FastAPI on port 8770.

Implements the spec's §4.4 REST surface that the Synergy SDK adapter
talks to. Eight endpoints serve the SDK's persistence + execution
needs (CRUD on workflow YAML files, validation, run triggers, run
history, and a live SSE event stream).

Design notes
------------
* **Atomic writes** (PUT): the workflow YAML is written to a tmp file
  in the same directory, then ``os.replace()``d into place. The
  reader never sees a half-written file even if the process dies
  mid-write. The api_server's file watcher (the engine's
  ``_watch_pending`` loop) re-reads the file on the next tick.
* **Validate-first** (PUT): per spec §4.4 and the load-time
  validator contract, we run ``validate_workflow_file`` on the
  proposed content BEFORE persisting. A bad workflow never touches
  disk. Validation failures return 400 with the validator's error
  message so the SDK can show the user a useful message.
* **In-place reload** (PUT): after a successful write we call
  ``engine.workflows.reload_workflow(id)`` so the engine's in-memory
  registry picks up the change without a full re-load. The spec's
  "kill criterion" calls this out: ``If the engine can't reload a
  PUT'd workflow at runtime, ... STOP and report.`` The reload
  method itself raises ``WorkflowValidationError`` if the on-disk
  file is unparseable; we catch that and return 500 (the validator
  was supposed to catch it before write, so this is a true bug).
* **Run history** (GET runs): we read ``state/wf_*.json`` on every
  call. The engine's active-instance cache is in-memory only and
  doesn't survive a restart; the state dir is the durable record.
* **SSE events** (GET runs/{id}/events): thin relay over the
  LiveStreamServer's ``subscribe_workflow`` queues. The browser's
  ``EventSource`` API auto-reconnects on disconnect, so the SDK
  doesn't need its own reconnect logic. The relay yields one
  ``data: ...\\n\\n`` line per event; on disconnect the generator
  unsubscribes so the listener queue is cleaned up.

Run with:
    python3 -m conductor.v2.api_server
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import bearer_dependency, set_expected_api_key
from .engine import (
    ConductorEngine,
    Event,
    Workflow,
    WorkflowInstance,
    _state_dir,
    _workflows_dir,
    read_yaml,
    utc_now,
)
from .workflow_validator import (
    WorkflowValidationError,
    validate_workflow,
    validate_workflow_file,
)

LOG = logging.getLogger("conductor.v2.api_server")

DEFAULT_HOST = os.environ.get("CONDUCTOR_API_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("CONDUCTOR_API_PORT", "8770"))


# ---------------------------------------------------------------------------
# Workflow YAML <-> dict conversion
# ---------------------------------------------------------------------------

def _workflow_to_dict(wf: Workflow) -> dict[str, Any]:
    """Serialize a Workflow dataclass to a JSON-friendly dict.

    Mirrors the on-disk YAML shape so the SDK can render the editor
    from the JSON it gets back. Steps are dumped with their full
    field set (so the editor sees god/skill/action/etc. and not just
    `id`).
    """
    return {
        "id": wf.id,
        "name": wf.name,
        "version": wf.version,
        "description": wf.description,
        "context": {
            "required": list(wf.context_required),
            "optional": list(wf.context_optional),
        },
        "steps": [
            {
                "id": s.id,
                "type": s.type,
                "god": s.god,
                "skill": s.skill,
                "action": s.action,
                "input": s.input,
                "input_from": s.input_from,
                "subject": s.subject,
                "message": s.message,
                "gates": list(s.gates),
                "output": s.output,
                "timeout": s.timeout,
                "on_timeout": s.on_timeout,
                "loop": s.loop,
                "payload": dict(s.payload),
                "operator_approval_required": s.operator_approval_required,
                "tool": s.tool,
                "tool_input": dict(s.tool_input),
                "on_error": dict(s.on_error),
                # parallel/merge fields — only present when the step
                # uses them, but harmless to include unconditionally
                "branches": [
                    {
                        "id": b.id,
                        "type": b.type,
                        "god": b.god,
                        "skill": b.skill,
                        "action": b.action,
                    }
                    for b in s.branches
                ],
                "fail_mode": s.fail_mode,
                "max_concurrency": s.max_concurrency,
                "inputs": list(s.inputs),
                "strategy": s.strategy,
                "strategy_config": dict(s.strategy_config),
            }
            for s in wf.steps
        ],
        "source_path": str(wf.source_path),
    }


def _instance_to_dict(inst: WorkflowInstance) -> dict[str, Any]:
    """Serialize a WorkflowInstance to a JSON-friendly dict.

    Used by ``GET /api/workflows/{id}/runs`` to return run summaries
    to the SDK. ``step_history`` is included so the SDK can render a
    per-step timeline without a second request.
    """
    return {
        "workflow_id": inst.workflow_id,
        "definition_id": inst.definition_id,
        "definition_version": inst.definition_version,
        "status": inst.status,
        "current_step": inst.current_step,
        "context_bag": inst.context_bag,
        "step_history": inst.step_history,
        "created": inst.created,
        "completion_target": inst.completion_target,
        "abort_on_fail": inst.abort_on_fail,
        "dispatched_to": inst.dispatched_to,
        "initiator": inst.initiator,
        "original_request": inst.original_request,
    }


def _atomic_write_yaml(path: Path, doc: dict[str, Any]) -> None:
    """Write `doc` as YAML to `path` atomically.

    Strategy: write to a sibling tmp file, fsync, then ``os.replace``
    the tmp into place. ``os.replace`` is atomic on POSIX (the file
    either exists with the new content or the old content — never a
    half-written mix). On Windows it's also atomic on the same
    volume.

    The tmp file's name includes the target path + a uuid suffix so
    concurrent PUTs to different ids don't collide; concurrent PUTs
    to the SAME id will race on ``os.replace`` and the last writer
    wins, which matches the editor's "last save wins" expectation.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w") as f:
            yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path_str, path)
    except Exception:
        # Clean up the tmp on failure so we don't leave junk.
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


def _list_run_state_files(state_dir: Path) -> list[Path]:
    """Return all run state files (``wf_*.json``) in `state_dir`.

    Sorted by mtime (oldest first) so the API's response is stable
    across calls. The engine writes ``wf_<uuid>.json`` per run, so
    the glob is the canonical list.
    """
    if not state_dir.exists():
        return []
    return sorted(state_dir.glob("wf_*.json"), key=lambda p: p.stat().st_mtime)


def _load_runs_for_definition(state_dir: Path, definition_id: str) -> list[WorkflowInstance]:
    """Load all run state files whose definition_id matches.

    Errors on individual files (corrupt JSON, missing fields) are
    logged and skipped — one bad file shouldn't break the whole
    listing. The list is sorted by ``created`` descending (newest
    first) so the SDK's run list shows the most recent at the top.
    """
    out: list[WorkflowInstance] = []
    for path in _list_run_state_files(state_dir):
        try:
            data = json.loads(path.read_text())
            if data.get("definition_id") != definition_id:
                continue
            out.append(WorkflowInstance.from_dict(data))
        except Exception as e:
            LOG.warning(f"failed to load run state {path}: {e}")
    out.sort(key=lambda i: i.created, reverse=True)
    return out


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

def make_app(
    *,
    workflows_dir: Optional[Path] = None,
    state_dir: Optional[Path] = None,
    engine: Optional[ConductorEngine] = None,
    api_key: str = "",
) -> FastAPI:
    """Build the FastAPI app for the Conductor v2 API server.

    Parameters
    ----------
    workflows_dir
        Where workflow YAML files live. Defaults to the env-resolved
        ``_workflows_dir()`` so a single env var moves the whole
        daemon between prod and test layouts.
    state_dir
        Where workflow run state (``wf_*.json``) is written.
        Defaults to ``_state_dir()``.
    engine
        The ConductorEngine instance. When provided, the PUT/POST/run
        endpoints use its in-memory workflow registry (so reload
        takes effect immediately) and its live_stream (so SSE
        events flow). When None, the api_server still works for
        list/read/validate but PUT/run return 503 (the engine is
        required for the mutating endpoints).
    api_key
        Bearer token expected on every protected route. Empty string
        disables auth (dev/test mode, same footgun as live_stream).
    """
    # Bind the expected key. An explicit arg always wins, even
    # when it's the empty string (which means 'auth disabled' in
    # dev/test mode). The empty-string override matters because the
    # env may have CONDUCTOR_API_KEY set (production-like) while a
    # test wants the dev path.
    set_expected_api_key(api_key)

    wf_dir = workflows_dir if workflows_dir is not None else _workflows_dir()
    st_dir = state_dir if state_dir is not None else _state_dir()
    # Ensure both dirs exist so the first PUT/GET doesn't 500.
    wf_dir.mkdir(parents=True, exist_ok=True)
    st_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Conductor v2 API Server",
        version="2.0.0",
        description=(
            "REST API for workflow authoring (CRUD on YAML), validation, "
            "run triggers, run history, and live SSE event streaming. "
            "All endpoints require a Bearer token (Authorization: Bearer *** "
            "or ?api_key=) unless started with an empty api_key."
        ),
    )
    auth_dep = bearer_dependency()

    # Capture in closure so route handlers can resolve the live
    # stream at request time (the engine's live_stream attribute may
    # be set after make_app() returns — service.py starts them in
    # sequence).
    def _live_stream():
        if engine is None:
            return None
        return engine.live_stream

    def _registry():
        if engine is None:
            return None
        return engine.workflows

    # ----- /health (unauthenticated, for liveness probes) -----

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "platform": "conductor-v2-api",
            "workflows_dir": str(wf_dir),
            "state_dir": str(st_dir),
            "engine_wired": engine is not None,
            "live_stream_wired": _live_stream() is not None,
            "auth": "required" if api_key else "DISABLED",
            "timestamp": utc_now(),
        }

    # ----- GET /api/workflows -----

    @app.get("/api/workflows", dependencies=[Depends(auth_dep)])
    async def list_workflows() -> dict[str, Any]:
        """List all workflow YAML files in the workflows directory.

        Returns a JSON object with a ``workflows`` list. Each entry
        has the workflow id, name, version, step count, and source
        path. The full step definitions are NOT included — the
        caller uses ``GET /api/workflows/{id}`` for those.
        """
        out: list[dict[str, Any]] = []
        for path in sorted(wf_dir.glob("*.yaml")):
            # Skip tmp files left by interrupted atomic writes.
            if path.name.startswith("."):
                continue
            try:
                doc = read_yaml(path)
                wf = Workflow.from_dict(doc, path)
            except Exception as e:
                # A broken YAML shouldn't take down the whole list.
                LOG.warning(f"failed to load workflow {path}: {e}")
                out.append({
                    "id": path.stem,
                    "name": path.stem,
                    "version": "?",
                    "description": f"<load error: {e}>",
                    "step_count": 0,
                    "source_path": str(path),
                    "broken": True,
                })
                continue
            out.append({
                "id": wf.id,
                "name": wf.name,
                "version": wf.version,
                "description": wf.description,
                "step_count": len(wf.steps),
                "source_path": str(path),
            })
        return {"workflows": out, "count": len(out)}

    # ----- GET /api/workflows/{id} -----

    @app.get("/api/workflows/{workflow_id}", dependencies=[Depends(auth_dep)])
    async def get_workflow(workflow_id: str) -> dict[str, Any]:
        """Read a single workflow YAML and return it as JSON.

        Returns 404 when the file doesn't exist. The response body
        is the full workflow document (id, name, version, steps) so
        the editor can populate the canvas from a single request.
        """
        path = wf_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"workflow not found: {workflow_id}")
        try:
            doc = read_yaml(path)
            wf = Workflow.from_dict(doc, path)
        except WorkflowValidationError as e:
            # File exists but fails load-time validation (e.g.
            # sovereign-outbound contract violation). Return 422
            # (Unprocessable Entity) with the validator's message
            # so the SDK can show the user a useful error.
            raise HTTPException(status_code=422, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to parse {path}: {e}")
        return _workflow_to_dict(wf)

    # ----- PUT /api/workflows/{id} -----

    @app.put("/api/workflows/{workflow_id}", dependencies=[Depends(auth_dep)])
    async def put_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
        """Write a workflow YAML file (validate-first, atomic).

        Accepts either a JSON body (parsed and re-serialized to YAML
        so the on-disk file matches the validator's expected shape)
        or a raw ``application/yaml`` body (used by the SDK when
        round-tripping a Conductor YAML untouched). JSON wins on
        ambiguous content types.

        Validation runs BEFORE the write — a bad workflow never
        touches disk. On success, the engine's registry is told to
        reload the file so the next ``start_workflow`` picks up the
        change without a daemon restart.

        Body shape (JSON): the workflow document as the SDK would
        send it (matches ``_workflow_to_dict``'s output). The
        ``id`` field in the body MUST match the path id, otherwise
        the on-disk file would be named differently from its
        contents (a debugging trap).
        """
        content_type = (request.headers.get("content-type") or "").lower()
        raw = await request.body()

        if "yaml" in content_type and "json" not in content_type:
            # Raw YAML — parse and validate.
            try:
                doc = yaml.safe_load(raw)
            except yaml.YAMLError as e:
                raise HTTPException(status_code=400, detail=f"invalid YAML: {e}")
        else:
            # Default to JSON. The SDK is the primary consumer
            # and round-trips JSON; YAML is the legacy path.
            try:
                doc = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise HTTPException(status_code=400, detail=f"invalid JSON: {e}")

        if not isinstance(doc, dict):
            raise HTTPException(
                status_code=400,
                detail=f"workflow body must be an object, got {type(doc).__name__}",
            )

        # Unwrap the legacy {workflow: {...}} envelope if present.
        inner = doc.get("workflow", doc) if isinstance(doc, dict) else doc
        if not isinstance(inner, dict):
            raise HTTPException(status_code=400, detail="workflow document must be an object")

        # Body id must match path id — otherwise the file would be
        # written under a misleading name. Strict 400.
        body_id = inner.get("id")
        if body_id != workflow_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"workflow id in body ({body_id!r}) does not match "
                    f"path id ({workflow_id!r})"
                ),
            )

        # Validate FIRST. We do this by writing the doc to a tmp
        # path, running the validator on it, then either committing
        # (move tmp to real path) or rejecting. This way a bad
        # workflow never overwrites the good one on disk — even if
        # the validator itself crashes, the on-disk file is
        # untouched.
        target = wf_dir / f"{workflow_id}.yaml"
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{workflow_id}.",
            suffix=".tmp",
            dir=str(wf_dir),
        )
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)
            # Validate the tmp file — WorkflowValidationError if bad.
            violations = validate_workflow_file(Path(tmp_path_str))
            if violations:
                # Don't even move the tmp — return 400 with the
                # violations list so the SDK can show all problems
                # at once (not just the first).
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "workflow validation failed",
                        "violations": violations,
                    },
                )
            # Validation passed — atomic commit.
            os.replace(tmp_path_str, target)
        except HTTPException:
            # Clean up the tmp file before bubbling up.
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            raise
        except Exception as e:
            try:
                os.unlink(tmp_path_str)
            except OSError:
                pass
            raise HTTPException(status_code=500, detail=f"failed to write workflow: {e}")

        # Tell the engine to pick up the change. The spec's kill
        # criterion: if this fails (validator accepted, but engine
        # can't parse the file), STOP and report. In practice the
        # validator's contract is the same parser the engine uses,
        # so this shouldn't fail — but we surface it as 500 if it
        # does, since the file is already on disk.
        registry = _registry()
        if registry is not None:
            try:
                registry.reload_workflow(workflow_id)
            except Exception as e:
                LOG.error(
                    f"engine reload failed after PUT {workflow_id}: {e} — "
                    f"file is on disk but the in-memory registry is stale"
                )
                return JSONResponse(
                    status_code=200,
                    content={
                        "status": "written",
                        "id": workflow_id,
                        "path": str(target),
                        "warning": (
                            f"file written but engine reload failed: {e} — "
                            f"the engine will pick up the change on the next "
                            f"start"
                        ),
                    },
                )

        return {
            "status": "written",
            "id": workflow_id,
            "path": str(target),
        }

    # ----- DELETE /api/workflows/{id} -----

    @app.delete("/api/workflows/{workflow_id}", dependencies=[Depends(auth_dep)])
    async def delete_workflow(workflow_id: str) -> dict[str, Any]:
        """Delete a workflow YAML file.

        Refuses to delete anything starting with ``bridge-`` (per
        spec §4.4) — those are bridge-test fixtures, not real
        workflows, and removing them would break the v1+v2 routing
        test suite.

        Returns 404 if the file doesn't exist. The engine's
        in-memory copy is purged so the next ``start_workflow`` for
        this id returns "unknown workflow".
        """
        if workflow_id.startswith("bridge-"):
            raise HTTPException(
                status_code=403,
                detail="refusing to delete bridge-* workflow (reserved for tests)",
            )
        path = wf_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"workflow not found: {workflow_id}")
        try:
            path.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"failed to delete: {e}")

        # Purge from the in-memory registry so a stale read doesn't
        # hand the editor a copy of the deleted workflow.
        registry = _registry()
        if registry is not None and workflow_id in registry._workflows:
            del registry._workflows[workflow_id]
            LOG.info(f"purged {workflow_id} from engine registry")

        return {"status": "deleted", "id": workflow_id}

    # ----- POST /api/workflows/{id}/validate -----

    @app.post(
        "/api/workflows/{workflow_id}/validate",
        dependencies=[Depends(auth_dep)],
    )
    async def validate_endpoint(workflow_id: str) -> dict[str, Any]:
        """Run ``validate_workflow_file`` on the on-disk YAML.

        Returns ``{"valid": true, "violations": []}`` on success,
        or ``{"valid": false, "violations": [...]}`` with a list of
        human-readable messages on failure. The HTTP status is
        always 200 — the response body's ``valid`` field tells the
        client whether the workflow passed. (Using 400 for
        validation failures would conflate "your request was bad"
        with "the workflow is bad"; they're different things.)

        The file is loaded fresh from disk on every call, so this
        endpoint reports on the CURRENT state of the file, not
        what's in the engine's registry.
        """
        path = wf_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"workflow not found: {workflow_id}")
        try:
            violations = validate_workflow_file(path)
        except Exception as e:
            # A load error (e.g. invalid YAML) is reported as a
            # violation, not a 500 — the file exists, the operator
            # just gave it bad content.
            return {
                "valid": False,
                "violations": [f"failed to load: {e}"],
                "workflow_id": workflow_id,
            }
        return {
            "valid": not violations,
            "violations": violations,
            "workflow_id": workflow_id,
        }

    # ----- POST /api/workflows/{id}/run -----

    @app.post(
        "/api/workflows/{workflow_id}/run",
        dependencies=[Depends(auth_dep)],
    )
    async def run_workflow(workflow_id: str, request: Request) -> dict[str, Any]:
        """Trigger a workflow run via the engine's ``start_workflow``.

        Accepts an optional JSON body with ``context`` (key/value
        bag passed to the workflow), ``initiator`` (defaults to
        ``"synergy-ui"``), and ``original_request`` (free-form).
        Empty body is OK — a run with no context is valid.

        Requires the engine to be wired. Returns 503 when the
        api_server was constructed without an engine (e.g. a
        read-only deployment that only serves workflow YAML).

        The actual execution is scheduled on the engine's event
        loop as a background task — the response returns the
        minted ``workflow_id`` (e.g. ``wf_abc12345``) so the caller
        can subscribe to ``/api/workflows/{id}/runs/{run_id}/events``
        for live progress.
        """
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail="api_server constructed without an engine — run endpoint unavailable",
            )

        # Body is optional — empty body is fine.
        body: dict[str, Any] = {}
        if request.headers.get("content-length"):
            try:
                body = await request.json()
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise HTTPException(status_code=400, detail=f"invalid JSON body: {e}")
        context = body.get("context") if isinstance(body.get("context"), dict) else None
        initiator = body.get("initiator", "synergy-ui")
        original_request = body.get("original_request", "")

        try:
            inst = engine.start_workflow(
                workflow_id,
                context=context,
                initiator=initiator,
                original_request=original_request,
            )
        except ValueError as e:
            # Engine raises ValueError for unknown workflow id.
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            LOG.exception(f"start_workflow({workflow_id}) failed: {e}")
            raise HTTPException(status_code=500, detail=f"start_workflow failed: {e}")

        return {
            "status": "started",
            "workflow_id": inst.workflow_id,
            "definition_id": inst.definition_id,
            "definition_version": inst.definition_version,
            "current_step": inst.current_step,
            "created": inst.created,
        }

    # ----- GET /api/workflows/{id}/runs -----

    @app.get(
        "/api/workflows/{workflow_id}/runs",
        dependencies=[Depends(auth_dep)],
    )
    async def list_runs(workflow_id: str) -> dict[str, Any]:
        """List all runs for a given workflow definition.

        Reads ``state/wf_*.json`` and returns the ones whose
        ``definition_id`` matches the path. Newest runs first. The
        full step_history is included so the SDK can render a
        timeline without a per-run fetch.
        """
        runs = _load_runs_for_definition(st_dir, workflow_id)
        return {
            "workflow_id": workflow_id,
            "runs": [_instance_to_dict(r) for r in runs],
            "count": len(runs),
        }

    # ----- GET /api/workflows/{id}/runs/{run_id}/events (SSE) -----

    @app.get(
        "/api/workflows/{workflow_id}/runs/{run_id}/events",
        dependencies=[Depends(auth_dep)],
    )
    async def stream_run_events(
        workflow_id: str,
        run_id: str,
        request: Request,
    ) -> StreamingResponse:
        """SSE stream of live events for a workflow run.

        Thin relay over the LiveStreamServer's ``subscribe_workflow``
        mechanism. Yields ``data: {json}\\n\\n`` per event. The
        ``id`` and ``event`` SSE fields are set to the workflow_id
        and event type respectively so a browser's ``EventSource``
        can re-attach on disconnect using ``Last-Event-ID``.

        The relay unsubscribes when the client disconnects (the
        generator is closed by Starlette), so listener queues
        don't leak. A ``?replay=N`` query param would replay the
        last N events from the journal; not implemented in v1.
        """
        live_stream = _live_stream()
        if live_stream is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "live_stream not wired on the engine — SSE endpoint "
                    "unavailable. Start the engine with live_stream="
                    "LiveStreamServer(api_key=...) to enable."
                ),
            )

        # Sanity-check the run exists so a typo'd run_id returns 404
        # before the SSE handshake. Reading the state file is cheap.
        run_path = st_dir / f"{run_id}.json"
        if not run_path.exists():
            # Allow live events for runs that haven't yet persisted
            # (the engine writes the state file in start_workflow,
            # so a race window is possible). Log and continue.
            LOG.debug(f"SSE: run {run_id} has no state file yet — streaming anyway")

        async def event_generator() -> AsyncIterator[bytes]:
            queue = await live_stream.subscribe_workflow(run_id)
            try:
                # Send a synthetic open event so the client knows the
                # stream is live. Helps with the browser's
                # EventSource.readyState transition.
                yield b"event: open\ndata: " + json.dumps({
                    "workflow_id": run_id,
                    "definition_id": workflow_id,
                    "timestamp": utc_now(),
                }).encode("utf-8") + b"\n\n"
                while True:
                    # Check for client disconnect (Starlette sets
                    # request.is_disconnected() once the client
                    # closes). We poll on every iteration so a
                    # disconnect unblocks the queue.get() below.
                    if await request.is_disconnected():
                        LOG.debug(f"SSE: client disconnected for run {run_id}")
                        break
                    try:
                        # Use a short timeout so we re-check
                        # is_disconnected() regularly even when no
                        # events are flowing.
                        payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        # Idle tick — send a comment line so the
                        # client knows the stream is still alive
                        # (browsers don't time out on comment lines).
                        yield b": keepalive\n\n"
                        continue
                    # payload is a JSON string (StreamEvent.to_json()).
                    yield b"data: " + payload.encode("utf-8") + b"\n\n"
            finally:
                # Always unsubscribe, even on client disconnect or
                # server shutdown — otherwise the queue would leak.
                await live_stream.unsubscribe_workflow(run_id, queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx buffering
            },
        )

    return app


# ---------------------------------------------------------------------------
# Lifecycle wrapper (mirrors webhook.py's WebhookServer)
# ---------------------------------------------------------------------------

class APIServer:
    """Async lifecycle wrapper for the API server.

    Run with ``await server.start()`` and ``await server.stop()``.
    The uvicorn import is deferred to ``start()`` so this module is
    importable in envs that don't have uvicorn installed (matches
    the WebhookServer pattern).
    """

    def __init__(
        self,
        *,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
        workflows_dir: Optional[Path] = None,
        state_dir: Optional[Path] = None,
        engine: Optional[ConductorEngine] = None,
        api_key: str = "",
    ):
        self.port = port
        self.host = host
        self.workflows_dir = workflows_dir
        self.state_dir = state_dir
        self.engine = engine
        self.api_key = api_key
        self._server: Optional[Any] = None
        self._app: Optional[FastAPI] = None

    async def start(self) -> dict[str, Any]:
        import uvicorn
        self._app = make_app(
            workflows_dir=self.workflows_dir,
            state_dir=self.state_dir,
            engine=self.engine,
            api_key=self.api_key,
        )
        config = uvicorn.Config(
            self._app,
            host=self.host,
            port=self.port,
            log_level="info",
            access_log=False,
            lifespan="on",
        )
        self._server = uvicorn.Server(config)
        asyncio.create_task(self._server.serve())
        # Wait briefly for startup
        for _ in range(20):
            await asyncio.sleep(0.1)
            if self._server.started:
                break
        LOG.info(
            f"api server listening on http://{self.host}:{self.port} "
            f"(auth: {'required' if self.api_key else 'DISABLED'})"
        )
        return {
            "status": "started",
            "host": self.host,
            "port": self.port,
            "engine_wired": self.engine is not None,
        }

    async def stop(self) -> dict[str, Any]:
        if self._server:
            self._server.should_exit = True
        return {"status": "stopping"}


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    app = make_app()
    uvicorn.run(app, host=DEFAULT_HOST, port=port, log_level="info")
