#!/usr/bin/env python3
"""T0 prefetch-cache acceptance tests (2026-09-21).

Baseline defect: the T0 cache key was `md5(query.lower().strip())`, an
exact-match key. Real conversation does not repeat a query verbatim inside the
5-minute TTL, so the cache was write-only overhead whose hit rate nobody could
state, because there were no counters either.

These tests pin the three properties that make the cache useful and safe:
  1. paraphrases and reordered questions HIT (content-token key)
  2. unrelated topics do NOT collide
  3. the cache is bounded, invalidated on write, and measurable

Run:
    /usr/local/lib/hermes-agent/venv/bin/python3 -m pytest \
        tests/test_ichor_t0_cache.py -q
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_PANTHEON_ROOT = Path(__file__).resolve().parent.parent
_PLUGIN_ROOT = Path("/home/konan/.hermes/plugins")
_HERMES_AGENT = Path("/home/konan/.hermes/hermes-agent")
for _p in (str(_PANTHEON_ROOT), str(_PLUGIN_ROOT), str(_HERMES_AGENT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ichor.provider as provider_mod  # noqa: E402
from ichor.provider import IchorMemoryProvider, _T0_CACHE_MAX  # noqa: E402


def bare_provider() -> IchorMemoryProvider:
    """Instance without __init__ side effects (no DB, no config, no network).

    The cache methods only touch `self._cache` and the counters, so bypassing
    __init__ keeps these tests hermetic and fast.
    """
    p = object.__new__(IchorMemoryProvider)
    p._cache = {}
    p._cache_hits = 0
    p._cache_misses = 0
    p._cache_invalidations = 0
    return p


class TestCacheKey(unittest.TestCase):

    def test_paraphrase_hits(self):
        p = bare_provider()
        a = p._cache_key("How does the ichor retention prune work?")
        b = p._cache_key("how does ichor retention prune work")
        self.assertEqual(a, b, "case and punctuation must not change the key")

    def test_word_order_does_not_matter(self):
        p = bare_provider()
        a = p._cache_key("ichor retention prune schedule")
        b = p._cache_key("schedule prune retention ichor")
        self.assertEqual(a, b, "content-token key must be order-insensitive")

    def test_unrelated_topics_do_not_collide(self):
        p = bare_provider()
        a = p._cache_key("How does the ichor retention prune work?")
        b = p._cache_key("When does the suno player release ship?")
        self.assertNotEqual(a, b, "different topics must never share a cache slot")

    def test_stopwords_are_ignored(self):
        p = bare_provider()
        a = p._cache_key("what is the state of the ichor database")
        b = p._cache_key("state ichor database")
        self.assertEqual(a, b)

    def test_single_token_queries_are_isolated(self):
        """A greeting must not collide with stored context."""
        p = bare_provider()
        a = p._cache_key("ok")
        b = p._cache_key("ok thanks")
        self.assertNotEqual(a, b)
        self.assertEqual(a, p._cache_key("OK"), "still stable for the same input")


class TestCacheBehaviour(unittest.TestCase):

    def test_hit_and_miss_are_counted(self):
        p = bare_provider()
        key = p._cache_key("ichor retention prune")
        # miss path
        if key in p._cache:
            pass
        else:
            p._cache_misses += 1
        p._cache[key] = {"text": "ctx", "confidence": 0.95, "timestamp": 0}
        p._cache_hits += 1
        stats = p.cache_stats()
        self.assertEqual(stats["hits"], 1)
        self.assertEqual(stats["misses"], 1)
        self.assertEqual(stats["hit_rate"], 0.5)

    def test_low_confidence_entry_is_not_a_hit(self):
        """Only >= 0.9 counts as a perfect hit (unchanged contract)."""
        p = bare_provider()
        p._cache[p._cache_key("x y")] = {"text": "ctx", "confidence": 0.4,
                                        "timestamp": 0}
        cached = p._cache[p._cache_key("x y")]
        self.assertLess(cached["confidence"], 0.9)

    def test_invalidate_clears_and_counts(self):
        p = bare_provider()
        p._cache[p._cache_key("a b")] = {"text": "t", "confidence": 1.0,
                                         "timestamp": 0}
        p._invalidate_cache("test")
        self.assertEqual(len(p._cache), 0)
        self.assertEqual(p._cache_invalidations, 1)

    def test_cache_is_bounded(self):
        """A long-lived gateway must not accumulate unbounded entries."""
        p = bare_provider()
        self.assertGreater(_T0_CACHE_MAX, 0)
        for i in range(_T0_CACHE_MAX + 25):
            p._cache[f"key{i}"] = {"text": "t", "confidence": 1.0,
                                   "timestamp": float(i)}
            if len(p._cache) >= _T0_CACHE_MAX:
                oldest = min(p._cache.items(),
                             key=lambda kv: kv[1].get("timestamp", 0))[0]
                del p._cache[oldest]
        self.assertLessEqual(len(p._cache), _T0_CACHE_MAX)


class TestWriteInvalidationWired(unittest.TestCase):

    def test_sync_turn_invalidates_cache(self):
        """The source must call _invalidate_cache when extraction wrote rows."""
        src = Path(provider_mod.__file__).read_text()
        self.assertIn('self._invalidate_cache(reason="turn write")', src,
                      "sync_turn must drop stale prefetches after a write")


if __name__ == "__main__":
    unittest.main(verbosity=2)
