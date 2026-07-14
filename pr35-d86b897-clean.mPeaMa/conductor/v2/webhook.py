"""Conductor v2 webhook receiver — FastAPI on port 8088.

Spec section 6 Layer 5. Thin HTTP server that accepts external webhooks
(GitHub, Stripe, Jira, YouTube, custom), converts each to an event
envelope, writes it to pending/_webhooks/ as a JSON file, and lets the
engine's file watcher pick it up like any other dispatch.

External events default to handling_mode=approval_required (spec 8.1) —
so the engine will quarantine them unless a rule explicitly matches.

Decoupling: FastAPI only, no hermes-agent imports.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse

from .engine import PENDING_DIR, Event, utc_now
from .auth import bearer_dependency, set_expected_api_key

LOG = logging.getLogger("conductor.v2.webhook")

DEFAULT_PORT = int(os.environ.get("CONDUCTOR_WEBHOOK_PORT", "8088"))
DEFAULT_HOST = os.environ.get("CONDUCTOR_WEBHOOK_HOST", "0.0.0.0")


def make_app(pending_dir: Path = PENDING_DIR, api_key: str = "") -> FastAPI:
    """Build the FastAPI app. Each app has its own pending_dir binding so
    tests can use a tmp directory.

    The `api_key` arg binds the bearer token expected on every
    protected endpoint. Passing "" disables auth (the dev/test
    footgun — the live_stream logs a warning in the same situation).
    The key is also bound to the module-level slot in auth.py so the
    shared `bearer_dependency()` factory can find it.

    Auth split per spec §6:
      * ``GET  /health``           — UNAUTHENTICATED (load balancers
        and the operator need to hit it without credentials).
      * ``POST /webhook/{source}`` — AUTHENTICATED (any external
        caller that can forge a webhook).
      * ``POST /dispatch``         — AUTHENTICATED (internal callers
        like Talon send their own token).
    """
    # Bind the expected key for the bearer_dependency() factory in
    # auth.py. Mirror the api_server fix: bind None for the empty
    # case so the resolver (CONDUCTOR_API_KEY env, then .env file
    # fallback) takes over. Otherwise an empty `api_key=""` would
    # leave a stale binding from a previous make_app() call in
    # place and silently enforce the wrong key (or no key, when
    # the prior binding was None).
    set_expected_api_key(api_key if api_key else None)

    inbox = pending_dir / "_webhooks"
    inbox.mkdir(parents=True, exist_ok=True)

    app = FastAPI(
        title="Conductor v2 Webhook Gateway",
        version="2.0.0",
        description="Receive external webhooks, convert to event envelopes, write to pending/_webhooks/.",
    )
    # Per-app dependency closure. Each route that needs auth uses
    # `Depends(auth_dep)` to enforce it.
    auth_dep = bearer_dependency()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "platform": "conductor-v2-webhook",
            "pending_inbox": str(inbox),
            "timestamp": utc_now(),
        }

    @app.post("/webhook/{source:path}", dependencies=[Depends(auth_dep)])
    async def receive_webhook(source: str, request: Request) -> JSONResponse:
        """Generic webhook catch-all. The {source} path segment names the
        origin (github, stripe, jira, etc.) and becomes the Event.source."""
        try:
            body_bytes = await request.body()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"could not read body: {e}")

        # Try to parse as JSON; fall back to raw text
        try:
            body = json.loads(body_bytes.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = {"_raw": body_bytes.decode("utf-8", errors="replace")}

        event = Event(
            type="webhook",
            source=source or "unknown",
            target=None,
            subject=str(request.url.path),
            payload=body if isinstance(body, dict) else {"value": body},
            is_external=True,
        )

        # Write to inbox — engine's file watcher will pick it up
        # OR the engine's event queue (if wired directly) will handle it now
        fname = f"{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:8]}.json"
        path = inbox / fname
        path.write_text(json.dumps({
            "id": f"webhook_{uuid.uuid4().hex[:8]}",
            "type": event.type,
            "source": event.source,
            "target": event.target,
            "subject": event.subject,
            "timestamp": event.timestamp,
            "context": {},
            "payload": event.payload,
            "is_external": True,
        }, indent=2, default=str))

        LOG.info(f"webhook received: source={event.source} path={request.url.path} → {path.name}")
        return JSONResponse({
            "status": "accepted",
            "queued_as": fname,
            "note": "external events default to approval_required (spec 8.1)",
        }, status_code=202)

    @app.post("/dispatch", dependencies=[Depends(auth_dep)])
    async def dispatch_direct(req: Request) -> JSONResponse:
        """Internal-style dispatch endpoint. Accepts a pre-formed event
        envelope (used by Talon or other internal Pantheons) and writes
        it to pending/inbox/ for the engine to process. NOT auto-approved
        unless a rule says so."""
        body = await req.json()
        if not isinstance(body, dict) or "type" not in body or "source" not in body:
            raise HTTPException(
                status_code=400,
                detail="event envelope requires 'type' and 'source' fields",
            )
        body.setdefault("id", f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}")
        body.setdefault("timestamp", utc_now())
        body.setdefault("context", {})
        body.setdefault("payload", {})
        # Mark external unless caller explicitly says internal
        body.setdefault("is_external", True)

        inbox_general = pending_dir / "inbox"
        inbox_general.mkdir(parents=True, exist_ok=True)
        path = inbox_general / f"{body['id']}.json"
        path.write_text(json.dumps(body, indent=2, default=str))
        LOG.info(f"dispatch received: type={body['type']} source={body['source']} → {path.name}")
        return JSONResponse({"status": "queued", "id": body["id"]}, status_code=202)

    return app


class WebhookServer:
    """Lifecycle wrapper around the FastAPI app. Run with `await server.start()`.

    Note: aiohttp/uvicorn import is deferred to start() so the module is
    importable even if uvicorn isn't installed in some edge envs.
    """

    def __init__(self, port: int = DEFAULT_PORT, host: str = DEFAULT_HOST,
                 pending_dir: Path = PENDING_DIR, api_key: str = ""):
        self.port = port
        self.host = host
        self.pending_dir = pending_dir
        # Bearer token expected on /webhook/{source} and /dispatch.
        # Empty string = auth disabled (dev/test mode). Production
        # passes the shared key from the ConductorService so all
        # three HTTP surfaces enforce the same auth.
        self.api_key = api_key
        self._server: Optional[Any] = None
        self._app: Optional[FastAPI] = None

    async def start(self) -> dict[str, Any]:
        import uvicorn
        self._app = make_app(self.pending_dir, api_key=self.api_key)
        config = uvicorn.Config(
            self._app, host=self.host, port=self.port,
            log_level="info", access_log=False, lifespan="on",
        )
        self._server = uvicorn.Server(config)
        # Run in background task — don't await forever
        asyncio.create_task(self._server.serve())
        # Wait briefly for startup
        for _ in range(20):
            await asyncio.sleep(0.1)
            if self._server.started:
                break
        LOG.info(f"webhook server listening on http://{self.host}:{self.port}")
        return {"status": "started", "host": self.host, "port": self.port, "inbox": str(self.pending_dir / "_webhooks")}

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

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    app = make_app()
    uvicorn.run(app, host=DEFAULT_HOST, port=port, log_level="info")
