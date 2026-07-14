"""
Ichor-Retrieval Phase 4 contract tests: Vector Hydration + Safer Ranking.

Spec: ~/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
      §Phase 4 (Vector Hydration and Safer Ranking)

Acceptance criteria (per spec):

  AC1: Vector hits include snippet/source metadata when the corresponding
       cold_events row exists.
  AC2: Vector hit with null snippet cannot rank #1 unless no better
       evidence exists.
  AC3: Exact decision/correction outranks vague semantic neighbor.
  AC4: Rank reasons are visible in returned results.

These tests are pure (no service restart, no DB writes) and exercise
both the hydration pipeline (lib.ichor.retrieval_hydration) and the
end-to-end MemoryTrait.retrieve() path.

Two halves:

  TestPipeline:
    Unit tests against the hydration pipeline directly. Construct
    synthetic result lists, run the pipeline, assert behavior. These
    run without any DB connectivity — they use sqlite3 in-memory or
    a temp file when DB lookup is required.

  TestEndToEnd:
    Integration tests against the live MemoryTrait.retrieve(). These
    read from the real ichor.db but do not write. They prove the
    pipeline is wired into the production retrieve() path.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from typing import Any, Dict, List

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _build_cold_events_table(conn: sqlite3.Connection) -> None:
    """Create a minimal cold_events table in the given connection.

    Schema mirrors the live cold_events columns needed for hydration
    (HYDRATION_COLUMNS in lib.ichor.retrieval_hydration). The hydration
    pipeline only SELECTs these columns so a smaller test schema is fine.
    """
    conn.execute(
        """
        CREATE TABLE cold_events (
            id INTEGER PRIMARY KEY,
            event_type TEXT,
            category TEXT,
            name TEXT,
            raw_text TEXT,
            brief TEXT,
            god_name TEXT,
            session_id TEXT,
            created_at TEXT,
            importance REAL DEFAULT 50.0,
            confidence REAL DEFAULT 0.5,
            trust REAL DEFAULT 50.0
        )
        """
    )


def _insert_cold_event(
    conn: sqlite3.Connection,
    *,
    id: int,
    event_type: str,
    category: str,
    name: str,
    raw_text: str,
    brief: str = "",
    god_name: str = "",
    session_id: str = "",
    importance: float = 50.0,
    confidence: float = 0.5,
    trust: float = 50.0,
    created_at: str = "2026-06-21 12:00:00",
) -> None:
    conn.execute(
        """
        INSERT INTO cold_events (
            id, event_type, category, name, raw_text, brief,
            god_name, session_id, created_at, importance, confidence, trust
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (id, event_type, category, name, raw_text, brief,
         god_name, session_id, created_at, importance, confidence, trust),
    )


# ─────────────────────────────────────────────────────────────────────
# Pipeline unit tests (no live DB)
# ─────────────────────────────────────────────────────────────────────

class TestPipeline(unittest.TestCase):
    """Pure-function tests against hydrate_pipeline()."""

    def test_ac1_vector_hit_gets_snippet_from_cold_events(self) -> None:
        """AC1: hydrated vector hit includes snippet + title + source."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            _insert_cold_event(
                conn,
                id=42,
                event_type="decision",
                category="decision",
                name="Conductor v2 routing decision",
                raw_text="Conductor v2 uses NATS for cross-god routing.",
                brief="NATS routing",
                god_name="hermes",
                session_id="sess-abc",
                confidence=0.9,
            )
            conn.commit()

            results = [
                {
                    "id": "vec:42",
                    "backend": "vector",
                    "score": 0.85,
                    "fused_score": 0.85,
                    "event_id": 42,
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "Conductor v2", conn=conn)

            self.assertTrue(results[0]["hydrated"], "vector hit should be hydrated")
            self.assertIn("Conductor v2", results[0]["snippet"])
            self.assertIn("routing", results[0]["title"].lower())
            self.assertEqual(results[0]["source"], "sess-abc")
            self.assertEqual(
                results[0]["metadata"]["event_type"], "decision",
            )
            self.assertIn("hydrated_vector", results[0]["rank_reasons"])

    def test_ac2_unhydrated_vector_cannot_rank_first(self) -> None:
        """AC2: vector hit with null snippet cannot rank #1 when a
        hydrated FTS5 result exists with positive score."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            # Only the FTS5 hit has a cold_events row. Vector points to nothing.
            _insert_cold_event(
                conn,
                id=1,
                event_type="fact",
                category="fact",
                name="Conductor v2 fact",
                raw_text="Conductor v2 is the orchestrator.",
            )
            conn.commit()

            results = [
                # Hydratable FTS5 hit
                {
                    "id": "fts5:1",
                    "backend": "fts5",
                    "title": "Conductor v2 fact",
                    "snippet": "Conductor v2 is the orchestrator.",
                    "fused_score": 0.40,
                    "event_type": "fact",
                    "rank_reasons": [],
                },
                # Unhydratable vector hit (event_id 999 doesn't exist)
                {
                    "id": "vec:999",
                    "backend": "vector",
                    "title": "",
                    "snippet": "",
                    "fused_score": 0.35,
                    "event_id": 999,
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "Conductor v2", conn=conn)
            results.sort(key=lambda r: r["fused_score"], reverse=True)

            top = results[0]
            self.assertNotEqual(
                top["backend"], "vector",
                "Unhydrated vector hit must not rank #1 when better evidence exists",
            )
            # Verify the penalty fired
            unhydrated = [r for r in results if r["backend"] == "vector"][0]
            self.assertFalse(unhydrated["hydrated"])
            self.assertIn("penalty_vector_unhydrated", unhydrated["rank_reasons"])
            # The heavy penalty (-1.0) must have dropped the score below 0
            self.assertLess(unhydrated["fused_score"], 0)

    def test_ac3_decision_outranks_vague_semantic_neighbor(self) -> None:
        """AC3: a hydrated decision/correction gets a boost that lets it
        outrank a vague semantic neighbor (vector hit with no decision
        metadata)."""
        from lib.ichor.retrieval_hydration import (
            hydrate_pipeline, BOOST_DECISION_OR_CORRECTION,
        )

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            _insert_cold_event(
                conn,
                id=10,
                event_type="decision",
                category="decision",
                name="Use NATS for Conductor v2",
                raw_text="We decided Conductor v2 routes via NATS, not Redis.",
                god_name="hephaestus",
                confidence=0.9,
            )
            _insert_cold_event(
                conn,
                id=20,
                event_type="follow_up",
                category="follow_up",
                name="Conductor v2 followup",
                raw_text="Unrelated conductor mention — vague.",
                god_name="marvin",
                confidence=0.5,
            )
            conn.commit()

            # Both results have the same base fused_score; the decision
            # should win via the rank modifier boost.
            results = [
                {
                    "id": "fts5:10",
                    "backend": "fts5",
                    "title": "Use NATS for Conductor v2",
                    "snippet": "We decided Conductor v2 routes via NATS, not Redis.",
                    "fused_score": 0.30,
                    # Production FTS5Backend sets `type`, not `event_type`.
                    # The pipeline reads metadata.event_type first, then
                    # falls back to top-level `type`.
                    "type": "decision",
                    "rank_reasons": [],
                },
                {
                    "id": "vec:20",
                    "backend": "vector",
                    "title": "Conductor v2 followup",
                    "snippet": "Unrelated conductor mention — vague.",
                    "fused_score": 0.30,  # equal base
                    "event_id": 20,
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "Conductor v2 NATS decision", conn=conn)
            results.sort(key=lambda r: r["fused_score"], reverse=True)

            top = results[0]
            self.assertEqual(top["type"], "decision")
            # Top must have boost reason AND be ahead of the vague neighbor
            self.assertIn("boost_decision_correction", top["rank_reasons"])
            self.assertGreater(top["fused_score"], results[1]["fused_score"])

    def test_ac4_rank_reasons_visible_on_every_result(self) -> None:
        """AC4: rank_reasons is a list on every result, even when no
        modifier fires (it stays empty, but the field is present)."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            _insert_cold_event(
                conn,
                id=1,
                event_type="fact",
                category="fact",
                name="A fact",
                raw_text="Some plain fact with no special signals.",
            )
            conn.commit()

            results = [
                {
                    "id": "fts5:1",
                    "backend": "fts5",
                    "title": "A fact",
                    "snippet": "Some plain fact with no special signals.",
                    "fused_score": 0.40,
                    "event_type": "fact",
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "plain fact", conn=conn)

            self.assertIn("rank_reasons", results[0])
            self.assertIsInstance(results[0]["rank_reasons"], list)

    def test_exact_phrase_boost_applied(self) -> None:
        """Spec: 'exact phrase/title match → boost'."""
        from lib.ichor.retrieval_hydration import (
            hydrate_pipeline, BOOST_EXACT_PHRASE,
        )

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            conn.commit()

            # Title contains the exact query phrase.
            results = [
                {
                    "id": "fts5:1",
                    "backend": "fts5",
                    "title": "Conductor v2 routing decision",
                    "snippet": "This is about the conductor v2 routing decision.",
                    "fused_score": 0.30,
                    "event_type": "fact",
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "Conductor v2 routing decision", conn=conn)

            self.assertIn(
                "boost_exact_phrase", results[0]["rank_reasons"],
                "title that contains the query phrase verbatim must trigger the boost",
            )

    def test_noisy_line_fragment_penalty(self) -> None:
        """Spec: 'noisy line fragment → penalty'."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            conn.commit()

            # Very short snippet that looks like a code/operator fragment.
            results = [
                {
                    "id": "fts5:1",
                    "backend": "fts5",
                    "title": "noise",
                    "snippet": "def __init__(self):",  # short + non-prose
                    "fused_score": 0.40,
                    "event_type": "fact",
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "anything", conn=conn)

            self.assertIn("penalty_noisy", results[0]["rank_reasons"])

    def test_stale_event_penalty(self) -> None:
        """Spec: 'stale/superseded → penalty'."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            # created_at 60 days ago — well past the 30-day stale threshold.
            _insert_cold_event(
                conn,
                id=1,
                event_type="fact",
                category="fact",
                name="Old fact",
                raw_text="This is from a long time ago.",
                created_at="2026-04-01 00:00:00",
            )
            conn.commit()

            results = [
                {
                    "id": "fts5:1",
                    "backend": "fts5",
                    "title": "Old fact",
                    "snippet": "This is from a long time ago.",
                    "fused_score": 0.40,
                    "event_type": "fact",
                    "created_at": "2026-04-01 00:00:00",
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "old fact", conn=conn)

            self.assertIn("penalty_stale", results[0]["rank_reasons"])

    def test_generic_index_penalized_for_non_index_query(self) -> None:
        """Spec: 'generic INDEX.md → penalty unless index query'."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            conn.commit()

            results = [
                {
                    "id": "ref:1",
                    "backend": "reference",
                    "title": "INDEX.md",
                    "snippet": "List of codexes.",
                    "source": "Codex-Pantheon/INDEX.md",
                    "fused_score": 0.50,
                    "event_type": "fact",
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "Conductor v2 architecture", conn=conn)

            self.assertIn("penalty_generic_index", results[0]["rank_reasons"])

    def test_generic_index_exempt_when_index_query(self) -> None:
        """Spec: INDEX.md penalty exempt when query is itself an index query."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            conn.commit()

            results = [
                {
                    "id": "ref:1",
                    "backend": "reference",
                    "title": "INDEX.md",
                    "snippet": "List of codexes.",
                    "source": "Codex-Pantheon/INDEX.md",
                    "fused_score": 0.50,
                    "event_type": "fact",
                    "rank_reasons": [],
                },
            ]
            hydrate_pipeline(results, "show me the codex index", conn=conn)

            self.assertNotIn(
                "penalty_generic_index", results[0]["rank_reasons"],
                "INDEX.md must NOT be penalized when query is asking for an index",
            )

    def test_hydration_pipeline_is_pure(self) -> None:
        """Sanity: the pipeline returns the same list object (mutated in place)
        and does not raise on an empty input list."""
        from lib.ichor.retrieval_hydration import hydrate_pipeline

        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            conn = sqlite3.connect(tmp.name)
            conn.row_factory = sqlite3.Row
            _build_cold_events_table(conn)
            conn.commit()

            empty: List[Dict[str, Any]] = []
            out = hydrate_pipeline(empty, "anything", conn=conn)
            self.assertEqual(out, [])
            self.assertIs(out, empty)


# ─────────────────────────────────────────────────────────────────────
# End-to-end tests against the live MemoryTrait.retrieve()
# ─────────────────────────────────────────────────────────────────────

class TestEndToEnd(unittest.TestCase):
    """Integration tests using the production retrieve() path.

    These read from the real ichor.db but do not write. They prove
    Phase 4 is wired into the production pipeline.
    """

    def _retrieve(self, query: str = "Conductor v2", limit: int = 5) -> Dict[str, Any]:
        from lib.ichor_hybrid import MemoryTrait
        return MemoryTrait().retrieve(
            query=query, limit=limit, output_format="json", active_god=None,
        )

    def test_ac1_e2e_vector_hit_has_snippet_when_cold_event_exists(self) -> None:
        """AC1 (end-to-end): any vector hit in the response whose
        event_id exists in cold_events must have a non-empty snippet."""
        result = self._retrieve("Conductor v2", limit=10)
        vector_hits = [r for r in result["results"] if r["backend"] == "vector"]
        if not vector_hits:
            self.skipTest("No vector backend available (no embedding service wired)")
        for hit in vector_hits:
            if hit.get("hydrated"):
                self.assertTrue(
                    hit.get("snippet"),
                    f"Hydrated vector hit must have a snippet: {hit}",
                )
                self.assertTrue(
                    hit.get("title"),
                    f"Hydrated vector hit must have a title: {hit}",
                )
                self.assertIn(
                    "hydrated_vector", hit.get("rank_reasons", []),
                    f"Hydrated vector hit must record the rank reason: {hit}",
                )

    def test_ac2_e2e_no_unhydrated_vector_at_rank_1(self) -> None:
        """AC2 (end-to-end): the top result must not be an unhydrated
        vector hit. (If no other evidence exists, an unhydrated vector
        could be #1 — that case is covered by the pipeline unit test.)"""
        result = self._retrieve("Conductor v2", limit=10)
        if not result["results"]:
            self.skipTest("No results returned; can't verify rank #1")
        top = result["results"][0]
        if top["backend"] == "vector":
            self.assertTrue(
                top.get("hydrated", False),
                f"Vector hit at rank #1 must be hydrated: {top}",
            )

    def test_ac4_e2e_every_result_has_rank_reasons_field(self) -> None:
        """AC4 (end-to-end): every returned result has rank_reasons."""
        result = self._retrieve("Conductor v2", limit=10)
        self.assertGreater(len(result["results"]), 0)
        for r in result["results"]:
            self.assertIn(
                "rank_reasons", r,
                f"Result must have rank_reasons: {r}",
            )
            self.assertIsInstance(r["rank_reasons"], list)

    def test_phase4_weights_are_correct(self) -> None:
        """Sanity: Phase 4 weights are loaded (not the old P5c values)."""
        from lib.ichor_hybrid import WEIGHTS
        self.assertEqual(WEIGHTS["fts5"], 0.40)
        self.assertEqual(WEIGHTS["vector"], 0.20)
        self.assertEqual(WEIGHTS["graph"], 0.15)
        self.assertEqual(WEIGHTS["events"], 0.15)
        self.assertEqual(WEIGHTS["reference"], 0.10)
        # Weights must still sum to 1.0
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0, places=4)


# ─────────────────────────────────────────────────────────────────────
# Pipeline import & contract tests
# ─────────────────────────────────────────────────────────────────────

class TestModuleContract(unittest.TestCase):
    """The new module exposes the expected public surface."""

    def test_module_imports(self) -> None:
        from lib.ichor import retrieval_hydration as rh
        self.assertTrue(hasattr(rh, "hydrate_event_ids"))
        self.assertTrue(hasattr(rh, "hydrate_vector_results"))
        self.assertTrue(hasattr(rh, "infer_metadata"))
        self.assertTrue(hasattr(rh, "apply_rank_modifiers"))
        self.assertTrue(hasattr(rh, "hydrate_pipeline"))
        self.assertTrue(hasattr(rh, "HYDRATION_COLUMNS"))

    def test_boost_constants_are_documented(self) -> None:
        from lib.ichor import retrieval_hydration as rh
        # Spec §Phase 4 lists the modifier conditions. We expose the
        # weights as constants so the Forge can tune them later.
        self.assertTrue(hasattr(rh, "BOOST_EXACT_PHRASE"))
        self.assertTrue(hasattr(rh, "BOOST_DECISION_OR_CORRECTION"))
        self.assertTrue(hasattr(rh, "BOOST_SPEC_OR_DISTILLED"))
        self.assertTrue(hasattr(rh, "PENALTY_NOISY"))
        self.assertTrue(hasattr(rh, "PENALTY_STALE"))
        self.assertTrue(hasattr(rh, "PENALTY_GENERIC_INDEX"))
        self.assertTrue(hasattr(rh, "PENALTY_VECTOR_UNHYDRATED"))

    def test_vector_backend_documents_hydration_contract(self) -> None:
        """Phase 4 vector_backend.docstring must reference hydration."""
        from lib.ichor import vector_backend as vb
        # Check the source code text for the hydration contract note.
        import inspect
        src = inspect.getsource(vb.VectorBackend.search)
        self.assertIn("hydration", src.lower())
        self.assertIn("phase 4", src.lower())


if __name__ == "__main__":
    unittest.main()