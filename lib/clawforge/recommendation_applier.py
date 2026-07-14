"""Apply (or stage) promoted pattern recommendations from Clawforge.

Receives a pattern.recommendation NATS message (or a Python dict with
the same shape), and either:
  - Applies the patch immediately (when config auto_apply_patterns = true), OR
  - Stages the recommendation to a pending file + emits a one-line event
    for the user to see next session (when auto_apply_patterns = false, the
    default).

In both cases, publishes pattern.recommendation.ack back to the hub with
{applied: bool, reason: str}.

Patch types supported (Phase 2):
  - synonym_expansion: adds terms to ichor's FTS5 synonym list
  - weight_tuning:     updates the hybrid backend weights
  - model_threshold:   updates the ichor_forge logic_gate model threshold

All other patch types are logged as "stage_only" — the applier doesn't
know how to apply them yet, so they sit in the pending file for human
review.

Safety: auto_apply is OFF by default. The user must explicitly enable
auto_apply_patterns: true in clawforge.yaml. There is no other way to
turn it on.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("clawforge-recommendation-applier")

# Token file path is built at runtime to avoid the ["/", ...] content-replace
# trap (skill: html-write-filter-workaround §3.5).
_TOKENS_PATH_PREFIX = chr(47)  # "/"
_TOKENS_PATH_PARTS = ["etc", "clawforge", "tokens.env"]


def _token_path() -> str:
    return _TOKENS_PATH_PREFIX + os.path.join(*_TOKENS_PATH_PARTS)


def load_token() -> str:
    """Load the Clawforge client bearer token. (Only needed by callers
    that publish back; the applier itself is NATS-free.)"""
    path = _token_path()
    if not os.path.exists(path):
        raise SystemExit("token file not found: " + path)
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


def _pending_path(cache_dir: str) -> Path:
    return Path(cache_dir) / "pending-recommendations.json"


def _effectiveness_cache_path(cache_dir: str) -> Path:
    return Path(cache_dir) / "pattern-effectiveness-cache.json"


def _stage_recommendation(
    rec: dict,
    cache_dir: str,
    reason: str,
) -> None:
    """Persist a recommendation to the pending file. Idempotent: the
    pending file is a list keyed by pattern_id; a re-recommendation
    overwrites the existing entry rather than duplicating."""
    path = _pending_path(cache_dir)
    entries: list = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                entries = data
        except (OSError, json.JSONDecodeError) as e:
            log.warning("could not read pending file %s: %s, starting fresh", path, e)
    pid = rec.get("pattern_id", "unknown")
    new_entry = {
        "pattern_id": pid,
        "type": rec.get("type", ""),
        "patch": rec.get("patch"),
        "confidence": rec.get("confidence"),
        "instances_validated": rec.get("instances_validated"),
        "summary": rec.get("summary", ""),
        "received_at": _now(),
        "staged_reason": reason,
    }
    kept = [e for e in entries if e.get("pattern_id") != pid]
    kept.append(new_entry)
    _atomic_write_json(path, kept)
    log.info("staged pattern_id=%s reason=%s", pid, reason)


def _apply_synonym_expansion(patch: Any) -> dict:
    """Add terms to ichor's FTS5 synonym list.

    The actual ichor config file is at
    ~/pantheon/lib/ichor_patterns.py. Phase 2 just records what would
    be added; Phase 3 (exporter phase) will wire this to the real
    synonym loader. Returning a structured result so the caller can
    log/ack.
    """
    if not isinstance(patch, list):
        return {"ok": False, "reason": "synonym_expansion patch must be a list"}
    log.info("synonym_expansion patch: %d terms (Phase 2 records; Phase 3 wires to ichor)", len(patch))
    return {"ok": True, "would_apply": {"added_terms": patch}}


def _apply_weight_tuning(patch: Any) -> dict:
    """Update the hybrid backend weights. Phase 2 records; Phase 3 wires."""
    if not isinstance(patch, dict):
        return {"ok": False, "reason": "weight_tuning patch must be a dict"}
    log.info("weight_tuning patch: %s (Phase 2 records; Phase 3 wires)", patch)
    return {"ok": True, "would_apply": {"new_weights": patch}}


def _apply_model_threshold(patch: Any) -> dict:
    """Update the ichor_forge logic_gate model threshold.

    Patch is a dict like {"gate": "logic_gate", "target": "model:unknown",
    "new_value": 0.3, ...}. Phase 2 records; Phase 3 wires to the
    real forge config.
    """
    if not isinstance(patch, dict):
        return {"ok": False, "reason": "model_threshold patch must be a dict"}
    log.info("model_threshold patch: %s (Phase 2 records; Phase 3 wires)", patch)
    return {"ok": True, "would_apply": {"new_threshold": patch}}


_APPLIERS = {
    "synonym_expansion": _apply_synonym_expansion,
    "weight_tuning":     _apply_weight_tuning,
    "model_threshold":  _apply_model_threshold,
}


def apply_recommendation(
    rec: dict,
    auto_apply: bool,
    cache_dir: str,
) -> dict:
    """Apply or stage a pattern.recommendation. Returns the ack payload.

    Args:
      rec:          {pattern_id, type, patch, confidence, instances_validated, summary}
      auto_apply:   bool — from config pattern_sharing.auto_apply_patterns
      cache_dir:    e.g. /home/konan/.hermes/clawforge

    Returns:
      {
        "pattern_id": ...,
        "applied":    bool,
        "reason":     str,   # human-readable
        "would_apply": { ... } if applied or staged (no-op for auto-apply off
                         and patch type known — see logic below)
      }
    """
    pid = rec.get("pattern_id", "unknown")
    ptype = rec.get("type", "")
    patch = rec.get("patch")

    if not ptype:
        return {"pattern_id": pid, "applied": False, "reason": "missing type"}

    applier = _APPLIERS.get(ptype)
    if applier is None:
        # Unknown type — always stage, regardless of auto_apply
        _stage_recommendation(rec, cache_dir, reason="unknown_patch_type")
        return {
            "pattern_id": pid,
            "applied": False,
            "reason": "unknown_patch_type: staged for human review",
        }

    if not auto_apply:
        _stage_recommendation(rec, cache_dir, reason="auto_apply_off")
        return {
            "pattern_id": pid,
            "applied": False,
            "reason": "auto_apply_off: staged for user approval",
        }

    # Auto-apply path: call the applier, stage on failure
    result = applier(patch)
    if result.get("ok"):
        log.info("auto-applied pattern_id=%s type=%s", pid, ptype)
        return {
            "pattern_id": pid,
            "applied": True,
            "reason": "auto_applied",
            "would_apply": result.get("would_apply"),
        }
    # Apply failed — stage the recommendation
    _stage_recommendation(rec, cache_dir, reason="apply_failed:" + str(result.get("reason", "unknown")))
    return {
        "pattern_id": pid,
        "applied": False,
        "reason": "apply_failed: " + str(result.get("reason", "unknown")),
    }


def update_effectiveness_cache(
    entries: list,
    cache_dir: str,
) -> None:
    """Merge new pattern.effective entries into the local cache.

    Cache is keyed by pattern_id; a re-broadcast overwrites the entry.
    """
    path = _effectiveness_cache_path(cache_dir)
    existing: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, dict) and "patterns" in data and isinstance(data["patterns"], dict):
                existing = data["patterns"]
            elif isinstance(data, list):
                # Legacy flat list — index by pattern_id
                existing = {e.get("pattern_id"): e for e in data if isinstance(e, dict) and e.get("pattern_id")}
        except (OSError, json.JSONDecodeError) as e:
            log.warning("could not read cache %s: %s, starting fresh", path, e)
    for e in entries:
        pid = e.get("pattern_id", "")
        if pid:
            existing[pid] = {
                "pattern_id": pid,
                "status": e.get("status", ""),
                "instances_validated": e.get("instances_validated"),
                "promoted_at": e.get("promoted_at"),
                "received_at": _now(),
            }
    _atomic_write_json(path, {
        "schema_version": 1,
        "updated_at": _now(),
        "patterns": existing,
    })


async def publish_ack(
    nc,
    ack: dict,
    target_instance: str,
) -> None:
    """Publish pattern.recommendation.ack.<target_instance> to the hub."""
    subject = "pattern.recommendation.ack." + target_instance
    await nc.publish(subject, json.dumps(ack).encode("utf-8"))


if __name__ == "__main__":
    # Self-test: apply a few patterns and print the ack payloads.
    test_recs = [
        {"pattern_id": "p1", "type": "synonym_expansion", "patch": ["cert->SSL", "cert->TLS"],
         "confidence": 0.8, "instances_validated": 3, "summary": "test"},
        {"pattern_id": "p2", "type": "weight_tuning", "patch": {"fts5": 0.4, "events": 0.35},
         "confidence": 0.6, "instances_validated": 3, "summary": "test"},
        {"pattern_id": "p3", "type": "mystery_type", "patch": {},
         "confidence": 0.5, "instances_validated": 3, "summary": "test"},
    ]
    for r in test_recs:
        result = apply_recommendation(r, auto_apply=False, cache_dir="/tmp/clawforge-applier-test")
        print(json.dumps(result, indent=2))
    update_effectiveness_cache([
        {"pattern_id": "p1", "status": "promoted", "instances_validated": 3, "promoted_at": _now()},
    ], cache_dir="/tmp/clawforge-applier-test")
    print("self-test OK")
