from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from lib.ichor_subconscious import _cluster_events, tick


class _FakeDB:
    def close(self) -> None:
        pass


class TestIchorSubconsciousClustering(unittest.TestCase):
    def _make_events(self, count: int = 10) -> list[dict[str, object]]:
        base = datetime.now(timezone.utc)
        events: list[dict[str, object]] = []
        for idx in range(count):
            events.append(
                {
                    "id": idx + 1,
                    "event_type": "insight",
                    "god_name": "hephaestus",
                    "subject": "Memory upgrade rollout",
                    "raw_text": "Memory upgrade rollout and reconciliation validation across the same subsystem.",
                    "confidence": 0.92,
                    "created_at": (base - timedelta(minutes=idx)).isoformat(),
                }
            )
        return events

    def test_cluster_events_groups_similar_events_into_one_topic(self) -> None:
        clusters = _cluster_events(self._make_events())
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["count"], 10)
        self.assertEqual(clusters[0]["summary"].startswith("Memory upgrade rollout"), True)

    def test_tick_emits_one_clustered_digest(self) -> None:
        events = self._make_events()
        captured: dict[str, str] = {}

        def _capture_deliver(god_name: str, report: str) -> bool:
            captured[god_name] = report
            return True

        with patch("lib.ichor_subconscious._get_db", return_value=_FakeDB()), \
             patch("lib.ichor_subconscious._discover_active_gods", return_value=["hephaestus"]), \
             patch("lib.ichor_subconscious._get_last_reported_id", return_value=0), \
             patch("lib.ichor_subconscious._query_actionable_events", return_value=events), \
             patch("lib.ichor_subconscious._deliver_to_inbox", side_effect=_capture_deliver), \
             patch("lib.ichor_subconscious._set_last_reported_id"):
            result = tick(dry_run=False)

        self.assertEqual(result["status"], "ok")
        self.assertIn("hephaestus", result["results"])
        self.assertTrue(result["results"]["hephaestus"]["delivered"])
        report = captured["hephaestus"]
        self.assertEqual(report.count("### 🧭 Topic"), 1)
        self.assertIn("10 events", report)
        self.assertIn("Member event ids", report)


if __name__ == "__main__":
    unittest.main()
