"""Fix B acceptance tests — reinforcement stops decay being a one-way door.

Handoff: ~/pantheon/shared/handoffs/ichor-relational-recall-fix/BRIEF.md (§Wave 2)

Fix B  `dream.py` halves a relationship's `weight` every 7 days (archive
       threshold 0.1, so ~23 days to zero), `_relationships_to_decay` selects
       `WHERE weight > 0`, and nothing restores weight.  Baseline at the time of
       the fix: 26,935 of 27,079 edges at `weight = 0.0`, permanently invisible
       to any weight-filtered query.

       Remedy: reinforce-on-traverse — an edge that is actually surfaced into a
       turn's injected context gets `w += (1 - w) * _REINFORCE_ALPHA`.

Every test here runs against a TEMP database; the live graph is never written.

Run:
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_fix_b_reinforce.py
"""
from __future__ import annotations

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
from ichor.provider import (  # noqa: E402
    _REINFORCE_ALPHA,
    IchorMemoryProvider,
)

SCHEMA = """
CREATE TABLE relationships (
    id INTEGER PRIMARY KEY,
    type_id TEXT,
    source_id INTEGER,
    target_id INTEGER,
    confidence REAL,
    weight REAL,
    provenance TEXT,
    valid_from TEXT,
    valid_to TEXT,
    updated_at TEXT
);
"""


def _make_db(rows: list[tuple]) -> Path:
    tmp = Path(tempfile.mkdtemp()) / "relationships.db"
    conn = sqlite3.connect(tmp)
    conn.execute(SCHEMA)
    conn.executemany(
        "INSERT INTO relationships (id, type_id, source_id, target_id, "
        "confidence, weight, provenance, valid_from, valid_to, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return tmp


def _weight(db: Path, row_id: int) -> tuple:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT weight, provenance FROM relationships WHERE id = ?", (row_id,)
        ).fetchone()
    finally:
        conn.close()


def _graph_entry(src: int, tgt: int, rel: str, backend: str = "graph") -> dict:
    return {
        "id": f"graph:{tgt}:{rel}",
        "backend": backend,
        "title": f"konan --{rel}--> Fia",
        "edge": {"source": src, "target": tgt, "type": rel},
    }


class TestReinforcement(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def _with_db(self, rows: list[tuple]):
        db = _make_db(rows)
        patcher = mock.patch.object(provider_mod, "_ICHOR_DB", db)
        patcher.start()
        self.addCleanup(patcher.stop)
        return db

    def test_zeroed_edge_is_lifted_off_zero(self):
        db = self._with_db([(1, "knows", 614, 4450, 0.7, 0.0, "dream_decay_archived",
                             None, None, "2026-09-01")])
        touched = self.provider._reinforce_edges([_graph_entry(614, 4450, "knows")])
        self.assertEqual(touched, 1)
        weight, provenance = _weight(db, 1)
        self.assertAlmostEqual(weight, _REINFORCE_ALPHA, places=4)
        self.assertGreater(weight, 0.0, "edge is still invisible to decay selection")
        self.assertEqual(provenance, "traverse_reinforced")

    def test_repeated_recall_compounds_and_never_exceeds_one(self):
        db = self._with_db([(1, "knows", 614, 4450, 0.7, 0.0, "dream_decay_archived",
                             None, None, "2026-09-01")])
        entry = [_graph_entry(614, 4450, "knows")]
        for _ in range(40):
            self.provider._reinforce_edges(entry)
        weight, _prov = _weight(db, 1)
        self.assertLessEqual(weight, 1.0, "reinforcement overshot 1.0")
        self.assertGreater(weight, 0.99)

    def test_only_graph_backed_entries_are_reinforced(self):
        db = self._with_db([(1, "knows", 614, 4450, 0.7, 0.0, "x", None, None, "t")])
        touched = self.provider._reinforce_edges(
            [_graph_entry(614, 4450, "knows", backend="fts5")]
        )
        self.assertEqual(touched, 0)
        self.assertEqual(_weight(db, 1)[0], 0.0)

    def test_entry_without_edge_triple_is_ignored(self):
        self._with_db([(1, "knows", 614, 4450, 0.7, 0.0, "x", None, None, "t")])
        touched = self.provider._reinforce_edges(
            [{"id": "graph:1:knows", "backend": "graph", "title": "no edge key"}]
        )
        self.assertEqual(touched, 0)

    def test_empty_and_none_inputs_are_safe(self):
        self._with_db([])
        self.assertEqual(self.provider._reinforce_edges([]), 0)
        self.assertEqual(self.provider._reinforce_edges(None), 0)

    def test_missing_table_is_non_fatal(self):
        bad = Path(tempfile.mkdtemp()) / "empty.db"
        sqlite3.connect(bad).close()
        patcher = mock.patch.object(provider_mod, "_ICHOR_DB", bad)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertEqual(
            self.provider._reinforce_edges([_graph_entry(614, 4450, "knows")]), 0
        )

    def test_per_turn_cap_is_enforced(self):
        rows = [
            (i, "knows", 614, 1000 + i, 0.7, 0.0, "x", None, None, "t")
            for i in range(1, 40)
        ]
        db = self._with_db(rows)
        entries = [_graph_entry(614, 1000 + i, "knows") for i in range(1, 40)]
        touched = self.provider._reinforce_edges(entries)
        self.assertLessEqual(touched, provider_mod._REINFORCE_MAX_PER_TURN)
        # the ones beyond the cap stay untouched
        self.assertEqual(_weight(db, 39)[0], 0.0)


class TestReinforcementWiring(unittest.TestCase):
    """The wiring: prefetch reinforces what it actually injects."""

    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def test_prefetch_reinforces_surfaced_graph_edges(self):
        db = _make_db([(1, "knows", 614, 4450, 0.7, 0.0, "dream_decay_archived",
                        None, None, "t")])
        with mock.patch.object(provider_mod, "_ICHOR_DB", db), \
                mock.patch.object(self.provider, "_query_fts5",
                                  side_effect=lambda q, limit=5: []), \
                mock.patch.object(self.provider, "_query_chroma", return_value=[]), \
                mock.patch.object(self.provider, "_query_graph",
                                  return_value=[_graph_entry(614, 4450, "knows")]):
            ctx = self.provider.prefetch("Who is Fia to me?", session_id="fixb")

        self.assertIn("--", ctx, "graph hit was not injected")
        weight, provenance = _weight(db, 1)
        self.assertGreater(weight, 0.0, "surfaced edge was not reinforced")
        self.assertEqual(provenance, "traverse_reinforced")

    def test_edges_fetched_but_dropped_are_not_reinforced(self):
        """Beyond the 5-entry inject cap => never seen => no reinforcement."""
        rows = [
            (i, "knows", 614, 2000 + i, 0.4, 0.0, "x", None, None, "t")
            for i in range(1, 9)
        ]
        db = _make_db(rows)
        weak = [
            {"id": f"graph:{2000 + i}:knows", "backend": "graph",
             "score": 0.4, "type": "person", "title": f"a --knows--> n{i}",
             "snippet": "s", "direction": "unknown",
             "edge": {"source": 614, "target": 2000 + i, "type": "knows"}}
            for i in range(1, 9)
        ]
        with mock.patch.object(provider_mod, "_ICHOR_DB", db), \
                mock.patch.object(self.provider, "_query_fts5",
                                  side_effect=lambda q, limit=5: []), \
                mock.patch.object(self.provider, "_query_chroma", return_value=[]), \
                mock.patch.object(self.provider, "_query_graph", return_value=weak):
            self.provider.prefetch("Who is Fia to me?", session_id="fixb-drop")

        # at least one edge beyond the injected head must remain at zero
        zeroed = [
            i for i in range(1, 9)
            if sqlite3.connect(db).execute(
                "SELECT weight FROM relationships WHERE id = ?", (i,)
            ).fetchone()[0] == 0.0
        ]
        self.assertTrue(zeroed, "every fetched edge was reinforced, not just injected ones")


if __name__ == "__main__":
    unittest.main(verbosity=2)
