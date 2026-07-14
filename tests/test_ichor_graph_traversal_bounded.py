"""
Ichor-Retrieval Phase 0 baseline + Phase 2 contract tests.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 0 (baseline) + §Phase 2 (bounded graph traversal)

This file has two halves:

  * TestBaseline_*   — currently PASS. They document the current
    behavior of `graph_query()` / `traverse()` and prove the weaknesses
    that Phase 2 must close: the `source_id OR target_id` JOIN
    pattern, the unbounded depth/timeout, and the absence of a
    `graph_query_by_id` entry point. These tests also include a
    dense-graph stress test that exposes the timeout-prone traversal.

  * TestContract_*   — currently FAIL (marked xfail(strict=False)). They
    assert the Phase 2 contract: bounded traversal with `max_nodes`,
    `max_edges`, `fanout`, and `timeout_ms`; a `graph_query_by_id`
    entry point; and a `partial: true` flag when the timeout is hit.

Acceptance criterion from the build spec §Phase 0:
  > At least one baseline test demonstrates current graph/retrieval
    weakness before implementation.

That test is `TestBaseline.test_traverse_uses_source_or_target_or_join`
(which proves the spec's flagged bad pattern) plus
`TestBaseline.test_dense_graph_traversal_actually_completes`
(which proves the timeout-prone behavior under realistic density).

No service restart required: all tests use isolated temp DBs.
"""
from __future__ import annotations

import inspect
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

try:
    import pytest
except ModuleNotFoundError:  # pragma: no cover - unittest fallback in minimal envs
    class _PytestStub:
        class mark:
            @staticmethod
            def xfail(*args, **kwargs):
                def _decorator(fn):
                    return fn

                return _decorator

    pytest = _PytestStub()


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.schema import get_conn, migrate  # noqa: E402
from lib.ichor.entities.traversal import (  # noqa: E402
    _find_start_entities,
    graph_query,
    graph_query_by_id,
    traverse,
)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _isolated_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="p0_bounded_")
    os.close(fd)
    return Path(path)


def _build_dense_conductor_graph(db_path: Path, neighbor_count: int = 30) -> None:
    """Build a dense graph around Conductor v2 — emulates the real shape.

    Conductor v2 is connected to `neighbor_count` downstream entities via
    `mentions` edges. Each downstream entity has 3 more neighbors (a
    small fanout at depth 2). This roughly matches the spec's "Conductor
    v2 fanout explodes before final LIMIT applies" condition.

    All confidences are above 0.5 so the diminishing-returns heuristic
    does not interfere.
    """
    migrate(db_path)
    conn = get_conn(db_path)
    try:
        # Conductor v2 + N neighbors (depth 1)
        conn.execute(
            "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
            (1, "project", "Conductor v2"),
        )
        for i in range(neighbor_count):
            conn.execute(
                "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
                (100 + i, "concept", f"Neighbor-{i}"),
            )
            conn.execute(
                "INSERT INTO relationships "
                "(type_id, source_id, target_id, confidence, valid_from) "
                "VALUES (?, ?, ?, ?, ?)",
                ("mentions", 1, 100 + i, 0.85, "2026-06-01"),
            )
        # Depth-2 fanout: each neighbor connects to 3 sub-neighbors
        sub_id = 1000
        for i in range(neighbor_count):
            for j in range(3):
                conn.execute(
                    "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
                    (sub_id, "concept", f"Sub-{i}-{j}"),
                )
                conn.execute(
                    "INSERT INTO relationships "
                    "(type_id, source_id, target_id, confidence, valid_from) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("related_to", 100 + i, sub_id, 0.70, "2026-06-01"),
                )
                sub_id += 1
        conn.commit()
    finally:
        conn.close()


class TestTemporalRetrieval(unittest.TestCase):
    def setUp(self) -> None:
        self.db_path = _isolated_db()
        migrate(self.db_path)
        conn = get_conn(self.db_path)
        try:
            conn.execute("INSERT OR IGNORE INTO entity_types (id, description) VALUES (?, ?)", ("person", "Person"))
            conn.execute(
                "INSERT OR IGNORE INTO entity_types (id, description) VALUES (?, ?)",
                ("organization", "Organization"),
            )
            conn.execute(
                "INSERT OR IGNORE INTO relationship_types (id, source_type, target_type) VALUES (?, ?, ?)",
                ("works_at", "person", "organization"),
            )
            conn.execute(
                "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
                (1, "person", "Alice"),
            )
            conn.execute(
                "INSERT INTO entities (id, type_id, name) VALUES (?, ?, ?)",
                (2, "organization", "Acme"),
            )
            conn.execute(
                "INSERT INTO relationships (type_id, source_id, target_id, valid_from, valid_to) VALUES (?, ?, ?, ?, ?)",
                ("works_at", 1, 2, "2024-01-01 00:00:00", "2025-01-01 00:00:00"),
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        for ext in ("-wal", "-shm"):
            sidecar = self.db_path.with_name(self.db_path.name + ext)
            if sidecar.exists():
                sidecar.unlink()

    def test_graph_query_by_id_filters_expired_relationship_by_default(self) -> None:
        conn = get_conn(self.db_path)
        try:
            current = graph_query_by_id(conn, 1, depth=1)
            historical = graph_query_by_id(conn, 1, depth=1, include_historical=True)
        finally:
            conn.close()
        self.assertEqual(current["stats"]["edge_count"], 0)
        self.assertEqual(current["stats"]["node_count"], 1)
        self.assertEqual(historical["stats"]["edge_count"], 1)
        self.assertEqual(historical["stats"]["node_count"], 2)



class TestBaseline(unittest.TestCase):
    """Documents the behavior the Phase 2 contract closes.

    After Phase 2 ships, the BFS-bounded path is the live behavior.
    The two absence-style tests (`test_graph_query_has_bounded_params`
    and `test_graph_query_by_id_is_exported`) are the *inverted*
    versions of the original "weakness proves the problem" tests —
    they now PASS, proving Phase 2's surface contract is in place.

    The remaining two tests (`test_traverse_uses_source_or_target_or_join`
    and `test_find_start_entities_can_explode`) still pass on purpose:
    they document that the legacy `traverse()` recursive-CTE path and
    `_find_start_entities()` LIKE-expansion are still present, just no
    longer on the canonical hot path (the MCP wrapper now goes
    query → entity_id → `graph_query_by_id`).
    """

    def setUp(self) -> None:
        self.db_path = _isolated_db()
        _build_dense_conductor_graph(self.db_path, neighbor_count=20)

    def tearDown(self) -> None:
        if self.db_path.exists():
            self.db_path.unlink()
        for ext in ("-wal", "-shm"):
            sidecar = self.db_path.with_name(self.db_path.name + ext)
            if sidecar.exists():
                sidecar.unlink()

    def test_traverse_uses_source_or_target_or_join(self) -> None:
        """WEAKNESS: traverse's CTE uses the bad OR-join pattern.

        Spec §Phase 2 (Current Problem):
          > Current traversal shape includes an `OR` join like:
          >     r.source_id = t.node_id OR r.target_id = t.node_id
          > SQLite plans this poorly and scans active relationships
          > through `idx_relationships_valid_to` instead of using
          > source/target indexes.

        We confirm this by inspecting the SQL source.
        """
        src = inspect.getsource(traverse)
        # The bad pattern
        self.assertIn(
            "r.source_id = t.node_id OR r.target_id = t.node_id",
            src,
            "Spec-flagged bad pattern still present in traverse() — "
            "Phase 2 must replace it with separate source_id / target_id "
            "queries.",
        )

    def test_dense_graph_traversal_actually_completes(self) -> None:
        """Baseline: even a dense graph completes (no infinite loop).

        This is a SAFETY test — it doesn't prove the spec's timeout
        problem (which is MCP-level, not the underlying recursive
        CTE), but it does prove that the current code at least
        returns SOMETHING for a dense entity.

        With 20 neighbors × 3 sub-neighbors = 80 entities at depth 2,
        the current `graph_query` returns within seconds. Phase 2 must
        keep this property and add a timeout ceiling.
        """
        start = time.time()
        conn = get_conn(self.db_path)
        try:
            result = graph_query(conn, "Conductor v2", depth=2, min_confidence=0.5)
        finally:
            conn.close()
        elapsed = time.time() - start

        # Safety: completes in under 30s on this small fixture
        self.assertLess(
            elapsed, 30.0,
            f"graph_query took {elapsed:.2f}s on a 80-entity fixture — "
            "traversal shape may be unbounded",
        )
        # Has nodes and edges
        self.assertGreater(len(result["nodes"]), 0)
        self.assertGreater(len(result["edges"]), 0)

    def test_graph_query_has_bounded_params(self) -> None:
        """Phase 2 surface contract: graph_query now exposes the bounded knobs.

        This is the INVERTED version of the original
        `test_graph_query_signature_lacks_bounded_params` weakness
        test. It now PASSES because Phase 2 added `max_nodes`,
        `max_edges`, `fanout`, and `timeout_ms` to `graph_query()`'s
        signature (the legacy CTE path silently accepts them; the
        new `graph_query_by_id()` honors them).
        """
        sig = inspect.signature(graph_query)
        for param in ("max_nodes", "max_edges", "fanout", "timeout_ms"):
            self.assertIn(
                param, sig.parameters,
                f"Phase 2 must add `{param}` to graph_query()",
            )

    def test_graph_query_by_id_is_exported(self) -> None:
        """Phase 2 surface contract: graph_query_by_id is exported.

        This is the INVERTED version of the original
        `test_no_graph_query_by_id_entrypoint` weakness test. It now
        PASSES because Phase 2 added `graph_query_by_id` to
        `lib.ichor.entities` so the MCP wrapper can resolve a query
        to a canonical entity_id first and bypass the multi-start
        fuzzy-prefix expansion.
        """
        from lib.ichor.entities import graph_query_by_id  # noqa: F401
        # Confirm the canonical-ID signature too.
        sig = inspect.signature(graph_query_by_id)
        for param in (
            "entity_id", "depth", "min_confidence", "max_nodes",
            "max_edges", "fanout", "timeout_ms", "include_provisional",
        ):
            self.assertIn(
                param, sig.parameters,
                f"Phase 2 must expose `{param}` on graph_query_by_id",
            )

    def test_find_start_entities_can_explode(self) -> None:
        """WEAKNESS: start resolution can return many entities.

        Spec §Phase 2:
          > Avoid this pattern:
          >     query -> resolved name -> graph_query(name) ->
          >       internal LIKE expansion to many starts
          > Use:
          >     query -> resolved entity_id -> graph_query_by_id(entity_id)

        We prove the current entry path uses a `name LIKE %x%` LIKE
        that can return many rows.
        """
        src = inspect.getsource(_find_start_entities)
        self.assertIn(
            "name LIKE", src,
            "_find_start_entities still uses LIKE expansion — Phase 2 "
            "must use canonical entity-id resolution at the MCP seam.",
        )


# ─────────────────────────────────────────────────────────────────────
# CONTRACT: Phase 2 deliverables (xfail until Phase 2 ships)
# ─────────────────────────────────────────────────────────────────────

class TestContract:
    """Phase 2 contract — bounded traversal + graph_query_by_id."""

    def test_graph_query_by_id_exists(self) -> None:
        from lib.ichor.entities import graph_query_by_id
        sig = inspect.signature(graph_query_by_id)
        for param in (
            "entity_id", "depth", "min_confidence", "max_nodes",
            "max_edges", "fanout", "timeout_ms", "include_provisional",
        ):
            assert param in sig.parameters, (
                f"Phase 2 must expose `{param}` on graph_query_by_id"
            )

    def test_graph_query_bounded_params_present(self) -> None:
        sig = inspect.signature(graph_query)
        for param in ("max_nodes", "max_edges", "fanout", "timeout_ms"):
            assert param in sig.parameters, (
                f"Phase 2 must add `{param}` to graph_query()"
            )

    def test_bounded_traversal_respects_max_nodes(self) -> None:
        """Phase 2: setting max_nodes caps the node count."""
        from lib.ichor.entities import graph_query_by_id
        db_path = _isolated_db()
        try:
            _build_dense_conductor_graph(db_path, neighbor_count=10)
            conn = get_conn(db_path)
            try:
                # Conductor v2 is id=1
                result = graph_query_by_id(
                    conn, 1, depth=2, min_confidence=0.5,
                    max_nodes=5, max_edges=10, fanout=50, timeout_ms=1500,
                )
            finally:
                conn.close()
            assert len(result["nodes"]) <= 5
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_bounded_traversal_returns_partial_on_timeout(self) -> None:
        """Phase 2: hitting the timeout returns partial=True."""
        from lib.ichor.entities import graph_query_by_id
        db_path = _isolated_db()
        try:
            # Make it dense: 200 neighbors → with a 1ms timeout, the
            # bounded BFS must declare partial.
            _build_dense_conductor_graph(db_path, neighbor_count=200)
            conn = get_conn(db_path)
            try:
                result = graph_query_by_id(
                    conn, 1, depth=3, min_confidence=0.0,
                    max_nodes=10000, max_edges=10000, fanout=50,
                    timeout_ms=1,  # 1ms — guaranteed to time out
                )
            finally:
                conn.close()
            assert result.get("partial") is True, (
                "Phase 2 must set partial=True when timeout_ms is hit"
            )
        finally:
            if db_path.exists():
                db_path.unlink()


# Phase 2 (bounded graph traversal) shipped — remove the xfail markers
# below to keep the contract tests live. The `_XFAIL_REASON` constant
# is kept as a no-op marker so the test names + reasons are documented
# in version control (useful when reading the test history).
_XFAIL_REASON = (
    "Phase 2 (bounded graph traversal) shipped — see "
    "ichor-athenaeum-god-aware-retrieval-build-spec-v1.md §Phase 2. "
    "Markers removed; the tests are now live gates."
)
# No-op loop kept intentionally so the marker semantics are explicit
# (the original implementation used setattr to mark each method).
# If Phase 2 is ever reverted, re-add the xfail wrappers here.
for _name in ():
    setattr(
        TestContract,
        _name,
        pytest.mark.xfail(reason=_XFAIL_REASON, strict=False)(
            getattr(TestContract, _name)
        ),
    )
