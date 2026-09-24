"""The approval surface must know WHO approved, and must fail closed.

An approval surface that cannot tell who approved is not an approval surface. The
two checks, both required:

  1. the actor must be in `DISCORD_ALLOWED_USERS` (the gateway's own allow-list)
  2. the actor must NOT be a bot

Without (2) the agent's own bot account reacts ✅ to its own proposal, and the result
is T3 wearing a human's badge. Without (1) any member can approve a harness change.

`fetch_messages` returns reaction COUNTS, and a count cannot say who reacted — which
is why the surface reads reactions over the REST API. A count is the shape of evidence
that looks like proof and isn't.

FALSIFICATION
-------------
`test_a_bot_cannot_approve` fails if the `user.get("bot")` check is removed.
`test_a_reaction_resolves_to_its_own_message` fails if the collector falls back to
guessing the target instead of using the recorded message-id -> proposal-id map —
guessing is what produced `proposal_id: None` and a silently refused approval.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

_spec = importlib.util.spec_from_file_location(
    "_proposal_surface", REPO / "scripts" / "proposal_surface.py")
ps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ps)

from lib.ichor import proposal_applier as pa  # noqa: E402

KONAN = "180817012619083776"
HERMES_BOT = "1499845064359280710"
STRANGER = "999999999999999999"
APPROVE = "\u2705"


@pytest.fixture()
def log(tmp_path):
    return tmp_path / "proposals.jsonl"


@pytest.fixture()
def proposal(log, tmp_path):
    t = tmp_path / "target.py"
    t.write_text("X = 1\n")
    return pa.propose(
        live_path=t, new_bytes=b"X = 2\n", artifact_class="threshold",
        rationale="test", inputs_read=["a.py"], author="hermes", trigger="human",
        expected_improvement={"mechanism": "the constant follows $HOME so a session "
                                           "reads a different tree",
                              "metric": "m", "predicted_delta": "d",
                              "blast_radius": "b", "reversibility": "r"},
        path=log)


def _stub(reactions, messages=()):
    def fake(method, path, token, body=None):
        if APPROVE in path or "%E2%9C%85" in path:
            return list(reactions)
        if "reactions" in path:
            return []
        if "messages?" in path:
            return list(messages)
        return {"id": "9001"}
    return fake


# ── identity ────────────────────────────────────────────────────────────

def test_a_bot_cannot_approve(monkeypatch):
    monkeypatch.setattr(ps, "_api", _stub([{"id": HERMES_BOT, "username": "hermes", "bot": True}]))
    d = ps.collect_decisions(message_id="1", token="x", humans={KONAN},
                             message_map={"1": "prp_x"})
    assert not [x for x in d if "rejected_actor" not in x], "a bot approval was accepted"
    assert any("bot account" in json.dumps(x) for x in d)


def test_a_stranger_cannot_approve(monkeypatch):
    monkeypatch.setattr(ps, "_api", _stub([{"id": STRANGER, "username": "x", "bot": False}]))
    d = ps.collect_decisions(message_id="1", token="x", humans={KONAN},
                             message_map={"1": "prp_x"})
    assert not [x for x in d if "rejected_actor" not in x]
    assert any("not in DISCORD_ALLOWED_USERS" in json.dumps(x) for x in d)


def test_an_allowed_human_is_accepted(monkeypatch):
    monkeypatch.setattr(ps, "_api", _stub([{"id": KONAN, "username": "the_cybermage", "bot": False}]))
    d = ps.collect_decisions(message_id="1", token="x", humans={KONAN},
                             message_map={"1": "prp_x"})
    ok = [x for x in d if "rejected_actor" not in x]
    assert len(ok) == 1 and ok[0]["actor_id"] == KONAN


def test_a_rejected_actor_is_reported_not_silently_dropped(monkeypatch):
    """A discarded approval and an absent approval look identical otherwise."""
    monkeypatch.setattr(ps, "_api", _stub([{"id": HERMES_BOT, "username": "h", "bot": True}]))
    d = ps.collect_decisions(message_id="1", token="x", humans={KONAN},
                             message_map={"1": "prp_x"})
    refusals = [x for x in d if "rejected_actor" in x]
    assert refusals and refusals[0]["rejected_actor"]["why"]


# ── the one-message-per-proposal rule ───────────────────────────────────

def test_one_message_per_proposal(proposal, log, tmp_path):
    """A ✅ attaches to a MESSAGE, so a message must carry exactly one proposal."""
    t = tmp_path / "t2.py"
    t.write_text("Y = 1\n")
    pa.propose(live_path=t, new_bytes=b"Y = 2\n", artifact_class="threshold",
               rationale="second", inputs_read=["a.py"], author="hermes", trigger="human",
               expected_improvement={"mechanism": "the constant follows $HOME so a session "
                                                  "reads a different tree",
                                     "metric": "m", "predicted_delta": "d",
                                     "blast_radius": "b", "reversibility": "r"}, path=log)
    msgs = ps.render_queue(log)
    assert len(msgs) == 2
    ids = {m["proposal_id"] for m in msgs}
    assert len(ids) == 2, "two proposals share a message — a ✅ would be ambiguous"
    for m in msgs:
        assert m["proposal_id"] in m["markdown"], "the message must name its proposal id"


def test_a_reaction_resolves_to_its_own_message(monkeypatch, proposal, log):
    """The target comes from the recorded map, not from a guess."""
    msgs = ps.render_queue(log)
    monkeypatch.setattr(ps, "_api", _stub([{"id": KONAN, "username": "k", "bot": False}]))
    d = ps.collect_decisions(message_id="777", token="x", humans={KONAN},
                             message_map={"777": msgs[0]["proposal_id"]})
    ok = [x for x in d if "rejected_actor" not in x]
    assert ok and ok[0]["proposal_id"] == msgs[0]["proposal_id"]


def test_an_unmapped_reaction_is_refused_not_guessed(monkeypatch, proposal, log):
    """No mapping means no target. Guessing would approve the wrong proposal."""
    monkeypatch.setattr(ps, "_api", _stub([{"id": KONAN, "username": "k", "bot": False}]))
    d = ps.collect_decisions(message_id="777", token="x", humans={KONAN}, message_map={})
    ok = [x for x in d if "rejected_actor" not in x]
    assert ok and ok[0]["proposal_id"] is None
    # and the applier refuses a decision with no target rather than applying something
    out = ps.act_on_decisions(ok, path=log)
    assert out["approved"] == [] and out["refused"]


# ── replies ─────────────────────────────────────────────────────────────

def test_a_reply_from_a_bot_is_refused(monkeypatch, proposal, log):
    monkeypatch.setattr(ps, "_api", _stub([], [
        {"content": "approve 1", "author": {"id": HERMES_BOT, "username": "h", "bot": True}}]))
    d = ps.collect_decisions(message_id="1", token="x", humans={KONAN},
                             number_map={1: proposal.proposal_id}, message_map={})
    assert not [x for x in d if "rejected_actor" not in x]


def test_an_empty_queue_renders_nothing(monkeypatch, log):
    assert ps.render_queue(log) == []
