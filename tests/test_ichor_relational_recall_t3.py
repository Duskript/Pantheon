"""Fix A / Fix C acceptance tests — Ichor relational recall.

Handoff: ~/pantheon/shared/handoffs/ichor-relational-recall-fix/BRIEF.md
Diagnosis: ~/athenaeum/Codex-God-thoth/research/ichor-relational-recall/report.md

Fix A  provider.py::_query_graph was a hardcoded `return []` no-op shim, so
       prefetch()'s T3 tier never ran and the relational half of the retriever
       was structurally absent.  Now wired to
       lib/ichor/entities/traversal.py::graph_query_by_id.
       Also: _extract_named_entities() dropped every capitalised token while
       its candidate list was still empty, so a typical short message produced
       zero entities and T3 never even got a query.
Fix C  entity_aliases had 0 rows; Konan existed as 6+ unmerged person rows and
       token-similarity merging can never join "Cybermage" to "Konan".

Run with the hermes venv:
    ~/.hermes/hermes-agent/.venv/bin/python3 -m pytest \\
        tests/test_ichor_relational_recall_t3.py -v
"""
from __future__ import annotations

import os
import sys
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

LIVE_DB = Path("/home/konan/.hermes/ichor.db")
CANONICAL_KONAN_ID = 614


def _fake_subgraph(start_id: int = CANONICAL_KONAN_ID) -> dict:
    return {
        "nodes": [
            {"id": start_id, "name": "konan", "type": "person",
             "summary": "", "provisional": 0},
            {"id": 4450, "name": "Fia", "type": "person",
             "summary": "Girlfriend/partner.", "provisional": 0},
        ],
        "edges": [
            {"source": start_id, "target": 4450, "type": "knows",
             "confidence": 0.7, "provisional": False},
        ],
        "stats": {"node_count": 2, "edge_count": 1},
    }


class TestT3GraphTierWiring(unittest.TestCase):
    """Fix A — T3 must call the real traversal and return the mapped shape."""

    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def test_query_graph_invokes_traversal_and_maps_all_results_shape(self):
        with mock.patch(
            "lib.ichor.entities.entity_resolve.resolve", return_value=CANONICAL_KONAN_ID
        ), mock.patch(
            "lib.ichor.entities.traversal.graph_query_by_id",
            return_value=_fake_subgraph(),
        ) as gq:
            results = self.provider._query_graph(["konan"], depth=2)

        # the tier actually called the traversal, anchored on the canonical id
        self.assertTrue(gq.called, "_query_graph did not call graph_query_by_id")
        self.assertEqual(gq.call_args.args[1], CANONICAL_KONAN_ID)
        self.assertEqual(gq.call_args.kwargs["depth"], 2)

        # and returned entries in the shape all_results / T4 already consume
        self.assertEqual(len(results), 1)
        hit = results[0]
        for key in ("id", "score", "backend", "type", "title", "snippet"):
            self.assertIn(key, hit)
        self.assertEqual(hit["backend"], "graph")
        self.assertTrue(hit["id"].startswith("graph:"))
        self.assertEqual(hit["score"], 0.7)
        self.assertIn("knows", hit["title"])
        self.assertIn("Fia", hit["title"])

    def test_query_graph_anchors_an_alias_on_the_canonical_entity(self):
        """'Cybermage' must walk from Konan's node, not a fragment."""
        seen = {}

        def _spy(conn, entity_id, **kwargs):
            seen["entity_id"] = entity_id
            return _fake_subgraph(entity_id)

        with mock.patch(
            "lib.ichor.entities.entity_resolve.resolve", return_value=CANONICAL_KONAN_ID
        ), mock.patch(
            "lib.ichor.entities.traversal.graph_query_by_id", side_effect=_spy
        ):
            results = self.provider._query_graph(["Cybermage"], depth=2)

        self.assertEqual(seen.get("entity_id"), CANONICAL_KONAN_ID)
        self.assertTrue(results, "alias query produced no graph results")

    def test_query_graph_is_empty_and_silent_when_nothing_resolves(self):
        with mock.patch(
            "lib.ichor.entities.entity_resolve.resolve", return_value=None
        ), mock.patch(
            "lib.ichor.entities.traversal.graph_query_by_id"
        ) as gq:
            self.assertEqual(self.provider._query_graph(["Zzzznotathing"], depth=2), [])
        self.assertFalse(gq.called)

    def test_query_graph_with_no_entities_short_circuits(self):
        self.assertEqual(self.provider._query_graph([], depth=2), [])

    def test_chroma_tier_is_left_as_a_no_op(self):
        """Guardrail: do NOT rebuild the vector tier without confirming intent."""
        self.assertEqual(self.provider._query_chroma("anything", limit=5), [])


class TestEntityExtraction(unittest.TestCase):
    """Fix A — _extract_named_entities must stop discarding capitalised words."""

    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def test_sentence_initial_proper_noun_is_extracted(self):
        out = self.provider._extract_named_entities("Konan is building TheoForge")
        self.assertIn("Konan", out, f"'Konan' was dropped: {out}")

    def test_short_capitalised_message_yields_entities(self):
        # The pre-fix guard tested len(candidates) == 0, so a query whose first
        # capitalised token appeared before any candidate consumed every token
        # and returned [].  Regression guard for exactly that.
        out = self.provider._extract_named_entities("What about Fia and Tallon?")
        joined = {e.lower() for e in out}
        self.assertIn("fia", joined)
        self.assertIn("tallon", joined)

    def test_possessive_suffix_is_stripped(self):
        out = self.provider._extract_named_entities("Konan's brother called today")
        self.assertIn("Konan", out)

    def test_relation_phrase_resolves_through_person_roots(self):
        out = self.provider._extract_named_entities("How is my brother doing?")
        self.assertIn("tallon", out, f"relation phrase unresolved: {out}")

    def test_konan_possessive_relation_resolves(self):
        out = self.provider._extract_named_entities("Konan's brother is in town")
        self.assertIn("tallon", out)

    def test_multiword_name_is_captured_as_a_phrase(self):
        out = self.provider._extract_named_entities("Ask Konan Ross Rudolph about it")
        self.assertTrue(
            any(" " in e for e in out),
            f"no multi-word phrase extracted: {out}",
        )

    def test_relation_table_ignores_the_what_konan_has_said_section(self):
        # "Fia is Sammy's mother" lives under '## What Konan has said'.  Scanning
        # the whole document would map 'mother' -> fia, which is wrong.
        out = self.provider._extract_named_entities("my mother called")
        self.assertNotIn("fia", out, f"'mother' leaked to fia: {out}")

    def test_sentence_initial_interrogatives_are_not_entities(self):
        """'What'/'How'/'Who' are capitalised but are not anchors."""
        junk = {"what", "how", "who", "when", "where", "why", "tell", "which"}
        for question in (
            "What is my relationship to Fia?",
            "How is my brother doing?",
            "Who does konan work with?",
            "Tell me about Amber.",
        ):
            out = {e.lower() for e in self.provider._extract_named_entities(question)}
            leaked = out & junk
            self.assertFalse(leaked, f"{question!r} leaked {leaked}")


@unittest.skipUnless(LIVE_DB.is_file(), "live ichor.db not present")
class TestLiveDatabase(unittest.TestCase):
    """Integration against the real graph — read-only."""

    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def test_relationship_query_returns_non_empty_t3_results(self):
        entities = self.provider._extract_named_entities(
            "Who is Fia to Konan and how does konan relate to Tallon?"
        )
        self.assertTrue(entities, "extraction produced nothing to anchor on")
        results = self.provider._query_graph(entities, depth=2)
        self.assertTrue(results, f"T3 returned nothing for {entities}")
        for r in results:
            self.assertEqual(r["backend"], "graph")
            self.assertTrue(r["title"])
        titles = [r["title"] for r in results]
        self.assertTrue(
            any("--" in t for t in titles),
            f"no relation trails in titles: {titles}",
        )

    def test_dense_hub_query_stays_within_budget(self):
        import time

        start = time.monotonic()
        results = self.provider._query_graph(["konan"], depth=2)
        elapsed = time.monotonic() - start
        self.assertTrue(results)
        self.assertLess(
            elapsed, 5.0,
            f"T3 on a 1,000+-edge hub took {elapsed:.2f}s — hot-path budget blown",
        )


class TestPrefetchComposition(unittest.TestCase):
    """Fix A — T3 must contribute to all_results on a turn where T1 is weak."""

    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def _low_confidence_fts5(self, query, limit=5):
        # 0.4 clears the 0.3 OOD gate but is below the 0.6 T2/T3 threshold,
        # which is exactly the band where the graph tier is supposed to help.
        return [{
            "id": "fts5:1",
            "score": 0.4,
            "backend": "fts5",
            "type": "fact",
            "title": "weak keyword hit",
            "snippet": "something tangential",
            "direction": "unknown",
        }]

    def test_prefetch_includes_graph_results_when_t1_is_weak(self):
        captured = {}
        real_query_graph = self.provider._query_graph

        def _spy(entities, depth=2):
            out = real_query_graph(entities, depth=depth)
            captured["entities"] = entities
            captured["t3_count"] = len(out)
            return out

        with mock.patch.object(self.provider, "_query_fts5",
                               side_effect=self._low_confidence_fts5), \
                mock.patch.object(self.provider, "_query_chroma", return_value=[]), \
                mock.patch.object(self.provider, "_query_graph", side_effect=_spy):
            ctx = self.provider.prefetch("What is my relationship to Fia?", session_id="t")

        self.assertTrue(captured, "prefetch never reached the T3 tier")
        self.assertGreater(
            captured["t3_count"], 0,
            f"T3 returned nothing for entities {captured.get('entities')}",
        )
        # The provider deliberately does NOT self-wrap in <memory-context>: Hermes'
        # memory_manager strips a <memory-context> span *including its interior*
        # (agent/memory_manager.py) and re-fences what survives, so a self-wrapped
        # payload arrived empty (measured 2026-09-20: 919 chars in, 0 out). The
        # tier's contract is "graph rows reach the returned text" — the fence
        # belongs to Hermes, so asserting the provider supplies it is stale.
        self.assertNotIn("<memory-context>", ctx)
        self.assertIn("--", ctx, f"no relational hit rendered into context:\n{ctx}")

    def test_prefetch_graph_contribution_is_the_delta_fix_a_creates(self):
        """Before/after in one process: shim vs wired."""
        with mock.patch.object(self.provider, "_query_fts5",
                               side_effect=self._low_confidence_fts5), \
                mock.patch.object(self.provider, "_query_chroma", return_value=[]):
            # BEFORE — the P4b shim.  `new=` (not side_effect=) so the lambda is
            # a descriptor and gets bound as a method with `self` injected.
            with mock.patch.object(type(self.provider), "_query_graph",
                                   new=lambda self, entities, depth=2: []):
                before = self.provider.prefetch("my brother Tallon", session_id="a")
            # AFTER — the wired tier
            self.provider._cache.clear()
            after = self.provider.prefetch("my brother Tallon", session_id="b")

        self.assertNotEqual(before, after)
        self.assertIn("--", after)
        self.assertNotIn("--", before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
