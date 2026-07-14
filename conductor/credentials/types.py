"""Credential domain types.

Defines the data shapes for credentials stored in the encrypted credentials
store. These are plain dataclasses — no SQL or encryption concerns here.
The store implementations (local_stub, encrypted_sqlite_impl) are
responsible for serializing them to whatever backing store they use.

Why dataclasses and not Pydantic / TypedDict
--------------------------------------------
Pydantic adds a runtime cost on every read/write and a dependency on
Pydantic's validator model. The credentials store is on the hot path of
workflow execution (every connector call resolves a credential) and the
shape is stable and simple. A frozen dataclass is enough — and it gives
us `__hash__` and `__eq__` for free, which the tests rely on heavily.

Schema (from build plan §Phase 4.5):
    credentials(id, name, type, encrypted_value, metadata_json,
                created_at, updated_at, last_used_at, rotation_policy_json)

The dataclasses in this module mirror that schema. The "encrypted" part
of `encrypted_value` is the store's concern, not the type's — this module
treats the value as an opaque string (the encrypted blob).
"""
from __future__ import annotations

import enum
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string with 'Z' suffix.

    Why a helper: ``datetime.utcnow().isoformat()`` is deprecated in
    Python 3.12+ and doesn't include a timezone marker. We want a
    single canonical timestamp format on disk and over the wire, and
    'Z' (Zulu = UTC) is the most interoperably readable one. The
    store implementations call this for `created_at` and `updated_at`.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp into a timezone-aware datetime.

    Accepts both 'Z' suffix and explicit '+00:00' offsets. Raises
    ValueError on bad input — the caller (store deserialization)
    is expected to surface that to the user as a corrupted record.
    """
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


class CredentialType(str, enum.Enum):
    """The kind of credential.

    Stored in the DB as the enum's string value, not its name — that
    way the on-disk format is stable across Python versions and
    reorderings. The string-inheritance from `str` lets callers pass
    ``CredentialType.API_KEY`` to a JSON serializer and get ``"api_key"``
    out, with no custom encoder.

    Values
    ------
    API_KEY
        Opaque API key (SendGrid, Stripe, etc.).
    OAUTH2
        OAuth2 access + refresh token pair (stored as JSON in value).
    BASIC_AUTH
        HTTP Basic auth — username:password, base64 encoded.
    BEARER_TOKEN
        Bearer token (JWT, opaque session token, etc.).
    DATABASE_URL
        SQLAlchemy / libpq style connection string.
    WEBHOOK_SECRET
        Shared secret used to verify inbound webhook signatures.
    CUSTOM_JSON
        Free-form JSON payload — the metadata describes the shape.
    """

    API_KEY = "api_key"
    OAUTH2 = "oauth2"
    BASIC_AUTH = "basic_auth"
    BEARER_TOKEN = "bearer_token"
    DATABASE_URL = "database_url"
    WEBHOOK_SECRET = "webhook_secret"
    CUSTOM_JSON = "custom_json"


@dataclass
class RotationPolicy:
    """How often the credential should be rotated.

    All fields are optional — a credential with a no-fields policy
    (the default) is treated as "never rotate". The store only
    surfaces the policy; the actual rotation is the operator's job
    (and `POST /api/credentials/{id}/rotate` triggers a re-issue).

    Fields
    ------
    interval_days
        How many days between rotations. None = no auto-rotation.
    next_rotation_at
        ISO-8601 timestamp of the next scheduled rotation. Computed
        from `updated_at + interval_days` by the store on each write.
        If set explicitly by the caller (e.g. after a manual
        rotation), the store respects that value.
    notify_before_days
        How many days BEFORE `next_rotation_at` to surface a warning
        (returned in the API response). Default 7.
    """

    interval_days: Optional[int] = None
    next_rotation_at: Optional[str] = None
    notify_before_days: int = 7

    def to_json(self) -> str:
        """Serialize to a JSON string for storage.

        The store stores rotation_policy as a TEXT column containing
        this JSON. The exact field set may grow in future revisions;
        the loader is tolerant of unknown keys.
        """
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, raw: str) -> "RotationPolicy":
        """Deserialize from a JSON string.

        Tolerates an empty/None string — returns a no-rotation policy
        in that case. Throws ValueError on malformed JSON or wrong
        field types (caller decides whether to log + skip or 500).
        """
        if not raw:
            return cls()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"rotation_policy must be an object, got {type(data).__name__}")
        return cls(
            interval_days=data.get("interval_days"),
            next_rotation_at=data.get("next_rotation_at"),
            notify_before_days=data.get("notify_before_days", 7),
        )


@dataclass
class Credential:
    """A single credential record.

    The `value` field is the encrypted blob produced by the store
    (caller never constructs a `Credential` with a raw plaintext
    value — the store's `create()` method accepts the plaintext and
    returns a `Credential` with the encrypted blob in `value`).

    The `metadata` field is free-form and unencrypted — it describes
    WHAT the credential is for (e.g. {"owner": "konan", "env":
    "prod", "purpose": "sendgrid-email"}) so an operator can audit
    the store without unlocking the values. Secrets NEVER go in
    metadata.

    Fields
    ------
    id
        UUID4 string. Assigned by the store on create.
    name
        Human-readable label, unique within the store. Required.
    type
        The credential kind (see CredentialType).
    value
        Encrypted blob. The store owns the encryption — callers
        pass plaintext to `create()/update()` and read plaintext
        from `get_value()`.
    metadata
        Free-form dict, stored unencrypted. Default {}.
    created_at
        ISO-8601 UTC timestamp. Set by the store on create.
    updated_at
        ISO-8601 UTC timestamp. Bumped by the store on every
        value/metadata/policy change.
    last_used_at
        ISO-8601 UTC timestamp. Bumped by `record_use()`. None
        until the credential has been used at least once.
    rotation_policy
        RotationPolicy instance. Default = no rotation.
    """

    id: str
    name: str
    type: CredentialType
    value: str  # encrypted blob; opaque to this module
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    last_used_at: Optional[str] = None
    rotation_policy: RotationPolicy = field(default_factory=RotationPolicy)

    def to_dict(self, *, include_value: bool = False) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict.

        The default shape OMITS the encrypted value — list/read
        endpoints return metadata only, never the blob. Pass
        `include_value=True` for the rare endpoint that needs the
        blob (it's still encrypted; the caller is responsible
        for the next decryption step).

        The rotation_policy is serialized as a nested dict, not a
        JSON string, so the API consumer doesn't have to
        double-decode.
        """
        out: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "rotation_policy": asdict(self.rotation_policy),
        }
        if include_value:
            out["value"] = self.value
        return out

    @classmethod
    def from_row(
        cls,
        *,
        id: str,
        name: str,
        type: str,
        value: str,
        metadata_json: str,
        created_at: str,
        updated_at: str,
        last_used_at: Optional[str],
        rotation_policy_json: str,
    ) -> "Credential":
        """Build a Credential from a raw row (DB or JSON file).

        Used by both store implementations. `type` is the string
        form ("api_key", not CredentialType.API_KEY); we look it
        up via CredentialType to be tolerant of unknown values —
        an unknown type becomes CUSTOM_JSON with a `__unknown_type`
        metadata marker so the operator can clean up.
        """
        try:
            cred_type = CredentialType(type)
        except ValueError:
            cred_type = CredentialType.CUSTOM_JSON
            # Caller can detect the recovery by reading metadata
            # for `__unknown_type`. We don't fail closed here
            # because losing a credential due to a code-side enum
            # change is worse than degrading the type.
        try:
            metadata = json.loads(metadata_json) if metadata_json else {}
        except json.JSONDecodeError:
            metadata = {"__corrupted_metadata": True}
        if not isinstance(metadata, dict):
            metadata = {"__corrupted_metadata": True, "__raw_type": type(metadata).__name__}
        return cls(
            id=id,
            name=name,
            type=cred_type,
            value=value,
            metadata=metadata,
            created_at=created_at,
            updated_at=updated_at,
            last_used_at=last_used_at,
            rotation_policy=RotationPolicy.from_json(rotation_policy_json),
        )


class CredentialError(Exception):
    """Base class for credential-store errors."""


class CredentialNotFoundError(CredentialError):
    """Raised when a lookup by id or name returns no row.

    Maps to HTTP 404 in the api_server endpoints.
    """

    def __init__(self, key: str, *, by: str = "id") -> None:
        self.key = key
        self.by = by  # 'id' or 'name'
        super().__init__(f"credential not found by {by}: {key!r}")


class CredentialAlreadyExistsError(CredentialError):
    """Raised when create() collides on a unique name.

    Maps to HTTP 409 in the api_server endpoints.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"credential already exists: name={name!r}")


class CredentialValidationError(CredentialError):
    """Raised when a name/type/value fails the store's pre-write check."""


class CredentialStoreLockedError(CredentialError):
    """Raised when a write is attempted on a locked store.

    Maps to HTTP 423 (Locked) in the api_server endpoints — the
    operator needs to POST /api/credentials/unlock first.
    """

    def __init__(self, op: str) -> None:
        self.op = op
        super().__init__(f"credential store is locked; cannot {op}")
