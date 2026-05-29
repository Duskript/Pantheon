"""
Google Calendar Sync Adapter.

Fetches upcoming calendar events via Composio BYOK OAuth.
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


@register_adapter("google_calendar")
class GoogleCalendarAdapter(BaseAdapter):
    """Sync adapter for Google Calendar via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "googlecalendar", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No Google Calendar connected account.")

        args: dict[str, Any] = {"maxResults": 30, "timeMin": cursor or ""}
        data = _exec_composio_tool(
            client, account_id, "GOOGLECALENDAR_LIST_EVENTS", args
        )
        if data is None:
            data = _exec_composio_tool(
                client, account_id, "GOOGLECALENDAR_FETCH_EVENTS", args
            )

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch calendar events")

        events = data if isinstance(data, list) else data.get("items", data.get("events", []))
        if isinstance(events, dict):
            events = [events]
        records = [self.canonicalize(evt) for evt in events]

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=records[-1].metadata.get("start") if records else cursor,
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        summary = raw_item.get("summary", "(untitled event)")
        start = raw_item.get("start", {})
        end = raw_item.get("end", {})
        start_time = start.get("dateTime", start.get("date", "")) if isinstance(start, dict) else str(start)
        end_time = end.get("dateTime", end.get("date", "")) if isinstance(end, dict) else str(end)
        location = raw_item.get("location", "")
        description = raw_item.get("description", "")
        attendees_list = raw_item.get("attendees", [])
        attendees = []
        for a in attendees_list:
            if isinstance(a, dict):
                attendees.append(a.get("email", a.get("displayName", "")))
            else:
                attendees.append(str(a))

        content = f"# {summary}\n\n"
        if start_time:
            content += f"**When:** {start_time}"
            if end_time:
                content += f" → {end_time}"
            content += "\n"
        if location:
            content += f"**Where:** {location}\n"
        if attendees:
            content += f"**Attendees:** {', '.join(a for a in attendees if a)}\n"
        if description:
            content += f"\n{description}"

        return SyncRecord(
            provider=self.provider,
            source_id=str(raw_item.get("id", "")),
            content=content,
            metadata={
                "summary": str(summary),
                "start": str(start_time),
                "end": str(end_time),
                "location": str(location) if location else "",
                "attendees": attendees,
                "event_id": raw_item.get("id"),
            },
            tags=["calendar", "google_calendar", "meeting"],
        )
