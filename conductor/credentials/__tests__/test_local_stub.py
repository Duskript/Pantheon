"""Tests for the LocalStubCredentialStore (plaintext JSON file).

This is the test reference behavior — every method on the ABC
should be exercised here. If a method works on the stub but fails
on the encrypted impl, the encrypted impl has a bug.

We use the `stub_store` fixture from conftest.py, which gives
each test a fresh tmp directory and a freshly-initialized
LocalStubCredentialStore. The store is closed in teardown.

Total: 28 tests organized into 7 test classes (Create, Get, List,
Update, Delete, Rotate, Persistence).
"""
from __future__ import annotations

import json
import time
import pytest
from pathlib import Path

from conductor.credentials import (
    Credential,
    CredentialAlreadyExistsError,
    CredentialError,
    CredentialNotFoundError,
    CredentialType,
    CredentialValidationError,
    LocalStubCredentialStore,
    RotationPolicy,
)


class TestCreate:
    """Tests for the create() method — happy path and validation."""

    def test_create_minimal(self, stub_store):
        # Minimum required fields: name, type, value. Everything
        # else is auto-generated.
        c = stub_store.create(
            name="sendgrid", type=CredentialType.API_KEY, plaintext_value="***"
        )
        assert isinstance(c, Credential)
        assert c.name == "sendgrid"
        assert c.type is CredentialType.API_KEY
        assert len(c.id) == 32  # UUID4 hex, no dashes
        assert c.created_at  # non-empty
        assert c.updated_at == c.created_at

    def test_create_with_metadata(self, stub_store):
        # Metadata is stored verbatim and round-trips through
        # to_dict() as a dict.
        c = stub_store.create(
            name="sendgrid",
            type=CredentialType.API_KEY,
            plaintext_value="***",
            metadata={"owner": "konan", "env": "test"},
        )
        assert c.metadata == {"owner": "konan", "env": "test"}

    def test_create_with_rotation_policy(self, stub_store):
        c = stub_store.create(
            name="sendgrid",
            type=CredentialType.API_KEY,
            plaintext_value="***",
            rotation_policy=RotationPolicy(interval_days=30),
        )
        assert c.rotation_policy.interval_days == 30

    def test_create_assigns_unique_ids(self, stub_store):
        # Each create should produce a fresh UUID4 id, even for
        # the same name shape.
        a = stub_store.create(name="a", type=CredentialType.API_KEY, plaintext_value="v")
        b = stub_store.create(name="b", type=CredentialType.API_KEY, plaintext_value="v")
        assert a.id != b.id

    def test_create_duplicate_name_raises(self, stub_store):
        # The name field is unique; a second create with the
        # same name should raise CredentialAlreadyExistsError.
        stub_store.create(name="dup", type=CredentialType.API_KEY, plaintext_value="v")
        with pytest.raises(CredentialAlreadyExistsError):
            stub_store.create(name="dup", type=CredentialType.API_KEY, plaintext_value="v")

    def test_create_empty_name_raises(self, stub_store):
        with pytest.raises(CredentialValidationError):
            stub_store.create(name="", type=CredentialType.API_KEY, plaintext_value="v")

    def test_create_empty_value_raises(self, stub_store):
        with pytest.raises(CredentialValidationError):
            stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="")

    def test_create_invalid_name_chars(self, stub_store):
        # Spaces and slashes are not allowed in the name field
        # because the SDK uses the name in URL paths.
        with pytest.raises(CredentialValidationError):
            stub_store.create(
                name="has space", type=CredentialType.API_KEY, plaintext_value="v"
            )
        with pytest.raises(CredentialValidationError):
            stub_store.create(
                name="slash/in/name", type=CredentialType.API_KEY, plaintext_value="v"
            )

    def test_create_too_long_name(self, stub_store):
        # 200 chars is over the 128-char limit.
        with pytest.raises(CredentialValidationError):
            stub_store.create(
                name="x" * 200, type=CredentialType.API_KEY, plaintext_value="v"
            )

    def test_create_reserved_name(self, stub_store):
        # '__all__' is reserved for bulk operations and must
        # not be usable as a real credential name.
        with pytest.raises(CredentialValidationError):
            stub_store.create(
                name="__all__", type=CredentialType.API_KEY, plaintext_value="v"
            )


class TestGet:
    """Tests for the get() / get_by_name() / get_value() methods."""

    def test_get_by_id(self, stub_store):
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        g = stub_store.get(c.id)
        assert g.id == c.id
        assert g.name == "x"

    def test_get_unknown_id_raises(self, stub_store):
        with pytest.raises(CredentialNotFoundError) as e:
            stub_store.get("nonexistent-id")
        assert e.value.by == "id"

    def test_get_by_name(self, stub_store):
        c = stub_store.create(name="lookupme", type=CredentialType.API_KEY, plaintext_value="v")
        g = stub_store.get_by_name("lookupme")
        assert g.id == c.id

    def test_get_by_name_unknown_raises(self, stub_store):
        with pytest.raises(CredentialNotFoundError) as e:
            stub_store.get_by_name("nope")
        assert e.value.by == "name"

    def test_get_value_returns_plaintext(self, stub_store):
        c = stub_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="the-actual-secret"
        )
        assert stub_store.get_value(c.id) == "the-actual-secret"

    def test_get_value_unknown_id_raises(self, stub_store):
        with pytest.raises(CredentialNotFoundError):
            stub_store.get_value("nonexistent")

    def test_get_value_bumps_last_used(self, stub_store):
        # Each get_value() should update last_used_at. The first
        # read sets it; the second read leaves a non-null value.
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        assert c.last_used_at is None
        stub_store.get_value(c.id)
        g = stub_store.get(c.id)
        assert g.last_used_at is not None
        assert g.last_used_at.endswith("Z")


class TestList:
    """Tests for the list() method — filtering and sorting."""

    def test_list_empty(self, stub_store):
        # An empty store returns an empty list, not None.
        assert stub_store.list() == []

    def test_list_all(self, stub_store):
        for n in ("a", "b", "c"):
            stub_store.create(name=n, type=CredentialType.API_KEY, plaintext_value="v")
        assert len(stub_store.list()) == 3

    def test_list_sorted_by_name(self, stub_store):
        # List output is sorted by name ascending — stable order
        # for the SDK's table view.
        for n in ("c", "a", "b"):
            stub_store.create(name=n, type=CredentialType.API_KEY, plaintext_value="v")
        names = [r.name for r in stub_store.list()]
        assert names == ["a", "b", "c"]

    def test_list_filter_by_type(self, stub_store):
        stub_store.create(name="k", type=CredentialType.API_KEY, plaintext_value="v")
        stub_store.create(name="u", type=CredentialType.DATABASE_URL, plaintext_value="v")
        api_only = stub_store.list(type=CredentialType.API_KEY)
        assert [r.name for r in api_only] == ["k"]
        db_only = stub_store.list(type=CredentialType.DATABASE_URL)
        assert [r.name for r in db_only] == ["u"]

    def test_list_filter_by_name_prefix(self, stub_store):
        stub_store.create(name="sendgrid-prod", type=CredentialType.API_KEY, plaintext_value="v")
        stub_store.create(name="sendgrid-staging", type=CredentialType.API_KEY, plaintext_value="v")
        stub_store.create(name="stripe-prod", type=CredentialType.API_KEY, plaintext_value="v")
        sg = stub_store.list(name_prefix="sendgrid")
        assert {r.name for r in sg} == {"sendgrid-prod", "sendgrid-staging"}


class TestUpdate:
    """Tests for the update() method — partial updates, validation, ts bumps."""

    def test_update_metadata_only(self, stub_store):
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        # Tiny sleep so the timestamps differ.
        time.sleep(0.01)
        u = stub_store.update(c.id, metadata={"new": "value"})
        assert u.metadata == {"new": "value"}
        assert u.updated_at > c.updated_at

    def test_update_value(self, stub_store):
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="old")
        stub_store.update(c.id, plaintext_value="new")
        assert stub_store.get_value(c.id) == "new"

    def test_update_rotation_policy(self, stub_store):
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        stub_store.update(c.id, rotation_policy=RotationPolicy(interval_days=90))
        g = stub_store.get(c.id)
        assert g.rotation_policy.interval_days == 90

    def test_update_unknown_id_raises(self, stub_store):
        with pytest.raises(CredentialNotFoundError):
            stub_store.update("nope", metadata={})


class TestDelete:
    """Tests for the delete() method — idempotency, get-after-delete."""

    def test_delete_removes(self, stub_store):
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        stub_store.delete(c.id)
        with pytest.raises(CredentialNotFoundError):
            stub_store.get(c.id)

    def test_delete_is_idempotent(self, stub_store):
        # The second delete is silent — matches REST DELETE
        # semantics and the spec's "idempotent" contract.
        c = stub_store.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        stub_store.delete(c.id)
        stub_store.delete(c.id)  # no error


class TestRotate:
    """Tests for the rotate() method — value swap + schedule advance."""

    def test_rotates_value(self, stub_store):
        c = stub_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="old",
            rotation_policy=RotationPolicy(interval_days=30),
        )
        stub_store.rotate(c.id, new_plaintext_value="new")
        assert stub_store.get_value(c.id) == "new"

    def test_advances_next_rotation(self, stub_store):
        # When a rotation policy has interval_days, rotating
        # should populate next_rotation_at with a date in the
        # future.
        c = stub_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="old",
            rotation_policy=RotationPolicy(interval_days=30),
        )
        assert c.rotation_policy.next_rotation_at is None
        stub_store.rotate(c.id, new_plaintext_value="new")
        g = stub_store.get(c.id)
        assert g.rotation_policy.next_rotation_at is not None

    def test_rotate_unknown_id_raises(self, stub_store):
        with pytest.raises(CredentialNotFoundError):
            stub_store.rotate("nope", new_plaintext_value="v")


class TestPersistence:
    """The stub persists across close/reopen — file durability."""

    def test_reload_after_close(self, tmp_dir):
        # We construct two store instances manually so we can
        # close the first one before opening the second. The
        # `stub_store` fixture only gives us one instance per test.
        path = tmp_dir / "creds.json"
        s1 = LocalStubCredentialStore(str(path))
        s1.initialize()
        c = s1.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        s1.close()
        s2 = LocalStubCredentialStore(str(path))
        s2.initialize()
        g = s2.get_by_name("x")
        assert g.id == c.id
        assert s2.get_value(g.id) == "v"
        s2.close()
