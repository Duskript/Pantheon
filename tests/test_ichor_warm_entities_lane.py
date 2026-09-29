#!/usr/bin/env python3
"""Warm-tier entity lookup: the lane the provider has promised since P4a.

`warm_entities` (Rule 43's single-source table) had **no retrieval path and no
index**: `provider.py`'s T2 slot documented itself as "replaced by FTS5 +
WARM entity lookup" while `_query_chroma` returned `[]`, and nothing else read
the table either. `WarmEntitiesBackend` + `warm_entities_fts` supply that path.

What these tests pin:

  1. **Indexed or nothing.** With `warm_entities_fts` missing the lane returns
     `[]` — it must never degrade to a `LIKE` scan over 188k rows.
  2. **The quality gate.** 97.4% of the table is the naive extractor's echo
     (`blocker crash`, `commitment TODO`); those rows must not reach a turn.
     Gated out: category-echo values, punctuation/JSON/markdown names, names
     under 3 or over 60 chars, names longer than 5 words, rows with no
     brief/outline text.
  3. **The relevance floor.** Loose OR-rung matches below half the top row's
     overlap score are dropped instead of occupying context slots.
  4. **Field weighting.** A name hit outranks a brief hit outranks a value hit.
  5. **Ordering and bounds.** `limit` is honoured, scores descend, <= 1.0.
  6. **Registration.** `warm` is registered and in the default lane list by
     default; absent under `ICHOR_WARM_ENABLED=false`.

Hermetic: a temp SQLite DB built in the test, with the real migration DDL.

    cd /home/konan/pantheon
    PYTHONPATH=/home/konan/.hermes/vendor/zvec:/home/konan/pantheon \\
      /usr/local/lib/hermes-agent/venv/bin/python3 tests/test_ichor_warm_entities_lane.py
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

from lib.ichor.migrations.v2_warm_entities_fts import DDL  # noqa: E402
from lib.ichor_hybrid import WarmEntitiesBackend  # noqa: E402

BASE_SCHEMA = """
CREATE TABLE warm_entities (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    importance REAL DEFAULT 50.0,
    trust REAL DEFAULT 50.0,
    maturity TEXT DEFAULT 'validated',
    last_access TEXT,
    related_to TEXT,
    brief TEXT DEFAULT '',
    outline TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE (category, name)
);
"""

# (category, name, value, brief)
GOOD_ROWS = [
    ("tool", "ChromaDB", "ChromaDB vector store", "A vector database that is not coming back."),
    ("concept", "OAuth", "OAuth protocol", "An authentication protocol used by API triggers."),
    ("file", "DESIGN.md", "DESIGN.md doc", "Design document for the conductor project."),
    ("project", "Pantheon", "Pantheon system", "System housing conductor v2 and connectors."),
    # Weak row on purpose: its only overlap with the floor queries below is one
    # token inside `value` (weight 1), so it can only surface via the loose OR
    # rung of the MATCH ladder.
    ("fact", "Widget Note", "unrelated filler text", "A brief note about a widget."),
]

# Each of these must be gated out, for the stated reason.
JUNK_ROWS = [
    ("blocker", "crash", "blocker crash", "A blocker that appeared during a run."),          # category echo
    ("commitment", "**", "commitment TODO", "A commitment to follow up on."),                 # punctuation name
    ("follow_up", "v2", "follow_up v2", "Follow up about version two later."),                # <3 chars
    ("reference", 'json{"a":1}', "reference payload", "A reference payload fragment here."),  # JSON punctuation
    ("fact", "db is", "fact db is", "A fact about the database being ready."),                # 2 words? kept? -> see test
    ("insight", "one two three four five six", "insight long", "An insight with a very long name."),  # >5 words
    ("blocker", "nodetail", "blocker nodetail", ""),                                          # no brief/outline
]


class _Fixture:
    def __init__(self, with_fts: bool = True) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ichor.db"
        conn = sqlite3.connect(str(self.path))
        conn.executescript(BASE_SCHEMA)
        rows = [(c, n, v, b) for c, n, v, b in GOOD_ROWS]
        junk = [(c, n, v, b) for c, n, v, b in JUNK_ROWS]
        for cat, name, value, brief in rows + junk:
            conn.execute(
                "INSERT INTO warm_entities (category, name, value, brief) VALUES (?,?,?,?)",
                (cat, name, value, brief),
            )
        if with_fts:
            conn.executescript(DDL)
            conn.execute("INSERT INTO warm_entities_fts(warm_entities_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()

    def backend(self) -> WarmEntitiesBackend:
        return WarmEntitiesBackend(db_path=self.path)

    def cleanup(self) -> None:
        self.dir.cleanup()


class TestWarmSearch(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture()
        self.be = self.fx.backend()

    def tearDown(self) -> None:
        self.fx.cleanup()

    def test_returns_shaped_rows(self):
        hits = self.be.search("chromadb vector database", limit=5)
        self.assertTrue(hits)
        top = hits[0]
        self.assertEqual(top["backend"], "warm")
        self.assertEqual(top["title"], "ChromaDB")
        self.assertEqual(top["type"], "tool")
        self.assertIn("warm_entity_overlap", top["rank_reasons"])
        self.assertLessEqual(top["score"], 1.0)

    def test_category_echo_rows_are_gated_out(self):
        # "crash"/blocker carries value "blocker crash" — the extractor echo.
        hits = self.be.search("crash blocker", limit=10)
        self.assertNotIn("warm:1", [h["id"] for h in hits])
        self.assertFalse([h for h in hits if h["title"] == "crash"])

    def test_punctuation_and_short_names_are_gated_out(self):
        for q, bad in (("commitment todo follow up", "**"),
                       ("version two follow up", "v2"),
                       ("reference payload fragment", 'json{"a":1}')):
            titles = [h["title"] for h in self.be.search(q, limit=10)]
            self.assertNotIn(bad, titles, f"{bad!r} should be gated out for {q!r}")

    def test_long_names_and_detail_less_rows_are_gated_out(self):
        titles = [h["title"] for h in self.be.search("insight long name words", limit=10)]
        self.assertNotIn("one two three four five six", titles)
        titles = [h["title"] for h in self.be.search("nodetail blocker", limit=10)]
        self.assertNotIn("nodetail", titles)

    def test_good_rows_survive_the_gate(self):
        titles = [h["title"] for h in self.be.search("pantheon conductor connectors", limit=10)]
        self.assertIn("Pantheon", titles)

    def test_relevance_floor_drops_weak_matches(self):
        # "chromadb unrelated" matches ChromaDB on its name (x3) and Widget Note
        # only inside `value` (x1). The AND rungs match nothing, so both arrive
        # via the OR rung and the floor is what separates them.
        hits = self.be.search("chromadb unrelated", limit=10)
        self.assertTrue(hits)
        titles = [h["title"] for h in hits]
        self.assertEqual(titles[0], "ChromaDB")
        self.assertNotIn("Widget Note", titles)
        best = hits[0]["score"]
        self.assertTrue(all(h["score"] >= 0.5 * best for h in hits))

    def test_floor_disabled_keeps_the_weak_match(self):
        """The floor is doing the work, not the MATCH ladder."""
        self.be._MIN_REL = 0.0
        titles = [h["title"] for h in self.be.search("chromadb unrelated", limit=10)]
        self.be._MIN_REL = 0.5
        self.assertIn("Widget Note", titles)

    def test_name_hit_outranks_brief_only_hit(self):
        hits = self.be.search("oauth authentication protocol", limit=5)
        self.assertEqual(hits[0]["title"], "OAuth")

    def test_limit_is_honoured_and_scores_descend(self):
        hits = self.be.search("database conductor protocol document", limit=2)
        self.assertLessEqual(len(hits), 2)
        scores = [h["score"] for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_include_raw_attaches_value(self):
        hits = self.be.search("chromadb", limit=1, include_raw=True)
        self.assertIn("raw_text", hits[0])

    def test_empty_and_stopword_queries_return_nothing(self):
        self.assertEqual(self.be.search("", limit=5), [])
        self.assertEqual(self.be.search("the of and", limit=5), [])

    def test_health_reflects_index_presence(self):
        self.assertTrue(self.be.health())


class TestWarmWithoutIndex(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = _Fixture(with_fts=False)
        self.be = self.fx.backend()

    def tearDown(self) -> None:
        self.fx.cleanup()

    def test_missing_index_returns_empty_not_a_scan(self):
        """The lane must refuse to fall back to a 188k-row LIKE scan."""
        self.assertEqual(self.be.search("chromadb oauth pantheon", limit=5), [])
        self.assertFalse(self.be.health())


class _StubBackend:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def search(self, *args, **kwargs):
        return []


class TestWarmRegistration(unittest.TestCase):
    def _build(self, warm_enabled: str):
        import lib.ichor_hybrid as hybrid

        env = {
            "ICHOR_WARM_ENABLED": warm_enabled,
            "ICHOR_REFERENCE_ENABLED": "false",
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
        self.assertIn("warm", scorer._backends)

    def test_lane_absent_when_disabled(self):
        scorer = self._build("false")
        self.assertNotIn("warm", scorer._backends)

    def test_warm_is_in_the_default_lane_set(self):
        import inspect

        import lib.ichor_hybrid as hybrid

        source = inspect.getsource(hybrid.HybridScorer.retrieve)
        self.assertIn('backends = ["fts5", "graph", "reference", "warm"]', source)

    def test_warm_weight_lives_in_the_extra_dict(self):
        """Opt-in lane: the exported WEIGHTS dict (and the C2 drift gate) is untouched."""
        import lib.ichor_hybrid as hybrid

        self.assertNotIn("warm", hybrid.WEIGHTS)
        self.assertIn("warm", hybrid._EXTRA_BACKEND_WEIGHTS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
