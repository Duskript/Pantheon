import os
from pathlib import Path
import tempfile
import pytest
from fastapi.testclient import TestClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"

os.environ["PANTHEON_SANCTUARIES_DIR"] = str(FIXTURES_DIR / "sanctuaries")
os.environ["PANTHEON_HARNESS_DIR"] = str(FIXTURES_DIR / "harnesses")

# Must import after env vars are set
import importlib
import api as api_module
from api import app

client = TestClient(app)


def test_get_sanctuaries_returns_grouped_dict():
    resp = client.get("/sanctuaries")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "Apollo" in data


def test_get_sanctuaries_each_entry_has_required_fields():
    resp = client.get("/sanctuaries")
    data = resp.json()
    sanctuary = data["Apollo"][0]
    assert "id" in sanctuary
    assert "name" in sanctuary
    assert "ui" in sanctuary


def test_get_prompt_returns_identity():
    resp = client.get("/sanctuary/test-apollo/prompt")
    assert resp.status_code == 200
    data = resp.json()
    assert "prompt" in data
    assert "TestApollo" in data["prompt"]
    assert data["god"] == "Apollo"


def test_get_prompt_unknown_sanctuary_returns_404():
    resp = client.get("/sanctuary/does-not-exist/prompt")
    assert resp.status_code == 404


def test_log_turn_returns_ok(tmp_path):
    os.environ["ATHENAEUM_ROOT"] = str(tmp_path)
    import importlib
    import api
    importlib.reload(api)
    from api import app as reloaded_app
    c = TestClient(reloaded_app)
    resp = c.post(
        "/sanctuary/test-apollo/log",
        json={"session_id": "test-session-1", "role": "user", "content": "hello"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_log_turn_unknown_sanctuary_returns_404():
    resp = client.post(
        "/sanctuary/does-not-exist/log",
        json={"session_id": "s1", "role": "user", "content": "hi"},
    )
    assert resp.status_code == 404
