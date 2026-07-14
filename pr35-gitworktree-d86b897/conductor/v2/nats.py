"""Conductor v2 NATS listener — single Subspace/Talon subscription.

Spec section 6 Layer 4. Subscribes to NATS subjects for cross-Pantheon
messages from Tallon's instance and routes them through the engine's
event handler.

Subjects (per spec 5 + Subspace convention):
    subspace.pantheon.incoming.>          (inbound from any Pantheon)
    subspace.pantheon.workflow.>          (workflow lifecycle events)
    subspace.broadcast                    (broadcast to all Pantheons)
    subspace.tallon.outgoing.>            (specific Tallon messages)

External events default to handling_mode=approval_required (spec 8.1)
so unknown sources get quarantined, not auto-executed.

Decoupling: only uses the `nats` Python client (already a hermes-agent
dependency). No imports from hermes-agent itself.

Resilience: if NATS is unreachable, the listener logs a warning and
returns a clean error — does not crash the daemon. Engine + webhook
keep working independently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

LOG = logging.getLogger("conductor.v2.nats")

DEFAULT_URL = os.environ.get("NATS_URL", "nats://100.100.46.52:4222")
DEFAULT_TOKEN_PATH = Path(os.environ.get("NATS_TOKEN_PATH", Path.home() / ".hermes" / "clawforge-tokens.env"))
DEFAULT_SUBJECT_PREFIX = os.environ.get("NATS_SUBJECT_PREFIX", "subspace.pantheon")
DEFAULT_SUBSCRIBE_SUBJECTS = [
    f"{DEFAULT_SUBJECT_PREFIX}.incoming.>",
    f"{DEFAULT_SUBJECT_PREFIX}.workflow.>",
    "subspace.broadcast",
    "subspace.tallon.outgoing.>",
]


def _load_token(path: Path = DEFAULT_TOKEN_PATH) -> str:
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("NATS_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class NATSListener:
    """Single subscription to Subspace subjects. Forwards every message
    to the engine's handle_event() coroutine.

    Construction does NOT connect — call await listener.start() from an
    async context. Failure to connect logs a warning and returns False
    but does not raise (daemon must keep running even if NATS is down).
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        token: str = "",
        token_path: Path = DEFAULT_TOKEN_PATH,
        subject_prefix: str = DEFAULT_SUBJECT_PREFIX,
        subscribe_subjects: Optional[list[str]] = None,
        on_message: Optional[Any] = None,  # async callable: (Event) -> None
    ):
        self.url = url
        self.token = token or _load_token(token_path)
        self.subject_prefix = subject_prefix
        self.subscribe_subjects = subscribe_subjects or DEFAULT_SUBSCRIBE_SUBJECTS
        self.on_message = on_message
        self._nc: Optional[Any] = None
        self._subs: list[Any] = []
        self._running = False

    @property
    def is_connected(self) -> bool:
        return self._nc is not None and self._nc.is_connected

    async def start(self) -> dict[str, Any]:
        """Connect + subscribe. Returns status dict. Never raises on
        connection failure — daemon continues without NATS."""
        try:
            import nats  # noqa: F401
        except ImportError:
            LOG.warning("nats-py not installed — NATS listener disabled")
            return {"status": "disabled", "reason": "nats-py not installed"}

        try:
            import nats
            kwargs = {"connect_timeout": 3}
            if self.token:
                kwargs["token"] = self.token
            # Outer timeout cap — nats-py's own timeout is a soft hint
            self._nc = await asyncio.wait_for(
                nats.connect(self.url, **kwargs), timeout=4.0
            )
            LOG.info(f"NATS connected: {self.url}")
        except asyncio.TimeoutError as e:
            LOG.warning(f"NATS connect timeout: {self.url} — listener disabled")
            self._nc = None
            return {"status": "unreachable", "error": "connect timeout", "url": self.url}
        except Exception as e:
            LOG.warning(f"NATS connect failed: {e} — listener disabled")
            self._nc = None
            return {"status": "unreachable", "error": str(e), "url": self.url}

        # Subscribe to each subject
        for subj in self.subscribe_subjects:
            try:
                sub = await self._nc.subscribe(subj)
                self._subs.append((subj, sub))
                LOG.info(f"subscribed: {subj}")
            except Exception as e:
                LOG.error(f"failed to subscribe to {subj}: {e}")

        # Spawn one task per subscription
        self._running = True
        for subj, sub in self._subs:
            asyncio.create_task(self._drain(subj, sub))

        return {
            "status": "connected",
            "url": self.url,
            "subscriptions": [s for s, _ in self._subs],
        }

    async def stop(self) -> dict[str, Any]:
        self._running = False
        for _, sub in self._subs:
            try:
                await sub.unsubscribe()
            except Exception:
                pass
        self._subs = []
        if self._nc:
            try:
                await self._nc.drain()
            except Exception:
                pass
            self._nc = None
        return {"status": "stopped"}

    async def _drain(self, subject: str, sub: Any) -> None:
        """Consume messages from a subscription, convert to Event, dispatch."""
        LOG.info(f"drain started: {subject}")
        try:
            async for msg in sub.messages:
                if not self._running:
                    break
                try:
                    await self._handle_msg(subject, msg)
                except Exception as e:
                    LOG.exception(f"error handling msg on {subject}: {e}")
        except Exception as e:
            LOG.exception(f"drain crashed for {subject}: {e}")
        LOG.info(f"drain stopped: {subject}")

    async def _handle_msg(self, subject: str, msg: Any) -> None:
        raw = msg.data.decode("utf-8", errors="replace") if msg.data else ""
        # Try to parse JSON
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"_raw": raw}

        # Build Event. All NATS messages are external → spec 8.1 applies
        from .engine import Event  # local import to avoid cycle

        # Infer source from subject: subspace.tallon.outgoing.hephaestus → tallon
        source = "unknown"
        parts = subject.split(".")
        if len(parts) >= 2 and parts[0] == "subspace":
            source = parts[1] if parts[1] != "broadcast" else "broadcast"
        # Also try payload-level source (Tallon may include it)
        if isinstance(payload, dict) and "source" in payload:
            source = payload["source"]

        # Optional target inference
        target = None
        if isinstance(payload, dict):
            target = payload.get("target")

        # Event.type is the routing discriminator (the rule engine filters
        # on it via `event_type: nats.message` in the rule's when: block).
        # We MUST NOT use the payload's `type` field here — Tallon/Enterprise
        # application messages commonly include their own `type` key
        # (e.g. "deploy.request", "workflow.complete") which is application
        # metadata, not the routing type. Using it as the routing type would
        # cause every well-formed application message to fail the
        # `event_type: nats.message` rule filter and fall through to the
        # default __default_external__ quarantine rule. The payload's `type`
        # (if present) is still preserved inside ev.payload["type"] for any
        # downstream consumer that wants to branch on it.
        #
        # Bug discovered 2026-06-15 by Marvin (Phase 3 REWORK #1 Step 3.1).
        # The prior behavior (`type=payload.get("type") or "nats.message"`)
        # was the actual root cause of BUILD-PLAN §Phase 3's "they all get
        # quarantined because no rule matches the NATS subjects" — the
        # rules DID match the subject, but the listener had rewritten the
        # event type to the application-level `type` and the event_type
        # filter rejected the rewritten value. Lock-in: test_nats_bridge.py
        # ::TestNatsListenerToEngineBridge pins the fixed behavior.
        event = Event(
            type="nats.message",
            source=source,
            target=target,
            subject=subject,
            payload=payload if isinstance(payload, dict) else {"value": payload},
            is_external=True,
        )

        LOG.info(f"NATS msg: subject={subject} source={source} bytes={len(raw)}")
        if self.on_message:
            res = self.on_message(event)
            if asyncio.iscoroutine(res):
                await res

    async def publish(self, subject: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Publish a message to NATS (used by nats_publish workflow steps
        and for outbound Subspace replies). Returns {status, ...}."""
        if not self.is_connected:
            return {"status": "not_connected"}
        try:
            await self._nc.publish(subject, json.dumps(payload, default=str).encode("utf-8"))
            await self._nc.flush()
            return {"status": "published", "subject": subject, "bytes": len(json.dumps(payload))}
        except Exception as e:
            LOG.error(f"publish failed on {subject}: {e}")
            return {"status": "error", "error": str(e)}


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _smoke() -> int:
        listener = NATSListener()
        status = await listener.start()
        print(f"start: {status}")
        if status.get("status") != "connected":
            return 1
        # Publish a test message
        pub_status = await listener.publish(
            "subspace.pantheon.workflow.test",
            {"type": "workflow.test", "source": "conductor", "hello": "world"},
        )
        print(f"publish: {pub_status}")
        await asyncio.sleep(1)
        stop = await listener.stop()
        print(f"stop: {stop}")
        return 0

    sys.exit(asyncio.run(_smoke()))
