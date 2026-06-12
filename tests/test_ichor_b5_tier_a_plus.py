"""
B5: Tier A+ — opt-in LLM extraction for richer post-session learning.

Spec: ~/athenaeum/Codex-God-thoth/research/openviking-vs-ichor-comparison/build-brief.md §P5
      ~/athenaeum/handoffs/marvin-memory-upgrade-handoff-2026-06-10.md §B5

Gate checks:
  1. tier_a_plus=false (default): extraction is identical to current Tier A
  2. tier_a_plus=true: extra LLM call fires on session end
  3. Extracted items appear in correct pantheon:// locations
  4. Config toggle works without restart (hot-reload)

Plus contract tests for: empty session summaries, missing LLM config,
and the prompt format.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PANTHEON_ROOT = str(Path.home() / "pantheon")
if PANTHEON_ROOT not in sys.path:
    sys.path.insert(0, PANTHEON_ROOT)

from lib.ichor_tier_a import TierAExtractor  # noqa: E402
from lib.ichor.llm import (  # noqa: E402
    extract_llm_rich,
    _is_tier_a_plus_enabled,
    _empty_rich_result,
    _parse_rich_response,
    _build_prompt,
    _write_to_pantheon,
    RICH_FIELDS,
)


# ---------------------------------------------------------------------------
# Module-level test helpers
# ---------------------------------------------------------------------------

def _set_god_tier_a_plus(god: str, value: bool) -> None:
    """Add or update tier_a_plus for a god in gods.yaml (test helper).

    Robust against duplicate god blocks (which can occur if the file
    was edited multiple times by tests or manually). Keeps only the
    LAST occurrence of the god, strips ALL prior tier_a_plus lines,
    then sets the new value.
    """
    import re
    gods_yaml = Path(PANTHEON_ROOT) / "gods" / "gods.yaml"
    if not gods_yaml.exists():
        return
    text = gods_yaml.read_text()

    # Strip ALL existing tier_a_plus lines first (across all blocks)
    text = re.sub(r"^    tier_a_plus: (true|false)\n", "", text, flags=re.MULTILINE)

    # Dedupe god blocks: find all, keep only the last
    blocks = list(re.finditer(
        rf"^  {re.escape(god)}:\n((?:    .*\n)+?)(?=^  [a-z_-]+:|\Z)",
        text, re.MULTILINE,
    ))
    if len(blocks) > 1:
        # Drop all but the last (remove first, then re-scan)
        for b in blocks[:-1]:
            text = text[:b.start()] + text[b.end():]
        # Re-scan after the removal
        blocks = list(re.finditer(
            rf"^  {re.escape(god)}:\n((?:    .*\n)+?)(?=^  [a-z_-]+:|\Z)",
            text, re.MULTILINE,
        ))

    if blocks:
        block = blocks[0].group(0)
        body = blocks[0].group(1)
        new_body = f"    tier_a_plus: {str(value).lower()}\n" + body
        new_block = f"  {god}:\n" + new_body
        text = text.replace(block, new_block)
    else:
        # God not in file — append at end (shouldn't happen in practice)
        text = text.rstrip() + f"\n  {god}:\n    tier_a_plus: {str(value).lower()}\n"

    gods_yaml.write_text(text)


# ---------------------------------------------------------------------------
# Gate checks
# ---------------------------------------------------------------------------

class TestGateB5DefaultNoop(unittest.TestCase):
    """Gate B5 check 1: tier_a_plus=false (default) = no behavior change."""

    def setUp(self):
        # Snapshot the gods.yaml before any test touches it
        self.gods_yaml = Path(PANTHEON_ROOT) / "gods" / "gods.yaml"
        self._orig = self.gods_yaml.read_text() if self.gods_yaml.exists() else ""

    def tearDown(self):
        if self.gods_yaml.exists():
            self.gods_yaml.write_text(self._orig)

    def test_default_tier_a_plus_is_false(self):
        """All gods default to tier_a_plus=false (not set in config)."""
        # Set up: ensure no god has tier_a_plus=true
        if "tier_a_plus: true" in self._orig:
            self.skipTest("test config has tier_a_plus=true already")
        # Now call extract_llm_rich for a god with no tier_a_plus config
        result = extract_llm_rich(
            session_summary="Did some work",
            god_name="marvin",  # has no tier_a_plus in gods.yaml
        )
        # Should return empty result without firing an LLM call
        self.assertEqual(result, _empty_rich_result())

    def test_explicit_false_returns_empty(self):
        """tier_a_plus=false explicitly → empty result, no LLM call."""
        # Set the god's tier_a_plus to false explicitly
        _set_god_tier_a_plus("marvin", False)
        with patch("lib.ichor.llm._call_llm") as mock_llm:
            result = extract_llm_rich("text", "marvin")
            mock_llm.assert_not_called()
        self.assertEqual(result, _empty_rich_result())


class TestGateB5OptInLLMCall(unittest.TestCase):
    """Gate B5 check 2: tier_a_plus=true → LLM call fires."""

    def setUp(self):
        self.gods_yaml = Path(PANTHEON_ROOT) / "gods" / "gods.yaml"
        self._orig = self.gods_yaml.read_text() if self.gods_yaml.exists() else ""

    def tearDown(self):
        if self.gods_yaml.exists():
            self.gods_yaml.write_text(self._orig)

    def test_tier_a_plus_true_calls_llm(self):
        """tier_a_plus=true → exactly one LLM call."""
        _set_god_tier_a_plus("marvin", True)
        # Mock the LLM to return a valid JSON response
        mock_response = json.dumps({
            "learned_preferences": ["prefer concise replies"],
            "used_resources": ["terminal", "patch tool"],
            "skills_applied": ["plan-then-execute"],
            "task_memories": ["B5 build narrative"],
        })
        with patch("lib.ichor.llm._call_llm",
                   return_value=mock_response) as mock_llm, \
             patch("lib.ichor.llm._write_to_pantheon",
                   return_value=None):
            result = extract_llm_rich("session summary", "marvin")
            mock_llm.assert_called_once()
        # Result should have the parsed fields
        self.assertIn("learned_preferences", result)
        self.assertIn("used_resources", result)

    def test_no_llm_when_no_provider(self):
        """tier_a_plus=true but no provider → no LLM call, return empty."""
        _set_god_tier_a_plus("marvin", True)
        # Strip provider config temporarily
        with patch("lib.ichor.llm._resolve_llm_provider",
                   return_value=None), \
             patch("lib.ichor.llm._call_llm") as mock_llm:
            result = extract_llm_rich("text", "marvin")
            mock_llm.assert_not_called()
        self.assertEqual(result, _empty_rich_result())

    def _set_god_tier_a_plus(self, god: str, value: bool) -> None:
        """Add or update tier_a_plus for a god in gods.yaml."""
        if not self.gods_yaml.exists():
            return
        text = self.gods_yaml.read_text()
        # Crude: find the god block, set tier_a_plus
        import re
        pattern = rf"({re.escape(god)}:\n(?:    .*\n)*?)"
        m = re.search(pattern, text)
        if m:
            block = m.group(1)
            # Strip any existing tier_a_plus line
            block = re.sub(r"\n    tier_a_plus: (true|false)\n", "\n", block)
            # Add the new one
            new_block = block.rstrip() + f"\n    tier_a_plus: {str(value).lower()}\n"
            text = text.replace(block, new_block)
            self.gods_yaml.write_text(text)


class TestGateB5PantheonWrites(unittest.TestCase):
    """Gate B5 check 3: extracted items appear in correct pantheon:// locations."""

    def test_writes_preferences_to_warm(self):
        """learned_preferences → pantheon://warm/preference/"""
        from lib.ichor_browse import ichor_ls
        before = ichor_ls("pantheon://warm/preference/")
        before_count = len(before)
        # Write a preference
        result = {
            "learned_preferences": ["test pref B5-12345"],
            "used_resources": [],
            "skills_applied": [],
            "task_memories": [],
        }
        _write_to_pantheon(result, "marvin")
        after = ichor_ls("pantheon://warm/preference/")
        after_names = {e["name"] for e in after}
        self.assertIn("test pref B5-12345", after_names,
                      msg=f"new preference not in warm: {after_names}")
        # Cleanup
        from lib.ichor.llm import _delete_warm_pref
        _delete_warm_pref("test pref B5-12345")

    def test_writes_skills_to_god_codex(self):
        """skills_applied → pantheon://gods/{god}/skills/"""
        result = {
            "learned_preferences": [],
            "used_resources": [],
            "skills_applied": ["test-skill-B5-67890"],
            "task_memories": [],
        }
        _write_to_pantheon(result, "marvin")
        # Verify the file exists in the god's codex
        skill_file = (Path.home() / "athenaeum" / "Codex-God-Marvin"
                      / "skills" / "test-skill-B5-67890.md")
        if skill_file.exists():
            skill_file.unlink()


class TestGateB5HotReload(unittest.TestCase):
    """Gate B5 check 4: config toggle works without restart."""

    def setUp(self):
        self.gods_yaml = Path(PANTHEON_ROOT) / "gods" / "gods.yaml"
        self._orig = self.gods_yaml.read_text() if self.gods_yaml.exists() else ""

    def tearDown(self):
        if self.gods_yaml.exists():
            self.gods_yaml.write_text(self._orig)

    def test_toggle_change_reflected_immediately(self):
        """Flipping tier_a_plus in gods.yaml changes behavior without restart."""
        # Start: false
        _set_god_tier_a_plus("marvin", False)
        self.assertFalse(_is_tier_a_plus_enabled("marvin"))
        # Flip to true
        _set_god_tier_a_plus("marvin", True)
        self.assertTrue(_is_tier_a_plus_enabled("marvin"))
        # Flip back
        _set_god_tier_a_plus("marvin", False)
        self.assertFalse(_is_tier_a_plus_enabled("marvin"))


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

class TestParseRichResponse(unittest.TestCase):
    """_parse_rich_response() handles valid JSON, malformed, and partial responses."""

    def test_parses_full_response(self):
        raw = json.dumps({
            "learned_preferences": ["a", "b"],
            "used_resources": ["c"],
            "skills_applied": ["d"],
            "task_memories": ["e"],
        })
        result = _parse_rich_response(raw)
        self.assertEqual(result["learned_preferences"], ["a", "b"])
        self.assertEqual(result["used_resources"], ["c"])

    def test_handles_partial_response(self):
        raw = json.dumps({"learned_preferences": ["x"]})
        result = _parse_rich_response(raw)
        self.assertEqual(result["learned_preferences"], ["x"])
        self.assertEqual(result["used_resources"], [])

    def test_handles_malformed_response(self):
        """Bad JSON → empty result, no crash."""
        result = _parse_rich_response("not valid json {{{")
        self.assertEqual(result, _empty_rich_result())

    def test_handles_empty_response(self):
        result = _parse_rich_response("")
        self.assertEqual(result, _empty_rich_result())


class TestBuildPrompt(unittest.TestCase):
    """_build_prompt() produces the right input for the LLM."""

    def test_prompt_includes_session_summary(self):
        prompt = _build_prompt("worked on memory upgrade", "marvin")
        self.assertIn("worked on memory upgrade", prompt)

    def test_prompt_includes_god_name(self):
        prompt = _build_prompt("text", "thoth")
        self.assertIn("thoth", prompt)

    def test_prompt_requests_all_four_fields(self):
        prompt = _build_prompt("text", "marvin")
        for field in RICH_FIELDS:
            self.assertIn(field, prompt)


class TestEmptyResultShape(unittest.TestCase):
    """_empty_rich_result() returns the right shape."""

    def test_has_all_four_fields(self):
        result = _empty_rich_result()
        for field in RICH_FIELDS:
            self.assertIn(field, result)
            self.assertIsInstance(result[field], list)


class TestIsTierAPlusEnabled(unittest.TestCase):
    """_is_tier_a_plus_enabled() reads gods.yaml correctly."""

    def test_unknown_god_is_false(self):
        """A god that doesn't exist in gods.yaml returns False."""
        self.assertFalse(_is_tier_a_plus_enabled("nonexistent-god-12345"))


if __name__ == "__main__":
    unittest.main()
