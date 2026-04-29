import copy
import os
from pathlib import Path

import yaml

from .exceptions import (
    HarnessCircularExtendsError,
    HarnessNotFoundError,
)
from .schema import validate

_DEFAULT_HARNESS_DIR = Path(__file__).resolve().parents[2] / "Athenaeum/Codex-Pantheon/harnesses"

_cache: dict[str, dict] = {}


def _harness_dir() -> Path:
    return Path(os.environ.get("PANTHEON_HARNESS_DIR", str(_DEFAULT_HARNESS_DIR)))


def load_harness(filename: str, _chain: list[str] | None = None) -> dict:
    if _chain is None:
        _chain = []

    if filename in _chain:
        raise HarnessCircularExtendsError(
            f"Circular extends detected: {' -> '.join(_chain)} -> {filename}"
        )

    harness_dir = _harness_dir()
    cache_key = str(harness_dir / filename)

    if cache_key in _cache:
        return copy.deepcopy(_cache[cache_key])

    path = harness_dir / filename
    if not path.exists():
        raise HarnessNotFoundError(f"Harness file not found: {path}")

    with path.open("r") as f:
        harness = yaml.safe_load(f)

    if harness is None:
        harness = {}

    validate(harness, filename)

    extends = harness.pop("extends", None)
    if extends:
        base = load_harness(extends, _chain + [filename])
        harness = _merge(base, harness)

    _cache[cache_key] = harness
    return copy.deepcopy(harness)


def invalidate(filename: str) -> None:
    cache_key = str(_harness_dir() / filename)
    _cache.pop(cache_key, None)
    _cache.pop(filename, None)  # backwards compat


def invalidate_all() -> None:
    _cache.clear()


def _merge(base: dict, child: dict) -> dict:
    merged = copy.deepcopy(base)

    for key, child_value in child.items():
        if key == "routing":
            base_routing = merged.get("routing", [])
            merged["routing"] = child_value + base_routing
        elif key == "guardrails":
            merged_guardrails = copy.deepcopy(merged.get("guardrails", {}))
            base_hard_stops = merged_guardrails.get("hard_stops", [])
            child_hard_stops = child_value.get("hard_stops", [])
            merged_guardrails["hard_stops"] = base_hard_stops + child_hard_stops
            child_soft = child_value.get("soft_boundaries")
            if child_soft is not None:
                merged_guardrails["soft_boundaries"] = child_soft
            merged["guardrails"] = merged_guardrails
        elif isinstance(child_value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], child_value)
        else:
            merged[key] = child_value

    return merged
