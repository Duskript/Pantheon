"""Tests for the Ichor Memory Engine Foundation Layer.

Tests the database schema, CRUD operations, FTS5 search,
and secret redaction safety module.
"""

import os
import tempfile
import pytest

from lib.ichor_db import IchorDB
from lib.ichor_safety import (
    has_likely_secret,
    sanitize_text,
    sanitize_json,
    SafetyConfig,
)


# ---------------------------------------------------------------------------
# IchorDB Tests
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> IchorDB:
    """Create an in-memory IchorDB for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_path = f.name
    ichor = IchorDB(db_path=tmp_path)
    ichor.connect()
    yield ichor
    ichor.close()
    os.unlink(tmp_path)


def test_insert_and_count(db: IchorDB) -> None:
    """Insert events and verify the count."""
    db.insert_event(
        session_id="ses-001",
        event_type="fact",
        subject="Athena",
        predicate="governs",
        object="wisdom",
        confidence=0.95,
        source="tier_a",
        raw_text="Athena governs wisdom and strategic warfare.",
        god_name="Zeus",
    )
    db.insert_event(
        session_id="ses-001",
        event_type="decision",
        subject="Zeus",
        predicate="decided",
        object="to summon council",
        raw_text="Zeus decided to summon the council of gods.",
        god_name="Zeus",
    )
    assert db.count() == 2


def test_query_by_session(db: IchorDB) -> None:
    """Query events by session ID."""
    db.insert_event(
        session_id="ses-abc",
        event_type="preference",
        subject="Hera",
        predicate="favors",
        object="marriage",
        god_name="Hera",
    )
    db.insert_event(
        session_id="ses-xyz",
        event_type="fact",
        subject="Poseidon",
        predicate="rules",
        object="seas",
        god_name="Poseidon",
    )
    results = db.query_by_session("ses-abc")
    assert len(results) == 1
    assert results[0]["subject"] == "Hera"


def test_query_by_type(db: IchorDB) -> None:
    """Filter events by type."""
    db.insert_event(session_id="s1", event_type="fact", subject="A")
    db.insert_event(session_id="s1", event_type="fact", subject="B")
    db.insert_event(session_id="s1", event_type="decision", subject="C")
    facts = db.query_by_type("fact")
    assert len(facts) == 2
    decisions = db.query_by_type("decision")
    assert len(decisions) == 1


def test_get_recent(db: IchorDB) -> None:
    """Get most recent events, ordered by created_at DESC."""
    db.insert_event(session_id="s1", event_type="fact", subject="First")
    db.insert_event(session_id="s1", event_type="fact", subject="Second")
    recent = db.get_recent(limit=1)
    assert len(recent) == 1
    assert recent[0]["subject"] == "Second"


def test_fts_search(db: IchorDB) -> None:
    """FTS5 full-text search returns matching events."""
    db.insert_event(
        session_id="s-fts",
        event_type="fact",
        subject="Hermes",
        predicate="is",
        object="messenger",
        raw_text="Hermes is the messenger of the gods.",
        god_name="Hermes",
    )
    db.insert_event(
        session_id="s-fts",
        event_type="fact",
        subject="Ares",
        predicate="is",
        object="war",
        raw_text="Ares is the god of war.",
        god_name="Ares",
    )
    results = db.query_fts("messenger")
    assert len(results) == 1
    assert results[0]["subject"] == "Hermes"

    results_war = db.query_fts("war")
    assert len(results_war) == 1
    assert results_war[0]["subject"] == "Ares"


def test_fts_no_results(db: IchorDB) -> None:
    """FTS5 returns empty list for non-matching queries."""
    db.insert_event(
        session_id="s-nomatch",
        event_type="fact",
        subject="Nothing",
        raw_text="No relevant content.",
    )
    results = db.query_fts("zzz_nonexistent_zzz")
    assert len(results) == 0


def test_event_type_constraint(db: IchorDB) -> None:
    """Inserting an invalid event_type raises IntegrityError."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        db.insert_event(session_id="bad", event_type="invalid_type", subject="X")


# ---------------------------------------------------------------------------
# Ichor Safety Tests
# ---------------------------------------------------------------------------


class TestHasLikelySecret:
    def test_bearer_token(self) -> None:
        assert has_likely_secret("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456")

    def test_api_key_sk(self) -> None:
        assert has_likely_secret("sk-proj-abcdefghijklmnopqrstuvwxyz123456")

    def test_private_key_pem(self) -> None:
        assert has_likely_secret(
            "-----BEGIN PRIVATE KEY-----\nABCDEF1234\n-----END PRIVATE KEY-----"
        )

    def test_ssh_private_key(self) -> None:
        assert has_likely_secret(
            "-----BEGIN OPENSSH PRIVATE KEY-----\nrandomdata\n-----END OPENSSH PRIVATE KEY-----"
        )

    def test_jwt_token(self) -> None:
        assert has_likely_secret(
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jNf7YgOQ"
        )

    def test_aws_access_key(self) -> None:
        assert has_likely_secret("AKIAIOSFODNN7EXAMPLE")

    def test_github_token(self) -> None:
        assert has_likely_secret("ghp_abcdefghijklmnopqrstuvwxyz1234567890")

    def test_plain_text_has_no_secret(self) -> None:
        assert not has_likely_secret("The quick brown fox jumps over the lazy dog.")

    def test_slack_token(self) -> None:
        assert has_likely_secret("xoxb-1234567890-1234567890123-abcdefghijk")


class TestSanitizeText:
    def test_redacts_bearer_token(self) -> None:
        text = "Header: Bearer abcdefghijklmnopqrstuvwxyz123456"
        sanitized, report = sanitize_text(text)
        assert "[REDACTED]" in sanitized
        assert "abcdefghijklmnopqrstuvwxyz123456" not in sanitized
        assert len(report) >= 1

    def test_redacts_private_key(self) -> None:
        text = "Key:\n-----BEGIN PRIVATE KEY-----\nABCDEF\n-----END PRIVATE KEY-----"
        sanitized, report = sanitize_text(text)
        assert "[REDACTED]" in sanitized
        assert "ABCDEF" not in sanitized
        assert any(r["count"] > 0 for r in report)

    def test_clean_text_unchanged(self) -> None:
        text = "Just a regular conversation about mythology."
        sanitized, report = sanitize_text(text)
        assert sanitized == text
        assert report == []

    def test_multiple_redactions(self) -> None:
        text = (
            "Token: sk-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz\n"
            "Also: Bearer 1234567890abcdef1234567890abcdef12345678"
        )
        sanitized, report = sanitize_text(text)
        assert sanitized.count("[REDACTED]") >= 2
        assert len(report) >= 2


class TestSanitizeJson:
    def test_redacts_secret_values(self) -> None:
        data = {
            "name": "Athena",
            "credentials": "Bearer sk-abcdefghijklmnopqrstuvwxyz123456",
            "role": "goddess",
        }
        sanitized, report = sanitize_json(data)
        assert sanitized["name"] == "Athena"
        assert sanitized["credentials"] == "[REDACTED]"
        assert sanitized["role"] == "goddess"
        assert len(report) >= 1

    def test_redacts_sensitive_keys(self) -> None:
        data = {
            "api_key": "sk-abcdefghijklmnopqrstuvwxyz123456",
            "password": "supersecret123",
            "username": "athena",
        }
        sanitized, report = sanitize_json(data)
        assert sanitized["api_key"] == "[REDACTED]"
        assert sanitized["password"] == "[REDACTED]"
        assert sanitized["username"] == "athena"
        assert len(report) == 2

    def test_nested_json_redaction(self) -> None:
        data = {
            "god": "Zeus",
            "config": {
                "token": "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
                "settings": {"level": 5},
            },
            "list_data": [
                "safe text",
                "Bearer abcdefghijklmnopqrstuvwxyz12345678",
            ],
        }
        sanitized, report = sanitize_json(data)
        assert sanitized["god"] == "Zeus"
        assert sanitized["config"]["token"] == "[REDACTED]"
        assert sanitized["config"]["settings"]["level"] == 5
        assert "[REDACTED]" in sanitized["list_data"][1]
        assert len(report) >= 2

    def test_clean_json_unchanged(self) -> None:
        data = {
            "god": "Athena",
            "domain": "wisdom",
            "children": ["craft", "strategy"],
        }
        sanitized, report = sanitize_json(data)
        assert sanitized == data
        assert report == []


class TestSafetyConfig:
    def test_add_pattern(self) -> None:
        config = SafetyConfig([])
        config.add_pattern("my_secret", r"MY_SECRET_\d+")
        assert len(config.patterns) == 1
        assert config.patterns[0]["name"] == "my_secret"

    def test_remove_pattern(self) -> None:
        config = SafetyConfig()
        before = len(config.patterns)
        config.remove_pattern("jwt_token")
        assert len(config.patterns) == before - 1

    def test_custom_patterns_work(self) -> None:
        from lib.ichor_safety import configure

        config = SafetyConfig([
            {"name": "custom_key", "pattern": __import__("re").compile(r"CUSTOM_KEY_\w+")},
        ])
        configure(config)
        try:
            assert has_likely_secret("CUSTOM_KEY_xyz")
            assert not has_likely_secret("Bearer something")
        finally:
            # Restore default config
            configure(SafetyConfig())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
