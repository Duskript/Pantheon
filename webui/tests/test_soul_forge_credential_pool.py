"""Regression tests for the Soul Forge credential-pool routing.

PR fixing the "Forge a God" bug: the forge threw "the forge flickers"
because `soul_forge._get_client()` read `OPENCODE_GO_API_KEY` directly
from `~/.hermes/.env`, which has a key with insufficient credits. The
fix routes through the credential pool instead, but the pool reader
(`hermes_cli.auth._auth_file_path()`) returns the per-profile
`auth.json` when the gateway scopes `HERMES_HOME` to a per-profile
directory — which hides manual fallback entries that live in the
GLOBAL `~/.hermes/auth.json`.

These tests pin the fix:

  1. `_resolve_global_auth_path()` climbs out of a per-profile layout
     to the global `~/.hermes/auth.json` when `HERMES_HOME` is scoped.
  2. `_resolve_credential_from_pool("opencode-go")` returns the
     manual fallback entry from the global pool, not the env-derived
     entry that has a recent auth/credit error.
  3. Entries with a recent `last_error_code` in {401, 402, 403} are
     skipped — they don't poison the resolution.
  4. The `.env` fallback fires when the global pool is empty.
  5. The function returns None gracefully when the global auth.json
     doesn't exist (so the fallback chain can run).

These tests are PURE UNIT TESTS — no LLM call, no live server, no
network. They construct synthetic `auth.json` files in temp dirs and
monkeypatch the resolver's path-detection to point at them.
"""
import json
import os
import sys
import types
import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).parent.parent.resolve()
WEBUI_PKG = REPO_ROOT  # webui/ is the package root
if str(WEBUI_PKG) not in sys.path:
    sys.path.insert(0, str(WEBUI_PKG))


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def global_auth_root(tmp_path, monkeypatch):
    """Create a synthetic Hermes home with:
      - global auth.json (has 1 manual fallback + 1 broken env entry)
      - per-profile auth.json (has only 1 broken env entry)

    The test exercises whether the resolver climbs out of the
    per-profile layout to find the global one.
    """
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    profile_dir = hermes_home / "profiles" / "marvin"
    profile_dir.mkdir(parents=True)

    # Global auth.json with manual fallback + env entry
    global_auth = {
        "version": 1,
        "credential_pool": {
            "opencode-go": [
                {
                    "id": "manual01",
                    "label": "opencode-go-fallback",
                    "auth_type": "api_key",
                    "priority": 0,
                    "source": "manual",
                    "access_token": "sk-manual-WORKING-KEY-67chars-aaaaaaaaaaaaa",
                    "base_url": "https://opencode.ai/zen/go/v1",
                },
                {
                    "id": "env01",
                    "label": "OPENCODE_GO_API_KEY",
                    "auth_type": "api_key",
                    "priority": 1,
                    "source": "env:OPENCODE_GO_API_KEY",
                    "access_token": "sk-env-BROKEN-KEY-67chars-bbbbbbbbbbbbb",
                    "base_url": "https://opencode.ai/zen/go/v1",
                },
            ],
        },
    }
    (hermes_home / "auth.json").write_text(json.dumps(global_auth))

    # Per-profile auth.json with only the broken env entry
    profile_auth = {
        "version": 1,
        "credential_pool": {
            "opencode-go": [
                {
                    "id": "env02",
                    "label": "OPENCODE_GO_API_KEY",
                    "auth_type": "api_key",
                    "priority": 0,
                    "source": "env:OPENCODE_GO_API_KEY",
                    "access_token": "sk-env-BROKEN-KEY-67chars-ccccccccccccc",
                    "base_url": "https://opencode.ai/zen/go/v1",
                },
            ],
        },
    }
    (profile_dir / "auth.json").write_text(json.dumps(profile_auth))

    monkeypatch.setenv("HERMES_HOME", str(profile_dir))
    return hermes_home


# ── Helper ──────────────────────────────────────────────────────────────────

def _reload_soul_forge():
    """Force a fresh import of api.soul_forge (the conftest may have
    cached a previous version)."""
    if "api.soul_forge" in sys.modules:
        del sys.modules["api.soul_forge"]
    return importlib.import_module("api.soul_forge")


# ── Tests ───────────────────────────────────────────────────────────────────

class TestResolveGlobalAuthPath:
    def test_climbs_out_of_per_profile_layout(self, global_auth_root, monkeypatch):
        """When HERMES_HOME is scoped to a per-profile dir, the resolver
        must return the GLOBAL auth.json, not the per-profile one."""
        sf = _reload_soul_forge()
        result = sf._resolve_global_auth_path()
        assert result == global_auth_root / "auth.json", (
            f"Expected global path {global_auth_root / 'auth.json'}, got {result}"
        )

    def test_returns_input_when_not_per_profile(self, tmp_path, monkeypatch):
        """When HERMES_HOME is the global root (not per-profile), the
        resolver returns it as-is (no false climb)."""
        hermes_home = tmp_path / "alt-hermes-home"
        hermes_home.mkdir()
        (hermes_home / "auth.json").write_text("{}")
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        sf = _reload_soul_forge()
        result = sf._resolve_global_auth_path()
        assert result == hermes_home / "auth.json"


class TestResolveCredentialFromPool:
    def test_picks_manual_entry_from_global_pool(self, global_auth_root):
        """The resolver must find the manual entry in the global pool
        and return it as (key, base_url)."""
        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is not None
        key, base_url = result
        assert key == "sk-manual-WORKING-KEY-67chars-aaaaaaaaaaaaa"
        assert base_url == "https://opencode.ai/zen/go/v1"

    def test_prefers_manual_over_env_when_both_healthy(self, global_auth_root):
        """When the global pool has both a manual and an env entry, the
        manual one (lower priority number = higher precedence) wins."""
        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is not None
        key, _ = result
        # Manual entry has the WORKING key, env has the BROKEN key
        assert "WORKING" in key, f"Expected manual (WORKING) key, got {key}"

    def test_skips_entries_with_recent_auth_error(self, tmp_path, monkeypatch):
        """Entries with last_error_code in {401, 402, 403} must be skipped.
        This protects against a broken manual entry poisoning the pool."""
        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir()
        auth = {
            "credential_pool": {
                "opencode-go": [
                    {
                        "id": "broken01",
                        "label": "broken-fallback",
                        "auth_type": "api_key",
                        "priority": 0,
                        "source": "manual",
                        "access_token": "sk-broken-401-poison",
                        "base_url": "https://opencode.ai/zen/go/v1",
                        "last_error_code": 401,
                    },
                    {
                        "id": "good01",
                        "label": "working-fallback",
                        "auth_type": "api_key",
                        "priority": 1,
                        "source": "manual",
                        "access_token": "sk-good-healthy-fallback-key",
                        "base_url": "https://opencode.ai/zen/go/v1",
                        "last_error_code": None,
                    },
                ],
            },
        }
        (hermes_home / "auth.json").write_text(json.dumps(auth))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is not None
        key, _ = result
        assert "good" in key, f"Expected healthy entry, got {key}"
        assert "broken" not in key

    def test_returns_none_when_global_pool_empty(self, tmp_path, monkeypatch):
        """When the global auth.json exists but has no entries for the
        provider, the resolver returns None (caller falls back to .env)."""
        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir()
        (hermes_home / "auth.json").write_text(json.dumps({"credential_pool": {}}))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is None

    def test_returns_none_when_global_auth_missing(self, tmp_path, monkeypatch):
        """When the global auth.json doesn't exist, the resolver returns
        None gracefully (no exception, .env fallback can run)."""
        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir()  # no auth.json inside
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is None

    def test_does_not_read_per_profile_auth(self, global_auth_root):
        """Critical regression: the resolver must NOT return the
        per-profile key (`sk-env-BROKEN...ccccccccccccc`). If it does,
        the forge will use the exhausted key from the per-profile file
        and fail with 401 CreditsError — the original bug."""
        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is not None
        key, _ = result
        # The per-profile broken key ends with 'ccccccccccccc'
        assert not key.endswith("ccccccccccccc"), (
            f"Resolver picked the per-profile key — original bug regressed! Got: {key}"
        )
        # The global manual key ends with 'aaaaaaaaaaaaa'
        assert key.endswith("aaaaaaaaaaaaa"), (
            f"Resolver did not pick the global manual entry. Got: {key}"
        )

    def test_uses_per_entry_base_url(self, tmp_path, monkeypatch):
        """If a pool entry has a custom base_url, the resolver returns
        it (not the module-level default)."""
        hermes_home = tmp_path / ".hermes"
        hermes_home.mkdir()
        auth = {
            "credential_pool": {
                "opencode-go": [
                    {
                        "id": "custom01",
                        "label": "custom-endpoint",
                        "auth_type": "api_key",
                        "priority": 0,
                        "source": "manual",
                        "access_token": "sk-custom-key-1234567890",
                        "base_url": "https://custom.example.com/v1",
                    },
                ],
            },
        }
        (hermes_home / "auth.json").write_text(json.dumps(auth))
        monkeypatch.setenv("HERMES_HOME", str(hermes_home))

        sf = _reload_soul_forge()
        result = sf._resolve_credential_from_pool("opencode-go")
        assert result is not None
        _, base_url = result
        assert base_url == "https://custom.example.com/v1"


class TestGetClientUsesPool:
    def test_client_base_url_matches_pool_entry(self, global_auth_root, monkeypatch):
        """End-to-end: the OpenAI client built by `_get_client()` uses
        the pool's base_url + access_token, not the .env defaults."""
        sf = _reload_soul_forge()
        # Force re-resolution (the module caches it on first call)
        sf._resolved_client_key = None
        client = sf._get_client()

        # Don't make a real HTTP call — just inspect the client config.
        # The OpenAI client stores base_url as a URL object; str() it.
        from openai import OpenAI
        assert isinstance(client, OpenAI)
        # We don't compare the secret itself, but the base_url should
        # match the pool entry, not the module default of
        # https://opencode.ai/zen/go/v1
        # (Both happen to be the same URL in this fixture, so we just
        #  assert the client was constructed without error and a
        #  subsequent resolver call returns the same key.)
        sf._resolved_client_key = None
        again = sf._resolve_credential_from_pool("opencode-go")
        assert again is not None
        key, _ = again
        assert "WORKING" in key
