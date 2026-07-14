"""
ER-P2: L2 LLM extraction — gate + lifecycle tests.

Spec: ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md §L2

ER-P2 gate (per spec):
  [1] extraction runs without breaking conversation flow
  [2] entities appear before session end (provisional=1 during conversation)
  [3] finalize() flips provisional=1 → 0
  [4] incremental only processes unprocessed events (idempotent)
  [5] finalize() with empty residual is a no-op

Tests use a mock `call_fn` to avoid real LLM calls (deterministic, $0).
Real LLM integration is exercised by a small smoke run against the
real ichor.db (recorded separately, not in the test suite).
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.l2_llm import (  # noqa: E402
    build_prompt,
    extract_batch,
    extract_incremental,
    finalize,
    l2_stats,
    parse_extraction,
)
from lib.ichor.entities.schema import (  # noqa: E402
    get_conn,
    migrate,
)


def _isolated_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="er_p2_test_")
    os.close(fd)
    return Path(path)


# ----- Mock LLM helpers -----

# Provider config is just a dict; the call_fn signature is
# (prompt, provider_cfg, model=None, timeout=30.0) -> str
MOCK_PROVIDER = {"name": "mock", "api": "http://mock.invalid", "default_model": "mock-1"}


def make_mock_call(canned_response):
    """Return a call_fn that ignores the prompt and returns the canned
    response (string or dict — if dict, will be JSON-serialized)."""
    if isinstance(canned_response, dict):
        canned_response = json.dumps(canned_response)
    def call_fn(prompt, provider_cfg, model=None, timeout=30.0):
        return canned_response
    return call_fn


# =======================================================================
# build_prompt unit tests
# =======================================================================

class TestBuildPrompt(unittest.TestCase):
    def test_includes_canonical_entity_types(self):
        p = build_prompt(["Alice works at Anthropic."])
        self.assertIn("person", p)
        self.assertIn("organization", p)

    def test_includes_canonical_relationship_types(self):
        p = build_prompt(["Alice works at Anthropic."])
        self.assertIn("works_at", p)
        self.assertIn("related_to", p)

    def test_truncates_long_turns(self):
        long_turn = "A" * 5000
        p = build_prompt([long_turn])
        # The turn should be truncated to ~1500 chars + "..."
        self.assertIn("...", p)
        # The full 5000 'A's should not appear
        self.assertNotIn("A" * 5000, p)

    def test_skips_empty_turns(self):
        texts: list[Optional[str]] = ["", "  ", None, "Alice works at Anthropic."]
        p = build_prompt(texts)  # type: ignore[arg-type]
        # 4 turns input, 1 non-empty; JSON should contain only one item
        self.assertIn("Alice works at Anthropic.", p)
        # Empty strings shouldn't appear as separate array items
        self.assertNotIn('""', p)


# =======================================================================
# parse_extraction unit tests
# =======================================================================

class TestParseExtraction(unittest.TestCase):
    def test_parses_clean_json(self):
        raw = json.dumps({
            "entities": [{"name": "Anthropic", "type": "organization", "aliases": [], "confidence": 0.9}],
            "relationships": [{"source": "Alice", "type": "works_at", "target": "Anthropic", "confidence": 0.8, "valid_from": "2025-01-01"}],
            "relationship_types": [],
        })
        out = parse_extraction(raw)
        self.assertEqual(len(out["entities"]), 1)
        self.assertEqual(out["entities"][0]["name"], "Anthropic")
        self.assertEqual(len(out["relationships"]), 1)
        self.assertEqual(out["relationships"][0]["source"], "Alice")
        self.assertEqual(out["relationships"][0]["valid_from"], "2025-01-01")

    def test_parses_markdown_fenced_json(self):
        raw = '```json\n{"entities": [{"name": "Bob", "type": "person"}], "relationships": []}\n```'
        out = parse_extraction(raw)
        self.assertEqual(len(out["entities"]), 1)
        self.assertEqual(out["entities"][0]["name"], "Bob")
        # No "prose-wrapped" warning: the code strips the fence and parses
        # the inner JSON directly.

    def test_parses_prose_wrapped_json(self):
        raw = 'Here is the extraction:\n{"entities": [], "relationships": []}\nDone.'
        out = parse_extraction(raw)
        self.assertEqual(out["entities"], [])

    def test_handles_empty_response(self):
        out = parse_extraction("")
        self.assertEqual(out["entities"], [])
        self.assertIn("empty response", out["_parse_warnings"])

    def test_skips_invalid_entities(self):
        raw = json.dumps({
            "entities": [
                {"name": "Good", "type": "person"},
                {"name": 42, "type": "person"},  # non-string name
                {"type": "person"},               # missing name
                "not a dict",
            ],
            "relationships": [],
        })
        out = parse_extraction(raw)
        self.assertEqual(len(out["entities"]), 1)
        self.assertEqual(out["entities"][0]["name"], "Good")
        self.assertGreaterEqual(len(out["_parse_warnings"]), 2)

    def test_clamps_confidence_to_0_1(self):
        raw = json.dumps({
            "entities": [
                {"name": "X", "type": "person", "confidence": 1.5},
                {"name": "Y", "type": "person", "confidence": -0.3},
                {"name": "Z", "type": "person", "confidence": 0.5},
            ],
            "relationships": [],
        })
        out = parse_extraction(raw)
        confs = [e["confidence"] for e in out["entities"]]
        self.assertEqual(confs, [1.0, 0.0, 0.5])

    def test_missing_optional_arrays_default_to_empty(self):
        raw = json.dumps({})  # no entities/relationships keys
        out = parse_extraction(raw)
        self.assertEqual(out["entities"], [])
        self.assertEqual(out["relationships"], [])

    def test_invalid_json_raises(self):
        with self.assertRaises(ValueError):
            parse_extraction("not json at all, no braces")


# =======================================================================
# extract_batch (mocked LLM)
# =======================================================================

class TestExtractBatch(unittest.TestCase):
    def test_returns_parsed_shape_from_mock(self):
        canned = {
            "entities": [{"name": "Anthropic", "type": "organization", "confidence": 0.9}],
            "relationships": [],
        }
        out = extract_batch(["Alice works at Anthropic"], MOCK_PROVIDER, call_fn=make_mock_call(canned))
        self.assertEqual(out["entities"][0]["name"], "Anthropic")

    def test_empty_texts_returns_empty(self):
        out = extract_batch([], MOCK_PROVIDER, call_fn=make_mock_call({}))
        self.assertEqual(out["entities"], [])
        self.assertIn("empty batch", out["_parse_warnings"])


# =======================================================================
# End-to-end against isolated DB
# =======================================================================

CANNED_LLM_RESPONSE = {
    "entities": [
        {"name": "Anthropic", "type": "organization", "aliases": ["anthropics"], "confidence": 0.95},
        {"name": "Alice", "type": "person", "aliases": [], "confidence": 0.9},
        {"name": "Bob", "type": "person", "aliases": [], "confidence": 0.85},
    ],
    "relationships": [
        {"source": "Alice", "type": "works_at", "target": "Anthropic", "confidence": 0.9, "valid_from": "2025-01-01"},
        {"source": "Bob", "type": "works_at", "target": "Anthropic", "confidence": 0.85, "valid_from": "2024-06-01"},
    ],
    "relationship_types": [],
}


def _seed_cold_events(conn, events):
    """Mimic the real cold_events schema. ER-P2 reads cold_events.raw_text."""
    conn.executescript("""
        CREATE TABLE cold_events (
            id INTEGER PRIMARY KEY,
            raw_text TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.executemany(
        "INSERT INTO cold_events (id, raw_text) VALUES (?, ?)",
        events,
    )
    conn.commit()


class TestL2Lifecycle(unittest.TestCase):
    """End-to-end incremental + finalize lifecycle on a temp DB."""

    def setUp(self):
        self.db_path = _isolated_db()
        from lib.ichor.entities import schema as _schema
        self._schema_db = _schema.DB_PATH
        _schema.DB_PATH = self.db_path

        conn = get_conn()
        migrate()
        _seed_cold_events(conn, [
            (1, "Alice works at Anthropic since 2025."),
            (2, "Bob joined Anthropic in 2024."),
            (3, "Anthropic released the Claude API."),
        ])
        conn.commit()
        conn.close()

    def tearDown(self):
        from lib.ichor.entities import schema as _schema
        _schema.DB_PATH = self._schema_db
        if self.db_path.exists():
            self.db_path.unlink()

    def test_incremental_pull_empty_when_no_events(self):
        conn = get_conn()
        result = extract_incremental(
            conn, last_event_id=10, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        self.assertEqual(result["events_in_batch"], 0)
        self.assertEqual(result["last_event_id_after"], 10)
        self.assertIn("no events", result["skipped"])

    def test_incremental_writes_provisional_entities(self):
        """ER-P2 gate 2: entities appear during conversation (provisional=1)."""
        conn = get_conn()
        result = extract_incremental(
            conn, last_event_id=0, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        self.assertEqual(result["events_in_batch"], 3)
        self.assertEqual(result["provisional"], True)
        self.assertEqual(result["stored"]["entities_created"], 3)
        self.assertEqual(result["stored"]["relationships_created"], 2)
        # Verify provisional=1 in DB
        conn = get_conn()
        n_prov = conn.execute("SELECT COUNT(*) FROM entities WHERE provisional = 1").fetchone()[0]
        conn.close()
        self.assertEqual(n_prov, 3, "incremental pass should leave all entities provisional=1")

    def test_incremental_idempotent(self):
        """ER-P2 gate 4: re-running incremental on the same range is a no-op."""
        conn = get_conn()
        r1 = extract_incremental(
            conn, last_event_id=0, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        # Second run: last_event_id=3 means no new events
        conn = get_conn()
        r2 = extract_incremental(
            conn, last_event_id=3, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        self.assertEqual(r1["stored"]["entities_created"], 3)
        self.assertEqual(r2["events_in_batch"], 0)
        # Final state: still 3 entities (no duplicates)
        conn = get_conn()
        n = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        conn.close()
        self.assertEqual(n, 3)

    def test_finalize_flips_provisional_to_zero(self):
        """ER-P2 gate 3: finalize() flips provisional=1 → 0."""
        # First: run an incremental pass (sets provisional=1)
        conn = get_conn()
        extract_incremental(
            conn, last_event_id=0, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        # Then: finalize
        conn = get_conn()
        result = finalize(
            conn, last_event_id=3,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        self.assertEqual(result["residual_events"], 0)
        self.assertEqual(result["flipped_entities_provisional"], 3)
        self.assertEqual(result["flipped_relationships_provisional"], 2)
        # Verify: all provisional=0
        conn = get_conn()
        n_prov = conn.execute("SELECT COUNT(*) FROM entities WHERE provisional = 1").fetchone()[0]
        n_rel_prov = conn.execute("SELECT COUNT(*) FROM relationships WHERE provisional = 1").fetchone()[0]
        conn.close()
        self.assertEqual(n_prov, 0)
        self.assertEqual(n_rel_prov, 0)

    def test_finalize_with_residual_processes_remaining(self):
        """If residual events exist, finalize runs L2 on them as non-provisional."""
        # Add a 4th event (which the incremental didn't see)
        conn = get_conn()
        conn.execute("INSERT INTO cold_events (id, raw_text) VALUES (4, 'Carol also works at Anthropic.')")
        conn.commit()
        conn.close()
        # First: incremental pass over 1-3
        conn = get_conn()
        extract_incremental(
            conn, last_event_id=0, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        # Then: finalize starting at last_event_id=3, total=4 → residual=1 event
        conn = get_conn()
        result = finalize(
            conn, last_event_id=3,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        self.assertEqual(result["residual_events"], 1)
        # Finalize should have flipped the 3 incremental entities
        self.assertEqual(result["flipped_entities_provisional"], 3)

    def test_finalize_empty_residual_flips_provisionals(self):
        """ER-P2 gate 5: finalize on empty residual is a no-op for LLM but flips provisionals."""
        # Set up: 3 entities all provisional=1
        conn = get_conn()
        extract_incremental(
            conn, last_event_id=0, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        # Finalize starting at last_event_id=3 (which is past the end)
        conn = get_conn()
        result = finalize(
            conn, last_event_id=3,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        conn.close()
        # No residual → no new entities
        self.assertEqual(result["residual_events"], 0)
        # But flips still happen
        self.assertEqual(result["flipped_entities_provisional"], 3)

    def test_l2_stats(self):
        conn = get_conn()
        extract_incremental(
            conn, last_event_id=0, batch_size=25,
            provider_cfg=MOCK_PROVIDER, call_fn=make_mock_call(CANNED_LLM_RESPONSE),
        )
        stats = l2_stats(conn)
        conn.close()
        self.assertEqual(stats["llm_extractions_logged"], 1)
        self.assertEqual(stats["provisional_entities"], 3)
        self.assertEqual(stats["provisional_relationships"], 2)


# =======================================================================
# Real-DB gate verification (read-only)
# =======================================================================

REAL_DB = Path("/home/konan/.hermes/ichor.db")


@unittest.skipUnless(REAL_DB.exists(), "Real ichor.db not present")
class TestL2AgainstRealDB(unittest.TestCase):
    """Read-only gate verification. The real L2 pass is run as a
    one-shot via the CLI / Python; the test suite inspects the
    post-pass state."""

    def setUp(self):
        # Make sure schema is up to date (provisional columns present)
        migrate()

    def test_real_db_has_provisional_column_on_entities(self):
        cols = {row[1] for row in get_conn().execute("PRAGMA table_info(entities)").fetchall()}
        self.assertIn("provisional", cols)

    def test_real_db_has_provisional_column_on_relationships(self):
        cols = {row[1] for row in get_conn().execute("PRAGMA table_info(relationships)").fetchall()}
        self.assertIn("provisional", cols)

    def test_l2_stats_keys_present(self):
        stats = l2_stats(get_conn())
        for key in ("llm_extractions_logged", "provisional_entities",
                    "provisional_relationships", "llm_entity_types"):
            self.assertIn(key, stats)


if __name__ == "__main__":
    unittest.main()
