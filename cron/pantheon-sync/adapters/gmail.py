"""
Gmail Sync Adapter.

Fetches recent emails from Gmail via the Composio BYOK OAuth flow (T14).
Produces canonicalized Markdown records with sender, subject, body, and metadata.

Stub implementation: returns realistic sample data until OAuth is wired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import BaseAdapter, SyncRecord, SyncResult, register_adapter


@register_adapter("gmail")
class GmailAdapter(BaseAdapter):
    """Sync adapter for Gmail."""

    def __init__(self, api_key: str | None = None, auth_config_id: str | None = None):
        self.api_key = api_key
        self.auth_config_id = auth_config_id

    def sync(self, cursor: str | None = None) -> SyncResult:
        """Fetch recent emails.

        In production, this calls the Gmail API via Composio:
            session = composio.create(user_id=..., toolkits=["gmail"])
            emails = session.tools()["gmail"].fetch_messages(...)
        """
        # Stub: return sample emails
        now = datetime.utcnow().isoformat()
        samples = [
            {
                "id": "msg_001",
                "thread_id": "thread_a",
                "sender": "alice@example.com",
                "subject": "Re: Q3 Planning Doc",
                "body": "Hey team,\n\nHere are my notes from the Q3 planning session:\n\n1. Priority: launch Olympus UI by end of Q3\n2. Secondary: integrate Composio OAuth for Gmail/GitHub/Slack\n3. Stretch: onboarding wizard with context gathering\n\nLet me know if I missed anything.\n\n— Alice",
                "timestamp": now,
                "labels": ["INBOX", "IMPORTANT"],
            },
            {
                "id": "msg_002",
                "thread_id": "thread_b",
                "sender": "bob@example.com",
                "subject": "PR #42 Review Request",
                "body": "Please review the OAuth flow PR when you get a chance.\n\nSummary of changes:\n- Added ConnectionManager component\n- Wired Composio BYOK flow\n- 15 new tests\n\nRepo: pantheon-core\nBranch: feat/oauth-flow\n\n— Bob",
                "timestamp": now,
                "labels": ["INBOX"],
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
        """Convert a raw Gmail message to a canonical SyncRecord."""
        sender = raw_item.get("sender", "unknown")
        subject = raw_item.get("subject", "(no subject)")
        body = raw_item.get("body", "")
        labels = raw_item.get("labels", [])

        content = f"# {subject}\n\n**From:** {sender}\n\n{body}"

        return SyncRecord(
            provider=self.provider,
            source_id=raw_item["id"],
            content=content,
            metadata={
                "sender": sender,
                "subject": subject,
                "thread_id": raw_item.get("thread_id"),
                "labels": labels,
                "timestamp": raw_item.get("timestamp"),
            },
            tags=["email"] + [f"label:{l.lower()}" for l in labels],
        )
