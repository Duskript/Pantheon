"""
state.py — Per-connector persistent state for the Pantheon connector library.

State is stored as JSON at ``~/pantheon/connectors/state/{user_id}/{source}.json``.
Writes are atomic: write to a temp file in the same directory, then ``os.replace``
(so it's atomic on POSIX and Windows). Reads tolerate a missing or malformed
file by returning a fresh empty state — connectors are best-effort and should
recover gracefully from first run, partial state, or corruption.

Schema (per design doc Appendix B):

    {
        "source": "youtube_takeout",
        "user_id": "konan",
        "last_run": "2026-06-16T07:00:00Z",
        "last_cursor": "2026-06-15T07:00:00Z",
        "items_processed": 47,
        "oauth_expires": "2026-07-16T07:00:00Z",  # optional, only for OAuth connectors
        "errors": []                                 # optional, list[str]
    }
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


# State directory root. Resolved at import time so tests can override via
# ``monkeypatch.setattr(state, 'STATE_ROOT', tmp_path)``.
STATE_ROOT = Path(os.path.expanduser("~/pantheon/connectors/state"))


# Per-process lock pool. ``state.py`` may be called from many connector
# instances concurrently, so we key locks on the absolute file path. This is
# sufficient for the single-process scheduler use case; the file-level
# ``os.replace`` provides cross-process atomicity.
_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    """Return a process-local lock for ``path``, creating it on first use."""
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def _state_path(user_id: str, source: str) -> Path:
    """Return the on-disk path for a (user, source) state file."""
    if not user_id:
        raise ValueError("user_id must be a non-empty string")
    if not source:
        raise ValueError("source must be a non-empty string")
    return STATE_ROOT / user_id / f"{source}.json"


def empty_state(user_id: str, source: str) -> Dict[str, Any]:
    """Return a fresh, schema-conformant empty state dict for ``(user_id, source)``."""
    return {
        "source": source,
        "user_id": user_id,
        "last_run": None,
        "last_cursor": None,
        "items_processed": 0,
        "errors": [],
    }


def load_state(user_id: str, source: str) -> Dict[str, Any]:
    """Load state for ``(user_id, source)``.

    Returns the schema-conformant empty state if the file does not exist or
    is malformed. Never raises on missing/corrupt files — the goal is "the
    connector can always start, even from a bad state."

    Parameters
    ----------
    user_id
        Tenant identifier (e.g. ``"konan"``). The Athenaeum is single-tenant
        today but every connector takes a ``user_id`` so the multi-tenant
        path is open.
    source
        Connector name (e.g. ``"youtube_takeout"``). Must match the
        ``ConnectorBase.name`` field.

    Returns
    -------
    dict
        A state dict. Always has at least the keys from :func:`empty_state`.
    """
    path = _state_path(user_id, source)
    if not path.is_file():
        return empty_state(user_id, source)

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        # Corrupt or unreadable — start fresh. The connector will likely
        # re-process some items, but that's safer than crashing the cron.
        return empty_state(user_id, source)

    if not isinstance(data, dict):
        return empty_state(user_id, source)

    # Merge with the empty-state defaults so a partially-written file still
    # has the keys downstream code expects.
    merged = empty_state(user_id, source)
    merged.update(data)
    # Re-stamp identity fields in case the file lied about them.
    merged["source"] = source
    merged["user_id"] = user_id
    return merged


def save_state(user_id: str, source: str, data: Dict[str, Any]) -> Path:
    """Atomically write ``data`` as the state for ``(user_id, source)``.

    The write is performed in two steps: write to a temp file in the same
    directory (so ``os.replace`` is atomic), then ``os.replace`` onto the
    final path. The temp file uses ``dir=path.parent`` so the rename is
    guaranteed to be a same-filesystem operation.

    A per-path ``threading.Lock`` prevents interleaved writes from clobbering
    each other inside a single process (e.g. parallel connector runs from
    ``run.py``). The atomic ``os.replace`` covers cross-process safety.

    Parameters
    ----------
    user_id
        Tenant identifier.
    source
        Connector name.
    data
        State dict to persist. ``user_id`` and ``source`` keys are forced to
        match the parameters.

    Returns
    -------
    pathlib.Path
        The path the state was written to.
    """
    path = _state_path(user_id, source)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Force identity fields — never trust the caller to keep these in sync.
    payload = dict(data)
    payload["source"] = source
    payload["user_id"] = user_id

    lock = _lock_for(path)
    with lock:
        # ``delete=False`` so we can name the file; ``dir=path.parent`` to
        # guarantee same-filesystem rename.
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=str(path.parent),
        )
        tmp_path = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.write("\n")  # POSIX-friendly trailing newline
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup of the orphan temp file.
            try:
                tmp_path.unlink()
            except OSError:
                pass
            raise

    return path


def update_state(
    user_id: str,
    source: str,
    *,
    cursor: str | None = None,
    items_added: int = 0,
    error: str | None = None,
    run_started_at: datetime | None = None,
) -> Dict[str, Any]:
    """Convenience helper: load, merge in a delta, save, return the new state.

    Use this in a connector's ``run()`` method to update the cursor and item
    count in a single call. ``error`` appends to the ``errors`` list (which is
    capped at the 20 most recent entries to keep the state file small).

    Parameters
    ----------
    user_id, source
        See :func:`load_state`.
    cursor
        New value for ``last_cursor``. ``None`` leaves it unchanged.
    items_added
        Number of items processed in this run; added to ``items_processed``.
    error
        Error message to append to ``errors``; ``None`` adds nothing.
    run_started_at
        Timestamp written to ``last_run``. Defaults to ``now`` (UTC).

    Returns
    -------
    dict
        The updated state (also written to disk).
    """
    # The full read-modify-write must be inside the lock, otherwise
    # concurrent updates race on the read (load_state is unlocked).
    # save_state takes the same path's lock, so we lock here first to
    # serialize both the read and the write.
    path = _state_path(user_id, source)
    lock = _lock_for(path)
    with lock:
        state = load_state(user_id, source)
        if cursor is not None:
            state["last_cursor"] = cursor
        if items_added:
            state["items_processed"] = int(state.get("items_processed", 0)) + items_added

        now = (run_started_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        state["last_run"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")

        if error is not None:
            errors = list(state.get("errors", []))
            errors.append(error)
            # Cap the error list — state files should stay small.
            state["errors"] = errors[-20:]

        # save_state will re-acquire the same lock; threading.Lock is
        # non-reentrant but the inner call goes via the same lock object
        # we already hold. Use a private internal that skips re-locking.
        _save_state_locked(user_id, source, state)
    return state


def _save_state_locked(user_id: str, source: str, data: Dict[str, Any]) -> Path:
    """Internal: write state file assuming the path's lock is already held.

    Same shape as :func:`save_state` but does not acquire the per-path
    lock. Use this when the caller already holds the lock (e.g.
    :func:`update_state`) to avoid the deadlock that would occur if a
    reentrant lock tried to acquire itself.
    """
    path = _state_path(user_id, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data)
    payload["source"] = source
    payload["user_id"] = user_id

    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    return path
