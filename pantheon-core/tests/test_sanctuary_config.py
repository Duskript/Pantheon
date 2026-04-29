import os
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

os.environ["PANTHEON_SANCTUARIES_DIR"] = str(FIXTURES_DIR / "sanctuaries")


from sanctuary.config import load_all_sanctuaries, load_sanctuary, SanctuaryConfig


def test_load_sanctuary_returns_config():
    s = load_sanctuary("test-apollo")
    assert s is not None
    assert isinstance(s, SanctuaryConfig)


def test_sanctuary_id_is_filename_stem():
    s = load_sanctuary("test-apollo")
    assert s.id == "test-apollo"


def test_sanctuary_fields_parsed():
    s = load_sanctuary("test-apollo")
    assert s.name == "Test Studio — Lyric Writing"
    assert s.god == "Apollo"
    assert s.studio == "lyric-writing"
    assert s.harness == "test-apollo.yaml"
    assert s.model == "gemma4"
    assert s.context_window == 8192


def test_vault_logging_parsed():
    s = load_sanctuary("test-apollo")
    assert s.vault_logging.enabled is True
    assert s.vault_logging.path == "Codex-SKC/sessions/"
    assert s.vault_logging.format == "markdown"


def test_ui_parsed():
    s = load_sanctuary("test-apollo")
    assert s.ui.accent_color == "#f59e0b"
    assert s.ui.icon == "🎵"


def test_load_missing_sanctuary_returns_none():
    result = load_sanctuary("does-not-exist")
    assert result is None


def test_load_all_sanctuaries_returns_list():
    sanctuaries = load_all_sanctuaries()
    assert isinstance(sanctuaries, list)
    assert len(sanctuaries) >= 1


def test_load_all_sanctuary_ids_are_unique():
    sanctuaries = load_all_sanctuaries()
    ids = [s.id for s in sanctuaries]
    assert len(ids) == len(set(ids))
