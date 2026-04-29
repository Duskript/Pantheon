import os
from pathlib import Path
import tempfile
import pytest

from sanctuary.config import SanctuaryConfig, VaultLogging, SanctuaryUI
from vault.writer import VaultWriter


def make_sanctuary(enabled: bool = True, path: str = "Codex-SKC/sessions/") -> SanctuaryConfig:
    return SanctuaryConfig(
        id="apollo-lyric-writing",
        name="The Studio — Lyric Writing",
        god="Apollo",
        studio="lyric-writing",
        harness="apollo-lyric-writing.yaml",
        model="gemma4",
        context_window=8192,
        vault_logging=VaultLogging(enabled=enabled, path=path),
        ui=SanctuaryUI(),
    )


def test_session_file_created_on_first_log():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "user", "hello")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        files = list(session_dir.glob("*.md"))
        assert len(files) == 1


def test_session_file_has_frontmatter():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "user", "hello")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        content = list(session_dir.glob("*.md"))[0].read_text()
        assert "sanctuary: The Studio — Lyric Writing" in content
        assert "god: Apollo" in content
        assert "studio: lyric-writing" in content


def test_user_turn_written():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "user", "what rhymes with fire?")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        content = list(session_dir.glob("*.md"))[0].read_text()
        assert "[User]: what rhymes with fire?" in content


def test_assistant_turn_uses_god_name():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "assistant", "desire, empire, entire")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        content = list(session_dir.glob("*.md"))[0].read_text()
        assert "[Apollo]: desire, empire, entire" in content


def test_multiple_turns_appended_to_same_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "user", "first")
        writer.append_turn("session-1", sanctuary, "assistant", "second")
        writer.append_turn("session-1", sanctuary, "user", "third")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        files = list(session_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "[User]: first" in content
        assert "[Apollo]: second" in content
        assert "[User]: third" in content


def test_different_sessions_create_different_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "user", "hello")
        writer.append_turn("session-2", sanctuary, "user", "world")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        files = list(session_dir.glob("*.md"))
        assert len(files) == 2


def test_vault_logging_disabled_writes_nothing():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary(enabled=False)
        writer.append_turn("session-1", sanctuary, "user", "hello")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        assert not session_dir.exists() or len(list(session_dir.glob("*.md"))) == 0


def test_session_file_name_is_iso8601_timestamp():
    with tempfile.TemporaryDirectory() as tmpdir:
        writer = VaultWriter(tmpdir)
        sanctuary = make_sanctuary()
        writer.append_turn("session-1", sanctuary, "user", "hello")
        session_dir = Path(tmpdir) / "Codex-SKC/sessions"
        filename = list(session_dir.glob("*.md"))[0].name
        assert "T" in filename
        assert filename.endswith(".md")
