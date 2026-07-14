"""Tests for Phase 6: Skill Crystallization + Trajectory Mining."""

from __future__ import annotations

import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

PANTHEON_HOME = Path(__file__).resolve().parent.parent


def _import_script(relpath: str):
    """Import a script module by filesystem path."""
    path = PANTHEON_HOME / relpath
    name = path.stem + "_test"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _seed_test_db(db_path: Path, events: list[dict]) -> None:
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


class TestSkillCrystallization(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.skill_mod = _import_script("hermes-dojo/scripts/skill_crystallization.py")

    def test_finds_high_importance_insights(self) -> None:
        find_candidates = self.skill_mod.find_candidates
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=6)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "insight",
                 "subject": "pattern: use plan-mode before complex tasks",
                 "raw_text": "Always scaffold with plan mode first",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
                {"session_id": "s2", "event_type": "fact",
                 "subject": "irrelevant fact",
                 "raw_text": "just a fact",
                 "created_at": recent, "importance": 50.0,
                 "god_name": "hermes"},
            ])
            candidates = find_candidates(db_path=str(db), days=1, reference_now=now)
            self.assertGreaterEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["god_name"], "hermes")

    def test_filters_low_importance(self) -> None:
        find_candidates = self.skill_mod.find_candidates
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "insight",
                 "subject": "low signal",
                 "raw_text": "not important enough",
                 "created_at": recent, "importance": 10.0,
                 "god_name": "hermes"},
            ])
            candidates = find_candidates(db_path=str(db), days=1, reference_now=now)
            self.assertEqual(len(candidates), 0)

    def test_filters_outside_window(self) -> None:
        find_candidates = self.skill_mod.find_candidates
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            old = (now - timedelta(days=5)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "decision",
                 "subject": "old decision",
                 "raw_text": "too old",
                 "created_at": old, "importance": 90.0,
                 "god_name": "hermes"},
            ])
            candidates = find_candidates(db_path=str(db), days=1, reference_now=now)
            self.assertEqual(len(candidates), 0)


class TestFailedTrajectoryMining(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.fail_mod = _import_script("hermes-dojo/scripts/failed_trajectory_mining.py")

    def test_finds_timeout_patterns(self) -> None:
        find_failure_patterns = self.fail_mod.find_failure_patterns
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=4)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "hermes-gateway timeout",
                 "raw_text": "operation timed out after 60s",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
                {"session_id": "s2", "event_type": "blocker",
                 "subject": "conductor timeout",
                 "raw_text": "timeout waiting for NATS response",
                 "created_at": recent, "importance": 70.0,
                 "god_name": "hephaestus"},
            ])
            result = find_failure_patterns(db_path=str(db), days=7, reference_now=now)
            patterns = result.get("patterns", [])
            self.assertGreaterEqual(len(patterns), 1)
            sigs = [p["signature"] for p in patterns]
            self.assertTrue(any("timeout" in s or "timed" in s for s in sigs))

    def test_filters_outside_window(self) -> None:
        find_failure_patterns = self.fail_mod.find_failure_patterns
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            old = (now - timedelta(days=10)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "old failure",
                 "raw_text": "error: something broke",
                 "created_at": old, "importance": 80.0,
                 "god_name": "hermes"},
            ])
            result = find_failure_patterns(db_path=str(db), days=7, reference_now=now)
            # Event is outside the 7-day window, so 0 events scanned
            self.assertEqual(result["total_events_scanned"], 0)
            self.assertEqual(len(result.get("patterns", [])), 0)

    def test_requires_min_occurrences(self) -> None:
        find_failure_patterns = self.fail_mod.find_failure_patterns
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            now = datetime(2026, 7, 14, 0, 0, 0, tzinfo=timezone.utc)
            recent = (now - timedelta(hours=2)).isoformat()
            _seed_test_db(db, [
                {"session_id": "s1", "event_type": "blocker",
                 "subject": "singleton failure",
                 "raw_text": "error: just once",
                 "created_at": recent, "importance": 80.0,
                 "god_name": "hermes"},
            ])
            result = find_failure_patterns(db_path=str(db), days=7, reference_now=now)
            self.assertEqual(len(result.get("patterns", [])), 0)


if __name__ == "__main__":
    unittest.main()
