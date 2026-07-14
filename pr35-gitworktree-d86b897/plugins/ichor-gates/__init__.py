"""Ichor RALPH 5-Gate Harness — Hermes Agent Plugin.

Wires the Ichor gates (State, Logic, Phase Detection, Intent Injection,
Handoff) into every god's tool-call loop via the Hermes Agent plugin system.

Pre-tool-call hooks:
  - State Gate: blocks write_file/patch on files not read first
  - Phase Detection: tracks RALPH phase transitions from user input
  - ReadCache: tracks read_file calls for State Gate awareness
  - RTK command rewrite: passes terminal commands through `rtk rewrite`
    before execution. Fails open — missing/unavailable rtk is a no-op.

Post-tool-call hooks:
  - Logic Gate: syntax-validates write_file/patch output
  - ForgeLogger: records all interventions per-model

The pipeline is lazy-initialized and singleton per-process. All failures are
caught and logged at DEBUG level — gates never block the agent's tool loop
due to their own errors.

Architecture:
  model_tools.py handle_function_call()
      │
      ├── pre_tool_call hook (this plugin)
      │   ├── State Gate → block message or None
      │   └── ReadCache.mark_read() for read_file calls
      │
      ├── [tool executes]
      │
      └── post_tool_call hook (this plugin)
          ├── Logic Gate → validation issues
          └── ForgeLogger → record intervention
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("ichor_gates_plugin")

# ---------------------------------------------------------------------------
# Lazy singleton — gates only load when a tool call fires.
# ---------------------------------------------------------------------------

_pipeline = None
_read_cache = None
_forge_logger = None
_session_id = ""
_god_name = ""


def _ensure_pantheon_path() -> None:
    """Add ~/pantheon/ to sys.path so 'from lib.ichor_gates' works."""
    pantheon_root = str(Path.home() / "pantheon")
    if pantheon_root not in sys.path:
        sys.path.insert(0, pantheon_root)


def _get_god_name() -> str:
    """Extract the god/profile name from HERMES_HOME.

    Each god runs as its own Hermes profile. HERMES_HOME points to
    ~/.hermes or ~/.hermes/profiles/{god_name}/ — the last directory
    component is the god name. Strip leading dots from hidden dirs.
    """
    try:
        from hermes_constants import get_hermes_home  # type: ignore[import-untyped]
        home = get_hermes_home()
        if home:
            name = Path(str(home)).name
            # Strip leading dots (e.g. ".hermes" → "hermes") and
            # reject known non-god defaults
            clean = name.lstrip(".")
            if clean in ("hermes", "default", "base", "root"):
                return clean
            return clean
    except Exception:
        pass
    return "unknown"


def _ensure_gates():
    """Lazy singleton: load the gate pipeline on first tool call."""
    global _pipeline, _read_cache, _forge_logger

    if _pipeline is not None:
        return _pipeline

    _ensure_pantheon_path()

    try:
        from lib.ichor_gates import (  # type: ignore[import-untyped]
            ForgeLogger,
            GatePipeline,
            LogicGate,
            PhaseDetectionGate,
            ReadCache,
            StateGate,
        )

        _read_cache = ReadCache()
        _forge_logger = ForgeLogger()

        pipeline = GatePipeline()
        pipeline.read_cache = _read_cache

        # Register gates
        pipeline.register(StateGate(_read_cache))
        pipeline.register(LogicGate())
        pipeline.register(PhaseDetectionGate())

        _pipeline = pipeline
        logger.info("Ichor Gates: pipeline initialized (%d gates)", len(pipeline.gates))
        return pipeline

    except Exception as exc:
        logger.debug("Ichor Gates: lazy init failed (non-fatal): %s", exc)
        return None


def _get_read_cache():
    _ensure_gates()
    return _read_cache


def _get_forge_logger():
    _ensure_gates()
    return _forge_logger


# ---------------------------------------------------------------------------
# Tools that are READ operations — tracked by ReadCache
# ---------------------------------------------------------------------------

_READ_TOOLS: Set[str] = {
    "read_file",
    "web_extract",
    "browser_get_images",
    "mcp_filesystem_read_text_file",
    "mcp_filesystem_read_file",
}

_WRITE_TOOLS: Set[str] = {
    "write_file",
    "patch",
    "mcp_filesystem_write_file",
    "mcp_filesystem_edit_file",
}


# ---------------------------------------------------------------------------
# Hook handlers
# ---------------------------------------------------------------------------


def _on_pre_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    **kwargs: Any,
) -> Optional[str]:
    """Pre-tool-call hook: enforce State Gate, track reads, detect phase.

    Returns:
        A block message string to prevent the tool from executing, or None.
    """
    try:
        pipeline = _ensure_gates()
        if pipeline is None:
            return None

        # ── Track read_file calls in ReadCache ──────────────────────────
        if tool_name in _READ_TOOLS:
            path = args.get("path", "")
            if path:
                rc = _get_read_cache()
                if rc:
                    rc.mark_read(path)

        # ── Track write_file paths (for existence check) ────────────────
        if tool_name in _WRITE_TOOLS:
            path = args.get("path", "")
            if path:
                rc = _get_read_cache()
                if rc:
                    # Pre-warm the existence check
                    rc.exists_on_disk(path)

        # ── Phase Detection ─────────────────────────────────────────────
        if tool_name in _WRITE_TOOLS or tool_name in _READ_TOOLS or tool_name == "terminal":
            # Attempt phase detection from user context if available
            context = {"user_message": kwargs.get("user_task", "") or ""}
            phase_result = pipeline.run_pre_call(tool_name, args, context)
            if phase_result and phase_result.payload:
                phase_info = phase_result.payload
                logger.info(
                    "Ichor Phase: %s → %s (tools: %d)",
                    phase_info.get("old_phase", "?"),
                    phase_info.get("new_phase", "?"),
                    len(phase_info.get("tools", [])),
                )

        # ── State Gate ──────────────────────────────────────────────────
        if tool_name in _WRITE_TOOLS:
            result = pipeline.run_pre_call(tool_name, args, {})
            if result is not None and not result.passed:
                logger.info(
                    "Ichor Gate BLOCKED: %s on %s — %s",
                    result.gate_name, tool_name, result.message,
                )
                return result.recovery_hint

        return None

    except Exception as exc:
        logger.debug("Ichor pre_tool_call hook error (non-fatal): %s", exc)
        return None


def _on_post_tool_call(
    tool_name: str,
    args: Dict[str, Any],
    result: str,
    **kwargs: Any,
) -> None:
    """Post-tool-call hook: run Logic Gate, log to ForgeLogger.

    This is fire-and-forget observational. The result is already committed
    — gates can't block after execution, but they log interventions.
    """
    try:
        pipeline = _ensure_gates()
        forge = _get_forge_logger()
        if pipeline is None or forge is None:
            return

        # ── Logic Gate (write_file/patch only) ──────────────────────────
        if tool_name in _WRITE_TOOLS:
            gate_results = pipeline.run_post_call(tool_name, args, result, {})
            for gr in gate_results:
                if not gr.passed and gr.intervention:
                    logger.info(
                        "Ichor Gate: %s — %s",
                        gr.gate_name, gr.message,
                    )
                    # Log to Forge
                    forge.log_intervention(
                        gate_name=gr.gate_name,
                        result=gr,
                        model=kwargs.get("model", "unknown"),
                        session_id=_session_id,
                        user_intent=kwargs.get("user_task", ""),
                        god=_god_name,
                    )

    except Exception as exc:
        logger.debug("Ichor post_tool_call hook error (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------


def register(ctx):
    """Register Ichor gate hooks with the Hermes Agent plugin system."""

    global _session_id, _god_name

    # Resolve god name from HERMES_HOME
    _god_name = _get_god_name()
    logger.info("Ichor Gates plugin: activating for god='%s'", _god_name)

    # Register pre-tool-call hook (can block tools)
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)

    # Register post-tool-call hook (observational)
    ctx.register_hook("post_tool_call", _on_post_tool_call)

    # Register RTK command rewriter (consolidated from rtk-rewrite plugin
    # 2026-06-02). Fires AFTER the gates so a rewritten command still
    # benefits from State Gate validation. Fails open — missing rtk
    # binary is a no-op.
    if _rtk_available():
        ctx.register_hook("pre_tool_call", _rtk_pre_tool_call)
        logger.info("Ichor Gates: RTK rewrite pass active (rtk binary found)")
    else:
        logger.info("Ichor Gates: RTK rewrite pass inactive (rtk binary not in PATH)")

    logger.info("Ichor Gates plugin registered: pre_tool_call + post_tool_call hooks active")


# ---------------------------------------------------------------------------
# RTK command rewriter (consolidated from plugins/rtk-rewrite/ on 2026-06-02)
# ---------------------------------------------------------------------------
# All rewrite logic lives in RTK's Rust `rtk rewrite` command; this module
# only bridges Hermes pre_tool_call payloads to that command and fails open.
# ---------------------------------------------------------------------------

ACCEPTED_REWRITE_RETURN_CODES = {0, 3}
EXPECTED_PASSTHROUGH_RETURN_CODES = {1, 2}
_rtk_missing_warned = False


def _rtk_available() -> bool:
    """Return whether the rtk binary is in PATH, warning once when missing."""
    global _rtk_missing_warned
    found = shutil.which("rtk") is not None
    if not found and not _rtk_missing_warned:
        print("ichor-gates: rtk binary not found in PATH; rewrite pass disabled",
              file=sys.stderr)
        _rtk_missing_warned = True
    return found


def _rtk_pre_tool_call(tool_name=None, args=None, **_kwargs):
    """Rewrite mutable Hermes terminal command args when RTK provides a change."""
    try:
        if tool_name != "terminal" or not isinstance(args, dict):
            return

        command = args.get("command")
        if not isinstance(command, str) or not command.strip():
            return

        try:
            result = subprocess.run(
                ["rtk", "rewrite", command],
                shell=False,
                timeout=2,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            print("ichor-gates: rtk rewrite timed out", file=sys.stderr)
            return

        if result.returncode not in ACCEPTED_REWRITE_RETURN_CODES:
            if result.returncode not in EXPECTED_PASSTHROUGH_RETURN_CODES:
                details = f"rtk rewrite failed with exit {result.returncode}"
                stderr = result.stderr.strip()
                if stderr:
                    details = f"{details}: {stderr}"
                print(f"ichor-gates: {details}", file=sys.stderr)
            return

        rewritten = result.stdout.strip()
        if rewritten and rewritten != command:
            args["command"] = rewritten
    except Exception as e:
        print(f"ichor-gates: rtk rewrite error: {e}", file=sys.stderr)
        return
