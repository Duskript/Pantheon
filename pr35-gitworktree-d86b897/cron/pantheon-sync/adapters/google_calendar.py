"""
Google Calendar Sync Adapter.

Checks Google Calendar n8n credential status. Actual data sync
is handled by n8n workflows.
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


@register_adapter("google_calendar")
class GoogleCalendarAdapter(BaseAdapter):
    """Sync adapter for Google Calendar via n8n credential."""

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
                error="No Google Calendar credential in n8n.",
            )

        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        summary = raw_item.get("summary", raw_item.get("title", "(no title)"))
        evt_id = raw_item.get("id", "")
        start = raw_item.get("start", {})
        end = raw_item.get("end", {})
        start_dt = start.get("dateTime", start.get("date", "")) if isinstance(start, dict) else ""
        end_dt = end.get("dateTime", end.get("date", "")) if isinstance(end, dict) else ""
        attendees = raw_item.get("attendees", [])
        attendee_list = [a.get("email", "") for a in attendees] if isinstance(attendees, list) else []

        if start_dt and end_dt:
            time_str = f"{start_dt} → {end_dt}"
        else:
            time_str = ""

        content = f"# {summary}\n\n"
        if time_str:
            content += f"**When:** {time_str}\n\n"
        if attendee_list:
            content += f"**Attendees:** {', '.join(attendee_list)}\n\n"

        return SyncRecord(
            provider=self.provider,
            source_id=str(evt_id),
            content=content,
            metadata={
                "summary": str(summary),
                "start": start_dt,
                "end": end_dt,
                "attendees": attendee_list,
                "location": raw_item.get("location", raw_item.get("htmlLink", "")),
            },
            tags=["calendar", "google_calendar"],
        )
