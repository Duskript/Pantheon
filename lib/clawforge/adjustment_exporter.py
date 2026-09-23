"""Clawforge forge adjustment exporter.

Reads the local forge intervention log (JSONL at
~/.hermes/ichor/forge/all.jsonl), runs the existing ForgeAnalyzer
pipeline, and emits a `forge.adjustment.submitted` payload to NATS.

All three Pass 3 exporters now have real data sources; the sibling modules
(`pattern_exporter.py`, `learning_exporter.py`) cover memory patterns and dojo
learnings. What they share — the three export legs, target resolution, token
loading — lives in `clawforge.legs`, so the lanes cannot drift apart again.

Anonymization: per spec §9, no raw event text, no session_id, no
user_intent text crosses the instance boundary. user_intent strings
are used as counter keys for frequency analysis but never emitted
in the output.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any, Optional

from clawforge.legs import (  # type: ignore
    _find_token_path,
    SHARING_OPT_IN,
    config as _config,
    federation_target as _federation_target,
    load_token,
    local_nats_url,
    now_iso as _now,
    publish,
    run_legs,
    sharing_allowed_for,
    sharing_enabled,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-adjustment-exporter")


# Token loading, `_now`, `publish`, `_config`/`local_nats_url`/
# `sharing_enabled`/`sharing_allowed_for`/`_federation_target` and the three-leg
# run are all imported from `clawforge.legs`. They are re-exported under their
# original names here for existing callers.
#
# A private copy of this machinery is exactly how this lane and its two siblings
# drifted apart: this file was fixed on 2026-09-22 while the other two kept a
# hardcoded peer address as their silent destination and had no local leg at
# all. See `clawforge/legs.py` for the gating rules.


# Mapping from ForgeAdjustment.target to the Clawforge "type" field.
# ForgeAdjustment.target values: intent_keywords, phase_keywords,
# phase_tools, logic_checks, model_thresholds, ...
_TARGET_TO_TYPE = {
    "model_thresholds": "model_threshold",
    "intent_keywords":   "keyword_addition",
    "phase_keywords":    "keyword_addition",
    "phase_tools":       "tool_adjustment",
    "logic_checks":      "logic_check",
}


def _gate_health(metrics: dict) -> dict:
    """Convert ForgeAnalyzer's per-gate metrics into the Clawforge
    `gate_health` shape: { gate_name: {interventions, block_rate, healthy} }.
    """
    out = {}
    for gate_name, gm in metrics.items():
        out[gate_name] = {
            "interventions": gm.total,
            "block_rate": round(gm.block_rate, 4),
            # Healthy = not over-blocking (<60%) and not under-blocking
            # (≥5% with >20 calls). ForgeAnalyzer has these as
            # properties; we recompute defensively.
            "healthy": not (gm.is_over_blocking or gm.is_under_blocking),
        }
    return out


def _adjustment_to_clawforge(adj, total_interventions: int) -> dict:
    """Convert a ForgeAdjustment into the Clawforge adjustments entry
    shape. ForgeAdjustment fields: target, action, item, reason, confidence.
    """
    claw_type = _TARGET_TO_TYPE.get(adj.target, adj.target)
    # "Effectiveness" in the spec's schema is before/after stats. We
    # have current state but no historical baseline; report the
    # current state and let cross-instance aggregation figure out
    # improvement.
    return {
        "type": claw_type,
        "gate": None,  # ForgeAdjustment doesn't carry gate; set by caller if known
        "target": adj.target,
        "action": adj.action,
        "item": adj.item,
        "old_value": None,        # not tracked in ForgeAdjustment
        "new_value": None,
        "reason": adj.reason,
        "effectiveness": {
            "instances_tested": 1,
            "interventions": total_interventions,
            "improvement_pct": None,  # unknown; aggregator will derive from cross-instance data
            "confidence": adj.confidence,
        },
    }


def export_forge_adjustments(instance_id: str, days: int = 7) -> dict:
    """Build the forge-adjustments.json submission entry from local
    intervention data. See API.md for the full schema.
    """
    # Import here (not at module top) so the self-test can run
    # without nats-py installed.
    from ichor_forge import ForgeAnalyzer  # type: ignore

    analyzer = ForgeAnalyzer()
    records = analyzer.load_records(days=days)
    if not records:
        log.info("no forge records in last %d days; emitting empty submission", days)
        return {
            "schema_version": 1,
            "instance_id": instance_id,
            "submitted_at": _now(),
            "span_days": days,
            "total_interventions": 0,
            "adjustments": [],
            "gate_health": {},
        }

    metrics = analyzer.compute_metrics(records)
    patterns = analyzer.detect_patterns(records, metrics)
    adjustments = analyzer.suggest_adjustments(records, patterns)
    clawforge_adjustments = [
        _adjustment_to_clawforge(a, len(records)) for a in adjustments
    ]

    entry = {
        "schema_version": 1,
        "instance_id": instance_id,
        "submitted_at": _now(),
        "span_days": days,
        "total_interventions": len(records),
        "adjustments": clawforge_adjustments,
        "gate_health": _gate_health(metrics),
    }
    return entry


def _assert_anonymized(entry: dict) -> None:
    """Self-test guard: ensure no forbidden keys are present in the
    submission entry.
    """
    forbidden_top = {"session_id", "query", "user_id", "raw_text"}
    for k in forbidden_top:
        if k in entry:
            raise AssertionError("forbidden key at top level: " + k)
    for adj in entry.get("adjustments", []):
        for k in forbidden_top:
            if k in adj:
                raise AssertionError("forbidden key in adjustment: " + k)
        # user_intent text must not appear in the reason (we use the
        # reason field as a *summary*, not raw text)
        reason = adj.get("reason", "")
        if "user_intent" in reason.lower() and len(reason) > 200:
            raise AssertionError("reason field looks like raw user_intent: " + reason[:80])
    inst = entry.get("instance_id", "")
    if len(inst) != 12 or not all(c in "0123456789abcdef" for c in inst):
        raise AssertionError("instance_id wrong format: " + repr(inst))


# ---------------------------------------------------------------------------
# The three export legs (local artifact / local relay / federation), target
# resolution and the sharing gates all live in `clawforge.legs`, shared by all
# three exporters. A private copy here is how this lane drifted from its
# siblings in the first place — the other two kept a hardcoded peer address as
# their silent destination and had no local leg while this one was fixed.
# ---------------------------------------------------------------------------


async def run(days: int = 7, share: Optional[bool] = None) -> dict:
    """Run all three legs and report which fired.

    `share` overrides config detection. None means read the per-system
    `pattern_sharing` opt-in (see `clawforge.legs.sharing_allowed_for`).

    Returns the summary dict from `run_legs`: `published_local` is the one that
    matters for local self-improvement; `published_remote` covers the federation
    leg. The built payload is under `entry`, with `instance_id`, `adjustments`
    and `total_interventions` echoed for the wrapper's log line.
    """
    from clawforge.instance_id import get_instance_id  # type: ignore

    instance_id = get_instance_id()
    entry = export_forge_adjustments(instance_id, days=days)
    _assert_anonymized(entry)

    result = await run_legs("forge", entry, share=share)
    result["instance_id"] = instance_id
    result["adjustments"] = len(entry.get("adjustments", []))
    result["total_interventions"] = entry.get("total_interventions", 0)
    log.info(
        "forge.adjustment.submitted: %d adjustments from %d interventions "
        "(local=%s, federation=%s)",
        result["adjustments"],
        result["total_interventions"],
        result["published_local"],
        result["published_remote"],
    )
    return result


if __name__ == "__main__":
    # Self-test: build the entry, print it, assert anonymization.
    from clawforge.instance_id import get_instance_id  # type: ignore

    inst = get_instance_id()
    entry = export_forge_adjustments(inst, days=30)
    _assert_anonymized(entry)
    print(json.dumps(entry, indent=2))
    print("---")
    print("self-test OK: instance_id=" + inst + ", adjustments=" + str(len(entry["adjustments"])))

    # If --publish flag passed, actually publish
    if "--publish" in sys.argv:
        asyncio.run(run(days=30))
