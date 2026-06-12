#!/usr/bin/env python3
"""Clawforge Federation Stats (relay-7, run via systemd timer).

Reads the 3 source registries (memory-patterns, forge-adjustments,
dojo-learnings) + pattern-effectiveness.json, and computes aggregated
federation statistics for the public-facing community dashboard at
federation.theoforgesolutions.com/INDEX.json.

Output is privacy-first: aggregated counts and effectiveness metrics
ONLY — no patch content, no trigger strings, no submission text, no
per-instance submission timestamps. Instance identities are exposed
(anonymous hash + display name from PROFILES.json) so a federation
participant can see their own row in the leaderboard, but the content
they submitted stays private.

Inputs (read-only):
  /var/www/clawforge/memory-patterns/INDEX.json
  /var/www/clawforge/forge-adjustments/INDEX.json
  /var/www/clawforge/dojo-learnings/INDEX.json
  /var/www/clawforge/pattern-effectiveness/INDEX.json
  /var/www/clawforge/profiles/PROFILES.json

Output (atomic write):
  /var/www/clawforge/federation/INDEX.json

Cadence: every 5 minutes (clawforge-federation-stats.timer). Federation
stats are aggregated counts and are safe to compute and publish often.

PRIVACY CONTRACT (enforced in _sanitize()):
  - The following fields from any pattern are STRIPPED before aggregation:
      patch, pattern, trigger, source_ref, submitted_at, submitted_by_session
  - The following are KEPT (anonymized/aggregated):
      type, effectiveness.improvement_pct (as a number),
      effectiveness.false_positive_pct (as a number)
  - Instance identities are kept as 12-hex-char anonymous hashes +
    display_name from PROFILES.json. If the instance_id is not in
    PROFILES.json, it's listed as "unregistered" but the count still
    shows.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-federation-stats")

REGISTRY_DIR = Path("/var/www/clawforge")

INPUT_REGISTRIES = [
    ("memory-patterns",   "patterns",     "memory"),
    ("forge-adjustments", "adjustments",  "forge"),
    ("dojo-learnings",    "learnings",    "dojo"),
]

OUTPUT_REGISTRY = ("federation", "INDEX.json")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically: write to .tmp in same dir, os.replace()."""
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
    """Read a registry file. Tolerates list-shaped or empty files."""
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
    """Read /var/www/clawforge/profiles/PROFILES.json. Returns {} if absent."""
    p = REGISTRY_DIR / "profiles" / "PROFILES.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError) as e:
        log.warning("could not read %s: %s", p, e)
        return {}


def _display_name_for(instance_id: str, profiles: dict) -> str:
    """Look up the friendly display name for an instance_id.

    Falls back to the raw instance_id (12-hex) if not in profiles.
    """
    instances = profiles.get("instances", {}) or {}
    rec = instances.get(instance_id) or {}
    return rec.get("display_name") or instance_id


# Privacy fields that MUST be stripped before any aggregation.
# These are the fields a pattern entry might contain that would leak
# user content if exposed in federation stats.
_PRIVATE_FIELDS = frozenset({
    "patch", "pattern", "adjustments", "learnings",  # the actual code/config
    "trigger", "source_ref", "source_session_id",     # semantic content
    "submitted_at", "first_seen", "last_seen",        # timing
    "item", "action", "reason", "new_value", "old_value",  # forge specifics
    "target", "old_target", "new_target",
})


def _sanitize_item(item: dict) -> dict:
    """Return a privacy-safe subset of a pattern item.

    Keeps ONLY the type, source_system tag, and numeric effectiveness
    metrics. Drops all content fields.
    """
    if not isinstance(item, dict):
        return {}
    safe: dict = {}
    # Type is safe (it's a category, not content)
    if "type" in item:
        safe["type"] = item["type"]
    # Effectiveness metrics are numeric and safe
    eff = item.get("effectiveness") or {}
    if isinstance(eff, dict):
        for k in ("improvement_pct", "improvementPct",
                  "false_positive_pct", "falsePositivePct",
                  "contradiction_rate_pct"):
            v = eff.get(k)
            if isinstance(v, (int, float)):
                safe.setdefault("effectiveness", {})[k] = float(v)
    return safe


# -----------------------------------------------------------------------------
# Core computation
# -----------------------------------------------------------------------------


def _source_for_entry(entry: dict) -> str | None:
    """Detect which source system an entry came from (memory/forge/dojo)."""
    if "patterns" in entry:
        return "memory"
    if "adjustments" in entry:
        return "forge"
    if "learnings" in entry:
        return "dojo"
    return None


def _items_in_entry(entry: dict) -> list:
    """Extract the per-entry items list (whatever it's called)."""
    for k in ("patterns", "adjustments", "learnings"):
        v = entry.get(k)
        if isinstance(v, list):
            return v
    return []


def compute_stats(profiles: dict) -> dict:
    """Compute the federation INDEX.json payload.

    Public-safe output. No patch content, no trigger strings, no
    submission timestamps. Instance identities are exposed as 12-hex
    anonymous hashes + friendly display names from PROFILES.json.
    """
    # Per-instance counters (instance_id -> {submitted, promoted, candidate, ...})
    per_instance: dict = defaultdict(lambda: {
        "submitted": 0,
        "promoted": 0,
        "candidate": 0,
        "source_systems": set(),
    })
    # Per-source counters (memory/forge/dojo -> {submitted, by_type: {type: count}})
    per_source: dict = {
        src: {
            "submitted": 0,
            "by_type": defaultdict(int),
            "avg_improvement_pct": None,   # filled below
            "avg_false_positive_pct": None,
        }
        for _, _, src in INPUT_REGISTRIES
    }
    # Per-type benchmarks (across all instances) — type -> {count, avg_imp, avg_fpr}
    per_type: dict = defaultdict(lambda: {
        "total": 0,
        "improvements": [],
        "false_positives": [],
        "source_systems": set(),
    })
    # Effectiveness aggregation (reads from pattern-effectiveness/INDEX.json)
    effectiveness_summary: dict = {
        "total_patterns": 0,
        "promoted_count": 0,
        "candidate_count": 0,
        "unvalidated_count": 0,
    }
    # Per-pattern aggregated effectiveness (privacy-safe: type, counts, averages)
    pattern_aggregates: list = []

    # Walk the 3 source registries
    for subdir, items_key, source in INPUT_REGISTRIES:
        entries = _read_registry(REGISTRY_DIR / subdir / "INDEX.json")
        source_counter = per_source[source]
        for entry in entries:
            instance_id = entry.get("instance_id", "unknown")
            items = _items_in_entry(entry)
            for item in items:
                # Increment per-instance counter
                per_instance[instance_id]["submitted"] += 1
                per_instance[instance_id]["source_systems"].add(source)
                # Increment per-source counter
                source_counter["submitted"] += 1
                # Track by type
                item_type = item.get("type", "")
                if item_type:
                    source_counter["by_type"][item_type] += 1
                    per_type[item_type]["total"] += 1
                    per_type[item_type]["source_systems"].add(source)
                # Track effectiveness metrics (numeric only)
                eff = item.get("effectiveness") or {}
                if isinstance(eff, dict):
                    imp = eff.get("improvement_pct") or eff.get("improvementPct")
                    if isinstance(imp, (int, float)):
                        per_type[item_type]["improvements"].append(float(imp))
                    fpr = (eff.get("false_positive_pct")
                           or eff.get("falsePositivePct")
                           or eff.get("contradiction_rate_pct"))
                    if isinstance(fpr, (int, float)):
                        per_type[item_type]["false_positives"].append(float(fpr))

    # Walk pattern-effectiveness for promoted/candidate counts
    pe_path = REGISTRY_DIR / "pattern-effectiveness" / "INDEX.json"
    pe_data = _read_registry(pe_path)
    # The pattern-effectiveness file is a dict (not a list); _read_registry
    # already unwraps the inner "patterns" list if present.
    # We need the TOP-LEVEL summary fields, which _read_registry DOESN'T
    # give us. Re-read the raw file:
    pe_summary: dict = {}
    if pe_path.exists():
        try:
            pe_raw = json.loads(pe_path.read_text())
            if isinstance(pe_raw, dict):
                pe_summary = {
                    "total_patterns": pe_raw.get("total_patterns", 0),
                    "promoted_count": pe_raw.get("promoted_count", 0),
                    "candidate_count": pe_raw.get("candidate_count", 0),
                    "unvalidated_count": pe_raw.get("unvalidated_count", 0),
                }
                effectiveness_summary.update(pe_summary)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("could not read %s: %s", pe_path, e)

    # Per-pattern aggregates (from the pattern-effectiveness file)
    pe_patterns = []
    if pe_path.exists():
        try:
            pe_raw = json.loads(pe_path.read_text())
            if isinstance(pe_raw, dict) and isinstance(pe_raw.get("patterns"), list):
                pe_patterns = pe_raw["patterns"]
        except (OSError, json.JSONDecodeError):
            pass
    for p in pe_patterns:
        if not isinstance(p, dict):
            continue
        # Privacy-safe: no patch, no trigger string, no timestamp
        agg = {
            "pattern_id":   p.get("pattern_id"),
            "type":         p.get("type"),
            "status":       p.get("status"),
            "instances_validated":  p.get("instances_validated", 0),
            "instances_confirmed":  p.get("instances_confirmed", 0),
            "instances_rejected":   p.get("instances_rejected", 0),
            "avg_improvement_pct":  p.get("avg_improvement_pct"),
            "avg_false_positive_pct": p.get("avg_false_positive_pct"),
            "source_systems":       sorted(p.get("source_systems") or []),
        }
        pattern_aggregates.append(agg)

    # Apply per-instance promoted/candidate counts from pattern-effectiveness
    # (we count how many patterns this instance appears in)
    for p in pe_patterns:
        if not isinstance(p, dict):
            continue
        tested = p.get("instances_tested_list") or []
        for inst in tested:
            if not isinstance(inst, str):
                continue
            per_instance[inst]["promoted"] += 1 if p.get("status") == "promoted" else 0
            per_instance[inst]["candidate"] += 1 if p.get("status") == "candidate" else 0

    # Compute per-source averages
    for src, counter in per_source.items():
        # Sum improvements/false_positives across all items of this source
        all_imps: list = []
        all_fprs: list = []
        for t, agg in per_type.items():
            if src in agg["source_systems"]:
                all_imps.extend(agg["improvements"])
                all_fprs.extend(agg["false_positives"])
        if all_imps:
            counter["avg_improvement_pct"] = round(
                sum(all_imps) / len(all_imps), 2
            )
        if all_fprs:
            counter["avg_false_positive_pct"] = round(
                sum(all_fprs) / len(all_fprs), 2
            )
        # Convert defaultdict-by_type to plain dict
        counter["by_type"] = dict(counter["by_type"])

    # Compute per-type averages and prepare for output
    type_benchmarks: list = []
    for t, agg in per_type.items():
        if agg["total"] == 0:
            continue
        avg_imp = (round(sum(agg["improvements"]) / len(agg["improvements"]), 2)
                   if agg["improvements"] else None)
        avg_fpr = (round(sum(agg["false_positives"]) / len(agg["false_positives"]), 2)
                   if agg["false_positives"] else None)
        type_benchmarks.append({
            "type": t,
            "total_submissions": agg["total"],
            "avg_improvement_pct": avg_imp,
            "avg_false_positive_pct": avg_fpr,
            "source_systems": sorted(agg["source_systems"]),
        })
    type_benchmarks.sort(key=lambda x: -x["total_submissions"])

    # Instance health rows (public-safe: just counts + display name)
    instance_health: list = []
    for inst_id, counter in per_instance.items():
        instance_health.append({
            "instance_id":  inst_id,
            "display_name": _display_name_for(inst_id, profiles),
            "submitted":    counter["submitted"],
            "promoted":     counter["promoted"],
            "candidate":    counter["candidate"],
            "source_systems": sorted(counter["source_systems"]),
        })
    # Sort: most submissions first, then most promoted
    instance_health.sort(key=lambda x: (-x["submitted"], -x["promoted"]))

    # Pattern quality leaderboard: same as instance_health but
    # ranked by promoted-count, with submission-count as tiebreaker
    leaderboard = sorted(
        instance_health,
        key=lambda x: (-x["promoted"], -x["submitted"]),
    )

    # Top-level payload
    payload = {
        "schema_version": 1,
        "updated_at": _now(),
        # Top-level aggregates
        "totals": {
            "instances":        len(per_instance),
            "submissions":      sum(c["submitted"]   for c in per_instance.values()),
            "patterns_promoted": effectiveness_summary["promoted_count"],
            "patterns_candidate": effectiveness_summary["candidate_count"],
            "patterns_unvalidated": effectiveness_summary["unvalidated_count"],
        },
        # Per-source aggregates
        "by_source": per_source,
        # Per-type cross-instance benchmarks
        "cross_instance_benchmarks": type_benchmarks,
        # Pattern-level aggregates (privacy-safe: no patch, no trigger)
        "patterns": pattern_aggregates,
        # Instance health (counts only, no submission content)
        "instance_health": instance_health,
        # Pattern quality leaderboard (sorted by promoted count)
        "pattern_quality_leaderboard": leaderboard,
        # Privacy contract (for the curious / auditors)
        "_privacy": {
            "stripped_fields": sorted(_PRIVATE_FIELDS),
            "instance_id_is_anonymous_hash": True,
            "patch_content_exposed": False,
            "trigger_strings_exposed": False,
            "submission_timestamps_exposed": False,
        },
    }

    return payload


def write_federation_index(payload: dict) -> Path:
    """Write the federation INDEX.json to the output dir. Returns the path."""
    out_path = REGISTRY_DIR / OUTPUT_REGISTRY[0] / OUTPUT_REGISTRY[1]
    _atomic_write_json(out_path, payload)
    log.info(
        "wrote %s: %d instances, %d submissions, %d patterns (%d promoted, %d candidate)",
        out_path,
        payload["totals"]["instances"],
        payload["totals"]["submissions"],
        len(payload["patterns"]),
        payload["totals"]["patterns_promoted"],
        payload["totals"]["patterns_candidate"],
    )
    return out_path


def run() -> dict:
    """Main: read, compute, write. Returns the payload for testability."""
    profiles = _read_profiles()
    log.info(
        "loaded profiles: %d instances registered",
        len(profiles.get("instances", {}) or {}),
    )
    payload = compute_stats(profiles)
    write_federation_index(payload)
    return payload


if __name__ == "__main__":
    run()
