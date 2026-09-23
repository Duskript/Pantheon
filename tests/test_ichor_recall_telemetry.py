#!/usr/bin/env python3
"""Recall telemetry must actually be written (2026-09-21).

`recall_log` had NO writer: 9 rows total, all from 2026-08-06/07, so nothing
could answer "is recall working, and what is the latency" from data. The
provider now writes one row per FULL-recall turn (every 3rd turn), not per
turn, to avoid re-introducing write churn.

The test redirects the module-level DB path to a temp file, so the live
`recall_log` is never touched.

Run:
    /usr/local/lib/hermes-agent/venv/bin/python3 -m pytest \
        tests/test_ichor_recall_telemetry.py -q
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_PANTHEON_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT = Path("/home/konan/.hermes/plugins")
_HERMES_AGENT = Path("/home/konan/.hermes/hermes-agent")
for _p in (str(_PANTHEON_ROOT), str(_PLUGIN_ROOT), str(_HERMES_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ichor.provider as provider_mod  # noqa: E402
from ichor.provider import IchorMemoryProvider  # noqa: E402


def make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE recall_log (
            id INTEGER PRIMARY KEY, query_text TEXT NOT NULL,
            god_name TEXT DEFAULT 'unknown', lanes_used TEXT DEFAULT '[]',
            per_lane_latency_ms TEXT DEFAULT '{}', total_ms REAL NOT NULL DEFAULT 0,
            top_result_ids TEXT DEFAULT '[]', top_result_scores TEXT DEFAULT '[]',
            retrieved_at TEXT DEFAULT (datetime('now')),
            retrieval_metadata_json TEXT DEFAULT '{}',
            backends_requested_json TEXT DEFAULT '[]',
            candidate_counts_json TEXT DEFAULT '{}',
            strict_scope_excluded_counts_json TEXT DEFAULT '{}',
            warnings_json TEXT DEFAULT '[]', rerank_status TEXT DEFAULT 'unknown')
    """)
    con.commit()
    con.close()


class TestRecallTelemetry(unittest.TestCase):

    def _provider(self):
        p = object.__new__(IchorMemoryProvider)
        p._god_name = "hermes"
        return p

    def test_log_recall_writes_a_row(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "t.db"
            make_db(db)
            fused = [{"id": 7, "score": 0.91, "tier": "fts5"},
                     {"id": 9, "score": 0.4, "tier": "graph"}]
            with mock.patch.object(provider_mod, "_ICHOR_DB", str(db)):
                self._provider()._log_recall("ichor retention prune", fused,
                                             0.0, False)
            con = sqlite3.connect(str(db))
            rows = con.execute("SELECT query_text, god_name, lanes_used,"
                              " top_result_ids, top_result_scores, total_ms"
                              " FROM recall_log").fetchall()
            con.close()
            self.assertEqual(len(rows), 1, "one row per logged recall")
            q, god, lanes, ids, scores, ms = rows[0]
            self.assertEqual(q, "ichor retention prune")
            self.assertEqual(god, "hermes")
            self.assertEqual(json.loads(ids), [7, 9])
            self.assertEqual(json.loads(lanes), ["fts5", "graph"])
            self.assertGreaterEqual(ms, 0.0)

    def test_log_recall_never_raises(self):
        """A telemetry failure must not affect the turn."""
        p = self._provider()
        with mock.patch.object(provider_mod, "_ICHOR_DB",
                               "/nonexistent/path/ichor.db"):
            p._log_recall("q", [{"id": 1, "score": 1.0, "tier": "fts5"}],
                          0.0, False)  # must not raise

    def test_wired_on_full_cadence_only(self):
        src = Path(provider_mod.__file__).read_text()
        self.assertIn("if is_full:", src)
        self.assertIn("self._log_recall(query, fused, t_recall_start, cross_god)", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
