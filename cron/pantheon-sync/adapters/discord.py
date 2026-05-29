"""
Discord Sync Adapter.

Fetches recent messages from Discord guilds/channels via Composio BYOK OAuth.
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


@register_adapter("discord")
class DiscordAdapter(BaseAdapter):
    """Sync adapter for Discord via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "discord", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No Discord connected account.")

        args: dict[str, Any] = {"limit": 30}
        if cursor:
            args["before"] = cursor

        data = _exec_composio_tool(
            client, account_id, "DISCORD_FETCH_MESSAGES", args
        )
        if data is None:
            data = _exec_composio_tool(
                client, account_id, "DISCORD_LIST_MESSAGES", args
            )

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch Discord messages")

        msgs = data if isinstance(data, list) else data.get("messages", data.get("data", []))
        if isinstance(msgs, dict):
            msgs = [msgs]
        records = [self.canonicalize(msg) for msg in msgs]

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=records[-1].source_id if records else cursor,
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        author_data = raw_item.get("author", raw_item.get("user", {}))
        if isinstance(author_data, dict):
            author = author_data.get("username", author_data.get("global_name", "unknown"))
        else:
            author = str(author_data or "unknown")

        channel = raw_item.get("channel_id", raw_item.get("channel", ""))
        content_text = raw_item.get("content", raw_item.get("text", ""))
        msg_id = str(raw_item.get("id", ""))
        timestamp = raw_item.get("timestamp", raw_item.get("created_at", ""))

        # Attachments
        attachments = raw_item.get("attachments", [])
        attach_str = ""
        if attachments:
            names = []
            for a in attachments:
                if isinstance(a, dict):
                    names.append(a.get("filename", a.get("url", "")))
            if names:
                attach_str = f"\n\n*Attachments: {', '.join(n for n in names if n)}*"

        content = f"**{author}** in <#{channel}>:\n\n{content_text}{attach_str}"

        return SyncRecord(
            provider=self.provider,
            source_id=msg_id,
            content=content,
            metadata={
                "author": author,
                "channel_id": str(channel),
                "timestamp": timestamp,
                "has_attachments": bool(attachments),
            },
            tags=["chat", "discord", "community"],
        )
