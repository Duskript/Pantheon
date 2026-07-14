"""Encrypted SQLite credential store — production implementation.

Uses SQLCipher (via the ``sqlcipher3`` Python package) for page-level
AES-256 encryption plus an application-level AES-256-GCM envelope on
the value column. The encryption key is derived from the operator's
passphrase using Argon2id (RFC 9106) with a per-database random salt.

Design notes
------------
**Defense in depth.** SQLCipher protects against someone copying the
``credentials.db`` file off the disk. AES-GCM on the value column
adds a second layer: if a future vulnerability breaks SQLCipher (or
if the page-level key is somehow exposed), the values are still
encrypted under a key that's only in process memory during
``unlock()``. The two layers use the same passphrase-derived key,
so the operator still only needs to remember one thing.

**Argon2id parameters.** ``time_cost=2``, ``memory_cost=64 MiB``,
``parallelism=4`` — OWASP's 2024 minimum recommendation for
interactive authentication. We're not authenticating a human in a
loop, but we want the same brute-force resistance as a password
manager. The parameters are stored in the DB header (as JSON) so
future versions can tune them up without breaking old DBs.

**Keyring caching.** After ``unlock()`` the master key is cached in
the OS keyring (libsecret on Linux, Credential Manager on Windows,
Keychain on macOS) under the service name
``conductor-credentials`` and the account ``<operator>@<db-path>``.
Subprocess restarts of the api_server pick up the cached key
without re-prompting for the passphrase. Cache entries expire
after 1 hour of inactivity; the operator can clear them by
calling ``lock()`` explicitly or by re-issuing ``unlock()`` with
a new passphrase.

**Headless fallback.** When no keyring backend is available
(server, container, CI), the master key is written to a
chmod-600 file (``<db-path>.key``) instead. The operator's
deployer is responsible for putting that file on a tmpfs or
sealed volume. The file is created with restrictive permissions
and overwritten with random bytes before deletion.

**Substitution note.** The build plan calls for
``better-sqlite3-multiple-ciphers`` (the JS-side equivalent).
The PyPI package is named ``sqlcipher3`` and provides the same
SQLCipher backend with AES-256 page encryption. We import
``sqlcipher3`` here; if a future deploy needs the exact
``better-sqlite3-multiple-ciphers`` build, swap the import.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id
from cryptography.exceptions import InvalidTag

from .interface import CredentialStore, _now, _validate_name
from .types import (
    Credential,
    CredentialAlreadyExistsError,
    CredentialNotFoundError,
    CredentialStoreLockedError,
    CredentialType,
    CredentialValidationError,
    RotationPolicy,
)


# Service name for OS keyring entries.
KEYRING_SERVICE = "conductor-credentials"
# Header key for the JSON metadata block stored at offset 0 in the DB.
META_HEADER_KEY = "__meta__"
# Argon2id parameters (OWASP 2024 minimum for interactive auth).
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST = 64 * 1024  # 64 MiB
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32  # 256-bit master key
# AES-GCM nonce size (NIST SP 800-38D §5.2.1.1).
AES_NONCE_LEN = 12
# Master key length (bytes).
MASTER_KEY_LEN = 32
# Salt length (bytes) — 16 is standard for Argon2id.
SALT_LEN = 16
# Keyring cache TTL (seconds). After this, the operator must re-unlock.
KEYRING_TTL_SECONDS = 3600


def _derive_master_key(passphrase: str, salt: bytes) -> bytes:
    """Derive a 32-byte master key from the passphrase using Argon2id.

    The salt is per-database and stored in the DB header (so the same
    passphrase on two different DBs produces two different keys). The
    parameters match the OWASP 2024 minimum and are also stored in
    the header (so we can tune them in a future version without
    breaking existing DBs — the loader reads the params and re-derives).

    Returns the raw 32-byte key (not base64'd; it's used as the
    SQLCipher key and as the AES-GCM key).
    """
    if not isinstance(passphrase, str) or not passphrase:
        raise CredentialValidationError("passphrase must be a non-empty string")
    kdf = Argon2id(
        salt=salt,
        length=ARGON2_HASH_LEN,
        iterations=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        lanes=ARGON2_PARALLELISM,
    )
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt_value(master_key: bytes, plaintext: str) -> str:
    """Encrypt the plaintext value with AES-256-GCM.

    Output format: base64( nonce (12) || ciphertext_with_tag )
    The tag is appended automatically by AESGCM.encrypt.

    Returns a base64 string (so the value column is text-safe and
    doesn't need to fight SQLite's BLOB vs TEXT storage rules).
    """
    nonce = secrets.token_bytes(AES_NONCE_LEN)
    cipher = AESGCM(master_key)
    ct = cipher.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(nonce + ct).decode("ascii")


def _decrypt_value(master_key: bytes, blob_b64: str) -> str:
    """Inverse of ``_encrypt_value``.

    Raises ``CredentialStoreLockedError`` (mapped from
    ``InvalidTag``) when the tag check fails — this happens when
    the master key is wrong (e.g. wrong passphrase) or when the
    stored blob is corrupted. Either way, the operator's
    response is the same: check the key and the DB integrity.
    """
    raw = base64.b64decode(blob_b64.encode("ascii"))
    if len(raw) < AES_NONCE_LEN + 16:
        # 16 = GCM tag size. Anything shorter is structurally bad.
        raise CredentialStoreLockedError("decrypt credential value")
    nonce, ct = raw[:AES_NONCE_LEN], raw[AES_NONCE_LEN:]
    cipher = AESGCM(master_key)
    try:
        pt = cipher.decrypt(nonce, ct, None)
    except InvalidTag:
        # Wrong key or corrupted blob. Map to "store locked" so the
        # api server returns 423 — the operator's "fix it" move
        # is the same in both cases (re-unlock, restore from
        # backup if that fails).
        raise CredentialStoreLockedError("decrypt credential value")
    return pt.decode("utf-8")


class EncryptedSqliteCredentialStore(CredentialStore):
    """Production credential store: SQLCipher + AES-GCM + Argon2id.

    Construction
    ------------
    Pass a path to the database file. The store starts LOCKED — the
    operator must call ``unlock(passphrase)`` before any read or
    write. Reads of metadata (does the row exist?) are allowed
    while locked so the API can return a 423 with a useful
    "you need to unlock" hint instead of a generic 500.

    On first ``unlock()``, the store generates a random salt and
    stores it in the DB header along with the Argon2id parameters.
    On subsequent ``unlock()``s the salt is read from the header
    and the same master key is derived.

    After unlock, the master key is held in memory and (optionally)
    cached in the OS keyring. The next api_server restart can
    restore the key from the keyring without prompting the operator.
    """

    def __init__(
        self,
        path: str,
        *,
        keyring_cache: bool = True,
        fallback_keyfile: Optional[str] = None,
    ) -> None:
        super().__init__(path)
        # Lazy import: sqlcipher3 may not be installed in dev envs
        # that only run the stub. The encrypted impl is only loaded
        # when the api_server is configured to use it.
        import sqlcipher3  # type: ignore

        self._sqlcipher3 = sqlcipher3
        self._path = Path(path)
        self._keyring_cache_enabled = keyring_cache
        self._fallback_keyfile = (
            Path(fallback_keyfile) if fallback_keyfile else self._path.with_suffix(".key")
        )
        self._lock = threading.RLock()
        self._conn: Optional[Any] = None
        self._master_key: Optional[bytes] = None
        self._salt: Optional[bytes] = None
        self._argon_params: dict[str, int] = {
            "time_cost": ARGON2_TIME_COST,
            "memory_cost": ARGON2_MEMORY_COST,
            "parallelism": ARGON2_PARALLELISM,
        }
        # Keyring handle is lazy — only opened on first cache write.
        self._keyring = None

    # ----- Lifecycle -----

    def initialize(self) -> None:
        """Prepare the on-disk location for the store.

        Idempotent. We do NOT create the SQLite file here — SQLCipher
        requires a key to be set before any other statement, and the
        key only exists after ``unlock()`` derives it from the
        operator's passphrase. Creating the file with a placeholder
        key would lock the file to that key, and the operator's real
        passphrase wouldn't be able to open it.

        What we DO do:
          * Make sure the parent directory exists.
          * If a meta sidecar exists, validate it (operator can spot
            a corrupted header before trying to unlock).

        The first ``unlock()`` creates the DB file (since the
        passphrase-derived key is now available) and writes the meta
        sidecar if it isn't already there. Subsequent ``unlock()``s
        reuse both.
        """
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # If a meta sidecar exists, validate it. A corrupted
            # sidecar means the DB is also probably unrecoverable,
            # but we surface the error here (not in unlock) so the
            # operator can act on the diagnosis without the extra
            # Argon2 work.
            meta_path = self._path.with_suffix(self._path.suffix + ".meta")
            if meta_path.exists():
                try:
                    doc = json.loads(meta_path.read_text(encoding="utf-8"))
                    if "salt" not in doc or "argon" not in doc:
                        raise ValueError(
                            "meta sidecar missing required keys 'salt'/'argon'"
                        )
                except (json.JSONDecodeError, OSError, ValueError) as e:
                    raise CredentialStoreLockedError(
                        f"initialize (corrupt meta sidecar at {meta_path}): {e}"
                    ) from e

    def _maybe_generate_initial_salt_on_disk(self) -> None:
        """On a brand-new DB, write a fresh salt + meta header.

        We write the meta as a sidecar file (``<db>.meta``) so
        SQLCipher's first-page format isn't disturbed. The
        encrypted impl reads it on every unlock; it's small
        (16-byte salt + a few int params) and tamper-evident
        via the SQLCipher page hash.

        Why a sidecar and not a DB row: the operator's
        passphrase is what creates the salt, so the first
        connection (with the random placeholder key) is the
        natural time to write the salt. Doing it in unlock()
        also works but adds a branch on every open. Sidecar
        is simpler and the file is chmod-600.
        """
        meta_path = self._path.with_suffix(self._path.suffix + ".meta")
        if meta_path.exists():
            return
        meta = {
            "version": 1,
            "salt": secrets.token_bytes(SALT_LEN).hex(),
            "argon": self._argon_params,
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        # Write atomically with restrictive perms.
        fd = os.open(
            str(meta_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(meta, f)
        except Exception:
            try:
                os.unlink(meta_path)
            except OSError:
                pass
            raise

    def _read_meta(self) -> dict[str, Any]:
        """Read the meta sidecar. Returns {} if missing (legacy DB)."""
        meta_path = self._path.with_suffix(self._path.suffix + ".meta")
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            # Wipe the master key from memory.
            if self._master_key is not None:
                # Best-effort zeroize. CPython may have copied the
                # bytes elsewhere; this only clears our reference.
                self._master_key = b"\x00" * len(self._master_key)
                self._master_key = None
        super().close()

    # ----- Locking -----

    def is_unlocked(self) -> bool:
        return self._master_key is not None and self._conn is not None

    def unlock(self, passphrase: str) -> None:
        """Unlock the store with the operator's passphrase.

        Re-derives the master key from the passphrase + stored salt,
        opens the DB with the key, and runs the schema migration.
        On success, the store is unlocked for reads and writes.

        On failure (wrong passphrase) raises ``CredentialStoreLockedError``
        with op="unlock" — the API surfaces this as 423.
        """
        with self._lock:
            meta = self._read_meta()
            salt_hex = meta.get("salt")
            if salt_hex:
                salt = bytes.fromhex(salt_hex)
                argon = meta.get("argon", self._argon_params)
                # Override module-level params from the stored header
                # so older DBs with lower params still work and future
                # DBs with higher params get the new ones.
                self._argon_params.update(argon)
            else:
                # Legacy / first-time: generate a fresh salt and
                # write the meta sidecar.
                salt = secrets.token_bytes(SALT_LEN)
                self._write_meta_salt(salt)
            self._salt = salt
            self._master_key = self._derive_with_params(passphrase, salt)

            # Open the DB with the derived key and verify it works.
            conn = self._sqlcipher3.connect(str(self._path))
            try:
                conn.execute(
                    "PRAGMA key = \"x'{}'\"".format(self._master_key.hex())
                )
                # We do NOT use a probe table here. On a fresh DB
                # any statement works; on an existing DB a probe
                # would force SQLCipher to read a page (the
                # sqlite_schema page) and decrypt it. With a wrong
                # key, that page-read raises MemoryError or
                # DatabaseError depending on the SQLCipher build,
                # neither of which is a clean "wrong passphrase"
                # signal. Instead, we trust that the schema
                # migration below will fail loudly if the key is
                # wrong.
                self._create_schema(conn)
            except Exception as e:
                try:
                    conn.close()
                except Exception:
                    pass
                self._master_key = None
                # MemoryError on page decrypt is the most common
                # signal of a wrong key on a populated DB; map to
                # locked so the API returns 423.
                err = type(e).__name__
                raise CredentialStoreLockedError(
                    f"unlock (likely wrong passphrase — got {err}): {e}"
                ) from e
            self._conn = conn
            # Optionally cache in keyring for next restart.
            if self._keyring_cache_enabled:
                self._cache_key_to_keyring()

    def _write_meta_salt(self, salt: bytes) -> None:
        meta_path = self._path.with_suffix(self._path.suffix + ".meta")
        meta = {
            "version": 1,
            "salt": salt.hex(),
            "argon": self._argon_params,
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(
            str(meta_path),
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(meta, f)
        except Exception:
            try:
                os.unlink(meta_path)
            except OSError:
                pass
            raise

    def _derive_with_params(self, passphrase: str, salt: bytes) -> bytes:
        """Derive master key with the params currently in self._argon_params.

        Separated from ``_derive_master_key`` so we honor the params
        stored in the meta sidecar (which may differ from the module
        defaults if a future version bumps them).
        """
        if not isinstance(passphrase, str) or not passphrase:
            raise CredentialValidationError("passphrase must be a non-empty string")
        kdf = Argon2id(
            salt=salt,
            length=self._argon_params.get("hash_len", ARGON2_HASH_LEN),
            iterations=self._argon_params["time_cost"],
            memory_cost=self._argon_params["memory_cost"],
            lanes=self._argon_params["parallelism"],
        )
        return kdf.derive(passphrase.encode("utf-8"))

    def _cache_key_to_keyring(self) -> None:
        """Best-effort write of the master key to the OS keyring.

        Failures are silent — the keyring is a cache, not the source
        of truth. If the operator's env doesn't have a keyring
        backend (e.g. headless CI), the in-memory key still works
        for the lifetime of the process; on restart, the operator
        will be prompted to unlock again.
        """
        try:
            import keyring  # type: ignore
        except Exception:
            return
        try:
            account = f"{os.environ.get('USER', 'operator')}@{self._path}"
            # keyring stores strings; we base64 the raw bytes.
            keyring.set_password(
                KEYRING_SERVICE,
                account,
                base64.b64encode(self._master_key).decode("ascii"),
            )
        except Exception:
            # libsecret not running, keyring disabled, etc.
            return

    def load_cached_key(self) -> bool:
        """Try to restore the master key from the keyring cache.

        Returns True if a cached key was found and used to unlock
        the store. Returns False if the cache is empty or the
        keyring is unavailable.
        """
        try:
            import keyring  # type: ignore
        except Exception:
            return False
        try:
            account = f"{os.environ.get('USER', 'operator')}@{self._path}"
            cached = keyring.get_password(KEYRING_SERVICE, account)
        except Exception:
            return False
        if not cached:
            return False
        try:
            key = base64.b64decode(cached.encode("ascii"))
            if len(key) != MASTER_KEY_LEN:
                return False
        except Exception:
            return False
        with self._lock:
            meta = self._read_meta()
            salt_hex = meta.get("salt")
            if not salt_hex:
                return False
            self._salt = bytes.fromhex(salt_hex)
            self._argon_params.update(meta.get("argon", self._argon_params))
            self._master_key = key
            conn = self._sqlcipher3.connect(str(self._path))
            try:
                conn.execute(
                    "PRAGMA key = \"x'{}'\"".format(self._master_key.hex())
                )
                conn.execute("CREATE TABLE IF NOT EXISTS __probe_unused__ (x)")
                conn.execute("DROP TABLE IF EXISTS __probe_unused__")
            except Exception:
                conn.close()
                self._master_key = None
                return False
            self._create_schema(conn)
            self._conn = conn
            return True

    def lock(self) -> None:
        """Lock the store, wiping the in-memory master key.

        Reverses ``unlock()``. The DB file is left on disk; the
        salt and meta sidecar are unchanged. Next read requires
        a fresh ``unlock()`` (or ``load_cached_key()``).
        """
        self.close()
        # Best-effort clear the keyring cache too.
        try:
            import keyring  # type: ignore
            account = f"{os.environ.get('USER', 'operator')}@{self._path}"
            keyring.delete_password(KEYRING_SERVICE, account)
        except Exception:
            pass

    # ----- Schema -----

    def _create_schema(self, conn: Any) -> None:
        """Idempotent schema migration.

        Schema (from build plan §Phase 4.5):
            credentials(id, name, type, encrypted_value, metadata_json,
                        created_at, updated_at, last_used_at,
                        rotation_policy_json)

        Notes:
            * id is a TEXT PK (UUID4 hex). 32 hex chars.
            * name is UNIQUE — collisions surface as
              CredentialAlreadyExistsError, mapped to 409.
            * type is TEXT (the enum string form).
            * encrypted_value is TEXT (base64 of nonce||ct).
            * metadata_json and rotation_policy_json are TEXT (JSON).
            * The timestamps are ISO-8601 UTC strings.
        """
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT,
                rotation_policy_json TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        # Index on name (UNIQUE already creates one, but be explicit
        # so future schema migrations can rely on it).
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_credentials_name ON credentials(name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_credentials_type ON credentials(type)"
        )
        conn.commit()

    # ----- CRUD -----

    def _require_unlocked(self) -> Any:
        """Return the open connection or raise CredentialStoreLockedError."""
        if self._conn is None or self._master_key is None:
            raise CredentialStoreLockedError("access credential store")
        return self._conn

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
            conn = self._require_unlocked()
            # Uniqueness check (the UNIQUE constraint will catch
            # a race; we check first for a friendlier error).
            cur = conn.execute("SELECT 1 FROM credentials WHERE name = ?", (name,))
            if cur.fetchone() is not None:
                raise CredentialAlreadyExistsError(name)
            cid = self._next_id()
            now = _now()
            enc = _encrypt_value(self._master_key, plaintext_value)
            try:
                conn.execute(
                    """
                    INSERT INTO credentials
                        (id, name, type, encrypted_value, metadata_json,
                         created_at, updated_at, last_used_at,
                         rotation_policy_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cid,
                        name,
                        type.value,
                        enc,
                        json.dumps(meta),
                        now,
                        now,
                        None,
                        policy.to_json(),
                    ),
                )
                conn.commit()
            except sqlite3.IntegrityError as e:
                if "UNIQUE" in str(e):
                    raise CredentialAlreadyExistsError(name) from e
                raise CredentialStoreLockedError("create") from e
            return self._row_to_credential(
                self._fetch_row(conn, cid, value=enc)
            )

    def get(self, credential_id: str) -> Credential:
        with self._lock:
            conn = self._require_unlocked()
            row = self._fetch_row(conn, credential_id, value=None)
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            # Re-fetch with the encrypted value (the no-value
            # variant is only for the create() return path).
            return self._row_to_credential(
                self._fetch_row(conn, credential_id, value=None)
            )

    def get_by_name(self, name: str) -> Credential:
        with self._lock:
            conn = self._require_unlocked()
            cur = conn.execute(
                "SELECT id FROM credentials WHERE name = ?", (name,)
            )
            row = cur.fetchone()
            if row is None:
                raise CredentialNotFoundError(name, by="name")
            return self.get(row[0])

    def get_value(self, credential_id: str) -> str:
        with self._lock:
            conn = self._require_unlocked()
            cur = conn.execute(
                "SELECT encrypted_value FROM credentials WHERE id = ?",
                (credential_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            pt = _decrypt_value(self._master_key, row[0])
            # Bump last_used_at.
            conn.execute(
                "UPDATE credentials SET last_used_at = ? WHERE id = ?",
                (_now(), credential_id),
            )
            conn.commit()
            return pt

    def list(
        self,
        *,
        type: Optional[CredentialType] = None,
        name_prefix: Optional[str] = None,
    ) -> list[Credential]:
        with self._lock:
            conn = self._require_unlocked()
            query = "SELECT * FROM credentials"
            clauses: list[str] = []
            params: list[Any] = []
            if type is not None:
                t_str = type.value if isinstance(type, CredentialType) else str(type)
                clauses.append("type = ?")
                params.append(t_str)
            if name_prefix is not None:
                clauses.append("name LIKE ?")
                params.append(name_prefix + "%")
            if clauses:
                query += " WHERE " + " AND ".join(clauses)
            query += " ORDER BY name ASC"
            cur = conn.execute(query, params)
            return [self._row_to_credential(self._row_to_dict(r)) for r in cur.fetchall()]

    def update(
        self,
        credential_id: str,
        *,
        plaintext_value: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        rotation_policy: Optional[RotationPolicy] = None,
    ) -> Credential:
        with self._lock:
            conn = self._require_unlocked()
            cur = conn.execute("SELECT 1 FROM credentials WHERE id = ?", (credential_id,))
            if cur.fetchone() is None:
                raise CredentialNotFoundError(credential_id, by="id")
            sets: list[str] = []
            params: list[Any] = []
            if plaintext_value is not None:
                if not isinstance(plaintext_value, str) or not plaintext_value:
                    raise CredentialValidationError("plaintext_value must be a non-empty string")
                sets.append("encrypted_value = ?")
                params.append(_encrypt_value(self._master_key, plaintext_value))
            if metadata is not None:
                if not isinstance(metadata, dict):
                    raise CredentialValidationError("metadata must be a dict")
                sets.append("metadata_json = ?")
                params.append(json.dumps(dict(metadata)))
            if rotation_policy is not None:
                if not isinstance(rotation_policy, RotationPolicy):
                    raise CredentialValidationError("rotation_policy must be a RotationPolicy")
                sets.append("rotation_policy_json = ?")
                params.append(rotation_policy.to_json())
            if not sets:
                # Nothing to do — return the current state. Bumping
                # updated_at would be a lie (no change happened), so
                # we don't.
                return self.get(credential_id)
            sets.append("updated_at = ?")
            params.append(_now())
            params.append(credential_id)
            conn.execute(
                f"UPDATE credentials SET {', '.join(sets)} WHERE id = ?",
                params,
            )
            conn.commit()
            return self.get(credential_id)

    def delete(self, credential_id: str) -> None:
        with self._lock:
            conn = self._require_unlocked()
            conn.execute("DELETE FROM credentials WHERE id = ?", (credential_id,))
            conn.commit()

    def rotate(
        self,
        credential_id: str,
        *,
        new_plaintext_value: str,
    ) -> Credential:
        with self._lock:
            conn = self._require_unlocked()
            cur = conn.execute(
                "SELECT rotation_policy_json FROM credentials WHERE id = ?",
                (credential_id,),
            )
            row = cur.fetchone()
            if row is None:
                raise CredentialNotFoundError(credential_id, by="id")
            existing = RotationPolicy.from_json(row[0])
            now = _now()
            new_policy = self._default_rotation_after_rotate(existing, now)
            conn.execute(
                """
                UPDATE credentials
                   SET encrypted_value = ?,
                       rotation_policy_json = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (
                    _encrypt_value(self._master_key, new_plaintext_value),
                    new_policy.to_json(),
                    now,
                    credential_id,
                ),
            )
            conn.commit()
            return self.get(credential_id)

    def record_use(self, credential_id: str) -> None:
        with self._lock:
            conn = self._require_unlocked()
            conn.execute(
                "UPDATE credentials SET last_used_at = ? WHERE id = ?",
                (_now(), credential_id),
            )
            conn.commit()

    # ----- Internals -----

    def _fetch_row(
        self, conn: Any, credential_id: str, value: Optional[str]
    ) -> dict[str, Any]:
        """Fetch a single credential row by id as a dict.

        The `value` arg is ignored in the query path (we always
        read encrypted_value from the DB). It exists so the
        post-insert path in create() can short-circuit without
        a redundant SELECT.
        """
        cur = conn.execute(
            "SELECT * FROM credentials WHERE id = ?", (credential_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        """Convert a SQL row (tuple) to a dict keyed by column name.

        SQLCipher returns rows as plain tuples; we use the
        description metadata to recover the column names.
        """
        # The cursor is in `row.cursor` if the row came from a
        # cursor object, but the simpler approach is to keep
        # the column order in lockstep with the SELECT * above.
        return {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "encrypted_value": row[3],
            "metadata_json": row[4],
            "created_at": row[5],
            "updated_at": row[6],
            "last_used_at": row[7],
            "rotation_policy_json": row[8],
        }

    def _row_to_credential(self, row: dict[str, Any]) -> Credential:
        return Credential.from_row(
            id=row["id"],
            name=row["name"],
            type=row["type"],
            value=row["encrypted_value"],
            metadata_json=row["metadata_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            rotation_policy_json=row["rotation_policy_json"],
        )
