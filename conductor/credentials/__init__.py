"""Conductor credentials subsystem.

This package provides a pluggable, encrypted credential store for
the Conductor v2 API. The store is the source of truth for
connector secrets (API keys, OAuth tokens, DB URLs, etc.); the
API endpoints in ``v2/api_server.py`` expose CRUD + rotate + test
operations over it.

Public surface
--------------
* :class:`CredentialStore` — abstract base, in ``interface.py``.
* :class:`LocalStubCredentialStore` — JSON-file-backed stub for
  tests, in ``local_stub.py``.
* :class:`EncryptedSqliteCredentialStore` — production store with
  SQLCipher + Argon2id + AES-GCM, in ``encrypted_sqlite_impl.py``.
* :class:`Credential` and :class:`CredentialType` — domain types
  used by both the store and the API endpoints, in ``types.py``.

Why two implementations
-----------------------
The stub is fast, has zero native dependencies, and is the
reference behavior for the test suite. The encrypted impl is
the production store and exercises the same ABC. If a test passes
on the stub but fails on the encrypted impl, the encrypted impl
has a bug — not the test, not the spec.

Selection at runtime
--------------------
The api_server picks the implementation based on the
``CONDUCTOR_CRED_STORE_BACKEND`` env var. The default is the
encrypted impl; the stub is opt-in for tests by setting the
env var to ``"stub"``.

    CONDUCTOR_CRED_STORE_BACKEND=encrypted   (default — production)
    CONDUCTOR_CRED_STORE_BACKEND=stub        (tests only)

Note that the encrypted impl lazy-imports ``sqlcipher3`` and the
``keyring`` / ``cryptography`` packages so the stub path works
in dev envs that don't have those installed.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

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
from .interface import CredentialStore
from .local_stub import LocalStubCredentialStore
from .encrypted_sqlite_impl import EncryptedSqliteCredentialStore

# Backwards-compat re-exports — anything that imported the names
# from the package root keeps working.
__all__ = [
    "Credential",
    "CredentialType",
    "RotationPolicy",
    "CredentialError",
    "CredentialNotFoundError",
    "CredentialAlreadyExistsError",
    "CredentialValidationError",
    "CredentialStoreLockedError",
    "CredentialStore",
    "LocalStubCredentialStore",
    "EncryptedSqliteCredentialStore",
    "open_store",
    "default_store_path",
]


def default_store_path() -> str:
    """Return the default on-disk path for the credential store.

    Resolution order:
      1. ``CONDUCTOR_CRED_STORE_PATH`` env var (explicit override).
      2. ``~/pantheon/conductor/state/credentials.db`` (production).

    Returns the path as a string so callers can pass it directly
    to ``open_store()`` without a ``str()`` conversion.
    """
    explicit = os.environ.get("CONDUCTOR_CRED_STORE_PATH")
    if explicit:
        return explicit
    return str(
        Path.home() / "pantheon" / "conductor" / "state" / "credentials.db"
    )


def open_store(
    path: Optional[str] = None,
    *,
    backend: Optional[str] = None,
    passphrase: Optional[str] = None,
) -> "CredentialStore":
    """Construct a credential store.

    Args:
        path: Where the store lives on disk. Defaults to
            ``default_store_path()`` (the production location).
        backend: ``"encrypted"`` (default, production) or
            ``"stub"`` (plaintext JSON, tests only). The selection
            also respects the ``CONDUCTOR_CRED_STORE_BACKEND``
            env var when ``backend`` is None.
        passphrase: Required for the encrypted backend. If
            omitted, the encrypted store starts LOCKED — call
            ``unlock(passphrase)`` after construction. If
            provided, the store auto-unlocks on open.

    Returns:
        A constructed (and optionally unlocked) ``CredentialStore``.

    Raises:
        RuntimeError: If the encrypted backend is selected but
            ``sqlcipher3`` or its system dependencies are not
            installed.
    """
    actual_path = path or default_store_path()
    actual_backend = (
        backend if backend is not None else os.environ.get(
            "CONDUCTOR_CRED_STORE_BACKEND", "encrypted"
        )
    )
    if actual_backend == "stub":
        store = LocalStubCredentialStore(actual_path)
        store.initialize()
        return store
    if actual_backend == "encrypted":
        store = EncryptedSqliteCredentialStore(actual_path)
        store.initialize()
        if passphrase is not None:
            store.unlock(passphrase)
        return store
    raise ValueError(
        f"unknown credential store backend: {actual_backend!r} "
        f"(valid: 'encrypted', 'stub')"
    )


# Lazy imports — these pull in optional native deps. The runtime
# only needs the class that the config asked for; importing the
# other one is wasted work.
# (Removed: classes are imported at module top now. We keep the
# PEP 562 hook for forward-compat with any caller that does
# ``import conductor.credentials as cc; cc.SomeNewClass`` before
# it's been re-exported at the top.)
def __getattr__(name: str):  # PEP 562
    if name == "LocalStubCredentialStore":
        from .local_stub import LocalStubCredentialStore
        return LocalStubCredentialStore
    if name == "EncryptedSqliteCredentialStore":
        from .encrypted_sqlite_impl import EncryptedSqliteCredentialStore
        return EncryptedSqliteCredentialStore
    if name == "CredentialStore":
        from .interface import CredentialStore
        return CredentialStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
