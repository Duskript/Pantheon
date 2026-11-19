"""Contract tests for the Pantheon Client Kit roster installer (Phase 2).

PURE UNIT TESTS — no LLM, no network, no writes outside pytest's tmp dirs.

What is pinned here:
  * the pack passes its own artifact-hygiene gate, and that gate actually fires
  * the installer writes the six gods at the declared layout and **nothing**
    outside the target root (the traversal guard is asserted, not assumed)
  * the memory scrub removes runtime history and *blanks* MEMORY.md / USER.md
  * credentials are never templated in — a planted secret fails the install
  * installing twice is a no-op; --force is required to overwrite
  * the §7.2 roster defects (inline icons, placeholder icons, mis-cased domains)
    are fixable on an existing tree without losing the artwork
"""
from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT = REPO / "client-kit"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


ri = _load("roster_install", KIT / "roster_install.py")

SHIPPED = ["hermes", "rheta", "iris", "thoth", "kairos", "caduceus"]


@pytest.fixture(scope="module")
def manifest():
    return ri.load_manifest()


@pytest.fixture(scope="module")
def rendered(manifest):
    return ri.render_roster(manifest)


# ── the pack's own hygiene gate ────────────────────────────────────────────

def test_shipped_pack_passes_its_hygiene_gate(manifest):
    assert ri.check_pack(manifest) == []


def test_pack_gate_catches_every_defect_it_claims_to(manifest):
    broken = json.loads(json.dumps(manifest))  # deep copy
    broken["gods"]["rheta"]["icon"] = "data:image/png;base64," + "A" * 900
    broken["gods"]["iris"]["icon"] = "<inline image data-url, 2,691,894 chars>"
    broken["gods"]["kairos"]["routes_to"] = {"implementation": "hephaestus"}
    broken["gods"]["thoth"]["domain"] = "God of Knowledge and stuff"
    del broken["gods"]["caduceus"]["color"]
    problems = ri.check_pack(broken)
    joined = " | ".join(problems)
    assert "inline data-url" in joined
    assert "roster placeholder" in joined
    assert "dead handoff" in joined
    assert "house style" in joined
    assert "missing 'color'" in joined


def test_pack_gate_catches_a_conductor_that_does_not_ship(manifest):
    broken = json.loads(json.dumps(manifest))
    broken["conductor"] = "hephaestus"
    assert any("not a shipped god" in p for p in ri.check_pack(broken))


# ── rendering ──────────────────────────────────────────────────────────────

def test_render_is_manifest_authoritative_and_artifact_complete(manifest, rendered):
    for god in SHIPPED:
        meta = json.loads(rendered[f"gods/{god}/god.json"])
        assert meta["display_name"] == manifest["gods"][god]["display_name"]
        assert meta["domain"] == manifest["gods"][god]["domain"]
        assert meta["color"] == manifest["gods"][god]["color"]
        for name in ("SOUL.md", "persona.md", "MEMORY.md", ".env", "config.yaml"):
            assert f"gods/{god}/{name}" in rendered, f"{god}/{name}"
    assert "tenant.json" in rendered
    assert "PHONEBOOK.json" in rendered


def test_render_never_contains_inline_images_or_secret_values(manifest, rendered):
    for rel, text in rendered.items():
        assert "data:image" not in text, rel
        assert "<inline image" not in text, rel
    assert ri.check_no_secrets(rendered) == []


def test_secret_gate_fires_on_a_planted_secret(manifest, rendered):
    poisoned = dict(rendered)
    poisoned["gods/hermes/.env"] = "DISCORD_BOT_TOKEN=ghp_" + "a" * 36 + "\n"
    leaks = ri.check_no_secrets(poisoned)
    assert leaks and "DISCORD_BOT_TOKEN" in leaks[0]


def test_routing_only_points_at_shipped_gods(manifest, rendered):
    book = json.loads(rendered["PHONEBOOK.json"])
    assert book["conductor"] == manifest["conductor"]
    for god, row in book["gods"].items():
        assert god in SHIPPED
        for slot, dest in row["routes_to"].items():
            assert dest in SHIPPED, f"{god}.{slot} -> {dest}"


def test_the_manifest_is_actually_authoritative(manifest):
    """Make the manifest *differ* from the engine's defaults, then check it wins.

    The engine normalises the same domains and picks close-enough colours, so a
    render test that only compares against the shipped manifest cannot tell an
    applied overlay from an ignored one. This one edits the manifest first.
    """
    edited = json.loads(json.dumps(manifest))
    edited["gods"]["rheta"]["domain"] = "Copy · Persuasion · Voice"
    edited["gods"]["rheta"]["color"] = "#123456"
    edited["gods"]["rheta"]["display_name"] = "Rheta Prime"
    rendered = ri.render_roster(edited)
    meta = json.loads(rendered["gods/rheta/god.json"])
    assert meta["domain"] == "Copy · Persuasion · Voice"
    assert meta["color"] == "#123456"
    assert meta["display_name"] == "Rheta Prime"
    # and the Codex directory follows the manifest's display name, not the engine's
    plan = ri.plan_placements(edited, rendered)
    assert "athenaeum/Codex-God-Rheta Prime/INDEX.md" in plan.values() or any(
        "Codex-God-Rheta Prime" in p for p in plan.values()
    ), sorted(plan.values())


def test_config_ships_without_a_model_or_credentials(manifest, rendered):
    cfg = yaml.safe_load(rendered["gods/hermes/config.yaml"])
    assert cfg["model"]["default"] is None
    assert cfg["model"]["provider"] is None
    assert "pantheon-background-ops" in cfg["plugins"]["enabled"]


# ── placement and the traversal guard ──────────────────────────────────────

def test_placements_follow_the_declared_layout(manifest, rendered):
    plan = ri.plan_placements(manifest, rendered)
    assert plan["gods/hermes/SOUL.md"] == ".hermes/profiles/hermes/SOUL.md"
    assert plan["tenant.json"] == "athenaeum/tenant.json"
    assert any(p.startswith("athenaeum/Codex-God-") for p in plan.values())
    assert any(p.startswith("athenaeum/Codex-User/relationships/") for p in plan.values())


def test_writes_are_confined_to_the_target_root(tmp_path):
    root = tmp_path / "client"
    root.mkdir()
    assert ri._resolve_within(root, ".hermes/profiles/hermes/SOUL.md").is_relative_to(root)
    with pytest.raises(ri.KitError):
        ri._resolve_within(root, "../../etc/passwd")
    with pytest.raises(ri.KitError):
        ri._resolve_within(root, ".hermes/../../escape")


# ── install + scrub ────────────────────────────────────────────────────────

def _dirty_profile(root: pathlib.Path, god: str) -> pathlib.Path:
    """A profile carrying exactly the runtime history a client must never receive."""
    profile = root / ".hermes" / "profiles" / god
    (profile / "sessions").mkdir(parents=True)
    (profile / "cron").mkdir()
    (profile / "ichor").mkdir()
    (profile / "memories").mkdir()
    (profile / "state.db").write_text("operator session history")
    (profile / "state.db-wal").write_text("wal")
    (profile / "lcm.db").write_text("lcm")
    (profile / "SOUL.md.bak-20261018-215036").write_text("operator soul")
    (profile / "config.yaml.bak-ichor-fleet").write_text("operator config")
    (profile / "sessions" / "20261118.json").write_text("a session")
    (profile / "cron" / "jobs.json").write_text("a cron job")
    (profile / "ichor" / "graph.db").write_text("operator memory graph")
    (profile / "MEMORY.md").write_text("Konan's private memory")
    (profile / "USER.md").write_text("Konan's private profile")
    return profile


def test_install_writes_the_roster_and_scrubs_it(manifest, rendered, tmp_path):
    root = tmp_path / "client"
    root.mkdir()
    for god in SHIPPED:
        _dirty_profile(root, god)
    shared = root / ".hermes" / "memories"
    shared.mkdir(parents=True)
    (shared / "MEMORY.md").write_text("fleet memory")
    (shared / "USER.md").write_text("fleet profile")
    (shared / "MEMORY.meta").write_text("{}")

    summary = ri.install_roster(root, manifest, rendered)

    # installed
    for god in SHIPPED:
        assert (root / ".hermes" / "profiles" / god / "SOUL.md").is_file()
        assert json.loads((root / ".hermes" / "profiles" / god / "god.json").read_text())
    assert (root / "athenaeum" / "tenant.json").is_file()
    assert (root / ".hermes" / "client-kit" / "PHONEBOOK.json").is_file()

    # scrubbed
    hv = root / ".hermes" / "profiles" / "hermes"
    for gone in ("state.db", "state.db-wal", "lcm.db", "sessions", "cron", "ichor", "memories"):
        assert not (hv / gone).exists(), gone
    assert not list(hv.glob("*.bak-*"))
    assert (hv / "MEMORY.md").read_text() == ""
    assert (hv / "USER.md").read_text() == ""
    assert (shared / "MEMORY.md").read_text() == ""
    assert not (shared / "MEMORY.meta").exists()
    assert summary["removed"], "the scrub must report what it removed"

    # and the source tree is untouched
    assert "Konan's private memory" not in (hv / "MEMORY.md").read_text()


def test_install_keeps_existing_files_unless_forced(manifest, rendered, tmp_path):
    root = tmp_path / "client"
    root.mkdir()
    first = ri.install_roster(root, manifest, rendered)
    assert first["written"] and not first["kept"]
    soul = root / ".hermes" / "profiles" / "rheta" / "SOUL.md"
    soul.write_text("client edited this")
    second = ri.install_roster(root, manifest, rendered)
    assert second["written"] == [] and second["kept"]
    assert soul.read_text() == "client edited this"
    forced = ri.install_roster(root, manifest, rendered, force=True)
    assert forced["written"] and soul.read_text() != "client edited this"


def test_dry_run_writes_nothing(manifest, rendered, tmp_path):
    root = tmp_path / "client"
    root.mkdir()
    summary = ri.install_roster(root, manifest, rendered, dry_run=True)
    assert summary["dry_run"] is True and summary["written"]
    assert list(root.iterdir()) == [], "dry-run must not create a single file"


# ── the §7.2 defects, fixed on an existing tree ────────────────────────────

def test_sanitize_extracts_an_inline_icon_without_losing_the_artwork(tmp_path, manifest):
    profile = tmp_path / "profiles" / "rheta"
    profile.mkdir(parents=True)
    payload = bytes(range(256)) * 8
    encoded = base64.b64encode(payload).decode()
    god_json = profile / "god.json"
    god_json.write_text(json.dumps({
        "display_name": "Rheta",
        "icon": f"data:image/png;base64,{encoded}",
        "color": "#B91C1C",
        "domain": "Copywriting rhetoric And persuasion",
    }), encoding="utf-8")

    result = ri.sanitize_god_json(god_json, domain=manifest["gods"]["rheta"]["domain"])

    assert (profile / "icon.png").read_bytes() == payload
    meta = json.loads(god_json.read_text())
    # /api/gods/rheta/icon reads exactly icon.png and sniffs the Content-Type,
    # so the field must be the extension-less served path.
    assert meta["icon"] == "/api/gods/rheta/icon"
    assert meta["domain"] == "Copywriting · Rhetoric · Persuasion"
    assert meta["display_name"] == "Rheta"
    assert god_json.with_suffix(".json.bak-inline-icon").exists()
    actions = " | ".join(result["actions"])
    assert "extracted inline icon" in actions and "domain" in actions


def test_sanitize_keeps_the_route_filename_when_the_label_lies(tmp_path):
    """rheta's live icon declares image/png but carries JPEG bytes.

    The route reads `icon.png` and sniffs magic bytes for the Content-Type, so the
    bytes belong in icon.png regardless — and the mislabel must be reported rather
    than silently trusted.
    """
    profile = tmp_path / "profiles" / "rheta"
    profile.mkdir(parents=True)
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    god_json = profile / "god.json"
    god_json.write_text(json.dumps({
        "display_name": "Rheta",
        "icon": "data:image/png;base64," + base64.b64encode(jpeg).decode(),
        "color": "#B91C1C",
    }), encoding="utf-8")

    result = ri.sanitize_god_json(god_json)

    assert (profile / "icon.png").read_bytes() == jpeg
    assert not list(profile.glob("icon.jpg")), "must not write a filename the route cannot serve"
    assert json.loads(god_json.read_text())["icon"] == "/api/gods/rheta/icon"
    assert "payload is actually .jpg" in " ".join(result["actions"])


def test_sanitize_replaces_a_roster_placeholder_icon(tmp_path):
    profile = tmp_path / "profiles" / "iris"
    profile.mkdir(parents=True)
    god_json = profile / "god.json"
    god_json.write_text(json.dumps({
        "display_name": "Iris",
        "icon": "<inline image data-url, 2,691,894 chars>",
    }), encoding="utf-8")
    ri.sanitize_god_json(god_json)
    assert json.loads(god_json.read_text())["icon"] == "/api/gods/iris/icon"


def test_sanitize_is_a_no_op_on_a_clean_file(tmp_path):
    profile = tmp_path / "profiles" / "thoth"
    profile.mkdir(parents=True)
    god_json = profile / "god.json"
    original = json.dumps({"display_name": "Thoth", "icon": "/api/gods/thoth/icon"}, indent=2)
    god_json.write_text(original, encoding="utf-8")
    result = ri.sanitize_god_json(god_json)
    assert result["actions"] == []
    assert god_json.read_text().strip() == original.strip()
    assert not list(profile.glob("*.bak-*"))


# ── CLI ────────────────────────────────────────────────────────────────────

def test_cli_check_is_green(capsys):
    assert ri.main(["--check"]) == 0
    assert "pack check OK" in capsys.readouterr().out


def test_cli_check_fails_on_a_broken_manifest(tmp_path, capsys, manifest):
    broken = json.loads(json.dumps(manifest))
    broken["gods"]["rheta"]["icon"] = "data:image/png;base64,AAAA"
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    assert ri.main(["--check", "--manifest", str(path)]) == 1
    assert "FAILED" in capsys.readouterr().out


def test_cli_dry_run_into_a_tmp_root(tmp_path, capsys):
    root = tmp_path / "client"
    root.mkdir()
    assert ri.main(["--root", str(root), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "would write" in out
    assert list(root.iterdir()) == []
