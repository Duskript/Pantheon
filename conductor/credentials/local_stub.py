"""JSON-file-backed credential store stub for tests.

This is the local, plaintext implementation. It exists for two
reasons:

  1. **Test isolation.** Tests that exercise the ``CredentialStore``
     ABC can run without an encrypted DB and without spawning the
     keyring. Each test gets a fresh tmp file, no cross-test state.

  2. **Reference behavior.** When a new method is added to the ABC
     or behavior changes, the stub is the simplest possible
     implementation that the encrypted impl must match. If a test
     passes on the stub but fails on the encrypted impl, the
     encrypted impl has a bug.

File format
-----------
A single JSON file (``.json`` extension) containing a single object:

    {
        "version": 1,
        "credentials": {
            "<id>": {
                "id": "<id>",
                "name": "...",
                "type": "api_key",
                "value": "<plaintext>",     # NOTE: plaintext in stub
                "metadata": {...},
                "created_at": "...",
                "updated_at": "...",
                "last_used_at": "...",
                "rotation_policy": {...}
            },
            ...
        }
    }

The "credentials" key is a dict (not a list) for O(1) lookups by id.
The on-disk file is written atomically (tmp + os.replace) so a
crash mid-write doesn't leave a half-written file.

Concurrency
-----------
A single ``threading.RLock`` guards all reads and writes. The stub
is not designed for multi-process use; the encrypted impl is the
production store and handles that. We add a RLock anyway so
threaded tests don't race (FastAPI's TestClient uses threads).

This is intentional — the stub is for tests, not production.
Production always uses ``EncryptedSqliteCredentialStore``.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional

from .interface import CredentialStore, _now, _validate_name
from .types import (
    Credential,
    CredentialAlreadyExistsError,
    CredentialNotFoundError,
    CredentialType,
    CredentialValidationError,
    RotationPolicy,
)


class LocalStubCredentialStore(CredentialStore):
    """A JSON-file-backed credential store. Plaintext on disk.

    Use this for tests. Do not use this in production.
    """

    FILE_VERSION = 1

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self._path = Path(path)
        self._lock = threading.RLock()
        self._data: dict[str, dict[str, Any]] = {}  # id -> row dict

    # ----- Lifecycle -----

    def initialize(self) -> None:
        with self._lock:
            if self._path.exists():
                self._load()
            else:
                # Create parent dir, write an empty file.
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._save()

    def close(self) -> None:
        with self._lock:
            self._data.clear()
        super().close()

    # ----- CRUD -----

    def create(
        self,
        *,
        name: str,
        type: CredentialType,
        plaintext_value: str,
        metadata: Optional[dict[str, Any]] = None,
        rotation_policy: Optional[RotationPolicy] = None,
    ) -> Credential:
        _validate_name(name)
        if not isinstance(plaintext_value, str) or not plaintext_value:
            raise CredentialValidationError("plaintext_value must be a non-empty string")
        if not isinstance(type, CredentialType):
            # Tolerate the string form for convenience.
            try:
                type = CredentialType(type)
            except ValueError:
                raise CredentialValidationError(
                    f"unknown credential type: {type!r} "
                    f"(valid: {[t.value for t in CredentialType]})"
                )
        meta = dict(metadata) if metadata else {}
        policy = rotation_policy or RotationPolicy()
        if not isinstance(policy, RotationPolicy):
            raise CredentialValidationError(
                f"rotation_policy must be a RotationPolicy, got {type(policy).__name__}"
            )

        with self._lock:
            # Uniqueness by name.
            for row in self._data.values():
                if row["name"] == name:
                    raise CredentialAlreadyExistsError(name)

            cid = self._next_id()
            now = _now()
            row = {
                "id": cid,
                "name": name,
                "type": type.value,
                "value": plaintext_value,  # plaintext in the stub
                "metadata": meta,
                "created_at": now,
                "updated_at": now,
                "last_used_at": None,
                "rotation_policy": policy.to_json(),
            }
            self._data[cid] = row
            self._save()
            return self._row_to_credential(row)

    def get(self, credential_id: str) -> Credential:
        with self._lock:
            row = self._data.get(credential_id)
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            return self._row_to_credential(row)

    def get_by_name(self, name: str) -> Credential:
        with self._lock:
            for row in self._data.values():
                if row["name"] == name:
                    return self._row_to_credential(row)
            raise CredentialNotFoundError(name, by="name")

    def get_value(self, credential_id: str) -> str:
        with self._lock:
            row = self._data.get(credential_id)
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            # Bump last_used_at.
            row["last_used_at"] = _now()
            self._save()
            return row["value"]

    def list(
        self,
        *,
        type: Optional[CredentialType] = None,
        name_prefix: Optional[str] = None,
    ) -> list[Credential]:
        with self._lock:
            rows = list(self._data.values())
        if type is not None:
            t_str = type.value if isinstance(type, CredentialType) else str(type)
            rows = [r for r in rows if r["type"] == t_str]
        if name_prefix is not None:
            rows = [r for r in rows if r["name"].startswith(name_prefix)]
        # Sort by name for stable output.
        rows.sort(key=lambda r: r["name"])
        return [self._row_to_credential(r) for r in rows]

    def update(
        self,
        credential_id: str,
        *,
        plaintext_value: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        rotation_policy: Optional[RotationPolicy] = None,
    ) -> Credential:
        with self._lock:
            row = self._data.get(credential_id)
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            if plaintext_value is not None:
                if not isinstance(plaintext_value, str) or not plaintext_value:
                    raise CredentialValidationError("plaintext_value must be a non-empty string")
                row["value"] = plaintext_value
            if metadata is not None:
                if not isinstance(metadata, dict):
                    raise CredentialValidationError("metadata must be a dict")
                row["metadata"] = dict(metadata)
            if rotation_policy is not None:
                if not isinstance(rotation_policy, RotationPolicy):
                    raise CredentialValidationError("rotation_policy must be a RotationPolicy")
                row["rotation_policy"] = rotation_policy.to_json()
            row["updated_at"] = _now()
            self._save()
            return self._row_to_credential(row)

    def delete(self, credential_id: str) -> None:
        with self._lock:
            self._data.pop(credential_id, None)
            self._save()

    def rotate(
        self,
        credential_id: str,
        *,
        new_plaintext_value: str,
    ) -> Credential:
        with self._lock:
            row = self._data.get(credential_id)
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            existing = RotationPolicy.from_json(row["rotation_policy"])
            now = _now()
            row["value"] = new_plaintext_value
            new_policy = self._default_rotation_after_rotate(existing, now)
            row["rotation_policy"] = new_policy.to_json()
            row["updated_at"] = now
            self._save()
            return self._row_to_credential(row)

    def record_use(self, credential_id: str) -> None:
        with self._lock:
            row = self._data.get(credential_id)
            if row is None:
                return
            row["last_used_at"] = _now()
            self._save()

    # ----- Internals -----

    def _row_to_credential(self, row: dict[str, Any]) -> Credential:
        return Credential.from_row(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            value=row["value"],
            metadata_json=json.dumps(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            rotation_policy_json=row["rotation_policy"],
        )

    def _load(self) -> None:
        """Load the file. Missing file is an error (initialize creates it)."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise
        doc = json.loads(raw)
        if not isinstance(doc, dict):
            raise ValueError(f"credential file is not a JSON object: {self._path}")
        if doc.get("version") != self.FILE_VERSION:
            raise ValueError(
                f"unsupported credential file version: {doc.get('version')!r} "
                f"(expected {self.FILE_VERSION})"
            )
        creds = doc.get("credentials", {})
        if not isinstance(creds, dict):
            raise ValueError("credential file 'credentials' must be a dict")
        self._data = creds

    def _save(self) -> None:
        """Atomically write the data to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"version": self.FILE_VERSION, "credentials": self._data}
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
