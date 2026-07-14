"""Tests for temporal backfill script."""

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
    path = PANTHEON_HOME / relpath
    name = path.stem + "_backfill_test"
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestBackfill(unittest.TestCase):

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _import_script("scripts/ichor_temporal_backfill.py")

    def test_backfill_relationships_expires_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            con = sqlite3.connect(str(db))
            con.executescript("""
                CREATE TABLE relationships (
                    id INTEGER PRIMARY KEY,
                    type_id TEXT, source_id INTEGER, target_id INTEGER,
                    confidence REAL, weight REAL, provenance TEXT,
                    source_ref TEXT, valid_from TEXT, valid_to TEXT,
                    created_at TEXT, updated_at TEXT, provisional INTEGER DEFAULT 0
                );
                CREATE TABLE ichor_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, event_type TEXT, subject TEXT,
                    predicate TEXT, object TEXT, confidence REAL,
                    source TEXT, raw_text TEXT, created_at TEXT,
                    god_name TEXT, importance REAL DEFAULT 50.0,
                    trust REAL DEFAULT 50.0, maturity TEXT DEFAULT 'draft',
                    last_access TEXT, direction TEXT, peer_god TEXT
                );
                -- Duplicate group: two rows, same type+source+target
                INSERT INTO relationships VALUES
                    (1, 'works_at', 100, 200, 0.9, 1.0, 'llm', 'ref1',
                     '2026-01-01', NULL, '2026-06-01 12:00:00', '2026-06-01', 0);
                INSERT INTO relationships VALUES
                    (2, 'works_at', 100, 200, 0.8, 1.0, 'llm', 'ref2',
                     '2026-01-01', NULL, '2026-06-15 12:00:00', '2026-06-15', 0);
                -- Unique row (no duplicate) — should stay untouched
                INSERT INTO relationships VALUES
                    (3, 'uses', 300, 400, 0.7, 1.0, 'llm', 'ref3',
                     '2026-01-01', NULL, '2026-06-10 12:00:00', '2026-06-10', 0);
            """)
            con.commit()
            con.close()

            result = self.mod.run_backfill(str(db), dry_run=False)
            rels = result["relationships"]
            self.assertEqual(rels["expired"], 1)
            self.assertEqual(rels["groups"], 1)

            # Verify: row 1 has valid_to set, row 2 does not, row 3 does not
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            r1 = con.execute("SELECT valid_to FROM relationships WHERE id=1").fetchone()
            r2 = con.execute("SELECT valid_to FROM relationships WHERE id=2").fetchone()
            r3 = con.execute("SELECT valid_to FROM relationships WHERE id=3").fetchone()
            self.assertIsNotNone(r1["valid_to"])
            self.assertIsNone(r2["valid_to"])
            self.assertIsNone(r3["valid_to"])
            con.close()

    def test_backfill_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            con = sqlite3.connect(str(db))
            con.executescript("""
                CREATE TABLE relationships (
                    id INTEGER PRIMARY KEY,
                    type_id TEXT, source_id INTEGER, target_id INTEGER,
                    confidence REAL, weight REAL, provenance TEXT,
                    source_ref TEXT, valid_from TEXT, valid_to TEXT,
                    created_at TEXT, updated_at TEXT, provisional INTEGER DEFAULT 0
                );
                CREATE TABLE ichor_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, event_type TEXT, subject TEXT,
                    predicate TEXT, object TEXT, confidence REAL,
                    source TEXT, raw_text TEXT, created_at TEXT,
                    god_name TEXT, importance REAL DEFAULT 50.0
                );
                INSERT INTO relationships VALUES
                    (1, 'blocks', 10, 20, 0.9, 1.0, 'llm', 'r1',
                     '2026-01-01', NULL, '2026-06-01', '2026-06-01', 0);
                INSERT INTO relationships VALUES
                    (2, 'blocks', 10, 20, 0.8, 1.0, 'llm', 'r2',
                     '2026-01-01', NULL, '2026-06-15', '2026-06-15', 0);
            """)
            con.commit()
            con.close()

            # Run twice — second run should be no-op
            r1 = self.mod.run_backfill(str(db), dry_run=False)
            self.assertEqual(r1["relationships"]["expired"], 1)

            r2 = self.mod.run_backfill(str(db), dry_run=False)
            self.assertEqual(r2["relationships"]["expired"], 0)

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "test.db"
            con = sqlite3.connect(str(db))
            con.executescript("""
                CREATE TABLE relationships (
                    id INTEGER PRIMARY KEY,
                    type_id TEXT, source_id INTEGER, target_id INTEGER,
                    confidence REAL, weight REAL, provenance TEXT,
                    source_ref TEXT, valid_from TEXT, valid_to TEXT,
                    created_at TEXT, updated_at TEXT, provisional INTEGER DEFAULT 0
                );
                CREATE TABLE ichor_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT, event_type TEXT, subject TEXT,
                    predicate TEXT, object TEXT, confidence REAL,
                    source TEXT, raw_text TEXT, created_at TEXT,
                    god_name TEXT, importance REAL DEFAULT 50.0
                );
                INSERT INTO relationships VALUES
                    (1, 'uses', 1, 2, 0.9, 1.0, 'llm', 'r1',
                     '2026-01-01', NULL, '2026-06-01', '2026-06-01', 0);
                INSERT INTO relationships VALUES
                    (2, 'uses', 1, 2, 0.8, 1.0, 'llm', 'r2',
                     '2026-01-01', NULL, '2026-06-15', '2026-06-15', 0);
            """)
            con.commit()
            con.close()

            result = self.mod.run_backfill(str(db), dry_run=True)
            self.assertEqual(result["relationships"]["expired"], 1)

            # Verify nothing was actually written
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            r1 = con.execute("SELECT valid_to FROM relationships WHERE id=1").fetchone()
            self.assertIsNone(r1["valid_to"])
            con.close()


if __name__ == "__main__":
    unittest.main()
