#!/usr/bin/env python3
"""Tests for the Fix D Option A priority-scoped summary backfill.

Run directly — the hermes venv has no pytest:

    /home/konan/.hermes/hermes-agent/.venv/bin/python3 \
        /home/konan/pantheon/tests/test_ichor_fix_d_priority_backfill.py

Every test builds its own temp DB (schema via `lib.ichor.entities.schema.migrate`)
and injects a fake `call_fn`, so the suite never touches the live graph and never
makes a network call.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path("/home/konan/pantheon")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor.entities.schema import migrate  # noqa: E402
from scripts.ichor_fix_d_priority_backfill import (  # noqa: E402
    FIXD_BACKFILL_METHOD,
    OPENCODE_SESSION_ID,
    build_evidence,
    build_prompt,
    call_llm_with_usage,
    evidence_digest,
    live_degree,
    parse_summaries,
    rollback,
    run,
    select_targets,
)

NOW = "2026-09-18 12:00:00"


class BaseCase(unittest.TestCase):
    """Temp DB + fixture graph shared by the suite."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "ichor.db"
        migrate(self.db)
        self.conn = sqlite3.connect(str(self.db))
        self.conn.row_factory = sqlite3.Row
        self._schema_extras()
        self._fixture()

    def tearDown(self) -> None:
        self.conn.close()
        self._tmp.cleanup()

    # -- schema -------------------------------------------------------------
    def _schema_extras(self) -> None:
        """Tables the live DB has but `migrate()` does not create."""
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cold_events (
                id INTEGER PRIMARY KEY,
                event_type TEXT,
                category TEXT,
                raw_text TEXT,
                created_at TEXT
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
                content, category, name, event_type, brief, outline
            );
            CREATE TABLE IF NOT EXISTS ichor_settings (
                key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
            );
            """
        )

    def add_entity(self, entity_id: int, name: str, *, type_id: str = "tool",
                   summary: str = "", status: str = "active",
                   aliases: str = "[]", provisional: int = 0) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO entities "
            "(id, type_id, name, aliases, summary, confidence, status, provisional, "
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (entity_id, type_id, name, aliases, summary, 0.9, status, provisional, NOW, NOW),
        )

    def add_rel(self, rel_id: int, source_id: int, target_id: int, type_id: str,
                *, confidence: float = 0.9, weight: float = 0.0,
                provisional: int = 0, valid_to: str | None = None,
                provenance: str = "test") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO relationships "
            "(id, type_id, source_id, target_id, confidence, weight, provenance, "
            " valid_from, valid_to, created_at, updated_at, provisional) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rel_id, type_id, source_id, target_id, confidence, weight, provenance,
             "1970-01-01", valid_to, NOW, NOW, provisional),
        )

    def _fixture(self) -> None:
        """Anchor 614 + a small neighbourhood mirroring the live shape."""
        self.add_entity(614, "konan", type_id="person", summary="Konan is the operator.")
        # empty-summary neighbours, varying degree
        self.add_entity(674, "Pantheon", type_id="organization", aliases='["pantheon"]')
        self.add_entity(595, "Hermes", type_id="tool")
        self.add_entity(780, "Marvin", type_id="project")
        self.add_entity(999, "Orphan", type_id="concept")
        self.add_entity(1000, "Named", type_id="person")
        # already summarised / inactive / nameless must be excluded
        self.add_entity(600, "HasSummary", summary="already there")
        self.add_entity(601, "Archived", status="archived")
        self.add_entity(602, "   ")
        for rel_id, target in ((1, 674), (2, 595), (3, 780)):
            self.add_rel(rel_id, 614, target, "related_to", confidence=0.8)
        # decayed (weight 0) but live — T3 traverses it, so it is in scope
        self.add_rel(4, 614, 999, "uses", confidence=0.5, weight=0.0,
                     provenance="dream_decay_archived")
        # excluded: provisional + expired edges must not create degree
        self.add_rel(5, 601, 1000, "uses", confidence=0.9, provisional=1)
        self.add_rel(6, 601, 1000, "uses", confidence=0.9, valid_to="2020-01-01")
        self.add_entity(700, "RichNeighbour", type_id="tool")
        self.add_rel(7, 614, 700, "knows", confidence=0.95)
        # off-anchor hub: reachable from nothing konan touches, but highest degree
        self.add_entity(800, "IsolatedHub", type_id="project")
        self.add_entity(801, "HubChildA", type_id="tool")
        self.add_entity(802, "HubChildB", type_id="tool")
        self.add_rel(8, 800, 801, "uses", confidence=0.9)
        self.add_rel(9, 800, 802, "uses", confidence=0.9)
        self.conn.executescript(
            """
            INSERT INTO cold_events (id, event_type, category, raw_text, created_at)
            VALUES (100, 'fact', 'event', 'Pantheon runs the god fleet.', '2026-09-01 10:00:00'),
                   (101, 'decision', 'event', 'Pantheon was renamed.', '2026-09-02 10:00:00');
            INSERT INTO memory_fts (rowid, content, category, name, event_type, brief, outline)
            VALUES (100, 'Pantheon runs the god fleet.', 'event', 'Pantheon', 'fact', '', ''),
                   (101, 'Pantheon was renamed this week.', 'event', 'Pantheon', 'decision', '', '');
            """
        )
        self.conn.commit()


class TestScope(BaseCase):
    def test_selects_only_empty_active_named_entities(self) -> None:
        self.add_rel(20, 614, 602, "mentions", confidence=0.7)  # nameless, now a candidate
        self.conn.commit()
        targets, stats = select_targets(self.conn, hubs=10, limit=50, db_path=self.db)
        picked = {t["id"] for t in targets}
        self.assertNotIn(600, picked, "summarised entity must be skipped")
        self.assertNotIn(601, picked, "archived entity must be skipped")
        self.assertNotIn(602, picked, "nameless entity must be skipped")
        self.assertNotIn(614, picked, "the anchor already has a summary -> out of scope")
        self.assertTrue({674, 595, 780, 999, 700}.issubset(picked))
        self.assertEqual(stats["skipped_nameless"], 1)

    def test_t3_membership_flag_and_hub_ordering(self) -> None:
        for extra in (803, 804, 805, 806):
            self.add_entity(extra, f"HubChild{extra}", type_id="tool")
            self.add_rel(extra, 800, extra, "uses", confidence=0.9)
        self.conn.commit()  # 800 now out-degrees the anchor (6 vs 5)
        targets, _ = select_targets(self.conn, hubs=1, depth=1, limit=50, db_path=self.db)
        by_id = {t["id"]: t for t in targets}
        self.assertTrue(by_id[674]["in_t3"], "a live neighbour of the anchor is T3-visible")
        self.assertFalse(by_id[800]["in_t3"],
                         "the off-anchor hub is selected by degree only")
        self.assertTrue(targets[0]["in_t3"], "T3-visible entities sort first")
        self.assertEqual(targets[-1]["id"], 800, "non-T3 hubs sort last")

    def test_limit_truncates_and_reports(self) -> None:
        targets, stats = select_targets(self.conn, hubs=10, limit=2, db_path=self.db)
        self.assertEqual(len(targets), 2)
        self.assertGreater(stats["truncated"], 0)

    def test_depth_two_reaches_grandchildren(self) -> None:
        self.add_entity(5555, "Grandchild", type_id="tool")
        self.add_rel(55, 780, 5555, "depends_on", confidence=0.7)
        self.conn.commit()
        targets, _ = select_targets(self.conn, hubs=0, depth=2, limit=50, db_path=self.db)
        self.assertIn(5555, {t["id"] for t in targets})


class TestDegree(BaseCase):
    def test_degree_ignores_provisional_and_expired(self) -> None:
        degree = live_degree(self.conn)
        self.assertNotIn(1000, degree, "only provisional/expired edges point at 1000")
        self.assertEqual(degree.get(674), 1)
        self.assertEqual(degree.get(614), 5, "614 has five live edges")


class TestEvidence(BaseCase):
    def test_relation_evidence_has_both_directions(self) -> None:
        self.add_rel(77, 780, 614, "manages", confidence=0.6)
        self.conn.commit()
        evidence = build_evidence(self.conn, {"id": 614, "name": "konan",
                                              "type_id": "person", "degree": 4})
        directions = {(r["direction"], r["other_name"]) for r in evidence["relations"]}
        self.assertIn(("->", "Pantheon"), directions)
        self.assertIn(("<-", "Marvin"), directions)
        self.assertEqual(evidence["aliases"], [], "aliases parsed only when present")

    def test_event_evidence_uses_fts_and_is_available(self) -> None:
        evidence = build_evidence(self.conn, {"id": 674, "name": "Pantheon",
                                              "type_id": "organization", "degree": 1})
        self.assertTrue(evidence["events"], "FTS index should supply snippets")
        self.assertTrue(all("Pantheon" in e["text"] for e in evidence["events"]))

    def test_event_evidence_degrades_without_fts(self) -> None:
        self.conn.execute("DROP TABLE memory_fts")
        self.conn.commit()
        evidence = build_evidence(self.conn, {"id": 674, "name": "Pantheon",
                                              "type_id": "organization", "degree": 1})
        self.assertEqual(evidence["events"], [])

    def test_short_names_are_not_searched(self) -> None:
        evidence = build_evidence(self.conn, {"id": 3, "name": "S1", "type_id": "tool",
                                              "degree": 0})
        self.assertEqual(evidence["events"], [])

    def test_digest_is_stable_and_content_sensitive(self) -> None:
        evidence = build_evidence(self.conn, {"id": 674, "name": "Pantheon",
                                              "type_id": "organization", "degree": 1})
        again = build_evidence(self.conn, {"id": 674, "name": "Pantheon",
                                           "type_id": "organization", "degree": 1})
        self.assertEqual(evidence_digest(evidence), evidence_digest(again))
        evidence["degree"] = 99
        self.assertNotEqual(evidence_digest(evidence), evidence_digest(again))


class TestHttpCaller(unittest.TestCase):
    """The opencode-go routing header — its absence was a live HTTP 400."""

    def _capture(self, api_base: str) -> dict:
        import urllib.request
        from unittest import mock

        captured: dict = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return json.dumps({
                    "choices": [{"message": {"content": "{}"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                }).encode()

        def fake_urlopen(req, timeout=None):
            captured["headers"] = {k.lower(): v for k, v in req.header_items()}
            captured["body"] = json.loads(req.data.decode())
            return FakeResponse()

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen):
            call_llm_with_usage("hello", {"api": api_base, "default_model": "m",
                                          "name": "opencode-go"}, model="m", timeout=1.0)
        return captured

    def test_opencode_endpoint_gets_session_header(self) -> None:
        captured = self._capture("https://opencode.ai/zen/go/v1")
        self.assertEqual(captured["headers"].get("x-opencode-session"), OPENCODE_SESSION_ID)
        self.assertEqual(captured["headers"]["user-agent"],
                         "pantheon-ichor/1.0 (fix_d_priority_backfill)")
        self.assertEqual(captured["body"]["thinking"], {"type": "disabled"})

    def test_other_endpoints_do_not(self) -> None:
        captured = self._capture("http://127.0.0.1:20141/v1")
        self.assertNotIn("x-opencode-session", captured["headers"])


class TestPrompt(BaseCase):
    def test_prompt_carries_only_supplied_evidence(self) -> None:
        evidence = build_evidence(self.conn, {"id": 674, "name": "Pantheon",
                                              "type_id": "organization", "degree": 1})
        prompt = build_prompt([evidence], {}, {})
        self.assertIn("name: Pantheon", prompt)
        self.assertIn("relations:", prompt)
        self.assertIn("konan", prompt, "the anchor relation is rendered")
        self.assertIn("event snippets mentioning it:", prompt)
        self.assertIn("Pantheon runs the god fleet.", prompt)
        self.assertIn('"summaries"', prompt)


class TestParse(unittest.TestCase):
    def test_tolerates_fences_and_prose(self) -> None:
        raw = 'Sure!\n```json\n{"summaries":[{"id":1,"summary":"A tool.","confidence":0.9}]}\n```'
        parsed, warnings = parse_summaries(raw, [1])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["summary"], "A tool.")
        self.assertEqual(warnings, [])

    def test_rejects_ids_outside_batch_and_empty_summaries(self) -> None:
        raw = json.dumps({"summaries": [
            {"id": 1, "summary": "ok"},
            {"id": 99, "summary": "not in batch"},
            {"id": 2, "summary": "   "},
            "junk",
        ]})
        parsed, warnings = parse_summaries(raw, [1, 2])
        self.assertEqual([p["id"] for p in parsed], [1])
        self.assertEqual(len(warnings), 3)

    def test_bad_json_returns_warning_not_exception(self) -> None:
        parsed, warnings = parse_summaries("not json at all", [1])
        self.assertEqual(parsed, [])
        self.assertTrue(warnings)

    def test_confidence_defaults_and_clamps(self) -> None:
        raw = json.dumps({"summaries": [{"id": 1, "summary": "x"},
                                        {"id": 2, "summary": "y", "confidence": 5},
                                        {"id": 3, "summary": "z", "confidence": -1}]})
        parsed, _ = parse_summaries(raw, [1, 2, 3])
        by_id = {p["id"]: p for p in parsed}
        self.assertEqual(by_id[1]["confidence"], 0.6)
        self.assertEqual(by_id[2]["confidence"], 1.0)
        self.assertEqual(by_id[3]["confidence"], 0.0)


class TestWrites(BaseCase):
    def _fake_calls(self, calls: list) -> object:
        def call_fn(prompt, provider_cfg, *, model=None, timeout=0.0):
            calls.append(prompt)
            ids = [int(line.split(":")[1]) for line in prompt.splitlines()
                   if line.strip().startswith("- id:")]
            if len(calls) == 1 and getattr(self, "first_reply_garbage", False):
                return ("not json", {"prompt_tokens": 5, "completion_tokens": 1})
            payload = {"summaries": [
                {"id": i, "summary": f"Entity {i} summary.", "confidence": 0.8}
                for i in ids]}
            return (json.dumps(payload), {"prompt_tokens": 100, "completion_tokens": 20})
        return call_fn

    def _run(self, *, apply: bool, audit: Path | None = None, batch: int = 3, limit: int = 5):
        calls: list = []
        report = run(self.conn, model="test-model", batch_size=batch, limit=limit,
                     hubs=10, depth=1, order="recent", apply=apply,
                     audit_path=audit, call_fn=self._fake_calls(calls),
                     provider_cfg={}, timeout=1.0, log=lambda _m: None,
                     db_path=self.db)
        return report, calls

    def test_dry_run_writes_nothing(self) -> None:
        before = self.conn.execute(
            "SELECT COUNT(*) FROM entities WHERE TRIM(COALESCE(summary,''))=''").fetchone()[0]
        report, calls = self._run(apply=False)
        after = self.conn.execute(
            "SELECT COUNT(*) FROM entities WHERE TRIM(COALESCE(summary,''))=''").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(report["written"], 0)
        self.assertGreater(report["generated"], 0)
        self.assertTrue(calls)

    def test_apply_writes_summaries_provenance_and_audit(self) -> None:
        audit = Path(self._tmp.name) / "audit.jsonl"
        report, _ = self._run(apply=True, audit=audit)
        self.assertEqual(report["written"], report["generated"])
        rows = self.conn.execute(
            "SELECT entity_id, method, confidence FROM extraction_log").fetchall()
        self.assertEqual(len(rows), report["written"])
        self.assertTrue(all(r["method"] == FIXD_BACKFILL_METHOD for r in rows))
        lines = [json.loads(line) for line in audit.read_text().splitlines() if line.strip()]
        self.assertEqual(len(lines), report["written"])
        self.assertTrue(all(l["new_summary"] and l["evidence_sha256"] for l in lines))
        checkpoint = self.conn.execute(
            "SELECT value FROM ichor_settings WHERE key='fix_d_priority_summary_backfill_001'"
        ).fetchone()
        self.assertIsNotNone(checkpoint)
        self.assertEqual(json.loads(checkpoint["value"])["written"], report["written"])

    def test_existing_summaries_are_never_overwritten(self) -> None:
        self.conn.execute("UPDATE entities SET summary='keeper' WHERE id=674")
        self.conn.commit()
        self._run(apply=True)
        self.assertEqual(
            self.conn.execute("SELECT summary FROM entities WHERE id=674").fetchone()[0],
            "keeper")

    def test_second_apply_is_a_no_op(self) -> None:
        first, _ = self._run(apply=True, limit=50)
        second, _ = self._run(apply=True, limit=50)
        self.assertGreater(first["written"], 0)
        self.assertEqual(second["written"], 0, "already-summarised rows are not re-written")
        self.assertEqual(second["generated"], 0)

    def test_retry_after_unparseable_reply(self) -> None:
        self.first_reply_garbage = True
        calls: list = []
        report = run(self.conn, model="test-model", batch_size=5, limit=1, hubs=10,
                     depth=1, order="recent", apply=True, audit_path=None,
                     call_fn=self._fake_calls(calls), provider_cfg={}, timeout=1.0,
                     log=lambda _m: None, db_path=self.db)
        self.assertTrue(report["written"], "retry should recover a usable summary")
        self.assertEqual(report["tokens"]["completion_tokens"], 21,
                         "the failed attempt and the retry are both accounted for")

    def test_rollback_restores_only_matching_rows(self) -> None:
        audit = Path(self._tmp.name) / "audit.jsonl"
        report, _ = self._run(apply=True, audit=audit)
        self.conn.execute("UPDATE entities SET summary='edited by a human' "
                          "WHERE id=(SELECT entity_id FROM extraction_log LIMIT 1)")
        self.conn.commit()
        result = rollback(self.conn, audit)
        self.assertEqual(result["skipped"], 1, "human-edited row must be left alone")
        self.assertEqual(result["reverted"], report["written"] - result["skipped"])
        left = self.conn.execute(
            "SELECT COUNT(*) FROM entities WHERE TRIM(COALESCE(summary,''))=''").fetchone()[0]
        self.assertGreater(left, 0, "rolled-back rows are empty again")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM extraction_log").fetchone()[0],
            result["skipped"], "provenance removed for reverted rows only")


if __name__ == "__main__":
    unittest.main(verbosity=2)
