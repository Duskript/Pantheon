"""Tests for the credential domain types (types.py).

Covers Credential, CredentialType, RotationPolicy, and the four
exception classes. These tests don't touch a backing store — they
exercise pure-Python data shapes.

Total: 16 tests.
"""
from __future__ import annotations

import json
import pytest
from datetime import datetime, timezone

from conductor.credentials.types import (
    Credential,
    CredentialAlreadyExistsError,
    CredentialError,
    CredentialNotFoundError,
    CredentialStoreLockedError,
    CredentialType,
    CredentialValidationError,
    RotationPolicy,
    _utcnow_iso,
    _parse_iso,
)


class TestCredentialType:
    """CredentialType enum behavior."""

    def test_values_are_lowercase_strings(self):
        # All members should be lowercased with underscores, and
        # inherit from `str` so JSON serialization is natural.
        for member in CredentialType:
            assert member.value == member.value.lower()
            assert isinstance(member, str)

    def test_seven_kinds(self):
        # The seven supported types — adding an 8th is a deliberate
        # contract change, not a typo.
        kinds = {m.value for m in CredentialType}
        assert kinds == {
            "api_key", "oauth2", "basic_auth", "bearer_token",
            "database_url", "webhook_secret", "custom_json",
        }

    def test_lookup_by_value(self):
        # The CredentialType(string) lookup is used by the
        # encrypted store's deserializer (which reads string-typed
        # rows from sqlite).
        assert CredentialType("api_key") is CredentialType.API_KEY
        assert CredentialType("oauth2") is CredentialType.OAUTH2

    def test_unknown_value_raises(self):
        with pytest.raises(ValueError):
            CredentialType("not_a_real_type")


class TestRotationPolicy:
    """RotationPolicy dataclass — JSON roundtrip and defaults."""

    def test_defaults(self):
        p = RotationPolicy()
        assert p.interval_days is None
        assert p.next_rotation_at is None
        assert p.notify_before_days == 7

    def test_to_json_roundtrip(self):
        p = RotationPolicy(interval_days=30, next_rotation_at="2026-12-01T00:00:00Z")
        d = json.loads(p.to_json())
        assert d["interval_days"] == 30
        assert d["next_rotation_at"] == "2026-12-01T00:00:00Z"
        assert d["notify_before_days"] == 7
        # Round-trip
        p2 = RotationPolicy.from_json(p.to_json())
        assert p2.interval_days == 30
        assert p2.next_rotation_at == "2026-12-01T00:00:00Z"

    def test_from_json_empty(self):
        # An empty/None policy string is treated as 'no rotation'.
        assert RotationPolicy.from_json("").interval_days is None
        assert RotationPolicy.from_json(None).interval_days is None

    def test_from_json_invalid(self):
        with pytest.raises(ValueError):
            RotationPolicy.from_json("not json")

    def test_from_json_wrong_shape(self):
        with pytest.raises(ValueError):
            # Lists are not valid policy shapes.
            RotationPolicy.from_json("[]")


class TestCredential:
    """Credential dataclass — to_dict/from_row serialization."""

    def _sample(self, **kwargs):
        defaults = dict(
            id="abc123",
            name="sendgrid",
            type=CredentialType.API_KEY,
            value="opaque-blob",
        )
        defaults.update(kwargs)
        return Credential(**defaults)

    def test_to_dict_omits_value_by_default(self):
        c = self._sample()
        d = c.to_dict()
        assert "value" not in d
        assert d["name"] == "sendgrid"
        assert d["type"] == "api_key"

    def test_to_dict_includes_value_when_requested(self):
        c = self._sample()
        d = c.to_dict(include_value=True)
        assert d["value"] == "opaque-blob"

    def test_from_row_happy_path(self):
        c = Credential.from_row(
            id="x",
            name="y",
            type="api_key",
            value="blob",
            metadata_json='{"a": 1}',
            created_at="2026-06-22T00:00:00Z",
            updated_at="2026-06-22T00:00:00Z",
            last_used_at=None,
            rotation_policy_json="{}",
        )
        assert c.name == "y"
        assert c.type is CredentialType.API_KEY
        assert c.metadata == {"a": 1}
        assert c.last_used_at is None

    def test_from_row_unknown_type_falls_back(self):
        # An unknown type should NOT crash — we degrade to
        # CUSTOM_JSON so the operator can clean up.
        c = Credential.from_row(
            id="x", name="y", type="future_type_we_dont_know",
            value="blob", metadata_json="{}",
            created_at="", updated_at="",
            last_used_at=None, rotation_policy_json="{}",
        )
        assert c.type is CredentialType.CUSTOM_JSON

    def test_from_row_corrupted_metadata(self):
        c = Credential.from_row(
            id="x", name="y", type="api_key", value="blob",
            metadata_json="not json",
            created_at="", updated_at="",
            last_used_at=None, rotation_policy_json="{}",
        )
        # We mark the corruption but don't raise.
        assert c.metadata.get("__corrupted_metadata") is True

    def test_to_dict_includes_rotation_policy_as_dict(self):
        c = self._sample()
        c.rotation_policy = RotationPolicy(interval_days=90)
        d = c.to_dict()
        assert d["rotation_policy"] == {"interval_days": 90, "next_rotation_at": None, "notify_before_days": 7}


class TestTimestampHelpers:
    """The _utcnow_iso / _parse_iso helpers used for `created_at` etc."""

    def test_utcnow_iso_format(self):
        ts = _utcnow_iso()
        # Must end in 'Z' (Zulu), per spec
        assert ts.endswith("Z")
        # Must be parseable back
        dt = _parse_iso(ts)
        assert dt.tzinfo is not None
        assert dt.year >= 2026

    def test_parse_iso_with_z_suffix(self):
        dt = _parse_iso("2026-06-22T15:30:00Z")
        assert dt.year == 2026 and dt.month == 6 and dt.day == 22
        assert dt.hour == 15 and dt.minute == 30

    def test_parse_iso_with_offset(self):
        dt = _parse_iso("2026-06-22T15:30:00+00:00")
        assert dt.year == 2026


class TestExceptionHierarchy:
    """All credential errors should share a common base for catch-all."""

    def test_base_class(self):
        assert issubclass(CredentialNotFoundError, CredentialError)
        assert issubclass(CredentialAlreadyExistsError, CredentialError)
        assert issubclass(CredentialValidationError, CredentialError)
        assert issubclass(CredentialStoreLockedError, CredentialError)

    def test_catch_all(self):
        # Operators should be able to `except CredentialError:` to
        # catch anything credential-related.
        for exc_cls in (
            CredentialNotFoundError,
            CredentialAlreadyExistsError,
            CredentialValidationError,
            CredentialStoreLockedError,
        ):
            try:
                raise exc_cls("test")
            except CredentialError as e:
                assert "test" in str(e)
