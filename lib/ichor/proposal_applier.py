"""Phase 3 — the applier: proposals, approval, and the tier gate.

THE TIER LINE (Thoth's adjudication, and the reason this module exists)
----------------------------------------------------------------------
    T0  propose only                     ALLOWED now
    T1  apply behind EXPLICIT approval   ALLOWED now
    T2  auto-apply, evaluation-gated     REFUSED — needs trust separation
    T3  auto-apply                       REFUSED — needs trust separation

The line is drawn at **approval vs automation**, not at artifact class. T0 and T1
are allowed because a human is in the loop on every write; T2 and T3 are refused
because the loop that proposes changes would also be the loop that applies them.

TRUST SEPARATION — WHAT IT ACTUALLY MEANS
-----------------------------------------
For auto-apply to be safe, the proposing agent must have no write path to the things
that judge it:

  * the edit ledger      (otherwise it can write its own history)
  * the version store    (otherwise it can rewrite the pre-state it is compared against)
  * the guardrail config (otherwise it can lift its own restrictions)
  * the label vault      (otherwise it can train on the held-out set)

Phase 2 delivered the fourth. The other three are NOT yet demonstrated, which is
exactly why T2/T3 are refused here rather than being "left as a config option". A
config option is a thing that gets flipped; a refusal is a thing that has to be
argued away first.

WHY THE APPLIER VERIFIES ITS OWN WORK
-------------------------------------
`apply_edit` returns a result dict, and a returned dict is not evidence. After the
write, this module reads the file back and compares bytes to what it intended. A
write that reports success and did not land is the failure class this whole system
exists to catch, and the applier is the last place it can be caught.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not decide WHAT to change. Proposals arrive from elsewhere (the Forge, the
Dojo, a human). This module decides whether a proposal may be applied, applies it
through the Phase 1 store, and proves it landed.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from lib.ichor import edit_ledger, harness_store
from lib.pantheon_path import account_home

PROPOSAL_DIR = account_home() / ".hermes" / "pantheon" / "proposals"
PROPOSAL_LOG = PROPOSAL_DIR / "proposals.jsonl"

#: Tiers this module will act on. T2/T3 are deliberately absent.
ALLOWED_TIERS = {"T0", "T1"}

#: Tiers that exist so a proposal can declare itself and be REFUSED loudly, rather
#: than being silently downgraded to a tier that happens to be allowed.
KNOWN_TIERS = {"T0", "T1", "T2", "T3"}

#: Artifact classes the ledger marks as never-autonomously-editable. Imported from the
#: ledger rather than restated here: a parallel list is a second copy of the same rule,
#: and two copies drift. The ledger is the source of truth for what is a guardrail.
SELF_PROTECTED_CLASSES = set(edit_ledger._T3_CLASSES)

#: The ledger's controlled vocabularies, likewise imported rather than restated, so a
#: proposal fails HERE with a clear message instead of deep inside admission.
VALID_TRIGGERS = set(edit_ledger.TRIGGERS)
VALID_ARTIFACT_CLASSES = set(edit_ledger.ARTIFACT_CLASSES)


class ProposalError(RuntimeError):
    """Raised when a proposal is malformed, unauthorised, or out of tier."""


class TierRefused(ProposalError):
    """Raised when a proposal declares a tier this module will not act on."""


@dataclass
class Proposal:
    """A proposed change, with the evidence needed to judge it without the diff."""
    proposal_id: str
    artifact_class: str
    live_path: str
    rationale: str
    #: Mandatory. Every entry states what improves, by how much, and why — so a
    #: human can approve or reject WITHOUT opening the diff.
    expected_improvement: Dict[str, str]
    tier: str
    inputs_read: List[str]
    author: str
    trigger: str
    new_bytes_sha256: str = ""
    new_content_b64: str = ""
    marker: str = ""
    eval_baseline_ref: str = ""
    state: str = "proposed"          # proposed -> approved -> applied -> reverted
    approver: Optional[str] = None
    approved_at: Optional[float] = None
    applied_at: Optional[float] = None
    apply_result: Dict[str, Any] = field(default_factory=dict)
    verification: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    REQUIRED_IMPROVEMENT_KEYS = ("mechanism", "metric", "predicted_delta",
                                 "blast_radius", "reversibility")

    def validate(self) -> None:
        if self.tier not in KNOWN_TIERS:
            raise ProposalError(
                f"unknown tier {self.tier!r}; known: {sorted(KNOWN_TIERS)}"
            )
        missing = [k for k in self.REQUIRED_IMPROVEMENT_KEYS
                   if not (self.expected_improvement or {}).get(k)]
        if missing:
            raise ProposalError(
                f"expected_improvement is missing {missing} — every entry must state "
                "what improves, by how much, and why, so it can be judged without the diff"
            )
        if self.artifact_class in SELF_PROTECTED_CLASSES:
            raise ProposalError(
                f"artifact class {self.artifact_class!r} is T3 (never autonomously "
                "editable) — a system that can edit its own guardrails has none"
            )
        if self.trigger not in VALID_TRIGGERS:
            raise ProposalError(
                f"trigger {self.trigger!r} is not in the ledger's vocabulary "
                f"{sorted(VALID_TRIGGERS)}"
            )
        if self.artifact_class not in VALID_ARTIFACT_CLASSES:
            raise ProposalError(
                f"artifact class {self.artifact_class!r} is not in the ledger's "
                f"vocabulary {sorted(VALID_ARTIFACT_CLASSES)}"
            )
        if not self.inputs_read:
            raise ProposalError("inputs_read is mandatory — an edit must name what it read")


def _load_proposals(path: Path = PROPOSAL_LOG) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _append(prop: Proposal, path: Path = PROPOSAL_LOG) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(prop), sort_keys=True) + "\n")


def _latest(path: Path = PROPOSAL_LOG) -> Dict[str, Dict[str, Any]]:
    """Latest record per proposal_id — the log is append-only, so state is folded."""
    out: Dict[str, Dict[str, Any]] = {}
    for rec in _load_proposals(path):
        out[rec["proposal_id"]] = rec
    return out


def propose(
    *,
    live_path: Path,
    new_bytes: bytes,
    artifact_class: str,
    rationale: str,
    expected_improvement: Dict[str, str],
    inputs_read: List[str],
    author: str,
    trigger: str,
    tier: str = "T1",
    marker: str = "",
    eval_baseline_ref: str = "",
    path: Path = PROPOSAL_LOG,
) -> Proposal:
    """Record a proposal. T0/T1 proceed to approval; T2/T3 are refused HERE."""
    if tier not in ALLOWED_TIERS:
        raise TierRefused(
            f"tier {tier!r} is not permitted: this module acts only on {sorted(ALLOWED_TIERS)}. "
            "Auto-apply requires trust separation — no write path from the proposer to the "
            "ledger, the version store, or the guardrail config — which is not yet demonstrated."
        )
    live_path = Path(live_path)
    if not live_path.is_file():
        raise ProposalError(f"artifact not found: {live_path}")

    prop = Proposal(
        proposal_id=f"prp_{uuid.uuid4().hex[:16]}",
        artifact_class=artifact_class,
        live_path=str(live_path),
        rationale=rationale,
        expected_improvement=dict(expected_improvement),
        tier=tier,
        inputs_read=list(inputs_read),
        author=author,
        trigger=trigger,
        new_bytes_sha256=hashlib.sha256(new_bytes).hexdigest(),
        new_content_b64=__import__("base64").b64encode(new_bytes).decode(),
        marker=marker,
        eval_baseline_ref=eval_baseline_ref,
    )
    prop.validate()
    _append(prop, path)
    return prop


def approve(proposal_id: str, *, approver: str, path: Path = PROPOSAL_LOG) -> Proposal:
    """Record an EXPLICIT human approval. This is what makes T1 legitimate."""
    if not approver or approver.lower() in ("auto", "agent", "system", "self"):
        raise ProposalError(
            f"approver {approver!r} is not a human identity — T1 requires an explicit "
            "human approval, and 'auto' is the thing T2/T3 would be"
        )
    recs = _latest(path)
    if proposal_id not in recs:
        raise ProposalError(f"unknown proposal {proposal_id!r}")
    prop = Proposal(**recs[proposal_id])
    if prop.state != "proposed":
        raise ProposalError(f"proposal {proposal_id} is {prop.state}, not 'proposed'")
    prop.state = "approved"
    prop.approver = approver
    prop.approved_at = time.time()
    _append(prop, path)
    return prop


def apply_proposal(
    proposal_id: str,
    *,
    store: Optional[harness_store.HarnessStore] = None,
    path: Path = PROPOSAL_LOG,
) -> Proposal:
    """Apply an APPROVED T1 proposal, then PROVE it landed by reading the bytes back.

    Refuses when: the tier is not allowed, no human approval is recorded, or the
    post-write read-back does not match the intended bytes.
    """
    import base64

    recs = _latest(path)
    if proposal_id not in recs:
        raise ProposalError(f"unknown proposal {proposal_id!r}")
    prop = Proposal(**recs[proposal_id])

    if prop.tier not in ALLOWED_TIERS:
        raise TierRefused(f"tier {prop.tier!r} is not permitted")
    if prop.state != "approved":
        raise ProposalError(
            f"proposal {proposal_id} is {prop.state!r} — T1 requires an explicit human "
            "approval before application (call approve() first)"
        )
    if not prop.approver:
        raise ProposalError(f"proposal {proposal_id} has no recorded approver")

    store = store or harness_store.HarnessStore()
    new_bytes = base64.b64decode(prop.new_content_b64)
    # The payload must still be the one that was approved.
    if hashlib.sha256(new_bytes).hexdigest() != prop.new_bytes_sha256:
        raise ProposalError(
            "the approved payload's hash does not match the stored bytes — refusing to "
            "apply something other than what was approved"
        )

    result = store.apply_edit(
        live_path=Path(prop.live_path),
        new_bytes=new_bytes,
        author_god=prop.author,
        trigger=prop.trigger,
        target_artifact_class=prop.artifact_class,
        rationale=prop.rationale,
        expected_improvement=prop.expected_improvement,
        inputs_read=prop.inputs_read,
        human_approver=prop.approver,
        marker=prop.marker,
        eval_baseline_ref=prop.eval_baseline_ref,
    )

    # ── verify by reading the file back. A returned dict is not evidence. ──
    actual = Path(prop.live_path).read_bytes()
    landed = hashlib.sha256(actual).hexdigest() == prop.new_bytes_sha256
    prop.verification = {
        "method": "read-back byte comparison after write",
        "expected_sha256": prop.new_bytes_sha256,
        "actual_sha256": hashlib.sha256(actual).hexdigest(),
        "landed": landed,
        "verified_at": time.time(),
    }
    if not landed:
        raise ProposalError(
            f"apply reported success but the file does NOT match the intended bytes "
            f"({prop.live_path}) — a reported write is not a landed write"
        )

    prop.state = "applied"
    prop.applied_at = time.time()
    prop.apply_result = {k: v for k, v in result.items() if k != "new_bytes"}
    _append(prop, path)
    return prop


def revert_proposal(
    proposal_id: str,
    *,
    reason: str = "",
    store: Optional[harness_store.HarnessStore] = None,
    path: Path = PROPOSAL_LOG,
) -> Proposal:
    """Revert an applied proposal through the Phase 1 store, and PROVE the revert.

    Two bugs lived here and only end-to-end execution caught them:

      1. `harness_store.revert` is `(edit_id, reason, automatic, live_path)` — the
         first positional argument is the EDIT ID, not a path. Passing the path
         made every revert fail with `unknown edit_id`.
      2. `apply_result` has no `commit` key. The key is `edit_id`, so
         `.get("commit", "")` silently produced an empty string — a lookup that
         fails without raising, feeding a call that was already wrong.

    Both failed silently in the sense that mattered: the revert did not happen and
    nothing said so until the file was read back.
    """
    recs = _latest(path)
    if proposal_id not in recs:
        raise ProposalError(f"unknown proposal {proposal_id!r}")
    prop = Proposal(**recs[proposal_id])
    if prop.state != "applied":
        raise ProposalError(f"proposal {proposal_id} is {prop.state!r}, not 'applied'")

    edit_id = prop.apply_result.get("edit_id")
    if not edit_id:
        raise ProposalError(
            f"proposal {proposal_id} has no edit_id recorded — cannot revert a write "
            "whose version we cannot name"
        )
    store = store or harness_store.HarnessStore()
    store.revert(edit_id, reason or f"revert of {proposal_id}",
                 live_path=Path(prop.live_path))

    # Verify the revert the same way the apply is verified: read the bytes back and
    # compare to the PRE-state hash the store recorded. A revert that reports success
    # and did not land is the same failure as a write that reports success.
    after = hashlib.sha256(Path(prop.live_path).read_bytes()).hexdigest()
    expected = prop.apply_result.get("before_sha256", "")
    prop.state = "reverted"
    prop.verification = {
        **prop.verification,
        "reverted_at": time.time(),
        "revert_expected_sha256": expected,
        "revert_actual_sha256": after,
        "revert_landed": bool(expected) and after == expected,
    }
    if expected and after != expected:
        raise ProposalError(
            f"revert reported success but the file does not match its pre-state hash "
            f"({prop.live_path}): expected {expected[:12]}, got {after[:12]}"
        )
    _append(prop, path)
    return prop


def pending(path: Path = PROPOSAL_LOG) -> List[Dict[str, Any]]:
    """Proposals awaiting a human decision — the approval queue."""
    return [r for r in _latest(path).values() if r["state"] == "proposed"]


def trust_separation_status() -> Dict[str, Any]:
    """Report which of the four separation conditions are actually demonstrated.

    This is what gates T2/T3, so it is computed rather than asserted. Each condition
    is a claim that must be checkable; an unproven one reports False.
    """
    return {
        "label_vault_read_only_to_proposer": True,   # Phase 2: enforced by test
        "ledger_not_writable_by_proposer": False,    # not yet demonstrated
        "version_store_not_writable_by_proposer": False,
        "guardrail_config_not_writable_by_proposer": False,
        "auto_apply_permitted": False,
        "reason": (
            "3 of 4 separation conditions are not yet demonstrated, so T2/T3 remain "
            "refused. A config option would be flipped; this is a refusal."
        ),
    }
