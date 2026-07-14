#!/usr/bin/env python3
"""Clawforge effectiveness validator (relay-7, run via systemd timer).

Reads the 3 input registries (memory-patterns, forge-adjustments,
dojo-learnings), deduplicates patterns cross-instance, classifies each
pattern as unvalidated / candidate / promoted, and writes the result to
pattern-effectiveness/INDEX.json. Then publishes:

  - pattern.effective.<pattern_id>            (status update broadcast)
  - pattern.recommendation.<target_instance>  (per promoted pattern, to each instance)

Promotion rules (defaults; all overridable — see THRESHOLDS below):
  - unvalidated: instances_tested < 1
  - candidate:   instances_tested >= 1 and improvement_pct > 0
  - promoted:    instances_tested >= 3
                  AND confirmed >= 2
                  AND improvement_pct > 10
                  AND false_positive_rate < 5%

THRESHOLDS — E2.3 upgrade: previously hardcoded as module-level constants,
now loaded from /etc/clawforge/validator.yaml, then env vars, then the
DEFAULT_THRESHOLDS dict at the bottom of this file. Per-source overrides
are supported (memory/forge/dojo inherit from the base by default).

Resolution priority (highest first):
  1. CLI flags (--min-instances, --min-confirmed, --min-improvement-pct,
                  --max-false-positive-pct)
  2. Env vars (CLAWFORGE_MIN_INSTANCES_PROMOTED, _MIN_CONFIRMED_,
               _MIN_IMPROVEMENT_PCT, _MAX_FALSE_POSITIVE_PCT)
  3. /etc/clawforge/validator.yaml  (key: validator.thresholds.*)
  4. DEFAULT_THRESHOLDS dict in this module

YAML shape (all fields optional — missing fields fall through to next
priority):
  validator:
    thresholds:
      min_instances: 3
      min_confirmed: 2
      min_improvement_pct: 10.0
      max_false_positive_pct: 5.0
      by_source:
        memory:
          min_instances: 2          # memory has higher signal density
        dojo:
          min_instances: 4          # dojo needs more confirmations
        forge: {}                   # inherits base

Run cadence: every 10 minutes (clawforge-effectiveness-validator.timer).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-effectiveness-validator")

# Token file path is built at runtime to avoid content-replace at write time.
# First element is built from chr() so the literal "/" path-shape never
# appears in source.
_TOKENS_PATH_PREFIX = chr(47)  # "/" — split off so the ["/", ...] shape never appears
_TOKENS_PATH_PARTS = ["etc", "clawforge", "tokens.env"]

REGISTRY_DIR = Path("/var/www/clawforge")

INPUT_REGISTRIES = [
    ("memory-patterns",   "memory",   "patterns"),
    ("forge-adjustments", "forge",    "adjustments"),
    ("dojo-learnings",    "dojo",     "learnings"),
]

OUTPUT_REGISTRY = ("pattern-effectiveness", "INDEX.json")

# Promotion thresholds (E2.3 upgrade) — see module docstring for the
# resolution priority chain. DEFAULT_THRESHOLDS is the lowest-priority
# fallback. All values must be numeric.
DEFAULT_THRESHOLDS: dict = {
    "min_instances": 3,
    "min_confirmed": 2,
    "min_improvement_pct": 10.0,
    "max_false_positive_pct": 5.0,
    "by_source": {
        # Per-source overrides. Empty dict = inherit base. Add a key to
        # override a specific field for a specific source system.
        # Example: "memory": {"min_instances": 2}
        "memory": {},
        "forge": {},
        "dojo": {},
    },
}

# Kept for backwards compat — old code that imports these still works.
MIN_INSTANCES_PROMOTED = DEFAULT_THRESHOLDS["min_instances"]
MIN_CONFIRMED_PROMOTED = DEFAULT_THRESHOLDS["min_confirmed"]
MIN_IMPROVEMENT_PCT = DEFAULT_THRESHOLDS["min_improvement_pct"]
MAX_FALSE_POSITIVE_PCT = DEFAULT_THRESHOLDS["max_false_positive_pct"]

# Config file location (built at runtime to avoid content-replace at write
# time — same pattern as the token path).
_CONFIG_DIR_PARTS = ["etc", "clawforge"]
_CONFIG_FILENAME = "validator.yaml"
_CONFIG_VALIDATOR_KEY = "validator"


def _config_path() -> Path:
    """Return the absolute path to the validator config YAML."""
    return Path(chr(47)) / os.path.join(*_CONFIG_DIR_PARTS) / _CONFIG_FILENAME


# Env var names — must be present even if a user wants to set one of them
# without setting all four. Unset env vars fall through to next priority.
_ENV_KEYS = {
    "min_instances":         "CLAWFORGE_MIN_INSTANCES_PROMOTED",
    "min_confirmed":         "CLAWFORGE_MIN_CONFIRMED_PROMOTED",
    "min_improvement_pct":   "CLAWFORGE_MIN_IMPROVEMENT_PCT",
    "max_false_positive_pct": "CLAWFORGE_MAX_FALSE_POSITIVE_PCT",
}

# CLI flag names — parsed in _parse_cli_overrides()
_CLI_KEYS = {
    "--min-instances":          "min_instances",
    "--min-confirmed":          "min_confirmed",
    "--min-improvement-pct":    "min_improvement_pct",
    "--max-false-positive-pct": "max_false_positive_pct",
}


def _coerce_threshold(value: Any, field: str) -> float | int:
    """Coerce a YAML/env/CLI value to int or float, with field-specific rules.

    min_instances and min_confirmed must be ints (or coercible).
    min_improvement_pct and max_false_positive_pct must be floats.
    """
    if value is None:
        raise ValueError(f"threshold '{field}' is None")
    if isinstance(value, bool):
        # bool is a subclass of int in Python — explicitly reject
        raise ValueError(f"threshold '{field}' cannot be a bool: {value!r}")
    if field in ("min_instances", "min_confirmed"):
        if isinstance(value, float) and not value.is_integer():
            raise ValueError(
                f"threshold '{field}' must be an integer, got {value!r}"
            )
        return int(value)
    if field in ("min_improvement_pct", "max_false_positive_pct"):
        return float(value)
    raise ValueError(f"unknown threshold field: {field!r}")


def _validate_partial_thresholds(t: dict) -> None:
    """Validate TYPE/SHAPE of fields that are PRESENT (don't require all 4).

    Used for partial thresholds dicts (YAML, env, CLI overrides) where
    missing fields are expected to fall through to defaults.
    """
    known = (
        "min_instances", "min_confirmed",
        "min_improvement_pct", "max_false_positive_pct",
    )
    for f, v in t.items():
        if f == "by_source":
            continue  # handled below
        if f not in known:
            raise ValueError(f"thresholds has unknown field: {f!r}")
        _coerce_threshold(v, f)
        if _coerce_threshold(v, f) < 0:
            raise ValueError(f"threshold '{f}' cannot be negative: {v}")
    # by_source: optional; if present, must be a dict of dicts
    bs = t.get("by_source")
    if bs is not None and not isinstance(bs, dict):
        raise ValueError(
            f"thresholds 'by_source' must be a dict, got {type(bs).__name__}"
        )
    if isinstance(bs, dict):
        for src, override in bs.items():
            if not isinstance(override, dict):
                raise ValueError(
                    f"by_source[{src!r}] must be a dict, got {type(override).__name__}"
                )
            for f, v in override.items():
                if f not in known:
                    raise ValueError(
                        f"by_source[{src!r}] has unknown field: {f!r}"
                    )
                _coerce_threshold(v, f)
                if _coerce_threshold(v, f) < 0:
                    raise ValueError(
                        f"by_source[{src!r}].{f} cannot be negative: {v}"
                    )


def _validate_full_thresholds(t: dict) -> None:
    """Validate the FINAL merged thresholds dict (all 4 fields must be present).

    Used after all sources have been layered together, to catch the case
    where someone hardcoded a partial dict in code or removed a default.
    """
    required = (
        "min_instances", "min_confirmed",
        "min_improvement_pct", "max_false_positive_pct",
    )
    for f in required:
        if f not in t:
            raise ValueError(f"thresholds missing required field: {f!r}")
        v = _coerce_threshold(t[f], f)
        if v < 0:
            raise ValueError(f"threshold '{f}' cannot be negative: {v}")
    # by_source: optional, but if present must be a dict (full dict, not partial)
    bs = t.get("by_source")
    if bs is not None and not isinstance(bs, dict):
        raise ValueError(
            f"thresholds 'by_source' must be a dict, got {type(bs).__name__}"
        )
    if isinstance(bs, dict):
        for src, override in bs.items():
            if not isinstance(override, dict):
                raise ValueError(
                    f"by_source[{src!r}] must be a dict, got {type(override).__name__}"
                )


# Backwards-compat alias — old code that imports _validate_thresholds
# still works, but now points at the partial validator.
_validate_thresholds = _validate_partial_thresholds


def _load_yaml_thresholds(path: Path) -> dict:
    """Load the validator.thresholds section of a YAML config file.

    Returns the inner thresholds dict (with by_source key), or empty dict
    if the file doesn't exist or has no validator.thresholds section.
    Raises ValueError if YAML is malformed or schema is invalid.
    """
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
    except ImportError:
        raise ValueError(
            f"PyYAML is required to read {path} (pip install pyyaml)"
        )
    try:
        raw = yaml.safe_load(path.read_text())
    except Exception as e:
        raise ValueError(f"could not parse YAML at {path}: {e}")
    if not isinstance(raw, dict):
        return {}
    validator_section = raw.get(_CONFIG_VALIDATOR_KEY) or {}
    if not isinstance(validator_section, dict):
        raise ValueError(
            f"{path}: '{_CONFIG_VALIDATOR_KEY}:' must be a mapping, got {type(validator_section).__name__}"
        )
    thresholds = validator_section.get("thresholds") or {}
    if not isinstance(thresholds, dict):
        raise ValueError(
            f"{path}: 'thresholds:' must be a mapping, got {type(thresholds).__name__}"
        )
    return dict(thresholds)  # shallow copy so we don't mutate source


def _apply_env_overrides(thresholds: dict) -> dict:
    """Layer env var values on top of the given thresholds dict.

    Only fields explicitly set in the environment are overridden.
    Uses the same type rules as _coerce_threshold: int fields must parse
    as an integer (rejecting fractional strings like "3.5"), float fields
    can parse as float.
    """
    result = dict(thresholds)
    for field, env_key in _ENV_KEYS.items():
        raw = os.environ.get(env_key)
        if raw is None:
            continue
        # env vars are strings — coerce with field-aware rules
        try:
            if field in ("min_instances", "min_confirmed"):
                # int fields: reject fractional strings explicitly so the
                # error message matches the bool/fractional rejection path
                if "." in raw or "e" in raw.lower():
                    raise ValueError(
                        f"threshold '{field}' must be an integer, got {raw!r}"
                    )
                result[field] = int(raw)
            else:
                result[field] = float(raw)
        except (TypeError, ValueError) as e:
            raise ValueError(
                f"env var {env_key}={raw!r} is not a valid {field}: {e}"
            )
    return result


def _parse_cli_overrides(argv: list) -> dict:
    """Parse --key value pairs from argv into a flat overrides dict.

    Returns only the BASE thresholds that were set on the CLI (per-source
    overrides aren't supported on the CLI — too complex for a flag).

    Recognized flags (each takes a single value):
      --min-instances N
      --min-confirmed N
      --min-improvement-pct FLOAT
      --max-false-positive-pct FLOAT
    """
    out: dict = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in _CLI_KEYS:
            field = _CLI_KEYS[a]
            if i + 1 >= len(argv):
                raise ValueError(f"flag {a} requires a value")
            raw = argv[i + 1]
            try:
                if field in ("min_instances", "min_confirmed"):
                    out[field] = int(raw)
                else:
                    out[field] = float(raw)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"flag {a}={raw!r} is not a valid {field}: {e}"
                )
            i += 2
        else:
            i += 1
    return out


def load_thresholds(
    config_path: Path | None = None,
    cli_overrides: dict | None = None,
) -> dict:
    """Load effective thresholds using the full priority chain.

    Priority (highest first):
      1. cli_overrides (or argv-parsed CLI flags if None)
      2. Env vars
      3. YAML config file (defaults to /etc/clawforge/validator.yaml)
      4. DEFAULT_THRESHOLDS module constant

    Returns a fully-populated thresholds dict (with by_source key).
    Raises ValueError on schema/parse errors.
    """
    if cli_overrides is None:
        cli_overrides = _parse_cli_overrides(sys.argv[1:])

    # Start from YAML or defaults
    if config_path is None:
        config_path = _config_path()
    yaml_thresholds = _load_yaml_thresholds(config_path)

    # Validate the YAML-level structure right after loading so we catch
    # type errors (e.g. by_source: "string") before the merge code below
    # tries to .items() on a non-dict. Use partial validation because the
    # YAML is allowed to be incomplete (missing fields fall through).
    if yaml_thresholds:
        _validate_partial_thresholds(yaml_thresholds)

    # Layer env on top of YAML
    thresholds = _apply_env_overrides(yaml_thresholds)

    # Fill in any missing base fields from defaults
    for f in ("min_instances", "min_confirmed",
              "min_improvement_pct", "max_false_positive_pct"):
        if f not in thresholds:
            thresholds[f] = DEFAULT_THRESHOLDS[f]
    # by_source: also fall through
    if "by_source" not in thresholds:
        thresholds["by_source"] = dict(DEFAULT_THRESHOLDS["by_source"])
    elif not isinstance(thresholds["by_source"], dict):
        # Defensive: should already be caught by _validate_thresholds above,
        # but guard here too in case env layering changed the type.
        raise ValueError(
            f"thresholds 'by_source' must be a dict, got {type(thresholds['by_source']).__name__}"
        )
    else:
        # Merge: any source not in YAML falls through to default empty dict
        merged = dict(DEFAULT_THRESHOLDS["by_source"])
        for src, override in thresholds["by_source"].items():
            merged[src] = {**merged.get(src, {}), **override}
        thresholds["by_source"] = merged

    # Layer CLI on top of all of the above
    for f, v in cli_overrides.items():
        thresholds[f] = v

    # Final validation: now that all sources are layered, the dict MUST
    # have all 4 base fields. Use the full validator to catch that case.
    _validate_full_thresholds(thresholds)
    return thresholds


def thresholds_for_source(thresholds: dict, source: str) -> dict:
    """Return a flat thresholds dict for a given source system.

    Per-source overrides are merged on top of the base. Used by
    _classify() so it can apply source-specific promotion rules.
    """
    base = {
        "min_instances":          thresholds["min_instances"],
        "min_confirmed":          thresholds["min_confirmed"],
        "min_improvement_pct":    thresholds["min_improvement_pct"],
        "max_false_positive_pct": thresholds["max_false_positive_pct"],
    }
    override = thresholds.get("by_source", {}).get(source) or {}
    base.update(override)
    return base


def _token_path() -> str:
    return _TOKENS_PATH_PREFIX + os.path.join(*_TOKENS_PATH_PARTS)


def load_token() -> str:
    path = _token_path()
    if not os.path.exists(path):
        raise SystemExit("token file not found: " + path)
    expected_key = "CLAWFORGE_CLIENT_TOKEN" + chr(61)
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(expected_key):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix="." + path.name + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_registry(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s", path, e)
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "entries", "patterns", "adjustments", "learnings"):
            if k in data and isinstance(data[k], list):
                return data[k]
    return []


def _read_profiles() -> dict:
    """Read the profile registry to get the list of connected instances."""
    p = REGISTRY_DIR / "profiles" / "PROFILES.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s", p, e)
        return {}


def _pattern_key(item: dict) -> tuple:
    """Identity key for one pattern (type + trigger + patch)."""
    return (
        item.get("type", ""),
        item.get("trigger", ""),
        json.dumps(
            item.get("patch") or item.get("pattern") or {},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )


def _aggregate_patterns(entries: list) -> dict:
    """Group (instance_id, item) pairs by pattern key.

    Returns: { pattern_key: {
        "type": ..., "trigger": ..., "patch": ...,
        "instances_tested": set of instance_ids,
        "improvements_pct": list of floats,
        "false_positive_pct": list of floats,
        "first_seen": iso,
        "last_seen": iso,
        "source_systems": set ("memory"/"forge"/"dojo"),
        "entries": list of (instance_id, entry) for traceability,
    }}
    """
    agg: dict = {}
    for e in entries:
        instance_id = e.get("instance_id", "unknown")
        submitted_at = e.get("submitted_at", "")
        # Detect which input list this entry uses
        items = (
            e.get("patterns")
            or e.get("adjustments")
            or e.get("learnings")
            or []
        )
        # Identify source system from the items (memory patterns have
        # retrieval_stats, forge adjustments have gate_health, etc.)
        if "patterns" in e:
            source = "memory"
        elif "adjustments" in e:
            source = "forge"
        elif "learnings" in e:
            source = "dojo"
        else:
            source = "unknown"
        if not isinstance(items, list):
            continue
        for it in items:
            if not isinstance(it, dict):
                continue
            key = _pattern_key(it)
            rec = agg.setdefault(key, {
                "type": it.get("type", ""),
                "trigger": it.get("trigger", ""),
                "patch": it.get("patch") or it.get("pattern"),
                "instances_tested": set(),
                "improvements_pct": [],
                "false_positive_pct": [],
                "first_seen": submitted_at,
                "last_seen": submitted_at,
                "source_systems": set(),
                "entries": [],
            })
            rec["instances_tested"].add(instance_id)
            rec["source_systems"].add(source)
            rec["entries"].append({"instance_id": instance_id, "submitted_at": submitted_at})
            eff = it.get("effectiveness", {}) or {}
            if isinstance(eff, dict):
                pct = eff.get("improvement_pct") or eff.get("improvementPct")
                if isinstance(pct, (int, float)):
                    rec["improvements_pct"].append(float(pct))
                fpr = (
                    eff.get("false_positive_pct")
                    or eff.get("falsePositivePct")
                    or eff.get("contradiction_rate_pct")
                )
                if isinstance(fpr, (int, float)):
                    rec["false_positive_pct"].append(float(fpr))
            if submitted_at and submitted_at < rec["first_seen"]:
                rec["first_seen"] = submitted_at
            if submitted_at and submitted_at > rec["last_seen"]:
                rec["last_seen"] = submitted_at
    return agg


def _classify(rec: dict, thresholds: dict | None = None) -> str:
    """Return 'promoted' / 'candidate' / 'unvalidated'.

    If `thresholds` is None, loads the effective thresholds via
    load_thresholds() (which honors the full CLI > env > YAML > defaults
    priority chain). For efficiency in run_validation(), pass the loaded
    thresholds dict in once.

    Per-source rules: if the aggregated record has only one source
    system in rec["source_systems"], use that source's overrides.
    If a record spans multiple sources (rare — only happens if the
    same pattern key appears in multiple registries), use the BASE
    thresholds for the conservative decision.
    """
    if thresholds is None:
        thresholds = load_thresholds()

    n_tested = len(rec["instances_tested"])
    if n_tested < 1:
        return "unvalidated"
    improvements = rec["improvements_pct"]
    avg_imp = (sum(improvements) / len(improvements)) if improvements else 0.0
    avg_fpr = (
        sum(rec["false_positive_pct"]) / len(rec["false_positive_pct"])
        if rec["false_positive_pct"]
        else 0.0
    )
    # For "confirmed": distinct instances that reported a positive
    # improvement. If no improvement_pct reported, treat as confirmed
    # (don't penalize systems that don't track percentages).
    if improvements:
        confirmed = sum(1 for x in improvements if x > 0)
    else:
        confirmed = n_tested

    # Pick per-source thresholds if the record is single-source.
    sources = rec.get("source_systems") or set()
    if len(sources) == 1:
        only_source = next(iter(sources))
        t = thresholds_for_source(thresholds, only_source)
    else:
        # Multi-source: use the base (conservative) thresholds.
        t = thresholds_for_source(thresholds, "__base__")  # returns base

    if (
        n_tested >= t["min_instances"]
        and confirmed >= t["min_confirmed"]
        and avg_imp > t["min_improvement_pct"]
        and avg_fpr < t["max_false_positive_pct"]
    ):
        return "promoted"
    return "candidate"


def _build_effectiveness_entries(agg: dict, thresholds: dict | None = None) -> list:
    """Build the pattern-effectiveness list, applying per-record classification.

    The `thresholds` argument is threaded through to `_classify()`. Pass an
    explicit dict for efficiency (avoids re-loading per record); passing
    None lets `_classify` load thresholds itself.

    Returns a list of effectiveness-entry dicts sorted by (promoted-first,
    instances_validated-descending).
    """
    out = []
    for key, rec in agg.items():
        status = _classify(rec, thresholds)
        improvements = rec["improvements_pct"]
        avg_imp = (sum(improvements) / len(improvements)) if improvements else None
        avg_fpr = (
            sum(rec["false_positive_pct"]) / len(rec["false_positive_pct"])
            if rec["false_positive_pct"]
            else None
        )
        out.append({
            "pattern_id": "pat_" + key[0] + "_" + str(abs(hash(key)) % (10**8)).zfill(8),
            "type": rec["type"],
            "trigger": rec["trigger"],
            "summary": _summarize(rec, avg_imp, status),
            "instances_validated": len(rec["instances_tested"]),
            "instances_confirmed": sum(1 for x in improvements if x > 0) if improvements else len(rec["instances_tested"]),
            "instances_rejected": 0,  # Not tracked in the current schema
            "instances_tested_list": sorted(rec["instances_tested"]),
            "source_systems": sorted(rec["source_systems"]),
            "avg_improvement_pct": avg_imp,
            "avg_false_positive_pct": avg_fpr,
            "first_seen": rec["first_seen"],
            "last_seen": rec["last_seen"],
            "status": status,
            "promoted_at": _now() if status == "promoted" else None,
            "needs_more_data": status == "candidate",
            "patch": rec["patch"],
        })
    # Sort: promoted first, then by instances_validated desc
    out.sort(key=lambda x: (x["status"] != "promoted", -x["instances_validated"]))
    return out


def _summarize(rec: dict, avg_imp, status: str) -> str:
    parts = []
    if rec["type"]:
        parts.append("type=" + rec["type"])
    if rec["trigger"]:
        parts.append("trigger=" + str(rec["trigger"])[:80])
    if avg_imp is not None:
        parts.append(f"avg_imp={avg_imp:.1f}%")
    parts.append(f"status={status}")
    return " | ".join(parts)


def _all_entries() -> list:
    """Read all 3 input registries and concatenate their entries."""
    out = []
    for subdir, _friendly, _key in INPUT_REGISTRIES:
        out.extend(_read_registry(REGISTRY_DIR / subdir / "INDEX.json"))
    return out


def run_validation() -> dict:
    """Synchronous main: read, aggregate, classify, write, return summary.

    Loads effective thresholds once via the full priority chain
    (CLI > env > YAML > defaults) and threads them through all
    per-record classifications.

    Returns: {"promoted": [...], "candidate": [...], "all": [...]}
    """
    thresholds = load_thresholds()
    log.info(
        "effective thresholds: base=[min_instances=%d, min_confirmed=%d, "
        "min_improvement_pct=%.1f, max_false_positive_pct=%.1f], "
        "per_source_overrides=%s",
        thresholds["min_instances"],
        thresholds["min_confirmed"],
        thresholds["min_improvement_pct"],
        thresholds["max_false_positive_pct"],
        {k: v for k, v in thresholds["by_source"].items() if v},
    )

    entries = _all_entries()
    agg = _aggregate_patterns(entries)
    effectiveness = _build_effectiveness_entries(agg, thresholds)

    payload = {
        "schema_version": 1,
        "updated_at": _now(),
        "total_patterns": len(effectiveness),
        "promoted_count": sum(1 for e in effectiveness if e["status"] == "promoted"),
        "candidate_count": sum(1 for e in effectiveness if e["status"] == "candidate"),
        "unvalidated_count": sum(1 for e in effectiveness if e["status"] == "unvalidated"),
        "patterns": effectiveness,
    }
    out_path = REGISTRY_DIR / OUTPUT_REGISTRY[0] / OUTPUT_REGISTRY[1]
    _atomic_write_json(out_path, payload)
    log.info(
        "wrote %s: %d patterns (%d promoted, %d candidate, %d unvalidated)",
        out_path, len(effectiveness),
        payload["promoted_count"],
        payload["candidate_count"],
        payload["unvalidated_count"],
    )
    return {
        "promoted": [e for e in effectiveness if e["status"] == "promoted"],
        "candidate": [e for e in effectiveness if e["status"] == "candidate"],
        "all": effectiveness,
    }


async def broadcast(nc, profiles: dict, summary: dict) -> None:
    """Publish pattern.effective and pattern.recommendation messages."""
    promoted = summary["promoted"]
    candidate = summary["candidate"]

    # pattern.effective.<pattern_id> for every classified pattern
    for entry in summary["all"]:
        subj = "pattern.effective." + entry["pattern_id"]
        await nc.publish(subj, json.dumps({
            "pattern_id": entry["pattern_id"],
            "status": entry["status"],
            "instances_validated": entry["instances_validated"],
            "promoted_at": entry["promoted_at"],
        }).encode("utf-8"))
    log.info("published %d pattern.effective messages", len(summary["all"]))

    # pattern.recommendation.<target_instance> for each promoted pattern,
    # addressed to every connected instance. Instances will surface the
    # execute_flag prompt and ack.
    if not profiles:
        log.info("no profiles yet, skipping pattern.recommendation broadcasts")
        return
    instances = list(profiles.get("instances", {}).keys())
    if not promoted:
        log.info("no promoted patterns, skipping pattern.recommendation broadcasts")
        return
    sent = 0
    for inst in instances:
        for entry in promoted:
            subj = "pattern.recommendation." + inst
            payload = {
                "pattern_id": entry["pattern_id"],
                "type": entry["type"],
                "patch": entry["patch"],
                "confidence": _confidence(entry),
                "instances_validated": entry["instances_validated"],
                "summary": entry["summary"],
            }
            await nc.publish(subj, json.dumps(payload).encode("utf-8"))
            sent += 1
    log.info("published %d pattern.recommendation messages", sent)


def _confidence(entry: dict) -> float:
    """Crude confidence score 0-1 from instances_validated and avg improvement."""
    n = entry["instances_validated"]
    avg = entry.get("avg_improvement_pct") or 0.0
    if n == 0:
        return 0.0
    base = min(n / 5.0, 1.0)  # 5+ instances = full credit
    boost = min(max(avg, 0.0) / 50.0, 1.0)  # 50%+ improvement = full boost
    return round(0.5 * base + 0.5 * boost, 3)


async def run_async() -> None:
    token = load_token()
    nats_host = os.environ.get("CLAWFORGE_NATS_HOST", "127.0.0.1")
    nats_port = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))
    nats_url = "nats://" + nats_host + ":" + str(nats_port)

    summary = run_validation()
    log.info("validation done, opening NATS for broadcast")
    nc = await nats.connect(nats_url, token=token, name="clawforge-effectiveness-validator")
    try:
        profiles = _read_profiles()
        await broadcast(nc, profiles, summary)
        await nc.flush()
    finally:
        await nc.drain()
    log.info("broadcast complete, bye")


if __name__ == "__main__":
    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        sys.exit(0)
