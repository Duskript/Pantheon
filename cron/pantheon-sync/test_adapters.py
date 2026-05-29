"""Tests for Pantheon sync adapters."""

import sys
import pytest

sys.path.insert(0, ".")
from adapters import list_adapters, get_adapter
from adapters.base import SyncRecord, SyncResult


def test_all_adapters_registered():
    """All 8 adapters should be importable and registered."""
    names = list_adapters()
    assert len(names) == 8, f"Expected 8 adapters, got {len(names)}: {names}"
    expected = {
        "discord", "github", "gmail", "google_calendar",
        "microsoft_teams", "notion", "outlook", "slack",
    }
    assert set(names) == expected


def test_adapter_creation():
    """All adapters should instantiate without error."""
    for name in list_adapters():
        adapter = get_adapter(name)
        assert adapter.provider == name


def test_sync_without_auth():
    """Adapters should return no_auth when no Composio key is configured."""
    for name in list_adapters():
        adapter = get_adapter(name)
        result = adapter.sync({})
        assert isinstance(result, SyncResult)
        assert result.status in ("no_auth", "not_connected", "empty")
        assert result.records == []


def test_gmail_canonicalize():
    adapter = get_adapter("gmail")
    record = adapter.canonicalize({
        "id": "msg_001",
        "from": "alice@example.com",
        "subject": "Test Email",
        "body": "Hello world",
        "labels": ["INBOX", "IMPORTANT"],
    })
    assert isinstance(record, SyncRecord)
    assert record.provider == "gmail"
    assert "Test Email" in record.content
    assert "alice@example.com" in record.content
    assert "email" in record.tags
    assert "gmail" in record.tags


def test_github_canonicalize():
    adapter = get_adapter("github")
    record = adapter.canonicalize({
        "id": "evt_001",
        "type": "PushEvent",
        "repo": {"name": "konan/pantheon-core"},
        "actor": {"login": "konan"},
        "payload": {},
        "created_at": "2026-01-01T00:00:00Z",
    })
    assert record.provider == "github"
    assert "konan/pantheon-core" in record.content
    assert "code" in record.tags
    assert "github" in record.tags


def test_slack_canonicalize():
    adapter = get_adapter("slack")
    record = adapter.canonicalize({
        "id": "slk_001",
        "user": "konan",
        "channel": "pantheon-dev",
        "text": "Stream A done!",
        "ts": "12345.67890",
    })
    assert record.provider == "slack"
    assert "konan" in record.content
    assert "Stream A done" in record.content
    assert "chat" in record.tags


def test_calendar_canonicalize():
    adapter = get_adapter("google_calendar")
    record = adapter.canonicalize({
        "id": "cal_001",
        "summary": "Q3 Planning",
        "start": {"dateTime": "2026-07-01T10:00:00"},
        "end": {"dateTime": "2026-07-01T11:00:00"},
        "attendees": [{"email": "alice@corp.com"}, {"email": "bob@corp.com"}],
    })
    assert record.provider == "google_calendar"
    assert "Q3 Planning" in record.content
    assert "alice@corp.com" in record.content
    assert "calendar" in record.tags


def test_outlook_canonicalize():
    adapter = get_adapter("outlook")
    record = adapter.canonicalize({
        "id": "out_001",
        "from": {"emailAddress": {"address": "boss@corp.com"}},
        "subject": "Budget Review",
        "body": {"content": "Please review..."},
    })
    assert record.provider == "outlook"
    assert "Budget Review" in record.content
    assert "boss@corp.com" in record.content
    assert "email" in record.tags


def test_teams_canonicalize():
    adapter = get_adapter("microsoft_teams")
    record = adapter.canonicalize({
        "id": "tm_001",
        "from": {"user": {"displayName": "Alice"}},
        "channelIdentity": {"channelName": "Engineering"},
        "body": {"content": "Deploy complete"},
    })
    assert record.provider == "microsoft_teams"
    assert "Alice" in record.content
    assert "Engineering" in record.content
    assert "chat" in record.tags


def test_notion_canonicalize():
    adapter = get_adapter("notion")
    record = adapter.canonicalize({
        "id": "not_001",
        "properties": {"title": {"title": [{"plain_text": "Architecture"}]}},
        "url": "https://notion.so/arch",
        "last_edited_time": "2026-01-01",
    })
    assert record.provider == "notion"
    assert "Architecture" in record.content
    assert "docs" in record.tags
    assert "notion" in record.tags


def test_discord_canonicalize():
    adapter = get_adapter("discord")
    record = adapter.canonicalize({
        "id": "dsc_001",
        "author": {"username": "game_dev"},
        "channel_id": "999888777",
        "content": "Fixed the rendering bug!",
    })
    assert record.provider == "discord"
    assert "game_dev" in record.content
    assert "Fixed the rendering bug" in record.content
    assert "discord" in record.tags
