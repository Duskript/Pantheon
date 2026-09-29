#!/usr/bin/env python3
"""Phase D health guardian for Pantheon observability.

Checks the Ichor MCP surface, the context engine the live config selects, the
lifecycle hooks the *deployed* plugins actually register, and the comparison
report directory. It is silent when the system is healthy and prints a compact
report only when a component is broken or divergence is detected.

Two probes used to report permanent false deaths because they were pinned to
components that only exist in Pantheon's vendored 0.17.0 checkout:

* ``probe_accordion_engine`` hardcoded ``load_context_engine("accordion")``.
  The accordion engine is absent from the fleet runtime, and
  ``~/.hermes/config.yaml`` selects ``context.engine: compressor`` (the built-in
  ContextCompressor), so the probe could never pass. It is now
  ``probe_context_engine``: it resolves whatever engine the live config selects,
  mirroring ``agent_init``'s resolution order -- which is also how a real
  misconfiguration (``context.engine: <name>`` with the plugin missing) gets
  caught.
* ``probe_pantheon_core`` hardcoded the ``pantheon-core`` plugin name and the
  ``~/.hermes/hooks/pantheon-core`` directory. That plugin is a Phase-B
  prototype that is not installed in the fleet -- the hooks directory holds only
  comparison-report data -- so the probe could never pass either. It is now
  ``probe_pantheon_hooks``: it asks the live plugin manager which plugins
  declare lifecycle hooks in their manifest and verifies that each declared hook
  was really registered.

A component genuinely absent from this deployment reports ``n/a`` (NOT
DEPLOYED) instead of ``dead``. ``n/a`` never makes the guardian unhealthy and
never fires a notification, but it stays visible in ``--json`` and in the text
report whenever anything else is wrong: an unmeasured lane is reported as
unmeasured rather than silently green.
"""
from __future__ import annotations

# stdlib only, plus yaml imported lazily inside _live_config(): the guardian
# probes other trees' imports, so its own import list stays minimal and cannot
# be the thing that breaks it.
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PANTHEON_ROOT = SCRIPT_DIR.parent


def _resolve_hermes_agent_root() -> tuple[Path, str]:
    """Locate the Hermes tree this host actually RUNS, not the nearest copy.

    This used to be hardcoded to ``PANTHEON_ROOT / "hermes-agent"`` -- the
    vendored 0.17.0 checkout inside Pantheon's own git. The fleet runs 0.20.0
    from ``~/.hermes/runtimes/fleet/hermes-agent``, so the guardian was
    importing ``hermes_cli.plugins`` from a tree no god executes and auditing an
    implementation that was not running. A probe against a dead tree cannot
    detect a live failure; that is the "reports success while doing nothing"
    class this whole audit is about.

    Resolution order, first hit wins:
        1. ``HERMES_AGENT_ROOT`` env override (explicit wins, always).
        2. ``$HERMES_HOME/runtimes/fleet/hermes-agent`` -- the live fleet runtime.
        3. ``~/.hermes/hermes-agent`` -- the entrypoint tree.
        4. the vendored Pantheon checkout (last resort; reported, never silent).

    A candidate only counts if it really contains ``hermes_cli/__init__.py``.
    """
    hermes_home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    candidates = (
        (os.environ.get("HERMES_AGENT_ROOT"), "HERMES_AGENT_ROOT env override"),
        (str(hermes_home / "runtimes" / "fleet" / "hermes-agent"), "live fleet runtime"),
        (str(Path.home() / ".hermes" / "hermes-agent"), "entrypoint tree"),
        (str(PANTHEON_ROOT / "hermes-agent"), "vendored pantheon checkout"),
    )
    for raw, label in candidates:
        if not raw:
            continue
        path = Path(raw)
        if (path / "hermes_cli" / "__init__.py").is_file():
            return path, label
    return PANTHEON_ROOT / "hermes-agent", "UNRESOLVED (no candidate had hermes_cli/)"


HERMES_AGENT_ROOT, HERMES_AGENT_ROOT_SOURCE = _resolve_hermes_agent_root()

# Order matters: each insert(0) pushes earlier entries right, so insert lowest
# priority first. Remove-then-insert unconditionally -- a plain "if not in
# sys.path" guard leaves ~/pantheon at index 0 whenever PYTHONPATH already
# contains it, and pantheon's stub `hermes_cli` (4 modules against the real
# 189) then shadows the real package: `hermes_cli.config` / `.auth` /
# `._subprocess_compat` all raise ModuleNotFoundError.
for _path in (str(PANTHEON_ROOT), str(HERMES_AGENT_ROOT)):
    while _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

sys.path.insert(0, str(SCRIPT_DIR))
from comparison_report import DEFAULT_COMPARISON_DIR, summarize_comparison_logs

DEFAULT_HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
DEFAULT_HOOKS_DIR = DEFAULT_HERMES_HOME / "hooks" / "pantheon-core"
CONFIG_PATH = DEFAULT_HERMES_HOME / "config.yaml"

# The built-in engine is selected by name and resolved from the core agent
# package; every other name is looked up in plugins/context_engine/<name>/.
# Mirrors agent/agent_init.py's context-engine selection.
DEFAULT_CONTEXT_ENGINE = "compressor"
BUILTIN_CONTEXT_ENGINES = frozenset({DEFAULT_CONTEXT_ENGINE})

_STATUS_ICONS = {"ok": "✅", "warning": "⚠️", "dead": "✗", "n/a": "·"}
_STATUS_WORDS = {"ok": "HEALTHY", "n/a": "NOT DEPLOYED"}
# Statuses that mean "something is actually wrong right now".
_UNHEALTHY_STATUSES = ("warning", "dead")


def _status(component: str, healthy: "bool | str", detail: str, **extra: Any) -> dict[str, Any]:
    """Build one component record.

    ``healthy`` accepts either a bool (True -> ``ok``, False -> ``dead``) or an
    explicit status string, so a probe can report ``warning`` or ``n/a`` without
    a second code path.
    """
    status = healthy if isinstance(healthy, str) else ("ok" if healthy else "dead")
    payload = {
        "component": component,
        "status": status,
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
        server = getattr(ichor_mcp, "MCP_SERVER_SOURCE", "unknown")
        detail = (
            f"healthy={healthy} server={server} "
            f"folds={stats.get('fold_count', 0)} expands={stats.get('expand_count', 0)} "
            f"audit={audit.get('count', 0)}"
        )
        return _status(
            "Ichor MCP",
            bool(healthy),
            detail,
            health=health,
            stats=stats,
            audit=audit,
            server_class=server,
        )
    except Exception as exc:
        return _status("Ichor MCP", False, f"{type(exc).__name__}: {exc}")


def _live_config() -> dict[str, Any]:
    """Read the config.yaml this deployment actually runs."""
    try:
        import yaml  # local import: the guardian must not hard-depend on yaml
    except ImportError:
        return {}
    try:
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _configured_context_engine() -> str:
    """Return the engine name ``context.engine`` selects (default: compressor)."""
    context_config = _live_config().get("context") or {}
    if not isinstance(context_config, dict):
        return DEFAULT_CONTEXT_ENGINE
    return str(context_config.get("engine") or DEFAULT_CONTEXT_ENGINE)


def _available_plugin_engines() -> str:
    """Describe the context engines shipped in the live runtime's plugin dir."""
    try:
        from plugins.context_engine import discover_context_engines

        found = discover_context_engines()
    except Exception as exc:
        return f"unavailable ({type(exc).__name__}: {exc})"
    if not found:
        return "none"
    return ", ".join(
        f"{name}{'' if available else ' (unavailable)'}" for name, _desc, available in found
    )


def probe_context_engine() -> dict[str, Any]:
    """Probe the context engine the live config selects.

    Replaces a probe hardcoded to ``load_context_engine("accordion")``. The
    accordion engine lives only in a vendored 0.17.0 tree and
    ``~/.hermes/config.yaml`` selects ``compressor``, so the old probe reported
    a permanent death for a component this deployment does not use. What
    actually matters is that the engine the config selects resolves -- and if
    the config names an engine that is not installed, that is a real fault
    worth a red light.
    """
    engine_name = _configured_context_engine()
    try:
        if engine_name in BUILTIN_CONTEXT_ENGINES:
            from agent.context_compressor import ContextCompressor

            detail = (
                f"engine={engine_name} (built-in ContextCompressor, "
                f"configured in {CONFIG_PATH.name})"
            )
            return _status(
                "Context Engine",
                True,
                detail,
                engine=engine_name,
                engine_class=ContextCompressor.__name__,
                source="builtin",
            )

        from plugins.context_engine import load_context_engine

        engine = load_context_engine(engine_name)
        if engine is None:
            return _status(
                "Context Engine",
                False,
                f"configured engine '{engine_name}' did not load; "
                f"plugin engines available: {_available_plugin_engines()}",
                engine=engine_name,
                source="plugin",
            )
        detail = (
            f"engine={engine_name} (plugin {type(engine).__name__}, "
            f"name={getattr(engine, 'name', engine_name)})"
        )
        return _status(
            "Context Engine",
            True,
            detail,
            engine=engine_name,
            engine_class=type(engine).__name__,
            source="plugin",
        )
    except Exception as exc:
        return _status(
            "Context Engine",
            False,
            f"engine='{engine_name}' {type(exc).__name__}: {exc}",
            engine=engine_name,
        )


# PluginManager records why a plugin did not activate in ``LoadedPlugin.error``.
# Three of those strings describe a deliberate configuration choice; anything
# else is a real load failure and belongs in the report.
_INTENTIONAL_PLUGIN_STATES = (
    "not enabled in config",
    "disabled via config",
    "exclusive plugin",
)


def _plugin_manager() -> "tuple[Any, dict[str, str]]":
    """Discover the live plugin set.

    Returns the manager plus a ``name -> error`` map for plugins that failed to
    load for a reason that is NOT a deliberate configuration choice, so a
    half-broken deployed plugin shows up in the report instead of only in the
    log stream. This reads ``LoadedPlugin.error`` rather than scraping the log:
    PluginManager writes its INFO/WARNING lines through Rich to stderr, wrapped
    across multiple lines, which is not a parseable signal.
    """
    from hermes_cli.plugins import PluginManager

    os.environ.setdefault("HERMES_BUNDLED_PLUGINS", str(HERMES_AGENT_ROOT / "plugins"))
    manager = PluginManager()
    manager.discover_and_load()

    failures: dict[str, str] = {}
    for key, plugin in (getattr(manager, "_plugins", {}) or {}).items():
        error = getattr(plugin, "error", None)
        if not error:
            continue
        if any(marker in str(error) for marker in _INTENTIONAL_PLUGIN_STATES):
            continue
        failures[key] = str(error)
    return manager, failures


def probe_pantheon_hooks() -> dict[str, Any]:
    """Probe the lifecycle hooks the *deployed* plugins actually register.

    The previous version hardcoded the ``pantheon-core`` plugin name and the
    ``~/.hermes/hooks/pantheon-core`` directory. That plugin is a Phase-B
    prototype that ships in Pantheon's vendored 0.17.0 checkout and is NOT
    installed in the fleet, so the probe reported a permanent false death for a
    component that does not exist here. This version asks the live plugin
    manager which plugins declare lifecycle hooks in their manifest and checks
    that each declared hook was really registered: a contract that adapts as the
    fleet's plugin set changes, and that still fails loudly when a *deployed*
    plugin half-registers.
    """
    try:
        manager, load_failures = _plugin_manager()
        plugins = getattr(manager, "_plugins", {}) or {}

        declared: dict[str, list[str]] = {}
        for key, plugin in plugins.items():
            manifest = getattr(plugin, "manifest", None)
            hooks = list(getattr(manifest, "provides_hooks", None) or [])
            if hooks:
                declared[key] = hooks

        if not declared:
            return _status(
                "Pantheon Hooks",
                "n/a",
                f"no deployed plugin declares lifecycle hooks in its manifest "
                f"({len(plugins)} plugins discovered, none with provides_hooks) "
                f"— hook contract not applicable to this deployment",
                discovered=len(plugins),
                load_failures=load_failures,
            )

        missing: dict[str, list[str]] = {}
        for key, hooks in declared.items():
            registered = set(getattr(plugins[key], "hooks_registered", []) or [])
            gap = sorted(set(hooks) - registered)
            if gap:
                missing[key] = gap

        if missing:
            detail = "; ".join(
                f"{key} declared but not registered: {', '.join(gap)}"
                for key, gap in missing.items()
            )
            return _status(
                "Pantheon Hooks",
                False,
                detail,
                declared=declared,
                load_failures=load_failures,
            )

        detail = (
            f"{len(declared)} plugin(s) register every declared hook: "
            + ", ".join(f"{key} ({len(declared[key])})" for key in sorted(declared))
        )
        if load_failures:
            # A plugin that cannot load at all is a stronger fault than a hook
            # mismatch, and it is otherwise invisible: the fleet just runs
            # without the plugin. Report it instead of staying quiet.
            failed = "; ".join(f"{key} ({error})" for key, error in sorted(load_failures.items()))
            return _status(
                "Pantheon Hooks",
                "warning",
                f"{detail}; {len(load_failures)} plugin(s) failed to load: {failed}",
                declared=declared,
                load_failures=load_failures,
            )
        return _status(
            "Pantheon Hooks", True, detail, declared=declared, load_failures=load_failures
        )
    except Exception as exc:
        return _status("Pantheon Hooks", False, f"{type(exc).__name__}: {exc}")


def probe_comparison_report() -> dict[str, Any]:
    """Probe the comparison lane -- and refuse to call an empty lane healthy.

    ``0 divergences`` reads as green, but with zero comparison entries there is
    nothing being compared: the number is not evidence of health. That is the
    "reports success while doing nothing" failure mode this audit exists to
    find, so an unmeasured lane now reports ``n/a`` instead of ``ok``.
    """
    try:
        summary = summarize_comparison_logs(DEFAULT_COMPARISON_DIR)
        entries = summary.get("total_entries", 0)
        divergences = summary.get("divergence_count", 0)
        if not entries:
            return _status(
                "Comparison Report",
                "n/a",
                f"unmeasured — 0 comparison entries in {summary.get('comparison_dir', DEFAULT_COMPARISON_DIR)}, "
                f"so '0 divergences' is not evidence of health",
                summary=summary,
            )
        healthy = divergences == 0
        detail = f"{divergences} divergences, {entries} comparison entries"
        return _status("Comparison Report", healthy, detail, summary=summary)
    except Exception as exc:
        return _status("Comparison Report", False, f"{type(exc).__name__}: {exc}")


def collect_observability_state() -> dict[str, Any]:
    components = [
        probe_ichor_mcp(),
        probe_context_engine(),
        probe_pantheon_hooks(),
        probe_comparison_report(),
    ]
    warning_count = sum(1 for item in components if item["status"] == "warning")
    dead_count = sum(1 for item in components if item["status"] == "dead")
    absent = [item for item in components if item["status"] == "n/a"]
    equivalence = next(
        (item.get("summary", {}) for item in components if item["component"] == "Comparison Report"),
        {},
    )
    entries = equivalence.get("total_entries", 0)
    divergences = equivalence.get("divergence_count", 0)
    if not entries:
        equivalence_status = "n/a"
        equivalence_detail = "unmeasured — 0 comparison entries"
    elif divergences:
        equivalence_status = "warning"
        equivalence_detail = f"{divergences} divergences across {entries} entries"
    else:
        equivalence_status = "ok"
        equivalence_detail = f"0 divergences across {entries} entries"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        # --- runtime provenance -------------------------------------------------
        # Which interpreter and Hermes tree produced this verdict.
        #
        # Two of the probes below resolve against the live runtime, and the
        # fleet's canonical interpreter is the gateway's venv
        # (``/usr/local/lib/hermes-agent/venv/bin/python``, per
        # ``hermes-gateway.service``). Cron invokes a bare ``python3``, which on
        # this host is ``/usr/bin/python3`` (3.14) plus whatever ``PYTHONPATH``
        # it inherits. That difference is not cosmetic: under the 3.14
        # interpreter the vector backend reports unhealthy and ``rtk-rewrite``
        # registers none of its declared hooks, so the same fleet looks broken.
        # Recording the interpreter turns a phantom component fault into an
        # obvious wrong-interpreter fault.
        "runtime": {
            "interpreter": sys.executable,
            "python_version": sys.version.split()[0],
            "hermes_agent_root": str(HERMES_AGENT_ROOT),
            "hermes_agent_root_source": HERMES_AGENT_ROOT_SOURCE,
        },
        "components": components,
        "warning_count": warning_count,
        "dead_count": dead_count,
        "not_deployed_count": len(absent),
        "not_deployed": [
            {"component": item["component"], "detail": item["detail"]} for item in absent
        ],
        "equivalence": {
            "status": equivalence_status,
            "detail": equivalence_detail,
        },
    }


def render_guardian_text(state: dict[str, Any]) -> str:
    unhealthy = [
        item for item in state.get("components", []) if item.get("status") in _UNHEALTHY_STATUSES
    ]
    if not unhealthy and state.get("equivalence", {}).get("status") != "warning":
        return ""

    lines = [
        f"Health Guardian — {state.get('timestamp', '')}",
        "─────────────────────────────────────",
    ]
    for item in state.get("components", []):
        status = item.get("status", "dead")
        icon = _STATUS_ICONS.get(status, "?")
        label = f"{item.get('component', 'Unknown'):14s}"
        state_word = _STATUS_WORDS.get(status, "UNHEALTHY")
        lines.append(f"{icon} {label} {state_word:12s} {item.get('detail', '')}")
    lines.append(f"Equivalence:    {state.get('equivalence', {}).get('detail', 'unknown')}")
    if state.get("not_deployed_count"):
        lines.append(
            f"Not deployed:   {state['not_deployed_count']} component(s) absent from this "
            f"deployment (informational, not counted as failures)"
        )
    return "\n".join(lines).strip() + "\n"




def notify_guardian(state: dict[str, Any]) -> None:
    """Best-effort push to the WebUI bell. A failed notification must not kill the run.

    This used to call ``subprocess.Popen`` bare, and on 2026-08-25 that raised
    straight out of ``main()``: the guardian ended in a traceback and a non-zero
    exit *instead of* the report it had already rendered -- a watchdog that
    crashes exactly when it finally has something to say. Failures are now
    reported on stderr while the report and exit code stand.
    """
    body = render_guardian_text(state).strip() or "Pantheon observability is unhealthy."
    title = f"{state.get('dead_count', 0)} dead / {state.get('warning_count', 0)} warning in observability"
    god_notify = Path.home() / ".local" / "bin" / "god-notify"
    if not god_notify.is_file():
        return
    try:
        subprocess.Popen(
            [str(god_notify), "Hephaestus", "error", title, body],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        print(
            f"guardian: notification failed ({type(exc).__name__}: {exc}); "
            f"the report above still stands",
            file=sys.stderr,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pantheon health guardian")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = parser.parse_args(argv)

    state = collect_observability_state()
    text = render_guardian_text(state)
    # An "n/a" component is not a fault: it means the component is absent from
    # this deployment. Only dead/warning components and measured divergence make
    # the guardian unhealthy -- otherwise the guardian would cry wolf forever
    # about lanes this fleet deliberately does not run.
    healthy = (
        state.get("dead_count", 0) == 0
        and state.get("warning_count", 0) == 0
        and state.get("equivalence", {}).get("status") != "warning"
    )

    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
    elif not healthy:
        print(text, end="")

    if not healthy:
        notify_guardian(state)

    return 0 if healthy else 1


if __name__ == "__main__":
    raise SystemExit(main())
