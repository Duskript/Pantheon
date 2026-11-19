"""Contract tests for the Pantheon client-kit seed interview engine (Phase 1).

PURE UNIT TESTS — no LLM, no network, no live WebUI server. They import
``webui/api/interview_engine.py`` straight off disk so they do not drag in the
webui ``conftest.py`` server fixtures.

What is pinned here is the *contract* the spec promises:
  * the question set is data, and a question without a destination cannot ship
  * the two layers never cross; the per-god layer is identity-first
  * "keep the defaults" really does skip the rest of the identity trio
  * nothing is invented — unanswered becomes an explicit `open` unknown
  * every artifact `seed_write` names is actually rendered, and parses
  * a client kit never ships operator artwork or an operator's model choice
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = REPO / "webui" / "api" / "interview_engine.py"


def _load_engine_module():
    spec = importlib.util.spec_from_file_location("interview_engine", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["interview_engine"] = module
    spec.loader.exec_module(module)
    return module


ie = _load_engine_module()


ANSWERS = {
    "T1": "Northwind Dental — a 4-chair family dental practice in Boise.",
    "T2": [
        {"name": "Dana Reyes", "role": "Owner / dentist", "contact": "dana@northwind.example"},
        {"name": "Priya Shah", "role": "Office manager", "contact": "", "approver": True},
    ],
    "T3": [
        {"person": "Dana Reyes", "discord_id": "111111111111111111"},
        {"person": "Priya Shah", "discord_id": "222222222222222222", "telegram_id": "333333333"},
    ],
    "T4": {"timezone": "America/Boise", "hours": "8am-5pm Mon-Thu"},
    "T5": "Warm, plain-spoken, zero jargon.",
    "T6": ["chase unpaid invoices", "summarize new-patient intake"],
    "T7": "Never email a patient without asking.",
    "T8": "discord",
    # rheta keeps the defaults -> its identity trio must be skipped
    "rheta/G1": "keep",
    # thoth is personalised
    "thoth/G1": "Oracle",
    "thoth/G2": "Dry, precise, cites everything.",
    "thoth/G3": {"owns": ["research", "synthesis"], "routes_elsewhere": {"copy": "rheta"}},
    # caduceus gets a client-uploaded avatar
    "caduceus/G7": "uploads/avatar-caduceus.png",
}


@pytest.fixture()
def built():
    spec = ie.load_spec()
    roster = ie.load_roster()
    engine = ie.InterviewEngine(spec, roster)
    for key, value in ANSWERS.items():
        engine.answer(key, value)
    return spec, roster, engine


# ── the spec is data, and it must be shippable ─────────────────────────────

def test_spec_loads_with_two_layers_and_the_declared_roster():
    spec = ie.load_spec()
    roster = ie.load_roster()
    assert spec.layers == ["tenant", "god"]
    assert len(spec.questions("tenant")) == 9
    assert len(spec.questions("god")) == 10
    assert spec.per_god_layer() == "god"
    assert roster.names() == ["hermes", "rheta", "iris", "thoth", "kairos", "caduceus"]
    assert roster.conductor == "hermes"


def test_check_spec_is_clean_on_the_shipped_set():
    assert ie.check_spec(ie.load_spec()) == []


def test_check_spec_rejects_orphan_and_colon_targets(tmp_path):
    bad = {
        "version": "0",
        "layers": {
            "tenant": {
                "questions": [
                    {"id": "T1", "ask": "a?", "type": "text", "required": True},
                    {"id": "T2", "ask": "b?", "writes_to": ["god:SOUL.md"]},
                ]
            }
        },
        "seed_write": {"per_install": ["tenant.json"]},
    }
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    problems = ie.check_spec(ie.load_spec(path))
    assert any("no writes_to" in p for p in problems), problems
    assert any("colon" in p for p in problems), problems


def test_question_public_shape_never_leaks_prose_internals():
    q = ie.load_spec().question("god", "G1")
    public = q.public()
    assert public["id"] == "G1"
    assert "on_keep" not in public and "raw" not in public
    assert public["writes_to"]


# ── ordering and the identity-trio skip ────────────────────────────────────

def test_run_is_tenant_first_then_identity_first_per_god(built):
    spec, roster, engine = built
    order = [(god, q.id) for _l, god, q in engine.order()]
    assert order[:9] == [("", q.id) for q in spec.questions("tenant")]
    for god in roster.names():
        ids = [qid for g, qid in order if g == god]
        assert ids[:3] == ["G1", "G2", "G3"], f"{god} is not identity-first: {ids}"


def test_keep_the_defaults_skips_the_identity_trio(built):
    _spec, _roster, engine = built
    engine.refresh_skips()
    assert "rheta/G2" in engine.skipped
    assert "rheta/G3" in engine.skipped
    assert "keep" in engine.skipped["rheta/G2"]
    # the rest of rheta's run resumes at G4
    assert "rheta/G4" not in engine.skipped
    assert "rheta/G4" in engine.run_keys()
    # a personalised god keeps its whole trio
    assert "thoth/G2" not in engine.skipped and "thoth/G3" not in engine.skipped


def test_engine_answer_validates_required_and_caps_max_lists(built):
    _spec, _roster, engine = built
    with pytest.raises(ie.SpecError):
        engine.answer("hermes/G10", "")
    engine.answer("hermes/G8", ["a", "b", "c", "d", "e", "f", "g"])
    spec_max = engine.spec.question("god", "G8").maximum
    assert spec_max is None or len(engine.answers["hermes/G8"]) <= spec_max


# ── unknowns are explicit, never invented ─────────────────────────────────

def test_optional_unanswered_becomes_an_open_unknown(built):
    _spec, _roster, engine = built
    keys = {u.key for u in engine.unknowns()}
    assert "hermes/G6" in keys          # optional: outside-world reach
    assert "hermes/G7" in keys          # optional: avatar
    assert all(u.public()["status"] == "open" for u in engine.unknowns())
    assert all(u.public()["owner"] for u in engine.unknowns())


def test_required_unanswered_is_not_an_unknown(built):
    _spec, _roster, engine = built
    unknown_keys = {u.key for u in engine.unknowns()}
    missing = engine.missing_required()
    assert "hermes/G2" in missing
    assert "hermes/G2" not in unknown_keys


def test_defaults_are_recorded_as_defaults_not_answers(built):
    _spec, _roster, engine = built
    defaults = engine.defaults_applied()
    assert defaults["hermes/G10"] == "anything external — always ask"
    assert "hermes/G10" not in engine.answers
    assert engine.value("hermes/G10") == "anything external — always ask"


def test_multiselect_default_all_expands_to_the_shipped_roster(built):
    spec, roster, engine = built
    assert spec.question("god", "G5").default == "all"
    book = json.loads(ie.render_artifacts(engine)["PHONEBOOK.json"])
    assert set(book["gods"]).issubset(set(roster.names()))
    for god, row in book["gods"].items():
        assert set(row["routes_to"]).issubset(set(roster.names())), god


# ── rendering: every promised artifact, and it parses ─────────────────────

def test_render_covers_every_seed_write_artifact(built):
    spec, _roster, engine = built
    artifacts = ie.render_artifacts(engine, spec)
    assert ie.verify_render(artifacts, spec) == []


def test_rendered_json_and_yaml_actually_parse(built, tmp_path):
    spec, _roster, engine = built
    artifacts = ie.render_artifacts(engine, spec)
    written = ie.write_artifacts(tmp_path, artifacts)
    assert "tenant.json" in written and "MANIFEST.json" in written
    for rel, text in artifacts.items():
        if rel.endswith(".json"):
            json.loads(text)
        if rel.endswith("config.yaml"):
            parsed = yaml.safe_load(text)
            assert isinstance(parsed, dict)
    manifest = json.loads(artifacts["MANIFEST.json"])
    assert manifest["gods"] == ["hermes", "rheta", "iris", "thoth", "kairos", "caduceus"]
    assert manifest["unanswered_required"]
    assert manifest["skipped"]                    # rheta's trio
    assert manifest["unknowns"]


def test_god_json_is_clean_normalised_and_complete(built):
    spec, roster, engine = built
    artifacts = ie.render_artifacts(engine, spec)
    for god in roster.names():
        raw = artifacts[f"gods/{god}/god.json"]
        assert "data:image" not in raw, god
        assert "<inline" not in raw, god
        meta = json.loads(raw)
        assert meta["display_name"]
        assert meta["domain"] == roster.get(god).domain
        assert ie.DOMAIN_SEP in meta["domain"] or "/" in meta["domain"], god
        assert meta["icon"] and not meta["icon"].startswith("data:")


def test_kairos_god_json_exists_even_though_the_live_profile_has_none(built):
    spec, _roster, engine = built
    meta = json.loads(ie.render_artifacts(engine, spec)["gods/kairos/god.json"])
    assert meta["display_name"] == "Kairos"
    assert meta["color"], "kairos ships with no colour — the kit must assign one"
    assert meta["icon"].startswith("/api/gods/kairos/")


def test_client_choices_land_in_the_artifacts(built):
    spec, _roster, engine = built
    artifacts = ie.render_artifacts(engine, spec)
    assert json.loads(artifacts["gods/thoth/god.json"])["display_name"] == "Oracle"
    assert json.loads(artifacts["gods/rheta/god.json"])["display_name"] == "Rheta"
    assert json.loads(artifacts["gods/caduceus/god.json"])["icon"] == "uploads/avatar-caduceus.png"
    assert "Oracle" in artifacts["gods/thoth/SOUL.md"]
    assert "Dry, precise" in artifacts["gods/thoth/persona.md"]
    assert "research" in artifacts["gods/thoth/MEMORY.md"]
    assert "{'owns'" not in artifacts["gods/thoth/MEMORY.md"]


def test_inline_image_is_refused_at_render_time(built):
    spec, _roster, engine = built
    engine.answer("iris/G7", "data:image/png;base64," + "A" * 5000)
    with pytest.raises(ie.SpecError):
        ie.render_artifacts(engine, spec)


def test_person_root_frontmatter_parses_and_carries_its_fields(built):
    spec, _roster, engine = built
    artifacts = ie.render_artifacts(engine, spec)
    profile = artifacts["person_roots/dana-reyes/PROFILE.md"]
    frontmatter = profile.split("---")[1]
    meta = yaml.safe_load(frontmatter)
    assert meta["person_id"] == "dana-reyes"
    assert meta["document_type"] == "profile"
    assert meta["display_name"] == "Dana Reyes"
    assert meta["direct_user"] is True
    assert meta["trust_tier"] == "tier_1_recognized"
    perms = yaml.safe_load(artifacts["person_roots/dana-reyes/PERMISSIONS.md"].split("---")[1])
    assert perms["document_type"] == "permissions"
    rows = artifacts["person_roots/INDEX_ROWS.md"]
    assert "| dana-reyes |" in rows and "| priya-shah |" in rows


def test_person_without_platform_ids_stays_open(built):
    spec, _roster, engine = built
    engine.answer("T3", [{"person": "Dana Reyes", "discord_id": "111111111111111111"}])
    artifacts = ie.render_artifacts(engine, spec)
    perms = artifacts["person_roots/priya-shah/PERMISSIONS.md"]
    assert "222222222222222222" not in perms
    assert "user_ids: []" in perms


def test_env_ships_no_secrets_and_carries_the_client_ids(built):
    spec, _roster, engine = built
    env = ie.render_artifacts(engine, spec)["gods/hermes/.env"]
    assert "111111111111111111" in env
    assert "333333333" in env
    for line in env.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        assert not value.startswith(("sk-", "ghp_", "ak_", "ck_", "eyJ", "data:"))
    assert "DISCORD_REQUIRE_MENTION=false" in env      # free-response lane default


def test_config_leaves_model_unset_for_the_onboarding_probe(built):
    spec, _roster, engine = built
    cfg = yaml.safe_load(ie.render_artifacts(engine, spec)["gods/hermes/config.yaml"])
    assert cfg["model"]["default"] is None
    assert cfg["model"]["provider"] is None
    assert "pantheon-background-ops" in cfg["plugins"]["enabled"]


def test_client_readme_states_the_roster_cut_limits(built):
    spec, _roster, engine = built
    readme = ie.render_artifacts(engine, spec)["CLIENT-README.md"]
    assert "No builder" in readme and "No sales god" in readme
    assert "Northwind Dental" in readme


def test_business_name_is_the_name_not_the_whole_paragraph(built):
    spec, _roster, engine = built
    tenant = json.loads(ie.render_artifacts(engine, spec)["tenant.json"])
    assert tenant["business_name"].strip() == "Northwind Dental"
    assert "4-chair" in tenant["about"]


def test_render_is_deterministic(built):
    spec, _roster, engine = built
    first = ie.render_artifacts(engine, spec, generated="2026-11-18")
    second = ie.render_artifacts(engine, spec, generated="2026-11-18")
    assert first == second


# ── the CLI is the same engine ─────────────────────────────────────────────

def test_cli_check_reports_ok(capsys):
    assert ie.main(["--check"]) == 0
    assert "spec check OK" in capsys.readouterr().out


def test_cli_end_to_end_renders_the_tree(tmp_path, capsys):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"answers": ANSWERS}), encoding="utf-8")
    out = tmp_path / "kit"
    code = ie.main(["--answers", str(answers), "--out", str(out), "--json"])
    assert code == 0, capsys.readouterr().err
    summary = json.loads(capsys.readouterr().out)
    assert summary["missing_from_seed_write"] == []
    assert (out / "tenant.json").exists()
    assert (out / "PHONEBOOK.json").exists()
    for god in ("hermes", "rheta", "iris", "thoth", "kairos", "caduceus"):
        for name in ("SOUL.md", "persona.md", "god.json", "MEMORY.md", ".env", "config.yaml"):
            assert (out / "gods" / god / name).exists(), f"{god}/{name}"
    assert (out / "athenaeum" / "Codex-God-Oracle" / "INDEX.md").exists()


def test_cli_start_lists_the_run_without_asking_anything(capsys):
    assert ie.main(["--start", "--json"]) == 0
    order = json.loads(capsys.readouterr().out)
    assert len(order) == 9 + 10 * 6
    assert all(row["writes_to"] for row in order)
