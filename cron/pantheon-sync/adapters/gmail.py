"""
Gmail Sync Adapter.

Checks Gmail n8n credential status. Actual data sync is handled
by n8n workflows.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseAdapter,
    SyncRecord,
    SyncResult,
    register_adapter,
    _check_n8n_credential,
)


@register_adapter("gmail")
class GmailAdapter(BaseAdapter):
    """Sync adapter for Gmail via n8n credential."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        cred = _check_n8n_credential(self.provider)
        if cred.get("error") and not cred["connected"]:
            return SyncResult(
                provider=self.provider,
                records=[],
                status="no_auth",
                error=cred["error"],
            )
        if not cred["connected"]:
            return SyncResult(
                provider=self.provider,
                records=[],
                status="not_connected",
                error="No Gmail credential in n8n. Set up in Settings → Integrations.",
            )

        # Credential exists — data sync is handled by n8n workflows
        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        sender = raw_item.get("from", raw_item.get("sender", "unknown"))
        subject = raw_item.get("subject", "(no subject)")
        body = raw_item.get("body", raw_item.get("snippet", ""))
        labels = raw_item.get("labels", raw_item.get("labelIds", []))
        msg_id = raw_item.get("id", raw_item.get("messageId", ""))

        content = f"# {subject}\n\n**From:** {sender}\n\n{body}"

        return SyncRecord(
            provider=self.provider,
            source_id=str(msg_id),
            content=content,
            metadata={
                "sender": str(sender),
                "subject": str(subject),
                "thread_id": raw_item.get("threadId", raw_item.get("thread_id")),
                "labels": labels if isinstance(labels, list) else [labels],
                "timestamp": raw_item.get("internalDate", raw_item.get("timestamp")),
            },
            tags=["email", "gmail"] + (
                [f"label:{l.lower()}" for l in labels]
                if isinstance(labels, list) else []
            ),
        )
