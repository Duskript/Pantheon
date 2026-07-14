#!/usr/bin/env python3
"""Phase D health guardian for Pantheon observability.

This script checks the Ichor MCP surface, the Accordion context engine,
the Pantheon-core hook plugin, and the comparison report directory. It is
silent when the system is healthy and prints a compact report only when a
component is broken or divergence is detected.
"""
from __future__ import annotations

import argparse
import subprocess
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PANTHEON_ROOT = SCRIPT_DIR.parent
HERMES_AGENT_ROOT = PANTHEON_ROOT / "hermes-agent"
for _path in (str(PANTHEON_ROOT), str(HERMES_AGENT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

sys.path.insert(0, str(SCRIPT_DIR))
from comparison_report import DEFAULT_COMPARISON_DIR, summarize_comparison_logs

DEFAULT_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DEFAULT_HOOKS_DIR = DEFAULT_HERMES_HOME / "hooks" / "pantheon-core"


def _status(component: str, healthy: bool, detail: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "component": component,
        "status": "ok" if healthy else "dead",
        "detail": detail,
    }
    payload.update(extra)
    return payload


def probe_ichor_mcp() -> dict[str, Any]:
    try:
        from lib import ichor_mcp

        health = json.loads(ichor_mcp.ichor_health())
        stats = json.loads(ichor_mcp.ichor_stats())
        audit = json.loads(ichor_mcp.ichor_audit(20))
        healthy = not health.get("error") and health.get("healthy", False)
        detail = f"healthy={healthy} folds={stats.get('fold_count', 0)} expands={stats.get('expand_count', 0)} audit={audit.get('count', 0)}"
        return _status("Ichor MCP", bool(healthy), detail, health=health, stats=stats, audit=audit)
    except Exception as exc:
        return _status("Ichor MCP", False, f"{type(exc).__name__}: {exc}")


def probe_accordion_engine() -> dict[str, Any]:
    try:
        from plugins.context_engine import load_context_engine

        engine = load_context_engine("accordion")
        if engine is None:
            return _status("Accordion", False, "accordion engine not loaded")
        detail = f"loaded tail={getattr(engine, 'working_tail', '?')} threshold={getattr(engine, 'threshold_percent', '?')}"
        return _status("Accordion", True, detail, engine=getattr(engine, 'name', 'accordion'))
    except Exception as exc:
        return _status("Accordion", False, f"{type(exc).__name__}: {exc}")


def probe_pantheon_core() -> dict[str, Any]:
    try:
        from hermes_cli.plugins import PluginManager

        os.environ.setdefault("HERMES_BUNDLED_PLUGINS", str(HERMES_AGENT_ROOT / "plugins"))
        mgr = PluginManager()
        mgr.discover_and_load()
        plugin = mgr._plugins.get("pantheon-core")
        if plugin is None:
            return _status("Hook Plugin", False, "pantheon-core plugin not loaded")
        hooks = set(getattr(plugin, "hooks_registered", []))
        expected = {"pre_llm_call", "pre_tool_call", "post_tool_call", "on_session_start", "on_session_finalize"}
        healthy = expected.issubset(hooks)
        detail = f"{len(hooks)}/5 hooks registered"
        return _status("Hook Plugin", healthy, detail, hooks=sorted(hooks))
    except Exception as exc:
        return _status("Hook Plugin", False, f"{type(exc).__name__}: {exc}")


def probe_comparison_report() -> dict[str, Any]:
    try:
        summary = summarize_comparison_logs(DEFAULT_COMPARISON_DIR)
        healthy = summary.get("divergence_count", 0) == 0
        detail = f"{summary.get('divergence_count', 0)} divergences, {summary.get('total_entries', 0)} comparison entries"
        return _status("Comparison Report", healthy, detail, summary=summary)
    except Exception as exc:
        return _status("Comparison Report", False, f"{type(exc).__name__}: {exc}")


def collect_observability_state() -> dict[str, Any]:
    components = [
        probe_ichor_mcp(),
        probe_accordion_engine(),
        probe_pantheon_core(),
        probe_comparison_report(),
    ]
    warning_count = sum(1 for item in components if item["status"] == "warning")
    dead_count = sum(1 for item in components if item["status"] == "dead")
    equivalence = next((item.get("summary", {}) for item in components if item["component"] == "Comparison Report"), {})
    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "components": components,
        "warning_count": warning_count,
        "dead_count": dead_count,
        "equivalence": {
            "status": "ok" if equivalence.get("divergence_count", 0) == 0 else "warning",
            "detail": f"{equivalence.get('divergence_count', 0)} divergences",
        },
    }


def render_guardian_text(state: dict[str, Any]) -> str:
    unhealthy = [item for item in state.get("components", []) if item.get("status") != "ok"]
    if not unhealthy and state.get("equivalence", {}).get("status") == "ok":
        return ""

    lines = [
        f"Health Guardian — {state.get('timestamp', '')}",
        "─────────────────────────────────────",
    ]
    for item in state.get("components", []):
        status = item.get("status", "dead")
        icon = {"ok": "✅", "warning": "⚠️", "dead": "✗"}.get(status, "?")
        label = f"{item.get('component', 'Unknown'):14s}"
        state_word = "HEALTHY" if status == "ok" else "UNHEALTHY"
        lines.append(f"{icon} {label} {state_word:10s} {item.get('detail', '')}")
    lines.append(f"Equivalence:    {state.get('equivalence', {}).get('detail', 'unknown')}")
    return "\n".join(lines).strip() + "\n"




def notify_guardian(state: dict[str, Any]) -> None:
    body = render_guardian_text(state).strip() or "Pantheon observability is unhealthy."
    title = f"{state.get('dead_count', 0)} dead / {state.get('warning_count', 0)} warning in observability"
    god_notify = Path.home() / ".local" / "bin" / "god-notify"
    if god_notify.is_file():
        subprocess.Popen(
            [str(god_notify), "Hephaestus", "error", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pantheon health guardian")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args(argv)

    state = collect_observability_state()
    text = render_guardian_text(state)
    healthy = state.get("dead_count", 0) == 0 and state.get("warning_count", 0) == 0 and state.get("equivalence", {}).get("status") == "ok"

    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
    elif not healthy:
        print(text, end="")

    if not healthy:
        notify_guardian(state)

    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
