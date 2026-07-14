"""
Outlook Sync Adapter.

Checks Outlook (Microsoft) n8n credential status. Actual data sync
is handled by n8n workflows.
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


@register_adapter("outlook")
class OutlookAdapter(BaseAdapter):
    """Sync adapter for Microsoft Outlook via n8n credential."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        cred = _check_n8n_credential(self.provider)
        if cred.get("error") and not cred["connected"]:
            return SyncResult(
                provider=self.provider, records=[], status="no_auth",
                error=cred["error"],
            )
        if not cred["connected"]:
            return SyncResult(
                provider=self.provider, records=[], status="not_connected",
                error="No Outlook credential in n8n.",
            )

        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        # Outlook API nest sender under from.emailAddress
        sender_data = raw_item.get("from", {})
        if isinstance(sender_data, dict):
            email_data = sender_data.get("emailAddress", {})
            sender = email_data.get("address", email_data.get("name", "unknown")) if isinstance(email_data, dict) else str(sender_data)
        else:
            sender = str(sender_data)

        subject = raw_item.get("subject", "(no subject)")

        # Body may be nested under body.content
        body_data = raw_item.get("body", {})
        body = body_data.get("content", raw_item.get("bodyPreview", raw_item.get("body", ""))) if isinstance(body_data, dict) else raw_item.get("body", "")

        msg_id = raw_item.get("id", "")
        received = raw_item.get("receivedDateTime", raw_item.get("timestamp", ""))

        content = f"# {subject}\n\n**From:** {sender}\n\n{body}"

        return SyncRecord(
            provider=self.provider,
            source_id=str(msg_id),
            content=content,
            metadata={
                "sender": str(sender),
                "subject": str(subject),
                "received": str(received),
                "conversation_id": raw_item.get("conversationId", ""),
            },
            tags=["email", "outlook"],
        )
