"""
Olympus Backend — FastAPI service for Olympus UI

Provides:
- Authentication (login/logout with JWT)
- User management (CRUD)
- Feature flags (GET/PUT)
- Theme (GET/PUT)
- Athenaeum browse (walk, read, search)
- Stream metrics (entities, edges, metrics)

Data storage: ~/pantheon/data/olympus/
Run: uvicorn main:app --host 127.0.0.1 --port 8788
"""

import os
import json
import hashlib
import secrets
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Paths ─────────────────────────────────────────────────

PANTHEON_HOME = Path(os.environ.get("PANTHEON_HOME", str(Path.home() / "pantheon")))
DATA_DIR = PANTHEON_HOME / "data" / "olympus"
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
FEATURE_FLAGS_FILE = DATA_DIR / "feature-flags.json"
THEME_FILE = PANTHEON_HOME / "config" / "olympus-theme.yaml"

# Ensure config dir
(PANTHEON_HOME / "config").mkdir(parents=True, exist_ok=True)

# ─── Logging ───────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("olympus-backend")

# ─── App ───────────────────────────────────────────────────

app = FastAPI(
    title="Olympus Backend",
    version="0.1.0",
    description="Backend service for Olympus UI",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Simple password hashing (bcrypt-like using hashlib) ────
# Note: In production, use bcrypt. This is a simplified version.

def hash_password(password: str) -> str:
    """Hash a password with salt."""
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100000)
    return f"pbkdf2:sha256:100000:{salt}:{h.hex()}"


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    try:
        _algo, _hash_name, _iterations, salt, stored = hashed.split(":")
        h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(_iterations))
        return h.hex() == stored
    except Exception:
        return False


# ─── Simple JWT (HS256-compatible) ─────────────────────────

JWT_SECRET = os.environ.get("OLYMPUS_JWT_SECRET", secrets.token_hex(32))
TOKEN_EXPIRY_HOURS = 24

def create_token(payload: dict) -> str:
    """Create a simple signed token."""
    header = {"alg": "HS256", "typ": "JWT"}
    body = {
        **payload,
        "iat": int(time.time()),
        "exp": int(time.time()) + TOKEN_EXPIRY_HOURS * 3600,
    }
    # Simple encoding (not real JWT, but works for this scope)
    data = json.dumps({"header": header, "body": body})
    sig = hashlib.sha256(f"{data}.{JWT_SECRET}".encode()).hexdigest()
    token = f"{data}.{sig}"
    return token

def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a token."""
    try:
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return None
        data_str, sig = parts
        expected_sig = hashlib.sha256(f"{data_str}.{JWT_SECRET}".encode()).hexdigest()
        if sig != expected_sig:
            return None
        data = json.loads(data_str)
        body = data.get("body", {})
        if body.get("exp", 0) < int(time.time()):
            return None
        return body
    except Exception:
        return None

# ─── Auth dependency ───────────────────────────────────────

async def require_auth(request: Request) -> dict:
    """Require a valid token in the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = auth[7:]
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


async def optional_auth(request: Request) -> Optional[dict]:
    """Optionally decode a token."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return verify_token(auth[7:])


# ─── User helpers ──────────────────────────────────────────

def load_users() -> list[dict]:
    """Load users from JSON file."""
    if not USERS_FILE.exists():
        return []
    return json.loads(USERS_FILE.read_text())


def save_users(users: list[dict]) -> None:
    """Save users to JSON file."""
    USERS_FILE.write_text(json.dumps(users, indent=2, default=str))


def ensure_owner_exists() -> None:
    """Create an owner user if no users exist."""
    users = load_users()
    if not users:
        owner = {
            "id": secrets.token_hex(8),
            "username": "owner",
            "display_name": "Owner",
            "password_hash": hash_password("olympus"),
            "role": "owner",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login_at": None,
            "color": "#6050b0",
            "avatar": None,
            "disabled": False,
        }
        save_users([owner])
        logger.info("Created default owner user (username: owner, password: olympus)")


def load_feature_flags() -> dict:
    """Load feature flags from JSON file."""
    if not FEATURE_FLAGS_FILE.exists():
        return {}
    return json.loads(FEATURE_FLAGS_FILE.read_text())


def save_feature_flags(flags: dict) -> None:
    """Save feature flags to JSON file."""
    FEATURE_FLAGS_FILE.write_text(json.dumps(flags, indent=2))


def load_theme() -> dict:
    """Load theme config from YAML file."""
    if not THEME_FILE.exists():
        return {"colors": {}, "terminology": {}}
    import yaml  # Optional import
    try:
        return yaml.safe_load(THEME_FILE.read_text()) or {}
    except Exception:
        return {"colors": {}, "terminology": {}}


def save_theme(theme: dict) -> None:
    """Save theme config to YAML file."""
    import yaml
    THEME_FILE.write_text(yaml.dump(theme, default_flow_style=False))


# ─── Request/Response models ───────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class LoginResponse(BaseModel):
    token: str
    user: dict

class CreateUserRequest(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "user"

class UpdateUserRequest(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    disabled: Optional[bool] = None
    color: Optional[str] = None

class FeatureFlagsRequest(BaseModel):
    flags: dict[str, bool]

class ThemeRequest(BaseModel):
    theme: dict


# ─── Health check ──────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "olympus-backend"}


# ─── Auth endpoints ────────────────────────────────────────

@app.post("/api/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    ensure_owner_exists()
    users = load_users()
    user = next((u for u in users if u["username"] == body.username), None)
    if not user or not verify_password(body.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if user.get("disabled"):
        raise HTTPException(status_code=403, detail="Account is disabled")

    # Update last login
    for u in users:
        if u["id"] == user["id"]:
            u["last_login_at"] = datetime.now(timezone.utc).isoformat()
    save_users(users)

    token = create_token({"sub": user["id"], "username": user["username"], "role": user["role"]})
    return LoginResponse(
        token=token,
        user={
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "role": user["role"],
            "color": user.get("color"),
            "avatar": user.get("avatar"),
            "created_at": user["created_at"],
            "last_login_at": user.get("last_login_at"),
        },
    )


@app.post("/api/auth/logout")
async def logout(payload: dict = Depends(require_auth)):
    # Token-based auth: client should discard token
    return {"ok": True}


@app.get("/api/auth/me")
async def me(payload: dict = Depends(require_auth)):
    users = load_users()
    user = next((u for u in users if u["id"] == payload["sub"]), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "display_name": user.get("display_name", user["username"]),
            "role": user["role"],
            "color": user.get("color"),
            "avatar": user.get("avatar"),
            "created_at": user["created_at"],
            "last_login_at": user.get("last_login_at"),
        },
        "features": load_feature_flags(),
    }


# ─── User management ───────────────────────────────────────

@app.get("/api/users")
async def list_users(payload: dict = Depends(require_auth)):
    """List all users. Requires auth."""
    users = load_users()
    # Strip password hashes
    return {
        "users": [
            {
                "id": u["id"],
                "username": u["username"],
                "display_name": u.get("display_name", u["username"]),
                "role": u["role"],
                "color": u.get("color"),
                "avatar": u.get("avatar"),
                "created_at": u["created_at"],
                "last_login_at": u.get("last_login_at"),
                "disabled": u.get("disabled", False),
            }
            for u in users
        ]
    }


@app.post("/api/users")
async def create_user(body: CreateUserRequest, payload: dict = Depends(require_auth)):
    """Create a new user. Requires auth (admin/owner)."""
    if payload.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    users = load_users()
    if any(u["username"] == body.username for u in users):
        raise HTTPException(status_code=409, detail="Username already exists")

    new_user = {
        "id": secrets.token_hex(8),
        "username": body.username,
        "display_name": body.display_name or body.username,
        "password_hash": hash_password(body.password),
        "role": body.role,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login_at": None,
        "color": None,
        "avatar": None,
        "disabled": False,
    }
    users.append(new_user)
    save_users(users)

    return {
        "id": new_user["id"],
        "username": new_user["username"],
        "display_name": new_user["display_name"],
        "role": new_user["role"],
        "created_at": new_user["created_at"],
    }


@app.patch("/api/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserRequest, payload: dict = Depends(require_auth)):
    """Update a user. Requires auth (admin/owner)."""
    if payload.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    users = load_users()
    idx = next((i for i, u in enumerate(users) if u["id"] == user_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Cannot change own role to lower
    if users[idx]["id"] == payload.get("sub") and body.role and body.role != "owner":
        # Allow owner to demote themselves? Usually not recommended but allowed
        pass

    if body.display_name is not None:
        users[idx]["display_name"] = body.display_name
    if body.role is not None:
        users[idx]["role"] = body.role
    if body.disabled is not None:
        users[idx]["disabled"] = body.disabled
    if body.color is not None:
        users[idx]["color"] = body.color

    save_users(users)

    return {
        "id": users[idx]["id"],
        "username": users[idx]["username"],
        "display_name": users[idx].get("display_name", users[idx]["username"]),
        "role": users[idx]["role"],
        "disabled": users[idx].get("disabled", False),
    }


@app.delete("/api/users/{user_id}")
async def delete_user(user_id: str, payload: dict = Depends(require_auth)):
    """Delete a user. Requires auth (admin/owner). Cannot delete self."""
    if payload.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    if user_id == payload.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    users = load_users()
    users = [u for u in users if u["id"] != user_id]
    save_users(users)
    return {"ok": True}


# ─── Feature flags ─────────────────────────────────────────

DEFAULT_FEATURE_FLAGS = {
    "cron": True,
    "plugins": True,
    "skills": True,
    "mcp": True,
    "kanban": False,
    "webhooks": False,
    "terminal": True,
    "summon_god": True,
    "edit_god": True,
    "forge_god": True,
    "multi_user": False,
}


@app.get("/api/feature-flags")
async def get_feature_flags(_auth: Optional[dict] = Depends(optional_auth)):
    """Get feature flags. Public (no auth required)."""
    stored = load_feature_flags()
    merged = {**DEFAULT_FEATURE_FLAGS, **stored}
    return {"flags": merged, "defaults": DEFAULT_FEATURE_FLAGS}


@app.put("/api/feature-flags")
async def update_feature_flags(body: FeatureFlagsRequest, payload: dict = Depends(require_auth)):
    """Update feature flags. Requires auth (admin/owner)."""
    if payload.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Validate keys
    valid_keys = set(DEFAULT_FEATURE_FLAGS.keys())
    for key in body.flags:
        if key not in valid_keys:
            raise HTTPException(status_code=400, detail=f"Unknown flag: {key}")

    save_feature_flags(body.flags)
    return {"ok": True, "flags": {**DEFAULT_FEATURE_FLAGS, **body.flags}}


# ─── Theme ─────────────────────────────────────────────────

@app.get("/api/theme")
async def get_theme():
    """Get theme config."""
    theme = load_theme()
    return {"theme": theme}


@app.put("/api/theme")
async def update_theme(body: ThemeRequest, payload: dict = Depends(require_auth)):
    """Update theme config. Requires auth."""
    save_theme(body.theme)
    return {"ok": True, "theme": body.theme}


# ─── Athenaeum ─────────────────────────────────────────────

# Server-side: these proxy to the Pantheon Athenaeum.
# For now, return stubs that the frontend can use.

@app.get("/api/athenaeum/walk")
async def athenaeum_walk(path: str = Query(default="INDEX.md")):
    """Walk the Athenaeum file tree."""
    athenaeum_root = PANTHEON_HOME / "docs"
    target = (athenaeum_root / path).resolve()
    # Security: ensure path is within athenaeum_root
    if not str(target).startswith(str(athenaeum_root.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")

    if not target.exists():
        return {"path": path, "type": "not_found", "entries": []}

    if target.is_dir():
        entries = []
        for entry in sorted(target.iterdir()):
            entries.append({
                "name": entry.name,
                "type": "directory" if entry.is_dir() else "file",
                "path": str(entry.relative_to(athenaeum_root)),
            })
        return {"path": path, "type": "directory", "entries": entries}
    else:
        return {"path": path, "type": "file"}


@app.get("/api/athenaeum/read")
async def athenaeum_read(path: str = Query(default="")):
    """Read a file from the Athenaeum."""
    athenaeum_root = PANTHEON_HOME / "docs"
    target = (athenaeum_root / path).resolve()
    if not str(target).startswith(str(athenaeum_root.resolve())):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    content = target.read_text()
    lines = content.split("\n")
    return {"path": path, "content": content, "line_count": len(lines), "lines": lines}


@app.get("/api/athenaeum/search")
async def athenaeum_search(q: str = Query(default="")):
    """Search the Athenaeum (stub)."""
    return {"query": q, "results": [], "count": 0}


# ─── Stream ────────────────────────────────────────────────

@app.get("/api/stream/entities")
async def stream_entities():
    """Get stream entities (stub)."""
    return {"entities": [], "count": 0}


@app.get("/api/stream/edges")
async def stream_edges():
    """Get stream edges (stub)."""
    return {"edges": [], "count": 0}


@app.get("/api/stream/metrics")
async def stream_metrics():
    """Get stream metrics (stub)."""
    return {
        "storage": {"athenaeum_files": 0, "total_bytes": 0},
        "sources": 0,
        "chunks": 0,
        "entities": 0,
        "connections": 0,
        "trending": [],
    }


# ─── Bootstrap endpoint (matches existing /api/olympus/...) ─

@app.get("/api/olympus/auth/me")
async def olympus_auth_me(payload: Optional[dict] = Depends(optional_auth)):
    """Bootstrap: user info + features. Public with optional auth."""
    if payload:
        users = load_users()
        user = next((u for u in users if u["id"] == payload["sub"]), None)
        if user:
            return {
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "display_name": user.get("display_name", user["username"]),
                    "role": user["role"],
                    "color": user.get("color"),
                    "avatar": user.get("avatar"),
                },
                "features": {**DEFAULT_FEATURE_FLAGS, **load_feature_flags()},
            }

    # No auth — return defaults
    return {
        "user": None,
        "features": {**DEFAULT_FEATURE_FLAGS, **load_feature_flags()},
    }


@app.get("/api/olympus/features")
async def olympus_features():
    """Feature flags (legacy endpoint, matches existing api-client.ts)."""
    stored = load_feature_flags()
    merged = {**DEFAULT_FEATURE_FLAGS, **stored}
    return {"features": merged, "overrides": stored}


@app.post("/api/olympus/features")
async def olympus_features_update(body: FeatureFlagsRequest, payload: dict = Depends(require_auth)):
    """Update feature flags (legacy endpoint)."""
    if payload.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    save_feature_flags(body.flags)
    return {"ok": True}


@app.get("/api/olympus/features/definitions")
async def olympus_features_definitions():
    """Feature flag definitions (legacy endpoint)."""
    definitions = [
        {"key": k, "label": k.replace("_", " ").title(), "description": "", "default_enabled": v}
        for k, v in DEFAULT_FEATURE_FLAGS.items()
    ]
    return {"definitions": definitions}


# ─── Start ─────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    ensure_owner_exists()
    logger.info(f"Data directory: {DATA_DIR}")
    logger.info(f"JWT secret: {JWT_SECRET[:8]}...")
    logger.info("Starting Olympus Backend on http://127.0.0.1:8788")
    uvicorn.run(app, host="127.0.0.1", port=8788)
