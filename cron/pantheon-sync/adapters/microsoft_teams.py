"""
Microsoft Teams Sync Adapter.

Fetches recent chat messages from Teams via Composio BYOK OAuth.
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


@register_adapter("microsoft_teams")
class MicrosoftTeamsAdapter(BaseAdapter):
    """Sync adapter for Microsoft Teams via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "microsoft_teams", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No Microsoft Teams connected account.")

        args: dict[str, Any] = {"limit": 30}
        data = _exec_composio_tool(
            client, account_id, "MICROSOFT_TEAMS_LIST_MESSAGES", args
        )
        if data is None:
            data = _exec_composio_tool(
                client, account_id, "MICROSOFT_TEAMS_FETCH_CHAT_MESSAGES", args
            )

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch Teams messages")

        msgs = data if isinstance(data, list) else data.get("value", data.get("messages", []))
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
        sender_data = raw_item.get("from", raw_item.get("sender", {}))
        if isinstance(sender_data, dict):
            sender = sender_data.get("user", {}).get("displayName", "") if isinstance(sender_data.get("user"), dict) else sender_data.get("displayName", "unknown")
        else:
            sender = str(sender_data or "unknown")

        channel = raw_item.get("channelIdentity", raw_item.get("channel", {}))
        channel_name = ""
        if isinstance(channel, dict):
            channel_name = channel.get("channelName", channel.get("displayName", ""))
        elif isinstance(channel, str):
            channel_name = channel

        text = raw_item.get("body", {}).get("content", "") if isinstance(raw_item.get("body"), dict) else raw_item.get("content", raw_item.get("text", ""))
        msg_id = str(raw_item.get("id", ""))
        created = raw_item.get("createdDateTime", raw_item.get("timestamp", ""))

        content = f"**{sender}**"
        if channel_name:
            content += f" in {channel_name}"
        content += f":\n\n{text}"

        return SyncRecord(
            provider=self.provider,
            source_id=msg_id,
            content=content,
            metadata={
                "sender": sender,
                "channel": channel_name,
                "message_type": raw_item.get("messageType", ""),
                "timestamp": created,
            },
            tags=["chat", "teams", "microsoft"] + (
                [f"channel:{channel_name}"] if channel_name else []
            ),
        )
