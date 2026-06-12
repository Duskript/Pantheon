"""Tests for B1-B4 from the Pass 3.1 cleanup.

This file tests the new pieces that close the gaps in the original build:
  - B1: canonical relationship_types (learned_from, superseded_by, ...)
        seeded on every migrate() call
  - B2: L2 prompt now lists learned_from in the canonical types
  - B3: backfill_l2.py runner exists with a sane loop (does NOT actually
        call the LLM in tests — call_fn is injected as a stub)
  - B4: outcome backfill promotes stale `pending` entries to `unknown`

We use a temp DB for the entity tests (per the established convention
that destructive ops on real DB pollute other test runs). We use a temp
JSONL for the outcome backfill tests.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

# Ensure lib.ichor.entities is importable when running from the repo root
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# =====================================================================
# B1: canonical relationship_types seeded on migrate()
# =====================================================================

class TestRelationshipTypeSeeds(unittest.TestCase):
    """B1: canonical relationship_types registered on migrate()."""

    def _fresh_db(self) -> str:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="er_b1_")
        os.close(fd)
        os.unlink(path)  # rm empty file; we want a fresh path
        return path

    def test_seeds_creates_5_canonical_types(self):
        """Fresh DB: migrate() inserts the 4 missing canonical types
        (related_to is pre-existing via L2)."""
        from lib.ichor.entities.relationship_type_seeds import (
            CANONICAL_TYPES,
            seed_relationship_types,
        )
        db = self._fresh_db()
        try:
            from lib.ichor.entities.schema import migrate
            result = migrate(db)
            seeded = result["seed_result"]
            # All 5 types end up present after migrate
            self.assertEqual(seeded["inserted"] + seeded["already_present"], len(CANONICAL_TYPES))
            # And they really are in the DB
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            rows = con.execute("SELECT id FROM relationship_types ORDER BY id").fetchall()
            ids = {r["id"] for r in rows}
            for expected in ("learned_from", "superseded_by", "derived_from", "replaces"):
                self.assertIn(expected, ids, f"{expected} should be seeded")
        finally:
            try: os.unlink(db)
            except OSError: pass

    def test_seeds_is_idempotent(self):
        """Running migrate() twice does not duplicate or error."""
        from lib.ichor.entities.schema import migrate
        db = self._fresh_db()
        try:
            r1 = migrate(db)
            r2 = migrate(db)
            self.assertGreaterEqual(r1["seed_result"]["inserted"], 4)
            self.assertEqual(r2["seed_result"]["inserted"], 0,
                             "second migrate() should be a no-op for seeds")
            expected = r1["seed_result"]["inserted"] + r1["seed_result"]["already_present"]
            self.assertEqual(r2["seed_result"]["already_present"], expected)
        finally:
            try: os.unlink(db)
            except OSError: pass

    def test_seeded_types_have_correct_metadata(self):
        """The seeded types have family/is_temporal/is_directional set."""
        from lib.ichor.entities.relationship_type_seeds import seed_relationship_types
        db = self._fresh_db()
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            from lib.ichor.entities.schema import SCHEMA_SQL, get_conn
            conn = get_conn(db)
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.close()
            # Now seed
            conn = get_conn(db)
            result = seed_relationship_types(conn)
            conn.commit()
            conn.close()
            # Check learned_from
            row = con.execute("SELECT * FROM relationship_types WHERE id = 'learned_from'").fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["family"], "learning")
            self.assertEqual(bool(row["is_temporal"]), True)
            self.assertEqual(bool(row["is_directional"]), True)
            # Check superseded_by
            row = con.execute("SELECT * FROM relationship_types WHERE id = 'superseded_by'").fetchone()
            self.assertEqual(row["family"], "lifecycle")
        finally:
            try: os.unlink(db)
            except OSError: pass


# =====================================================================
# B2: L2 prompt now includes learned_from
# =====================================================================

class TestL2PromptIncludesLearnedFrom(unittest.TestCase):
    """B2: PROMPT_TEMPLATE lists learned_from in the canonical types."""

    def test_learned_from_in_canonical_list(self):
        from lib.ichor.entities.l2_llm import PROMPT_TEMPLATE
        self.assertIn("learned_from", PROMPT_TEMPLATE)

    def test_superseded_by_still_in_canonical_list(self):
        """B2 doesn't drop superseded_by — it was already there."""
        from lib.ichor.entities.l2_llm import PROMPT_TEMPLATE
        self.assertIn("superseded_by", PROMPT_TEMPLATE)

    def test_prompt_has_learning_family_guidance(self):
        """The guidance text was added in B2 — it should be in the prompt."""
        from lib.ichor.entities.l2_llm import PROMPT_TEMPLATE
        self.assertIn("LEARNING family", PROMPT_TEMPLATE)
        self.assertIn("LIFECYCLE family", PROMPT_TEMPLATE)

    def test_build_prompt_runs_with_typical_texts(self):
        """Smoke: build_prompt() with sample inputs produces a valid prompt."""
        from lib.ichor.entities.l2_llm import build_prompt
        prompt = build_prompt([
            "We learned from the 2026-06-04 incident that cache invalidation matters.",
            "The old Atlas auth is superseded by the new OIDC setup.",
        ])
        self.assertIn("learned_from", prompt)
        self.assertIn("superseded_by", prompt)
        # The turns are embedded
        self.assertIn("cache invalidation", prompt)
        self.assertIn("OIDC", prompt)


# =====================================================================
# B3: backfill_l2.py runner exists with a sane loop
# =====================================================================

class TestBackfillL2Runner(unittest.TestCase):
    """B3: backfill_l2 runner loops extract_incremental to completion."""

    def _stub_call_fn(self, events: list[str]) -> str:
        """Stub LLM call: returns a no-entities JSON."""
        return json.dumps({
            "entities": [],
            "relationships": [],
            "relationship_types": [],
        })

    def test_run_stops_when_no_more_events(self):
        """If extract_incremental reports no events, the loop stops."""
        from lib.ichor.entities.backfill_l2 import run
        from lib.ichor.entities.schema import get_conn, SCHEMA_SQL

        db = tempfile.mktemp(suffix=".db", prefix="er_b3_")
        try:
            # Fresh DB
            conn = get_conn(db)
            conn.executescript(SCHEMA_SQL)
            conn.commit()
            conn.close()

            # Mock extract_incremental to always report 0 events
            with mock.patch("lib.ichor.entities.backfill_l2.extract_incremental") as m:
                m.return_value = {
                    "events_in_batch": 0,
                    "last_event_id_before": 0,
                    "last_event_id_after": 0,
                    "provisional": True,
                    "stored": {"entities_created": 0, "relationships_created": 0,
                               "rel_types_created": 0, "entity_types_created": 0,
                               "extraction_logs_inserted": 0},
                }
                result = run(db, batch_size=50, max_passes=10, call_fn=self._stub_call_fn)
                self.assertEqual(result["passes"], 1,
                                 "loop should stop on first no-events result")
                self.assertEqual(result["last_event_id"], 0)
        finally:
            try: os.unlink(db)
            except OSError: pass

    def test_run_respects_max_passes_safety_cap(self):
        """max_passes prevents an infinite loop in pathological conditions."""
        from lib.ichor.entities.backfill_l2 import run

        db = tempfile.mktemp(suffix=".db", prefix="er_b3b_")
        try:
            # Mock to always report 1 event AND advance the cursor each
            # pass. The safety cap is what stops us; the defensive
            # "didn't advance" break is not triggered.
            counter = {"n": 0}
            def _mock(*args, **kwargs):
                counter["n"] += 1
                return {
                    "events_in_batch": 1,
                    "last_event_id_before": counter["n"] - 1,
                    "last_event_id_after": counter["n"],
                    "provisional": True,
                    "stored": {"entities_created": 0, "relationships_created": 0,
                               "rel_types_created": 0, "entity_types_created": 0,
                               "extraction_logs_inserted": 0},
                }
            with mock.patch("lib.ichor.entities.backfill_l2.extract_incremental", _mock):
                result = run(db, batch_size=50, max_passes=3, call_fn=self._stub_call_fn)
                self.assertEqual(result["passes"], 3, "should respect max_passes cap")
                self.assertEqual(result["last_event_id"], 3)
        finally:
            try: os.unlink(db)
            except OSError: pass


# =====================================================================
# B4: outcome backfill promotes stale pending to unknown
# =====================================================================

class TestOutcomeBackfill(unittest.TestCase):
    """B4: outcome_backfill.py promotes stale `pending` to `unknown`."""

    def _make_log(self, entries: list[dict]) -> str:
        """Write a temp JSONL with the given entries."""
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="rl_b4_")
        os.close(fd)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e))
                f.write("\n")
        return path

    def test_dry_run_does_not_write(self):
        from lib.clawforge.outcome_backfill import backfill_pending
        now = time.time()
        path = self._make_log([
            {"timestamp": now - 86400, "outcome": "pending", "query": "old1"},
            {"timestamp": now - 60, "outcome": "pending", "query": "new1"},
        ])
        try:
            before = open(path).read()
            counts = backfill_pending(Path(path), grace_hours=4, dry_run=True)
            after = open(path).read()
            self.assertEqual(before, after, "dry_run must not modify the file")
            self.assertEqual(counts["promoted"], 1, "old entry should be eligible")
            self.assertEqual(counts["pending_within_grace"], 1)
        finally:
            os.unlink(path)

    def test_promotes_stale_pending(self):
        from lib.clawforge.outcome_backfill import backfill_pending
        now = time.time()
        path = self._make_log([
            {"timestamp": now - 86400, "outcome": "pending", "query": "old1"},
            {"timestamp": now - 86400 * 2, "outcome": "pending", "query": "old2"},
            {"timestamp": now - 60, "outcome": "pending", "query": "new1"},
            {"timestamp": now - 86400, "outcome": "used", "query": "already_resolved"},
        ])
        try:
            counts = backfill_pending(Path(path), grace_hours=4, new_outcome="unknown")
            self.assertEqual(counts["scanned"], 4)
            self.assertEqual(counts["promoted"], 2, "two stale entries should be promoted")
            self.assertEqual(counts["pending_within_grace"], 1, "new entry stays pending")
            self.assertEqual(counts["already_resolved"], 1, "used entry untouched")

            # Verify the file was rewritten with the new outcome
            lines = [json.loads(l) for l in open(path) if l.strip()]
            old1 = [e for e in lines if e.get("query") == "old1"][0]
            self.assertEqual(old1["outcome"], "unknown")
            self.assertEqual(old1["_promoted_from"], "pending")
            self.assertIn("_promoted_at", old1)

            new1 = [e for e in lines if e.get("query") == "new1"][0]
            self.assertEqual(new1["outcome"], "pending", "new entry stays pending")

            used = [e for e in lines if e.get("query") == "already_resolved"][0]
            self.assertEqual(used["outcome"], "used", "used entry untouched")
        finally:
            os.unlink(path)

    def test_missing_log_file_returns_zero_counts(self):
        from lib.clawforge.outcome_backfill import backfill_pending
        path = Path("/tmp/definitely_does_not_exist_xyz_12345.jsonl")
        if path.exists():
            path.unlink()
        counts = backfill_pending(path, grace_hours=4)
        self.assertEqual(counts["scanned"], 0)
        self.assertEqual(counts["promoted"], 0)

    def test_atomic_write_via_tempfile(self):
        """The writer uses .tmp + os.replace so a crash mid-write doesn't
        corrupt the log."""
        from lib.clawforge.outcome_backfill import backfill_pending, _atomic_write_jsonl
        now = time.time()
        path = self._make_log([
            {"timestamp": now - 86400, "outcome": "pending", "query": "x"},
        ])
        try:
            _atomic_write_jsonl(Path(path), [
                {"timestamp": now, "outcome": "used", "query": "rewritten"},
            ])
            content = open(path).read().strip()
            self.assertEqual(json.loads(content)["query"], "rewritten")
            # No leftover .tmp files
            tmp_files = list(Path(path).parent.glob(f".{Path(path).name}.*.tmp"))
            self.assertEqual(len(tmp_files), 0, "no leftover .tmp files")
        finally:
            os.unlink(path)


# =====================================================================
# Integration: Outcome API now sees promoted entries
# =====================================================================

class TestOutcomeApiAfterBackfill(unittest.TestCase):
    """The Outcome API (`get_recent_outcomes`) should now return entries
    after the backfill runs, instead of always returning total=0."""

    def test_outcome_api_sees_unknown_entries(self):
        from lib.clawforge.outcome_backfill import backfill_pending
        from lib.clawforge.memory_api import get_recent_outcomes
        now = time.time()
        # 5 stale entries, 1 fresh
        entries = [
            {"timestamp": now - 86400 * (i + 1), "outcome": "pending",
             "query": f"test query {i}", "result_count": 5,
             "result_ids": [f"chroma:id{i}"], "weights": {}, "backends_used": ["fts5"]}
            for i in range(5)
        ]
        entries.append({"timestamp": now - 60, "outcome": "pending",
                        "query": "fresh", "result_count": 1,
                        "result_ids": ["chroma:fresh"], "weights": {}, "backends_used": ["fts5"]})
        path = self._make_log(entries)
        try:
            # Patch the path the API uses
            from lib.clawforge import memory_api
            with mock.patch.object(memory_api, "RETRIEVAL_LOG_PATH", Path(path)):
                # Before backfill: total=0 (everything is pending)
                summary = get_recent_outcomes(days=30)
                self.assertEqual(summary.total, 0, "before backfill should be 0")

                # Run backfill
                counts = backfill_pending(Path(path), grace_hours=4)
                self.assertEqual(counts["promoted"], 5)

                # After backfill: 5 entries surface as `unknown`
                summary2 = get_recent_outcomes(days=30)
                self.assertEqual(summary2.total, 5)
                by_outcome = summary2.by_outcome
                self.assertEqual(by_outcome.get("unknown"), 5)
        finally:
            os.unlink(path)

    def _make_log(self, entries: list[dict]) -> str:
        fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="rl_b4int_")
        os.close(fd)
        with open(path, "w") as f:
            for e in entries:
                f.write(json.dumps(e))
                f.write("\n")
        return path


if __name__ == "__main__":
    unittest.main()
