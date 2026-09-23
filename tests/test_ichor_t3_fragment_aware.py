#!/usr/bin/env python3
"""Fragment-aware T3 anchoring — same-name sibling facets.

Problem
-------
`_query_graph` resolved each candidate name to ONE entity id, so a query for
"Thoth" walked one of six active `thoth`/`Thoth` rows and every edge hanging off
the other facets was invisible. Fragmentation is structural in this graph:
1,854 lowercase names carry more than one active row (11 'pantheon', 6 'thoth',
6 'mercer', 6 'lyric smith'), because merges only fold same-type rows and L2
extraction creates a new (name, type_id) pair for free.

Fix
---
`_resolve_entity_facets(name)` returns the canonical id first, then the
remaining active same-name rows by id, capped at `_T3_MAX_FACETS`; `_query_graph`
walks each facet and dedupes edges by (neighbour, relation).

Hermetic: a temp DB stands in for the live graph via a patched `_ICHOR_DB`.

Run with the hermes venv (no pytest there):
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_t3_fragment_aware.py
"""
from __future__ import annotations

import os
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

# name -> (id, type, status, merged_into)
FRAGMENTS = [
    (100, "Thoth", "person", "active", None),
    (101, "thoth", "tool", "active", None),
    (102, "Thoth", "concept", "active", None),
    (103, "Thoth", "project", "active", None),
    (104, "Thoth", "organization", "active", None),
    (105, "Thoth", "document", "merged", 100),
    (200, "Konan", "person", "active", None),
]


def _seed_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE entities (id INTEGER PRIMARY KEY, name TEXT, type_id TEXT, "
        "status TEXT, merged_into INTEGER, aliases TEXT, summary TEXT, "
        "provisional INTEGER DEFAULT 0)"
    )
    conn.execute(
        "CREATE TABLE entity_aliases (id INTEGER PRIMARY KEY, "
        "canonical_entity_id INTEGER, alias TEXT)"
    )
    # Degree ordering needs the edge table (indexed source_id/target_id in the
    # live schema; here a plain table is enough).
    conn.execute(
        "CREATE TABLE relationships (id INTEGER PRIMARY KEY, source_id INTEGER, "
        "target_id INTEGER, valid_to TEXT)"
    )
    for eid, name, type_id, status, merged_into in FRAGMENTS:
        conn.execute(
            "INSERT INTO entities (id, name, type_id, status, merged_into, aliases, summary) "
            "VALUES (?, ?, ?, ?, ?, '[]', ?)",
            (eid, name, type_id, status, merged_into, f"summary for {name} #{eid}"),
        )
    # Alias table drives the fast path: 'thoth' -> 100 (canonical facet).
    conn.execute("INSERT INTO entity_aliases (canonical_entity_id, alias) VALUES (100, 'thoth')")
    conn.execute("INSERT INTO entity_aliases (canonical_entity_id, alias) VALUES (200, 'Cybermage')")
    conn.commit()
    conn.close()


def _subgraph(start_id: int) -> dict:
    other = start_id + 1000
    return {
        "nodes": [
            {"id": start_id, "name": "Thoth", "type": "person", "summary": "seed", "provisional": 0},
            {"id": other, "name": f"Neighbour{start_id}", "type": "tool",
             "summary": f"edge from facet {start_id}", "provisional": 0},
        ],
        "edges": [
            {"source": start_id, "target": other, "type": "uses", "confidence": 0.8,
             "provisional": False},
        ],
        "stats": {"node_count": 2, "edge_count": 1},
    }


class TestResolveEntityFacets(unittest.TestCase):
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="t3_facets_")
        os.close(fd)
        self.db = Path(path)
        _seed_db(self.db)
        self._real_db = provider_mod._ICHOR_DB
        provider_mod._ICHOR_DB = self.db
        self.provider = IchorMemoryProvider()

    def tearDown(self) -> None:
        provider_mod._ICHOR_DB = self._real_db
        if self.db.exists():
            self.db.unlink()

    def test_canonical_id_comes_first_then_siblings(self):
        facets = self.provider._resolve_entity_facets("Thoth")
        self.assertEqual(facets[0], 100, "canonical (alias-resolved) facet must lead")
        self.assertEqual(facets, [100, 101, 102])

    def test_merged_rows_are_not_walked(self):
        self.assertNotIn(105, self.provider._resolve_entity_facets("Thoth"))

    def test_cap_is_enforced(self):
        with mock.patch.object(provider_mod, "_T3_MAX_FACETS", 4):
            self.provider._entity_facet_cache.clear()
            self.assertEqual(self.provider._resolve_entity_facets("Thoth"), [100, 101, 102, 103])

    def test_misses_are_memoised(self):
        self.assertEqual(self.provider._resolve_entity_facets("Nope Nothing"), [])
        calls = []
        real_connect = sqlite3.connect

        def _counting(*a, **kw):
            calls.append(a)
            return real_connect(*a, **kw)

        with mock.patch.object(provider_mod.sqlite3, "connect", side_effect=_counting):
            self.assertEqual(self.provider._resolve_entity_facets("Nope Nothing"), [])
        self.assertEqual(calls, [], "memoised miss still hit the DB")

    def test_case_insensitive_lookup(self):
        self.assertEqual(self.provider._resolve_entity_facets("THOTH"), [100, 101, 102])

    def test_unfragmented_name_yields_single_facet(self):
        self.assertEqual(self.provider._resolve_entity_facets("Cybermage"), [200])


class TestQueryGraphWalksEveryFacet(unittest.TestCase):
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="t3_facets_walk_")
        os.close(fd)
        self.db = Path(path)
        _seed_db(self.db)
        self._real_db = provider_mod._ICHOR_DB
        provider_mod._ICHOR_DB = self.db
        self.provider = IchorMemoryProvider()

    def tearDown(self) -> None:
        provider_mod._ICHOR_DB = self._real_db
        if self.db.exists():
            self.db.unlink()

    def test_walk_visits_canonical_and_siblings(self):
        anchors = []

        def _spy(conn, entity_id, **kwargs):
            anchors.append(entity_id)
            return _subgraph(entity_id)

        with mock.patch("lib.ichor.entities.traversal.graph_query_by_id", side_effect=_spy):
            results = self.provider._query_graph(["Thoth"], depth=2)

        self.assertEqual(anchors, [100, 101, 102], "T3 walked only part of the fragments")
        ids = {r["id"] for r in results}
        self.assertIn("graph:1100:uses", ids)
        self.assertIn("graph:1101:uses", ids, "sibling facet's edge never reached the results")
        self.assertIn("graph:1102:uses", ids)
        self.assertEqual(len(results), 3)

    def test_single_facet_name_still_walks_once(self):
        anchors = []

        def _spy(conn, entity_id, **kwargs):
            anchors.append(entity_id)
            return _subgraph(entity_id)

        with mock.patch("lib.ichor.entities.traversal.graph_query_by_id", side_effect=_spy):
            results = self.provider._query_graph(["Cybermage"], depth=2)

        self.assertEqual(anchors, [200])
        self.assertEqual(len(results), 1)


class TestDensityOrdering(unittest.TestCase):
    """A stub facet must never be walked first — it would fill (or empty) the
    global 12-slot result budget before the dense sibling is reached."""

    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="t3_facet_density_")
        os.close(fd)
        self.db = Path(path)
        _seed_db(self.db)
        conn = sqlite3.connect(str(self.db))
        # 100 (canonical via alias): 1 edge.  101: 0 edges.  102: 6 edges.
        conn.execute("INSERT INTO relationships (source_id, target_id, valid_to) VALUES (100, 900, NULL)")
        for i in range(6):
            conn.execute(
                "INSERT INTO relationships (source_id, target_id, valid_to) VALUES (102, ?, NULL)",
                (1000 + i,),
            )
        conn.commit()
        conn.close()
        self._real_db = provider_mod._ICHOR_DB
        provider_mod._ICHOR_DB = self.db
        self.provider = IchorMemoryProvider()

    def tearDown(self) -> None:
        provider_mod._ICHOR_DB = self._real_db
        if self.db.exists():
            self.db.unlink()

    def test_densest_facet_is_walked_first(self):
        facets = self.provider._resolve_entity_facets("Thoth")
        self.assertEqual(facets, [102, 100, 101], "dense facet must lead the walk")
        self.assertIn(100, facets, "canonical facet must still be walked")

    def test_walk_order_follows_density(self):
        anchors = []

        def _spy(conn, entity_id, **kwargs):
            anchors.append(entity_id)
            return _subgraph(entity_id)

        with mock.patch("lib.ichor.entities.traversal.graph_query_by_id", side_effect=_spy):
            self.provider._query_graph(["Thoth"], depth=2)
        self.assertEqual(anchors, [102, 100, 101])


if __name__ == "__main__":
    unittest.main(verbosity=2)
