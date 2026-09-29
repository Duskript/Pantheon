#!/usr/bin/env python3
"""L2 entity summaries — the hollow-node fix (prompt → parser → storage).

Context: `_get_or_create_entity` used to hardcode `summary = ''`, and neither
`build_prompt()` nor `parse_extraction()` carried a summary field at all. So
every entity the L2 LLM extractor created was born hollow: 10,007 of 13,109
connected entities had no summary, and the empty set grew ~450/day. Graph
recall still rendered those nodes (read-time descriptor) but with derived
filler instead of knowledge.

Contract pinned by this suite:
  1. the prompt asks for a grounded one-sentence summary per entity
  2. the parser carries it, normalizes junk to "", and caps length
  3. storage writes it on create
  4. re-extraction NEVER overwrites an existing summary (only fills empties)
  5. counts + l2_stats expose summary coverage for monitoring

Tests use a temp DB and a mock `call_fn` — no network, no writes to the live
graph. Run with the hermes venv (no pytest there):
    ~/.hermes/hermes-agent/.venv/bin/python3 tests/test_ichor_l2_entity_summary.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.l2_llm import (  # noqa: E402
    MAX_SUMMARY_CHARS,
    _store_extraction,
    build_prompt,
    extract_incremental,
    l2_stats,
    parse_extraction,
)
from lib.ichor.entities.schema import get_conn, migrate  # noqa: E402

MOCK_PROVIDER = {"name": "mock", "api": "http://mock.invalid", "default_model": "mock-1"}


def _isolated_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="l2_summary_test_")
    os.close(fd)
    return Path(path)


def make_mock_call(payload) -> object:
    if isinstance(payload, dict):
        payload = json.dumps(payload)

    def call_fn(prompt, provider_cfg, model=None, timeout=30.0):
        return payload

    return call_fn


def _parsed(entities) -> dict:
    return {"entities": entities, "relationships": [], "relationship_types": []}


class TestPromptAsksForSummary(unittest.TestCase):
    def test_prompt_requests_grounded_summary(self):
        prompt = build_prompt(["Alice works at Anthropic since 2025."])
        self.assertIn('"summary"', prompt)
        self.assertIn("Every entity MUST carry", prompt)
        self.assertIn("grounded ONLY in the turns", prompt)

    def test_prompt_tells_model_empty_beats_invented(self):
        prompt = build_prompt(["something"])
        self.assertIn("empty beats invented", prompt)

    def test_prompt_does_not_reintroduce_empty_string_literals(self):
        """The ER-P2 suite pins that the prompt never emits a bare "" literal
        for an empty turn; the summary guidance must not break that."""
        prompt = build_prompt(["Alice works at Anthropic."])
        self.assertNotIn('""', prompt)


class TestParseCarriesSummary(unittest.TestCase):
    def test_summary_is_kept_and_stripped(self):
        out = parse_extraction(json.dumps({
            "entities": [{"name": "Tallon", "type": "person", "summary": "  Konan's brother.  "}],
            "relationships": [],
        }))
        self.assertEqual(out["entities"][0]["summary"], "Konan's brother.")

    def test_missing_summary_defaults_to_empty_string(self):
        out = parse_extraction(json.dumps({"entities": [{"name": "X", "type": "person"}]}))
        self.assertEqual(out["entities"][0]["summary"], "")

    def test_null_and_non_string_summary_collapse_to_empty(self):
        out = parse_extraction(json.dumps({
            "entities": [
                {"name": "A", "type": "person", "summary": None},
                {"name": "B", "type": "person", "summary": 42},
                {"name": "C", "type": "person", "summary": ["nope"]},
            ]
        }))
        self.assertEqual([e["summary"] for e in out["entities"]], ["", "", ""])

    def test_overlong_summary_is_capped(self):
        long_text = "x" * (MAX_SUMMARY_CHARS + 200)
        out = parse_extraction(json.dumps({
            "entities": [{"name": "L", "type": "concept", "summary": long_text}]
        }))
        s = out["entities"][0]["summary"]
        self.assertEqual(len(s), MAX_SUMMARY_CHARS)
        self.assertTrue(s.endswith("..."))

    def test_every_entity_dict_has_summary_key(self):
        out = parse_extraction(json.dumps({"entities": [{"name": "K", "type": "tool"}]}))
        self.assertIn("summary", out["entities"][0])


class TestSummaryStorage(unittest.TestCase):
    """Temp DB: storage contract for create / fill / never-overwrite."""

    def setUp(self):
        self.db_path = _isolated_db()
        from lib.ichor.entities import schema as _schema

        self._schema_db = _schema.DB_PATH
        _schema.DB_PATH = self.db_path
        conn = get_conn()
        migrate()
        # `migrate()` covers the entity-graph tables only; cold_events is the
        # cold-storage corpus and is created here (mirrors the ER-P2 suite).
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cold_events (
                   id INTEGER PRIMARY KEY,
                   raw_text TEXT,
                   created_at TEXT DEFAULT (datetime('now'))
               )"""
        )
        conn.execute(
            "INSERT INTO cold_events (id, raw_text) VALUES (1, 'Tallon is Konan''s brother.')"
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        from lib.ichor.entities import schema as _schema

        _schema.DB_PATH = self._schema_db
        if self.db_path.exists():
            self.db_path.unlink()

    def _summary_of(self, name: str, type_id: str = "person") -> str:
        conn = get_conn()
        try:
            row = conn.execute(
                "SELECT summary FROM entities WHERE name = ? AND type_id = ?", (name, type_id)
            ).fetchone()
            return row["summary"] if row else None
        finally:
            conn.close()

    def test_new_entity_stores_summary(self):
        conn = get_conn()
        counts = _store_extraction(
            conn,
            _parsed([{"name": "Tallon", "type": "person", "summary": "Konan's brother."}]),
            source_text="t",
            provisional=True,
        )
        conn.commit()
        conn.close()
        self.assertEqual(self._summary_of("Tallon"), "Konan's brother.")
        self.assertEqual(counts["entity_summaries_written"], 1)

    def test_reextraction_does_not_overwrite_existing_summary(self):
        conn = get_conn()
        _store_extraction(
            conn,
            _parsed([{"name": "Tallon", "type": "person", "summary": "Konan's brother."}]),
            source_text="t1",
            provisional=True,
        )
        counts = _store_extraction(
            conn,
            _parsed([{"name": "Tallon", "type": "person", "summary": "A person mentioned somewhere."}]),
            source_text="t2",
            provisional=False,
        )
        conn.commit()
        conn.close()
        self.assertEqual(self._summary_of("Tallon"), "Konan's brother.")
        self.assertEqual(counts["entity_summaries_written"], 0)

    def test_hollow_entity_is_filled_on_reobservation(self):
        conn = get_conn()
        _store_extraction(
            conn,
            _parsed([{"name": "Fia", "type": "person"}]),  # no summary → hollow
            source_text="t1",
            provisional=True,
        )
        conn.commit()
        self.assertEqual(self._summary_of("Fia"), "")

        counts = _store_extraction(
            conn,
            _parsed([{"name": "Fia", "type": "person", "summary": "Konan's partner."}]),
            source_text="t2",
            provisional=True,
        )
        conn.commit()
        conn.close()
        self.assertEqual(self._summary_of("Fia"), "Konan's partner.")
        self.assertEqual(counts["entity_summaries_written"], 1)

    def test_empty_summary_never_writes(self):
        conn = get_conn()
        counts = _store_extraction(
            conn,
            _parsed([{"name": "Ghost", "type": "concept", "summary": "   "}]),
            source_text="t",
            provisional=True,
        )
        conn.commit()
        conn.close()
        self.assertEqual(self._summary_of("Ghost", "concept"), "")
        self.assertEqual(counts["entity_summaries_written"], 0)

    def test_incremental_pass_reports_summaries_written(self):
        conn = get_conn()
        result = extract_incremental(
            conn,
            last_event_id=0,
            batch_size=25,
            provider_cfg=MOCK_PROVIDER,
            call_fn=make_mock_call({
                "entities": [
                    {"name": "Tallon", "type": "person", "summary": "Konan's brother."},
                    {"name": "Pantheon", "type": "project", "summary": "Konan's multi-agent system."},
                ],
                "relationships": [
                    {"source": "Tallon", "type": "knows", "target": "Pantheon", "confidence": 0.8}
                ],
            }),
        )
        conn.close()
        self.assertEqual(result["events_in_batch"], 1)
        self.assertEqual(result["stored"]["entities_created"], 2)
        self.assertEqual(result["stored"]["entity_summaries_written"], 2)
        self.assertEqual(self._summary_of("Pantheon", "project"), "Konan's multi-agent system.")

    def test_empty_batch_result_exposes_summaries_key(self):
        conn = get_conn()
        result = extract_incremental(
            conn, last_event_id=999, batch_size=25, provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call({})
        )
        conn.close()
        self.assertIn("entity_summaries_written", result["stored"])

    def test_l2_stats_reports_summary_coverage(self):
        conn = get_conn()
        _store_extraction(
            conn,
            _parsed([
                {"name": "Tallon", "type": "person", "summary": "Konan's brother."},
                {"name": "Hollow", "type": "concept"},
            ]),
            source_text="t",
            provisional=True,
        )
        conn.commit()
        stats = l2_stats(conn)
        conn.close()
        self.assertGreaterEqual(stats["entities_active"], 2)
        self.assertGreaterEqual(stats["entities_hollow"], 1)
        self.assertLess(stats["entity_summary_coverage_pct"], 100.0)
        self.assertGreater(stats["entity_summary_coverage_pct"], 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
