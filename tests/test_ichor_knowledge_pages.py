"""Knowledge page projection contract tests (Phase 8)."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor_db import IchorDB  # noqa: E402
from lib.ichor_knowledge_pages import (  # noqa: E402
    EXCLUDED_CATEGORIES,
    KnowledgePageStore,
    build_pages_from_observations,
)


def test_knowledge_page_versioning_and_strict_tag_search(tmp_path) -> None:
    db_path = str(tmp_path / "ichor.db")
    IchorDB(db_path=db_path).connect().close()
    store = KnowledgePageStore(db_path=db_path)

    first = store.upsert_page(
        key="routing", question="How does routing work?",
        scope_tags=["user:konan", "scope:pantheon"],
        content_md="# Routing\n\nEvent driven.", source_observation_ids=[1],
    )
    assert first["version"] == 1

    second = store.upsert_page(
        key="routing", question="How does routing work?",
        scope_tags=["user:konan", "scope:pantheon"],
        content_md="# Routing\n\nEvent driven, no polling.", source_observation_ids=[1, 2],
    )
    assert second["version"] == 2

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM ichor_knowledge_page_versions").fetchone()[0]
    assert count == 1

    assert store.search_pages("polling", tags=["user:konan"], tags_match="any_strict")
    assert not store.search_pages("polling", tags=["user:other"], tags_match="any_strict")


# ── Projection builder (Phase 8 writer) ─────────────────────────────────
#
# Before 2026-09-21 the only caller of `upsert_page` in the whole repo was this
# test file, so the highest-priority retrieval lane was a wired reader over a
# permanently empty table -- indistinguishable from a healthy empty lane, which
# is why it survived an audit. These tests pin the writer AND the contract that
# makes its rows readable.


def _seed_observations(db_path: str, rows: list[tuple[str, str, int]]) -> None:
    """Insert (category, content, proof_count) observations into a fresh DB."""
    with sqlite3.connect(db_path) as conn:
        for category, content, proof in rows:
            conn.execute(
                "INSERT INTO ichor_observations "
                "(subject, predicate, object, content, category, confidence, "
                " proof_count, first_seen, last_seen, evidence_span_days, trend, status) "
                "VALUES (?, 'status', 'ok', ?, ?, 0.9, ?, "
                " '2026-09-01T00:00:00Z', '2026-09-20T00:00:00Z', 1.0, 'stable', 'active')",
                (f"subject-{category}-{proof}", content, category, proof),
            )
        conn.commit()


def _fresh_db(tmp_path) -> str:
    db_path = str(tmp_path / "ichor.db")
    IchorDB(db_path=db_path).connect().close()
    return db_path


def test_builder_projects_categories_into_pages(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("commitment", "ship the android app to the store", 7),
        ("commitment", "publish the blog post this week", 5),
        ("commitment", "call the vendor about the invoice", 3),
        ("decision", "use sqlite for the state store", 4),
        ("decision", "defer the vector lane for now", 4),
        ("decision", "single-owner maintenance was chosen", 4),
    ])
    report = build_pages_from_observations(db_path)
    assert report["pages_written"] == 2
    assert not report["dry_run"]

    store = KnowledgePageStore(db_path=db_path)
    page = store.get_page("category:commitment")
    assert page is not None
    assert page["version"] == 1
    assert page["question"] == "What commitments are outstanding?"
    assert page["scope_tags"] == [], "a tagged global page is unreadable by the ladder"
    assert len(page["source_observation_ids"]) == 3
    assert "ship the android app" in page["content_md"]
    assert "observation:" in page["content_md"], "evidence must be cited"


def test_builder_is_idempotent(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("fact", "the first stable fact sentence", 3),
        ("fact", "the second stable fact sentence", 3),
        ("fact", "the third stable fact sentence", 3),
    ])
    first = build_pages_from_observations(db_path)
    second = build_pages_from_observations(db_path)
    assert first["pages_written"] == second["pages_written"] == 1
    assert second["pages"][0]["version"] == 1, "unchanged content must not version-bump"
    with sqlite3.connect(db_path) as conn:
        versions = conn.execute(
            "SELECT COUNT(*) FROM ichor_knowledge_page_versions"
        ).fetchone()[0]
    assert versions == 0


def test_builder_skips_machine_categories_and_thin_groups(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("health_check", "health:god:hermes status ok.", 2),
        ("health_check", "health:god:thoth status ok.", 2),
        ("health_check", "health:god:marvin status ok.", 2),
        ("digest_entry", "digest line", 2),
        ("digest_entry", "digest line 2", 2),
        ("digest_entry", "digest line 3", 2),
        ("insight", "only one observation here", 2),
    ])
    report = build_pages_from_observations(db_path)
    assert report["pages_written"] == 0
    store = KnowledgePageStore(db_path=db_path)
    assert store.get_page("category:health_check") is None
    assert store.get_page("category:digest_entry") is None
    assert "health_check" in EXCLUDED_CATEGORIES


def test_untagged_page_is_readable_by_the_ladder_default_call(tmp_path) -> None:
    """The anti-trap contract.

    The ladder calls `search_pages(query, tags=[], tags_match="any")`. Under
    `any` mode a page WITH tags fails `any(t in page_set) or not page_set` and is
    filtered out -- so a "helpful" scope tag would have made every written page
    invisible to its only reader. This asserts the page survives that exact call.
    """
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("commitment", "ship the android app to the store", 7),
        ("commitment", "publish the blog post this week", 5),
        ("commitment", "call the vendor about the invoice", 3),
    ])
    build_pages_from_observations(db_path)
    store = KnowledgePageStore(db_path=db_path)

    for tags_match in ("any", "any_strict", "all", "all_strict"):
        hits = store.search_pages(
            "what commitments are outstanding?", tags=[], tags_match=tags_match
        )
        assert hits, f"page invisible to the ladder under tags_match={tags_match!r}"


def test_builder_never_writes_back_to_observations(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("blocker", "waiting on vendor", 9),
        ("blocker", "blocked on review", 8),
        ("blocker", "blocked on keys", 7),
    ])
    with sqlite3.connect(db_path) as conn:
        before = conn.execute(
            "SELECT id, content, status FROM ichor_observations ORDER BY id"
        ).fetchall()
    build_pages_from_observations(db_path)
    with sqlite3.connect(db_path) as conn:
        after = conn.execute(
            "SELECT id, content, status FROM ichor_observations ORDER BY id"
        ).fetchall()
    assert before == after, "the projection mutated its source rows"


def test_dry_run_writes_nothing(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("insight", "one sentence about the cache", 3),
        ("insight", "two sentences about the cache", 3),
        ("insight", "three sentences about the cache", 3),
    ])
    report = build_pages_from_observations(db_path, dry_run=True)
    assert report["dry_run"] is True
    assert "content_md" in report["pages"][0]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM ichor_knowledge_pages").fetchone()[0] == 0


def test_quality_gate_keeps_rubble_out_of_the_projection(tmp_path) -> None:
    """The projection is the highest-priority lane: noise there is worse than empty.

    `ichor_observations.content` is template-rendered from raw turns, so it
    carries JSON, code fences, file paths and truncated quotes. A candidate must
    read like a sentence before it is allowed onto a page.
    """
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("insight", "the retry loop drops the last attempt", 5),
        ("insight", "a second real sentence about caching", 5),
        ("insight", "a third real sentence about latency", 5),
        # Noise: every one of these is a real shape found in the live store.
        ("insight", '{"required_commands": [], "missing": true}', 5),
        ("insight", "```python\nprint('x')\n```", 5),
        ("insight", "see https://example.com/docs for the details", 5),
        ("insight", "short", 5),
    ])
    build_pages_from_observations(db_path)
    content = KnowledgePageStore(db_path=db_path).get_page("category:insight")["content_md"]
    assert "the retry loop drops the last attempt" in content
    assert "required_commands" not in content, "JSON rubble reached the page"
    assert "print(" not in content, "code fence reached the page"
    assert "https://" not in content, "URL reached the page"


def test_category_is_skipped_when_the_gate_empties_it(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("preference", '{"a": 1}', 9),
        ("preference", '{"b": 2}', 9),
        ("preference", '{"c": 3}', 9),
    ])
    report = build_pages_from_observations(db_path)
    assert report["pages_written"] == 0
    assert report["skipped"][0]["reason"].startswith("below min_observations")
    assert KnowledgePageStore(db_path=db_path).get_page("category:preference") is None


def test_low_confidence_and_unproven_rows_are_excluded(tmp_path) -> None:
    db_path = _fresh_db(tmp_path)
    _seed_observations(db_path, [
        ("fact", "a solid proven sentence here", 5),
        ("fact", "another solid proven sentence", 5),
        ("fact", "a third solid proven sentence", 5),
        ("fact", "a fourth solid proven sentence", 5),
    ])
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE ichor_observations SET confidence = 0.4 WHERE content LIKE 'a solid%'"
        )
        conn.commit()
    build_pages_from_observations(db_path)
    content = KnowledgePageStore(db_path=db_path).get_page("category:fact")["content_md"]
    assert "a solid proven sentence here" not in content
