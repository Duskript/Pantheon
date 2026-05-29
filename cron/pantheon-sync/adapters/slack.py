"""
Slack Sync Adapter.

Fetches recent Slack messages from joined channels via Composio BYOK OAuth.
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


@register_adapter("slack")
class SlackAdapter(BaseAdapter):
    """Sync adapter for Slack via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "slack", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No Slack connected account.")

        args: dict[str, Any] = {"limit": 30}
        if cursor:
            args["cursor"] = cursor

        data = _exec_composio_tool(client, account_id, "SLACK_FETCH_MESSAGES", args)
        if data is None:
            data = _exec_composio_tool(client, account_id, "SLACK_LIST_MESSAGES", args)

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch Slack messages")

        msgs = data if isinstance(data, list) else data.get("messages", data.get("data", []))
        if isinstance(msgs, dict):
            msgs = [msgs]
        records = [self.canonicalize(msg) for msg in msgs]

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=data.get("next_cursor") if isinstance(data, dict) else (
                records[-1].source_id if records else cursor
            ),
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        channel = raw_item.get("channel", {}).get("name", "") if isinstance(raw_item.get("channel"), dict) else raw_item.get("channel", "unknown")
        sender = raw_item.get("user", raw_item.get("sender", "unknown"))
        text = raw_item.get("text", raw_item.get("body", ""))
        ts = raw_item.get("ts", raw_item.get("timestamp", ""))
        thread_ts = raw_item.get("thread_ts")
        reactions = raw_item.get("reactions", [])

        content = f"**{sender}** in #{channel}"
        if thread_ts:
            content += " (thread)"
        content += f":\n\n{text}"

        if reactions:
            react_strs = []
            for r in reactions:
                if isinstance(r, dict):
                    react_strs.append(r.get("name", ""))
                else:
                    react_strs.append(str(r))
            content += f"\n\n*Reactions: {' '.join(f':{r}:' for r in react_strs if r)}*"

        return SyncRecord(
            provider=self.provider,
            source_id=str(ts or "0"),
            content=content,
            metadata={
                "sender": str(sender),
                "channel": str(channel),
                "is_thread_reply": bool(thread_ts),
                "reactions": reactions,
                "timestamp": ts,
            },
            tags=["chat", "slack", f"channel:{str(channel).lstrip('#')}"],
        )
