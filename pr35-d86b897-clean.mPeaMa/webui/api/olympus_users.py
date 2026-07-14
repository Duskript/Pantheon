"""
Olympus UI — Multi-User Data Store.

Persists users, roles, and session-to-user mappings in a JSON file.
Built on top of the existing Hermes WebUI session management in auth.py.

First boot: creates a default admin user. The admin can then create
additional users via the API or invite system.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import tempfile
import time
import uuid
from typing import Any

from api.config import STATE_DIR

logger = logging.getLogger(__name__)

# ── File paths ───────────────────────────────────────────────────────────────

_USERS_FILE = STATE_DIR / "olympus_users.json"

# ─── Roles (from Olympus ROLE_PERMISSIONS.md) ─────────────────────────────

SYSTEM_ROLES = frozenset({"owner", "admin", "power_user", "user", "guest"})

ROLE_HIERARCHY = {
    "owner": 5,
    "admin": 4,
    "power_user": 3,
    "user": 2,
    "guest": 1,
}

# Feature flags per role (deployment defaults)
DEFAULT_FEATURE_FLAGS: dict[str, dict[str, bool]] = {
    "model_picker": {"owner": True, "admin": True, "power_user": True, "user": False, "guest": False},
    "agent_switcher": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "boon_drawer": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": True},
    "file_uploads": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "tools_panel": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "skills_panel": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "cron_panel": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "memory_panel": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "theme_switcher": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "admin_panel": {"owner": True, "admin": True, "power_user": False, "user": False, "guest": False},
    "session_export": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "terminal": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "notifications": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": True},
    "project_ideas": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "god_glow": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": True},
    "providers_tab": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "restart_tab": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "remote_access_tab": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "kanban": {"owner": True, "admin": True, "power_user": True, "user": False, "guest": False},
    "helpers_tab": {"owner": True, "admin": True, "power_user": True, "user": True, "guest": False},
    "dashboard": {"owner": True, "admin": True, "power_user": False, "user": False, "guest": False},
    "plugins_panel": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "mcp_panel": {"owner": True, "admin": False, "power_user": False, "user": False, "guest": False},
    "user_management": {"owner": True, "admin": True, "power_user": False, "user": False, "guest": False},
    "n8n": {"owner": True, "admin": True, "power_user": False, "user": False, "guest": False},
}


# ─── Data Types ──────────────────────────────────────────────────────────


def _default_users() -> list[dict[str, Any]]:
    """Return an empty user list — admin is created on first boot."""
    return []


def _default_state() -> dict[str, Any]:
    return {
        "users": _default_users(),
        "metadata": {
            "created_at": time.time(),
            "version": 2,
        },
    }


# ─── Persistence ────────────────────────────────────────────────────────


def _load_data() -> dict[str, Any]:
    """Load user data from disk. Returns default state on error or missing file."""
    try:
        if _USERS_FILE.exists():
            raw = _USERS_FILE.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict) and "users" in data:
                return data
    except Exception as e:
        logger.debug("Failed to load user data: %s", e)
    return _default_state()


def _save_data(data: dict[str, Any]) -> None:
    """Atomically persist user data to disk (0600)."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_DIR, suffix=".olympus_users.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
            os.chmod(tmp, 0o600)
            os.replace(tmp, _USERS_FILE)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception as e:
        logger.error("Failed to persist user data: %s", e)


# ─── Data ───────────────────────────────────────────────────────────────

_data: dict[str, Any] | None = None
_data_lock = __import__("threading").Lock()


def _get_data() -> dict[str, Any]:
    global _data
    if _data is None:
        with _data_lock:
            if _data is None:
                _data = _load_data()
                _ensure_first_admin()
                _migrate_users()
    return _data


def _migrate_users() -> None:
    """Backfill missing fields on existing users (avatar, color, permitted_gods) after code changes."""
    changed = False
    for user in _data.get("users", []):
        if "avatar" not in user:
            user["avatar"] = None
            changed = True
        if "color" not in user:
            user["color"] = "#6050b0"
            changed = True
        if "permitted_gods" not in user:
            user["permitted_gods"] = None if user.get("role") == "owner" else []
            changed = True
    if changed:
        _save_data(_data)


def _flush_data() -> None:
    with _data_lock:
        if _data is not None:
            _save_data(_data)


# ─── Password Helpers ──────────────────────────────────────────────────

# Uses the same PBKDF2 scheme as auth.py, but with a per-user salt for
# multi-user isolation.


def _hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Hash a password with PBKDF2-SHA256. Returns (hash_hex, salt_hex)."""
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_hex(16).encode()
    if not salt_hex:
        salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return dk.hex(), salt.hex()


def _verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    """Verify a password against a stored hash+salt."""
    dk, _ = _hash_password(password, salt_hex)
    return hmac.compare_digest(dk, stored_hash)


# ─── User CRUD ─────────────────────────────────────────────────────────


def _ensure_first_admin() -> None:
    """Create a default admin user on first boot if no users exist."""
    data = _data if _data is not None else _load_data()
    if data["users"]:
        return

    env_user = os.getenv("OLYMPUS_ADMIN_USER", "admin").strip()
    env_pass = os.getenv("OLYMPUS_ADMIN_PASSWORD", "password").strip()

    # If env var was explicitly set to empty, use a random password
    if os.getenv("OLYMPUS_ADMIN_PASSWORD") is not None and not env_pass:
        env_pass = secrets.token_urlsafe(16)
        logger.info(
            "═══ First boot: created default admin account ═══\n"
            "  Username: %s\n"
            "  Password: %s\n"
            "  ⚠  Set OLYMPUS_ADMIN_PASSWORD env var to configure in advance.",
            env_user,
            env_pass,
        )
        # Also print to stderr so journalctl/service logs capture it
        import sys as _sys
        print(file=_sys.stderr)
        print("⚠  FIRST BOOT — Admin account created", file=_sys.stderr)
        print(f"   Username: {env_user}", file=_sys.stderr)
        print(f"   Password: {env_pass}", file=_sys.stderr)
        print("   Set OLYMPUS_ADMIN_PASSWORD env var to configure in advance.", file=_sys.stderr)
        print(file=_sys.stderr)

    user = _create_user_internal(data, env_user, env_pass, "owner")
    logger.info("Created initial admin user: %s (id=%s)", user["username"], user["id"])

    if _data is not None:
        _save_data(data)


def _create_user_internal(
    data: dict[str, Any],
    username: str,
    password: str,
    role: str,
) -> dict[str, Any]:
    """Create a user in the provided data dict. Returns the user dict."""
    if role not in SYSTEM_ROLES:
        raise ValueError(f"Invalid role: {role}. Must be one of {sorted(SYSTEM_ROLES)}")

    hash_hex, salt_hex = _hash_password(password)
    now = time.time()

    user = {
        "id": "u_" + uuid.uuid4().hex[:12],
        "username": username,
        "display_name": username,
        "avatar": None,  # base64 data URL or null
        "color": "#6050b0",
        "role": role,
        "permitted_gods": None if role == "owner" else [],  # owner → all gods, others → explicit list
        "password_hash": hash_hex,
        "password_salt": salt_hex,
        "status": "active",
        "preferences": {
            "theme": "pantheon",
            "density": "comfortable",
        },
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }

    data["users"].append(user)
    return user


def _find_user(data: dict[str, Any], user_id: str | None = None, username: str | None = None) -> dict[str, Any] | None:
    """Find a user by ID or username."""
    for u in data["users"]:
        if user_id and u["id"] == user_id:
            return u
        if username and u["username"] == username:
            return u
    return None


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    """Authenticate a user. Returns the user dict on success, None on failure."""
    data = _get_data()
    user = _find_user(data, username=username)
    if not user:
        return None
    if user["status"] != "active":
        return None
    if not _verify_password(password, user["password_hash"], user["password_salt"]):
        return None
    # Update last_login
    user["last_login_at"] = time.time()
    _flush_data()
    return user


def get_user(user_id: str) -> dict[str, Any] | None:
    """Get a user by ID. Returns None if not found."""
    data = _get_data()
    return _find_user(data, user_id=user_id)


def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Get a user by username. Returns None if not found."""
    data = _get_data()
    return _find_user(data, username=username)


def list_users() -> list[dict[str, Any]]:
    """List all users (without password hashes)."""
    data = _get_data()
    return [_strip_secrets(u) for u in data["users"]]


def create_user(username: str, password: str, role: str, created_by_role: str) -> dict[str, Any]:
    """Create a new user. Enforces role ceiling."""
    if role not in SYSTEM_ROLES:
        raise ValueError(f"Invalid role: {role}")
    if ROLE_HIERARCHY.get(role, 0) > ROLE_HIERARCHY.get(created_by_role, 0):
        raise ValueError(f"Cannot create user with role '{role}' from role '{created_by_role}' (role ceiling)")
    if len(username.strip()) < 2:
        raise ValueError("Username must be at least 2 characters")
    if len(password) < 6:
        raise ValueError("Password must be at least 6 characters")

    data = _get_data()

    # Check for duplicate username
    if _find_user(data, username=username.strip()):
        raise ValueError(f"Username '{username}' already exists")

    user = _create_user_internal(data, username.strip(), password, role)
    _save_data(data)
    return _strip_secrets(user)


def update_user(user_id: str, updates: dict[str, Any], acting_role: str) -> dict[str, Any]:
    """Update a user's fields. Enforces role ceiling."""
    data = _get_data()
    user = _find_user(data, user_id=user_id)
    if not user:
        raise ValueError(f"User '{user_id}' not found")

    # Role changes: enforce ceiling
    new_role = updates.get("role")
    if new_role and new_role != user["role"]:
        if new_role not in SYSTEM_ROLES:
            raise ValueError(f"Invalid role: {new_role}")
        if ROLE_HIERARCHY.get(new_role, 0) > ROLE_HIERARCHY.get(acting_role, 0):
            raise ValueError(f"Cannot assign role '{new_role}' from role '{acting_role}' (role ceiling)")

    if "password" in updates and updates["password"]:
        hash_hex, salt_hex = _hash_password(updates["password"])
        user["password_hash"] = hash_hex
        user["password_salt"] = salt_hex

    if "username" in updates:
        user["username"] = updates["username"].strip()
    if "display_name" in updates:
        user["display_name"] = updates["display_name"].strip()
    if "avatar" in updates:
        user["avatar"] = updates["avatar"]
    if "color" in updates:
        color = updates["color"].strip()
        if not color.startswith("#") or len(color) not in (4, 7):
            raise ValueError("Invalid color format — must be hex like #6050b0")
        user["color"] = color
    if "role" in updates:
        user["role"] = updates["role"]
    if "permitted_gods" in updates:
        # None = all gods (owner), list = explicit god names
        pg = updates["permitted_gods"]
        user["permitted_gods"] = pg if pg is None or isinstance(pg, list) else []
    if "status" in updates:
        user["status"] = updates["status"]

    user["updated_at"] = time.time()
    _save_data(data)
    return _strip_secrets(user)


def delete_user(user_id: str, acting_role: str) -> None:
    """Soft-delete a user (set status=disabled). Prevents deleting the last owner."""
    data = _get_data()
    user = _find_user(data, user_id=user_id)
    if not user:
        raise ValueError(f"User '{user_id}' not found")
    if user["role"] == "owner":
        # Check this isn't the last owner
        owners = [u for u in data["users"] if u["role"] == "owner" and u["status"] == "active"]
        if len(owners) <= 1:
            raise ValueError("Cannot disable the last active owner")

    user["status"] = "disabled"
    user["updated_at"] = time.time()
    _save_data(data)


def _strip_secrets(user: dict[str, Any]) -> dict[str, Any]:
    """Return a user dict without password fields."""
    return {k: v for k, v in user.items() if k not in ("password_hash", "password_salt")}


# ─── Feature Flags ──────────────────────────────────────────────────────

# Runtime overrides (set via admin panel, persist to user_data.json)
_feature_overrides: dict[str, bool] | None = None


def get_feature_flags(role: str) -> dict[str, bool]:
    """Resolve effective feature flags for a given role."""
    flags: dict[str, bool] = {}
    for flag_name, role_map in DEFAULT_FEATURE_FLAGS.items():
        flags[flag_name] = role_map.get(role, False)

    # Apply any runtime overrides
    overrides = _get_feature_overrides()
    for flag_name, value in overrides.items():
        if flag_name in flags:
            flags[flag_name] = value

    return flags


def set_feature_override(flag_name: str, value: bool, acting_role: str) -> None:
    """Set a deployment-wide feature flag override. Owner only."""
    if acting_role != "owner":
        raise ValueError("Only owners can change feature flags")
    if flag_name not in DEFAULT_FEATURE_FLAGS:
        raise ValueError(f"Unknown feature flag: {flag_name}")

    overrides = _get_feature_overrides()
    overrides[flag_name] = value
    _save_feature_overrides(overrides)


def list_feature_flags() -> dict[str, dict[str, bool]]:
    """Return all feature flags with their default role map."""
    return dict(DEFAULT_FEATURE_FLAGS)


def get_feature_overrides() -> dict[str, bool]:
    return dict(_get_feature_overrides())


def _get_feature_overrides() -> dict[str, bool]:
    global _feature_overrides
    if _feature_overrides is None:
        data = _get_data()
        _feature_overrides = dict(data.get("feature_overrides", {}))
    return _feature_overrides


def _save_feature_overrides(overrides: dict[str, bool]) -> None:
    global _feature_overrides
    _feature_overrides = dict(overrides)
    data = _get_data()
    data["feature_overrides"] = dict(overrides)
    _save_data(data)


# ─── Session ↔ User mapping ────────────────────────────────────────────

# Maps Hermes session tokens → user IDs
# This bridges the existing auth.py session system with multi-user
_session_user_map: dict[str, str] = {}
_session_user_lock = __import__("threading").Lock()


def associate_session(session_token: str, user_id: str) -> None:
    """Associate a session token with a user ID."""
    with _session_user_lock:
        _session_user_map[session_token] = user_id


def get_session_user(session_token: str) -> str | None:
    """Get the user ID associated with a session token."""
    with _session_user_lock:
        return _session_user_map.get(session_token)


def remove_session_association(session_token: str) -> None:
    """Remove a session→user mapping."""
    with _session_user_lock:
        _session_user_map.pop(session_token, None)


# ─── Bootstrap helper for the React app ────────────────────────────────


def build_bootstrap(user: dict[str, Any]) -> dict[str, Any]:
    """Build the bootstrap response for the React app (GET /api/auth/me)."""
    user_clean = _strip_secrets(user)
    return {
        "ok": True,
        "user": user_clean,
        "permissions": {
            "role": user["role"],
            "role_level": ROLE_HIERARCHY.get(user["role"], 0),
        },
        "features": get_feature_flags(user["role"]),
    }
