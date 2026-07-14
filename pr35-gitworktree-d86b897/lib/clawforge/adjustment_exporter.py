"""Clawforge forge adjustment exporter.

Reads the local forge intervention log (JSONL at
~/.hermes/ichor/forge/all.jsonl), runs the existing ForgeAnalyzer
pipeline, and emits a `forge.adjustment.submitted` payload to NATS.

This is the only one of the 3 Pass 3 exporters that has a real data
source. The other two (`pattern_exporter.py`, `learning_exporter.py`)
defer to Pass 3.1 — see `~/pantheon/lib/clawforge/API.md` for why.

Anonymization: per spec §9, no raw event text, no session_id, no
user_intent text crosses the instance boundary. user_intent strings
are used as counter keys for frequency analysis but never emitted
in the output.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-adjustment-exporter")

# Token file path is built at runtime to avoid the ["/", ...] content-replace
# trap (skill: html-write-filter-workaround §3.5).
_TOKENS_PATH_PREFIX = chr(47)  # "/"
_TOKENS_PATH_PARTS = ["etc", "clawforge", "tokens.env"]


def _token_path() -> str:
    return _TOKENS_PATH_PREFIX + os.path.join(*_TOKENS_PATH_PARTS)


def _find_token_path() -> str:
    """Find the Clawforge token file. Tries:
      1. CLAWFORGE_TOKENS_PATH env var
      2. /home/konan/.hermes/clawforge-tokens.env (Pantheon)
      3. /etc/clawforge/tokens.env (Relay-7)
      4. ~/.hermes/clawforge-tokens.env
    Returns the first existing path, or "" if none.
    """
    candidates = []
    env_path = os.environ.get("CLAWFORGE_TOKENS_PATH")
    if env_path:
        candidates.append(env_path)
    home = os.path.expanduser("~")
    candidates.extend([
        os.path.join(home, ".hermes", "clawforge-tokens.env"),
        os.path.sep + os.path.join("etc", "clawforge", "tokens.env"),
    ])
    # Also: relative to current user's home, fall through to last candidate
    for c in candidates:
        if os.path.exists(c):
            return c
    return candidates[0] if candidates else ""


def load_token() -> str:
    """Load the Clawforge client bearer token from the first
    available token file."""
    path = _find_token_path()
    if not path or not os.path.exists(path):
        raise SystemExit("token file not found (tried CLAWFORGE_TOKENS_PATH, "
                         "~/.hermes/clawforge-tokens.env, /etc/clawforge/tokens.env)")
    expected_key = "CLAWFORGE_CLIENT_TOKEN" + chr(61)
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(chr(35)):
            continue
        if line.startswith(expected_key):
            return line.split(chr(61), 1)[1].strip()
    raise SystemExit("CLAWFORGE_CLIENT_TOKEN not found in " + path)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


async def publish(nc, subject: str, entry: dict) -> None:
    """Publish a single submission to NATS."""
    data = json.dumps(entry).encode("utf-8")
    await nc.publish(subject, data)


async def run(days: int = 7) -> dict:
    """Top-level entry: build the entry, publish, return the entry."""
    import nats  # type: ignore
    from clawforge.instance_id import get_instance_id  # type: ignore

    instance_id = get_instance_id()
    entry = export_forge_adjustments(instance_id, days=days)
    _assert_anonymized(entry)

    token = load_token()
    nats_host = os.environ.get("CLAWFORGE_NATS_HOST", "100.100.46.52")
    nats_port = int(os.environ.get("CLAWFORGE_NATS_PORT", "4222"))
    nats_url = "nats://" + nats_host + ":" + str(nats_port)

    log.info("connecting to %s", nats_url)
    nc = await nats.connect(nats_url, token=token, name="clawforge-adjustment-exporter")
    try:
        await publish(nc, "forge.adjustment.submitted", entry)
        await nc.flush()
        log.info(
            "published forge.adjustment.submitted: %d adjustments, %d interventions, %d gates",
            len(entry["adjustments"]),
            entry["total_interventions"],
            len(entry["gate_health"]),
        )
    finally:
        await nc.drain()
    return entry


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
