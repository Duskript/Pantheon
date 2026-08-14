"""Contract tests for the disposable Ichor canary doctor.

The Cash/ichor-canary incident crossed four surfaces at once: profile env
isolation, Discord routing, A2A clone drift, and OpenCode Go credential-pool
selection. The doctor script exists so the next canary can be checked with one
bounded, token-safe report instead of an ad-hoc debug sequence.

These tests pin three non-negotiable boundaries:

* report generation never includes secret values;
* default/read-only doctor runs do not mutate profile files; and
* repair mode is explicitly canary-scoped before it may rewrite benign A2A env
  metadata.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "doctor-ichor-canary.py"


def load_module():
    spec = importlib.util.spec_from_file_location("doctor_ichor_canary", SCRIPT)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_profile(root: Path, profile: str = "ichor-canary", *, a2a_name: str = "ichor-canary Pantheon") -> Path:
    profile_dir = root / profile
    profile_dir.mkdir(parents=True)
    (profile_dir / ".env").write_text(
        "DISCORD_BOT_TOKEN=super-secret-token-value\n"
        "DISCORD_ALLOWED_CHANNELS=1530994028206755871\n"
        "DISCORD_FREE_RESPONSE_CHANNELS=1530994028206755871\n"
        "DISCORD_HOME_CHANNEL=1530994028206755871\n"
        "A2A_AGENT_NAME=" + a2a_name + "\n"
        "A2A_PORT=9913\n"
        "OPENCODE_GO_API_KEY=super-secret-opencode-key\n",
        encoding="utf-8",
    )
    (profile_dir / "config.yaml").write_text(
        "auxiliary:\n"
        "  compression:\n"
        "    provider: opencode-go\n"
        "    model: deepseek-v4-flash\n"
        "    base_url: https://opencode.ai/zen/go/v1\n"
        "discord:\n"
        "  allowed_channels: '1530994028206755871'\n"
        "  free_response_channels: '1530994028206755871'\n",
        encoding="utf-8",
    )
    return profile_dir


def test_report_is_token_safe_and_ready_when_all_checks_pass(tmp_path):
    module = load_module()
    profile_dir = write_profile(tmp_path)

    def fake_runner(cmd):
        if cmd[:1] == ["ss"]:
            return module.CommandResult(0, "LISTEN 0 5 127.0.0.1:9913 0.0.0.0:* users:((\"hermes\",pid=123,fd=18))\n", "")
        return module.CommandResult(0, "active running 123 0 0\n", "")

    report = module.build_report(
        profile="ichor-canary",
        profile_dir=profile_dir,
        channel="1530994028206755871",
        runner=fake_runner,
        pool_loader=lambda provider: module.PoolSnapshot(
            provider=provider,
            selected_label="opencode-go-nextcloud-3",
            selected_status="ok",
            entries=[
                {"idx": 0, "label": "opencode-go-nextcloud-1", "status": "exhausted", "reason": "region_error"},
                {"idx": 1, "label": "opencode-go-nextcloud-2", "status": "exhausted", "reason": "GoUsageLimitError"},
                {"idx": 2, "label": "opencode-go-nextcloud-3", "status": "ok", "reason": None},
            ],
        ),
        allowlist_checker=lambda profile: True,
        compression_smoker=lambda: {"ok": True, "content": "successful"},
        token_exposed=True,
    )

    payload = json.dumps(report, sort_keys=True)
    assert report["ready"] is True
    assert report["profile_isolated"] is True
    assert report["discord_route_locked"] is True
    assert report["compression_provider"] == "opencode-go"
    assert report["compression_model"] == "deepseek-v4-flash"
    assert report["selected_pool_entry"] == "opencode-go-nextcloud-3"
    assert report["compression_smoke"] == "successful"
    assert report["canary_allowed_by_scripts"] is True
    assert report["token_rotation_required"] is True
    assert "super-secret" not in payload


def test_repair_refuses_non_canary_profile(tmp_path):
    module = load_module()
    profile_dir = write_profile(tmp_path, profile="thoth", a2a_name="thoth Pantheon")

    result = module.repair_profile_metadata(profile="thoth", profile_dir=profile_dir)

    assert result["applied"] is False
    assert result["reason"] == "repair_refused_non_canary_profile"
    assert "thoth Pantheon" in (profile_dir / ".env").read_text(encoding="utf-8")


def test_repair_updates_only_canary_a2a_metadata_and_preserves_secret_lines(tmp_path):
    module = load_module()
    profile_dir = write_profile(tmp_path, a2a_name="thoth Pantheon")

    result = module.repair_profile_metadata(profile="ichor-canary", profile_dir=profile_dir)

    env_text = (profile_dir / ".env").read_text(encoding="utf-8")
    assert result["applied"] is True
    assert result["changes"] == {"A2A_AGENT_NAME": "ichor-canary Pantheon"}
    assert "A2A_AGENT_NAME=ichor-canary Pantheon" in env_text
    assert "DISCORD_BOT_TOKEN=super-secret-token-value" in env_text
    assert "OPENCODE_GO_API_KEY=super-secret-opencode-key" in env_text
