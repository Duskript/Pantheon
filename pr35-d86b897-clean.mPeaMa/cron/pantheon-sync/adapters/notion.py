"""
Notion Sync Adapter.

Checks Notion n8n credential status. Actual data sync is handled
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


@register_adapter("notion")
class NotionAdapter(BaseAdapter):
    """Sync adapter for Notion via n8n credential."""

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
                error="No Notion credential in n8n. Set up in Settings → Integrations.",
            )

        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        props = raw_item.get("properties", {})
        title_data = props.get("title", props.get("Name", {}))
        title_parts = title_data.get("title", []) if isinstance(title_data, dict) else []
        title = title_parts[0].get("plain_text", "") if title_parts else raw_item.get("url", "(no title)")

        page_id = raw_item.get("id", "")
        url = raw_item.get("url", "")
        last_edited = raw_item.get("last_edited_time", raw_item.get("last_edited", ""))

        content = f"# {title}\n\n**Source:** Notion ({url})\n\n"

        return SyncRecord(
            provider=self.provider,
            source_id=str(page_id),
            content=content,
            metadata={
                "title": str(title),
                "url": str(url),
                "last_edited": str(last_edited),
            },
            tags=["docs", "notion"],
        )
