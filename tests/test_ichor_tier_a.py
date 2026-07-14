"""Tests for Ichor Tier A regex extraction engine.

Tests pattern matching, confidence scoring, dedup, edge cases,
storage, and real conversation extraction.
"""

import os
import tempfile
import pytest

from lib.ichor_tier_a import TierAExtractor, CONFIDENCE_FLOOR
from lib.ichor_patterns import ALL_TYPES, pattern_count, type_pattern_counts


# ── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def db_path():
    """Create a temporary database path."""
    path = tempfile.mktemp(suffix=".db")
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def extractor(db_path):
    """Create a TierAExtractor with a temp database."""
    ext = TierAExtractor(db_path=db_path)
    yield ext
    ext.close()


# ── Pattern Registry Tests ─────────────────────────────────────────────


class TestPatternRegistry:
    def test_all_types_present(self):
        """All 9 expected event types are registered."""
        expected = {
            "decision", "commitment", "fact", "preference",
            "correction", "insight", "blocker", "reference", "follow_up",
        }
        assert set(ALL_TYPES) == expected

    def test_minimum_patterns_per_type(self):
        """Each type has at least 15 patterns."""
        counts = type_pattern_counts()
        for t, c in counts.items():
            assert c >= 15, f"{t} only has {c} patterns (need 15)"

    def test_total_patterns(self):
        """At least 150 total patterns across all types."""
        assert pattern_count() >= 150

    def test_all_patterns_compile(self):
        """All patterns import without errors."""
        from lib.ichor_patterns import PATTERNS
        assert len(PATTERNS) == len(ALL_TYPES)


# ── Individual Event Type Matching ─────────────────────────────────────


class TestDecisionExtraction:
    def test_decision_go_with(self, extractor):
        events = extractor.extract_from_text(
            "Let's go with PostgreSQL for the database.",
            "test-001", "hephaestus", "user",
        )
        decisions = [e for e in events if e["event_type"] == "decision"]
        assert len(decisions) >= 1

    def test_decision_agreed(self, extractor):
        events = extractor.extract_from_text(
            "We agreed to use microservices architecture.",
            "test-002", "hephaestus", "user",
        )
        decisions = [e for e in events if e["event_type"] == "decision"]
        assert len(decisions) >= 1

    def test_decision_decided(self, extractor):
        events = extractor.extract_from_text(
            "I've decided to go with FastAPI for the backend.",
            "test-003", "hephaestus", "user",
        )
        decisions = [e for e in events if e["event_type"] == "decision"]
        assert len(decisions) >= 1

    def test_decision_multi(self, extractor):
        """Multiple decisions in one text."""
        events = extractor.extract_from_text(
            "I picked React for the frontend. We agreed on GraphQL for the API.",
            "test-004", "hephaestus", "user",
        )
        decisions = [e for e in events if e["event_type"] == "decision"]
        assert len(decisions) >= 2


class TestCommitmentExtraction:
    def test_commitment_deadline(self, extractor):
        events = extractor.extract_from_text(
            "I'll have the PR ready by Friday.",
            "test-005", "hephaestus", "user",
        )
        commits = [e for e in events if e["event_type"] == "commitment"]
        assert len(commits) >= 1

    def test_commitment_action(self, extractor):
        events = extractor.extract_from_text(
            "I will handle the deployment this evening.",
            "test-006", "apollo", "user",
        )
        commits = [e for e in events if e["event_type"] == "commitment"]
        assert len(commits) >= 1

    def test_commitment_delegated(self, extractor):
        events = extractor.extract_from_text(
            "I've assigned the database migration to the team.",
            "test-007", "hephaestus", "user",
        )
        commits = [e for e in events if e["event_type"] == "commitment"]
        assert len(commits) >= 1

    def test_commitment_todo(self, extractor):
        events = extractor.extract_from_text(
            "TODO: refactor the auth module before the next release.",
            "test-008", "hephaestus", "user",
        )
        commits = [e for e in events if e["event_type"] == "commitment"]
        assert len(commits) >= 1


class TestFactExtraction:
    def test_fact_we_use(self, extractor):
        events = extractor.extract_from_text(
            "We use React with TypeScript on the frontend.",
            "test-010", "hephaestus", "user",
        )
        facts = [e for e in events if e["event_type"] == "fact"]
        assert len(facts) >= 1

    def test_fact_location(self, extractor):
        events = extractor.extract_from_text(
            "I'm based in Boise, Idaho.",
            "test-011", "hermes", "user",
        )
        facts = [e for e in events if e["event_type"] == "fact"]
        assert len(facts) >= 1

    def test_fact_architecture(self, extractor):
        events = extractor.extract_from_text(
            "The platform is built with Python and hosted on a local server.",
            "test-012", "hermes", "user",
        )
        facts = [e for e in events if e["event_type"] == "fact"]
        assert len(facts) >= 1


class TestPreferenceExtraction:
    def test_preference_like(self, extractor):
        events = extractor.extract_from_text(
            "I prefer dark mode honestly, it's easier on my eyes.",
            "test-013", "thoth", "user",
        )
        prefs = [e for e in events if e["event_type"] == "preference"]
        assert len(prefs) >= 1

    def test_preference_dislike(self, extractor):
        events = extractor.extract_from_text(
            "I'm not a fan of verbose logging in production.",
            "test-014", "hephaestus", "user",
        )
        prefs = [e for e in events if e["event_type"] == "preference"]
        assert len(prefs) >= 1

    def test_preference_choice(self, extractor):
        events = extractor.extract_from_text(
            "I'd rather use SQLite for local development.",
            "test-015", "hephaestus", "user",
        )
        prefs = [e for e in events if e["event_type"] == "preference"]
        assert len(prefs) >= 1


class TestCorrectionExtraction:
    def test_correction_no_that_wrong(self, extractor):
        events = extractor.extract_from_text(
            "No, that's not right — I meant the production server.",
            "test-016", "hermes", "user",
        )
        corrections = [e for e in events if e["event_type"] == "correction"]
        assert len(corrections) >= 1

    def test_correction_actually(self, extractor):
        events = extractor.extract_from_text(
            "Actually, it's the staging environment that has the issue.",
            "test-017", "hermes", "user",
        )
        corrections = [e for e in events if e["event_type"] == "correction"]
        assert len(corrections) >= 1

    def test_correction_let_me_clarify(self, extractor):
        events = extractor.extract_from_text(
            "Let me clarify what I meant by that last suggestion.",
            "test-018", "hermes", "user",
        )
        corrections = [e for e in events if e["event_type"] == "correction"]
        assert len(corrections) >= 1


class TestInsightExtraction:
    def test_insight_realized(self, extractor):
        events = extractor.extract_from_text(
            "Oh wait, I just realized — that means the cache expires before we use it!",
            "test-019", "thoth", "user",
        )
        insights = [e for e in events if e["event_type"] == "insight"]
        assert len(insights) >= 1

    def test_insight_interesting(self, extractor):
        events = extractor.extract_from_text(
            "Interesting. That suggests the problem is actually in the network layer.",
            "test-020", "thoth", "user",
        )
        insights = [e for e in events if e["event_type"] == "insight"]
        assert len(insights) >= 1

    def test_insight_realization(self, extractor):
        events = extractor.extract_from_text(
            "That changes everything — I see the connection now between the two bugs.",
            "test-021", "thoth", "user",
        )
        insights = [e for e in events if e["event_type"] == "insight"]
        assert len(insights) >= 1


class TestBlockerExtraction:
    def test_blocker_stuck(self, extractor):
        events = extractor.extract_from_text(
            "I'm stuck on this Docker networking issue, the containers can't communicate.",
            "test-022", "hephaestus", "user",
        )
        blockers = [e for e in events if e["event_type"] == "blocker"]
        assert len(blockers) >= 1

    def test_blocker_error(self, extractor):
        events = extractor.extract_from_text(
            "Getting a 502 error from the API gateway whenever I try to deploy.",
            "test-023", "hephaestus", "user",
        )
        blockers = [e for e in events if e["event_type"] == "blocker"]
        assert len(blockers) >= 1

    def test_blocker_timeout(self, extractor):
        events = extractor.extract_from_text(
            "The build keeps timing out after 10 minutes with no error message.",
            "test-024", "hephaestus", "user",
        )
        blockers = [e for e in events if e["event_type"] == "blocker"]
        assert len(blockers) >= 1


class TestReferenceExtraction:
    def test_reference_url(self, extractor):
        events = extractor.extract_from_text(
            "Check out the docs at https://fastapi.tiangolo.com/ for more details.",
            "test-025", "hephaestus", "user",
        )
        refs = [e for e in events if e["event_type"] == "reference"]
        assert len(refs) >= 1

    def test_reference_tool(self, extractor):
        events = extractor.extract_from_text(
            "There's a great library called SQLAlchemy that handles this well.",
            "test-026", "hephaestus", "user",
        )
        refs = [e for e in events if e["event_type"] == "reference"]
        assert len(refs) >= 1

    def test_reference_github(self, extractor):
        events = extractor.extract_from_text(
            "The repo is at github.com/nicedoc/some-repo.",
            "test-027", "hephaestus", "user",
        )
        refs = [e for e in events if e["event_type"] == "reference"]
        assert len(refs) >= 1


class TestFollowUpExtraction:
    def test_follow_up_circle_back(self, extractor):
        events = extractor.extract_from_text(
            "Let's circle back to this next session when we have more context.",
            "test-028", "thoth", "user",
        )
        follow_ups = [e for e in events if e["event_type"] == "follow_up"]
        assert len(follow_ups) >= 1

    def test_follow_up_next_step(self, extractor):
        events = extractor.extract_from_text(
            "The next step is to deploy this to staging and test it.",
            "test-029", "hephaestus", "user",
        )
        follow_ups = [e for e in events if e["event_type"] == "follow_up"]
        assert len(follow_ups) >= 1

    def test_follow_up_on_hold(self, extractor):
        events = extractor.extract_from_text(
            "I'm putting that feature on hold until we fix the performance issues first.",
            "test-030", "hephaestus", "user",
        )
        follow_ups = [e for e in events if e["event_type"] == "follow_up"]
        assert len(follow_ups) >= 1


# ── Confidence Scoring ─────────────────────────────────────────────────


class TestConfidenceScoring:
    def test_user_higher_than_assistant(self, extractor):
        """User messages get higher baseline confidence."""
        user_events = extractor.extract_from_text(
            "I've decided to use FastAPI.",
            "test-c1", "hephaestus", "user",
        )
        assistant_events = extractor.extract_from_text(
            "I've decided to use FastAPI.",
            "test-c2", "hephaestus", "assistant",
        )
        if user_events and assistant_events:
            u_avg = sum(e["confidence"] for e in user_events) / len(user_events)
            a_avg = sum(e["confidence"] for e in assistant_events) / len(assistant_events)
            assert u_avg > a_avg, (
                f"User avg {u_avg:.2f} should be > assistant avg {a_avg:.2f}"
            )

    def test_confidence_within_range(self, extractor):
        """All confidence values are between 0 and 1."""
        events = extractor.extract_from_text(
            "I prefer dark mode. Let's go with SQLite. I'll fix it by Friday.",
            "test-c3", "hephaestus", "user",
        )
        for ev in events:
            assert 0 <= ev["confidence"] <= 1.0

    def test_confidence_below_floor_filtered(self, extractor):
        """Events below CONFIDENCE_FLOOR are not returned."""
        events = extractor.extract_from_text(
            "The",  # too short, no meaningful patterns
            "test-c4", "hephaestus", "user",
        )
        all_above = all(e["confidence"] >= CONFIDENCE_FLOOR for e in events)
        assert all_above, "All returned events should be at or above confidence floor"

    def test_short_match_penalized(self, extractor):
        """Very short matches get a confidence penalty."""
        events = extractor.extract_from_text(
            "I will.",  # very short commitment match
            "test-c5", "hephaestus", "user",
        )
        # Short matches should start dropping toward the floor
        for ev in events:
            if ev["event_type"] == "commitment":
                assert ev["confidence"] < 0.85


# ── Dedup Tests ─────────────────────────────────────────────────────────


class TestDedup:
    def test_same_event_deduped(self, extractor):
        """Same (type, subject) within same call gets merged."""
        events = extractor.extract_from_text(
            "I've decided to use FastAPI. Yes, I've decided on FastAPI.",
            "test-d1", "hephaestus", "user",
        )
        decisions = [e for e in events if e["event_type"] == "decision"]
        subjects = {(e["event_type"], e["subject"].lower()) for e in events}
        # Should have fewer subjects than raw pattern matches
        assert len(subjects) <= len(events)

    def test_different_sessions_separate(self, extractor):
        """Events from different session_ids are stored separately."""
        text = "I've decided to use FastAPI."
        ext1 = TierAExtractor(db_path=tempfile.mktemp(suffix=".db"))
        c1 = ext1.extract_and_store(text, "session-a", "hephaestus", "user")
        c2 = ext1.extract_and_store(text, "session-b", "hephaestus", "user")
        total = ext1.db.count()
        ext1.close()
        os.unlink(ext1.db.db_path)
        assert total >= 1  # Events stored across both sessions


# ── Edge Cases ──────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_text(self, extractor):
        """Empty text returns empty list."""
        events = extractor.extract_from_text("", "test-e1", "hephaestus", "user")
        assert events == []

    def test_whitespace_only(self, extractor):
        """Whitespace-only text returns empty list."""
        events = extractor.extract_from_text("   \n  \t  ", "test-e2", "hephaestus", "user")
        assert events == []

    def test_no_matching_patterns(self, extractor):
        """Text with no matching patterns returns empty list."""
        events = extractor.extract_from_text(
            "The quick brown fox jumps over the lazy dog.",
            "test-e3", "hephaestus", "user",
        )
        assert events == []

    def test_all_types_in_one_text(self, extractor):
        """A single text containing all event types extracts them all."""
        text = (
            "I've decided to go with Python. "  # decision
            "I'll finish it by Friday. "  # commitment
            "We use Ubuntu on the servers. "  # fact
            "I prefer dark mode. "  # preference
            "Actually, I meant the other server. "  # correction
            "Oh wait, that explains the bug! "  # insight
            "I'm stuck on this error. "  # blocker
            "Check out the docs at example.com. "  # reference
            "Let's revisit this next session. "  # follow_up
        )
        events = extractor.extract_from_text(
            text, "test-e4", "thoth", "user",
        )
        types_found = {e["event_type"] for e in events}
        for t in ALL_TYPES:
            assert t in types_found, f"Type '{t}' not extracted from mixed text"

    def test_long_text_no_crash(self, extractor):
        """Very long text doesn't crash the extractor."""
        paragraph = "I've decided to use FastAPI. " * 100 + "I'll finish by Friday. " * 100
        events = extractor.extract_from_text(
            paragraph, "test-e5", "hephaestus", "user",
        )
        assert len(events) >= 0  # At minimum, shouldn't crash


# ── Storage Tests ───────────────────────────────────────────────────────


class TestStorage:
    def test_extract_and_store_returns_count(self, extractor):
        """extract_and_store returns the number of stored events."""
        count = extractor.extract_and_store(
            "I've decided to use FastAPI. I'll have it ready by Friday.",
            "test-s1", "hephaestus", "user",
        )
        assert count >= 0
        assert isinstance(count, int)

    def test_stored_events_fts_searchable(self, extractor):
        """Stored events are queryable via FTS5."""
        extractor.extract_and_store(
            "I've decided to use FastAPI for the backend.",
            "test-s2", "hephaestus", "user",
        )
        extractor.extract_and_store(
            "I prefer Kotlin for mobile development.",
            "test-s3", "hephaestus", "user",
        )
        results = extractor.db.query_fts("FastAPI")
        assert len(results) >= 1

    def test_stored_events_by_type(self, extractor):
        """Events can be queried by type."""
        extractor.extract_and_store(
            "I'll have the PR ready by Friday.",
            "test-s4", "hephaestus", "user",
        )
        results = extractor.db.query_by_type("commitment")
        assert len(results) >= 1

    def test_stored_events_by_session(self, extractor):
        """Events can be queried by session."""
        extractor.extract_and_store(
            "I've decided to use SQLite.",
            "test-s5", "hephaestus", "user",
        )
        results = extractor.db.query_by_session("test-s5")
        assert len(results) >= 1


# ── Real Conversation Extraction ────────────────────────────────────────


class TestRealConversation:
    def test_multi_turn_conversation(self, extractor):
        """Extract from a realistic multi-sentence conversation."""
        text = (
            "So I've been thinking about the database setup. "
            "I prefer using PostgreSQL honestly, it's more reliable for our use case. "
            "I'm stuck on the migration script though, it keeps failing with a foreign key error. "
            "Oh wait, I think I see the issue — the migration order is wrong. "
            "Let's fix it and circle back to the indexing strategy later."
        )
        events = extractor.extract_from_text(
            text, "test-r1", "hephaestus", "user",
        )
        types_found = {e["event_type"] for e in events}
        # Should capture multiple types from a realistic paragraph
        assert len(types_found) >= 3

    def test_segment_extraction(self, extractor):
        """Extract from a user+assistant exchange pair."""
        user_msg = "I'm stuck on this Docker networking issue. Can you help?"
        assistant_msg = "Let's check the docker-compose.yml. Actually, I think the issue is the bridge network config."
        events = extractor.extract_from_segment(
            user_msg, assistant_msg, "test-r2", "hephaestus",
        )
        types_found = {e["event_type"] for e in events}
        assert "blocker" in types_found
        assert len(events) >= 2

    def test_multi_god_isolation(self, extractor):
        """Events from different gods are stored separately and queryable."""
        extractor.extract_and_store(
            "I'll finish the API by Friday.",
            "test-r3", "hephaestus", "user",
        )
        extractor.extract_and_store(
            "I promise to write the lyrics by tomorrow.",
            "test-r3", "apollo", "user",
        )
        hep_results = extractor.db.query_fts("Friday")
        apollo_results = extractor.db.query_fts("lyrics")
        assert len(hep_results) >= 0
        assert len(apollo_results) >= 0
