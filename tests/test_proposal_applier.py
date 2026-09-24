"""Phase 3's applier must refuse automation, refuse self-edits, and prove its writes.

Every test pins a refusal, because the applier is the last place these failures can
be caught before they reach a live file:

  * T2/T3 must be refused, not "left as a config option" — a config option is a thing
    that gets flipped; a refusal is a thing that has to be argued away first.
  * A T1 apply with no recorded human approval must be refused, or T1 is T3 with
    extra steps.
  * A proposal must not be able to target its own guardrails.
  * A reported write is not a landed write: the applier reads the bytes back.

FALSIFICATION
-------------
`test_apply_refuses_without_approval` fails if the `state != "approved"` check is
removed — the proposal then applies with no human in the loop, which is precisely the
line the tier system exists to hold.
`test_apply_verifies_by_reading_back` fails if the read-back comparison is removed,
because `apply_edit`'s returned dict is then taken as evidence.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from lib.ichor import proposal_applier as pa  # noqa: E402

GOOD_IMPROVEMENT = {
    "mechanism": "the constant resolves through $HOME, so a god session reads a different tree",
    "metric": "shadow DB present: yes -> no",
    "predicted_delta": "eliminates a class-4 stale source",
    "blast_radius": "one module constant",
    "reversibility": "single commit revert",
}


@pytest.fixture()
def live_file(tmp_path):
    p = tmp_path / "target.py"
    p.write_text("VALUE = 1\n")
    return p


@pytest.fixture()
def log(tmp_path):
    return tmp_path / "proposals.jsonl"


def _propose(live_file, log, **over):
    kw = dict(
        live_path=live_file, new_bytes=b"VALUE = 2\n", artifact_class="threshold",
        rationale="fix the path resolution", expected_improvement=GOOD_IMPROVEMENT,
        inputs_read=["lib/pantheon_path.py"], author="hermes", trigger="human", path=log,
    )
    kw.update(over)
    return pa.propose(**kw)


# ── the tier gate ───────────────────────────────────────────────────────

@pytest.mark.parametrize("tier", ["T2", "T3"])
def test_auto_apply_tiers_are_refused_at_proposal(live_file, log, tier):
    with pytest.raises(pa.TierRefused, match="trust separation"):
        _propose(live_file, log, tier=tier)


def test_an_unknown_tier_is_refused(live_file, log):
    with pytest.raises(pa.TierRefused):
        _propose(live_file, log, tier="T9")


def test_trust_separation_reports_auto_apply_as_unavailable():
    s = pa.trust_separation_status()
    assert s["auto_apply_permitted"] is False
    assert s["label_vault_read_only_to_proposer"] is True
    assert not s["ledger_not_writable_by_proposer"]


# ── the approval gate ───────────────────────────────────────────────────

def test_apply_refuses_without_approval(live_file, log):
    """A T1 apply with no human approval is T3 with extra steps."""
    prop = _propose(live_file, log)
    with pytest.raises(pa.ProposalError, match="explicit human approval"):
        pa.apply_proposal(prop.proposal_id, path=log)
    assert live_file.read_text() == "VALUE = 1\n", "the file must be untouched"


def test_an_agent_cannot_approve(live_file, log):
    prop = _propose(live_file, log)
    for fake in ("auto", "agent", "system", "self"):
        with pytest.raises(pa.ProposalError, match="not a human identity"):
            pa.approve(prop.proposal_id, approver=fake, path=log)


# ── self-protection ─────────────────────────────────────────────────────

@pytest.mark.parametrize("cls", sorted(pa.SELF_PROTECTED_CLASSES))
def test_a_proposal_cannot_target_its_own_guardrails(live_file, log, cls):
    with pytest.raises(pa.ProposalError, match="never autonomously editable"):
        _propose(live_file, log, artifact_class=cls)


# ── intake rules ────────────────────────────────────────────────────────

def test_expected_improvement_is_mandatory(live_file, log):
    for key in pa.Proposal.REQUIRED_IMPROVEMENT_KEYS:
        partial = {k: v for k, v in GOOD_IMPROVEMENT.items() if k != key}
        with pytest.raises(pa.ProposalError, match="expected_improvement is missing"):
            _propose(live_file, log, expected_improvement=partial)


def test_inputs_read_is_mandatory(live_file, log):
    with pytest.raises(pa.ProposalError, match="inputs_read is mandatory"):
        _propose(live_file, log, inputs_read=[])


def test_a_missing_artifact_is_refused(live_file, log, tmp_path):
    with pytest.raises(pa.ProposalError, match="artifact not found"):
        _propose(live_file, log, live_path=tmp_path / "nope.py")


# ── the happy path, with proof ──────────────────────────────────────────

def test_approved_proposal_applies_and_verifies(live_file, log):
    prop = _propose(live_file, log)
    pa.approve(prop.proposal_id, approver="konan", path=log)
    done = pa.apply_proposal(prop.proposal_id, path=log)

    assert done.state == "applied"
    assert done.verification["landed"] is True
    assert done.verification["expected_sha256"] == done.verification["actual_sha256"]
    assert live_file.read_text() == "VALUE = 2\n", "the write must actually land"


def test_apply_verifies_by_reading_back(live_file, log):
    """A returned dict is not evidence — the applier must compare bytes."""
    prop = _propose(live_file, log)
    pa.approve(prop.proposal_id, approver="konan", path=log)
    done = pa.apply_proposal(prop.proposal_id, path=log)
    assert done.verification["method"] == "read-back byte comparison after write"
    assert "actual_sha256" in done.verification


def test_the_approved_payload_cannot_be_swapped(live_file, log):
    """What is applied must be what was approved, verified by hash."""
    prop = _propose(live_file, log)
    pa.approve(prop.proposal_id, approver="konan", path=log)
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    recs[-1]["new_content_b64"] = __import__("base64").b64encode(b"VALUE = 999\n").decode()
    log.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    with pytest.raises(pa.ProposalError, match="does not match the stored bytes"):
        pa.apply_proposal(prop.proposal_id, path=log)


# ── revert: the leg that was BROKEN and only end-to-end execution caught ──
# `harness_store.revert` is `(edit_id, reason, automatic, live_path)` — the first
# positional argument is the EDIT ID, not a path. The applier passed the path, and
# read the id from a `commit` key that does not exist (`apply_result` uses `edit_id`).
# Both faults were silent: the revert simply did not happen.

@pytest.fixture()
def store(tmp_path):
    from lib.ichor import harness_store
    return harness_store.HarnessStore(repo_dir=tmp_path / "store", live_root=tmp_path,
                                      ledger_path=tmp_path / "ledger.jsonl")


def test_revert_restores_the_pre_state(live_file, log, store):
    before = live_file.read_bytes()
    prop = _propose(live_file, log)
    pa.approve(prop.proposal_id, approver="konan", path=log)
    applied = pa.apply_proposal(prop.proposal_id, store=store, path=log)
    assert live_file.read_text() == "VALUE = 2\n"

    rev = pa.revert_proposal(prop.proposal_id, reason="test", store=store, path=log)
    assert rev.state == "reverted"
    assert rev.verification["revert_landed"] is True, "the revert did not actually land"
    assert live_file.read_bytes() == before, "the file was not restored byte-for-byte"
    assert rev.verification["revert_actual_sha256"] == applied.apply_result["before_sha256"]


def test_revert_refuses_when_no_edit_id_was_recorded(live_file, log):
    """A write whose version cannot be named cannot be reverted."""
    prop = _propose(live_file, log)
    pa.approve(prop.proposal_id, approver="konan", path=log)
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    recs[-1]["state"] = "applied"
    recs[-1]["apply_result"] = {}
    log.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    with pytest.raises(pa.ProposalError, match="no edit_id recorded"):
        pa.revert_proposal(prop.proposal_id, store=None, path=log)


def test_revert_refuses_a_proposal_that_was_never_applied(live_file, log):
    prop = _propose(live_file, log)
    with pytest.raises(pa.ProposalError, match="not 'applied'"):
        pa.revert_proposal(prop.proposal_id, path=log)


def test_pending_lists_only_undecided_proposals(live_file, log):
    a = _propose(live_file, log)
    b = _propose(live_file, log, rationale="second")
    pa.approve(b.proposal_id, approver="konan", path=log)
    ids = {p["proposal_id"] for p in pa.pending(log)}
    assert a.proposal_id in ids
    assert b.proposal_id not in ids
