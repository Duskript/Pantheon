"""Hermes UI compatibility endpoints for the Pantheon retheme branch."""

import json
import shutil
import urllib.error
import urllib.request
import uuid

from tests._pytest_port import BASE


def get(path):
    req = urllib.request.Request(BASE + path)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code


def post(path, body=None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        return json.loads(e.read()), e.code


def _cleanup_skill_and_trash(skill_name):
    from tools.skills_tool import SKILLS_DIR

    root = SKILLS_DIR
    for skill_file in list(root.rglob("SKILL.md")):
        if skill_file.parent.name == skill_name:
            shutil.rmtree(skill_file.parent, ignore_errors=True)

    trash_root = root.parent / "skills-trash"
    if trash_root.exists():
        for skill_file in list(trash_root.rglob("SKILL.md")):
            trash_dir = skill_file.parent
            meta_path = trash_dir / ".webui-trash.json"
            original_name = ""
            if meta_path.exists():
                try:
                    original_name = json.loads(meta_path.read_text(encoding="utf-8")).get("original_name", "")
                except Exception:
                    original_name = ""
            if original_name == skill_name or trash_dir.name.startswith(f"{skill_name}--"):
                shutil.rmtree(trash_dir, ignore_errors=True)


def test_hermes_ui_compatibility_endpoint_shapes():
    d, status = get("/api/work-items")
    assert status == 200
    assert d["ok"] is True
    assert isinstance(d["items"], list)

    d, status = post("/api/work-items", {"stream_id": "none", "action": "dismiss"})
    assert status == 200
    assert d["success"] is True
    assert d["status"] == "dismissed"
    assert d["id"] == "stream:none"

    d, status = get("/api/delegation/info")
    assert status == 200
    assert "configured" in d

    d, status = get("/api/tools/toolsets")
    assert status == 200
    assert d["ok"] is True
    assert isinstance(d["toolsets"], list)


def test_skills_delete_moves_to_trash_and_restore_round_trips():
    skill_name = f"test-hermes-ui-compat-{uuid.uuid4().hex[:8]}"
    _cleanup_skill_and_trash(skill_name)
    content = (
        "---\n"
        f"name: {skill_name}\n"
        "description: temporary compatibility test skill\n"
        "---\n\n"
        "# Temporary Skill\n"
    )
    try:
        d, status = post("/api/skills/save", {"name": skill_name, "content": content})
        assert status == 200
        assert d["ok"] is True
        assert d["success"] is True

        d, status = post("/api/skills/delete", {"name": skill_name})
        assert status == 200
        assert d["ok"] is True
        assert d["success"] is True
        assert d["trash_item"]["original_name"] == skill_name
        trash_id = d["trash_item"]["id"]

        d, status = get("/api/skills/trash")
        assert status == 200
        assert d["ok"] is True
        assert isinstance(d["items"], list)
        assert isinstance(d["trash"], list)
        assert any(item.get("id") == trash_id for item in d["items"])

        d, status = post("/api/skills/restore", {"id": trash_id})
        assert status == 200
        assert d["ok"] is True
        assert d["success"] is True
        assert d["name"] == skill_name

        d, status = get(f"/api/skills/content?name={skill_name}")
        assert status == 200
        assert skill_name in d.get("content", "")
    finally:
        _cleanup_skill_and_trash(skill_name)
