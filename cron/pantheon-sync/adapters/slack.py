"""
Slack Sync Adapter.

Fetches recent Slack messages from channels via Composio BYOK.
Produces canonicalized Markdown records with sender, text, timestamp, and metadata.

Stub implementation: returns realistic sample data until OAuth is wired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import BaseAdapter, SyncRecord, SyncResult, register_adapter


@register_adapter("slack")
class SlackAdapter(BaseAdapter):
    """Sync adapter for Slack."""

    def __init__(self, api_key: str | None = None, auth_config_id: str | None = None):
        self.api_key = api_key
        self.auth_config_id = auth_config_id

    def sync(self, cursor: str | None = None) -> SyncResult:
        """Fetch recent Slack messages.

        In production, this calls the Slack API via Composio:
            session = composio.create(user_id=..., toolkits=["slack"])
            msgs = session.tools()["slack"].fetch_messages(...)
        """
        now = datetime.utcnow().isoformat()
        samples = [
            {
                "id": "slk_001",
                "channel": "#pantheon-dev",
                "sender": "konan",
                "text": "Alright, T7 is merged. Stream A is done! 🎉",
                "thread_ts": None,
                "reactions": ["🎉", "🚀"],
                "timestamp": now,
            },
            {
                "id": "slk_002",
                "channel": "#pantheon-dev",
                "sender": "alice",
                "text": "Nice work! What's next — Stream B adapters or Stream C OAuth?",
                "thread_ts": None,
                "reactions": [],
                "timestamp": now,
            },
            {
                "id": "slk_003",
                "channel": "#general",
                "sender": "bob",
                "text": "Heads up: the search debounce was discussed in issue #128. I think 150ms is the sweet spot.",
                "thread_ts": "slk_003",
                "reactions": ["👍"],
                "timestamp": now,
            },
        ]

        records = [self.canonicalize(item) for item in samples]
        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=samples[-1]["id"] if samples else None,
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        """Convert a raw Slack message to a canonical SyncRecord."""
        channel = raw_item.get("channel", "unknown")
        sender = raw_item.get("sender", "unknown")
        text = raw_item.get("text", "")
        reactions = raw_item.get("reactions", [])
        is_thread = bool(raw_item.get("thread_ts"))

        content = f"**{sender}** in {channel}"
        if is_thread:
            content += " (thread reply)"
        content += f":\n\n{text}"

        if reactions:
            content += f"\n\n*Reactions: {' '.join(reactions)}*"

        return SyncRecord(
            provider=self.provider,
            source_id=raw_item["id"],
            content=content,
            metadata={
                "sender": sender,
                "channel": channel,
                "is_thread_reply": is_thread,
                "reactions": reactions,
                "timestamp": raw_item.get("timestamp"),
            },
            tags=["chat", f"channel:{channel.lstrip('#')}"],
        )
