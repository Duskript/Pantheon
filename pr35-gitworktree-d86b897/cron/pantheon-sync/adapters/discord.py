"""
Discord Sync Adapter.

Checks Discord n8n credential status. Actual data sync is handled
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


@register_adapter("discord")
class DiscordAdapter(BaseAdapter):
    """Sync adapter for Discord via n8n credential."""

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
                error="No Discord credential in n8n.",
            )

        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        author = raw_item.get("author", raw_item.get("user", {}))
        if isinstance(author, dict):
            author = author.get("username", author.get("displayName", author.get("name", "unknown")))
        elif not isinstance(author, str):
            author = str(author or "unknown")

        channel_id = raw_item.get("channel_id", raw_item.get("channel", "unknown"))
        text = raw_item.get("content", raw_item.get("text", ""))
        msg_id = raw_item.get("id", "")

        content = f"**{author}** (channel: {channel_id}):\n\n{text}"

        return SyncRecord(
            provider=self.provider,
            source_id=str(msg_id),
            content=content,
            metadata={
                "author": str(author),
                "channel_id": str(channel_id),
                "timestamp": raw_item.get("timestamp", ""),
            },
            tags=["chat", "discord", f"channel:{channel_id}"],
        )
