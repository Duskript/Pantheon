"""Fix D (zero-LLM half) tests — graph hits must not render as hollow nodes.

14,093 of 18,427 entities (76%) have an empty `summary` and exactly 1 has >=200
chars.  `_format_context` builds a graph hit's snippet from `summary`, so every
hit landing on a summary-less entity used to render a content-free string.

`_neighborhood_descriptor` derives a one-liner from the entity's own typed
neighbourhood, at read time, with NO writes to `summary` — a semantic backfill
must still be able to tell "never summarised" from "summarised".

Run:
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_fix_d_descriptor.py
"""
from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

_PANTHEON_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT = Path("/home/konan/.hermes/plugins")
_HERMES_AGENT = Path("/home/konan/.hermes/hermes-agent")
for _p in (str(_PANTHEON_ROOT), str(_PLUGIN_ROOT), str(_HERMES_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ichor.provider import IchorMemoryProvider  # noqa: E402

LIVE_DB = Path("/home/konan/.hermes/ichor.db")


class TestDescriptorOnTempGraph(unittest.TestCase):
    """Deterministic, isolated: a hand-built graph with no summaries anywhere."""

    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT,
                                   type_id TEXT, summary TEXT);
            CREATE TABLE relationships (id INTEGER PRIMARY KEY, type_id TEXT,
                source_id INTEGER, target_id INTEGER, confidence REAL,
                weight REAL, provisional INTEGER DEFAULT 0, valid_to TEXT);
            INSERT INTO entities (id, name, type_id, summary) VALUES
                (1, 'konan', 'person', ''),
                (2, 'Fia',   'person', ''),
                (3, 'VTC',   'organization', NULL);
            INSERT INTO relationships
                (id, type_id, source_id, target_id, confidence, weight, provisional, valid_to)
            VALUES
                (1, 'knows',    1, 2, 0.9, 0.0, 0, NULL),
                (2, 'works_at', 1, 3, 0.8, 0.0, 0, NULL),
                (3, 'low_conf', 1, 2, 0.1, 0.0, 0, NULL);
            """
        )

    def tearDown(self) -> None:
        self.conn.close()

    def test_describes_a_summary_less_entity(self):
        out = self.provider._neighborhood_descriptor(self.conn, 1)
        self.assertTrue(out, "summary-less entity produced no descriptor")
        self.assertIn("linked via", out)
        self.assertIn("Fia", out)
        self.assertIn("VTC", out)

    def test_below_confidence_floor_edges_are_ignored(self):
        out = self.provider._neighborhood_descriptor(self.conn, 1)
        self.assertNotIn("low_conf", out)

    def test_entity_with_no_edges_returns_empty(self):
        self.conn.execute(
            "INSERT INTO entities (id, name, type_id, summary) VALUES (9, 'Orphan', 'concept', '')"
        )
        self.assertEqual(self.provider._neighborhood_descriptor(self.conn, 9), "")

    def test_descriptor_never_writes_to_summary(self):
        before = self.conn.execute("SELECT summary FROM entities WHERE id = 1").fetchone()[0]
        self.provider._neighborhood_descriptor(self.conn, 1)
        after = self.conn.execute("SELECT summary FROM entities WHERE id = 1").fetchone()[0]
        self.assertEqual(before, after,
                         "descriptor wrote to `summary`; a semantic backfill can no "
                         "longer distinguish never-summarised from summarised")

    def test_missing_table_is_non_fatal(self):
        empty = sqlite3.connect(":memory:")
        empty.row_factory = sqlite3.Row
        self.assertEqual(self.provider._neighborhood_descriptor(empty, 1), "")
        empty.close()


@unittest.skipUnless(LIVE_DB.is_file(), "live ichor.db not present")
class TestDescriptorOnLiveGraph(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def test_live_summary_less_hub_is_described(self):
        conn = sqlite3.connect(f"file:{LIVE_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            # entity 614 'konan' — high degree, empty summary before Fix D
            out = self.provider._neighborhood_descriptor(conn, 614)
            self.assertTrue(out, "live summary-less hub produced no descriptor")
            self.assertIn("linked via", out)
        finally:
            conn.close()

    def test_graph_results_are_never_hollow(self):
        results = self.provider._query_graph(["konan"], depth=2)
        self.assertTrue(results, "no graph results to check")
        hollow = [r for r in results if not (r.get("snippet") or "").strip()]
        self.assertFalse(hollow, f"hollow snippets survived Fix D: {hollow}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
