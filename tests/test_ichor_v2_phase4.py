"""Tests for Phase 4: Decay + Eviction + Forge."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _seed_test_db(db_path: Path, events: list[dict]) -> None:
    """Create a minimal ichor_events table and insert seed rows."""
    con = sqlite3.connect(str(db_path))
    con.executescript("""
        CREATE TABLE ichor_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            event_type TEXT,
            subject TEXT,
            predicate TEXT,
            object TEXT,
            confidence REAL DEFAULT 0.8,
            source TEXT,
            raw_text TEXT,
            created_at TEXT,
            god_name TEXT,
            importance REAL DEFAULT 50.0,
            trust REAL DEFAULT 50.0,
            maturity TEXT DEFAULT 'draft',
            last_access TEXT,
            direction TEXT,
            peer_god TEXT
        );
    """)
    for ev in events:
        cols = ", ".join(ev.keys())
        ph = ", ".join("?" for _ in ev)
        con.execute(f"INSERT INTO ichor_events ({cols}) VALUES ({ph})", list(ev.values()))
    con.commit()
    con.close()


class TestDecay(unittest.TestCase):

    def test_decay_lowers_importance(self) -> None:
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            old = (now - timedelta(days=10)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": old, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=True, reference_now=now)
            self.assertEqual(result["decayed"], 1)
            self.assertEqual(result["skipped"], 0)
            s = result["sample"][0]
            self.assertLess(s["new_importance"], s["old_importance"])
            self.assertGreater(s["new_importance"], 0)

    def test_decay_skips_recent_events(self) -> None:
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(minutes=30)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": recent, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=True, reference_now=now)
            self.assertEqual(result["decayed"], 0)
            self.assertGreater(result["skipped"], 0)

    def test_decay_apply_writes(self) -> None:
        from lib.ichor_decay import run_decay
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            old = (now - timedelta(days=30)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "test", "raw_text": "x",
                 "created_at": old, "importance": 100.0,
                 "god_name": "hermes"},
            ])
            result = run_decay(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["decayed"], 1)
            # Verify it persisted
            con = sqlite3.connect(str(db))
            imp = con.execute("SELECT importance FROM ichor_events WHERE id=1").fetchone()[0]
            con.close()
            self.assertLess(imp, 100.0)
            self.assertGreater(imp, 0.0)


class TestEviction(unittest.TestCase):

    def test_eviction_candidates_found(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=120)).isoformat()
            very_low = 0.01
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "stale", "raw_text": "x",
                 "created_at": very_old, "importance": very_low,
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=True, reference_now=now)
            self.assertEqual(len(result.get("candidates", [])), 1)

    def test_eviction_skips_recent(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(days=5)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "fresh", "raw_text": "x",
                 "created_at": recent, "importance": 0.01,
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=True, reference_now=now)
            self.assertEqual(len(result.get("candidates", [])), 0)

    def test_eviction_apply(self) -> None:
        from lib.ichor_eviction import run_eviction
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            very_old = (now - timedelta(days=120)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "fact",
                 "subject": "stale", "raw_text": "x",
                 "created_at": very_old, "importance": 0.01,
                 "god_name": "hermes"},
            ])
            result = run_eviction(str(db), dry_run=False, reference_now=now)
            self.assertEqual(result["archived"], 1)
            # Verify moved to cold storage and removed from main
            con = sqlite3.connect(str(db))
            main_count = con.execute("SELECT COUNT(*) FROM ichor_events").fetchone()[0]
            cold_count = con.execute("SELECT COUNT(*) FROM ichor_cold_storage").fetchone()[0]
            con.close()
            self.assertEqual(main_count, 0)
            self.assertEqual(cold_count, 1)


class TestForge(unittest.TestCase):

    def test_forge_finds_cross_session_pattern(self) -> None:
        from scripts.ichor_overnight_phase4 import run_forge_step
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=6)).isoformat()
            _seed_test_db(db, [
                {"session_id": "sess-a", "event_type": "fact",
                 "subject": "hermes:nginx-config", "raw_text": "nginx ssl setup",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
                {"session_id": "sess-b", "event_type": "insight",
                 "subject": "hermes:nginx-config", "raw_text": "renewed certs",
                 "created_at": recent, "importance": 70.0,
                 "god_name": "hephaestus"},
                {"session_id": "sess-a", "event_type": "follow_up",
                 "subject": "hermes:other-topic", "raw_text": "something else",
                 "created_at": recent, "importance": 50.0,
                 "god_name": "hermes"},
            ])
            result = run_forge_step(str(db), dry_run=True, reference_now=now)
            self.assertGreaterEqual(result["patterns_found"], 1)
            topics = [p["topic"] for p in result.get("patterns", [])]
            self.assertIn("nginx-config", topics)

    def test_forge_requires_two_sessions(self) -> None:
        from scripts.ichor_overnight_phase4 import run_forge_step
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            _seed_test_db(db, [
                {"session_id": "sess-a", "event_type": "fact",
                 "subject": "hermes:single-topic", "raw_text": "only one session",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
                {"session_id": "sess-a", "event_type": "follow_up",
                 "subject": "hermes:single-topic", "raw_text": "same session again",
                 "created_at": recent, "importance": 70.0,
                 "god_name": "hermes"},
            ])
            result = run_forge_step(str(db), dry_run=True, reference_now=now)
            # No cross-session pattern — same session doesn't count
            self.assertEqual(result["patterns_found"], 0)


if __name__ == "__main__":
    unittest.main()
