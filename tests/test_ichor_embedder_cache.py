#!/usr/bin/env python3
"""Query-embedding cache — memoisation, LRU bound, telemetry.

Why: the vector lane embeds the query text on every retrieval, and both a
follow-up turn and the weight tuner (one query set scored under a dozen weight
configurations) re-embed the same strings. A CPU embedding is 40-120 ms of pure
repeat work. These tests pin the cache behaviour and its bound so a long-lived
gateway process cannot grow it without limit.

Run with the hermes venv:
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_embedder_cache.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

PANTHEON = Path("/home/konan/pantheon")
if str(PANTHEON) not in sys.path:
    sys.path.insert(0, str(PANTHEON))

from lib.ichor import embedder  # noqa: E402


class EmbedderCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        embedder.query_cache_clear()
        self.calls = []

        def fake_embed(texts, **kwargs):
            self.calls.append(list(texts))
            return [[0.1, 0.2, 0.3] for _ in texts]

        self._patch = mock.patch.object(embedder, "embed", side_effect=fake_embed)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        embedder.query_cache_clear()

    def test_second_identical_query_is_served_from_cache(self):
        a = embedder.embed_one("konan memory system")
        b = embedder.embed_one("konan memory system")
        self.assertEqual(a, b)
        self.assertEqual(len(self.calls), 1, "duplicate embedding work performed")
        self.assertEqual(embedder.query_cache_stats()["hits"], 1)

    def test_whitespace_variants_share_one_entry(self):
        embedder.embed_one("konan memory system")
        embedder.embed_one("  konan memory system  ")
        self.assertEqual(len(self.calls), 1, "whitespace broke memoisation")

    def test_different_queries_are_embedded_separately(self):
        embedder.embed_one("alpha query")
        embedder.embed_one("beta query")
        self.assertEqual(len(self.calls), 2)

    def test_use_cache_false_bypasses_and_does_not_populate(self):
        embedder.embed_one("gamma query", use_cache=False)
        embedder.embed_one("gamma query", use_cache=False)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(embedder.query_cache_stats()["entries"], 0)

    def test_empty_and_blank_return_none_without_embedding(self):
        self.assertIsNone(embedder.embed_one(""))
        self.assertIsNone(embedder.embed_one("   "))
        self.assertEqual(self.calls, [])

    def test_cache_is_bounded_and_evicts_oldest(self):
        with mock.patch.object(embedder, "_QUERY_CACHE_MAX", 2):
            embedder.embed_one("q1")
            embedder.embed_one("q2")
            embedder.embed_one("q3")
            stats = embedder.query_cache_stats()
            self.assertEqual(stats["entries"], 2, "cache exceeded its bound")
            calls_before = len(self.calls)
            embedder.embed_one("q1")
            self.assertEqual(len(self.calls), calls_before + 1)

    def test_returned_vector_is_a_copy_not_the_cache_internals(self):
        first = embedder.embed_one("mutation test")
        first.append(99.0)
        second = embedder.embed_one("mutation test")
        self.assertNotIn(99.0, second, "caller mutated the cached vector")

    def test_clear_resets_entries_and_counters(self):
        embedder.embed_one("reset me")
        embedder.query_cache_clear()
        stats = embedder.query_cache_stats()
        self.assertEqual(stats, {"entries": 0, "max_entries": embedder._QUERY_CACHE_MAX,
                                 "hits": 0, "misses": 0})

    def test_embed_failure_is_not_cached(self):
        with mock.patch.object(embedder, "embed", return_value=[]):
            self.assertIsNone(embedder.embed_one("failing query"))
        self.assertEqual(embedder.query_cache_stats()["entries"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
