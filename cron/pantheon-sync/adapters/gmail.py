"""
Gmail Sync Adapter.

Fetches recent emails from Gmail via Composio BYOK OAuth.
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


@register_adapter("gmail")
class GmailAdapter(BaseAdapter):
    """Sync adapter for Gmail via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(
                provider=self.provider,
                records=[],
                status="no_auth",
                error="Composio API key not configured",
            )

        account_id = _get_connected_account_id(client, "gmail", connection)
        if account_id is None:
            return SyncResult(
                provider=self.provider,
                records=[],
                status="not_connected",
                error="No Gmail connected account. Run OAuth flow first.",
            )

        # Fetch recent unread emails
        args: dict[str, Any] = {"maxResults": 20, "q": "is:unread"}
        if cursor:
            args["q"] = f"after:{cursor}"

        data = _exec_composio_tool(
            client, account_id, "GMAIL_FETCH_MESSAGES", args
        )

        if data is None:
            return SyncResult(
                provider=self.provider,
                records=[],
                status="error",
                error="Failed to fetch Gmail messages via Composio",
            )

        messages = data if isinstance(data, list) else data.get("messages", [])
        records = [self.canonicalize(msg) for msg in messages]

        next_cursor = records[-1].source_id if records else cursor

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=next_cursor,
            status="ok" if records else "empty",
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
