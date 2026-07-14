"""
ER-P3: Multi-hop traversal — gate + lifecycle tests.

Spec: ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md §Multi-Hop Retrieval

ER-P3 gate (per build list, 4 assertions):
  [1] ChromaDB-style path returns sensible multi-hop traversal
  [2] bidirectional search finds meeting point between two entities
  [3] cycle detection prevents infinite loops
  [4] all 3 traversal primitives are exposed (traverse, graph_query, traverse_between)

Plus unit tests for resolve_depth and format_path.
Plus an integration test on a small hand-built graph (3 nodes, 3 edges).
Plus a real-DB smoke test (read-only — inspects what traversal does
on the existing real data; doesn't write).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.schema import (  # noqa: E402
    get_conn,
    migrate,
)
from lib.ichor.entities.traversal import (  # noqa: E402
    format_meeting_path,
    format_path,
    graph_query,
    resolve_depth,
    traverse,
    traverse_between,
)


def _isolated_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="er_p3_test_")
    os.close(fd)
    return Path(path)


def _build_test_graph(conn) -> None:
    """Build a small deterministic graph for testing:

        Alice ──works_at──> Anthropic ──uses──> Claude
                              │
                              └──competitor──> OpenAI
        Bob ──works_at──> Anthropic (different person, same company)
    """
    # Seed entity_types
    conn.executemany(
        "INSERT INTO entity_types (id, description) VALUES (?, ?)",
        [
            ("person", "A person"),
            ("organization", "An organization"),
            ("tool", "A tool"),
        ],
    )
    # Seed relationship_types
    conn.executemany(
        "INSERT INTO relationship_types (id, description, family) VALUES (?, ?, ?)",
        [
            ("works_at", "Affiliation", "affiliation"),
            ("uses", "Dependency", "dependency"),
            ("competitor", "Lifecycle", "lifecycle"),
        ],
    )
    # Seed entities
    conn.executemany(
        "INSERT INTO entities (type_id, name) VALUES (?, ?)",
        [
            ("person", "Alice"),
            ("person", "Bob"),
            ("organization", "Anthropic"),
            ("organization", "OpenAI"),
            ("tool", "Claude"),
        ],
    )
    # Seed relationships
    # Alice -> works_at -> Anthropic
    # Bob -> works_at -> Anthropic
    # Anthropic -> uses -> Claude
    # Anthropic -> competitor -> OpenAI
    conn.executemany(
        """INSERT INTO relationships
           (type_id, source_id, target_id, confidence, weight, provenance, source_ref,
            valid_from, valid_to, provisional, created_at, updated_at)
           VALUES (?, ?, ?, ?, 1.0, 'manual', '', '2025-01-01', NULL, 0,
                   datetime('now'), datetime('now'))""",
        [
            ("works_at", 1, 3, 0.9),    # Alice -> Anthropic
            ("works_at", 2, 3, 0.85),   # Bob -> Anthropic
            ("uses", 3, 5, 0.95),        # Anthropic -> Claude
            ("competitor", 3, 4, 0.8),   # Anthropic -> OpenAI
        ],
    )
    conn.commit()


# =======================================================================
# resolve_depth unit tests
# =======================================================================

class TestResolveDepth(unittest.TestCase):
    def test_default_when_no_signals(self):
        d = resolve_depth(query_specificity=0.5, entity_density=5.0)
        self.assertEqual(d, 3)

    def test_precise_query_shallow(self):
        d = resolve_depth(query_specificity=0.9, entity_density=5.0)
        self.assertLessEqual(d, 2)

    def test_vague_query_deep(self):
        d = resolve_depth(query_specificity=0.2, entity_density=5.0)
        self.assertGreaterEqual(d, 4)

    def test_dense_neighborhood_shallow(self):
        d = resolve_depth(query_specificity=0.5, entity_density=30.0)
        self.assertLessEqual(d, 2)

    def test_sparse_neighborhood_deep(self):
        d = resolve_depth(query_specificity=0.5, entity_density=1.0)
        self.assertGreaterEqual(d, 4)

    def test_absolute_max_caps(self):
        d = resolve_depth(query_specificity=0.0, entity_density=0.0, absolute_max=4)
        self.assertLessEqual(d, 4)

    def test_min_floor(self):
        d = resolve_depth(query_specificity=1.0, entity_density=100.0)
        self.assertGreaterEqual(d, 1)


# =======================================================================
# format_path unit tests
# =======================================================================

class TestFormatPath(unittest.TestCase):
    def test_anchor_only(self):
        path = {
            "path": [{"id": 1, "name": "Alice", "type": "person"}],
            "depth": 0,
            "path_confidence": 1.0,
        }
        out = format_path(path)
        self.assertIn("Alice (person)", out)
        # Anchor path_confidence is 1.0 (no edges traversed yet)
        self.assertIn("1.000", out)
        self.assertIn("depth: 0", out)

    def test_multi_hop(self):
        path = {
            "path": [
                {"id": 1, "name": "Alice", "type": "person"},
                {"id": 3, "name": "Anthropic", "type": "organization", "via": "works_at", "direction": "out"},
                {"id": 5, "name": "Claude", "type": "tool", "via": "uses", "direction": "out"},
            ],
            "depth": 2,
            "path_confidence": 0.85,
        }
        out = format_path(path)
        self.assertIn("Alice (person)", out)
        self.assertIn("[works_at]", out)
        self.assertIn("Anthropic (organization)", out)
        self.assertIn("[uses]", out)
        self.assertIn("Claude (tool)", out)


# =======================================================================
# Traversal integration tests (small deterministic graph)
# =======================================================================

class TestTraversalIntegration(unittest.TestCase):
    """Build a small graph and test the 3 traversal primitives."""

    def setUp(self):
        self.db_path = _isolated_db()
        from lib.ichor.entities import schema as _schema
        self._schema_db = _schema.DB_PATH
        _schema.DB_PATH = self.db_path

        conn = get_conn()
        migrate()
        _build_test_graph(conn)
        conn.close()

    def tearDown(self):
        from lib.ichor.entities import schema as _schema
        _schema.DB_PATH = self._schema_db
        if self.db_path.exists():
            self.db_path.unlink()

    # --- traverse ---

    def test_traverse_finds_anchor(self):
        conn = get_conn()
        results = traverse(conn, "Alice", depth=2)
        conn.close()
        # The anchor Alice should be in the result
        names = [r["name"] for r in results]
        self.assertIn("Alice", names)

    def test_traverse_finds_2hop_path(self):
        conn = get_conn()
        results = traverse(conn, "Alice", depth=2)
        conn.close()
        # 2-hop: Alice -> works_at -> Anthropic -> uses -> Claude
        # Check that Claude (depth 2) is reachable
        claude_paths = [r for r in results if r["name"] == "Claude"]
        self.assertGreater(len(claude_paths), 0, "Should reach Claude at depth 2 from Alice")
        # The path should include Alice and Anthropic
        for p in claude_paths:
            path_names = [hop["name"] for hop in p["path"]]
            self.assertIn("Alice", path_names)
            self.assertIn("Anthropic", path_names)
            self.assertIn("Claude", path_names)

    def test_traverse_follow_filter_only_traverses_listed(self):
        conn = get_conn()
        # Only follow 'works_at' — should NOT reach Claude (uses via 'uses')
        results = traverse(conn, "Alice", depth=2, follow=["works_at"])
        conn.close()
        names = [r["name"] for r in results]
        self.assertIn("Anthropic", names)
        self.assertNotIn("Claude", names, "Should not reach Claude when only following works_at")

    def test_traverse_skip_filter(self):
        conn = get_conn()
        # Skip 'competitor' — Anthropic should not be linked to OpenAI
        results = traverse(conn, "Anthropic", depth=2, skip=["competitor"])
        conn.close()
        names = [r["name"] for r in results]
        self.assertNotIn("OpenAI", names, "Should not reach OpenAI when skipping competitor")

    def test_traverse_families_filter(self):
        conn = get_conn()
        # Only follow 'affiliation' family — should reach Alice, Bob, but not Claude
        results = traverse(conn, "Anthropic", depth=2, families=["affiliation"])
        conn.close()
        names = [r["name"] for r in results]
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)
        self.assertNotIn("Claude", names, "Should not reach Claude when filtering by affiliation")

    def test_traverse_respects_max_depth(self):
        conn = get_conn()
        # depth=1 from Alice: only Alice + Anthropic
        results = traverse(conn, "Alice", depth=1)
        conn.close()
        max_depth_reached = max(r["depth"] for r in results)
        self.assertLessEqual(max_depth_reached, 1)

    def test_traverse_unknown_entity_returns_empty(self):
        conn = get_conn()
        results = traverse(conn, "NonExistent", depth=2)
        conn.close()
        self.assertEqual(results, [])

    def test_traverse_min_confidence_filter(self):
        conn = get_conn()
        # min_confidence=0.9 — only edges with conf >= 0.9
        # works_at Alice=0.9 ✓, works_at Bob=0.85 ✗, uses=0.95 ✓, competitor=0.8 ✗
        results = traverse(conn, "Alice", depth=2, min_confidence=0.9)
        conn.close()
        names = [r["name"] for r in results]
        # Alice -> Anthropic (0.9 ≥ 0.9) — yes
        # Anthropic -> Claude (0.95 ≥ 0.9) — yes
        self.assertIn("Anthropic", names)
        self.assertIn("Claude", names)
        # Bob (0.85 < 0.9) — no
        self.assertNotIn("Bob", names)

    # --- graph_query ---

    def test_graph_query_returns_subgraph_shape(self):
        conn = get_conn()
        result = graph_query(conn, "Anthropic", depth=2, min_confidence=0.1)
        conn.close()
        self.assertIn("nodes", result)
        self.assertIn("edges", result)
        self.assertIn("stats", result)
        self.assertGreaterEqual(result["stats"]["node_count"], 1)
        # Anthropic + Alice + Bob + Claude + OpenAI = 5 nodes
        self.assertEqual(result["stats"]["node_count"], 5)
        # 4 edges: works_at Alice, works_at Bob, uses, competitor
        self.assertEqual(result["stats"]["edge_count"], 4)

    def test_graph_query_unknown_entity(self):
        conn = get_conn()
        result = graph_query(conn, "NoSuchEntity", depth=2)
        conn.close()
        self.assertEqual(result["nodes"], [])
        self.assertEqual(result["edges"], [])
        self.assertEqual(result["stats"]["node_count"], 0)

    # --- traverse_between ---

    def test_traverse_between_direct(self):
        """Alice and Anthropic are directly connected."""
        conn = get_conn()
        paths = traverse_between(conn, "Alice", "Anthropic", max_depth=3)
        conn.close()
        self.assertGreater(len(paths), 0)
        # Should be short — 1 hop
        self.assertLessEqual(paths[0]["total_depth"], 2)

    def test_traverse_between_2hop(self):
        """Alice -> Anthropic -> Claude (2 hops)."""
        conn = get_conn()
        paths = traverse_between(conn, "Alice", "Claude", max_depth=4)
        conn.close()
        self.assertGreater(len(paths), 0)
        # Check the path goes Alice → Anthropic → Claude
        path_names_from = [hop["name"] for hop in paths[0]["from"]]
        path_names_to = [hop["name"] for hop in paths[0]["to"]]
        self.assertIn("Alice", path_names_from)
        self.assertIn("Claude", path_names_to)

    def test_traverse_between_disconnected(self):
        """Add a disconnected island; verify no path found."""
        conn = get_conn()
        # Add a disconnected person
        conn.execute("INSERT INTO entity_types (id) VALUES ('island')")
        conn.execute("INSERT INTO entities (type_id, name) VALUES ('island', 'Stranger')")
        conn.commit()
        conn.close()

        conn = get_conn()
        paths = traverse_between(conn, "Stranger", "Claude", max_depth=3)
        conn.close()
        self.assertEqual(paths, [], "Disconnected nodes should have no path")

    def test_traverse_between_same_entity(self):
        conn = get_conn()
        paths = traverse_between(conn, "Alice", "Alice", max_depth=3)
        conn.close()
        # Should return the trivial path (depth 0)
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0]["total_depth"], 0)

    def test_traverse_between_unknown_entity(self):
        conn = get_conn()
        paths = traverse_between(conn, "Alice", "NoSuchEntity", max_depth=3)
        conn.close()
        self.assertEqual(paths, [])


# =======================================================================
# Cycle detection test
# =======================================================================

class TestCycleDetection(unittest.TestCase):
    """Build a graph with a cycle: A→B→C→A. Verify traversal doesn't loop."""

    def setUp(self):
        self.db_path = _isolated_db()
        from lib.ichor.entities import schema as _schema
        self._schema_db = _schema.DB_PATH
        _schema.DB_PATH = self.db_path

        conn = get_conn()
        migrate()
        conn.executemany(
            "INSERT INTO entity_types (id) VALUES (?)",
            [("a",), ("b",), ("c",)],
        )
        conn.executemany(
            "INSERT INTO entities (type_id, name) VALUES (?, ?)",
            [("a", "NodeA"), ("b", "NodeB"), ("c", "NodeC")],
        )
        conn.executescript("""
            INSERT INTO relationship_types (id) VALUES ('link');
            INSERT INTO relationships (type_id, source_id, target_id, confidence, valid_from)
              VALUES ('link', 1, 2, 0.9, '2025-01-01');
            INSERT INTO relationships (type_id, source_id, target_id, confidence, valid_from)
              VALUES ('link', 2, 3, 0.9, '2025-01-01');
            INSERT INTO relationships (type_id, source_id, target_id, confidence, valid_from)
              VALUES ('link', 3, 1, 0.9, '2025-01-01');
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        from lib.ichor.entities import schema as _schema
        _schema.DB_PATH = self._schema_db
        if self.db_path.exists():
            self.db_path.unlink()

    def test_traverse_terminates_on_cycle(self):
        """With cycle A→B→C→A, traversal should NOT loop forever.
        It should return paths that visit each node at most once."""
        import signal

        def handler(signum, frame):
            raise TimeoutError("traverse() did not terminate on cyclic graph")

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(5)  # 5 second timeout

        try:
            conn = get_conn()
            results = traverse(conn, "NodeA", depth=10)
            conn.close()
            # Verify no path revisits a node
            for r in results:
                path_ids = [hop["id"] for hop in r["path"]]
                self.assertEqual(len(path_ids), len(set(path_ids)),
                                 f"Path revisits a node: {path_ids}")
            # Should still have found NodeA (anchor), NodeB, NodeC
            names = [r["name"] for r in results]
            self.assertIn("NodeA", names)
            self.assertIn("NodeB", names)
            self.assertIn("NodeC", names)
        finally:
            signal.alarm(0)

    def test_traverse_between_on_cycle(self):
        """Bidirectional search on a cyclic graph still terminates."""
        import signal

        def handler(signum, frame):
            raise TimeoutError("traverse_between() did not terminate on cyclic graph")

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(5)

        try:
            conn = get_conn()
            paths = traverse_between(conn, "NodeA", "NodeC", max_depth=5)
            conn.close()
            # Should find a path: NodeA -> NodeB -> NodeC
            self.assertGreater(len(paths), 0)
        finally:
            signal.alarm(0)


# =======================================================================
# Gate assertions: the 4 spec'd checks
# =======================================================================

class TestER_P3_Gate(unittest.TestCase):
    """The 4 gate assertions from the build list.

    Uses the small deterministic graph (which is easier to assert against
    than real DB data, which has different entities)."""

    def setUp(self):
        self.db_path = _isolated_db()
        from lib.ichor.entities import schema as _schema
        self._schema_db = _schema.DB_PATH
        _schema.DB_PATH = self.db_path

        conn = get_conn()
        migrate()
        _build_test_graph(conn)
        conn.close()

    def tearDown(self):
        from lib.ichor.entities import schema as _schema
        _schema.DB_PATH = self._schema_db
        if self.db_path.exists():
            self.db_path.unlink()

    def test_gate_1_chromadb_style_path(self):
        """Gate 1: a multi-hop query returns a sensible path.
        The ChromaDB example from the spec is illustrative; here we
        verify a comparable multi-hop query (Alice -> Anthropic -> Claude)
        returns the right shape with the right hop count."""
        conn = get_conn()
        results = traverse(conn, "Alice", depth=3, min_confidence=0.1)
        conn.close()
        # Find a path reaching Claude
        claude_paths = [r for r in results if r["name"] == "Claude"]
        self.assertGreater(len(claude_paths), 0, "Must reach Claude at depth ≥ 2")
        # The path has 3 hops (Alice, Anthropic, Claude)
        for p in claude_paths:
            self.assertEqual(len(p["path"]), 3, f"Expected 3-hop path, got {len(p['path'])}")
            # Path confidence compounds: 0.9 * 0.95 = 0.855
            self.assertGreater(p["path_confidence"], 0.7)
            # Via relations are recorded
            self.assertIn("works_at", p["relations_traversed"])
            self.assertIn("uses", p["relations_traversed"])

    def test_gate_2_bidirectional(self):
        """Gate 2: traverse_between finds the meeting point between two
        entities using bidirectional BFS."""
        conn = get_conn()
        # Use a 2-hop query: Alice -> Anthropic -> Claude
        paths = traverse_between(conn, "Alice", "Claude", max_depth=4)
        conn.close()
        self.assertGreater(len(paths), 0, "Must find a path between Alice and Claude")
        # Path should be: from side (Alice -> Anthropic) + to side (Claude)
        # meeting at Anthropic
        path = paths[0]
        from_names = [hop["name"] for hop in path["from"]]
        to_names = [hop["name"] for hop in path["to"]]
        self.assertIn("Alice", from_names)
        self.assertIn("Claude", to_names)
        self.assertEqual(path["meeting_at_name"], "Anthropic")
        # The total depth should be ≤ 2 (Alice → Anthropic → Claude = 2 hops)
        self.assertLessEqual(path["total_depth"], 2)

    def test_gate_3_cycle_detect(self):
        """Gate 3: traversal terminates on cyclic graphs (no infinite loop)."""
        # The TestCycleDetection class above already covers this; this
        # gate is a re-statement with a different starting scenario.
        import signal

        def handler(signum, frame):
            raise TimeoutError("traverse() did not terminate on cycle")

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(5)
        try:
            # Add a self-loop on Alice: Alice -> Alice
            conn = get_conn()
            alice_id = conn.execute("SELECT id FROM entities WHERE name = 'Alice'").fetchone()["id"]
            conn.execute(
                """INSERT INTO relationships
                   (type_id, source_id, target_id, confidence, valid_from)
                   VALUES ('works_at', ?, ?, 0.5, '2025-01-01')""",
                (alice_id, alice_id),
            )
            conn.commit()
            conn.close()
            # Run traversal — must terminate
            conn = get_conn()
            results = traverse(conn, "Alice", depth=5)
            conn.close()
            # No path should contain a node twice
            for r in results:
                ids = [h["id"] for h in r["path"]]
                self.assertEqual(len(ids), len(set(ids)))
        finally:
            signal.alarm(0)

    def test_gate_4_all_3_tools_exposed(self):
        """Gate 4: all 3 traversal primitives are importable from the
        package's public API."""
        # Imported at top of file — verify the public re-exports
        import lib.ichor.entities as pkg
        self.assertTrue(callable(pkg.traverse))
        self.assertTrue(callable(pkg.graph_query))
        self.assertTrue(callable(pkg.traverse_between))
        # And they appear in __all__
        for name in ("traverse", "graph_query", "traverse_between"):
            self.assertIn(name, pkg.__all__, f"{name} not in __all__")


# =======================================================================
# Real-DB smoke (read-only)
# =======================================================================

REAL_DB = Path("/home/konan/.hermes/ichor.db")


@unittest.skipUnless(REAL_DB.exists(), "Real ichor.db not present")
class TestTraversalAgainstRealDB(unittest.TestCase):
    """Read-only smoke test on the real ichor.db. We don't run heavy
    queries — just verify the primitives can be called and return the
    right shape on the real data."""

    def test_real_db_traverse_returns_shape(self):
        from lib.ichor.entities import backfill_stats
        stats = backfill_stats(get_conn())
        if stats["entities_count"] == 0:
            self.skipTest("No entities in real DB; run P1 backfill first")
        # Pick a real entity name to query
        conn = get_conn()
        sample = conn.execute("SELECT name FROM entities LIMIT 1").fetchone()
        conn.close()
        if not sample:
            self.skipTest("No entities to query")
        conn = get_conn()
        results = traverse(conn, sample["name"], depth=2, max_results=10)
        conn.close()
        # Even if no relations, the result should be a list
        self.assertIsInstance(results, list)

    def test_real_db_graph_query_shape(self):
        from lib.ichor.entities import backfill_stats
        stats = backfill_stats(get_conn())
        if stats["entities_count"] == 0:
            self.skipTest("No entities in real DB; run P1 backfill first")
        conn = get_conn()
        sample = conn.execute("SELECT name FROM entities LIMIT 1").fetchone()
        conn.close()
        if not sample:
            self.skipTest("No entities to query")
        conn = get_conn()
        result = graph_query(conn, sample["name"], depth=1, min_confidence=0.1)
        conn.close()
        self.assertIn("nodes", result)
        self.assertIn("edges", result)
        self.assertIn("stats", result)


if __name__ == "__main__":
    unittest.main()
