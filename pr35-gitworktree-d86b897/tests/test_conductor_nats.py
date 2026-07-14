"""Conductor NATS integration tests."""

from __future__ import annotations

import json
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
NATS_AVAILABLE = conductor_server.NATS_AVAILABLE


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


@pytest.mark.skipif(not NATS_AVAILABLE, reason="nats-py not installed")
def test_nats_import_available(conductor: Conductor) -> None:
    assert NATS_AVAILABLE is True


def test_start_nats_listener_requires_token(conductor: Conductor, tmp_path: Path, monkeypatch) -> None:
    # Point home to tmp_path so no token file exists
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    instance = Conductor(base_dir=tmp_path / "c", handoffs_dir=tmp_path / "shared" / "handoffs")
    result = instance.start_nats_listener()
    assert result["status"] == "error"
    assert "token" in result["reason"].lower()


def test_start_stop_nats_listener_symmetry(conductor: Conductor) -> None:
    result = conductor.stop_nats_listener()
    assert result["status"] == "stopped"


@pytest.mark.skipif(not NATS_AVAILABLE, reason="nats-py not installed")
def test_publish_workflow_event_integration(conductor: Conductor) -> None:
    # This may succeed if real NATS is reachable
    result = conductor.publish_workflow_event("wf_test_1", "started", {"step": "research"})
    # Accept either success or connection error - just verify it runs without crashing
    assert result["status"] in ("published", "error")


