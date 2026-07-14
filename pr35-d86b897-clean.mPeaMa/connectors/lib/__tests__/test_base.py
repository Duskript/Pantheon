"""
test_base.py — Tests for lib/base.py.

Covers:
- A minimal mock connector: instantiate, run the default loop, verify
  the items are written to the inbox.
- The default ``run()`` updates the state file with the new cursor and
  the dropped-item count.
- A connector that raises in ``authenticate()`` records the error in
  state and returns 0 (does not crash the cron).
- A connector that raises mid-``fetch_since()`` still updates the state
  with the run timestamp.
- A connector that fails to normalize a single item logs the error and
  continues with the rest.
- The ``name`` attribute is enforced (empty name → RuntimeError).
- ``normalize_default`` produces the same output as the library helper.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

import pytest

from lib import base as base_mod
from lib.base import ConnectorBase
from lib.normalize import RawItem
from lib import state as state_mod
from lib.state import load_state


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Redirect both STATE_ROOT and INBOX_DIR to tmp paths."""
    state_root = tmp_path / "state"
    inbox = tmp_path / "inbox"
    state_root.mkdir()
    inbox.mkdir()
    monkeypatch.setattr(state_mod, "STATE_ROOT", state_root)
    monkeypatch.setattr(base_mod, "INBOX_DIR", inbox)
    return {"state_root": state_root, "inbox": inbox}


class _MockConnector(ConnectorBase):
    """A minimal working connector used by most tests."""

    name = "mock"
    default_cadence = __import__("datetime").timedelta(hours=1)

    def __init__(self, items: Optional[List[RawItem]] = None, fail_on: str = ""):
        self._items = items or []
        self._fail_on = fail_on
        self.authenticated = False
        self.fetch_called_with: Optional[datetime] = None

    def authenticate(self) -> None:
        if self._fail_on == "auth":
            raise RuntimeError("simulated auth failure")
        self.authenticated = True

    def fetch_since(self, since):
        if self._fail_on == "fetch":
            raise RuntimeError("simulated fetch failure")
        self.fetch_called_with = since
        yield from self._items

    def normalize(self, item):
        if self._fail_on == "normalize":
            raise RuntimeError(f"simulated normalize failure for {item.item_id}")
        return self.normalize_default(item)


# ─── happy path ─────────────────────────────────────────────────────


def test_run_drops_items_into_inbox(isolated_paths):
    items = [
        RawItem(
            item_id="v1",
            title="First",
            url="https://example.com/1",
            content="body 1",
        ),
        RawItem(
            item_id="v2",
            title="Second",
            url="https://example.com/2",
            content="body 2",
            published_at=datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    c = _MockConnector(items=items)
    n = c.run()

    assert n == 2
    # Two markdown files in the inbox.
    inbox_files = sorted(isolated_paths["inbox"].glob("*.md"))
    assert len(inbox_files) == 2
    # Each file has the right shape.
    contents = [f.read_text(encoding="utf-8") for f in inbox_files]
    for body in contents:
        assert body.startswith("---\n")
        assert 'connector: "mock"' in body
    # State is updated.
    state = load_state("konan", "mock")
    assert state["items_processed"] == 2
    # The latest published_at became the cursor.
    assert state["last_cursor"] == "2026-06-15T12:00:00Z"
    assert state["last_run"] is not None


def test_run_picks_up_existing_cursor(isolated_paths):
    """If state has a last_cursor, run() passes it to fetch_since."""
    # Pre-seed state with a cursor.
    state_mod.save_state(
        "konan", "mock",
        {
            "source": "mock",
            "user_id": "konan",
            "last_cursor": "2026-06-01T00:00:00Z",
            "items_processed": 99,
            "errors": [],
        },
    )

    c = _MockConnector(items=[])
    c.run()

    assert c.fetch_called_with is not None
    assert c.fetch_called_with.year == 2026
    # Existing items_processed is preserved (we added 0).
    state = load_state("konan", "mock")
    assert state["items_processed"] == 99


def test_run_uses_caller_supplied_since(isolated_paths):
    """``run(since=...)`` overrides the state cursor."""
    state_mod.save_state(
        "konan", "mock",
        {
            "source": "mock",
            "user_id": "konan",
            "last_cursor": "2030-01-01T00:00:00Z",
            "items_processed": 0,
            "errors": [],
        },
    )

    c = _MockConnector(items=[])
    explicit = datetime(2025, 1, 1, tzinfo=timezone.utc)
    c.run(since=explicit)

    assert c.fetch_called_with == explicit


# ─── error paths ────────────────────────────────────────────────────


def test_run_records_auth_error_and_returns_zero(isolated_paths):
    c = _MockConnector(items=[
        RawItem(item_id="x1", title="t", url="u", content="c"),
    ], fail_on="auth")
    n = c.run()
    assert n == 0
    # Nothing landed in the inbox.
    assert list(isolated_paths["inbox"].glob("*.md")) == []
    # Error was recorded.
    state = load_state("konan", "mock")
    assert any("authenticate" in e for e in state["errors"])


def test_run_records_fetch_error_but_still_writes_run_timestamp(isolated_paths):
    c = _MockConnector(items=[], fail_on="fetch")
    n = c.run()
    assert n == 0
    state = load_state("konan", "mock")
    assert state["last_run"] is not None
    assert any("fetch_since" in e for e in state["errors"])


def test_run_continues_when_normalize_fails_on_one_item(isolated_paths):
    """A bad item shouldn't block the rest of the batch."""
    # We'll mark only the second item as a normalize failure by giving
    # the connector a custom list and toggling fail_on per-call. Easiest
    # approach: subclass with a list-of-failures.
    class _PartialFail(_MockConnector):
        def normalize(self, item):
            if item.item_id == "bad":
                raise RuntimeError("nope")
            return self.normalize_default(item)

    c = _PartialFail(items=[
        RawItem(item_id="good1", title="G1", url="u", content="c"),
        RawItem(item_id="bad", title="BAD", url="u", content="c"),
        RawItem(item_id="good2", title="G2", url="u", content="c"),
    ])
    n = c.run()
    assert n == 2  # good1 and good2 dropped
    inbox_files = list(isolated_paths["inbox"].glob("*.md"))
    assert len(inbox_files) == 2
    state = load_state("konan", "mock")
    assert any("normalize bad" in e for e in state["errors"])


# ─── invariants ────────────────────────────────────────────────────


def test_empty_name_raises(isolated_paths):
    c = _MockConnector(items=[])
    c.name = ""
    with pytest.raises(RuntimeError, match="name"):
        c.run()


def test_inbox_filename_includes_source_and_id(isolated_paths):
    c = _MockConnector(items=[
        RawItem(item_id="VID42", title="A Test Video", url="u", content="c"),
    ])
    c.run()
    files = list(isolated_paths["inbox"].glob("*.md"))
    assert len(files) == 1
    name = files[0].name
    assert "mock" in name
    assert "VID42" in name
    assert name.endswith(".md")


def test_normalize_default_matches_library_helper(isolated_paths):
    """The base's helper produces output equivalent to calling the module fn directly."""
    from lib.normalize import normalize_to_inbox
    item = RawItem(item_id="x", title="t", url="u", content="c")
    c = _MockConnector()
    c.codex = "Codex-X"
    via_base = c.normalize_default(item)
    via_lib = normalize_to_inbox(item, source="mock", codex="Codex-X")
    assert via_base == via_lib
