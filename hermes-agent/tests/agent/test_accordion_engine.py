from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.context_compressor import SUMMARY_PREFIX
from plugins.context_engine import discover_context_engines, load_context_engine


def _make_messages(turns: int) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": "system prompt"}]
    for turn in range(1, turns + 1):
        messages.append({"role": "user", "content": f"user {turn}: discuss database schema"})
        messages.append({"role": "assistant", "content": f"assistant {turn}: reply {turn}"})
    return messages


class TestAccordionEngineDiscovery(unittest.TestCase):
    def test_discover_context_engines_lists_accordion_engine(self) -> None:
        names = {name for name, _desc, _available in discover_context_engines()}
        self.assertIn("accordion", names)

    def test_load_context_engine_returns_accordion_engine(self) -> None:
        engine = load_context_engine("accordion")
        self.assertIsNotNone(engine)
        self.assertEqual(engine.name, "accordion")


class TestAccordionEngineBehavior(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(dir="/home/konan")
        self.addCleanup(self._tmp.cleanup)
        self._env_patch = patch.dict("os.environ", {"HERMES_HOME": self._tmp.name}, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def test_folds_older_turns_and_keeps_tail(self) -> None:
        stored: dict[str, object] = {}

        from plugins.context_engine import accordion as accordion_mod

        def fake_fold(session_id, content, summary, token_count, fold_type="turn", parent_fold_id=None):
            stored.update(
                session_id=session_id,
                content=content,
                summary=summary,
                token_count=token_count,
                fold_type=fold_type,
                parent_fold_id=parent_fold_id,
            )
            return json.dumps({
                "stored": True,
                "fold": {
                    "id": 101,
                    "session_id": session_id,
                    "summary": summary,
                    "full_content": content,
                    "token_count": token_count,
                },
            })

        with patch.object(accordion_mod, "ichor_fold", fake_fold):
            from plugins.context_engine.accordion import AccordionEngine

            engine = AccordionEngine(config={"working_tail": 7, "threshold_percent": 0.75})
            engine.on_session_start("sess-accordion", hermes_home=self._tmp.name, model="gpt-5.4-mini")
            messages = _make_messages(10)

            result = engine.compress(messages, current_tokens=100_000, focus_topic="database schema")

        self.assertEqual(len(result), 1 + 1 + (7 * 2))
        self.assertEqual(result[0]["role"], "system")
        self.assertTrue(result[1]["content"].startswith(SUMMARY_PREFIX))
        self.assertEqual(result[-2]["content"], "user 10: discuss database schema")
        self.assertEqual(result[-1]["content"], "assistant 10: reply 10")
        self.assertEqual(stored["session_id"], "sess-accordion")
        self.assertEqual(stored["fold_type"], "turn")
        self.assertIn("user 1: discuss database schema", stored["content"])
        self.assertIn("assistant 3: reply 3", stored["content"])
        self.assertNotIn("user 10: discuss database schema", stored["content"])

    def test_expands_matching_fold(self) -> None:
        from plugins.context_engine import accordion as accordion_mod

        def fake_fold(session_id, content, summary, token_count, fold_type="turn", parent_fold_id=None):
            return json.dumps({
                "stored": True,
                "fold": {
                    "id": 17,
                    "session_id": session_id,
                    "summary": summary,
                    "full_content": content,
                    "token_count": token_count,
                },
            })

        stored_fold = {
            "id": 17,
            "session_id": "sess-accordion",
            "summary": "database schema decisions",
            "full_content": json.dumps(
                [
                    {"role": "user", "content": "user 1: discuss database schema"},
                    {"role": "assistant", "content": "assistant 1: use sqlite"},
                ]
            ),
            "token_count": 1200,
        }

        with patch.object(accordion_mod, "ichor_fold", fake_fold), patch.object(
            accordion_mod,
            "ichor_expand",
            lambda fold_id: json.dumps({"expanded": True, "fold": stored_fold | {"id": fold_id}}),
        ):
            from plugins.context_engine.accordion import AccordionEngine

            engine = AccordionEngine(config={"working_tail": 7})
            engine.on_session_start("sess-accordion", hermes_home=self._tmp.name, model="gpt-5.4-mini")
            messages = _make_messages(8)
            engine.compress(messages, current_tokens=100_000, focus_topic="database schema")

            result = engine.expand_for_message("can you remember the database schema decisions?")

        self.assertIsNotNone(result)
        self.assertEqual(result["fold_id"], 17)
        self.assertTrue(result["context"].startswith(SUMMARY_PREFIX))
        self.assertIn("use sqlite", result["context"])

    def test_has_content_to_compress_respects_working_tail(self) -> None:
        from plugins.context_engine.accordion import AccordionEngine

        engine = AccordionEngine(config={"working_tail": 7})
        self.assertFalse(engine.has_content_to_compress(_make_messages(7)))
        self.assertTrue(engine.has_content_to_compress(_make_messages(8)))

    def test_clusters_related_folds_and_separates_unrelated_topics(self) -> None:
        from plugins.context_engine.accordion import AccordionEngine, FoldRecord

        engine = AccordionEngine(config={"working_tail": 7})
        engine.on_session_start("sess-accordion", hermes_home=self._tmp.name, model="gpt-5.4-mini")
        engine._fold_index = [
            FoldRecord(
                fold_id=1,
                summary="database schema decisions",
                keywords=["database", "schema", "decisions"],
                token_count=100,
                created_at="2026-07-05T00:00:00Z",
            ),
            FoldRecord(
                fold_id=2,
                summary="database schema follow-up",
                keywords=["database", "schema", "follow", "decisions"],
                token_count=120,
                created_at="2026-07-05T00:10:00Z",
            ),
            FoldRecord(
                fold_id=3,
                summary="lunch plan",
                keywords=["lunch", "plan"],
                token_count=80,
                created_at="2026-07-05T01:00:00Z",
            ),
        ]

        engine._rebuild_clusters()

        self.assertEqual(len(engine._cluster_index), 2)
        self.assertEqual(engine._cluster_index[0].fold_ids, [1, 2])
        self.assertEqual(engine._cluster_index[1].fold_ids, [3])
        self.assertIn("database", engine._cluster_index[0].summary)
        self.assertIn("lunch", engine._cluster_index[1].summary)


if __name__ == "__main__":
    unittest.main()
