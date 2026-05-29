"""
GitHub Sync Adapter.

Fetches recent GitHub events (PRs, issues, commits, stars)
via Composio BYOK OAuth.
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


@register_adapter("github")
class GitHubAdapter(BaseAdapter):
    """Sync adapter for GitHub via Composio."""

    def sync(
        self, connection: dict[str, Any], cursor: str | None = None
    ) -> SyncResult:
        client = _get_composio_client(connection)
        if client is None:
            return SyncResult(provider=self.provider, records=[], status="no_auth",
                              error="Composio API key not configured")

        account_id = _get_connected_account_id(client, "github", connection)
        if account_id is None:
            return SyncResult(provider=self.provider, records=[], status="not_connected",
                              error="No GitHub connected account. Run OAuth flow first.")

        args: dict[str, Any] = {"per_page": 30}
        data = _exec_composio_tool(client, account_id, "GITHUB_LIST_USER_EVENTS", args)
        if data is None:
            # Fallback: try activity feed
            data = _exec_composio_tool(client, account_id, "GITHUB_GET_FEED", args)

        if data is None:
            return SyncResult(provider=self.provider, records=[], status="error",
                              error="Failed to fetch GitHub events via Composio")

        events = data if isinstance(data, list) else data.get("events", data.get("data", []))
        if isinstance(events, dict):
            events = [events]
        records = [self.canonicalize(evt) for evt in events]

        return SyncResult(
            provider=self.provider,
            records=records,
            next_cursor=records[-1].source_id if records else cursor,
            status="ok" if records else "empty",
        )

    def canonicalize(self, raw_item: dict[str, Any]) -> SyncRecord:
        repo = raw_item.get("repo", {}).get("name", "") if isinstance(raw_item.get("repo"), dict) else raw_item.get("repo", "unknown")
        event_type = raw_item.get("type", raw_item.get("event_type", "unknown"))
        actor_data = raw_item.get("actor", raw_item.get("user", {}))
        actor = actor_data.get("login", actor_data.get("display_login", "unknown")) if isinstance(actor_data, dict) else str(actor_data or "unknown")
        payload = raw_item.get("payload", {}) if isinstance(raw_item.get("payload"), dict) else {}
        action = payload.get("action", "")

        evt_id = str(raw_item.get("id", raw_item.get("event_id", "")))
        created = raw_item.get("created_at", raw_item.get("timestamp", ""))

        # Build title from event type + action
        title_map = {
            "PushEvent": f"push to {repo}",
            "PullRequestEvent": f"PR {action}: {repo}",
            "PullRequestReviewEvent": f"PR review {action}: {repo}",
            "IssuesEvent": f"Issue {action}: {repo}",
            "CreateEvent": f"created {payload.get('ref_type', '')} in {repo}",
            "WatchEvent": f"starred {repo}",
            "ForkEvent": f"forked {repo}",
        }
        title = title_map.get(event_type, f"{event_type} on {repo}")

        content = f"# [{repo}] {title}\n\n"
        content += f"**Event:** {event_type} · **Actor:** {actor}"
        if action:
            content += f" · **Action:** {action}"
        content += "\n"

        return SyncRecord(
            provider=self.provider,
            source_id=evt_id,
            content=content,
            metadata={
                "repo": str(repo),
                "event_type": str(event_type),
                "actor": str(actor),
                "action": str(action) if action else "",
                "url": raw_item.get("html_url", raw_item.get("url")),
                "timestamp": created,
            },
            tags=["code", "github", f"repo:{repo}", f"event:{event_type}"],
        )
