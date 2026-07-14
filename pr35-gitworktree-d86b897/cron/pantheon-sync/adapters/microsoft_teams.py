"""
Microsoft Teams Sync Adapter.

Checks Teams n8n credential status. Actual data sync is handled
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


@register_adapter("microsoft_teams")
class MicrosoftTeamsAdapter(BaseAdapter):
    """Sync adapter for Microsoft Teams via n8n credential."""

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
                error="No Teams credential in n8n.",
            )

        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        from_data = raw_item.get("from", raw_item.get("user", {}))
        if isinstance(from_data, dict):
            user_data = from_data.get("user", from_data)
            sender = user_data.get("displayName", user_data.get("name", "unknown")) if isinstance(user_data, dict) else str(from_data)
        else:
            sender = str(from_data)

        channel_data = raw_item.get("channelIdentity", {})
        channel = channel_data.get("channelName", raw_item.get("channel", "unknown")) if isinstance(channel_data, dict) else str(channel_data)

        body_data = raw_item.get("body", {})
        text = body_data.get("content", raw_item.get("text", raw_item.get("message", ""))) if isinstance(body_data, dict) else raw_item.get("body", "")

        msg_id = raw_item.get("id", "")

        content = f"**{sender}** in #{channel}:\n\n{text}"

        return SyncRecord(
            provider=self.provider,
            source_id=str(msg_id),
            content=content,
            metadata={
                "sender": str(sender),
                "channel": str(channel),
                "timestamp": raw_item.get("createdDateTime", raw_item.get("timestamp", "")),
            },
            tags=["chat", "teams", f"channel:{channel}"],
        )
