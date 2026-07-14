"""
Ichor-Retrieval Phase 0 baseline + Phase 1 contract tests.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 0 (baseline) + §Phase 1 (validated-only graph)

This file has two halves:

  * TestBaseline_*   — currently PASS. They document the current behavior
    of `graph_query()` and prove the weakness: the function mixes
    provisional and validated entities/edges with no opt-in flag, no
    response metadata, and no scope enforcement. This is the "before"
    picture that motivates Phase 1.

  * TestContract_*   — currently FAIL (marked xfail(strict=False)). They
    assert the Phase 1 contract: validated-only by default, with an
    explicit opt-in for provisional, and response metadata that names
    the scope. When Phase 1 lands, remove the xfail markers.

Acceptance criterion from the build spec §Phase 0:
  > At least one baseline test demonstrates current graph/retrieval
  > weakness before implementation.

That test is `TestBaseline.test_graph_query_currently_mixes_provisional_rows`.

No service restart required: all tests use isolated temp DBs.
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from pathlib import Path


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.schema import get_conn, migrate  # noqa: E402
from lib.ichor.entities.traversal import graph_query  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _isolated_db() -> Path:
    """Return a fresh temp DB path. Caller is responsible for cleanup."""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="p0_validated_")
    os.close(fd)
    return Path(path)


def _build_mixed_provisional_graph(db_path: Path) -> None:
    """Build a small graph with a mix of provisional + validated edges.

    Schema types and relationship types used here are the ones
    pre-seeded by `migrate()` (see lib/ichor/entities/{entity,
    relationship}_type_seeds.py). We do NOT add new types — that
    would collide with the seeds.

    All confidences are intentionally high (0.85–0.95) so that the
    "diminishing returns" heuristic in `traverse()` does not trim any
    of them. That ensures the test genuinely proves the absence of a
    provisional filter, not the absence of low-confidence rows.

    Layout (all edges from Conductor v2 outward):

        Conductor v2 ─depends_on (validated,   conf=0.95)──> NATS
        Conductor v2 ─mentions   (validated,   conf=0.90)──> MCP
        Conductor v2 ─requires   (PROVISIONAL, conf=0.95)──> systemd
        Conductor v2 ─related_to (PROVISIONAL, conf=0.90)──> OldRuntime
        Conductor v2 ─replaces   (PROVISIONAL, conf=0.85)──> Conductor v1

    Phase 1 must hide the three provisional edges/entities by default.
    """
    migrate(db_path)
    conn = get_conn(db_path)
    try:
        # Entities — types project + concept are pre-seeded by migrate()
        conn.executemany(
            "INSERT INTO entities (id, type_id, name, provisional) VALUES (?, ?, ?, ?)",
            [
                (1, "project", "Conductor v2", 0),     # start (validated)
                (2, "concept", "NATS", 0),              # validated neighbor
                (3, "concept", "MCP", 0),               # validated neighbor
                (4, "concept", "systemd", 1),           # PROVISIONAL neighbor
                (5, "project", "OldRuntime", 1),        # PROVISIONAL neighbor
                (6, "project", "Conductor v1", 1),      # PROVISIONAL neighbor
            ],
        )
        # Relationships — types depend_on/mentions/requires/related_to/
        # replaces are pre-seeded by migrate()
        conn.executemany(
            "INSERT INTO relationships "
            "(type_id, source_id, target_id, confidence, valid_from, provisional) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("depends_on",  1, 2, 0.95, "2026-06-01", 0),  # validated
                ("mentions",    1, 3, 0.90, "2026-06-01", 0),  # validated
                ("requires",    1, 4, 0.95, "2026-06-15", 1),  # PROVISIONAL
                ("related_to",  1, 5, 0.90, "2026-06-16", 1),  # PROVISIONAL
                ("replaces",    1, 6, 0.85, "2026-06-17", 1),  # PROVISIONAL
            ],
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────
# CONTRACT: Phase 1 deliverables (live as of Phase 1 ship)
# ─────────────────────────────────────────────────────────────────────

class TestContract:
    """Phase 1 contract — validated-only graph by default.

    These tests are the live gate for Phase 1. They were xfail while
    Phase 0 (baseline) tests documented the bug; once Phase 1 ships,
    the xfail markers come off and the TestBaseline class is removed
    (the bug it documented is now fixed).
    """

    def test_default_graph_query_excludes_provisional(self) -> None:
        db_path = _isolated_db()
        try:
            _build_mixed_provisional_graph(db_path)
            conn = get_conn(db_path)
            try:
                result = graph_query(conn, "Conductor v2", depth=1, min_confidence=0.3)
            finally:
                conn.close()

            edge_types = sorted({e["type"] for e in result["edges"]})
            node_names = sorted({n["name"] for n in result["nodes"]})

            # Only validated edges remain
            assert "depends_on" in edge_types
            assert "mentions" in edge_types
            assert "requires" not in edge_types
            assert "related_to" not in edge_types
            assert "replaces" not in edge_types

            # Only validated nodes
            assert "NATS" in node_names
            assert "MCP" in node_names
            assert "systemd" not in node_names
            assert "OldRuntime" not in node_names
            assert "Conductor v1" not in node_names
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_include_provisional_true_returns_everything(self) -> None:
        db_path = _isolated_db()
        try:
            _build_mixed_provisional_graph(db_path)
            conn = get_conn(db_path)
            try:
                sig = inspect.signature(graph_query)
                assert "include_provisional" in sig.parameters, (
                    "Phase 1 must add include_provisional kwarg"
                )
                # Use a kwargs dict so the call compiles today (Phase 1
                # not yet shipped). When Phase 1 lands, the dict has
                # the correct shape and the call succeeds.
                call_kwargs = {
                    "depth": 1,
                    "min_confidence": 0.3,
                    "include_provisional": True,
                }
                result = graph_query(conn, "Conductor v2", **call_kwargs)
            finally:
                conn.close()

            edge_types = sorted({e["type"] for e in result["edges"]})
            assert "depends_on" in edge_types
            assert "requires" in edge_types
        finally:
            if db_path.exists():
                db_path.unlink()

    def test_response_includes_validation_metadata(self) -> None:
        db_path = _isolated_db()
        try:
            _build_mixed_provisional_graph(db_path)
            conn = get_conn(db_path)
            try:
                result = graph_query(conn, "Conductor v2", depth=1, min_confidence=0.3)
            finally:
                conn.close()

            assert "validation_scope" in result
            assert result["validation_scope"] == "validated_only"
            assert "validated_entities_used" in result
            assert "provisional_entities_skipped" in result
            assert "validated_relationships_used" in result
            assert "provisional_relationships_skipped" in result

            # On our seed: 3 provisional neighbor entities skipped
            assert isinstance(result["provisional_entities_skipped"], int)
            assert result["provisional_entities_skipped"] >= 3
        finally:
            if db_path.exists():
                db_path.unlink()
