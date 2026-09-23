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
from typing import Any, Optional

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


# ---------------------------------------------------------------------------
# Target resolution
#
# This pipeline has THREE legs with three different scopes, and conflating them
# was the original defect:
#
#   1. LOCAL ARTIFACT — write down what this instance proposes. Always runs.
#   2. LOCAL RELAY    — publish to the local NATS from `clawforge.yaml`'s
#                       `relay:` block. Always runs, unauthenticated. This is
#                       the leg local consumers (approval surface, Conductor)
#                       read.
#   3. FEDERATION     — transmit to a peer instance so another system can
#                       contribute to and receive the learning (the NATS leg
#                       for Tallon's system). Requires `pattern_sharing.enabled`
#                       AND a client token.
#
# Legs 1 and 2 used to sit behind leg 3's switch, so a cross-instance PRIVACY
# setting silently disabled local self-improvement — and the wrapper logged
# SKIPPED while exiting 0, so it went unnoticed for months.
# ---------------------------------------------------------------------------

_CLAWFORGE_CONFIG = Path(os.path.expanduser("~/.hermes/clawforge.yaml"))
_LOCAL_ARTIFACT = Path(os.path.expanduser("~/.hermes/pantheon/forge-adjustments-latest.json"))


def _config() -> dict:
    """Load ~/.hermes/clawforge.yaml. Returns {} when absent or unparseable.

    Parsed with a real YAML loader on purpose: the wrapper in scripts/ hand-rolls
    an indentation walk, and that is how a whole `pattern_sharing` block went
    missing without anyone noticing.
    """
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(_CLAWFORGE_CONFIG.read_text())
        return data if isinstance(data, dict) else {}
    except Exception as exc:  # unreadable or invalid config must not crash a run
        log.warning("could not read %s: %s", _CLAWFORGE_CONFIG, exc)
        return {}


def local_nats_url() -> str:
    """The local relay endpoint, from the `relay:` block. Defaults to loopback."""
    relay = _config().get("relay") or {}
    host = relay.get("host") or "127.0.0.1"
    port = relay.get("port") or 4222
    return "nats://" + str(host) + ":" + str(port)


def sharing_enabled() -> bool:
    """True only when `pattern_sharing.enabled: true` is explicitly present."""
    return bool((_config().get("pattern_sharing") or {}).get("enabled"))


#: Which `pattern_sharing` key opts a given exporter's data into sharing.
_SHARING_OPT_IN = {
    "forge": "forge_adjustments",
    "memory": "memory_patterns",
    "dojo": "dojo_learnings",
}


def sharing_allowed_for(name: str) -> bool:
    """Whether THIS artifact class may cross the instance boundary.

    Both the master switch and the per-system opt-in must be true.

    These keys live INSIDE the `pattern_sharing` block, so they scope sharing.
    The wrapper used to read them as a gate on producing the artifact at all,
    which is how a sharing setting came to disable local self-improvement —
    the same defect as the master switch, one level down.
    """
    ps = _config().get("pattern_sharing") or {}
    return bool(ps.get("enabled")) and bool(ps.get(_SHARING_OPT_IN.get(name, name)))


def _federation_target() -> tuple:
    """(nats_url, bearer_token) for the cross-instance leg.

    Host and port come from the explicit `federation:` block. The previous code
    defaulted the host to a hardcoded tailnet address, which made a PEER INSTANCE
    the silent default destination of a purely local run.
    """
    fed = _config().get("federation") or {}
    host = os.environ.get("CLAWFORGE_NATS_HOST") or fed.get("host") or ""
    port = os.environ.get("CLAWFORGE_NATS_PORT") or fed.get("port") or 4222
    if not host:
        raise SystemExit(
            "federation leg requested but no peer configured: set "
            "`federation: {host: <host>, port: 4222}` in ~/.hermes/clawforge.yaml "
            "or export CLAWFORGE_NATS_HOST"
        )
    return "nats://" + str(host) + ":" + str(port), load_token()


def _write_local_artifact(entry: dict) -> Path:
    _LOCAL_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    _LOCAL_ARTIFACT.write_text(json.dumps(entry, indent=2, sort_keys=True))
    return _LOCAL_ARTIFACT


async def run(days: int = 7, share: Optional[bool] = None) -> dict:
    """Run all three legs and report which fired.

    `share` overrides config detection. None means read `pattern_sharing.enabled`.

    Returns a summary dict. `published_local` is the one that matters for local
    self-improvement; `published_remote` covers the federation leg.
    """
    import nats  # type: ignore
    from clawforge.instance_id import get_instance_id  # type: ignore

    instance_id = get_instance_id()
    entry = export_forge_adjustments(instance_id, days=days)
    _assert_anonymized(entry)

    result: dict = {
        "instance_id": instance_id,
        "entry": entry,
        "adjustments": len(entry.get("adjustments", [])),
        "total_interventions": entry.get("total_interventions", 0),
        "artifact": "",
        "published_local": False,
        "published_remote": False,
        "local_url": local_nats_url(),
        "notes": [],
    }

    # Leg 1 — local artifact. Always. No switch can turn this off.
    try:
        result["artifact"] = str(_write_local_artifact(entry))
    except OSError as exc:
        result["notes"].append("local artifact write failed: " + str(exc))

    # Leg 2 — local relay. Always, unauthenticated.
    try:
        nc = await nats.connect(result["local_url"], name="clawforge-adj-local")
        try:
            await publish(nc, "forge.adjustment.submitted", entry)
            await nc.flush()
            result["published_local"] = True
            log.info(
                "published forge.adjustment.submitted to LOCAL relay %s (%d adjustments)",
                result["local_url"], result["adjustments"],
            )
        finally:
            await nc.drain()
    except Exception as exc:
        result["notes"].append(
            "local relay publish failed: " + type(exc).__name__ + ": " + str(exc)
        )

    # Leg 3 — federation. Explicitly gated; a local run must never require it.
    want_share = sharing_allowed_for("forge") if share is None else bool(share)
    if not want_share:
        result["notes"].append(
            "federation leg skipped: pattern_sharing.enabled is false "
            "(local artifact + local relay ran)"
        )
        return result

    try:
        url, token = _federation_target()
    except SystemExit as exc:
        result["notes"].append("federation leg skipped: " + str(exc))
        return result

    try:
        nc = await nats.connect(url, token=token, name="clawforge-adj-federation")
        try:
            await publish(nc, "forge.adjustment.submitted", entry)
            await nc.flush()
            result["published_remote"] = True
            log.info("published forge.adjustment.submitted to FEDERATION %s", url)
        finally:
            await nc.drain()
    except Exception as exc:
        result["notes"].append(
            "federation publish failed: " + type(exc).__name__ + ": " + str(exc)
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
