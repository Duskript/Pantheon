"""
Notion Sync Adapter.

Fetches recently modified Notion pages via Composio BYOK OAuth.
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


@register_adapter("notion")
class NotionAdapter(BaseAdapter):
    """Sync adapter for Notion via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "notion", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No Notion connected account.")

        args: dict[str, Any] = {"page_size": 30}
        if cursor:
            args["start_cursor"] = cursor

        data = _exec_composio_tool(client, account_id, "NOTION_SEARCH", args)
        if data is None:
            data = _exec_composio_tool(
                client, account_id, "NOTION_LIST_PAGES", args
            )

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch Notion pages")

        pages = data if isinstance(data, list) else data.get("results", data.get("pages", []))
        if isinstance(pages, dict):
            pages = [pages]
        records = [self.canonicalize(page) for page in pages]

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=data.get("next_cursor") if isinstance(data, dict) else (
                records[-1].source_id if records else cursor
            ),
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        # Extract title from various Notion page shapes
        title = ""
        props = raw_item.get("properties", {})
        if isinstance(props, dict):
            title_prop = props.get("title", props.get("Name", {}))
            if isinstance(title_prop, dict):
                title_items = title_prop.get("title", [])
                if isinstance(title_items, list):
                    title = "".join(
                        t.get("plain_text", "") if isinstance(t, dict) else str(t)
                        for t in title_items
                    )

        if not title:
            title = raw_item.get("title", "Untitled")

        page_id = str(raw_item.get("id", ""))
        url = raw_item.get("url", f"https://notion.so/{page_id.replace('-', '')}")
        last_edited = raw_item.get("last_edited_time", raw_item.get("timestamp", ""))
        created = raw_item.get("created_time", "")
        archived = raw_item.get("archived", False)

        content = f"# {title}\n\n"
        content += f"**Notion Page** · [Open in Notion]({url})\n"
        if archived:
            content += "*(archived)*\n"
        if last_edited:
            content += f"Last edited: {last_edited}\n"

        return SyncRecord(
            provider=self.provider,
            source_id=page_id,
            content=content,
            metadata={
                "title": str(title),
                "url": str(url),
                "last_edited": str(last_edited),
                "created": str(created),
                "archived": archived,
            },
            tags=["docs", "notion", "wiki"],
        )
