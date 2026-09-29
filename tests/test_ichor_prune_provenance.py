#!/usr/bin/env python3
"""prune_execute must clean dependants before deleting events (2026-09-21).

`ichor_event_tags.event_id` declares ON DELETE CASCADE and
`ichor_observation_sources.event_id` declares ON DELETE SET NULL, but every
live connection runs `foreign_keys=0`, so SQLite never enforces either. The
function used to delete events alone, which had accumulated 121,997 dangling
provenance pointers and 6,319 orphaned tag rows by the time it was caught.

Run:
    /usr/local/lib/hermes-agent/venv/bin/python3 -m pytest \
        tests/test_ichor_prune_provenance.py -q
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

_PANTHEON_ROOT = Path(__file__).resolve().parent.parent
if str(_PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PANTHEON_ROOT))

from lib import ichor_memory_score as score  # noqa: E402


def seed(db: Path) -> None:
    con = sqlite3.connect(str(db))
    con.executescript("""
        CREATE TABLE ichor_events (
            id INTEGER PRIMARY KEY, session_id TEXT, event_type TEXT,
            subject TEXT, raw_text TEXT, created_at TEXT,
            importance REAL, trust REAL, maturity TEXT, last_access TEXT
        );
        CREATE TABLE ichor_event_tags (
            event_id INTEGER NOT NULL, tag TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY(event_id, tag)
        );
        CREATE TABLE ichor_observation_sources (
            observation_id INTEGER NOT NULL, event_id INTEGER,
            conclusion_id INTEGER, quote TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY(observation_id, event_id, conclusion_id)
        );
    """)
    # one prunable event (old, low importance + low trust) ...
    con.execute("INSERT INTO ichor_events (id, session_id, event_type, subject,"
                " raw_text, created_at, importance, trust, maturity)"
                " VALUES (1,'s1','fact','prunable','x', datetime('now','-200 day'), 1.0, 1.0, 'draft')")
    # ... and one that must survive
    con.execute("INSERT INTO ichor_events (id, session_id, event_type, subject,"
                " raw_text, created_at, importance, trust, maturity)"
                " VALUES (2,'s1','decision','keeper','x', datetime('now','-1 day'), 90.0, 80.0, 'core')")
    con.execute("INSERT INTO ichor_event_tags (event_id, tag) VALUES (1,'scope:pantheon')")
    con.execute("INSERT INTO ichor_event_tags (event_id, tag) VALUES (2,'scope:pantheon')")
    con.execute("INSERT INTO ichor_observation_sources (observation_id, event_id,"
                " conclusion_id, quote) VALUES (10, 1, NULL, 'evidence text')")
    con.execute("INSERT INTO ichor_observation_sources (observation_id, event_id,"
                " conclusion_id, quote) VALUES (11, 2, NULL, 'kept evidence')")
    con.commit()
    con.close()


class TestPruneCleansDependants(unittest.TestCase):

    def test_prune_nulls_provenance_and_removes_tags(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            seed(db)
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            n = score.prune_execute(con, dry_run=False)
            self.assertEqual(n, 1, "the old low-value event should be pruned")

            survivors = con.execute("SELECT count(*) FROM ichor_events").fetchone()[0]
            self.assertEqual(survivors, 1, "only the keeper should remain")

            orphan_tags = con.execute(
                "SELECT count(*) FROM ichor_event_tags t WHERE NOT EXISTS "
                "(SELECT 1 FROM ichor_events e WHERE e.id = t.event_id)").fetchone()[0]
            self.assertEqual(orphan_tags, 0,
                             "pruning must not leave orphaned tag rows")

            dangling = con.execute(
                "SELECT count(*) FROM ichor_observation_sources s "
                "WHERE s.event_id IS NOT NULL AND NOT EXISTS "
                "(SELECT 1 FROM ichor_events e WHERE e.id = s.event_id)").fetchone()[0]
            self.assertEqual(dangling, 0,
                             "pruning must NULL provenance, not dangle it")

            kept = con.execute(
                "SELECT event_id FROM ichor_observation_sources "
                "WHERE observation_id = 11").fetchone()[0]
            self.assertEqual(kept, 2, "surviving evidence must keep its pointer")
            con.close()

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            seed(db)
            con = sqlite3.connect(str(db))
            con.row_factory = sqlite3.Row
            n = score.prune_execute(con, dry_run=True)
            self.assertEqual(n, 1)
            self.assertEqual(con.execute("SELECT count(*) FROM ichor_events").fetchone()[0], 2)
            self.assertEqual(con.execute("SELECT count(*) FROM ichor_event_tags").fetchone()[0], 2)
            con.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
