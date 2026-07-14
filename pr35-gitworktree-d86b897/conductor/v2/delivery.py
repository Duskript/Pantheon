"""Conductor v2 delivery — Telegram + Subspace result router.

Spec section 11. When a god finishes a step, the result needs to land
in front of the right person. This module routes results to:

  1. Telegram (Konan's primary interface) via the gateway's Telegram platform
  2. Subspace/NATS replies back to Tallon (for cross-Pantheon workflows)
  3. The Pantheon messaging inbox (so other gods can pick it up)

Decoupling: we hit the gateway over HTTP for Telegram (same as spawning
runs), and use the NATS module for Subspace replies. No hermes-agent
imports.

Configuration (env):
    CONDUCTOR_TELEGRAM_CHAT_ID   Konan's chat ID for notifications
    CONDUCTOR_TELEGRAM_TOPIC_INBOX  Topic ID for #inbox (if forum group)
    CONDUCTOR_SUBSPACE_FROM       Our Pantheon ID (default: "konan")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from .engine import PENDING_DIR, utc_now

LOG = logging.getLogger("conductor.v2.delivery")


def _pending_dir() -> Path:
    """Resolve PENDING_DIR lazily — re-reads CONDUCTOR_BASE_DIR/PANTHEON_ROOT
    each call so test isolation via env vars works without reimporting."""
    import os as _os
    from pathlib import Path as _P
    base = _os.environ.get("CONDUCTOR_BASE_DIR")
    if base:
        return _P(base) / "pending"
    root = _os.environ.get("PANTHEON_ROOT", str(_P.home() / "pantheon"))
    return _P(root) / "conductor" / "pending"

DEFAULT_TELEGRAM_CHAT_ID = os.environ.get("CONDUCTOR_TELEGRAM_CHAT_ID", "")
DEFAULT_SUBSPACE_FROM = os.environ.get("CONDUCTOR_SUBSPACE_FROM", "konan")


@dataclass
class DeliveryTarget:
    name: str
    kind: str  # telegram | subspace | inbox
    chat_id: str = ""  # for telegram
    subject: str = ""  # for subspace
    inbox_god: str = ""  # for inbox


def build_default_targets() -> list[DeliveryTarget]:
    """The canonical set of delivery targets for a finished workflow step."""
    targets = [
        DeliveryTarget(
            name="pantheon-inbox",
            kind="inbox",
            inbox_god="hermes",
        ),
    ]
    if DEFAULT_TELEGRAM_CHAT_ID:
        targets.append(DeliveryTarget(
            name="telegram-konan",
            kind="telegram",
            chat_id=DEFAULT_TELEGRAM_CHAT_ID,
        ))
    return targets


def format_step_summary(
    workflow_id: str,
    definition_id: str,
    step_id: str,
    god: str,
    output: str,
    status: str = "completed",
    *,
    max_len: int = 800,
) -> str:
    """Format a step result as a human-readable message."""
    out = (output or "").strip()
    if len(out) > max_len:
        out = out[:max_len] + "…"
    icon = "✅" if status == "completed" else "❌" if status in ("failed", "aborted") else "⏳"
    lines = [
        f"{icon} *Conductor* — `{workflow_id}`",
        f"📋 {definition_id} / `{step_id}` ({god})",
        "",
        out or f"({status})",
    ]
    return "\n".join(lines)


def format_quarantine_alert(
    event_summary: str,
    source: str,
    subject: str,
    rule_id: str,
    quarantine_path: str,
) -> str:
    """Format the message Konan sees for an approval_required event."""
    return (
        f"🔔 *Conductor — Approval Required*\n\n"
        f"**Source:** `{source}`\n"
        f"**Subject:** `{subject}`\n"
        f"**Rule:** `{rule_id}`\n"
        f"**Event:** {event_summary}\n\n"
        f"Quarantined at: `{quarantine_path}`\n"
        f"Reply with: `approve {rule_id}` to handle, or `dismiss` to drop."
    )


class DeliveryRouter:
    """Routes notifications to Telegram / Subspace / Pantheon inboxes.

    Stateless — each deliver() call is independent. The router caches an
    httpx client for Telegram calls.
    """

    def __init__(
        self,
        gateway_base_url: str = "",
        gateway_api_key: str = "",
        targets: Optional[list[DeliveryTarget]] = None,
    ):
        from . import gateway as gw_mod  # local import
        # Reuse gateway's defaults for auth
        default_cfg = gw_mod.GatewayConfig()
        self.gateway_base_url = gateway_base_url or default_cfg.base_url
        self.gateway_api_key = gateway_api_key or default_cfg.api_key
        self.targets = targets or build_default_targets()
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "DeliveryRouter":
        self._client = httpx.AsyncClient(
            base_url=self.gateway_base_url,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.gateway_api_key}"} if self.gateway_api_key else {}),
            },
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("DeliveryRouter must be used as async context manager")
        return self._client

    async def deliver(
        self,
        text: str,
        targets: Optional[list[DeliveryTarget]] = None,
    ) -> list[dict[str, Any]]:
        """Send `text` to every target. Returns a list of per-target
        status dicts. Failures are isolated — one bad target doesn't
        block the others."""
        results: list[dict[str, Any]] = []
        for target in targets or self.targets:
            try:
                if target.kind == "telegram":
                    r = await self._send_telegram(target.chat_id, text)
                elif target.kind == "subspace":
                    r = await self._send_subspace(target.subject, text)
                elif target.kind == "inbox":
                    r = self._write_inbox(target.inbox_god, text)
                else:
                    r = {"status": "unknown_kind", "kind": target.kind}
            except Exception as e:
                LOG.error(f"delivery to {target.name} failed: {e}")
                r = {"status": "error", "target": target.name, "error": str(e)}
            results.append({"target": target.name, **r})
        return results

    async def deliver_step_completion(
        self,
        workflow_id: str,
        definition_id: str,
        step_id: str,
        god: str,
        output: str,
        status: str = "completed",
    ) -> list[dict[str, Any]]:
        text = format_step_summary(workflow_id, definition_id, step_id, god, output, status)
        return await self.deliver(text)

    async def deliver_quarantine_alert(
        self,
        event,
        rule_id: str,
        quarantine_path: str,
    ) -> list[dict[str, Any]]:
        text = format_quarantine_alert(
            event_summary=event.payload.get("summary", event.subject or event.type),
            source=event.source,
            subject=event.subject or "",
            rule_id=rule_id,
            quarantine_path=quarantine_path,
        )
        return await self.deliver(text)

    async def _send_telegram(self, chat_id: str, text: str) -> dict[str, Any]:
        """v1: write a notification file to pending/telegram_outbox/ that
        the gateway's Telegram platform adapter can pick up on its next
        poll cycle. Soft-delivery pattern — doesn't require the Telegram
        bot to run in our process. Future: POST directly to Telegram
        Bot API once the gateway exposes a send-message endpoint."""
        inbox = _pending_dir() / "telegram_outbox"
        inbox.mkdir(parents=True, exist_ok=True)
        fname = f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{chat_id}.json"
        path = inbox / fname
        path.write_text(json.dumps({
            "chat_id": chat_id,
            "text": text,
            "queued_at": utc_now(),
        }, indent=2))
        return {"status": "queued", "path": str(path)}

    async def _send_subspace(self, subject: str, text: str) -> dict[str, Any]:
        """Reply over Subspace. Writes a NATS-shaped message to a
        pending/nats_outbox/ directory; the nats listener picks it up
        on its next publish cycle."""
        inbox = _pending_dir() / "nats_outbox"
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.json"
        path.write_text(json.dumps({
            "subject": subject,
            "payload": {"text": text, "source": DEFAULT_SUBSPACE_FROM, "type": "conductor.reply"},
            "queued_at": utc_now(),
        }, indent=2))
        return {"status": "queued", "subject": subject, "path": str(path)}

    def _write_inbox(self, god: str, text: str) -> dict[str, Any]:
        inbox = _pending_dir() / god
        inbox.mkdir(parents=True, exist_ok=True)
        path = inbox / f"conductor_msg_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.json"
        path.write_text(json.dumps({
            "from": "conductor",
            "to": god,
            "text": text,
            "queued_at": utc_now(),
        }, indent=2))
        return {"status": "queued", "path": str(path)}


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    async def _smoke() -> int:
        async with DeliveryRouter() as router:
            results = await router.deliver_step_completion(
                workflow_id="wf_smoke_001",
                definition_id="morning-briefing",
                step_id="dawn-patrol",
                god="thoth",
                output="Today's research digest: 5 hot AI signals, 1 TheoForge lead, no blockers.",
                status="completed",
            )
            for r in results:
                print(r)
        return 0

    sys.exit(asyncio.run(_smoke()))
