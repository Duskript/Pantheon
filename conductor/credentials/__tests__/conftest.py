"""Shared fixtures for the Conductor credentials test suite.

Every test gets a fresh tmp directory (so writes don't leak between
tests) and a fresh credential store wired against that directory.
The encrypted-store fixture also generates a per-test passphrase,
so tests can't accidentally share keys.

Two store kinds are exposed:

  * ``stub_store`` — LocalStubCredentialStore, plaintext on disk.
    Used by tests that need a working store without crypto.
  * ``encrypted_store`` — EncryptedSqliteCredentialStore, fully
    encrypted. Used by encryption-specific tests; tests that need
    a fast backend (e.g. API endpoint tests) should use the stub.

A third fixture, ``fastapi_app``, wires the stub into a FastAPI app
for the endpoint tests. The api_key is empty (= auth disabled,
dev mode) by default; tests that exercise auth set it explicitly.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Iterator

import pytest


# Make the conductor package importable from anywhere.
_REPO = Path("/home/konan/pantheon")
sys.path.insert(0, str(_REPO))


@pytest.fixture
def tmp_dir() -> Iterator[Path]:
    """A fresh tmp directory; auto-cleaned after the test.

    Each test gets its own dir so credential stores can't leak
    files between tests.
    """
    d = Path(tempfile.mkdtemp(prefix="creds_test_"))
    try:
        yield d
    finally:
        # Best-effort cleanup. We don't fail tests on cleanup
        # errors — the tmp dir is in the system tmp and gets
        # GC'd eventually.
        import shutil
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


@pytest.fixture
def passphrase() -> str:
    """A per-test passphrase. The encrypted store fixture uses this
    to unlock; tests that need a 'wrong' passphrase can use a
    different value."""
    import secrets
    # Use a high-entropy string so accidental matches in the
    # test suite are statistically impossible.
    return "test-" + secrets.token_hex(16)


@pytest.fixture
def stub_store(tmp_dir: Path):
    """A fresh LocalStubCredentialStore in a tmp dir.

    The store is initialized (creates the empty file) and
    closed on teardown.
    """
    from conductor.credentials import LocalStubCredentialStore
    store = LocalStubCredentialStore(str(tmp_dir / "creds.json"))
    store.initialize()
    try:
        yield store
    finally:
        try:
            store.close()
        except Exception:
            pass


@pytest.fixture
def encrypted_store(tmp_dir: Path, passphrase: str):
    """A fresh, unlocked EncryptedSqliteCredentialStore.

    Each test gets a unique passphrase (see `passphrase` fixture)
    so the cached master key can't accidentally decrypt another
    test's data.
    """
    from conductor.credentials import EncryptedSqliteCredentialStore
    store = EncryptedSqliteCredentialStore(str(tmp_dir / "creds.db"))
    store.initialize()
    store.unlock(passphrase)
    try:
        yield store
    finally:
        try:
            store.lock()
        except Exception:
            pass


@pytest.fixture
def fastapi_app(stub_store, tmp_dir: Path):
    """A FastAPI app wired with a stub credential store and
    isolated workflow/state dirs. No auth (empty api_key)."""
    from fastapi.testclient import TestClient
    from conductor.v2.api_server import make_app

    wf_dir = tmp_dir / "wf"
    st_dir = tmp_dir / "st"
    wf_dir.mkdir(exist_ok=True)
    st_dir.mkdir(exist_ok=True)
    app = make_app(
        workflows_dir=wf_dir,
        state_dir=st_dir,
        api_key="",
        credential_store=stub_store,
    )
    client = TestClient(app)
    try:
        yield app, client
    finally:
        # TestClient doesn't need explicit close, but be safe.
        pass


@pytest.fixture
def fastapi_app_with_auth(stub_store, tmp_dir: Path):
    """Same as fastapi_app but with auth enabled (api_key='test-key')."""
    from fastapi.testclient import TestClient
    from conductor.v2.api_server import make_app

    wf_dir = tmp_dir / "wf"
    st_dir = tmp_dir / "st"
    wf_dir.mkdir(exist_ok=True)
    st_dir.mkdir(exist_ok=True)
    app = make_app(
        workflows_dir=wf_dir,
        state_dir=st_dir,
        api_key="test-key",
        credential_store=stub_store,
    )
    client = TestClient(app)
    try:
        yield app, client
    finally:
        pass


# A simple sample credential for tests that just need any record.
SAMPLE_CREDENTIAL = {
    "name": "sendgrid",
    "type": "api_key",
    "value": "***",
    "metadata": {"owner": "konan", "env": "test"},
}


def bearer_headers(key: str = "test-key") -> dict:
    """Build an Authorization header for an authenticated client."""
    return {"Authorization": f"Bearer {key}"}
