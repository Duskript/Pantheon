"""Conductor v2 service — single-process daemon entry point.

Wires together:
    - engine  (rule eval + DAG execution + file watcher)
    - gateway (HTTP client to Hermes api_server)
    - nats    (Subspace/Talon listener)
    - webhook (FastAPI receiver on 8088)
    - delivery (Telegram/Subspace/inbox router)

This is the file systemd runs. Spec section 6: "single process with
optional feature flags". Here we run all of them by default since the
daemon is meant to be the canonical Conductor.

Usage:
    python3 -m conductor.v2.service              # start daemon
    python3 -m conductor.v2.service --check      # validate config and exit
    python3 -m conductor.v2.service --no-nats    # run without NATS listener
    python3 -m conductor.v2.service --no-webhook # run without webhook HTTP
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, Optional

from .engine import (
    ConductorEngine, RuleEngine, WorkflowRegistry, Event,
    _pending_dir, _state_dir, _rules_dir, _workflows_dir,
)
from .gateway import GatewayClient, GatewayConfig
from .nats import NATSListener
from .webhook import WebhookServer, DEFAULT_PORT as DEFAULT_WEBHOOK_PORT
from .delivery import DeliveryRouter
from .cron_scheduler import CronScheduler


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s: %(message)s",
    )
    # Quiet down noisy libraries
    for noisy in ("httpx", "httpcore", "asyncio", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


LOG = logging.getLogger("conductor.v2.service")


class ConductorService:
    """The daemon. Owns the engine, gateway client, listeners, and
    background tasks. Wires them together so events flow:

        webhook/nats/file-watcher
                ↓ (Event)
        engine.handle_event()
                ↓ (rule match + dispatch)
        gateway.submit_run()  →  god run_id
                ↓ (wait_for_run)
        engine._execute_step()  →  next step or done
                ↓
        delivery.deliver_step_completion()  →  Telegram/inbox/Subspace
    """

    def __init__(
        self,
        *,
        enable_nats: bool = True,
        enable_webhook: bool = True,
        webhook_port: int = DEFAULT_WEBHOOK_PORT,
        log_level: str = "INFO",
        cron_tick_interval: Optional[float] = None,
        rules: Optional["RuleEngine"] = None,
        workflows: Optional["WorkflowRegistry"] = None,
    ):
        """
        Construct the ConductorService daemon.

        Parameters
        ----------
        enable_nats, enable_webhook
            Toggle the optional background listeners. Production runs
            both; tests usually disable both to avoid needing the real
            services.
        webhook_port
            Port the webhook HTTP server binds to (only used when
            `enable_webhook=True`).
        log_level
            Python logging level for the daemon. Defaults to INFO.
        cron_tick_interval
            Override the CronScheduler tick interval. None = use the
            default (30s, matches the spec). Tests pass 0.5-1.0s to
            avoid waiting half a minute per assertion.
        rules, workflows
            **Phase 2 PM-fix:** optional pre-built RuleEngine /
            WorkflowRegistry instances. When provided, the service uses
            them directly instead of constructing fresh ones from the
            env-resolved CONDUCTOR_BASE_DIR. Production callers leave
            both as None (unchanged behavior). Tests use this to
            inject tmpdir-scoped registries and bypass the conftest's
            env-guard race entirely — see test_cron_e2e.py for the
            canonical usage pattern.
        """
        setup_logging(log_level)
        self.enable_nats = enable_nats
        self.enable_webhook = enable_webhook
        self.webhook_port = webhook_port
        # cron_tick_interval=None -> use the CronScheduler default (30s).
        # Tests pass 1.0 (or 0.1 for ultra-fast) to avoid waiting half a
        # minute per assertion.
        self.cron_tick_interval = cron_tick_interval

        # Phase 2 PM-fix: accept pre-built RuleEngine / WorkflowRegistry
        # via the new `rules` / `workflows` kwargs so tests can inject
        # tmpdir-scoped instances and bypass the env-resolver + conftest
        # env-guard race entirely. Production callers leave both as None
        # and get the env-resolved defaults (same as the original
        # behavior — fully backward-compatible).
        self.rules = rules if rules is not None else RuleEngine()
        self.workflows = workflows if workflows is not None else WorkflowRegistry()
        LOG.info(f"loaded {len(self.rules._rules)} rules, {len(self.workflows._workflows)} workflows")

        # Gateway client (created in start())
        self.gw: Optional[GatewayClient] = None
        self.engine: Optional[ConductorEngine] = None
        self.nats: Optional[NATSListener] = None
        self.webhook: Optional[WebhookServer] = None
        self.delivery: Optional[DeliveryRouter] = None
        self.cron: Optional[CronScheduler] = None
        self._tasks: list[asyncio.Task] = []
        self._stop_event: Optional[asyncio.Event] = None

    async def start(self) -> dict[str, Any]:
        """Start the full daemon. Returns status dict."""
        self._stop_event = asyncio.Event()
        results: dict[str, Any] = {}

        # Gateway client
        self.gw = GatewayClient()
        await self.gw.__aenter__()
        try:
            health = await self.gw.health()
            results["gateway"] = {"status": "connected", "health": health}
        except Exception as e:
            LOG.error(f"gateway health check failed: {e}")
            results["gateway"] = {"status": "unreachable", "error": str(e)}

        # Engine
        self.engine = ConductorEngine(
            gateway_client=self.gw,
            rules=self.rules,
            workflows=self.workflows,
            pending_dir=_pending_dir(),
            state_dir=_state_dir(),
        )
        active = self.engine.list_active()
        results["engine"] = {
            "status": "ready",
            "active_workflows": len(active),
            "pending_inboxes": [p.name for p in _pending_dir().iterdir() if p.is_dir()],
        }
        LOG.info(f"engine ready, {len(active)} active workflow(s)")

        # File watcher task
        self._tasks.append(asyncio.create_task(
            self.engine.watch_pending(self._stop_event),
            name="conductor.file-watcher",
        ))

        # Cron scheduler task — Phase 2 REWORK #1, Step 2.1.
        # Emits schedule.cron events on cron timers; the engine picks
        # them up via handle_event() the same way it does webhook /
        # NATS / handoff events. Shares the same _stop_event so the
        # scheduler dies with the rest of the daemon.
        scheduler_kwargs: dict = {}
        if self.cron_tick_interval is not None:
            scheduler_kwargs["tick_interval"] = self.cron_tick_interval
        self.cron = CronScheduler(
            engine=self.engine,
            rules=self.rules,
            stop_event=self._stop_event,
            **scheduler_kwargs,
        )
        # CronScheduler.start() names the task "conductor.cron-scheduler"
        # itself, so we don't need a separate set_name() here.
        self._tasks.append(self.cron.start())

        # Delivery router
        self.delivery = DeliveryRouter()
        await self.delivery.__aenter__()

        # NATS listener (optional)
        if self.enable_nats:
            self.nats = NATSListener(on_message=self._on_nats_event)
            nats_status = await self.nats.start()
            results["nats"] = nats_status
        else:
            results["nats"] = {"status": "disabled"}

        # Webhook HTTP server (optional)
        if self.enable_webhook:
            self.webhook = WebhookServer(port=self.webhook_port, pending_dir=_pending_dir())
            wh_status = await self.webhook.start()
            results["webhook"] = wh_status
        else:
            results["webhook"] = {"status": "disabled"}

        return results

    async def stop(self) -> None:
        """Graceful shutdown."""
        LOG.info("conductor v2 shutting down…")
        if self._stop_event:
            self._stop_event.set()
        if self.webhook:
            await self.webhook.stop()
        if self.nats:
            await self.nats.stop()
        # Wait for tasks
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        # The cron scheduler tracks its own task internally and has
        # an explicit stop() — call it now so its in-flight
        # handle_event() coroutines finish before we tear down the
        # gateway / delivery.
        if self.cron:
            await self.cron.stop()
        if self.delivery:
            await self.delivery.__aexit__(None, None, None)
        if self.gw:
            await self.gw.__aexit__(None, None, None)
        LOG.info("conductor v2 stopped")

    async def _on_nats_event(self, event: Event) -> None:
        """Bridge from NATS listener into the engine."""
        if not self.engine:
            return
        result = await self.engine.handle_event(event)
        # If quarantined, deliver an alert
        if result.get("status") == "quarantined" and self.delivery:
            try:
                await self.delivery.deliver_quarantine_alert(
                    event=event,
                    rule_id=result.get("rule", "?"),
                    quarantine_path=result.get("quarantine_file", ""),
                )
            except Exception as e:
                LOG.error(f"quarantine alert delivery failed: {e}")

    async def run_forever(self) -> None:
        """Block until SIGINT/SIGTERM."""
        loop = asyncio.get_running_loop()
        stop_signal = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_signal.set)
        await stop_signal.wait()
        await self.stop()

    # ----- Status helpers -----

    def status(self) -> dict[str, Any]:
        return {
            "engine": "ready" if self.engine else "not started",
            "gateway": "connected" if self.gw and self.gw._client else "not started",
            "nats": "connected" if self.nats and self.nats.is_connected else ("disabled" if not self.enable_nats else "not connected"),
            "webhook": f"http://0.0.0.0:{self.webhook_port}" if self.enable_webhook else "disabled",
            "rules_loaded": len(self.rules._rules),
            "workflows_loaded": len(self.workflows._workflows),
            "active_workflows": len(self.engine.list_active()) if self.engine else 0,
            "tasks_running": sum(1 for t in self._tasks if not t.done()),
            "cron": (
                "running"
                if self.cron and self.cron._task and not self.cron._task.done()
                else "stopped"
            ),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

async def _check_only() -> int:
    """Validate config + show what would start, then exit."""
    setup_logging("INFO")
    LOG.info("=== Conductor v2 configuration check ===")
    LOG.info(f"pending_dir:  {_pending_dir()}")
    LOG.info(f"state_dir:    {_state_dir()}")
    LOG.info(f"rules_dir:    {_rules_dir()}")
    LOG.info(f"workflows_dir:{_workflows_dir()}")
    rules = RuleEngine()
    workflows = WorkflowRegistry()
    LOG.info(f"rules loaded:    {len(rules._rules)}")
    LOG.info(f"workflows loaded: {len(workflows._workflows)}")
    for w in workflows.all():
        LOG.info(f"  - {w.id} v{w.version} ({len(w.steps)} steps)")
    cfg = GatewayConfig()
    LOG.info(f"gateway:    {cfg.base_url} key=...{cfg.api_key[-6:] if cfg.api_key else '(none)'}")
    # Test gateway reachability
    async with GatewayClient(cfg) as gw:
        try:
            h = await gw.health()
            LOG.info(f"gateway health: {h['status']}")
        except Exception as e:
            LOG.error(f"gateway unreachable: {e}")
            return 2
    LOG.info("=== all checks passed ===")
    return 0


async def _run(args: argparse.Namespace) -> int:
    svc = ConductorService(
        enable_nats=not args.no_nats,
        enable_webhook=not args.no_webhook,
        webhook_port=args.webhook_port,
        log_level=args.log_level,
    )
    startup = await svc.start()
    LOG.info(f"startup: {startup}")
    try:
        await svc.run_forever()
    finally:
        await svc.stop()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="conductor-v2",
        description="Conductor v2 — Pantheon workflow and reaction engine daemon",
    )
    parser.add_argument("--check", action="store_true", help="Validate config and exit")
    parser.add_argument("--no-nats", action="store_true", help="Disable NATS listener")
    parser.add_argument("--no-webhook", action="store_true", help="Disable webhook HTTP server")
    parser.add_argument("--webhook-port", type=int, default=DEFAULT_WEBHOOK_PORT, help=f"Webhook port (default {DEFAULT_WEBHOOK_PORT})")
    parser.add_argument("--log-level", default="INFO", help="Log level (DEBUG/INFO/WARNING/ERROR)")
    args = parser.parse_args(argv)

    if args.check:
        return asyncio.run(_check_only())
    return asyncio.run(_run(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
