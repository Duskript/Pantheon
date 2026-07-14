"""Operator-facing config loader for the kanban dispatcher.

Reads ``/home/konan/pantheon/config/kanban.yaml`` (or the override path
passed in) and exposes its knobs as typed attributes. If the file is
missing or malformed, falls back to safe defaults so a missing config
never blocks work.

Why this module lives at the repo root (not inside hermes-agent):

  The new ``spec-to-cards`` skill and ``on_session_start.py`` hook need
  to read the same knobs as the dispatcher. They're invoked from the
  Hephaestus profile, not from hermes-agent. Keeping the reader at
  ``hermes_cli/`` (the new top-level package) means the skill can
  import it without sys.path gymnastics.

Schema for the YAML is in ``config/kanban.yaml`` — keep them in sync.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_CONFIG_PATH = Path("/home/konan/pantheon/config/kanban.yaml")


@dataclass
class DispatcherConfig:
    """Knobs under ``kanban.dispatcher.*`` in kanban.yaml."""

    interval_seconds: int = 60
    max_parallel_per_assignee: int = 4
    max_parallel_total: int = 12
    default_max_loc_delta: int = 30
    max_loc_delta_hard_cap: int = 100
    conflict_check: str = "mechanical"  # "mechanical" or "off"


@dataclass
class ContractsConfig:
    """Knobs under ``kanban.contracts.*`` in kanban.yaml."""

    require_out_of_scope_min: int = 3
    require_verify_command: bool = True
    render_prompt_max_bytes: int = 2048


@dataclass
class KanbanConfig:
    """Full kanban.yaml surface as typed attributes."""

    dispatcher: DispatcherConfig = field(default_factory=DispatcherConfig)
    contracts: ContractsConfig = field(default_factory=ContractsConfig)


def _safe_int(value, default: int) -> int:
    if isinstance(value, bool):  # bool is a subclass of int — exclude it
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _safe_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "on", "1")
    return default


def load_config(path: Optional[Path] = None) -> KanbanConfig:
    """Load kanban.yaml and return a typed config.

    Falls back to defaults if the file is missing, malformed, or
    missing any required key. Never raises — a missing config is
    not a reason to break the system.
    """
    cfg = KanbanConfig()
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return cfg

    try:
        import yaml  # type: ignore
        with open(config_path) as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        return cfg

    if not isinstance(raw, dict):
        return cfg

    kanban_section = raw.get("kanban", {})
    if not isinstance(kanban_section, dict):
        return cfg

    disp = kanban_section.get("dispatcher", {})
    if isinstance(disp, dict):
        cfg.dispatcher.interval_seconds = _safe_int(
            disp.get("interval_seconds"), cfg.dispatcher.interval_seconds
        )
        cfg.dispatcher.max_parallel_per_assignee = _safe_int(
            disp.get("max_parallel_per_assignee"),
            cfg.dispatcher.max_parallel_per_assignee,
        )
        cfg.dispatcher.max_parallel_total = _safe_int(
            disp.get("max_parallel_total"), cfg.dispatcher.max_parallel_total
        )
        cfg.dispatcher.default_max_loc_delta = _safe_int(
            disp.get("default_max_loc_delta"), cfg.dispatcher.default_max_loc_delta
        )
        cfg.dispatcher.max_loc_delta_hard_cap = _safe_int(
            disp.get("max_loc_delta_hard_cap"),
            cfg.dispatcher.max_loc_delta_hard_cap,
        )
        cc = disp.get("conflict_check")
        if isinstance(cc, str) and cc in ("mechanical", "off"):
            cfg.dispatcher.conflict_check = cc

    contracts = kanban_section.get("contracts", {})
    if isinstance(contracts, dict):
        cfg.contracts.require_out_of_scope_min = _safe_int(
            contracts.get("require_out_of_scope_min"),
            cfg.contracts.require_out_of_scope_min,
        )
        cfg.contracts.require_verify_command = _safe_bool(
            contracts.get("require_verify_command"),
            cfg.contracts.require_verify_command,
        )
        cfg.contracts.render_prompt_max_bytes = _safe_int(
            contracts.get("render_prompt_max_bytes"),
            cfg.contracts.render_prompt_max_bytes,
        )

    return cfg


if __name__ == "__main__":
    cfg = load_config()
    print(f"max_parallel_per_assignee: {cfg.dispatcher.max_parallel_per_assignee}")
    print(f"max_parallel_total: {cfg.dispatcher.max_parallel_total}")
    print(f"default_max_loc_delta: {cfg.dispatcher.default_max_loc_delta}")
    print(f"max_loc_delta_hard_cap: {cfg.dispatcher.max_loc_delta_hard_cap}")
    print(f"conflict_check: {cfg.dispatcher.conflict_check}")
    print(f"require_out_of_scope_min: {cfg.contracts.require_out_of_scope_min}")
    print(f"require_verify_command: {cfg.contracts.require_verify_command}")
    print(f"render_prompt_max_bytes: {cfg.contracts.render_prompt_max_bytes}")
