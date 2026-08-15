"""Conductor v2 shared authentication helpers.

Per the Synergy WB port adapter spec §6, the three Conductor HTTP surfaces
(api_server, webhook, live_stream) share a single bearer token. This
module centralizes the auth logic so each surface enforces it the same
way.

The token is sourced from the ``CONDUCTOR_API_KEY`` env var (or
``CONDUCTOR_WS_API_KEY`` as a legacy alias — the live stream historically
used that name). When unset, auth is disabled — a dev/test footgun, but
useful for local development. The production daemon sets the env var in
``~/.hermes/.env``.

Two surfaces, two helper shapes:

  * ``require_bearer`` — FastAPI dependency. Returns the validated token,
    or raises 401/403. Used by api_server.py and webhook.py.
  * ``check_query_key`` — plain function. Returns True/False. Used by
    aiohttp handlers (live_stream.py) that need to inspect ``?api_key=``
    before the WebSocket handshake completes (browsers cannot send
    custom headers on the WebSocket upgrade request).

Both helpers accept the same token resolution rule: explicit arg > env
var. Callers pass the env-resolved token at startup, then the helpers
do constant-time comparison at request time.
"""
from __future__ import annotations

import functools
import hmac
import os
from pathlib import Path
from typing import Optional

# Header / query key the client sends. Spec §6 picks `Authorization:
# Bearer <token>` for the JSON API and `?api_key=<token>` for the WS
# endpoint (browsers cannot customize the WebSocket upgrade request
# headers). We honor BOTH on the JSON API — `?api_key=` is provided for
# parity so SDK consumers that prefer the query form don't need a
# second code path.
BEARER_HEADER = "Authorization"
QUERY_KEY = "api_key"

# Env var names. CONDUCTOR_API_KEY is the canonical name (per spec §6);
# CONDUCTOR_WS_API_KEY is the legacy name for the live stream — kept as
# a fallback so existing operator config (which uses the older name)
# keeps working. New deployments should set CONDUCTOR_API_KEY.
API_KEY_ENV = "CONDUCTOR_API_KEY"
LEGACY_WS_API_KEY_ENV = "CONDUCTOR_WS_API_KEY"

# Operator's global hermes env file. We read this when the process env
# doesn't have the key set, so the operator can put CONDUCTOR_API_KEY
# in their global hermes config and the conductor daemon picks it up
# without an explicit `export`. The first candidate that exists wins;
# the others are skipped. Per-process env (os.environ) always wins
# over the file — that way `CONDUCTOR_API_KEY=... uvicorn ...` still
# works in CI and tests.
_HERMES_ENV_CANDIDATES = (
    Path.home() / ".hermes" / ".env",
    Path.home() / "pantheon" / "conductor" / "v2" / ".env",
)


def _parse_env_line(line: str) -> Optional[tuple[str, str]]:
    """Parse a single `KEY=value` line from a .env file.

    Returns (key, value) on success, None on blank/comment lines.
    Strips optional surrounding quotes (single or double) from the
    value. Trailing `# comments` are NOT stripped (a value with a `#`
    in it would survive — this matches bash/dotenv semantics closely
    enough for our use case, which is `KEY=long-random-hex` lines).
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if "=" not in stripped:
        return None
    key, _, value = stripped.partition("=")
    key = key.strip()
    value = value.strip()
    # Strip surrounding quotes if present (the only kind of value the
    # operator is likely to put a quote in is a quoted token).
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not key:
        return None
    return key, value


@functools.lru_cache(maxsize=1)
def _read_env_file(path: Path) -> dict[str, str]:
    """Read a .env file and return its key/value pairs as a dict.

    Missing or unreadable file → empty dict (not an error; the caller
    falls through to the next candidate). Cached for the life of the
    process so we don't re-parse on every request; the operator
    restarts the daemon to pick up edits. Raises nothing.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        key, value = parsed
        out[key] = value
    return out


def _read_hermes_api_key() -> str:
    """Return CONDUCTOR_API_KEY (or the legacy alias) from the first
    operator .env file we can find. Returns "" when neither file has
    the key set — callers fall through to the dev-mode disabled path.
    """
    for candidate in _HERMES_ENV_CANDIDATES:
        env = _read_env_file(candidate)
        if not env:
            continue
        # Prefer the canonical name; fall back to the legacy alias so
        # existing operator config keeps working.
        key = env.get(API_KEY_ENV) or env.get(LEGACY_WS_API_KEY_ENV, "")
        if key:
            return key
    return ""


def resolve_api_key(explicit: Optional[str] = None) -> str:
    """Return the configured API key, honoring the resolution order:

      1. Explicit argument (used by tests, which pass a known key).
      2. ``CONDUCTOR_API_KEY`` process env var (canonical name per
         spec §6). Wins over the .env file so a one-off
         ``CONDUCTOR_API_KEY=... uvicorn ...`` still works in CI.
      3. ``CONDUCTOR_WS_API_KEY`` process env var (legacy alias for
         the live stream — kept for back-compat with existing
         operator config).
      4. ``CONDUCTOR_API_KEY`` from ``~/.hermes/.env`` (operator's
         global hermes env file). Lets the operator set the key once
         in their global hermes config and have the conductor daemon
         pick it up without an explicit `export` at startup.
      5. ``CONDUCTOR_WS_API_KEY`` from the same .env file (legacy
         alias, same reasoning as step 3).
      6. ``~/pantheon/conductor/v2/.env`` — the conductor's local
         env file, checked as a defensive fallback for operators who
         keep conductor-specific config in a sub-directory.
      7. Empty string (auth disabled — dev/test mode).

    Returns the empty string when no key is configured. Callers should
    log a warning when starting in that state (the live_stream does).
    """
    if explicit is not None:
        return explicit
    # Process env wins over the .env file (steps 2-3 over 4-6).
    proc = os.environ.get(API_KEY_ENV) or os.environ.get(LEGACY_WS_API_KEY_ENV, "")
    if proc:
        return proc
    # File fallback (steps 4-6, collapsed into the helper).
    return _read_hermes_api_key()


def _extract_bearer_token(authorization_header: Optional[str], query_key: Optional[str]) -> str:
    """Pull the token from either the Authorization header or the
    `?api_key=` query string. Returns empty string if neither is set.

    The Authorization header takes precedence: it's the spec-default and
    is harder to leak in logs.
    """
    if authorization_header:
        # Standard `Bearer <token>` shape per RFC 6750. We accept the
        # header as long as it starts with "Bearer " (case-insensitive)
        # and a non-empty token follows. Anything else → empty.
        scheme, _, token = authorization_header.partition(" ")
        if scheme.lower() == "bearer" and token:
            return token.strip()
    if query_key:
        return query_key.strip()
    return ""


def check_token(provided: str, expected: str) -> bool:
    """Constant-time token comparison.

    Returns True iff both the provided and expected tokens are non-empty
    AND match. Empty expected = auth disabled (dev mode); the test suite
    relies on this behavior. Empty provided is rejected even when
    expected is non-empty (so a missing header doesn't accidentally
    pass).

    hmac.compare_digest is used (rather than ``==``) to avoid leaking
    the expected length via timing. The token isn't a high-value secret,
    but constant-time comparison is the right default — it costs
    nothing and removes one footgun.
    """
    if not expected:
        # Auth disabled — every request is allowed. The caller is
        # expected to have logged a warning at startup.
        return True
    if not provided:
        return False
    # hmac.compare_digest requires equal-length strings. Pad the
    # shorter side to the longer so a short provided token doesn't
    # fast-fail on length comparison. (The token is short, so the
    # timing leak from unequal lengths is negligible; this is
    # belt-and-suspenders.)
    if len(provided) != len(expected):
        # Still run a compare so the timing is roughly constant for
        # attackers who can measure; the result is always False here.
        hmac.compare_digest(provided.ljust(len(expected), "\0"), expected)
        return False
    return hmac.compare_digest(provided, expected)


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

# Module-level slot for the expected API key. Set by `set_expected_api_key()`
# when the app is constructed, or read from the env var on first use.
# A FastAPI dependency can't easily take a constructor arg, so we use
# this module-level indirection — the alternative (a per-route closure)
# works but is more boilerplate.
_EXPECTED_API_KEY: Optional[str] = None


def set_expected_api_key(api_key: Optional[str]) -> None:
    """Bind the expected API key for the current process.

    Called by `make_app(..., api_key=...)` so a single process can run
    with a known key even when the env var is unset (tests). Idempotent.
    Passing `None` clears the binding and re-enables env-var resolution.
    """
    global _EXPECTED_API_KEY
    _EXPECTED_API_KEY = api_key


def _expected_for_request() -> str:
    """Return the API key to use for the current request.

    Resolution order: module-level binding (set by make_app) > env var
    > empty. The module-level binding wins so a test that sets a known
    key isn't accidentally overridden by an env var in the developer's
    shell.
    """
    if _EXPECTED_API_KEY is not None:
        return _EXPECTED_API_KEY
    return resolve_api_key()


def _validate_bearer(authorization: Optional[str], api_key_query: Optional[str]) -> str:
    """Inner validator — split out from `require_bearer` so the
    `HTTPException` import is lazy (FastAPI is the only caller) and
    the logic is unit-testable without spinning up an app.

    Auth-disabled semantics: if no API key is configured (neither via
    ``set_expected_api_key()`` nor the env var), the validator is a
    no-op. This matches the live_stream's behavior (it logs a warning
    at startup and lets every connection through). Without this, every
    dev-mode request would need a token that nobody told the client.

    Returns the validated token on success. Raises HTTPException on
    failure. The error split is per RFC 6750:
      * 401 — no credentials supplied (caller should retry with creds)
      * 403 — credentials supplied but invalid (caller should fix creds)
    """
    from fastapi import HTTPException

    expected_key = _expected_for_request()
    if not expected_key:
        # Auth disabled — every request is allowed. The provided
        # token is still extracted (so a misconfigured client that
        # sends a stale token doesn't see surprising behavior), but
        # the comparison is skipped.
        return _extract_bearer_token(authorization, api_key_query) or ""

    provided = _extract_bearer_token(authorization, api_key_query)
    if not provided:
        # No token at all. 401 (not 403) — RFC 7235 says the client
        # should respond by retrying with credentials.
        raise HTTPException(
            status_code=401,
            detail="missing bearer token (Authorization: Bearer *** or ?api_key=)",
            headers={"WWW-Authenticate": 'Bearer realm="conductor"'},
        )
    if not check_token(provided, expected_key):
        raise HTTPException(
            status_code=403,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="conductor"'},
        )
    return provided


def require_bearer(
    authorization: Optional[str] = None,
    api_key_query: Optional[str] = None,
) -> str:
    """FastAPI dependency. Validates the bearer token and returns it.

    Usage in a route::

        from fastapi import Depends
        from .auth import require_bearer

        @app.get("/api/foo", dependencies=[Depends(require_bearer)])
        async def foo(): ...

    The expected key is read from the module-level binding (set by
    ``set_expected_api_key()`` when ``make_app(..., api_key=...)`` is
    called), or from the ``CONDUCTOR_API_KEY`` env var as a fallback.

    For the per-route wiring, the helper accepts ``Authorization`` as a
    header and ``api_key`` as a query parameter — see
    ``bearer_dependency()`` for the full Depends-wrapped version that
    pulls those from the request.

    Raises HTTPException(401) when no token is supplied, 403 when the
    token is wrong. See `_validate_bearer` for the rationale.
    """
    return _validate_bearer(authorization, api_key_query)


def bearer_dependency():
    """Build a FastAPI dependency callable that pulls the Authorization
    header and the `?api_key=` query string from the request and runs
    the bearer-token check.

    Why a factory: FastAPI's ``Depends()`` resolves parameter names
    against the request, and it needs the parameter types to be
    ``Header(...)`` / ``Query(...)`` for FastAPI to wire them up
    correctly. A function that takes raw kwargs doesn't work — we need
    a wrapper that declares the FastAPI metadata.

    Usage in a route::

        from .auth import bearer_dependency
        auth = bearer_dependency()

        @app.get("/api/foo", dependencies=[Depends(auth)])
        async def foo(): ...
    """
    from fastapi import Header, Query, Depends

    async def _dep(
        authorization: Optional[str] = Header(default=None, alias="Authorization"),
        api_key_query: Optional[str] = Query(default=None, alias="api_key"),
    ) -> str:
        return _validate_bearer(authorization, api_key_query)

    return _dep


# ---------------------------------------------------------------------------
# aiohttp / WebSocket helper
# ---------------------------------------------------------------------------

def check_query_key(provided: str, expected: Optional[str] = None) -> bool:
    """Validate a token from the `?api_key=` query string.

    Used by the live stream's WebSocket handler. The browser cannot
    send a custom Authorization header on the WS upgrade request, so
    the spec §6 keeps the legacy query-string shape for that surface.
    The api_server (JSON) accepts BOTH the header and the query param.

    Returns True when the request is authorized. False when rejected.
    Empty `expected` means auth disabled.
    """
    expected_key = expected if expected is not None else resolve_api_key()
    return check_token(provided, expected_key)
