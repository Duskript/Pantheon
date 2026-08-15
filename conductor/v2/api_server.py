"""Conductor v2 API server — Phase 4.0b: CRUD + validate/run/events + auth.

Implements the spec's §4.4 REST surface that the Synergy SDK adapter
talks to. Eight endpoints serve the SDK's persistence + execution
needs:

  Phase 4.0a (slim CRUD):
    GET    /api/workflows                  List workflow YAML files
    GET    /api/workflows/{id}             Read single workflow YAML
    PUT    /api/workflows/{id}             Write workflow YAML (atomic)
    DELETE /api/workflows/{id}             Delete workflow YAML

  Phase 4.0b (validate, run, history, SSE):
    POST   /api/workflows/{id}/validate    Run validate_workflow_file
    POST   /api/workflows/{id}/run         Trigger engine.start_workflow
    GET    /api/workflows/{id}/runs        List run history (state/*.json)
    GET    /api/workflows/{id}/runs/{run_id}/events   SSE live event stream

Plus the unauthenticated liveness probe:
    GET    /health                         Service status + wiring state

Design notes
------------
* **Atomic writes (PUT):** the body is written to a tmp file in the
  same directory, fsync'd, then ``os.replace``'d into place. Readers
  never see a half-written file even if the process dies mid-write.
* **Validate-first (PUT):** the validator runs against the tmp file
  BEFORE ``os.replace``. A bad workflow never touches the real path.
* **In-place reload (PUT):** after a successful write we call
  ``engine.workflows.reload_workflow(id)`` so the engine's in-memory
  registry picks up the change without a daemon restart. The spec's
  kill criterion: if this fails, the file is on disk but the registry
  is stale — we return a 200 with a warning field so the operator
  sees the inconsistency. (Hardening option: 500 with explicit
  remediation; the warning is the gentler path that keeps the editor
  functional.)
* **Path-traversal guard:** the ``{id}`` path parameter is validated
  against a strict regex (``[A-Za-z0-9][A-Za-z0-9_-]{0,127}``) before
  any filesystem access. The new ``runs`` and ``events`` endpoints
  rely on FastAPI's path-matching to reject slashes, and validate
  the ``run_id`` against the ``wf_<hex>`` pattern.
* **Lazy workflows dir:** the directory is resolved from
  ``CONDUCTOR_BASE_DIR`` / ``PANTHEON_ROOT`` env at request time (via
  ``engine._workflows_dir()``), so a single env override moves the
  whole daemon between prod and test layouts.
* **Auth (Phase 4.0b):** a single bearer token shared across api_server,
  webhook, and live_stream (spec §6). Resolved from ``api_key=`` ctor
  arg, then ``CONDUCTOR_API_KEY`` env, then empty (auth disabled).
  Enforced on every endpoint except ``/health``. The helper lives in
  ``auth.py`` so all three surfaces enforce the same logic.

Run with:
    python3 -m conductor.v2.api_server
or:
    uvicorn conductor.v2.api_server:app --host 127.0.0.1 --port 8770
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import bearer_dependency, resolve_api_key, set_expected_api_key
from .engine import (
    ConductorEngine,
    Workflow,
    WorkflowInstance,
    _state_dir,
    _workflows_dir,
    read_yaml,
    utc_now,
)
from .workflow_validator import (
    validate_workflow_file,
)

LOG = logging.getLogger("conductor.v2.api_server")

DEFAULT_HOST = os.environ.get("CONDUCTOR_API_HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("CONDUCTOR_API_PORT", "8770"))

# Workflow id validation: safe filename stem. No slashes (path traversal),
# no leading dot (hidden file), no special chars. 1-128 chars.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# Run id (workflow_id of an instance) shape: wf_<hex>. Matches the
# engine's start_workflow: f"wf_{uuid.uuid4().hex[:8]}". Used to
# reject obviously-bad inputs before the SSE path is wired.
_RUN_ID_PATTERN = re.compile(r"^wf_[a-z0-9]{1,32}$")


def _validate_id(workflow_id: str) -> None:
    """Raise 400 if ``workflow_id`` is not a safe filename stem."""
    if not _ID_PATTERN.match(workflow_id):
        raise HTTPException(
            status_code=400,
            detail=(
                f"invalid workflow id {workflow_id!r}: must match "
                f"{_ID_PATTERN.pattern}"
            ),
        )


def _validate_run_id(run_id: str) -> None:
    """Raise 400 if ``run_id`` is not a wf_<hex> pattern.

    Lenient on the hex length (1-32) so non-engine-minted ids (e.g.
    ad-hoc tests with ``wf_evt01``) still pass — the path match alone
    prevents slashes, and the live_stream subscription is keyed on the
    raw string. This guard only catches clearly malformed inputs.
    """
    if not _RUN_ID_PATTERN.match(run_id):
        raise HTTPException(
            status_code=400,
            detail=f"invalid run id {run_id!r}: must match {_RUN_ID_PATTERN.pattern}",
        )


def _atomic_write_yaml(path: Path, doc: dict[str, Any]) -> None:
    """Write ``doc`` as YAML to ``path`` atomically.

    Strategy: write to a sibling tmp file, fsync, then ``os.replace``
    the tmp into place. ``os.replace`` is atomic on POSIX — the file
    either exists with the new content or the old content, never a
    half-written mix. The tmp file's name includes the target path
    stem so concurrent PUTs to different ids don't collide; concurrent
    PUTs to the SAME id will race on ``os.replace`` and the last
    writer wins, which matches the editor's "last save wins" semantics.
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
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


def _workflow_summary(path: Path) -> Optional[dict[str, Any]]:
    """Read a YAML file and return a summary dict.

    Returns None if the file is empty / unparseable. Used by the LIST
    endpoint so a single bad workflow doesn't take down the whole list.

    The summary has id, name, version, step_count, description. Steps
    themselves are NOT included — the SDK fetches the full document
    via GET /api/workflows/{id} when the user opens a workflow.
    """
    try:
        doc = read_yaml(path)
    except Exception as e:
        LOG.warning(f"failed to load workflow summary {path}: {e}")
        return None
    if not isinstance(doc, dict):
        return None
    return {
        "id": doc.get("id") or path.stem,
        "name": doc.get("name") or path.stem,
        "version": doc.get("version") or "?",
        "description": doc.get("description", ""),
        "step_count": len(doc.get("steps") or []),
    }


def _load_runs_for_definition(
    state_dir: Path, definition_id: str
) -> list[WorkflowInstance]:
    """Load all run state files whose definition_id matches.

    Sorted by ``created`` descending (newest first). Errors on
    individual files (corrupt JSON, missing fields) are logged and
    skipped — one bad file shouldn't break the whole listing.
    """
    if not state_dir.exists():
        return []
    out: list[WorkflowInstance] = []
    for path in sorted(state_dir.glob("wf_*.json"), key=lambda p: p.stat().st_mtime):
        try:
            data = json.loads(path.read_text())
            if data.get("definition_id") != definition_id:
                continue
            out.append(WorkflowInstance.from_dict(data))
        except Exception as e:
            LOG.warning(f"failed to load run state {path}: {e}")
    out.sort(key=lambda i: i.created, reverse=True)
    return out


def _instance_to_dict(inst: WorkflowInstance) -> dict[str, Any]:
    """Serialize a WorkflowInstance to a JSON-friendly dict.

    Used by ``GET /api/workflows/{id}/runs`` to return run summaries
    to the SDK. ``step_history`` is included so the SDK can render a
    per-step timeline without a per-run fetch.
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
    """Build the Phase 4.0b FastAPI app.

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
        The ConductorEngine instance. When provided, the run and SSE
        endpoints use its in-memory workflow registry (so reload
        takes effect immediately) and its live_stream (so SSE events
        flow). When None, the api_server still works for list/read/
        validate but run/SSE return 503.
    api_key
        Bearer token expected on every protected route. Empty string
        (the default) does NOT disable auth — it falls through to
        env-var resolution (CONDUCTOR_API_KEY, then CONDUCTOR_WS_API_KEY).
        Pass an explicit non-empty string to override the env var; pass
        the literal sentinel value `""` only via the `disable_auth=True`
        shortcut (see below). The empty-string override used to
        force-disable auth even when CONDUCTOR_API_KEY was set in
        production — a security gap (Ponytail Tier-2 finding 2 on
        PR #35). The fix is to bind None for the empty case so
        `_expected_for_request()` falls through to `resolve_api_key()`
        which honors the env var.
    """
    # Bind the expected key. An explicit non-empty arg wins over the
    # env var (intentional — tests pass a known key, deployments
    # leave the arg empty and rely on CONDUCTOR_API_KEY). An empty
    # arg binds None so the env-var resolver takes over; this is
    # what protects production deploys with `uvicorn conductor.v2.api_server:app`
    # + CONDUCTOR_API_KEY set in ~/.hermes/.env from accidentally
    # running unauthenticated.
    set_expected_api_key(api_key if api_key else None)

    # Resolve the EFFECTIVE auth state once so /health can report it
    # honestly. The local `api_key` arg is misleading: when it's the
    # default `""` but CONDUCTOR_API_KEY is configured (env or .env),
    # the routes ARE enforcing auth — but the previous health
    # endpoint claimed "DISABLED". Resolve via the shared helper so
    # the report matches what the routes actually enforce.
    from .auth import resolve_api_key
    effective_api_key = resolve_api_key(api_key if api_key else None)

    wf_dir = workflows_dir if workflows_dir is not None else _workflows_dir()
    st_dir = state_dir if state_dir is not None else _state_dir()
    # Ensure both dirs exist so the first PUT/GET doesn't 500.
    wf_dir.mkdir(parents=True, exist_ok=True)
    st_dir.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Conductor v2 API Server",
        version="0.4.0b",
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

    # Resolve the effective API key once so the /health endpoint
    # reports the actual auth state after env-var and .env file
    # fallback — not just whether the make_app api_key argument
    # was explicitly set to a truthy value. Uses the same
    # resolution chain as _expected_for_request().
    _effective_key = resolve_api_key(api_key if api_key else None)

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
            "auth": "required" if _effective_key else "DISABLED",
            "timestamp": utc_now(),
        }

    # ----- GET /api/workflows -----

    @app.get("/api/workflows", dependencies=[Depends(auth_dep)])
    def list_workflows() -> JSONResponse:
        """List all workflow YAML files in the workflows dir.

        Each entry has id, name, version, step_count, and description
        — NOT the full step definitions (the editor fetches those via
        GET /api/workflows/{id} on demand). Bad YAML files are
        reported with ``name=<filename>, version='?', description=
        <load error: ...>`` so a single broken file doesn't blank the
        list.
        """
        items: list[dict[str, Any]] = []
        for path in sorted(wf_dir.glob("*.yaml")):
            # Skip tmp files left by interrupted atomic writes.
            if path.name.startswith("."):
                continue
            try:
                stat = path.stat()
            except OSError as e:
                LOG.warning(f"failed to stat {path}: {e}")
                continue
            summary = _workflow_summary(path)
            if summary is None:
                # Bad YAML — emit a sentinel entry so the user can
                # see there's a broken file.
                items.append({
                    "id": path.stem,
                    "name": path.stem,
                    "version": "?",
                    "description": f"<load error>",
                    "step_count": 0,
                    "size_bytes": stat.st_size,
                    "modified": stat.st_mtime,
                })
                continue
            items.append({
                **summary,
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
            })
        return JSONResponse({"workflows": items, "count": len(items)})

    # ----- GET /api/workflows/{id} -----

    @app.get("/api/workflows/{workflow_id}", dependencies=[Depends(auth_dep)])
    def read_workflow(workflow_id: str) -> JSONResponse:
        """Read a single workflow YAML as JSON.

        Returns 404 when the file doesn't exist. The body is the
        parsed workflow document so the editor can populate the canvas
        from a single request — ``id``, ``name``, ``steps`` etc. as
        they appear on disk.
        """
        _validate_id(workflow_id)
        path = wf_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise HTTPException(
                status_code=404, detail=f"workflow {workflow_id!r} not found"
            )
        try:
            doc = read_yaml(path)
        except Exception as e:
            LOG.warning(f"failed to parse {path}: {e}")
            raise HTTPException(
                status_code=500, detail=f"workflow YAML parse error: {e}"
            )
        # Flatten the document to the top level so the editor can
        # render the canvas from a single response — id, name,
        # steps[], etc. as they appear on disk. We also include
        # `id` and `filename` as a convenience so callers don't
        # need to track them separately.
        if isinstance(doc, dict):
            return JSONResponse(
                {**doc, "id": doc.get("id") or workflow_id, "filename": path.name}
            )
        # Non-dict YAML (rare — list/empty): wrap so the response
        # is always a JSON object.
        return JSONResponse(
            {"id": workflow_id, "filename": path.name, "workflow": doc}
        )

    # ----- PUT /api/workflows/{id} -----

    @app.put("/api/workflows/{workflow_id}", dependencies=[Depends(auth_dep)])
    async def write_workflow(workflow_id: str, request: Request) -> JSONResponse:
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

        Body shape: the workflow document as the SDK would send it.
        The ``id`` field in the body MUST match the path id — the
        file would otherwise be named differently from its contents.
        """
        _validate_id(workflow_id)
        content_type = (request.headers.get("content-type") or "").lower()

        if "yaml" in content_type and "json" not in content_type:
            raw = await request.body()
            try:
                doc = yaml.safe_load(raw)
            except yaml.YAMLError as e:
                raise HTTPException(
                    status_code=400, detail=f"invalid YAML: {e}"
                )
        else:
            try:
                doc = await request.json()
            except json.JSONDecodeError as e:
                raise HTTPException(
                    status_code=400, detail=f"invalid JSON body: {e}"
                )

        if not isinstance(doc, dict):
            raise HTTPException(
                status_code=400,
                detail=(
                    "workflow body must be a JSON object, got "
                    f"{type(doc).__name__}"
                ),
            )

        # Body id must match path id — otherwise the file would be
        # written under a misleading name. Strict 400.
        body_id = doc.get("id")
        if body_id != workflow_id:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"workflow id in body ({body_id!r}) does not match "
                    f"path id ({workflow_id!r})"
                ),
            )

        # Validate FIRST by writing to a tmp file, running the
        # validator on it, then either committing (os.replace) or
        # rejecting. A bad workflow never overwrites the good one on
        # disk — even if the validator itself crashes, the on-disk
        # file is untouched.
        target = wf_dir / f"{workflow_id}.yaml"
        fd, tmp_path_str = tempfile.mkstemp(
            prefix=f".{workflow_id}.",
            suffix=".tmp",
            dir=str(wf_dir),
        )
        try:
            with os.fdopen(fd, "w") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            # Validate the tmp file — returns violations list, may
            # raise if the YAML is unparseable.
            try:
                violations = validate_workflow_file(Path(tmp_path_str))
            except Exception as e:
                raise HTTPException(
                    status_code=500, detail=f"validator failed: {e}"
                )
            if violations:
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
            LOG.exception(f"failed to write {target}")
            raise HTTPException(
                status_code=500, detail=f"failed to write workflow: {e}"
            )

        # Tell the engine to pick up the change. The spec's kill
        # criterion: if this fails, the file is on disk but the
        # in-memory registry is stale. We log + return a warning
        # rather than 500, so the editor still gets a "success"
        # response (the file IS on disk; only the cache is stale).
        if engine is not None:
            try:
                engine.workflows.reload_workflow(workflow_id)
            except Exception as e:
                LOG.error(
                    f"engine reload failed after PUT {workflow_id}: {e} — "
                    f"file is on disk but the in-memory registry is stale"
                )
                return JSONResponse({
                    "id": workflow_id,
                    "filename": target.name,
                    "status": "written",
                    "size_bytes": target.stat().st_size,
                    "warning": (
                        f"file written but engine reload failed: {e} — "
                        f"the engine will pick up the change on the next "
                        f"start"
                    ),
                })

        return JSONResponse({
            "id": workflow_id,
            "filename": target.name,
            "status": "written",
            "size_bytes": target.stat().st_size,
        })

    # ----- DELETE /api/workflows/{id} -----

    @app.delete("/api/workflows/{workflow_id}", dependencies=[Depends(auth_dep)])
    def delete_workflow(workflow_id: str) -> JSONResponse:
        """Delete a workflow YAML file.

        Refuses to delete anything starting with ``bridge-`` (per
        spec §4.4) — those are bridge-test fixtures, not real
        workflows, and removing them would break the v1+v2 routing
        test suite.

        Returns 404 if the file doesn't exist. The engine's
        in-memory copy is purged so the next ``start_workflow`` for
        this id returns "unknown workflow".
        """
        _validate_id(workflow_id)
        if workflow_id.startswith("bridge-"):
            raise HTTPException(
                status_code=403,
                detail="refusing to delete bridge-* workflow (reserved for tests)",
            )
        path = wf_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise HTTPException(
                status_code=404, detail=f"workflow {workflow_id!r} not found"
            )
        try:
            path.unlink()
        except OSError as e:
            LOG.exception(f"failed to delete {path}")
            raise HTTPException(
                status_code=500, detail=f"failed to delete workflow: {e}"
            )
        # Purge from the in-memory registry so a stale read doesn't
        # hand the editor a copy of the deleted workflow.
        if engine is not None and workflow_id in engine.workflows._workflows:
            del engine.workflows._workflows[workflow_id]
            LOG.info(f"purged {workflow_id} from engine registry")
        return JSONResponse({"id": workflow_id, "status": "deleted"})

    # ----- POST /api/workflows/{id}/validate -----

    @app.post(
        "/api/workflows/{workflow_id}/validate",
        dependencies=[Depends(auth_dep)],
    )
    def validate_workflow_endpoint(workflow_id: str) -> JSONResponse:
        """Run ``validate_workflow_file`` on the on-disk YAML.

        Returns ``{"valid": true, "violations": []}`` on success, or
        ``{"valid": false, "violations": [...]}`` on failure. The HTTP
        status is always 200 — the response body's ``valid`` field
        tells the client whether the workflow passed. (Using 400 for
        validation failures would conflate "your request was bad" with
        "the workflow is bad"; they're different things.)

        The file is loaded fresh from disk on every call, so this
        endpoint reports on the CURRENT state of the file, not
        what's in the engine's registry.
        """
        _validate_id(workflow_id)
        path = wf_dir / f"{workflow_id}.yaml"
        if not path.exists():
            raise HTTPException(
                status_code=404, detail=f"workflow {workflow_id!r} not found"
            )
        try:
            violations = validate_workflow_file(path)
        except Exception as e:
            # A load error (e.g. invalid YAML) is reported as a
            # violation, not a 500 — the file exists, the operator
            # just gave it bad content.
            return JSONResponse({
                "valid": False,
                "violations": [f"failed to load: {e}"],
                "workflow_id": workflow_id,
            })
        return JSONResponse({
            "valid": not violations,
            "violations": violations,
            "workflow_id": workflow_id,
        })

    # ----- POST /api/workflows/{id}/run -----

    @app.post(
        "/api/workflows/{workflow_id}/run",
        dependencies=[Depends(auth_dep)],
    )
    async def run_workflow(
        workflow_id: str, request: Request
    ) -> JSONResponse:
        """Trigger a workflow run via the engine's ``start_workflow``.

        Accepts an optional JSON body with ``context`` (key/value bag
        passed to the workflow), ``initiator`` (defaults to
        ``"synergy-ui"``), and ``original_request`` (free-form). Empty
        body is OK — a run with no context is valid.

        Requires the engine to be wired. Returns 503 when the
        api_server was constructed without an engine (e.g. a
        read-only deployment that only serves workflow YAML).

        The actual execution is scheduled on the engine's event loop
        as a background task — the response returns the minted
        ``workflow_id`` (e.g. ``wf_abc12345``) so the caller can
        subscribe to ``/api/workflows/{id}/runs/{run_id}/events``
        for live progress.
        """
        _validate_id(workflow_id)
        if engine is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "api_server constructed without an engine — "
                    "run endpoint unavailable"
                ),
            )

        # Body is optional — empty body is fine.
        body: dict[str, Any] = {}
        if request.headers.get("content-length"):
            try:
                body = await request.json()
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                raise HTTPException(
                    status_code=400, detail=f"invalid JSON body: {e}"
                )
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
            raise HTTPException(
                status_code=500, detail=f"start_workflow failed: {e}"
            )

        return JSONResponse({
            "status": "started",
            "workflow_id": inst.workflow_id,
            "definition_id": inst.definition_id,
            "definition_version": inst.definition_version,
            "current_step": inst.current_step,
            "created": inst.created,
        })

    # ----- GET /api/workflows/{id}/runs -----

    @app.get(
        "/api/workflows/{workflow_id}/runs",
        dependencies=[Depends(auth_dep)],
    )
    def list_runs(workflow_id: str) -> JSONResponse:
        """List all runs for a given workflow definition.

        Reads ``state/wf_*.json`` and returns the ones whose
        ``definition_id`` matches the path. Newest runs first. The
        full step_history is included so the SDK can render a
        timeline without a per-run fetch.
        """
        _validate_id(workflow_id)
        runs = _load_runs_for_definition(st_dir, workflow_id)
        return JSONResponse({
            "workflow_id": workflow_id,
            "runs": [_instance_to_dict(r) for r in runs],
            "count": len(runs),
        })

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
        ``id`` and ``event`` SSE fields are set to the run_id and
        event type respectively so a browser's ``EventSource`` can
        re-attach on disconnect using ``Last-Event-ID``.

        The relay unsubscribes when the client disconnects (the
        generator is closed by Starlette), so listener queues
        don't leak.
        """
        # Gate SSE on `live_stream is not None` only — NOT on
        # `is_running`. The WebSocket bind is independent of the
        # queue mechanism: SSE consumers subscribe via
        # `subscribe_workflow()` which uses an in-memory queue, not
        # the aiohttp WebSocket server. Tests mark the live_stream
        # "started" without binding a port (so they don't have to
        # fight a bind() race); production always goes through
        # service.py which starts live_stream before api_server.
        _validate_id(workflow_id)
        _validate_run_id(run_id)
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
                        payload = await asyncio.wait_for(
                            queue.get(), timeout=1.0
                        )
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
        _effective = resolve_api_key(self.api_key if self.api_key else None)
        LOG.info(
            f"api server listening on http://{self.host}:{self.port} "
            f"(auth: {'required' if _effective else 'DISABLED'})"
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


# Default app for `python -m conductor.v2.api_server` and `uvicorn ...`
# NOTE: the default app has no engine wired — the run/SSE endpoints
# will return 503. Production deployments go through service.py which
# constructs APIServer(engine=self.engine) so the engine and live_stream
# are wired in.
app = make_app()


def main() -> None:
    """Run the API server under uvicorn."""
    import uvicorn

    uvicorn.run(app, host=DEFAULT_HOST, port=DEFAULT_PORT)


if __name__ == "__main__":
    main()
