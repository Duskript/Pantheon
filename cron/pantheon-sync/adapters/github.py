"""
GitHub Sync Adapter.

Fetches recent GitHub events (PRs, issues, commits) via Composio BYOK.
Produces canonicalized Markdown records with repo, event_type, and metadata.

Stub implementation: returns realistic sample data until OAuth is wired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import BaseAdapter, SyncRecord, SyncResult, register_adapter


@register_adapter("github")
class GitHubAdapter(BaseAdapter):
    """Sync adapter for GitHub."""

    def __init__(self, api_key: str | None = None, auth_config_id: str | None = None):
        self.api_key = api_key
        self.auth_config_id = auth_config_id

    def sync(self, cursor: str | None = None) -> SyncResult:
        """Fetch recent GitHub events.

        In production, this calls the GitHub API via Composio:
            session = composio.create(user_id=..., toolkits=["github"])
            events = session.tools()["github"].list_events(...)
        """
        now = datetime.utcnow().isoformat()
        samples = [
            {
                "id": "evt_001",
                "repo": "konan/pantheon-core",
                "event_type": "PullRequestReview",
                "title": "PR #42: OAuth Flow UI",
                "actor": "alice",
                "action": "approved",
                "body": "LGTM! The ConnectionManager looks clean. One nit: add error handling for the fetch call in handleConnect.",
                "url": "https://github.com/konan/pantheon-core/pull/42",
                "timestamp": now,
            },
            {
                "id": "evt_002",
                "repo": "konan/pantheon-core",
                "event_type": "IssuesEvent",
                "title": "Issue #128: Search panel debounce too aggressive",
                "actor": "bob",
                "action": "opened",
                "body": "The search panel has a 300ms debounce which feels sluggish. Can we reduce to 150ms or make it configurable?",
                "url": "https://github.com/konan/pantheon-core/issues/128",
                "timestamp": now,
            },
            {
                "id": "evt_003",
                "repo": "konan/Olympus-UI",
                "event_type": "PushEvent",
                "title": "feat(admin): T7 multi-user toggle",
                "actor": "konan",
                "action": "pushed",
                "body": "3 files changed, 15 insertions(+), 4 deletions(-)\n\n- __root.tsx: fetch feature flags on boot\n- AdminPanel.tsx: restore multi_user gating\n- AdminPanel.test.tsx: updated tests",
                "url": "https://github.com/konan/Olympus-UI/commit/d12e416",
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
        """Convert a raw GitHub event to a canonical SyncRecord."""
        repo = raw_item.get("repo", "unknown")
        event_type = raw_item.get("event_type", "unknown")
        title = raw_item.get("title", "")
        actor = raw_item.get("actor", "unknown")
        action = raw_item.get("action", "")
        body = raw_item.get("body", "")

        content = f"# [{repo}] {title}\n\n"
        content += f"**Event:** {event_type} · **Actor:** {actor} · **Action:** {action}\n\n"
        content += body

        return SyncRecord(
            provider=self.provider,
            source_id=raw_item["id"],
            content=content,
            metadata={
                "repo": repo,
                "event_type": event_type,
                "actor": actor,
                "action": action,
                "url": raw_item.get("url"),
                "timestamp": raw_item.get("timestamp"),
            },
            tags=["code", f"repo:{repo}", f"event:{event_type}"],
        )
