"""Tests for gods/kronos.py — KronosWriter JSONL log pipeline."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from gods.kronos import KronosWriter, LogEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "kronos"


@pytest.fixture()
def writer(log_dir: Path) -> KronosWriter:
    return KronosWriter(str(log_dir))


def _entry(
    god: str = "hestia",
    event: str = "health-check",
    level: str = "info",
    detail: str | None = None,
) -> LogEntry:
    return LogEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        level=level,
        god=god,
        event=event,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Directory creation
# ---------------------------------------------------------------------------


class TestInit:
    def test_creates_log_dir(self, tmp_path: Path):
        log_dir = tmp_path / "nested" / "kronos"
        assert not log_dir.exists()
        KronosWriter(str(log_dir))
        assert log_dir.is_dir()


# ---------------------------------------------------------------------------
# log()
# ---------------------------------------------------------------------------


class TestLog:
    def test_creates_file_on_first_write(self, writer: KronosWriter, log_dir: Path):
        writer.log(_entry())
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert (log_dir / f"{today}.jsonl").exists()

    def test_file_contains_valid_json_line(self, writer: KronosWriter, log_dir: Path):
        entry = _entry(god="kronos", event="startup", level="info", detail="boot")
        writer.log(entry)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw = (log_dir / f"{today}.jsonl").read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["god"] == "kronos"
        assert data["event"] == "startup"
        assert data["detail"] == "boot"
        assert data["level"] == "info"

    def test_appends_multiple_entries(self, writer: KronosWriter, log_dir: Path):
        for i in range(5):
            writer.log(_entry(event=f"event-{i}"))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = (log_dir / f"{today}.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5

    def test_each_line_is_independent_json(self, writer: KronosWriter, log_dir: Path):
        events = ["alpha", "beta", "gamma"]
        for ev in events:
            writer.log(_entry(event=ev))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lines = (log_dir / f"{today}.jsonl").read_text(encoding="utf-8").strip().splitlines()
        parsed_events = [json.loads(l)["event"] for l in lines]
        assert parsed_events == events

    def test_detail_none_stored_as_null(self, writer: KronosWriter, log_dir: Path):
        writer.log(_entry(detail=None))
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        raw = (log_dir / f"{today}.jsonl").read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        assert data["detail"] is None


# ---------------------------------------------------------------------------
# read_today()
# ---------------------------------------------------------------------------


class TestReadToday:
    def test_returns_empty_list_when_no_file(self, writer: KronosWriter):
        assert writer.read_today() == []

    def test_returns_all_written_entries(self, writer: KronosWriter):
        entries = [_entry(event=f"e{i}") for i in range(3)]
        for e in entries:
            writer.log(e)
        result = writer.read_today()
        assert len(result) == 3
        assert [r.event for r in result] == ["e0", "e1", "e2"]

    def test_returns_logentry_instances(self, writer: KronosWriter):
        writer.log(_entry())
        result = writer.read_today()
        assert all(isinstance(r, LogEntry) for r in result)


# ---------------------------------------------------------------------------
# read_date()
# ---------------------------------------------------------------------------


class TestReadDate:
    def test_returns_empty_list_for_missing_date(self, writer: KronosWriter):
        assert writer.read_date("2000-01-01") == []

    def test_reads_specific_date_file(self, writer: KronosWriter, log_dir: Path):
        # Manually write a fixture file for a past date
        date = "2025-12-25"
        fixture = LogEntry(
            timestamp="2025-12-25T00:00:00+00:00",
            level="info",
            god="demeter",
            event="xmas",
            detail=None,
        )
        path = log_dir / f"{date}.jsonl"
        path.write_text(
            json.dumps(
                {
                    "timestamp": fixture.timestamp,
                    "level": fixture.level,
                    "god": fixture.god,
                    "event": fixture.event,
                    "detail": fixture.detail,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        result = writer.read_date(date)
        assert len(result) == 1
        assert result[0].event == "xmas"
        assert result[0].god == "demeter"

    def test_skips_malformed_lines(self, writer: KronosWriter, log_dir: Path):
        date = "2025-01-01"
        path = log_dir / f"{date}.jsonl"
        path.write_text('{"broken":\n{"valid": true, "timestamp": "t", "level": "info", "god": "g", "event": "e", "detail": null}\n', encoding="utf-8")
        # Should not raise; only valid lines returned
        result = writer.read_date(date)
        assert len(result) == 1
