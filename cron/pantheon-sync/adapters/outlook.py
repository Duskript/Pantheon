"""
Outlook Sync Adapter.

Fetches recent emails from Microsoft Outlook via Composio BYOK OAuth.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseAdapter,
    SyncRecord,
    SyncResult,
    register_adapter,
    _get_composio_client,
    _get_connected_account_id,
    _exec_composio_tool,
)


@register_adapter("outlook")
class OutlookAdapter(BaseAdapter):
    """Sync adapter for Microsoft Outlook via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "outlook", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No Outlook connected account.")

        args: dict[str, Any] = {"top": 20, "$orderby": "receivedDateTime desc"}
        if cursor:
            args["$filter"] = f"receivedDateTime gt {cursor}"

        data = _exec_composio_tool(client, account_id, "OUTLOOK_LIST_MESSAGES", args)
        if data is None:
            data = _exec_composio_tool(client, account_id, "OUTLOOK_FETCH_EMAILS", args)

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch Outlook messages")

        messages = data if isinstance(data, list) else data.get("value", data.get("messages", []))
        if isinstance(messages, dict):
            messages = [messages]
        records = [self.canonicalize(msg) for msg in messages]

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=records[-1].source_id if records else cursor,
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        sender_data = raw_item.get("from", raw_item.get("sender", {}))
        if isinstance(sender_data, dict):
            sender = sender_data.get("emailAddress", {}).get("address", "") if isinstance(sender_data.get("emailAddress"), dict) else sender_data.get("address", "unknown")
        else:
            sender = str(sender_data or "unknown")

        subject = raw_item.get("subject", "(no subject)")
        body = raw_item.get("body", {}).get("content", "") if isinstance(raw_item.get("body"), dict) else raw_item.get("bodyPreview", raw_item.get("body", ""))
        categories = raw_item.get("categories", [])
        msg_id = str(raw_item.get("id", ""))

        content = f"# {subject}\n\n**From:** {sender}\n\n{body}"

        return SyncRecord(
            provider=self.provider,
            source_id=msg_id,
            content=content,
            metadata={
                "sender": sender,
                "subject": str(subject),
                "categories": categories if isinstance(categories, list) else [],
                "has_attachments": bool(raw_item.get("hasAttachments", False)),
                "timestamp": raw_item.get("receivedDateTime", raw_item.get("timestamp")),
            },
            tags=["email", "outlook", "microsoft"] + (
                [f"category:{c.lower()}" for c in categories]
                if isinstance(categories, list) else []
            ),
        )
