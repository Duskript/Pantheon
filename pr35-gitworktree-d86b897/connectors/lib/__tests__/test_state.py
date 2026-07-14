"""
test_state.py — Tests for lib/state.py.

Covers:
- Save/load roundtrip preserves all keys.
- Loading a missing file returns the empty-state defaults (no crash).
- Loading a corrupt file returns the empty-state defaults.
- update_state() bumps ``items_processed`` and the cursor.
- update_state() caps the error list at 20 entries.
- Concurrent saves (multiple threads) produce a valid file — no torn writes.
- save_state() is atomic: a partially-written temp file is never visible
  at the final path.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from lib import state as state_mod
from lib.state import (
    empty_state,
    load_state,
    save_state,
    update_state,
)


@pytest.fixture
def tmp_state_root(tmp_path, monkeypatch):
    """Redirect STATE_ROOT to a tmp dir for the duration of one test."""
    monkeypatch.setattr(state_mod, "STATE_ROOT", tmp_path)
    return tmp_path


# ─── roundtrip ──────────────────────────────────────────────────────


def test_save_and_load_roundtrip(tmp_state_root):
    payload = {
        "source": "youtube_takeout",
        "user_id": "konan",
        "last_run": "2026-06-16T07:00:00Z",
        "last_cursor": "2026-06-15T07:00:00Z",
        "items_processed": 47,
        "oauth_expires": "2026-07-16T07:00:00Z",
        "errors": ["once upon a time"],
        "extra_connector_field": "ok",
    }
    save_state("konan", "youtube_takeout", payload)
    loaded = load_state("konan", "youtube_takeout")
    # All keys round-trip; JSON is faithful for the values we use here.
    assert loaded == payload


def test_load_missing_returns_empty_state(tmp_state_root):
    loaded = load_state("konan", "never_existed")
    expected = empty_state("konan", "never_existed")
    assert loaded == expected
    assert loaded["items_processed"] == 0
    assert loaded["errors"] == []
    assert loaded["last_run"] is None
    assert loaded["last_cursor"] is None


def test_load_corrupt_file_returns_empty_state(tmp_state_root):
    path = tmp_state_root / "konan" / "broken.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is not valid json", encoding="utf-8")

    loaded = load_state("konan", "broken")
    assert loaded == empty_state("konan", "broken")


def test_load_non_dict_file_returns_empty_state(tmp_state_root):
    """If the file is valid JSON but not an object, treat as corrupt."""
    path = tmp_state_root / "konan" / "list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[1, 2, 3]", encoding="utf-8")

    loaded = load_state("konan", "list")
    assert loaded == empty_state("konan", "list")


def test_load_partial_file_merges_with_defaults(tmp_state_root):
    """A file with only some keys should still expose the default ones."""
    path = tmp_state_root / "konan" / "partial.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"items_processed": 9}), encoding="utf-8")

    loaded = load_state("konan", "partial")
    assert loaded["items_processed"] == 9
    assert loaded["source"] == "partial"  # identity field re-stamped
    assert loaded["user_id"] == "konan"  # identity field re-stamped
    assert loaded["errors"] == []  # default
    assert loaded["last_run"] is None  # default


# ─── update_state ───────────────────────────────────────────────────


def test_update_state_bumps_cursor_and_count(tmp_state_root):
    update_state(
        "konan", "demo",
        cursor="2026-06-15T07:00:00Z",
        items_added=3,
    )
    loaded = load_state("konan", "demo")
    assert loaded["last_cursor"] == "2026-06-15T07:00:00Z"
    assert loaded["items_processed"] == 3
    # last_run is set to "now"; just confirm it's a non-empty Z-suffixed string.
    assert loaded["last_run"] is not None
    assert loaded["last_run"].endswith("Z")


def test_update_state_appends_errors_and_caps_at_20(tmp_state_root):
    for i in range(25):
        update_state("konan", "errs", error=f"err-{i}")
    loaded = load_state("konan", "errs")
    assert len(loaded["errors"]) == 20
    # The cap drops the oldest, so we should see err-5..err-24.
    assert loaded["errors"][0] == "err-5"
    assert loaded["errors"][-1] == "err-24"


def test_update_state_without_args_writes_run_timestamp(tmp_state_root):
    update_state("konan", "ts")
    loaded = load_state("konan", "ts")
    assert loaded["last_run"] is not None
    assert loaded["last_cursor"] is None  # not touched
    assert loaded["items_processed"] == 0  # not touched


# ─── atomicity + concurrency ───────────────────────────────────────


def test_save_state_writes_to_temp_then_renames(tmp_state_root):
    """After save_state, no .tmp files remain in the user's state dir."""
    save_state("konan", "atomic", {"k": "v"})
    user_dir = tmp_state_root / "konan"
    leftovers = list(user_dir.glob("*.tmp"))
    assert leftovers == []
    # The final file is the only thing in the dir.
    finals = list(user_dir.glob("*.json"))
    assert [p.name for p in finals] == ["atomic.json"]


def test_concurrent_saves_produce_valid_file(tmp_state_root):
    """Many threads writing the same path should leave a single valid JSON file.

    ``os.replace`` is atomic per-write; the per-path lock serializes
    in-process writers. We assert the end state is parseable and contains
    one of the values that was written.
    """
    n_threads = 20
    barrier = threading.Barrier(n_threads)

    def writer(i: int) -> None:
        barrier.wait()  # all threads start at once
        save_state("konan", "concurrent", {"writer": i, "n": i * 10})

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        for i in range(n_threads):
            ex.submit(writer, i)

    # File exists, is valid JSON, and is a dict.
    path = tmp_state_root / "konan" / "concurrent.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert "writer" in data
    assert "n" in data


def test_concurrent_updates_accumulate_items(tmp_state_root):
    """N threads each adding M items should sum to N*M in the count."""
    n_threads = 8
    per_thread = 5

    def worker() -> None:
        update_state("konan", "counter", items_added=per_thread)

    with ThreadPoolExecutor(max_workers=n_threads) as ex:
        for _ in range(n_threads):
            ex.submit(worker)

    loaded = load_state("konan", "counter")
    assert loaded["items_processed"] == n_threads * per_thread


def test_save_state_forces_identity_fields(tmp_state_root):
    """Even if the caller lies about source/user_id, the saved file tells the truth."""
    save_state(
        "konan", "identity",
        {"source": "WRONG", "user_id": "WRONG", "k": "v"},
    )
    loaded = load_state("konan", "identity")
    assert loaded["source"] == "identity"
    assert loaded["user_id"] == "konan"


# ─── validation ────────────────────────────────────────────────────


def test_load_state_rejects_empty_user_id():
    with pytest.raises(ValueError):
        load_state("", "x")


def test_load_state_rejects_empty_source():
    with pytest.raises(ValueError):
        load_state("konan", "")


def test_save_state_creates_user_directory(tmp_state_root):
    save_state("new_user", "first_connector", {"k": "v"})
    assert (tmp_state_root / "new_user" / "first_connector.json").is_file()
