#!/usr/bin/env python3
"""Tests for `lib.ichor.llm._resolve_llm_provider` resolution order.

The last step (main `~/.hermes/config.yaml`) exists because pseudo-gods such as
"subconscious" are not in gods.yaml and have no profile directory; before it was
added the resolver returned None and every caller silently degraded to "no LLM
available" — the subconscious cluster summarizer returned "" on every tick.

Run directly (the hermes venv has no pytest):

    /home/konan/.hermes/hermes-agent/.venv/bin/python3 \
        /home/konan/pantheon/tests/test_ichor_llm_provider_fallback.py
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path("/home/konan/pantheon")
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from lib.ichor import llm  # noqa: E402

PROVIDERS = {
    "opencode-go": {"name": "opencode-go", "api": "https://opencode.ai/zen/go/v1",
                    "default_model": "deepseek-v4.1-flash"},
    "minimax": {"name": "minimax", "api": "https://api.minimax.io/v1",
                "default_model": "MiniMax-M3"},
}


class TestProviderResolution(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        (self.home / ".hermes").mkdir(parents=True)
        self.main_cfg = self.home / ".hermes" / "config.yaml"
        self.gods_yaml = self.home / "gods.yaml"
        self._patchers = [
            mock.patch.object(llm, "_HOME", self.home),
            mock.patch.object(llm, "_GODS_YAML", self.gods_yaml),
        ]
        for patcher in self._patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in self._patchers:
            patcher.stop()
        self._tmp.cleanup()

    def write_main_config(self, provider: str = "opencode-go") -> None:
        self.main_cfg.write_text(
            "model:\n"
            f"  provider: {provider}\n"
            "  default: deepseek-v4.1-flash\n"
            "providers:\n"
            + "".join(
                f"  {name}:\n    name: {name}\n    api: {cfg['api']}\n"
                f"    default_model: {cfg['default_model']}\n"
                for name, cfg in PROVIDERS.items()
            )
        )

    def write_gods_yaml(self, god: str, provider: str) -> None:
        self.gods_yaml.write_text(
            "gods:\n"
            f"  {god}:\n"
            f"    display_name: {god.title()}\n"
            f"    llm_provider: {provider}\n"
        )

    def write_profile(self, god: str, provider: str) -> None:
        profile = self.home / ".hermes" / "profiles" / god
        profile.mkdir(parents=True)
        (profile / "config.yaml").write_text(
            f"model:\n  provider: {provider}\n  default: whatever\n"
        )

    # -- the regression that motivated the fix ------------------------------
    def test_pseudo_god_falls_back_to_main_config(self) -> None:
        self.write_main_config("opencode-go")
        resolved = llm._resolve_llm_provider("subconscious")
        self.assertTrue(resolved, "pseudo-god must resolve via the main config")
        self.assertEqual(resolved["name"], "opencode-go")
        self.assertEqual(resolved["default_model"], "deepseek-v4.1-flash")

    def test_god_without_profile_falls_back_to_main_config(self) -> None:
        self.write_main_config("minimax")
        resolved = llm._resolve_llm_provider("some-god-with-no-profile")
        self.assertEqual((resolved or {}).get("name"), "minimax")

    # -- precedence ---------------------------------------------------------
    def test_gods_yaml_entry_wins(self) -> None:
        self.write_main_config("opencode-go")
        self.write_gods_yaml("thoth", "minimax")
        resolved = llm._resolve_llm_provider("thoth")
        self.assertEqual((resolved or {}).get("name"), "minimax")

    def test_profile_wins_over_main_config(self) -> None:
        self.write_main_config("opencode-go")
        self.write_profile("marvin", "minimax")
        resolved = llm._resolve_llm_provider("marvin")
        self.assertEqual((resolved or {}).get("name"), "minimax")

    # -- degraded states stay None, not a bogus config ----------------------
    def test_no_config_anywhere_returns_none(self) -> None:
        self.assertIsNone(llm._resolve_llm_provider("subconscious"))

    def test_unconfigured_provider_name_returns_none(self) -> None:
        self.write_main_config("does-not-exist")
        self.assertIsNone(llm._resolve_llm_provider("subconscious"))

    def test_malformed_config_returns_none(self) -> None:
        self.main_cfg.write_text("model: [this is not a mapping\n")
        self.assertIsNone(llm._resolve_llm_provider("subconscious"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
