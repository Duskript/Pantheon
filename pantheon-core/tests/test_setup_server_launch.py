from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch


def _load_setup_server():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "setup-server.py"
    spec = importlib.util.spec_from_file_location("pantheon_setup_server", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_launch_worker_starts_dashboard_on_port_8787(monkeypatch, tmp_path):
    """Completing the wizard should launch a real dashboard, not just gateway."""
    setup_server = _load_setup_server()
    monkeypatch.setattr(setup_server, "PANTHEON_DIR", str(tmp_path))

    popen_calls: list[list[str]] = []

    def fake_run(*args, **kwargs):
        return MagicMock(returncode=0, stdout="", stderr="")

    def fake_popen(cmd, *args, **kwargs):
        popen_calls.append(list(cmd))
        return MagicMock(pid=1234)

    def fake_get(url, *args, **kwargs):
        response = MagicMock()
        response.status_code = 200
        return response

    with patch.object(setup_server.subprocess, "run", side_effect=fake_run), \
         patch.object(setup_server.subprocess, "Popen", side_effect=fake_popen), \
         patch("httpx.get", side_effect=fake_get), \
         patch.object(setup_server.time, "sleep", return_value=None):
        setup_server._launch_worker()

    assert ["hermes", "gateway"] in popen_calls
    assert any(
        cmd[:2] == ["hermes", "dashboard"]
        and "--port" in cmd
        and cmd[cmd.index("--port") + 1] == "8787"
        and "--host" in cmd
        and cmd[cmd.index("--host") + 1] == "127.0.0.1"
        for cmd in popen_calls
    )
