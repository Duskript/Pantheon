"""Contract tests for the client-kit conductor onboarding (Phase 3).

PURE UNIT TESTS — no network, no live guild, no real token. The Discord transport
is injectable, so the call sequence is asserted against a fake that records what
it was asked to do; nothing here can touch a client's server.

Pinned here:
  * the permission split — a worker invite must be *refused* for the conductor,
    because the failure otherwise lands on a live guild at "create the category"
  * a token is never printable: the invite URL carries only the decoded numeric
    client_id, and the leak guard actually fires
  * the mesh plan is ordered, reuse-first, complete (one lane per shipped god),
    and contains no destructive op
  * per-god lane config keeps exactly one god answering in exactly one lane
  * a missing Telegram dependency is a refusal naming the fix, not a silent skip
"""
from __future__ import annotations

import base64
import importlib.util
import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
KIT = REPO / "client-kit"


def _load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


co = _load("conductor_onboard", KIT / "conductor_onboard.py")

SHIPPED = ["hermes", "rheta", "iris", "thoth", "kairos", "caduceus"]
SNOWFLAKE = "1499845064359280710"


def fake_token(client_id: str = SNOWFLAKE, secret: str = "sEcReT-sEgMeNt-xyz") -> str:
    """A format-accurate but entirely synthetic bot token."""
    head = base64.b64encode(client_id.encode()).decode().rstrip("=")
    return f"{head}.{secret}.{'f' * 32}"


@pytest.fixture(scope="module")
def manifest():
    return co.load_manifest()


class FakeTransport:
    """Records the calls instead of making them."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.token = fake_token()

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        return 200, {"id": f"id-{len(self.calls)}", "name": (payload or {}).get("name")}


# ── the permission split ───────────────────────────────────────────────────

def test_worker_permissions_are_the_documented_least_privilege_set():
    assert co.WORKER_PERMISSIONS == 379968
    assert co.permission_names(co.WORKER_PERMISSIONS) == [
        "ADD_REACTIONS", "VIEW_CHANNEL", "SEND_MESSAGES", "EMBED_LINKS",
        "ATTACH_FILES", "READ_MESSAGE_HISTORY", "USE_EXTERNAL_EMOJIS",
    ]


def test_conductor_permissions_are_worker_plus_the_four_elevated_bits():
    assert co.CONDUCTOR_PERMISSIONS == (
        379968 | 16 | 268435456 | 34359738368 | 17179869184
    )
    for name in co.CONDUCTOR_ONLY_BITS:
        assert co.CONDUCTOR_PERMISSIONS & co.PERMISSION_BITS[name], name


def test_a_worker_invite_is_refused_for_the_conductor():
    """The whole point of the split: this must fail before it hits a live guild."""
    missing = co.missing_conductor_permissions(co.WORKER_PERMISSIONS)
    assert set(missing) == set(co.CONDUCTOR_ONLY_BITS)
    with pytest.raises(co.ConductorError) as exc:
        co.check_conductor_permissions(co.WORKER_PERMISSIONS)
    assert "MANAGE_CHANNELS" in str(exc.value)
    co.check_conductor_permissions(co.CONDUCTOR_PERMISSIONS)  # must not raise


# ── tokens and invites ─────────────────────────────────────────────────────

def test_client_id_is_decoded_from_the_token_and_the_token_is_not_returned():
    token = fake_token()
    assert co.client_id_from_token(token) == SNOWFLAKE
    assert token not in co.client_id_from_token(token)


@pytest.mark.parametrize("bad", ["", "not-a-token", "only.two", base64.b64encode(b"abc").decode() + ".x.y"])
def test_malformed_tokens_are_refused(bad):
    with pytest.raises(co.ConductorError):
        co.client_id_from_token(bad)


def test_invite_url_carries_the_client_id_and_never_the_token():
    token = fake_token()
    url = co.invite_url(co.client_id_from_token(token), co.WORKER_PERMISSIONS)
    assert f"client_id={SNOWFLAKE}" in url
    assert f"permissions={co.WORKER_PERMISSIONS}" in url
    assert "scope=bot%20applications.commands" in url
    assert token not in url


def test_invite_plan_marks_an_unsupplied_token_as_open_not_guessed(manifest):
    rows = co.invite_plan(manifest)
    assert [r["god"] for r in rows] == SHIPPED
    assert all(r["client_id"] is None and "open" in r["status"] for r in rows)
    assert [r["permissions"] for r in rows if r["role"] == "conductor"] == [co.CONDUCTOR_PERMISSIONS]
    assert all(r["permissions"] == co.WORKER_PERMISSIONS for r in rows if r["role"] == "worker")


def test_invite_plan_uses_the_conductor_permissions_for_the_conductor(manifest):
    rows = co.invite_plan(manifest, {manifest["conductor"]: fake_token()})
    conductor = next(r for r in rows if r["role"] == "conductor")
    assert conductor["status"] == "ready"
    assert conductor["permissions"] == co.CONDUCTOR_PERMISSIONS
    assert conductor["invite_url"] and SNOWFLAKE in conductor["invite_url"]


def test_the_leak_guard_fires():
    token = fake_token()
    co.assert_no_token_leak("nothing secret here", [token])
    with pytest.raises(co.ConductorError):
        co.assert_no_token_leak(f"url?token={token}", [token])


# ── the mesh plan ──────────────────────────────────────────────────────────

def test_discord_mesh_plan_is_ordered_complete_and_non_destructive(manifest):
    plan = co.plan_discord_mesh(manifest, "1499851384814702783", manifest and None)
    assert plan["guild_id"] == "1499851384814702783"
    assert plan["category"]["policy"] == "reuse-or-create"
    assert [c["god"] for c in plan["channels"]] == SHIPPED
    assert all(c["name"] and " " not in c["name"] for c in plan["channels"])

    ops = [(a["op"], a["target"]) for a in plan["actions"]]
    assert ops[0] == ("GET", "/guilds/1499851384814702783")
    assert ops[1] == ("GET", "/guilds/1499851384814702783/channels")
    assert ops[2] == ("POST", "/guilds/1499851384814702783/channels")   # category first
    assert len([o for o in ops if o == ("POST", "/guilds/1499851384814702783/channels")]) == 7
    assert ops[-1] == ("PATCH", "/users/@me")
    assert not any(a["destructive"] for a in plan["actions"])
    assert not any("DELETE" in a["op"] for a in plan["actions"])


def test_telegram_mesh_plan_reports_the_missing_dependency_and_still_plans(manifest):
    plan = co.plan_telegram_mesh(manifest, "-1003814664247")
    assert [c["god"] for c in plan["channels"]] == SHIPPED
    availability = plan["availability"]
    if not availability["available"]:
        assert co.TELEGRAM_DEP in availability["reason"]
        assert "pip install" in availability["fix"]
        assert availability["what_still_works"]
    assert any(a["target"] == "telegram.extra.ignored_threads" for a in plan["actions"])
    assert any(a["op"] == "USERBOT" for a in plan["actions"])


# ── lanes: one god, one lane ───────────────────────────────────────────────

def test_free_response_lane_answers_without_a_mention(manifest):
    meta = manifest["gods"]["rheta"]
    env = co.lane_env("rheta", meta, platform="discord", channel_id="1522263522078363861",
                      lane=co.LANE_FREE, allowed_users=["180817012619083776"])
    assert env["DISCORD_REQUIRE_MENTION"] == "false"
    assert env["DISCORD_IGNORE_NO_MENTION"] == "false"
    assert env["DISCORD_FREE_RESPONSE_CHANNELS"] == env["DISCORD_ALLOWED_CHANNELS"] == "1522263522078363861"
    assert env["DISCORD_HOME_CHANNEL_NAME"] == "Rheta"
    assert env["DISCORD_ALLOWED_USERS"] == "180817012619083776"
    assert "TELEGRAM_HOME_CHANNEL" not in env


def test_mention_only_lane_does_not_get_free_response(manifest):
    env = co.lane_env("rheta", manifest["gods"]["rheta"], platform="discord",
                      channel_id="1", lane=co.LANE_MENTION)
    assert env["DISCORD_REQUIRE_MENTION"] == "true"
    assert env["DISCORD_FREE_RESPONSE_CHANNELS"] == ""
    assert env["DISCORD_IGNORE_NO_MENTION"] == "true"


def test_telegram_lane_adds_the_group_gates(manifest):
    env = co.lane_env("thoth", manifest["gods"]["thoth"], platform="telegram",
                      channel_id="-1003814664247", lane=co.LANE_FREE,
                      allowed_users=["1460056890"])
    assert env["TELEGRAM_GROUP_ALLOWED_CHATS"] == "-1003814664247"
    assert env["TELEGRAM_GROUP_ALLOWED_USERS"] == "1460056890"


def test_topic_config_is_a_hard_inbound_gate():
    cfg = co.telegram_topic_config("thoth", {"display_name": "Thoth"}, "19")
    assert cfg["telegram.allowed_topics"] == ["19"]
    assert cfg["telegram.extra.ignored_threads"] == [1]
    assert cfg["telegram.free_response_topics"] == ["<chat_id>:19"]
    mention_only = co.telegram_topic_config("thoth", {"display_name": "Thoth"}, "19",
                                            lane=co.LANE_MENTION)
    assert mention_only["telegram.free_response_topics"] == []


# ── phonebook ──────────────────────────────────────────────────────────────

def test_phonebook_matches_the_live_schema_and_never_fabricates_a_channel(manifest):
    payload = json.loads(co.phonebook(manifest, {"thoth": "1522263525605773332"}))
    assert payload["schema_version"] == "1.0"
    assert payload["conductor"] == "hermes"
    assert set(payload["gods"]) == set(SHIPPED)
    assert payload["gods"]["thoth"]["home_channel"] == "1522263525605773332"
    assert payload["gods"]["thoth"]["discord_bot"] is True
    assert payload["gods"]["rheta"]["home_channel"] is None      # not invented
    for god, row in payload["gods"].items():
        for dest in row["routes_to"].values():
            assert dest in SHIPPED, f"{god} -> {dest}"


# ── execution ──────────────────────────────────────────────────────────────

def test_dry_run_needs_no_credentials_and_calls_nothing(manifest):
    plan = co.plan_discord_mesh(manifest, "1")
    executor = co.MeshExecutor(None, dry_run=True)
    log = executor.apply(plan["actions"])
    assert len(log) == len(plan["actions"])
    assert all(row["result"] == "dry-run" for row in log)


def test_apply_without_a_token_is_refused(manifest):
    plan = co.plan_discord_mesh(manifest, "1")
    executor = co.MeshExecutor(None, dry_run=False)
    with pytest.raises(co.ConductorError):
        executor.apply(plan["actions"])


def test_apply_replays_the_plan_in_order_against_the_transport(manifest):
    plan = co.plan_discord_mesh(manifest, "999")
    transport = FakeTransport()
    log = co.MeshExecutor(transport, dry_run=False).apply(plan["actions"])
    assert [c[0] for c in transport.calls] == [a["op"] for a in plan["actions"]]
    assert transport.calls[0][1] == "/guilds/999"
    assert sum(1 for c in transport.calls if c[0] == "POST") == 7
    assert all(row["ok"] for row in log)


def test_a_destructive_action_is_refused_outright():
    executor = co.MeshExecutor(FakeTransport(), dry_run=False)
    with pytest.raises(co.ConductorError) as exc:
        executor.apply([co.MeshAction("DELETE", "/channels/123")])
    assert "unrecoverable" in str(exc.value)
    assert executor.apply.__self__.log == []


# ── verification checklist ─────────────────────────────────────────────────

def test_verification_checklist_carries_the_observed_signals():
    discord = co.verify_checklist("discord")
    assert [row["id"] for row in discord] == ["adapter", "lane", "containment", "phase"]
    assert all(row["done"] is False for row in discord)     # nothing is done unobserved

    telegram = co.verify_checklist("telegram")
    lock = next(row for row in telegram if row["id"] == "lock")
    assert "not in allowed_topics" in lock["expected"]
    with pytest.raises(co.ConductorError):
        co.verify_checklist("slack")


# ── CLI ────────────────────────────────────────────────────────────────────

def test_cli_check_is_green(capsys):
    assert co.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "conductor check OK" in out
    assert str(co.CONDUCTOR_PERMISSIONS) in out


def test_cli_plan_is_json_and_leaks_nothing(capsys):
    assert co.main(["--plan", "--guild-id", "123456789012345678", "--json"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert len(plan["channels"]) == 6
    assert plan["invites"]


def test_cli_verify_marks_nothing_done(capsys):
    assert co.main(["--verify", "--platform", "telegram"]) == 0
    out = capsys.readouterr().out
    assert out.count("[ ]") == 4
    assert "[x]" not in out


def test_cli_dry_run_prints_the_call_list_without_credentials(capsys):
    assert co.main(["--guild-id", "123456789012345678"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "one lane for Caduceus" in out


def test_cli_apply_without_a_token_fails_cleanly(capsys):
    code = co.main(["--guild-id", "123456789012345678", "--apply"])
    captured = capsys.readouterr()
    assert code == 2, f"expected a clean refusal, got {code}"
    assert "token" in (captured.out + captured.err).lower()
