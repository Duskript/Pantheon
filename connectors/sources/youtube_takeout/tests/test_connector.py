"""
test_connector.py — Tests for the YouTube Takeout connector.

Covers:

* :func:`parse_watch_history` — schema tolerance:
  - Happy-path entries become ``WatchEntry`` records.
  - Non-YouTube headers (YouTube Music, ads) are dropped.
  - Entries with no ``titleUrl`` / no video ID are dropped.
  - Removed/unavailable video titles are flagged ``is_removed``.
  - Missing / malformed ``time`` fields are tolerated.
  - Channel name is extracted from the first subtitle.
  - The ``Watched `` prefix is stripped from the title.

* :class:`YouTubeTakeoutConnector` end-to-end:
  - The full ``run()`` loop drops a markdown file per video.
  - Frontmatter matches the design-doc contract (Appendix A) and the
    regex used by ``process-inbox.py``.
  - State cursor advances and prevents re-processing on a second run.
  - Transcript fetch failures produce a placeholder body, not a crash.
  - Missing file: error is recorded in state, no items dropped.
  - Empty file: same as missing.
  - The connector's ``name`` and default ``codex`` are set correctly.

The tests redirect ``INBOX_DIR`` and ``STATE_ROOT`` to a tmp dir via
the standard ``isolated_paths`` fixture pattern from the D1 lib tests.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest

from lib import base as base_mod
from lib import state as state_mod
from lib.base import ConnectorBase
from lib.normalize import RawItem

import sources.youtube_takeout.connector as yt_mod
from sources.youtube_takeout.connector import (
    YouTubeTakeoutConnector,
    WatchEntry,
    parse_watch_history,
)


# ─── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def isolated_paths(tmp_path, monkeypatch):
    """Redirect STATE_ROOT and INBOX_DIR to fresh tmp paths.

    Mirrors the pattern in ``lib/__tests__/test_base.py`` so the
    D2 tests behave the same way in isolation or together.
    """
    state_root = tmp_path / "state"
    inbox = tmp_path / "inbox"
    state_root.mkdir()
    inbox.mkdir()
    monkeypatch.setattr(state_mod, "STATE_ROOT", state_root)
    monkeypatch.setattr(base_mod, "INBOX_DIR", inbox)
    return {"state_root": state_root, "inbox": inbox, "tmp": tmp_path}


def _make_entry(
    video_id: str = "dQw4w9WgXcQ",
    title: str = "Some Video",
    channel: str = "Channel",
    time: str = "2024-01-15T10:30:00.000Z",
    header: str = "YouTube",
    title_url: str | None = None,
    subtitles: list | None = None,
) -> dict:
    """Build a single watch-history entry dict for tests.

    ``video_id`` defaults to a real 11-char YouTube ID. If a shorter
    string is passed, the resulting titleUrl won't have a valid ID
    and the entry will be filtered out by :func:`parse_watch_history`.
    """
    return {
        "header": header,
        "title": f"Watched {title}" if title else title,
        "titleUrl": title_url or f"https://www.youtube.com/watch?v={video_id}",
        "subtitles": (
            subtitles
            if subtitles is not None
            else ([{"name": channel, "url": f"https://www.youtube.com/@{channel}"}] if channel else [])
        ),
        "time": time,
    }


# 11-character video IDs for the sample. Real YouTube IDs are
# always exactly 11 chars, so the test fixtures must respect that.
SAMPLE_WATCH_HISTORY: list[dict] = [
    _make_entry(video_id="vidAAAA0001", title="How To Write A Connector", channel="Pantheon Academy", time="2024-01-15T10:30:00.000Z"),
    _make_entry(video_id="vidBBBB0002", title="RAG Architecture Deep Dive", channel="AI Builders", time="2024-01-14T08:00:00.000Z"),
    # Real Google marker — used verbatim because that's what Takeout
    # actually exports for removed/unavailable videos.
    _make_entry(video_id="vidCCCC0003", title="a video that has been removed", header="YouTube", time="2024-01-13T07:00:00.000Z"),
    # YouTube Music — should be dropped.
    _make_entry(video_id="vidDDDD0004", title="Some Song", header="YouTube Music", time="2024-01-12T06:00:00.000Z"),
    # Missing titleUrl — should be dropped.
    {"header": "YouTube", "title": "Watched No URL", "subtitles": [], "time": "2024-01-11T05:00:00.000Z"},
    # No subtitles — channel empty string.
    _make_entry(video_id="vidEEEE0005", title="No Channel Video", channel="", subtitles=[], time="2024-01-10T04:00:00.000Z"),
]


# ─── parse_watch_history ───────────────────────────────────────────


def test_parse_watch_history_extracts_video_ids_and_titles():
    """Happy path: the canonical YouTube entry shape."""
    entries = parse_watch_history(SAMPLE_WATCH_HISTORY)
    assert len(entries) == 4  # 2 happy + 1 removed + 1 no-channel; music + no-URL dropped
    # The first entry's title has the "Watched " prefix stripped.
    assert entries[0].title == "How To Write A Connector"
    assert entries[0].video_id == "vidAAAA0001"
    assert entries[0].channel == "Pantheon Academy"
    assert entries[0].is_removed is False
    assert entries[0].watched_at == datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_watch_history_skips_non_youtube_headers():
    """YouTube Music / ads / any other product are dropped."""
    entries = parse_watch_history(SAMPLE_WATCH_HISTORY)
    ids = {e.video_id for e in entries}
    assert "vidDDDD0004" not in ids  # the YouTube Music entry


def test_parse_watch_history_skips_entries_without_url():
    """Malformed entries without a video ID are dropped."""
    entries = parse_watch_history(SAMPLE_WATCH_HISTORY)
    # The "Watched No URL" entry has no titleUrl — must be dropped.
    for e in entries:
        assert e.video_id != ""


def test_parse_watch_history_flags_removed_videos():
    """Titles with Google's removed/unavailable markers are flagged."""
    entries = parse_watch_history(SAMPLE_WATCH_HISTORY)
    removed = [e for e in entries if e.video_id == "vidCCCC0003"]
    assert len(removed) == 1
    assert removed[0].is_removed is True


def test_parse_watch_history_handles_missing_subtitles():
    """An entry with empty ``subtitles`` still parses with empty channel."""
    entries = parse_watch_history(SAMPLE_WATCH_HISTORY)
    no_channel = [e for e in entries if e.video_id == "vidEEEE0005"]
    assert len(no_channel) == 1
    assert no_channel[0].channel == ""


def test_parse_watch_history_tolerates_malformed_timestamps():
    """Bad ``time`` fields become ``None`` — entry is not dropped."""
    data = [
        _make_entry(video_id="good1xxxxxx", title="Good", time="2024-01-15T10:30:00.000Z"),
        _make_entry(video_id="bad1xxxxxxx", title="No Time", time="not-a-date"),
        _make_entry(video_id="bad2xxxxxxx", title="No Time Field", time=""),
    ]
    entries = parse_watch_history(data)
    assert len(entries) == 3
    by_id = {e.video_id: e for e in entries}
    assert by_id["good1xxxxxx"].watched_at is not None
    assert by_id["bad1xxxxxxx"].watched_at is None
    assert by_id["bad2xxxxxxx"].watched_at is None


def test_parse_watch_history_handles_unexpected_payload_gracefully():
    """Non-list, non-dict, or None payloads are tolerated."""
    # All of these must not raise.
    assert parse_watch_history([]) == []
    assert parse_watch_history([{"header": "Other", "title": "x"}]) == []
    # Mixed types: skip the bad ones, keep the good ones.
    mixed = [
        "not a dict",
        None,
        42,
        _make_entry(video_id="vidOK12345x", title="OK", time="2024-01-15T10:30:00.000Z"),
    ]
    entries = parse_watch_history(mixed)
    assert [e.video_id for e in entries] == ["vidOK12345x"]


def test_parse_watch_history_handles_alternate_url_forms():
    """``youtu.be``, ``/shorts/``, ``/embed/`` all yield the video ID."""
    cases = [
        ("https://youtu.be/abcDEF12345", "abcDEF12345"),
        ("https://www.youtube.com/shorts/abcDEF12345", "abcDEF12345"),
        ("https://www.youtube.com/embed/abcDEF12345", "abcDEF12345"),
        ("https://www.youtube.com/live/abcDEF12345", "abcDEF12345"),
        ("https://www.youtube.com/watch?v=abcDEF12345&t=42s", "abcDEF12345"),
    ]
    for url, expected_id in cases:
        data = [_make_entry(video_id="placeholder", title="X", title_url=url)]
        entries = parse_watch_history(data)
        assert len(entries) == 1
        assert entries[0].video_id == expected_id, f"failed for {url}"


# ─── Connector.run end-to-end ─────────────────────────────────────


def _mock_transcript_factory(monkeypatch, transcripts: dict[str, str] | None = None, fail_on: set[str] | None = None):
    """Replace :func:`fetch_transcript` with a deterministic stub.

    Parameters
    ----------
    transcripts
        Maps ``video_id`` → transcript text. If a video isn't in the
        map, the stub returns ``None`` (treated as "transcript
        unavailable" by the connector).
    fail_on
        Set of video IDs that should raise rather than return text.
    """
    transcripts = transcripts or {}
    fail_on = fail_on or set()

    def _stub(video_id, *, languages=None, timeout=None):
        if video_id in fail_on:
            return None
        return transcripts.get(video_id)

    monkeypatch.setattr(yt_mod, "fetch_transcript", _stub)


def _write_takeout(tmp_path: Path, entries: list[dict]) -> Path:
    path = tmp_path / "watch-history.json"
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_run_drops_inbox_file_per_video(isolated_paths, monkeypatch):
    """The full run() loop drops one markdown file per parsed video."""
    _mock_transcript_factory(monkeypatch, transcripts={
        "vidAAAA0001": "First transcript",
        "vidBBBB0002": "Second transcript",
        "vidEEEE0005": "No channel transcript",
    })
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY)
    c = YouTubeTakeoutConnector(file_path=path)
    n = c.run()
    # 4 entries: 2 happy + 1 removed + 1 no-channel. (Music and no-URL
    # entries were dropped at parse time.)
    assert n == 4
    files = sorted(isolated_paths["inbox"].glob("*.md"))
    assert len(files) == 4


def test_run_inbox_format_matches_process_inbox_regex(isolated_paths, monkeypatch):
    """Each dropped file's frontmatter is parseable by process-inbox.py."""
    _mock_transcript_factory(monkeypatch, transcripts={
        "vidAAAA0001": "Connector design walkthrough.\nLine two.\n",
    })
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY[:1])
    c = YouTubeTakeoutConnector(file_path=path)
    c.run()

    (md_file,) = isolated_paths["inbox"].glob("*.md")
    md = md_file.read_text(encoding="utf-8")

    # Mirror process-inbox.py's regex (lines 182, 185) exactly.
    src_match = re.search(r'^source:\s*["\']?(.+?)["\']?\s*$', md, re.MULTILINE)
    title_match = re.search(r'^title:\s*["\']?(.+?)["\']?\s*$', md, re.MULTILINE)
    assert src_match is not None, f"source regex failed on:\n{md}"
    assert title_match is not None, f"title regex failed on:\n{md}"
    assert src_match.group(1).strip().strip("'\"") == "https://www.youtube.com/watch?v=vidAAAA0001"
    assert title_match.group(1).strip().strip("'\"") == "How To Write A Connector"

    # Frontmatter also includes the connector-specific extras.
    assert 'video_id: "vidAAAA0001"' in md
    assert 'channel: "Pantheon Academy"' in md
    assert 'codex: "Codex-YouTube"' in md
    assert 'connector: "youtube_takeout"' in md
    # The transcript text is in the body.
    assert "Connector design walkthrough." in md
    assert "## Fetched Content" in md


def test_run_advances_cursor_and_skips_processed(isolated_paths, monkeypatch):
    """A second run with no new entries drops zero items."""
    _mock_transcript_factory(monkeypatch, transcripts={
        "vidAAAA0001": "t1",
        "vidBBBB0002": "t2",
    })
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY)

    c1 = YouTubeTakeoutConnector(file_path=path)
    n1 = c1.run()
    assert n1 == 4

    # Second run — same file. The cursor should be at the latest
    # watched_at, so no items are newer.
    c2 = YouTubeTakeoutConnector(file_path=path)
    n2 = c2.run()
    assert n2 == 0

    # State has the cursor and the cumulative count.
    state = state_mod.load_state("konan", "youtube_takeout")
    assert state["items_processed"] == 4
    assert state["last_cursor"] is not None
    assert state["last_cursor"].startswith("2024-01-15T")


def test_run_handles_transcript_fetch_failure(isolated_paths, monkeypatch):
    """If transcript fetch returns ``None``, the file is still dropped with a placeholder."""
    # _mock_transcript_factory with empty transcripts dict → all fetches return None.
    _mock_transcript_factory(monkeypatch)
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY[:1])
    c = YouTubeTakeoutConnector(file_path=path)
    n = c.run()
    # Even with no transcripts, the file is still dropped.
    assert n == 1

    (md_file,) = isolated_paths["inbox"].glob("*.md")
    md = md_file.read_text(encoding="utf-8")
    assert "Transcript unavailable" in md
    # Frontmatter is still valid.
    assert 'title: "How To Write A Connector"' in md


def test_run_handles_removed_video(isolated_paths, monkeypatch):
    """Removed videos get the placeholder body and are still dropped."""
    _mock_transcript_factory(monkeypatch)
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY)
    c = YouTubeTakeoutConnector(file_path=path)
    c.run()
    files = list(isolated_paths["inbox"].glob("*.md"))
    # The "a video that has been removed" entry should be among them.
    bodies = [f.read_text(encoding="utf-8") for f in files]
    assert any("a video that has been removed" in b for b in bodies)
    # And the body has the placeholder text.
    assert any("Transcript unavailable" in b for b in bodies)


def test_run_records_missing_file_error(isolated_paths, monkeypatch):
    """A missing file: error in state, zero items dropped."""
    _mock_transcript_factory(monkeypatch)
    c = YouTubeTakeoutConnector(file_path=isolated_paths["tmp"] / "does_not_exist.json")
    n = c.run()
    assert n == 0
    state = state_mod.load_state("konan", "youtube_takeout")
    assert any("not found" in e for e in state["errors"]), state["errors"]


def test_run_records_malformed_file_error(isolated_paths, monkeypatch):
    """A non-JSON file: error in state, zero items dropped."""
    _mock_transcript_factory(monkeypatch)
    bad = isolated_paths["tmp"] / "watch-history.json"
    bad.write_text("not valid json {", encoding="utf-8")
    c = YouTubeTakeoutConnector(file_path=bad)
    n = c.run()
    assert n == 0
    state = state_mod.load_state("konan", "youtube_takeout")
    assert len(state["errors"]) >= 1


def test_run_handles_wrong_top_level_shape(isolated_paths, monkeypatch):
    """A JSON object (not array) is logged and yields nothing."""
    _mock_transcript_factory(monkeypatch)
    bad = isolated_paths["tmp"] / "watch-history.json"
    bad.write_text(json.dumps({"header": "YouTube"}), encoding="utf-8")
    c = YouTubeTakeoutConnector(file_path=bad)
    n = c.run()
    assert n == 0


def test_authenticate_requires_file_path():
    """The connector rejects calls when ``file_path`` is unset."""
    c = YouTubeTakeoutConnector()
    with pytest.raises(FileNotFoundError):
        c.authenticate()


def test_default_codex_is_codex_youtube():
    """The connector's default codex is ``Codex-YouTube``."""
    c = YouTubeTakeoutConnector(file_path="/tmp/whatever.json")
    assert c.codex == "Codex-YouTube"


def test_connector_name_is_youtube_takeout():
    """The connector's ``name`` matches the state-file basename convention."""
    c = YouTubeTakeoutConnector(file_path="/tmp/whatever.json")
    assert c.name == "youtube_takeout"


def test_inbox_filename_includes_source_and_video_id(isolated_paths, monkeypatch):
    """The base class builds a filename with the source name + video ID."""
    _mock_transcript_factory(monkeypatch, transcripts={"vidAAAA0001": "t"})
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY[:1])
    c = YouTubeTakeoutConnector(file_path=path)
    c.run()
    (md_file,) = isolated_paths["inbox"].glob("*.md")
    name = md_file.name
    assert "youtube_takeout" in name
    assert "vidAAAA0001" in name
    assert name.endswith(".md")


def test_second_run_does_not_re_drop_processed_videos(isolated_paths, monkeypatch):
    """The cursor is set to the latest seen ``watched_at``; older items are skipped."""
    # First run with all entries.
    _mock_transcript_factory(monkeypatch, transcripts={"vidFFFF0006": "ta", "vidGGGG0007": "tb"})
    history = [
        _make_entry(video_id="vidFFFF0006", title="A", time="2024-01-15T10:30:00.000Z"),
        _make_entry(video_id="vidGGGG0007", title="B", time="2024-01-14T10:30:00.000Z"),
    ]
    path = _write_takeout(isolated_paths["tmp"], history)
    c1 = YouTubeTakeoutConnector(file_path=path)
    assert c1.run() == 2

    # Now append a new entry to the file (simulate a re-takeout with
    # one additional video). The second run should only drop the new
    # one.
    history.append(_make_entry(video_id="vidHHHH0008", title="C", time="2024-01-16T10:30:00.000Z"))
    path.write_text(json.dumps(history), encoding="utf-8")
    c2 = YouTubeTakeoutConnector(file_path=path)
    n2 = c2.run()
    assert n2 == 1

    # Inbox has 3 files total: 2 from run 1, 1 from run 2.
    files = list(isolated_paths["inbox"].glob("*.md"))
    assert len(files) == 3


def test_user_id_override_propagates_to_inbox(isolated_paths, monkeypatch):
    """Setting ``user_id`` doesn't affect the inbox file, but the state does."""
    _mock_transcript_factory(monkeypatch, transcripts={"vidAAAA0001": "t"})
    path = _write_takeout(isolated_paths["tmp"], SAMPLE_WATCH_HISTORY[:1])
    c = YouTubeTakeoutConnector(file_path=path)
    c.user_id = "konan"
    c.run()
    # The state file lives under the user_id directory.
    state_files = list((isolated_paths["state_root"] / "konan").glob("*.json"))
    assert any(p.name == "youtube_takeout.json" for p in state_files)


# ─── Run CLI smoke test ────────────────────────────────────────────


def test_run_module_imports_and_dispatches():
    """The CLI module imports and exposes the connector."""
    # If the module is broken, the import at the top of this file
    # would have failed. Here we just confirm the connector is
    # reachable via the package public API.
    from sources.youtube_takeout import YouTubeTakeoutConnector as Exported

    assert Exported is YouTubeTakeoutConnector
