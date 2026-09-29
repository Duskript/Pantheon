"""Fix E acceptance tests — the OOD gate is non-terminal.

Handoff: ~/pantheon/shared/handoffs/ichor-relational-recall-fix/BRIEF.md (§Wave 3)

Fix E  prefetch() used to return empty context the moment T1 was empty or scored
       below 0.3, so T2/T3/T4 never ran in exactly the case they exist for.
       Because the gate is now non-terminal, T3 runs on turns where it never ran
       before, which forced two pieces of hardening:
         * `_resolve_entity_id` memo + fast indexed path (the full resolver costs
           ~85 ms on a MISS because it scans every entity's aliases JSON), and
         * the cross_god peer->peer filter applied on every path, not just the
           T1-only early exit.

Run:
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_fix_e_ood_gate.py
"""
from __future__ import annotations

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

from ichor.provider import IchorMemoryProvider  # noqa: E402

LIVE_DB = Path("/home/konan/.hermes/ichor.db")

PEER_MARKER = "PEER-ONLY-SECRET"


def _fts(score: float, direction: str = "unknown", title: str = "t1 hit") -> list:
    return [{
        "id": "fts5:1", "score": score, "backend": "fts5", "type": "fact",
        "title": title, "snippet": "snippet text", "direction": direction,
    }]


class TestOodGateIsNonTerminal(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def _prefetch(self, fts_results, query="How is my brother doing?", **kw):
        with mock.patch.object(self.provider, "_query_fts5",
                               side_effect=lambda q, limit=5: list(fts_results)), \
                mock.patch.object(self.provider, "_query_chroma", return_value=[]):
            return self.provider.prefetch(query, session_id="fixe", **kw)

    def test_empty_t1_still_reaches_the_graph_tier(self):
        """The headline Fix E behaviour: FTS5 misses, T3 still runs."""
        calls = []
        real = self.provider._query_graph

        def _spy(entities, depth=2):
            out = real(entities, depth=depth)
            calls.append((entities, len(out)))
            return out

        self.provider._query_graph = _spy
        ctx = self._prefetch([])
        self.assertTrue(calls, "T3 was never reached on an empty-T1 turn")
        self.assertTrue(calls[0][1], f"T3 returned nothing: {calls}")
        self.assertIn("memory-context", ctx)
        self.assertIn("--", ctx, f"no relational hit rendered:\n{ctx}")

    def test_low_t1_below_ood_threshold_reaches_the_graph_tier(self):
        calls = []
        real = self.provider._query_graph

        def _spy(entities, depth=2):
            out = real(entities, depth=depth)
            calls.append(len(out))
            return out

        self.provider._query_graph = _spy
        # 0.1 is below the old 0.3 OOD threshold — previously a hard return.
        ctx = self._prefetch(_fts(0.1))
        self.assertTrue(calls, "T3 was never reached with T1 below 0.3")
        self.assertIn("--", ctx)

    def test_definitive_t1_still_short_circuits(self):
        """A 0.8+ T1 hit must NOT pay for a graph walk.

        `_turn_counter` is pinned off the full-recall cadence on purpose:
        turn 0 satisfies `0 % full_recall == 0`, so the first turn of a fresh
        session is *by design* a full pass that runs every tier.  See
        `test_turn_zero_is_a_full_recall_pass`.
        """
        self.provider._turn_counter = 1  # 1 % 3 != 0 -> not a full pass
        calls = []
        self.provider._query_graph = lambda entities, depth=2: calls.append(entities) or []
        ctx = self._prefetch(_fts(0.95, title="exact recall"))
        self.assertFalse(calls, "strong T1 paid for a T3 walk it did not need")
        self.assertIn("exact recall", ctx)

    def test_turn_zero_is_a_full_recall_pass(self):
        """Documented cadence behaviour: the first turn runs every tier."""
        self.provider._turn_counter = 0
        calls = []
        self.provider._query_graph = lambda entities, depth=2: calls.append(entities) or []
        self._prefetch(_fts(0.95, title="exact recall"))
        self.assertTrue(calls, "turn 0 should be a full-recall pass")

    def test_truly_empty_turn_returns_empty_context(self):
        """No tiers produced anything => inject nothing."""
        self.provider._query_graph = lambda entities, depth=2: []
        ctx = self._prefetch([], query="Zzzznotathing qqqq wwww")
        self.assertEqual(ctx, "")


class TestPeerToPeerPrivacyOnEveryPath(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def _run(self, cross_god: bool) -> str:
        fts = _fts(0.1, direction="peer\u2192peer", title=PEER_MARKER)
        with mock.patch.object(self.provider, "_query_fts5",
                               side_effect=lambda q, limit=5: list(fts)), \
                mock.patch.object(self.provider, "_query_chroma", return_value=[]):
            return self.provider.prefetch(
                "How is my brother doing?", session_id=f"peer-{cross_god}",
                cross_god=cross_god,
            )

    def test_peer_peer_is_filtered_on_a_weak_t1_turn(self):
        ctx = self._run(cross_god=False)
        self.assertNotIn(PEER_MARKER, ctx,
                         "peer\u2192peer leaked through the weak-T1 path")

    def test_peer_peer_is_included_when_cross_god_is_requested(self):
        ctx = self._run(cross_god=True)
        self.assertIn(PEER_MARKER, ctx,
                      "cross_god=True must keep peer\u2192peer observations")


@unittest.skipUnless(LIVE_DB.is_file(), "live ichor.db not present")
class TestResolveEntityIdFastPath(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = IchorMemoryProvider()

    def test_alias_resolves_through_the_index_table(self):
        self.assertEqual(self.provider._resolve_entity_id("Cybermage"), 614)
        self.assertEqual(self.provider._resolve_entity_id("KONAN"), 614)
        self.assertEqual(self.provider._resolve_entity_id("Tallon"), 878)

    def test_misses_are_memoized(self):
        """A miss is the expensive case — it must not be recomputed."""
        with mock.patch(
            "lib.ichor.entities.entity_resolve.resolve", return_value=None
        ) as slow:
            self.assertIsNone(self.provider._resolve_entity_id("Zzzznotathing"))
            self.assertIsNone(self.provider._resolve_entity_id("Zzzznotathing"))
            self.assertIsNone(self.provider._resolve_entity_id("ZZZZNOTATHING"))
        self.assertEqual(slow.call_count, 1,
                         "miss was recomputed instead of served from the memo")

    def test_hits_never_touch_the_slow_resolver(self):
        with mock.patch(
            "lib.ichor.entities.entity_resolve.resolve", return_value=None
        ) as slow:
            self.assertEqual(self.provider._resolve_entity_id("Cybermage"), 614)
        self.assertEqual(slow.call_count, 0,
                         "indexed alias hit fell through to the O(N) resolver")

    def test_merged_row_hops_to_its_survivor(self):
        # entity 785 'Konan' is status='merged', merged_into=614.
        self.assertEqual(self.provider._resolve_entity_id("Konan Ross Rudolph I"), 614)

    def test_blank_input_is_safe(self):
        self.assertIsNone(self.provider._resolve_entity_id(""))
        self.assertIsNone(self.provider._resolve_entity_id(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
