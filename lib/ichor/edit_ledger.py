"""Append-only edit ledger for automated changes to Pantheon harness artifacts.

Why this exists
---------------
Nothing in Pantheon recorded *who changed which harness artifact, why, on what
evidence, and how to undo it*. The one live applier — the Ichor Forge appender
that writes a marked block into god `SOUL.md` files — has no backup, no undo, and
skips on a single marker string, so a re-application is a silent no-op and an
unwanted change is unrecoverable. Any applier built before this ledger exists is
an irreversible one.

The governing rule this ledger enforces
---------------------------------------
**The loop may optimize content it is allowed to vary; it may never vary the
constraint set that defines allowed variation.** So the ledger makes every edit
answerable, and makes a revert a first-class recorded event rather than an
out-of-band human rescue.

Hard requirements
-----------------
- **`inputs_read` is mandatory and non-empty.** It is the only way to answer
  "which poisoned memory caused this edit?" An edit whose inputs are unknown
  cannot be invalidated when those inputs are discovered to be corrupt.
- **`expected_improvement` is mandatory.** Every applied edit states the causal
  mechanism, the metric it should move, a signed predicted delta, the blast
  radius, and how it is undone. An edit that cannot say how it improves the
  system is rejected at intake.
- **Append-only.** Records are never rewritten. A revert is a new event carrying
  the same `edit_id`; current state is derived by folding the stream.
- **Freezing is automatic.** Repeated reverts of the same artifact class freeze
  that class to human-only, so a class that keeps failing stops being edited
  autonomously.

Storage
-------
`~/.hermes/pantheon/edit-ledger.jsonl` — plain JSONL so it can be diffed,
grepped and read by anything, and deliberately outside the skill tree so it is a
file of record rather than agent-authored content.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Resolve through the account home, not `$HOME`: a god's gateway session runs
# with HOME set to its profile sandbox, so `Path.home()` silently points at a
# DIFFERENT DB — a shadow `ichor.db` was written in production this way.
from lib.pantheon_path import account_home as _account_home  # noqa: E402

log = logging.getLogger("ichor.edit_ledger")

_HOME = _account_home()
LEDGER_PATH = Path(
    os.environ.get("ICHOR_EDIT_LEDGER", str(_HOME / ".hermes" / "pantheon" / "edit-ledger.jsonl"))
)
#: Sidecar holding derived freeze state so a freeze survives restarts without
#: re-folding the whole ledger on every check.
FREEZE_PATH = Path(
    os.environ.get("ICHOR_FREEZE_STATE", str(_HOME / ".hermes" / "pantheon" / "edit-ledger-freezes.json"))
)

#: How a change was triggered. `human` is the only one that may carry a null
#: approver without escalating.
TRIGGERS = ("cron", "handoff", "reflection", "human", "tripwire")

#: Artifact classes the loop may edit. T1/T2/T3 from the plan map onto these;
#: the tier gates autonomy, not whether the ledger records it. T3 classes must
#: never appear in an autonomous edit — `_T3_CLASSES` is enforced below.
ARTIFACT_CLASSES = (
    "skill",
    "soul_append",
    "tool_schema",
    "cron_prompt",
    "weights",
    "synonym_list",
    "threshold",
)

#: Never autonomously editable. A self-edit touching these is privilege
#: escalation via self-definition, so the ledger refuses to record one that
#: claims to be autonomous rather than quietly allowing it.
_T3_CLASSES = ("soul_identity", "permission_scope", "gate_config", "guardrail",
               "mcp_server_def", "routing", "ledger", "version_store")

#: Reverts of one class that trigger a freeze to human-only.
FREEZE_AFTER_REVERTS = int(os.environ.get("ICHOR_FREEZE_AFTER_REVERTS", "2"))

#: Fields every `recorded` event must carry, with a non-empty value.
_REQUIRED = (
    "edit_id", "ts", "author_god", "trigger", "target_artifact_class",
    "target_path", "inputs_read", "rationale", "expected_improvement",
    "parent_version",
)

_EXPECTED_IMPROVEMENT_KEYS = (
    "mechanism", "metric", "predicted_delta", "blast_radius", "reversibility",
)


class EditRejected(ValueError):
    """Raised when an edit record fails the admission rule."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _edit_id(artifact_path: str, diff: str, ts: str) -> str:
    """Content-addressed on the artifact + diff + timestamp (one per application)."""
    digest = hashlib.sha256(f"{artifact_path}|{diff}|{ts}".encode("utf-8")).hexdigest()
    return "ed_" + digest[:16]


def validate(record: Dict[str, Any]) -> List[str]:
    """Return the reasons `record` is unacceptable. Empty list means valid."""
    problems: List[str] = []

    for field in _REQUIRED:
        val = record.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            problems.append(f"{field} is required")
        elif isinstance(val, (list, dict)) and len(val) == 0:
            problems.append(f"{field} is required and must be non-empty")

    if problems:
        return problems

    trig = record.get("trigger")
    if trig not in TRIGGERS:
        problems.append(f"trigger must be one of {TRIGGERS}, got {trig!r}")

    cls = record.get("target_artifact_class")
    if cls in _T3_CLASSES:
        problems.append(
            f"target_artifact_class {cls!r} is T3 — never autonomously editable; "
            "the ledger will not record an edit to it"
        )
    elif cls not in ARTIFACT_CLASSES:
        problems.append(
            f"target_artifact_class must be one of {ARTIFACT_CLASSES} (or a T3 class, "
            f"which is refused), got {cls!r}"
        )

    # inputs_read is the anti-poisoning control. A single opaque entry such as
    # "unknown" defeats it, so require more than a placeholder.
    inputs = record.get("inputs_read") or []
    if not isinstance(inputs, list) or not all(isinstance(i, str) for i in inputs):
        problems.append("inputs_read must be a list of strings")
    else:
        junk = [i for i in inputs if len(i.strip()) < 4]
        if junk:
            problems.append(f"inputs_read entries must be meaningful; got {junk!r}")

    ei = record.get("expected_improvement") or {}
    if not isinstance(ei, dict):
        problems.append("expected_improvement must be an object")
    else:
        for key in _EXPECTED_IMPROVEMENT_KEYS:
            val = ei.get(key)
            if val is None or (isinstance(val, str) and not val.strip()):
                problems.append(f"expected_improvement.{key} is required")
        # A restatement of the diff is not a causal claim.
        mech = str(ei.get("mechanism") or "")
        if mech and len(mech.split()) < 6:
            problems.append(
                "expected_improvement.mechanism must state the causal claim, "
                "not restate the change (<6 words)"
            )

    # An autonomous edit with no approver is allowed only for T1 classes.
    approver = record.get("human_approver")
    if (approver in (None, "", "null")) and cls in ("skill", "soul_append", "cron_prompt", "tool_schema"):
        problems.append(
            f"target_artifact_class {cls!r} is T2 — a null human_approver is not "
            "allowed; T2 requires human approval"
        )

    return problems


def build_record(
    author_god: str,
    trigger: str,
    target_artifact_class: str,
    target_path: str,
    inputs_read: List[str],
    rationale: str,
    expected_improvement: Dict[str, str],
    parent_version: str,
    diff: str = "",
    human_approver: Optional[str] = None,
    eval_baseline_ref: str = "",
    edit_id: str = "",
    ts: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build and VALIDATE a record without appending it. Raises EditRejected.

    Exists so a caller can establish admission *before* it performs any side
    effect. The harness store snapshots the pre-edit revision to git, and doing
    that before admission means a rejected edit still leaves a commit behind —
    which contradicts "nothing is written until the record is acceptable".
    """
    ts = ts or _now()
    record = {
        "event": "recorded",
        "edit_id": edit_id or _edit_id(target_path, diff, ts),
        "ts": ts,
        "author_god": author_god,
        "trigger": trigger,
        "target_artifact_class": target_artifact_class,
        "target_path": target_path,
        "diff": diff,
        "inputs_read": list(inputs_read or []),
        "rationale": rationale.strip(),
        "expected_improvement": dict(expected_improvement or {}),
        "parent_version": parent_version,
        "human_approver": human_approver,
        "eval_baseline_ref": eval_baseline_ref,
        "reverted": False,
    }
    # `extra` carries facts the caller learned while applying — e.g. that the
    # target was a symlink and what else it affected. It may not shadow a core
    # field, because a caller must not be able to rewrite its own rationale,
    # provenance, or approval after the fact.
    if extra:
        collisions = sorted(set(extra) & set(record))
        if collisions:
            raise EditRejected("extra cannot overwrite core fields: " + ", ".join(collisions))
        record.update(extra)

    problems = validate(record)
    if problems:
        raise EditRejected("edit rejected: " + "; ".join(problems))
    return record


def append_record(record: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    """Append an already-validated record."""
    return _append(record, path)


def record_edit(
    author_god: str,
    trigger: str,
    target_artifact_class: str,
    target_path: str,
    inputs_read: List[str],
    rationale: str,
    expected_improvement: Dict[str, str],
    parent_version: str,
    diff: str = "",
    human_approver: Optional[str] = None,
    eval_baseline_ref: str = "",
    edit_id: str = "",
    path: Optional[Path] = None,
    ts: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate and append one applied-edit record. Raises EditRejected."""
    record = build_record(
        author_god=author_god, trigger=trigger,
        target_artifact_class=target_artifact_class, target_path=target_path,
        inputs_read=inputs_read, rationale=rationale,
        expected_improvement=expected_improvement, parent_version=parent_version,
        diff=diff, human_approver=human_approver,
        eval_baseline_ref=eval_baseline_ref, edit_id=edit_id, ts=ts,
    )
    return _append(record, path)


def record_revert(
    edit_id: str,
    reason: str,
    restored_version: str = "",
    automatic: bool = False,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append a revert event. Reverts are first-class, never deletions."""
    if not str(reason).strip():
        raise EditRejected("a revert must state a reason")
    entry = {
        "event": "reverted",
        "ts": _now(),
        "edit_id": edit_id,
        "reason": reason.strip(),
        "restored_version": restored_version,
        "automatic": bool(automatic),
    }
    return _append(entry, path)


def record_noop(
    target_path: str,
    target_artifact_class: str,
    author_god: str,
    reason: str,
    detail: str = "",
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append a no-op event: an application that was correctly skipped.

    The Ichor Forge appender skips re-application when its marker is present and
    says nothing, so a silent no-op is indistinguishable from a silent failure.
    Recording it makes "nothing happened, and that was correct" visible — which
    is the difference between an idempotent applier and a dead one.
    """
    if not str(reason).strip():
        raise EditRejected("a no-op event must state why it was a no-op")
    entry = {
        "event": "noop",
        "ts": _now(),
        "author_god": author_god,
        "target_path": target_path,
        "target_artifact_class": target_artifact_class,
        "reason": reason.strip(),
        "detail": detail,
    }
    return _append(entry, path)


def noops(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every recorded no-op, newest last."""
    return [e for e in load_events(path) if e.get("event") == "noop"]


def _append(entry: Dict[str, Any], path: Optional[Path]) -> Dict[str, Any]:
    p = Path(path) if path is not None else LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def load_events(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    p = Path(path) if path is not None else LEDGER_PATH
    if not p.exists():
        return []
    out: List[Dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_edits(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Fold the stream into current per-edit state.

    An edit is *live* until a revert event names it. `reverted` is derived, never
    written in place — the original record keeps saying what it did.
    """
    edits: Dict[str, Dict[str, Any]] = {}
    for ev in load_events(path):
        eid = ev.get("edit_id")
        if not eid:
            continue
        if ev.get("event") == "recorded":
            edits.setdefault(eid, dict(ev))
        elif ev.get("event") == "reverted" and eid in edits:
            edits[eid]["reverted"] = True
            edits[eid]["revert_reason"] = ev.get("reason")
            edits[eid]["reverted_ts"] = ev.get("ts")
            edits[eid]["reverted_automatic"] = ev.get("automatic", False)
    return sorted(edits.values(), key=lambda r: r.get("ts", ""))


def live_edits(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return [e for e in load_edits(path) if not e.get("reverted")]


def revert_counts_by_class(path: Optional[Path] = None) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for e in load_edits(path):
        if e.get("reverted"):
            cls = e.get("target_artifact_class", "unknown")
            counts[cls] = counts.get(cls, 0) + 1
    return counts


def frozen_classes(path: Optional[Path] = None) -> Dict[str, str]:
    """Artifact classes frozen to human-only, with the reason."""
    frozen = {
        cls: (f"{n} reverts (threshold {FREEZE_AFTER_REVERTS})")
        for cls, n in revert_counts_by_class(path).items()
        if n >= FREEZE_AFTER_REVERTS
    }
    try:
        extra = json.loads(FREEZE_PATH.read_text())
        if isinstance(extra, dict):
            frozen.update(extra)
    except (OSError, json.JSONDecodeError):
        pass
    return frozen


def is_frozen(artifact_class: str, path: Optional[Path] = None) -> bool:
    return artifact_class in frozen_classes(path)


def edits_reading_artifact(artifact_path: str, path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Every edit whose `inputs_read` touches `artifact_path`.

    This is the invalidation primitive: when an artifact is found to be corrupt,
    every edit that read it becomes suspect and can be reverted as a group.
    """
    hits = []
    for e in load_edits(path):
        for src in e.get("inputs_read") or []:
            if artifact_path in str(src):
                hits.append(e)
                break
    return hits
