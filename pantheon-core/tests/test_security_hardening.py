from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest


def _load_pantheon_plugin(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "plugins"))
    agent_module = types.ModuleType("agent")
    memory_provider_module = types.ModuleType("agent.memory_provider")

    class MemoryProvider:
        pass

    memory_provider_module.MemoryProvider = MemoryProvider
    monkeypatch.setitem(sys.modules, "agent", agent_module)
    monkeypatch.setitem(sys.modules, "agent.memory_provider", memory_provider_module)
    monkeypatch.setenv("ATHENAEUM_ROOT", str(tmp_path / "athenaeum"))
    monkeypatch.setenv("CHROMA_DIR", str(tmp_path / "chroma"))
    module = importlib.import_module("pantheon")
    return importlib.reload(module)


def test_athenaeum_read_rejects_path_traversal(monkeypatch, tmp_path):
    pantheon = _load_pantheon_plugin(monkeypatch, tmp_path)
    root = tmp_path / "athenaeum"
    root.mkdir()
    outside = tmp_path / "secret.txt"
    outside.write_text("do not read me", encoding="utf-8")

    plugin = pantheon.PantheonMemoryProvider()
    plugin._athenaeum_root = root
    result = plugin._tool_read({"path": "../secret.txt"})

    assert "error" in result
    assert "Athenaeum" in result["error"]
    assert "do not read me" not in str(result)


def test_athenaeum_embed_rejects_absolute_paths(monkeypatch, tmp_path):
    pantheon = _load_pantheon_plugin(monkeypatch, tmp_path)
    outside = tmp_path / "secret.txt"
    outside.write_text("do not embed me", encoding="utf-8")

    plugin = pantheon.PantheonMemoryProvider()
    plugin._athenaeum_root = tmp_path / "athenaeum"
    plugin._athenaeum_root.mkdir()
    result = plugin._tool_embed({"path": str(outside)})

    assert "error" in result
    assert "Athenaeum" in result["error"]


def test_url_ingest_blocks_private_network_targets(monkeypatch, tmp_path):
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root / "plugins"))
    _load_pantheon_plugin(monkeypatch, tmp_path)
    monkeypatch.setenv("ATHENAEUM_ROOT", str(tmp_path / "athenaeum"))
    ingest = importlib.import_module("pantheon.demeter.ingest")
    ingest = importlib.reload(ingest)

    with patch("httpx.get") as mock_get:
        result = ingest.ingest_url("http://127.0.0.1:8010/mcp")

    assert result.success is False
    assert "private" in (result.error or "").lower() or "local" in (result.error or "").lower()
    mock_get.assert_not_called()
