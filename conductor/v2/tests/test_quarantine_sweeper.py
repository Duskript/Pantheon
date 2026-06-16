"""Tests for the quarantine sweeper.

Covers:
  - format_quarantine_alert integration (the alert body has the right shape)
  - dedupe: same file is never alerted twice across restarts
  - snooze: per-source and global snooze suppress alerts
  - kill-switch HTTP: /snooze, /unsnooze, /status, /healthz
  - parse_duration: 30m, 2h, 1d, garbage input
  - one-shot scan: existing files in _quarantine/ are processed and counted
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.client import HTTPConnection
from pathlib import Path
from unittest.mock import patch


def _run(coro):
    import asyncio
    return asyncio.run(coro)

import pytest

# Reuse the test fixture pattern from the rest of the v2 test suite.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from v2.tests.fixtures import TmpConductor  # noqa: E402
from v2 import quarantine_sweeper as qs  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_quarantine(qdir: Path, name: str, source: str = "github", subject: str = "/webhook/github", rule_id: str = "__default_external__") -> Path:
    qdir.mkdir(parents=True, exist_ok=True)
    p = qdir / name
    p.write_text(json.dumps({
        "event": {
            "handling_mode": "approval_required",
            "is_external": True,
            "payload": {"action": "opened", "pr": 42},
            "raw": {"id": "x"},
            "source": source,
            "subject": subject,
            "target": None,
            "timestamp": "2026-06-14T07:23:32.909283Z",
            "type": "webhook",
        },
        "queued_at": "2026-06-14T07:23:33Z",
        "rule_id": rule_id,
    }))
    return p


def _read_snooze_file() -> tuple[set, dict]:
    if not qs.SEEN_FILE.exists():
        return set(), {}
    d = json.loads(qs.SEEN_FILE.read_text())
    return set(d.get("seen") or []), d.get("snooze") or {}


# ---------------------------------------------------------------------------
# format_quarantine_alert integration
# ---------------------------------------------------------------------------

class TestAlertShape:
    def test_alert_contains_source_and_subject(self):
        text = qs.delivery_mod.format_quarantine_alert(
            event_summary="opened pr=42",
            source="github",
            subject="/webhook/github",
            rule_id="__default_external__",
            quarantine_path="/tmp/q.json",
        )
        assert "github" in text
        assert "/webhook/github" in text
        assert "Approval Required" in text
        assert "__default_external__" in text
        assert "approve" in text
        assert "dismiss" in text

    def test_sweeper_appends_kill_switch(self):
        sweeper = qs.QuarantineSweeper(run_control_server=False)
        text = sweeper._append_kill_switch("hello")
        assert "snooze 1h" in text
        assert "status" in text


# ---------------------------------------------------------------------------
# Snooze state
# ---------------------------------------------------------------------------

class TestSnooze:
    def test_global_snooze_blocks(self):
        s = qs.SnoozeState()
        s.snooze(60)
        assert s.is_silenced("github")
        assert s.is_silenced("stripe")

    def test_per_source_does_not_block_other_sources(self):
        s = qs.SnoozeState()
        s.snooze(60, source="github")
        assert s.is_silenced("github")
        assert not s.is_silenced("stripe")

    def test_snooze_expires(self):
        s = qs.SnoozeState()
        s.snooze(1, source="github")
        time.sleep(1.1)
        assert not s.is_silenced("github")

    def test_cancel(self):
        s = qs.SnoozeState()
        s.snooze(3600)
        s.cancel()
        assert not s.is_silenced("github")
        s.snooze(3600, source="github")
        s.cancel(source="github")
        assert not s.is_silenced("github")

    def test_round_trip(self):
        s = qs.SnoozeState()
        s.snooze(7200, source="github")
        s.snooze(1800)
        d = s.to_dict()
        s2 = qs.SnoozeState.from_dict(d)
        assert s2.is_silenced("github")
        assert s2.is_silenced("stripe")


# ---------------------------------------------------------------------------
# parse_duration
# ---------------------------------------------------------------------------

class TestParseDuration:
    def test_minutes(self):
        assert qs.parse_duration("snooze 30m") == 30 * 60

    def test_hours(self):
        assert qs.parse_duration("snooze 2h") == 2 * 3600

    def test_days(self):
        assert qs.parse_duration("snooze 1d") == 86400

    def test_seconds(self):
        assert qs.parse_duration("snooze 45s") == 45

    def test_garbage(self):
        assert qs.parse_duration("dismiss this") == 0.0


# ---------------------------------------------------------------------------
# Dedupe + seen persistence
# ---------------------------------------------------------------------------

class TestDedupe:
    def test_seen_round_trip(self, tmp_path, monkeypatch):
        # redirect SEEN_FILE to a tmp path so we don't touch real state
        fake = tmp_path / "seen.json"
        monkeypatch.setattr(qs, "SEEN_FILE", fake)

        seen, snooze = qs._load_seen()
        assert seen == set()

        seen.add("foo.json")
        seen.add("bar.json")
        qs._save_seen(seen, qs.SnoozeState())

        # Reload and verify
        monkeypatch.setattr(qs, "SEEN_FILE", fake)
        seen2, _ = qs._load_seen()
        assert seen2 == {"foo.json", "bar.json"}


# ---------------------------------------------------------------------------
# Scan once: counts + dedupe
# ---------------------------------------------------------------------------

class TestScanOnce:
    def test_scan_dedupes_via_seen(self, tmp_path, monkeypatch):
        # Isolated conductor dir
        c = TmpConductor.create()
        try:
            _write_quarantine(c.quarantine_dir, "alpha.json")
            _write_quarantine(c.quarantine_dir, "beta.json", source="stripe")

            # Point the sweeper at our tmp dir
            monkeypatch.setenv("CONDUCTOR_BASE_DIR", str(c.root))
            monkeypatch.setattr(qs, "SEEN_FILE", tmp_path / "seen.json")

            sweeper = qs.QuarantineSweeper(
                token="",  # we'll mock send_telegram so the real one isn't called
                chat_id="",
                seen=set(),
                run_control_server=False,
            )

            orig = qs.send_telegram
            qs.send_telegram = lambda *a, **kw: (True, "ok")
            try:
                counts = _run(sweeper.scan_once())
                assert counts["sent"] == 2

                # Second scan should dedupe — zero new alerts
                counts2 = _run(sweeper.scan_once())
                assert counts2["sent"] == 0
            finally:
                qs.send_telegram = orig
        finally:
            c.cleanup()

    def test_snooze_suppresses(self, tmp_path, monkeypatch):
        c = TmpConductor.create()
        try:
            _write_quarantine(c.quarantine_dir, "gamma.json", source="github")
            monkeypatch.setenv("CONDUCTOR_BASE_DIR", str(c.root))
            monkeypatch.setattr(qs, "SEEN_FILE", tmp_path / "seen.json")

            sweeper = qs.QuarantineSweeper(
                token="x", chat_id="y",
                seen=set(),
                snooze=qs.SnoozeState(),
                run_control_server=False,
            )
            sweeper.snooze.snooze(3600, source="github")

            orig = qs.send_telegram
            qs.send_telegram = lambda *a, **kw: (True, "ok")
            try:
                counts = _run(sweeper.scan_once())
                assert counts["suppressed"] == 1
                assert counts["sent"] == 0
            finally:
                qs.send_telegram = orig
        finally:
            c.cleanup()


# ---------------------------------------------------------------------------
# Control HTTP server
# ---------------------------------------------------------------------------

class TestControlServer:
    def test_status_and_snooze(self, tmp_path, monkeypatch):
        c = TmpConductor.create()
        try:
            monkeypatch.setenv("CONDUCTOR_BASE_DIR", str(c.root))
            monkeypatch.setattr(qs, "SEEN_FILE", tmp_path / "seen.json")

            sweeper = qs.QuarantineSweeper(
                token="x", chat_id="y",
                seen=set(), snooze=qs.SnoozeState(),
                control_port=0,  # pick a free port
            )
            sweeper._start_control_server()
            assert sweeper._control_server is not None
            port = sweeper._control_server.server_address[1]
            base = f"http://127.0.0.1:{port}"

            def get(path):
                with urllib.request.urlopen(f"{base}{path}", timeout=2) as r:
                    return r.status, json.loads(r.read())

            def post(path, body):
                req = urllib.request.Request(
                    f"{base}{path}",
                    data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=2) as r:
                    return r.status, json.loads(r.read())

            # /healthz
            code, body = get("/healthz")
            assert code == 200
            assert body == {"ok": True}

            # /status initial
            code, body = get("/status")
            assert code == 200
            assert body["snooze"]["global_snoozed_until"] is None

            # POST /snooze global
            code, body = post("/snooze", {"seconds": 60})
            assert code == 200
            assert body["status"] == "snoozed"

            # status now shows global snooze
            _, body = get("/status")
            assert body["snooze"]["global_snoozed_until"] is not None

            # POST /snooze per-source
            code, body = post("/snooze", {"seconds": 30, "source": "github"})
            assert code == 200
            assert body["source"] == "github"

            _, body = get("/status")
            assert "github" in body["snooze"]["per_source"]

            # POST /unsnooze github
            code, body = post("/unsnooze", {"source": "github"})
            assert code == 200
            _, body = get("/status")
            assert "github" not in body["snooze"]["per_source"]

            # unknown path
            with pytest.raises(urllib.error.HTTPError) as ei:
                get("/nope")
            assert ei.value.code == 404

            sweeper._stop_control_server()
        finally:
            c.cleanup()
