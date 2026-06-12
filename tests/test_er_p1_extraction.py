"""
ER-P1: Entity-relationship graph backfill extraction — gate + contract tests.

Spec: ~/athenaeum/handoffs/marvin-build-list-2026-06-11.md §ER-P1
       ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md §Extraction

ER-P1 gate (per build list):
  [1] entity count > 0
  [2] no NULL names
  [3] ≥5 distinct entity types populated (real DB; ≥3 in synthetic)
  [4] links to warm_entities present

Plus L0 unit tests (regex patterns) and L1 unit tests (Levenshtein
clustering), all against isolated temp DBs.

Important: tests check the ACTUAL schema in
`lib.ichor.entities.schema` (entity_types.id is TEXT slug, no `name` col).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from lib.ichor.entities.extraction import (  # noqa: E402
    _levenshtein,
    backfill,
    backfill_stats,
    cluster_l1,
    extract_l0,
    link_to_warm,
)
from lib.ichor.entities.schema import (  # noqa: E402
    get_conn,
    migrate,
)


def _isolated_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db", prefix="er_p1_test_")
    os.close(fd)
    return Path(path)


def _seed_cold_events(conn, events: list[tuple[int, str]]) -> None:
    """Replicates the real 5-tier schema for the parts backfill() needs
    (cold_events.raw_text, warm_entities.id/name/category). The real
    warm_entities has category NOT NULL, so we always set it.
    """
    conn.executescript("""
        CREATE TABLE cold_events (
            id INTEGER PRIMARY KEY,
            raw_text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE warm_entities (
            id INTEGER PRIMARY KEY,
            category TEXT NOT NULL DEFAULT 'reference',
            name TEXT NOT NULL,
            value TEXT NOT NULL DEFAULT ''
        );
    """)
    conn.executemany(
        "INSERT INTO cold_events (id, raw_text) VALUES (?, ?)",
        events,
    )
    conn.commit()


# =======================================================================
# L0: regex extraction unit tests
# =======================================================================

class TestExtractL0_Email(unittest.TestCase):
    def test_finds_simple_email(self):
        hits = extract_l0("Contact alice@example.com for details")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["type"], "email")
        self.assertEqual(hits[0]["value"], "alice@example.com")

    def test_normalises_to_lowercase(self):
        hits = extract_l0("Write to BOB@Example.COM")
        self.assertEqual(hits[0]["value"], "bob@example.com")

    def test_ignores_at_sign_without_email(self):
        self.assertEqual(extract_l0("Use @ to mention someone"), [])

    def test_finds_email_at_start_and_end(self):
        hits = extract_l0("alice@a.io wrote: ... --bob@b.io")
        self.assertEqual([h["value"] for h in hits], ["alice@a.io", "bob@b.io"])


class TestExtractL0_Mention(unittest.TestCase):
    def test_finds_mention(self):
        hits = extract_l0("Thanks @anthropic for the release")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["value"], "@anthropic")
        self.assertEqual(hits[0]["type"], "mention")

    def test_ignores_email_at_sign(self):
        # The @ in emails is consumed by the email pattern; the mention
        # pattern uses a lookbehind to avoid double-matching.
        hits = extract_l0("Email alice@example.com please")
        mentions = [h for h in hits if h["type"] == "mention"]
        self.assertEqual(mentions, [])

    def test_caps_username_length(self):
        long_name = "@" + "a" * 40
        hits = extract_l0(f"Ping {long_name} later")
        self.assertEqual([h for h in hits if h["type"] == "mention"], [])


class TestExtractL0_URL(unittest.TestCase):
    def test_finds_http_url(self):
        hits = extract_l0("See https://github.com/anthropics for info")
        url_hits = [h for h in hits if h["type"] == "url"]
        self.assertEqual(len(url_hits), 1)
        self.assertEqual(url_hits[0]["value"], "https://github.com/anthropics")

    def test_strips_trailing_punctuation(self):
        hits = extract_l0("Visit https://anthropic.com.")
        url_hits = [h for h in hits if h["type"] == "url"]
        self.assertEqual(url_hits[0]["value"], "https://anthropic.com")


class TestExtractL0_GitHub(unittest.TestCase):
    def test_finds_github_com_org(self):
        hits = extract_l0("https://github.com/anthropics has stuff")
        gh = [h for h in hits if h["type"] in ("github_org", "github_repo")]
        self.assertEqual(gh[0]["value"], "anthropics")

    def test_finds_github_com_repo(self):
        hits = extract_l0("https://github.com/anthropics/anthropic-sdk-python")
        gh = [h for h in hits if h["type"] == "github_repo"]
        self.assertEqual(gh[0]["value"], "anthropics/anthropic-sdk-python")

    def test_finds_known_org_in_org_slash_repo(self):
        # RE_GITHUB_SHORT pattern: "anthropic/anthropic-sdk-python" with a known org
        hits = extract_l0("we ship with anthropic/anthropic-sdk-python daily")
        repos = [h for h in hits if h["type"] == "github_repo"]
        self.assertTrue(any(r["value"] == "anthropic/anthropic-sdk-python" for r in repos),
                        f"expected anthropic/anthropic-sdk-python in {repos}")

    def test_dedupes_github_org_and_path(self):
        # If both patterns match the same org, only one is returned
        text = "github.com/anthropics and anthropics-fans mention it"
        hits = extract_l0(text)
        orgs = [h for h in hits if h["type"] == "github_org"]
        names = [h["value"] for h in orgs]
        self.assertEqual(len(names), len(set(names)))


class TestExtractL0_Empty(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(extract_l0(""), [])

    def test_none(self):
        self.assertEqual(extract_l0(None), [])  # type: ignore[arg-type]


# =======================================================================
# L1: Levenshtein clustering unit tests
# =======================================================================

class TestLevenshtein(unittest.TestCase):
    def test_identical(self):
        self.assertEqual(_levenshtein("anthropic", "anthropic", 3), 0)

    def test_one_substitution_short(self):
        # Single char substitution
        self.assertEqual(_levenshtein("cat", "bat", 3), 1)

    def test_one_insertion(self):
        self.assertEqual(_levenshtein("anthropic", "anthropics", 3), 1)

    def test_one_deletion(self):
        self.assertEqual(_levenshtein("anthropics", "anthropic", 3), 1)

    def test_distance_exceeds_max(self):
        # 5 substitutions, max_dist=3 → returns 4 (max_dist+1)
        self.assertEqual(_levenshtein("abcdef", "ghijkl", 3), 4)

    def test_length_prefilter_short_circuits(self):
        # 95-char diff in length, way over max_dist=2
        self.assertEqual(_levenshtein("a" * 5, "b" * 100, 2), 3)


class TestClusterL1(unittest.TestCase):
    def test_clusters_typos(self):
        items = [
            {"type": "github_org", "value": "anthropic", "span": (0, 0), "source_event_id": 1},
            {"type": "github_org", "value": "anthropics", "span": (0, 0), "source_event_id": 2},
            {"type": "github_org", "value": "anthropicx", "span": (0, 0), "source_event_id": 3},
        ]
        clusters = cluster_l1(items, distance_threshold=2)
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]["type"], "github_org")
        self.assertEqual(clusters[0]["count"], 3)
        # canonical: longest name. "anthropicx" and "anthropics" tie at 10 chars;
        # "anthropicx" > "anthropics" lexicographically → canonical is "anthropicx"
        self.assertEqual(clusters[0]["canonical_value"], "anthropicx")
        self.assertEqual(set(clusters[0]["aliases"]), {"anthropic", "anthropics", "anthropicx"})

    def test_does_not_cluster_different_types(self):
        items = [
            {"type": "email", "value": "alice@example.com", "span": (0, 0), "source_event_id": 1},
            {"type": "mention", "value": "@example", "span": (0, 0), "source_event_id": 2},
        ]
        clusters = cluster_l1(items, distance_threshold=2)
        types = {c["type"] for c in clusters}
        self.assertEqual(types, {"email", "mention"})

    def test_separates_distinct_names(self):
        items = [
            {"type": "github_org", "value": "openai", "span": (0, 0), "source_event_id": 1},
            {"type": "github_org", "value": "anthropic", "span": (0, 0), "source_event_id": 2},
        ]
        clusters = cluster_l1(items, distance_threshold=2)
        self.assertEqual(len(clusters), 2)

    def test_tracks_source_events(self):
        items = [
            {"type": "email", "value": "a@x.com", "span": (0, 0), "source_event_id": 1},
            {"type": "email", "value": "a@x.com", "span": (0, 0), "source_event_id": 7},
            {"type": "email", "value": "b@x.com", "span": (0, 0), "source_event_id": 3},
        ]
        clusters = cluster_l1(items, distance_threshold=0)
        a_cluster = next(c for c in clusters if c["canonical_value"] == "a@x.com")
        self.assertEqual(sorted(a_cluster["sources"]), [1, 7])

    def test_empty_input(self):
        self.assertEqual(cluster_l1([]), [])


# =======================================================================
# Linker to warm_entities
# =======================================================================

class TestLinkToWarm(unittest.TestCase):
    def test_finds_exact_match(self):
        cluster = {"canonical_value": "anthropic", "aliases": []}
        warm = [(1, "anthropic"), (2, "openai")]
        self.assertEqual(link_to_warm(cluster, warm), [1])

    def test_finds_typo_match(self):
        cluster = {"canonical_value": "anthropic", "aliases": []}
        warm = [(1, "anthropics"), (2, "openai")]
        self.assertEqual(link_to_warm(cluster, warm, distance_threshold=2), [1])

    def test_no_match_when_too_far(self):
        cluster = {"canonical_value": "anthropic", "aliases": []}
        warm = [(1, "openai"), (2, "google")]
        self.assertEqual(link_to_warm(cluster, warm, distance_threshold=2), [])

    def test_returns_sorted_unique(self):
        cluster = {"canonical_value": "anthropic", "aliases": ["anthropic-sdk"]}
        warm = [(5, "anthropic"), (2, "anthropic"), (1, "anthropic-sdk"), (3, "openai")]
        result = link_to_warm(cluster, warm, distance_threshold=0)
        self.assertEqual(result, [1, 2, 5])


# =======================================================================
# End-to-end backfill against isolated DB
# =======================================================================

class TestBackfillIntegration(unittest.TestCase):
    """Full backfill() against a temp DB with seeded cold_events + warm_entities."""

    def setUp(self):
        self.db_path = _isolated_db()
        from lib.ichor.entities import schema as _schema
        self._schema_db = _schema.DB_PATH
        _schema.DB_PATH = self.db_path

        conn = get_conn()
        migrate()
        _seed_cold_events(conn, [
            (1, "Contact alice@anthropic.com or check https://anthropic.com for docs"),
            (2, "We use anthropic-sdk-python in production, see github.com/anthropics/anthropic-sdk-python"),
            (3, "Also check openai/openai-python for comparison"),
            (4, "Bob writes: 'I love @anthropic, they are doing great work'"),
            (5, "Pure prose with no entities, just a long block of text " * 20),
        ])
        conn.executemany(
            "INSERT INTO warm_entities (category, name, value) VALUES (?, ?, ?)",
            [
                ("reference", "anthropic", "ref to anthropic company"),
                ("reference", "anthropic-sdk-python", "anthropic sdk memory"),
                ("reference", "openai", "ref to openai"),
            ],
        )
        conn.commit()
        conn.close()

    def tearDown(self):
        from lib.ichor.entities import schema as _schema
        _schema.DB_PATH = self._schema_db
        if self.db_path.exists():
            self.db_path.unlink()

    def test_backfill_populates_entity_types(self):
        conn = get_conn()
        result = backfill(conn)
        conn.close()
        self.assertGreater(result["clusters_after_l1"], 0)
        conn = get_conn()
        n_types = conn.execute("SELECT COUNT(*) FROM entity_types").fetchone()[0]
        conn.close()
        self.assertGreater(n_types, 0)

    def test_backfill_gate_1_entity_count_gt_zero(self):
        conn = get_conn()
        backfill(conn)
        stats = backfill_stats(conn)
        conn.close()
        self.assertGreater(stats["entities_count"], 0, "Gate 1 failed: no entities")

    def test_backfill_gate_2_no_null_names(self):
        conn = get_conn()
        backfill(conn)
        nulls = conn.execute("SELECT COUNT(*) FROM entities WHERE name IS NULL OR name = ''").fetchone()[0]
        conn.close()
        self.assertEqual(nulls, 0, "Gate 2 failed: NULL/empty names present")

    def test_backfill_gate_3_at_least_3_types_synthetic(self):
        conn = get_conn()
        backfill(conn)
        stats = backfill_stats(conn)
        conn.close()
        # Synthetic dataset has at least 3 types: email, url, github_repo (+ maybe org)
        self.assertGreaterEqual(stats["distinct_entity_types_used"], 3,
                               f"Only {stats['distinct_entity_types_used']} types in synthetic data")

    def test_backfill_gate_4_warm_entity_links(self):
        conn = get_conn()
        backfill(conn)
        stats = backfill_stats(conn)
        conn.close()
        self.assertGreater(stats["entities_with_warm_link"], 0,
                          "Gate 4 failed: no warm entity links")

    def test_backfill_is_idempotent(self):
        conn = get_conn()
        r1 = backfill(conn)
        conn.close()
        conn = get_conn()
        r2 = backfill(conn)
        conn.close()
        # Second run: no new entities, all logs dedup
        self.assertEqual(r2["entities_inserted"], 0)
        self.assertEqual(r2["extraction_logs_inserted"], 0)
        # Same final cluster count
        self.assertEqual(r1["clusters_after_l1"], r2["clusters_after_l1"])

    def test_backfill_stats_keys(self):
        conn = get_conn()
        backfill(conn)
        stats = backfill_stats(conn)
        conn.close()
        for key in ("entity_types_count", "entities_count", "relationship_types_count",
                    "relationships_count", "entity_facts_count", "extraction_log_count",
                    "distinct_entity_types_used", "entities_with_warm_link", "total_warm_links"):
            self.assertIn(key, stats, f"Missing key: {key}")


# =======================================================================
# Real-DB gate verification (skip if real DB not present)
# =======================================================================

REAL_DB = Path("/home/konan/.hermes/ichor.db")


@unittest.skipUnless(REAL_DB.exists(), "Real ichor.db not present")
class TestBackfillAgainstRealDB(unittest.TestCase):
    """Read-only gate verification on the real ichor.db.

    These tests do NOT re-run backfill() — that takes ~50s for the full
    7K-event corpus and would blow up the test suite. Instead they
    verify that the real DB has the post-backfill state from previous
    runs. Use `python3 -m lib.ichor.entities.extraction` for a one-shot
    full backfill; the stats key 'entities_count' is the gate check.
    """

    def setUp(self):
        # Ensure entity-graph tables exist. migrate() is idempotent.
        migrate()

    def test_real_db_gate_1_entity_count_gt_zero(self):
        stats = backfill_stats(get_conn())
        self.assertGreater(stats["entities_count"], 0,
                          f"Gate 1 failed on real DB: {stats}")

    def test_real_db_gate_2_no_null_names(self):
        conn = get_conn()
        nulls = conn.execute("SELECT COUNT(*) FROM entities WHERE name IS NULL OR name = ''").fetchone()[0]
        conn.close()
        self.assertEqual(nulls, 0, "Gate 2 failed: NULL/empty names in real DB")

    def test_real_db_gate_3_at_least_5_types(self):
        stats = backfill_stats(get_conn())
        self.assertGreaterEqual(stats["distinct_entity_types_used"], 5,
                               f"Gate 3 failed on real DB: only {stats['distinct_entity_types_used']} types")

    def test_real_db_gate_4_warm_entity_links(self):
        stats = backfill_stats(get_conn())
        self.assertGreater(stats["entities_with_warm_link"], 0,
                          f"Gate 4 failed on real DB: {stats}")


if __name__ == "__main__":
    unittest.main()
