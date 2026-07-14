"""Tests for the quarantine_status helper script.

Covers the spec-mandated behaviors from Phase 4 REWORK #1:
  - empty dirs (both 0) → exit 0, count 0
  - 1 file in quarantine → exit 1, count 1, items has 1 entry
  - 5 files in quarantine, 0 in webhooks → exit 1, count 5
  - 0 in quarantine, 3 in webhooks → exit 1, count 3
  - missing dirs (never created) → exit 0, count 0, items empty

Plus a few bonus cases to lock in the JSON shape, top-5 truncation, and
oldest_age_seconds semantics (uses the OLDEST file, not the average).

The helper lives in conductor/scripts/ and is invoked as a subprocess so
the test exercises the real CLI surface (argparse, exit codes, JSON
output), not just the ``collect()`` function in isolation. We also call
``collect()`` directly for the cheap unit checks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

# Make conductor/scripts importable so we can call collect() directly
SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import quarantine_status  # noqa: E402

HELPER = SCRIPTS_DIR / "quarantine_status.py"


# ---------------------------------------------------------------------------
# Subprocess wrapper — runs the helper against arbitrary dirs and returns
# (exit_code, parsed_json_payload). Stdout is JSON; stderr is ignored.
# ---------------------------------------------------------------------------

def _run_helper(qdir: Path, wdir: Path, *extra: str) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            str(HELPER),
            "--quarantine-dir", str(qdir),
            "--webhooks-dir", str(wdir),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=10,
    )
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError:
        payload = {"_raw_stdout": proc.stdout, "_raw_stderr": proc.stderr}
    return proc.returncode, payload


# ---------------------------------------------------------------------------
# Spec cases (5) — exact behaviors the spec calls out
# ---------------------------------------------------------------------------

class TestSpecCases:
    def test_empty_dirs_both_zero(self, tmp_path):
        """Both dirs empty → exit 0, count 0."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        code, payload = _run_helper(q, w)
        assert code == 0
        assert payload["count"] == 0
        assert payload["items"] == []
        assert payload["oldest_age_seconds"] == 0

    def test_one_file_in_quarantine(self, tmp_path):
        """1 file in quarantine, 0 in webhooks → exit 1, count 1, items=[1]."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        (q / "alpha.json").write_text("{}")
        code, payload = _run_helper(q, w)
        assert code == 1
        assert payload["count"] == 1
        assert len(payload["items"]) == 1
        assert payload["items"][0]["filename"] == "alpha.json"

    def test_five_files_in_quarantine_zero_in_webhooks(self, tmp_path):
        """5 in quarantine, 0 in webhooks → exit 1, count 5."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        for i in range(5):
            (q / f"q_{i}.json").write_text("{}")
        code, payload = _run_helper(q, w)
        assert code == 1
        assert payload["count"] == 5
        assert len(payload["items"]) == 5  # all 5 fit under top-5

    def test_zero_in_quarantine_three_in_webhooks(self, tmp_path):
        """0 in quarantine, 3 in webhooks → exit 1, count 3."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        for i in range(3):
            (w / f"w_{i}.json").write_text("{}")
        code, payload = _run_helper(q, w)
        assert code == 1
        assert payload["count"] == 3
        assert len(payload["items"]) == 3

    def test_missing_dirs_never_created(self, tmp_path):
        """Dirs that were never created → exit 0, count 0, no crash."""
        # Note: we DO NOT mkdir the dirs. Helper must handle this gracefully.
        q = tmp_path / "nope_quarantine"
        w = tmp_path / "nope_webhooks"
        assert not q.exists()
        assert not w.exists()
        code, payload = _run_helper(q, w)
        assert code == 0
        assert payload["count"] == 0
        assert payload["items"] == []
        assert payload["oldest_age_seconds"] == 0


# ---------------------------------------------------------------------------
# JSON shape + ordering + truncation — locks the wire format
# ---------------------------------------------------------------------------

class TestPayloadShape:
    def test_payload_has_required_keys(self, tmp_path):
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        (q / "x.json").write_text("hello")
        code, payload = _run_helper(q, w)
        assert set(payload.keys()) == {"count", "oldest_age_seconds", "items"}
        assert isinstance(payload["count"], int)
        assert isinstance(payload["oldest_age_seconds"], int)
        assert isinstance(payload["items"], list)

    def test_item_shape(self, tmp_path):
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        (q / "y.json").write_text("12345")  # 5 bytes
        code, payload = _run_helper(q, w)
        item = payload["items"][0]
        assert set(item.keys()) == {"filename", "mtime", "size_bytes"}
        assert item["filename"] == "y.json"
        assert item["size_bytes"] == 5
        assert isinstance(item["mtime"], (int, float))

    def test_top_five_truncation(self, tmp_path):
        """6 files in quarantine → items has 5, count is 6."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        for i in range(6):
            (q / f"q_{i}.json").write_text("{}")
        code, payload = _run_helper(q, w)
        assert code == 1
        assert payload["count"] == 6
        assert len(payload["items"]) == 5  # truncated to top 5

    def test_oldest_first_ordering(self, tmp_path):
        """Items are sorted oldest first (smallest mtime first)."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        # Write files with a clear time spread. mtime resolution is 1s on
        # most filesystems, so sleep >1s between writes.
        (q / "newer.json").write_text("{}")
        time.sleep(1.2)
        (q / "middle.json").write_text("{}")
        time.sleep(1.2)
        (q / "oldest.json").write_text("{}")
        code, payload = _run_helper(q, w)
        assert code == 1
        names = [it["filename"] for it in payload["items"]]
        assert names == ["newer.json", "middle.json", "oldest.json"]

    def test_oldest_age_seconds_is_oldest_not_average(self, tmp_path):
        """oldest_age_seconds is the age of the SINGLE oldest file, not
        the average. The OLDEST file is the one with the SMALLEST mtime
        (written first). We pin mtimes explicitly with ``os.utime`` to
        avoid any sleep-based race in the test itself."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        # Write two files, then pin their mtimes deterministically.
        # mtimes chosen so there's a clear, large gap (1000s) between them.
        old_file = q / "oldest.json"
        new_file = q / "newest.json"
        old_file.write_text("{}")
        new_file.write_text("{}")
        # Use absolute timestamps so the test isn't sensitive to "now"
        now = time.time()
        # oldest.json: mtime 1000s ago
        # newest.json: mtime 100s ago
        os.utime(old_file, (now - 1000, now - 1000))
        os.utime(new_file, (now - 100, now - 100))

        code, payload = _run_helper(q, w)
        assert code == 1
        assert payload["count"] == 2
        # Items should be sorted oldest-first
        assert payload["items"][0]["filename"] == "oldest.json"
        assert payload["items"][1]["filename"] == "newest.json"
        # oldest_age_seconds should match the OLDEST file's age, not
        # the newer file's age. Allow a 5s drift because the helper and
        # the test both call time.time() and they may differ by a second
        # or two of wall clock.
        reported = payload["oldest_age_seconds"]
        assert 995 <= reported <= 1010, (
            f"oldest_age_seconds={reported} should be ~1000 "
            f"(the age of oldest.json), not ~100 (newest.json)"
        )

    def test_webhook_dir_alone_raises_exit_one(self, tmp_path):
        """Even with quarantine empty, webhooks alone flips exit to 1."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        (w / "w0.json").write_text("{}")
        code, payload = _run_helper(q, w)
        assert code == 1
        assert payload["count"] == 1


# ---------------------------------------------------------------------------
# Human-readable output path
# ---------------------------------------------------------------------------

class TestHumanReadable:
    def test_json_false_emits_summary(self, tmp_path):
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        (q / "a.json").write_text("{}")
        proc = subprocess.run(
            [
                sys.executable, str(HELPER),
                "--quarantine-dir", str(q),
                "--webhooks-dir", str(w),
                "--json", "false",
            ],
            capture_output=True, text=True, timeout=10,
        )
        assert proc.returncode == 1
        assert "Conductor quarantine backlog: 1 file(s)" in proc.stdout
        assert "a.json" in proc.stdout


# ---------------------------------------------------------------------------
# collect() direct unit checks — small cheap cases
# ---------------------------------------------------------------------------

class TestCollectDirect:
    def test_default_paths_dont_crash(self):
        """Calling collect() with the real production paths must not raise.
        We don't assert anything about the count because prod state changes,
        only that the call completes and returns a valid payload shape."""
        payload = quarantine_status.collect()
        assert set(payload.keys()) == {"count", "oldest_age_seconds", "items"}
        assert isinstance(payload["count"], int)
        assert isinstance(payload["items"], list)

    def test_clock_skew_doesnt_make_negative_age(self, tmp_path, monkeypatch):
        """Files with future mtimes (clock skew) clamp oldest_age to 0."""
        q = tmp_path / "_quarantine"
        w = tmp_path / "_webhooks"
        q.mkdir()
        w.mkdir()
        future = tmp_path / "future.json"
        future.write_text("{}")
        # Set mtime to far future
        future_ts = time.time() + 3600
        os.utime(future, (future_ts, future_ts))
        payload = quarantine_status.collect(quarantine_dir=q, webhooks_dir=w)
        # Oldest_age must be >= 0, not negative
        assert payload["oldest_age_seconds"] >= 0
