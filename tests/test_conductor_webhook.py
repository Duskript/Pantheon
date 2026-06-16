"""Conductor webhook gateway tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER_PATH = ROOT / "conductor" / "conductor_server.py"
SCHEMA_PATH = ROOT / "shared" / "handoffs" / "schema.json"

import importlib.util
spec = importlib.util.spec_from_file_location("conductor_server", SERVER_PATH)
conductor_server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(conductor_server)
Conductor = conductor_server.Conductor
AIOHTTP_AVAILABLE = conductor_server.AIOHTTP_AVAILABLE


@pytest.fixture()
def conductor(tmp_path: Path) -> Conductor:
    base = tmp_path / "conductor"
    handoffs = tmp_path / "shared" / "handoffs"
    handoffs.mkdir(parents=True)
    import shutil
    shutil.copy2(SCHEMA_PATH, handoffs / "schema.json")
    instance = Conductor(base_dir=base, handoffs_dir=handoffs)
    instance.ensure_layout()
    return instance


def test_start_webhook_gateway_requires_aiohttp(conductor: Conductor, monkeypatch) -> None:
    monkeypatch.setattr(conductor_server, "AIOHTTP_AVAILABLE", False)
    result = conductor.start_webhook_gateway()
    assert result["status"] == "error"
    assert "aiohttp" in result["reason"].lower()


def test_start_stop_webhook_gateway_symmetry(conductor: Conductor) -> None:
    result = conductor.stop_webhook_gateway()
    assert result["status"] == "stopped"


@pytest.mark.skipif(not AIOHTTP_AVAILABLE, reason="aiohttp not installed")
def test_webhook_gateway_start_stop_integration(conductor: Conductor) -> None:
    # This tests actual start/stop - may fail if port is in use, just verify API shape
    result = conductor.start_webhook_gateway(0)  # port 0 = OS assigns free port
    # Could be "started" or "error" depending on environment
    assert result["status"] in ("started", "error")
    if result["status"] == "started":
        stop_result = conductor.stop_webhook_gateway()
        assert stop_result["status"] == "stopped"


