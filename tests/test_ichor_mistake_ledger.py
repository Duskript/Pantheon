"""Tests for the Ichor mistake ledger.

The ledger's whole value is that a record is *attributable* — an
un-attributed "something went wrong" note cannot be acted on and would
corrupt the recurrence counts that decide when a prevention is warranted.
These tests pin that admission rule.
"""
from __future__ import annotations

import importlib
import json

import pytest

from lib.ichor import mistakes as M


@pytest.fixture()
def ledger(tmp_path):
    return tmp_path / "mistake-ledger.jsonl"


# ── admission discipline ───────────────────────────────────────────────────

def test_rejects_a_mistake_with_no_offending_instance():
    problems = M.validate({"god": "hermes", "claim": "x", "category": "wrong_fact",
                           "detected_by": "self"})
    assert any("claim is too short" in p for p in problems)


def test_rejects_unknown_category():
    problems = M.validate({"god": "hermes", "claim": "a real actionable claim",
                           "category": "oops", "detected_by": "self"})
    assert any("category must be one of" in p for p in problems)


def test_rejects_unknown_detector():
    problems = M.validate({"god": "hermes", "claim": "a real actionable claim",
                           "category": "wrong_fact", "detected_by": "vibes"})
    assert any("detected_by must be one of" in p for p in problems)


def test_human_detected_mistake_requires_the_revealing_quote():
    """A human-caught mistake must point at the turn that caught it."""
    problems = M.validate({"god": "hermes", "claim": "a real actionable claim",
                           "category": "wrong_fact", "detected_by": "human"})
    assert any("requires 'quote'" in p for p in problems)


def test_record_mistake_raises_on_invalid_and_writes_nothing(ledger):
    with pytest.raises(ValueError):
        M.record_mistake(god="", claim="short", category="nope",
                         detected_by="nope", path=ledger)
    assert not ledger.exists(), "a rejected record must not touch the ledger"


def test_valid_record_is_accepted(ledger):
    rec = M.record_mistake(
        god="hermes", claim="reported extract healthy while it had failed 456 times",
        category="false_success", detected_by="human", quote="that is wrong",
        correction="check the journal", path=ledger,
    )
    assert rec["mistake_id"].startswith("mis_")
    assert rec["state"] == "open"
    assert ledger.exists()


# ── append-only + state folding ────────────────────────────────────────────

def test_state_transitions_are_appended_not_rewritten(ledger):
    rec = M.record_mistake(god="hermes", claim="shipped a fix in the wrong layer",
                           category="broken_code", detected_by="tool", path=ledger)
    M.resolve_mistake(rec["mistake_id"], "learned",
                      prevention="resolve credentials at the call site, not the caller",
                      path=ledger)

    lines = [json.loads(l) for l in ledger.read_text().splitlines() if l.strip()]
    assert [l["event"] for l in lines] == ["recorded", "resolved"], "must append, not rewrite"

    folded = M.load_mistakes(ledger)
    assert len(folded) == 1
    assert folded[0]["state"] == "learned"
    assert "call site" in folded[0]["prevention"]


def test_learned_requires_a_named_prevention(ledger):
    """Claiming a lesson without naming the prevention is the failure mode this catches."""
    rec = M.record_mistake(god="hermes", claim="something actionable happened here",
                           category="bad_plan", detected_by="self", path=ledger)
    with pytest.raises(ValueError):
        M.resolve_mistake(rec["mistake_id"], "learned", path=ledger)


def test_open_mistakes_excludes_resolved_ones(ledger):
    a = M.record_mistake(god="hermes", claim="first actionable mistake", category="wrong_fact",
                         detected_by="self", path=ledger)
    M.record_mistake(god="thoth", claim="second actionable mistake", category="bad_plan",
                     detected_by="self", path=ledger)
    M.resolve_mistake(a["mistake_id"], "verified", prevention="p", path=ledger)
    assert [m["god"] for m in M.open_mistakes(ledger)] == ["thoth"]


# ── the signal that decides when a prevention is warranted ─────────────────

def test_recurrence_counts_by_category(ledger):
    for _ in range(3):
        M.record_mistake(god="hermes", claim="repeated error type number one",
                         category="false_success", detected_by="tool", path=ledger)
    M.record_mistake(god="hermes", claim="a one off different mistake here",
                     category="hallucination", detected_by="self", path=ledger)
    rec = M.recurrence(ledger)
    assert rec["false_success"] == 3
    assert rec["hallucination"] == 1
    assert list(rec)[0] == "false_success", "most frequent category must sort first"


def test_stats_shape(ledger):
    M.record_mistake(god="hermes", claim="an actionable mistake for stats",
                     category="wrong_fact", detected_by="human", quote="no",
                     path=ledger)
    s = M.stats(ledger)
    assert s["total"] == 1
    assert s["by_state"] == {"open": 1}
    assert s["by_god"] == {"hermes": 1}
    assert s["by_detector"] == {"human": 1}


def test_empty_ledger_is_not_an_error(tmp_path):
    missing = tmp_path / "nope.jsonl"
    assert M.load_mistakes(missing) == []
    assert M.stats(missing)["total"] == 0


# ── `peer` detector: cross-god catches must be countable ───────────────────

def _base(**over):
    kw = dict(god="thoth", claim="a claim that was wrong", category="wrong_fact",
              detected_by="peer", detected_by_god="hermes",
              quote="the turn that revealed it", path=None)
    kw.update(over)
    return kw


def test_peer_is_an_accepted_detector(tmp_path):
    p = tmp_path / "ledger.jsonl"
    rec = M.record_mistake(**_base(path=p))
    assert rec["detected_by"] == "peer"
    assert rec["detected_by_god"] == "hermes"


def test_peer_requires_a_quote(tmp_path):
    """Same evidence burden as a human catch: name the turn that revealed it."""
    with pytest.raises(ValueError) as e:
        M.record_mistake(**_base(path=tmp_path / "l.jsonl", quote=""))
    assert "requires 'quote'" in str(e.value)


def test_peer_requires_the_detecting_god(tmp_path):
    """Without the god, the cross-god attribution this value exists for is lost."""
    with pytest.raises(ValueError) as e:
        M.record_mistake(**_base(path=tmp_path / "l.jsonl", detected_by_god=""))
    assert "requires 'detected_by_god'" in str(e.value)


def test_human_still_requires_a_quote(tmp_path):
    with pytest.raises(ValueError) as e:
        M.record_mistake(**_base(path=tmp_path / "l.jsonl", detected_by="human",
                                        detected_by_god="", quote=""))
    assert "detected_by='human' requires 'quote'" in str(e.value)


def test_self_and_tool_need_no_quote(tmp_path):
    p = tmp_path / "l.jsonl"
    for d in ("self", "tool"):
        M.record_mistake(**_base(path=p, detected_by=d, detected_by_god="", quote=""))
    assert len([json.loads(l) for l in p.read_text().splitlines() if l.strip()]) == 2


def test_detector_enum_is_exactly_the_four(tmp_path):
    assert set(M.DETECTORS) == {"human", "self", "tool", "peer"}


# ── the ledger must not fork on a sandboxed $HOME ──────────────────────────

def _reload_with_home(monkeypatch, home):
    """Re-import mistakes with $HOME patched, as a gateway session would see it."""
    import importlib
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("ICHOR_MISTAKE_LEDGER", raising=False)
    return importlib.reload(M)


def test_a_sandboxed_home_does_not_fork_the_ledger(tmp_path, monkeypatch):
    """A god's gateway session runs with HOME set to its profile sandbox.

    HOW TO FALSIFY THIS — patch what `_account_home()` READS, not the module
    attribute. `_reload_with_home()` calls `importlib.reload(M)`, which
    re-executes the module source and **discards any patch applied to the
    module's own attributes**. So `M._account_home = lambda: ...` followed by a
    reload silently falsifies nothing and leaves a green suite, which reads as
    "this test is vacuous" when it is not. Thoth hit exactly that and nearly
    reported the test as weak.

    Patch `pwd.getpwuid` instead (see the fake in this file), or edit the source
    the way the original falsification did — a source edit survives the reload
    because the reload re-runs it. Verified: making `pw_dir` follow `$HOME`
    fails THIS test, with `sandboxed_home()` returning '' because both sides
    then agree on the spoofed home.

    The ledger forked in production because the path was Path.home()-derived:
    a god wrote to ~/.hermes/profiles/<god>/home/.hermes/pantheon/... while
    everyone else wrote to ~/.hermes/pantheon/... Recurrence is counted per
    file, so a recurrence split across two ledgers is invisible precisely
    because the halves were written from different environments.
    """
    sandbox = tmp_path / "profiles" / "thoth" / "home"
    sandbox.mkdir(parents=True)
    real = M._account_home()
    try:
        mod = _reload_with_home(monkeypatch, sandbox)
        assert mod.sandboxed_home() == str(sandbox)
        # the path must NOT follow HOME
        assert str(sandbox) not in str(mod.LEDGER_PATH)
        if real is not None and real.is_dir():
            assert mod.LEDGER_PATH == real / ".hermes" / "pantheon" / "mistake-ledger.jsonl"
    finally:
        importlib.reload(M)


def test_an_explicit_override_still_wins(tmp_path, monkeypatch):
    target = tmp_path / "custom.jsonl"
    monkeypatch.setenv("ICHOR_MISTAKE_LEDGER", str(target))
    try:
        mod = importlib.reload(M)
        assert mod.LEDGER_PATH == target
    finally:
        importlib.reload(M)


def test_sandboxed_home_is_empty_when_home_is_the_account_home(monkeypatch):
    real = M._account_home()
    if real is None:
        return
    monkeypatch.setenv("HOME", str(real))
    try:
        mod = importlib.reload(M)
        assert mod.sandboxed_home() == ""
    finally:
        importlib.reload(M)
