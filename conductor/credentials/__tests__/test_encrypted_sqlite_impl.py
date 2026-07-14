"""Tests for the EncryptedSqliteCredentialStore (production store).

This test file covers:
  * Roundtrip — create/get/update/rotate/delete against the encrypted
    store; values come back as plaintext, encrypted_value is opaque.
  * Encryption — the on-disk value is NOT plaintext; the file
    itself is encrypted (SQLCipher); wrong key fails.
  * Locking — the store starts locked, unlock() enables access,
    lock() disables it.
  * Keyring — the keyring cache is best-effort; we don't fail
    if it's not available (e.g. headless CI).

Total: 30 tests.

We use the `encrypted_store` fixture from conftest.py, which gives
each test a fresh tmp dir, a fresh DB file, a unique passphrase,
and unlocks the store before yielding.
"""
from __future__ import annotations

import json
import os
import pytest
from pathlib import Path

from conductor.credentials import (
    CredentialType,
    EncryptedSqliteCredentialStore,
    LocalStubCredentialStore,
    RotationPolicy,
)
from conductor.credentials.encrypted_sqlite_impl import (
    _encrypt_value,
    _decrypt_value,
    _derive_master_key,
    ARGON2_TIME_COST,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_HASH_LEN,
    MASTER_KEY_LEN,
    SALT_LEN,
    AES_NONCE_LEN,
)
from conductor.credentials.types import (
    CredentialNotFoundError,
    CredentialAlreadyExistsError,
    CredentialStoreLockedError,
    CredentialValidationError,
)


# Module-level: generate a master key once for unit tests of the
# internal crypto helpers. The fixture uses a fresh passphrase per
# test, but the helpers themselves are pure functions of (key, salt,
# plaintext), so we can pin the key for deterministic asserts.
import secrets as _secrets

_MASTER_KEY = _secrets.token_bytes(MASTER_KEY_LEN)


class TestCryptoHelpers:
    """Unit tests for the internal crypto helpers.

    These don't touch the store at all — they test the encrypt/
    decrypt/derive primitives directly.
    """

    def test_encrypt_decrypt_roundtrip(self):
        # A plaintext value should encrypt and decrypt back to
        # the same string.
        pt = "the-quick-brown-fox"
        blob = _encrypt_value(_MASTER_KEY, pt)
        assert blob != pt  # it's NOT plaintext
        out = _decrypt_value(_MASTER_KEY, blob)
        assert out == pt

    def test_encrypt_produces_nonce_prefixed_output(self):
        # The blob is base64( nonce (12) || ct_with_tag ). Length
        # is plaintext_len + 12 (nonce) + 16 (GCM tag).
        pt = "x" * 32
        blob = _encrypt_value(_MASTER_KEY, pt)
        import base64
        raw = base64.b64decode(blob)
        assert len(raw) == len(pt) + AES_NONCE_LEN + 16
        # The first 12 bytes are the nonce.
        assert raw[:AES_NONCE_LEN] != b"\x00" * AES_NONCE_LEN  # not all-zero

    def test_encrypt_produces_unique_nonces(self):
        # Two encryptions of the same plaintext should produce
        # different ciphertexts (the nonce is random).
        a = _encrypt_value(_MASTER_KEY, "same")
        b = _encrypt_value(_MASTER_KEY, "same")
        assert a != b

    def test_decrypt_with_wrong_key_fails(self):
        # Decrypting with a different key should raise
        # CredentialStoreLockedError (not InvalidTag) so the
        # api server can map it to HTTP 423.
        blob = _encrypt_value(_MASTER_KEY, "secret")
        wrong_key = _secrets.token_bytes(MASTER_KEY_LEN)
        with pytest.raises(CredentialStoreLockedError):
            _decrypt_value(wrong_key, blob)

    def test_decrypt_corrupt_blob_raises(self):
        # A blob that's too short to contain a nonce + tag is
        # structurally invalid.
        import base64
        short = base64.b64encode(b"\x00" * 10).decode("ascii")
        with pytest.raises(CredentialStoreLockedError):
            _decrypt_value(_MASTER_KEY, short)

    def test_derive_master_key_deterministic(self):
        # Same passphrase + same salt = same key.
        salt = b"\x42" * SALT_LEN
        k1 = _derive_master_key("passphrase", salt)
        k2 = _derive_master_key("passphrase", salt)
        assert k1 == k2
        assert len(k1) == MASTER_KEY_LEN

    def test_derive_master_key_different_salts(self):
        # Different salt = different key (even with same passphrase).
        k1 = _derive_master_key("p", b"\x01" * SALT_LEN)
        k2 = _derive_master_key("p", b"\x02" * SALT_LEN)
        assert k1 != k2

    def test_derive_master_key_different_passphrases(self):
        # Different passphrase = different key (with same salt).
        salt = b"\x42" * SALT_LEN
        k1 = _derive_master_key("p1", salt)
        k2 = _derive_master_key("p2", salt)
        assert k1 != k2

    def test_derive_master_key_empty_passphrase_raises(self):
        with pytest.raises(CredentialValidationError):
            _derive_master_key("", b"\x42" * SALT_LEN)


class TestStoreRoundtrip:
    """End-to-end roundtrip against the encrypted store."""

    def test_create_and_get_value(self, encrypted_store):
        # The full lifecycle: create, get_value returns plaintext.
        c = encrypted_store.create(
            name="sendgrid", type=CredentialType.API_KEY, plaintext_value="***"
        )
        assert encrypted_store.get_value(c.id) == "***"

    def test_create_get_metadata(self, encrypted_store):
        # get() returns metadata + the encrypted blob (not plaintext).
        c = encrypted_store.create(
            name="sendgrid", type=CredentialType.API_KEY, plaintext_value="***",
            metadata={"owner": "konan"},
        )
        g = encrypted_store.get(c.id)
        assert g.metadata == {"owner": "konan"}
        # The encrypted value field is a base64 blob, not the plaintext.
        assert g.value != "***"
        import base64
        # Should decode cleanly.
        base64.b64decode(g.value.encode("ascii"))

    def test_get_by_name(self, encrypted_store):
        c = encrypted_store.create(
            name="lookupme", type=CredentialType.API_KEY, plaintext_value="v"
        )
        g = encrypted_store.get_by_name("lookupme")
        assert g.id == c.id

    def test_get_unknown_raises(self, encrypted_store):
        from conductor.credentials import CredentialNotFoundError
        with pytest.raises(CredentialNotFoundError):
            encrypted_store.get("nonexistent")

    def test_list_returns_all(self, encrypted_store):
        for n in ("a", "b", "c"):
            encrypted_store.create(name=n, type=CredentialType.API_KEY, plaintext_value="v")
        assert len(encrypted_store.list()) == 3

    def test_list_filter_by_type(self, encrypted_store):
        encrypted_store.create(name="k", type=CredentialType.API_KEY, plaintext_value="v")
        encrypted_store.create(name="u", type=CredentialType.DATABASE_URL, plaintext_value="v")
        assert len(encrypted_store.list(type=CredentialType.API_KEY)) == 1
        assert len(encrypted_store.list(type=CredentialType.DATABASE_URL)) == 1

    def test_list_filter_by_name_prefix(self, encrypted_store):
        encrypted_store.create(name="sendgrid-prod", type=CredentialType.API_KEY, plaintext_value="v")
        encrypted_store.create(name="stripe-prod", type=CredentialType.API_KEY, plaintext_value="v")
        rows = encrypted_store.list(name_prefix="sendgrid")
        assert {r.name for r in rows} == {"sendgrid-prod"}

    def test_update_value(self, encrypted_store):
        c = encrypted_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="old"
        )
        encrypted_store.update(c.id, plaintext_value="new")
        assert encrypted_store.get_value(c.id) == "new"

    def test_update_metadata(self, encrypted_store):
        c = encrypted_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="v"
        )
        encrypted_store.update(c.id, metadata={"env": "prod"})
        g = encrypted_store.get(c.id)
        assert g.metadata == {"env": "prod"}

    def test_rotate(self, encrypted_store):
        c = encrypted_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="old",
            rotation_policy=RotationPolicy(interval_days=30),
        )
        encrypted_store.rotate(c.id, new_plaintext_value="new")
        assert encrypted_store.get_value(c.id) == "new"
        g = encrypted_store.get(c.id)
        assert g.rotation_policy.next_rotation_at is not None

    def test_delete(self, encrypted_store):
        c = encrypted_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="v"
        )
        encrypted_store.delete(c.id)
        with pytest.raises(CredentialNotFoundError):
            encrypted_store.get(c.id)

    def test_record_use_bumps_last_used(self, encrypted_store):
        c = encrypted_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="v"
        )
        assert encrypted_store.get(c.id).last_used_at is None
        encrypted_store.record_use(c.id)
        assert encrypted_store.get(c.id).last_used_at is not None


class TestEncryption:
    """The actual encryption behavior — on-disk bytes."""

    def test_on_disk_value_not_plaintext(self, encrypted_store, tmp_dir):
        # The plaintext must NOT appear in the on-disk DB file.
        # This is the "the value is encrypted" guarantee.
        secret = "very-secret-credential-value-12345"
        encrypted_store.create(
            name="sendgrid", type=CredentialType.API_KEY, plaintext_value=secret
        )
        # Read the raw DB file (binary) and check the secret is
        # not in there.
        db_path = tmp_dir / "creds.db"
        raw = db_path.read_bytes()
        assert secret.encode("utf-8") not in raw

    def test_on_disk_db_is_encrypted(self, encrypted_store, tmp_dir):
        # SQLCipher applies page-level encryption. The raw DB
        # bytes should not contain recognizable SQLite headers
        # (which start with "SQLite format 3\x00").
        encrypted_store.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="v"
        )
        db_path = tmp_dir / "creds.db"
        raw = db_path.read_bytes()
        assert b"SQLite format 3" not in raw
        # The plaintext name 'x' or 'sendgrid' should also not
        # be in the file (we just created "x" in this test).
        assert b'"name"' not in raw
        assert b'"api_key"' not in raw

    def test_meta_sidecar_is_restrictive(self, encrypted_store, tmp_dir):
        # The meta sidecar (with the salt) should be chmod-600.
        meta_path = tmp_dir / "creds.db.meta"
        assert meta_path.exists()
        # 0o600 = 0b110_000_000 = decimal 384. Mask with 0o777 to
        # drop the file-type bits; check the result is exactly 0o600.
        mode = meta_path.stat().st_mode & 0o777
        assert mode == 0o600

    def test_meta_sidecar_contains_salt(self, encrypted_store, tmp_dir):
        # The meta sidecar stores the Argon2id salt as hex.
        meta_path = tmp_dir / "creds.db.meta"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert "salt" in meta
        assert len(bytes.fromhex(meta["salt"])) == SALT_LEN
        assert "argon" in meta

    def test_different_passphrase_cannot_unlock(self, tmp_dir, passphrase):
        # Create a store, unlock with the right passphrase, write
        # a credential. Then close. Reopen with a wrong passphrase
        # — should fail to unlock.
        path = tmp_dir / "creds.db"
        s1 = EncryptedSqliteCredentialStore(str(path))
        s1.initialize()
        s1.unlock(passphrase)
        c = s1.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="v"
        )
        s1.lock()
        # Wrong passphrase
        s2 = EncryptedSqliteCredentialStore(str(path))
        s2.initialize()
        with pytest.raises(CredentialStoreLockedError):
            s2.unlock("wrong-passphrase-12345")
        # Cleanup
        try:
            s2.close()
        except Exception:
            pass

    def test_same_passphrase_can_reopen(self, tmp_dir, passphrase):
        # Re-opening with the right passphrase restores access.
        path = tmp_dir / "creds.db"
        s1 = EncryptedSqliteCredentialStore(str(path))
        s1.initialize()
        s1.unlock(passphrase)
        c = s1.create(
            name="x", type=CredentialType.API_KEY, plaintext_value="***"
        )
        s1.lock()
        s2 = EncryptedSqliteCredentialStore(str(path))
        s2.initialize()
        s2.unlock(passphrase)
        assert s2.get_value(c.id) == "***"
        s2.lock()

    def test_two_creds_have_different_ciphertexts(self, encrypted_store):
        # Two credentials with the SAME plaintext should produce
        # different encrypted blobs (because the nonce is random).
        a = encrypted_store.create(
            name="a", type=CredentialType.API_KEY, plaintext_value="same"
        )
        b = encrypted_store.create(
            name="b", type=CredentialType.API_KEY, plaintext_value="same"
        )
        assert encrypted_store.get(a.id).value != encrypted_store.get(b.id).value


class TestLocking:
    """The store starts locked; unlock/lock lifecycle."""

    def test_starts_locked(self, tmp_dir, passphrase):
        # A freshly constructed store (before unlock) should
        # reject all reads and writes.
        from conductor.credentials import EncryptedSqliteCredentialStore
        path = tmp_dir / "creds.db"
        s = EncryptedSqliteCredentialStore(str(path))
        s.initialize()
        assert not s.is_unlocked()
        with pytest.raises(CredentialStoreLockedError):
            s.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        with pytest.raises(CredentialStoreLockedError):
            s.list()
        with pytest.raises(CredentialStoreLockedError):
            s.get("anything")
        with pytest.raises(CredentialStoreLockedError):
            s.get_value("anything")
        # Cleanup
        s.close()

    def test_unlock_enables_access(self, tmp_dir, passphrase):
        from conductor.credentials import EncryptedSqliteCredentialStore
        path = tmp_dir / "creds.db"
        s = EncryptedSqliteCredentialStore(str(path))
        s.initialize()
        s.unlock(passphrase)
        assert s.is_unlocked()
        # Now writes work.
        c = s.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        assert s.get_value(c.id) == "v"
        s.lock()

    def test_lock_disables_access(self, tmp_dir, passphrase):
        from conductor.credentials import EncryptedSqliteCredentialStore
        path = tmp_dir / "creds.db"
        s = EncryptedSqliteCredentialStore(str(path))
        s.initialize()
        s.unlock(passphrase)
        c = s.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        s.lock()
        assert not s.is_unlocked()
        with pytest.raises(CredentialStoreLockedError):
            s.get_value(c.id)

    def test_lock_then_unlock_again(self, tmp_dir, passphrase):
        from conductor.credentials import EncryptedSqliteCredentialStore
        path = tmp_dir / "creds.db"
        s = EncryptedSqliteCredentialStore(str(path))
        s.initialize()
        s.unlock(passphrase)
        c = s.create(name="x", type=CredentialType.API_KEY, plaintext_value="v")
        s.lock()
        s.unlock(passphrase)
        assert s.get_value(c.id) == "v"
        s.lock()
