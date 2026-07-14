"""
Slack Sync Adapter.

Checks Slack n8n credential status. Actual data sync is handled
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


@register_adapter("slack")
class SlackAdapter(BaseAdapter):
    """Sync adapter for Slack via n8n credential."""

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
                error="No Slack credential in n8n. Set up in Settings → Integrations.",
            )

        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        user = raw_item.get("user", raw_item.get("username", raw_item.get("author", {})))
        if isinstance(user, dict):
            user = user.get("username", user.get("displayName", user.get("name", "unknown")))
        channel = raw_item.get("channel", raw_item.get("channel_name", "unknown"))
        text = raw_item.get("text", raw_item.get("message", ""))
        ts = raw_item.get("ts", raw_item.get("timestamp", ""))
        msg_id = raw_item.get("id", raw_item.get("client_msg_id", ts))

        content = f"**{user}** in #{channel}:\n\n{text}"

        return SyncRecord(
            provider=self.provider,
            source_id=str(msg_id),
            content=content,
            metadata={
                "user": str(user),
                "channel": str(channel),
                "timestamp": str(ts),
            },
            tags=["chat", "slack", f"channel:{channel}"],
        )
