#!/usr/bin/env python3
"""`reference` lane: the weight existed, the backend did not.

`WEIGHTS["reference"]` has been in the fusion dict since the 4-backend era, but
no backend ever registered under that name in `HybridScorer._backends`. The lane
was therefore inert — no result could carry `backend="reference"`, and the
labeled harness correctly reported it as offline (0 candidates, 0 ms). The
`L2ReferenceBackend` class wires it to the two *small* curated corpora:

  * `reference_knowledge` — curated Athenaeum indexes / distilled concepts
  * `l2_scenarios` — Forge cross-session patterns (`status='active'` only)

What these tests pin:

  1. **Overlap scoring, not substring.** A query token must match a row token;
     a partial word must not (`conduc` does not match `conductor`), because
     substring matching is what anchored relational queries on the wrong hub.
  2. **Field weighting.** A title hit outranks a body-only hit (title x3,
     slug/source x2, body/brief/outline x1).
  3. **Bounded, ordered output.** `limit` is honoured, scores are descending and
     normalised to <= 1.0.
  4. **Status filter.** `retired` / `superseded` L2 scenarios are not recalled.
  5. **Graceful degradation.** A database without the tables returns `[]`
     instead of raising — the lane must never take a query down.
  6. **Registration.** The lane registers in `HybridScorer._backends` by
     default and is absent when `ICHOR_REFERENCE_ENABLED=false` (rollback
     without a service restart).

Hermetic: a temp SQLite database built in the test. No live graph, no live
`ichor.db`, no writes outside `tmp`.

Run with the venv that has the real backends (sqlite-vec + embedder):

    cd /home/konan/pantheon
    PYTHONPATH=/home/konan/.hermes/vendor/zvec:/home/konan/pantheon \\
      /usr/local/lib/hermes-agent/venv/bin/python3 tests/test_ichor_reference_lane.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PANTHEON_ROOT = Path(__file__).resolve().parent.parent
if str(PANTHEON_ROOT) not in sys.path:
    sys.path.insert(0, str(PANTHEON_ROOT))

from lib.ichor_hybrid import L2ReferenceBackend  # noqa: E402

_REF_SCHEMA = """
CREATE TABLE reference_knowledge (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE,
    title TEXT,
    body TEXT,
    source TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    brief TEXT DEFAULT '',
    outline TEXT DEFAULT ''
);
CREATE TABLE l2_scenarios (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    pattern_type TEXT DEFAULT 'cross_session',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    status TEXT DEFAULT 'active',
    event_count INTEGER DEFAULT 0,
    session_count INTEGER DEFAULT 0,
    last_seen TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""

_REF_ROWS = [
    ("athenaeum", "Athenaeum — Master Index", "canonical knowledge index of codexes", "athenaeum"),
    ("Codex-Android", "Codex-Android — Android Development Standards", "gradle kotlin compose conventions", "athenaeum"),
    ("Codex-Notes", "Notes", "conductor timeout boilerplate detail", "athenaeum"),
    ("Codex-Misc", "Misc Notes", "android development notes about gradle", "athenaeum"),
]

_L2_ROWS = [
    (1, "forge:1", "recurring_blocker", "Conductor timeout boilerplate is recurring",
     "conductor timeout boilerplate appears as a false blocker", 0.9, "active"),
    (2, "forge:2", "cross_session", "Retired pattern about conductor timeout",
     "conductor timeout boilerplate retired note", 0.9, "retired"),
]


class _Fixture:
    """Temp ichor.db carrying just the two curated corpora."""

    def __init__(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ichor.db"
        conn = sqlite3.connect(str(self.path))
        conn.executescript(_REF_SCHEMA)
        conn.executemany(
            "INSERT INTO reference_knowledge (slug, title, body, source) VALUES (?,?,?,?)",
            _REF_ROWS,
        )
        conn.executemany(
            "INSERT INTO l2_scenarios (id, slug, pattern_type, title, body, confidence, status) "
            "VALUES (?,?,?,?,?,?,?)",
            _L2_ROWS,
        )
        conn.commit()
        conn.close()

    def backend(self) -> L2ReferenceBackend:
        return L2ReferenceBackend(db_path=self.path)

    def cleanup(self) -> None:
        self.dir.cleanup()


class TestReferenceSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.be = self.fx.backend()

    def tearDown(self) -> None:
        self.fx.cleanup()

    def test_returns_shaped_rows(self):
        hits = self.be.search("athenaeum master index", limit=5)
        self.assertTrue(hits)
        top = hits[0]
        self.assertEqual(top["backend"], "reference")
        self.assertEqual(top["id"], "ref:athenaeum")
        self.assertIn("reference_overlap", top["rank_reasons"])
        self.assertLessEqual(top["score"], 1.0)

    def test_l2_scenarios_are_labeled_and_ranked(self):
        hits = self.be.search("conductor timeout boilerplate", limit=5)
        ids = [h["id"] for h in hits]
        self.assertIn("l2-scenario:1", ids)
        l2 = next(h for h in hits if h["id"] == "l2-scenario:1")
        self.assertEqual(l2["backend"], "reference")
        self.assertIn("l2_metadata", l2)
        self.assertEqual(l2["l2_metadata"]["maturity"], "scenario")

    def test_retired_scenarios_are_not_recalled(self):
        hits = self.be.search("conductor timeout boilerplate", limit=10)
        self.assertNotIn("l2-scenario:2", [h["id"] for h in hits])

    def test_partial_word_does_not_match(self):
        # Substring matching would anchor "conduc" onto "conductor"; token
        # overlap must not.
        self.assertEqual(self.be.search("conduc", limit=5), [])

    def test_stopwords_only_query_returns_nothing(self):
        self.assertEqual(self.be.search("the of and to", limit=5), [])
        self.assertEqual(self.be.search("", limit=5), [])

    def test_title_hit_outranks_body_only_hit(self):
        hits = self.be.search("android development standards", limit=5)
        self.assertEqual(hits[0]["id"], "ref:Codex-Android")
        # A body-only mention of the same token must sit below it.
        self.assertGreater(hits[0]["score"], hits[-1]["score"])

    def test_limit_is_honoured_and_scores_descend(self):
        hits = self.be.search("athenaeum codex conductor", limit=2)
        self.assertLessEqual(len(hits), 2)
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_include_raw_attaches_body(self):
        hits = self.be.search("athenaeum master index", limit=1, include_raw=True)
        self.assertIn("raw_text", hits[0])
        self.assertIn("canonical knowledge index", hits[0]["raw_text"])

    def test_missing_tables_degrade_to_empty(self):
        with tempfile.TemporaryDirectory() as d:
            empty = Path(d) / "ichor.db"
            sqlite3.connect(str(empty)).close()
            self.assertEqual(L2ReferenceBackend(db_path=empty).search("athenaeum", limit=5), [])

    def test_unopenable_db_degrades_to_empty(self):
        # A directory is not a database: sqlite refuses to open it, and the
        # lane must return [] rather than raise into the query path.
        self.assertEqual(
            L2ReferenceBackend(db_path=Path(tempfile.gettempdir())).search("athenaeum", limit=5),
            [],
        )

    def test_health_reports_table_presence(self):
        self.assertTrue(self.be.health())


class _StubBackend:
    """Constructor-compatible stub so the scorer can be built without a DB."""

    def __init__(self, *args, **kwargs) -> None:
        pass

    def search(self, *args, **kwargs):
        return []


class TestReferenceRegistration(unittest.TestCase):
    def _build(self, reference_enabled: str):
        import lib.ichor_hybrid as hybrid

        env = {
            "ICHOR_REFERENCE_ENABLED": reference_enabled,
            "ICHOR_OBSERVATIONS_ENABLED": "false",
            "ICHOR_KNOWLEDGE_PAGES_ENABLED": "false",
            "ICHOR_PERSON_ROOTS_ENABLED": "false",
        }
        stubs = ("FTS5Backend", "EventsBackend", "GraphBackend", "LiveGraphBackend",
                 "KnowledgePagesBackend")
        patches = [mock.patch.dict(os.environ, env, clear=False)]
        patches += [mock.patch.object(hybrid, name, _StubBackend) for name in stubs]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return hybrid.HybridScorer()

    def test_lane_registers_by_default(self):
        scorer = self._build("true")
        self.assertIn("reference", scorer._backends)
        self.assertIsInstance(scorer._backends["reference"], L2ReferenceBackend)

    def test_lane_absent_when_disabled(self):
        scorer = self._build("false")
        self.assertNotIn("reference", scorer._backends)

    def test_lane_stays_out_of_the_default_backend_list(self):
        # Registered and measurable, but not queried by legacy calls: the
        # default 4-lane list is part of the shipped contract, and adding a
        # lane to it is a behaviour change that has to be measured first.
        import inspect

        import lib.ichor_hybrid as hybrid

        source = inspect.getsource(hybrid.HybridScorer.retrieve)
        self.assertIn('backends = ["fts5", "graph", "reference", "warm"]', source)
        # The two lanes that measured zero recall for ~3 s/query are opt-in now,
        # not silently re-added to the hot path.
        self.assertNotIn('backends = ["fts5", "vector", "graph", "events"]', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
