#!/usr/bin/env python3
"""Ichor disposable canary doctor.

This command turns the Cash/ichor-canary lessons into a repeatable preflight
report. Default mode is read-only and token-safe: it reports booleans, routing
IDs, provider/model names, pool entry labels/statuses, and service state, but
never prints API keys or Discord bot tokens.

Optional ``--repair`` is deliberately narrow. It only rewrites benign A2A
metadata in a profile whose name contains ``canary``; it never touches tokens,
never restarts gateways, never changes fleet defaults, and never mutates
production god profiles.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

try:
    import yaml
except Exception:  # pragma: no cover - yaml is present in normal Pantheon env
    yaml = None


DEFAULT_PROFILE_ROOT = Path.home() / ".hermes" / "profiles"
SCRIPT_PATH = Path(__file__).resolve()
PANTHEON_ROOT = SCRIPT_PATH.parents[1]
PROFILE_BOOTSTRAP_APPLY = PANTHEON_ROOT / "conductor" / "scripts" / "profile-bootstrap-apply.py"
EXPECTED_PROVIDER = "opencode-go"
EXPECTED_MODEL = "deepseek-v4-flash"
EXPECTED_BASE_URL = "https://opencode.ai/zen/go/v1"


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass
class PoolSnapshot:
    provider: str
    selected_label: str | None
    selected_status: str | None
    entries: list[dict[str, Any]]
    error: str | None = None


def run_command(cmd: list[str], timeout: int = 20) -> CommandResult:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return CommandResult(result.returncode, result.stdout, result.stderr)
    except Exception as exc:
        return CommandResult(1, "", f"{type(exc).__name__}: {exc}")


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists() or path.is_symlink():
        return values
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="ignore"))
    return data if isinstance(data, dict) else {}


def env_has_key(env_values: dict[str, str], key: str) -> bool:
    return bool(env_values.get(key))


def channels_match(env_values: dict[str, str], config: dict[str, Any], channel: str) -> bool:
    raw_discord_cfg = config.get("discord")
    discord_cfg: dict[str, Any] = raw_discord_cfg if isinstance(raw_discord_cfg, dict) else {}
    candidates = [
        env_values.get("DISCORD_ALLOWED_CHANNELS", ""),
        env_values.get("DISCORD_FREE_RESPONSE_CHANNELS", ""),
        env_values.get("DISCORD_HOME_CHANNEL", ""),
        str(discord_cfg.get("allowed_channels", "")),
        str(discord_cfg.get("free_response_channels", "")),
    ]
    return bool(channel) and all(channel in c for c in candidates if c)


def compression_config(config: dict[str, Any]) -> dict[str, str]:
    raw_auxiliary = config.get("auxiliary")
    auxiliary: dict[str, Any] = raw_auxiliary if isinstance(raw_auxiliary, dict) else {}
    raw_compression = auxiliary.get("compression")
    compression: dict[str, Any] = raw_compression if isinstance(raw_compression, dict) else {}
    return {
        "provider": str(compression.get("provider", "") or ""),
        "model": str(compression.get("model", "") or ""),
        "base_url": str(compression.get("base_url", "") or ""),
    }


def load_pool_snapshot(provider: str, profile_dir: Path) -> PoolSnapshot:
    old_home = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(profile_dir)
    try:
        hermes_path = "/usr/local/lib/hermes-agent"
        if hermes_path not in sys.path:
            sys.path.insert(0, hermes_path)
        from agent.credential_pool import load_pool

        pool = load_pool(provider)
        selected = pool.select() if pool else None
        entries: list[dict[str, Any]] = []
        for idx, entry in enumerate(pool.entries() if pool else []):
            entries.append({
                "idx": idx,
                "label": getattr(entry, "label", None),
                "source": getattr(entry, "source", None),
                "status": getattr(entry, "last_status", None),
                "reason": getattr(entry, "last_error_reason", None),
                "error_code": getattr(entry, "last_error_code", None),
            })
        return PoolSnapshot(
            provider=provider,
            selected_label=getattr(selected, "label", None) if selected else None,
            selected_status=getattr(selected, "last_status", None) if selected else None,
            entries=entries,
        )
    except Exception as exc:
        return PoolSnapshot(provider=provider, selected_label=None, selected_status=None, entries=[], error=f"{type(exc).__name__}: {exc}")
    finally:
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home


def check_gateway(profile: str, runner: Callable[[list[str]], CommandResult]) -> dict[str, Any]:
    unit = f"hermes-gateway@{profile}.service"
    result = runner([
        "systemctl", "--user", "show", unit,
        "-p", "ActiveState", "-p", "SubState", "-p", "MainPID", "-p", "ExecMainStatus", "-p", "NRestarts",
        "--value",
    ])
    values = result.stdout.split()
    return {
        "unit": unit,
        "ok": result.returncode == 0 and len(values) >= 2 and values[0] == "active" and values[1] == "running",
        "raw": " ".join(values[:5]),
        "error": result.stderr.strip()[:240] if result.returncode != 0 else None,
    }


def check_a2a_listen(port: str, runner: Callable[[list[str]], CommandResult]) -> dict[str, Any]:
    if not port:
        return {"ok": False, "port": "", "listening": False}
    result = runner(["ss", "-ltnp"])
    listening = f":{port} " in result.stdout
    return {"ok": result.returncode == 0 and listening, "port": port, "listening": listening}


def check_canary_allowlist(profile: str) -> bool:
    if not PROFILE_BOOTSTRAP_APPLY.exists():
        return False
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        canonical = root / "canonical" / "devops" / "example-skill"
        canonical.mkdir(parents=True)
        (canonical / "SKILL.md").write_text("---\nname: example-skill\n---\n# Example\n", encoding="utf-8")
        no_canon = root / "no-canon.txt"
        no_canon.write_text("# empty\n", encoding="utf-8")
        result = run_command([
            sys.executable,
            str(PROFILE_BOOTSTRAP_APPLY),
            "--god", profile,
            "--canonical-root", str(root / "canonical"),
            "--profiles-root", str(root / "profiles"),
            "--no-canon-report", str(no_canon),
            "--json",
        ])
        return result.returncode == 0


def smoke_compression(profile_dir: Path) -> dict[str, Any]:
    old_home = os.environ.get("HERMES_HOME")
    os.environ["HERMES_HOME"] = str(profile_dir)
    try:
        hermes_path = "/usr/local/lib/hermes-agent"
        if hermes_path not in sys.path:
            sys.path.insert(0, hermes_path)
        from agent.auxiliary_client import call_llm

        resp = call_llm(
            task="compression",
            messages=[{"role": "user", "content": "Compress this to one word: successful successful successful"}],
            max_tokens=16,
            timeout=60,
        )
        content = (resp.choices[0].message.content or "").strip()
        return {"ok": True, "content": content[:80]}
    except Exception as exc:
        return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:240]}
    finally:
        if old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = old_home


def build_report(
    *,
    profile: str,
    profile_dir: Path,
    channel: str,
    runner: Callable[[list[str]], CommandResult] = run_command,
    pool_loader: Callable[[str], PoolSnapshot] | None = None,
    allowlist_checker: Callable[[str], bool] = check_canary_allowlist,
    compression_smoker: Callable[[], dict[str, Any]] | None = None,
    token_exposed: bool = False,
) -> dict[str, Any]:
    env_path = profile_dir / ".env"
    config_path = profile_dir / "config.yaml"
    env_values = parse_env_file(env_path)
    config = load_yaml(config_path)
    compression = compression_config(config)
    gateway = check_gateway(profile, runner)
    a2a = check_a2a_listen(env_values.get("A2A_PORT", ""), runner)
    pool_loader = pool_loader or (lambda provider: load_pool_snapshot(provider, profile_dir))
    pool = pool_loader(compression["provider"] or EXPECTED_PROVIDER)
    smoke = compression_smoker() if compression_smoker else {"ok": None, "content": None}

    profile_exists = profile_dir.exists()
    profile_isolated = env_path.exists() and not env_path.is_symlink()
    discord_route_locked = channels_match(env_values, config, channel)
    a2a_identity_ok = env_values.get("A2A_AGENT_NAME") == f"{profile} Pantheon"
    compression_lane_ok = (
        compression["provider"] == EXPECTED_PROVIDER
        and compression["model"] == EXPECTED_MODEL
        and compression["base_url"].rstrip("/") == EXPECTED_BASE_URL
    )
    selected_pool_ok = bool(pool.selected_label) and pool.selected_status in {None, "ok"}
    canary_allowed = allowlist_checker(profile)
    compression_ok = smoke.get("ok") in {True, None}

    checks = {
        "profile_exists": profile_exists,
        "profile_isolated": profile_isolated,
        "discord_token_present": env_has_key(env_values, "DISCORD_BOT_TOKEN"),
        "discord_route_locked": discord_route_locked,
        "a2a_identity_ok": a2a_identity_ok,
        "a2a_listening": a2a["ok"],
        "gateway_active": gateway["ok"],
        "compression_lane_ok": compression_lane_ok,
        "selected_pool_ok": selected_pool_ok,
        "canary_allowed_by_scripts": canary_allowed,
        "compression_smoke_ok": compression_ok,
    }
    ready = all(checks.values())

    return {
        "profile": profile,
        "profile_path": str(profile_dir),
        "ready": ready,
        **checks,
        "a2a_port": env_values.get("A2A_PORT", ""),
        "gateway": gateway,
        "compression_provider": compression["provider"],
        "compression_model": compression["model"],
        "compression_base_url": compression["base_url"],
        "pool_provider": pool.provider,
        "selected_pool_entry": pool.selected_label,
        "selected_pool_status": pool.selected_status,
        "pool_entries": pool.entries,
        "pool_error": pool.error,
        "canary_allowed_by_scripts": canary_allowed,
        "compression_smoke": smoke.get("content") if smoke.get("ok") else None,
        "compression_smoke_error": None if smoke.get("ok") else smoke,
        "token_rotation_required": bool(token_exposed),
        "repair_recommendations": repair_recommendations(profile, env_values, checks),
    }


def repair_recommendations(profile: str, env_values: dict[str, str], checks: dict[str, bool]) -> list[str]:
    recs: list[str] = []
    if not checks.get("a2a_identity_ok", False):
        recs.append(f"set A2A_AGENT_NAME={profile} Pantheon")
    if not checks.get("profile_isolated", False):
        recs.append("replace symlinked/missing .env with isolated profile .env before testing")
    if not checks.get("discord_route_locked", False):
        recs.append("align DISCORD_ALLOWED_CHANNELS/FREE_RESPONSE/HOME with the canary channel")
    return recs


def repair_profile_metadata(*, profile: str, profile_dir: Path) -> dict[str, Any]:
    if "canary" not in profile:
        return {"applied": False, "reason": "repair_refused_non_canary_profile", "changes": {}}
    env_path = profile_dir / ".env"
    if not env_path.exists() or env_path.is_symlink():
        return {"applied": False, "reason": "env_missing_or_symlinked", "changes": {}}
    lines = env_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    target_name = f"{profile} Pantheon"
    changes: dict[str, str] = {}
    new_lines: list[str] = []
    saw_name = False
    for line in lines:
        if line.startswith("A2A_AGENT_NAME="):
            saw_name = True
            if line != f"A2A_AGENT_NAME={target_name}":
                line = f"A2A_AGENT_NAME={target_name}"
                changes["A2A_AGENT_NAME"] = target_name
        new_lines.append(line)
    if not saw_name:
        new_lines.append(f"A2A_AGENT_NAME={target_name}")
        changes["A2A_AGENT_NAME"] = target_name
    if changes:
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return {"applied": bool(changes), "reason": "ok", "changes": changes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Token-safe doctor for the Ichor disposable canary profile.")
    parser.add_argument("--profile", default="ichor-canary")
    parser.add_argument("--channel", default="")
    parser.add_argument("--profiles-root", type=Path, default=DEFAULT_PROFILE_ROOT)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--smoke-compression", action="store_true", help="make one real auxiliary compression LLM call")
    parser.add_argument("--token-exposed", action="store_true", help="mark report with token_rotation_required=true")
    parser.add_argument("--repair", action="store_true", help="repair only benign canary profile metadata; never restarts services")
    args = parser.parse_args(argv)

    profile_dir = args.profiles_root / args.profile
    repair_result = None
    if args.repair:
        repair_result = repair_profile_metadata(profile=args.profile, profile_dir=profile_dir)

    report = build_report(
        profile=args.profile,
        profile_dir=profile_dir,
        channel=args.channel,
        compression_smoker=(lambda: smoke_compression(profile_dir)) if args.smoke_compression else None,
        token_exposed=args.token_exposed,
    )
    if repair_result is not None:
        report["repair_result"] = repair_result

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"profile={report['profile']} ready={report['ready']} selected_pool={report['selected_pool_entry']}")
        print(f"compression={report['compression_provider']}/{report['compression_model']} smoke={report['compression_smoke']}")
        if report["repair_recommendations"]:
            print("repair_recommendations:")
            for rec in report["repair_recommendations"]:
                print(f"- {rec}")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
