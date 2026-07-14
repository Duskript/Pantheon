"""
GitHub Sync Adapter.

Checks GitHub n8n credential status. Actual data sync is handled
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


@register_adapter("github")
class GitHubAdapter(BaseAdapter):
    """Sync adapter for GitHub via n8n credential."""

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
                error="No GitHub credential in n8n. Set up in Settings → Integrations.",
            )

        # Credential exists — data sync is handled by n8n workflows
        return SyncResult(
            provider=self.provider,
            records=[],
            next_cursor=cursor,
            status="ok",
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
        content += f"**Event:** {event_type} \u00b7 **Actor:** {actor}"
        if action:
            content += f" \u00b7 **Action:** {action}"
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
