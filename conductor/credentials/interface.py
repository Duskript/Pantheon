"""Credential store abstract interface.

Defines the contract every credential store implementation must satisfy.
There are two implementations:

  * ``local_stub.LocalStubCredentialStore`` — JSON-file backed, used
    by tests. Plaintext on disk, no encryption. Fast, no dependencies.

  * ``encrypted_sqlite_impl.EncryptedSqliteCredentialStore`` — the
    production implementation. SQLCipher (AES-256 page-level) +
    application-level AES-256-GCM on the value column, key derived
    from operator passphrase via Argon2id. Keyring-cached or
    chmod-600-file fallback for headless deployments.

Both implementations pass the same set of behavior tests because they
implement this ABC. The REST endpoints in ``v2/api_server.py`` are
parameterized on the store, not on a specific implementation.

Why an ABC and not a Protocol
-----------------------------
The store is on the hot path of workflow execution — we want type
errors at the call site when a method is missing, not a runtime
AttributeError. ABCs give us that for free. A Protocol would also
work, but ABCs let us share a default ``__repr__`` and a few shared
helpers (like ``_now()``) without each implementation reinventing
them.

What the store does NOT do
--------------------------
* It does NOT transport the value over the wire. That's the api
  server's job. The store is local-only.
* It does NOT enforce access control (e.g. which operator can read
  which credential). The api server's auth layer handles that.
* It does NOT call out to the credential target (e.g. "test the
  connection"). The api server's POST /test endpoint does that
  using the credential's resolved value, not via the store.
"""
from __future__ import annotations

import abc
import uuid
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from .types import (
    Credential,
    CredentialAlreadyExistsError,
    CredentialError,
    CredentialNotFoundError,
    CredentialStoreLockedError,
    CredentialType,
    CredentialValidationError,
    RotationPolicy,
)


def _now() -> str:
    """Current UTC time as 'YYYY-MM-DDTHH:MM:SS.ffffffZ' string.

    Used by the store for `created_at`/`updated_at` stamping. Centralized
    here so both implementations return identical timestamp formats.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_name(name: str) -> None:
    """Name validator — shared by every implementation.

    Rules:
      * Non-empty
      * Length 1-128
      * No leading/trailing whitespace
      * ASCII alphanumeric + ``_``, ``-``, ``.``, ``:``
      * Reserved names ``__all__`` and ``*`` are rejected (used by
        the API for bulk operations, not for real credentials).
    """
    if not isinstance(name, str):
        raise CredentialValidationError(f"name must be a string, got {type(name).__name__}")
    if not name:
        raise CredentialValidationError("name must not be empty")
    if len(name) > 128:
        raise CredentialValidationError(f"name too long ({len(name)} > 128 chars)")
    if name != name.strip():
        raise CredentialValidationError("name must not have leading/trailing whitespace")
    if name in ("__all__", "*"):
        raise CredentialValidationError(f"name {name!r} is reserved")
    bad = set(name) - set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789_-.:"
    )
    if bad:
        raise CredentialValidationError(
            f"name {name!r} contains invalid characters: {sorted(bad)}"
        )


class CredentialStore(abc.ABC):
    """Abstract base for credential stores.

    A store holds credential records and supports the basic CRUD
    operations the REST endpoints need. Implementations may add
    extra methods (e.g. the encrypted impl has ``unlock()``); those
    are NOT part of the interface — they're called by the api
    server's bind/handler code, not via this ABC.

    Lifecycle
    ---------
    1. Construct with a path (and, for the encrypted impl, a passphrase
       or a callback that produces one).
    2. Call ``initialize()`` once to create the schema/tables.
    3. Use the CRUD methods. Reads and lists are always allowed; writes
       require the store to be ``unlocked`` (only the encrypted impl
       enforces this — the stub allows all writes).
    4. ``close()`` releases the underlying resources (DB connection,
       file handle, keyring handle).
    """

    def __init__(self, path: str) -> None:
        self._path = path

    # ----- Lifecycle (overridable) -----

    def initialize(self) -> None:
        """Set up the store (create tables, write headers, etc.).

        Idempotent — calling it on an already-initialized store is a
        no-op. The encrypted impl also verifies the key here (so a
        wrong passphrase fails fast at startup, not on first read).
        """

    def close(self) -> None:
        """Release resources. Subclasses must call ``super().close()``."""

    # ----- CRUD -----

    @abc.abstractmethod
    def create(
        self,
        *,
        name: str,
        type: CredentialType,
        plaintext_value: str,
        metadata: Optional[dict[str, Any]] = None,
        rotation_policy: Optional[RotationPolicy] = None,
    ) -> Credential:
        """Create a new credential.

        Args:
            name: Unique name. Validated; raises
                ``CredentialValidationError`` on bad input.
            type: The credential kind.
            plaintext_value: The secret, in plaintext. The store
                encrypts this before persisting. The returned
                ``Credential`` has the encrypted blob in ``value``.
            metadata: Optional unencrypted metadata dict. Default {}.
            rotation_policy: Optional rotation policy. Default = none.

        Returns:
            The new ``Credential`` (with encrypted ``value``).

        Raises:
            CredentialValidationError: Name is bad or plaintext is empty.
            CredentialAlreadyExistsError: A credential with this name exists.
            CredentialStoreLockedError: The store is locked (encrypted impl).
        """

    @abc.abstractmethod
    def get(self, credential_id: str) -> Credential:
        """Read a credential by id (metadata only, value is encrypted).

        Raises:
            CredentialNotFoundError: No row with this id.
        """

    @abc.abstractmethod
    def get_by_name(self, name: str) -> Credential:
        """Read a credential by name (metadata only, value is encrypted)."""

    @abc.abstractmethod
    def get_value(self, credential_id: str) -> str:
        """Read the DECRYPTED value.

        Returns the plaintext value. This is the only method that
        touches the decrypted secret — every other read returns
        metadata only.

        For audit purposes, the store also bumps ``last_used_at``
        on this call. Operators can disable the bump (e.g. for
        repeated reads in a tight loop) by passing
        ``bump_last_used=False`` to ``get_value`` — but the
        interface default is True.
        """

    @abc.abstractmethod
    def list(
        self,
        *,
        type: Optional[CredentialType] = None,
        name_prefix: Optional[str] = None,
    ) -> list[Credential]:
        """List credentials (metadata only — values are encrypted blobs).

        Args:
            type: If set, only return credentials of this type.
            name_prefix: If set, only return credentials whose name
                starts with this string (case-sensitive).
        """

    @abc.abstractmethod
    def update(
        self,
        credential_id: str,
        *,
        plaintext_value: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        rotation_policy: Optional[RotationPolicy] = None,
    ) -> Credential:
        """Update an existing credential.

        Any of the three fields can be None = "don't change". The
        returned ``Credential`` reflects the post-update state.
        ``updated_at`` is bumped automatically.

        Raises:
            CredentialNotFoundError: No row with this id.
        """

    @abc.abstractmethod
    def delete(self, credential_id: str) -> None:
        """Delete a credential permanently.

        Idempotent: returns silently if the id doesn't exist (so
        concurrent deletes don't race). Use ``get()`` first if you
        need a "not found" error.
        """

    @abc.abstractmethod
    def rotate(
        self,
        credential_id: str,
        *,
        new_plaintext_value: str,
    ) -> Credential:
        """Rotate the credential's value.

        Equivalent to ``update(credential_id, plaintext_value=new)``
        but also updates the rotation policy's ``next_rotation_at``
        (advancing it by ``interval_days`` from the rotation time).
        The api server exposes this as a separate endpoint so
        audit logs can distinguish "user changed the secret" from
        "user rotated the secret" — they're different operations
        with different security implications.
        """

    @abc.abstractmethod
    def record_use(self, credential_id: str) -> None:
        """Bump ``last_used_at`` to now.

        Called by the workflow runtime after a successful connector
        invocation. Idempotent on missing id (silent skip).
        """

    # ----- Helpers (non-abstract; useful to both impls) -----

    def _next_id(self) -> str:
        """Generate a fresh credential id (UUID4 hex).

        Centralized so both impls use the same id format. 32 hex
        characters, no dashes — sortable lexicographically when
        mixed in with timestamps.
        """
        return uuid.uuid4().hex

    def _default_rotation_after_rotate(
        self, policy: RotationPolicy, rotate_at: str
    ) -> RotationPolicy:
        """Compute the post-rotate RotationPolicy.

        The encrypted impl overrides this if it tracks rotation time
        differently (e.g. it uses the on-disk ``updated_at`` instead
        of an in-memory clock). The default is good enough for both.
        """
        if policy.interval_days is None:
            return policy
        from datetime import datetime, timedelta

        # Parse rotate_at ("...Z") and add interval_days. If the
        # caller already set next_rotation_at, leave it alone (they
        # might be back-filling).
        if policy.next_rotation_at is not None:
            return policy
        ts = rotate_at
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        new_ts = datetime.fromisoformat(ts) + timedelta(days=policy.interval_days)
        return RotationPolicy(
            interval_days=policy.interval_days,
            next_rotation_at=new_ts.isoformat().replace("+00:00", "Z"),
            notify_before_days=policy.notify_before_days,
        )
