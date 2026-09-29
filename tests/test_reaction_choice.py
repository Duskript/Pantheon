"""The reaction gate must know WHO chose, and must fail closed.

An approval surface that cannot tell who approved is not an approval surface. Two
checks, both required:

  1. the actor must be in `DISCORD_ALLOWED_USERS` (the gateway's own allow-list)
  2. the actor must NOT be a bot

Without (2) the agent's own account reacts to its own choice and the pipeline ships
whatever it wanted. Without (1) any server member can steer published content.

These tests stub `_api`, so no network and no real Discord message is involved. Every
test names the mutation it is designed to catch, so the suite is falsifiable rather
than merely green.

FALSIFICATION
-------------
- `test_bot_reaction_is_refused`      fails if the `user.get("bot")` check is removed.
- `test_stranger_reaction_is_refused` fails if the allow-list check is removed.
- `test_ambiguous_choice_is_refused`  fails if multiple votes are resolved by picking
                                     the newest instead of refusing.
- `test_empty_allowlist_refuses_all`  fails if the empty-list case short-circuits to
                                     "allowed" (`if humans and ...`).
- `test_choice_resolves_to_its_own_message` fails if the reader guesses the target
                                     instead of reading the given message id.
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
    "_reaction_choice", REPO / "scripts" / "reaction_choice.py")
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)

KONAN = "180817012619083776"
HERMES_BOT = "1499845064359280710"
STRANGER = "999999999999999999"
HUMANS = {KONAN, HERMES_BOT}

A_EMOJI, B_EMOJI, C_EMOJI = rc.CHOICE_EMOJI["A"], rc.CHOICE_EMOJI["B"], rc.CHOICE_EMOJI["C"]
MSG = "1553288174275661914"


def _user(uid: str, bot: bool = False) -> dict:
    return {"id": uid, "username": f"user{uid}", "bot": bot}


def _stub(*, reactions=None, replies=()):
    """Fake `_api`. `reactions` maps emoji -> list of users."""
    reactions = reactions or {}

    def fake(method, path, token, body=None):
        for emoji, users in reactions.items():
            quoted = __import__("urllib.parse", fromlist=["quote"]).quote(emoji)
            if quoted in path:
                return list(users)
        if "reactions" in path:
            return []
        if "messages?" in path:
            return list(replies)
        return {"id": MSG}
    return fake


def _read(monkeypatch, *, reactions=None, replies=(), options=("A", "B", "C"), humans=HUMANS):
    monkeypatch.setattr(rc, "_api", _stub(reactions=reactions, replies=replies))
    monkeypatch.setattr(rc, "token", lambda: "test-token")
    return rc.read_choice(message_id=MSG, thread_id="123", options=list(options), humans=humans)


# ── identity ────────────────────────────────────────────────────────────

def test_bot_reaction_is_refused(monkeypatch):
    """FALSIFIES: removing the bot check lets the agent choose its own option."""
    out = _read(monkeypatch, reactions={A_EMOJI: [_user(HERMES_BOT, bot=True)]})
    assert out["status"] == "no_choice"
    assert out["choice"] is None
    assert [r["why"] for r in out["refused"]] == ["bot account"]


def test_stranger_reaction_is_refused(monkeypatch):
    """FALSIFIES: removing the allow-list check lets any member steer content."""
    out = _read(monkeypatch, reactions={B_EMOJI: [_user(STRANGER)]})
    assert out["status"] == "no_choice"
    assert out["refused"][0]["why"] == "not in DISCORD_ALLOWED_USERS"


def test_bot_and_stranger_together_are_refused(monkeypatch):
    out = _read(monkeypatch, reactions={A_EMOJI: [_user(HERMES_BOT, bot=True), _user(STRANGER)]})
    assert out["status"] == "no_choice"
    assert len(out["refused"]) == 2


def test_actor_is_human_empty_list_refuses_directly():
    """Unit-level guard, isolated from read_choice's own early return.

    Without this the empty-list mutation SURVIVES: read_choice carries its own
    `if not humans` early return, so an integration-level test passes even when
    actor_is_human has been mutated back to the `if humans and ...` short-circuit.
    Verified by mutation: this test is the only one that catches it.
    """
    assert rc.actor_is_human({"id": KONAN}, set()) == (
        False, "no allow-list configured (DISCORD_ALLOWED_USERS is empty)")
    assert rc.actor_is_human({"id": KONAN, "bot": True}, set())[0] is False
    assert rc.actor_is_human({"id": KONAN}, {KONAN}) == (True, "")


def test_empty_allowlist_refuses_all(monkeypatch):
    """FALSIFIES: `if humans and ...` short-circuits an unset allow-list to 'allowed'."""
    monkeypatch.setattr(rc, "_api", _stub(reactions={A_EMOJI: [_user(KONAN)]}))
    monkeypatch.setattr(rc, "token", lambda: "t")
    out = rc.read_choice(message_id=MSG, thread_id="123", options=["A", "B"], humans=set())
    assert out["status"] == "no_allowlist"
    assert out["choice"] is None


# ── choice resolution ───────────────────────────────────────────────────

def test_human_reaction_chooses(monkeypatch):
    out = _read(monkeypatch, reactions={B_EMOJI: [_user(KONAN)]})
    assert out["status"] == "chosen"
    assert out["choice"] == "B"
    assert out["source"] == "reaction"


def test_bot_ignored_when_a_human_also_voted(monkeypatch):
    """The common live case: the bot pre-adds all reactions so the operator can click."""
    out = _read(monkeypatch, reactions={
        A_EMOJI: [_user(HERMES_BOT, bot=True)],
        B_EMOJI: [_user(HERMES_BOT, bot=True), _user(KONAN)],
        C_EMOJI: [_user(HERMES_BOT, bot=True)],
    })
    assert out["status"] == "chosen"
    assert out["choice"] == "B"
    assert len(out["refused"]) == 3


def test_ambiguous_choice_is_refused(monkeypatch):
    """FALSIFIES: 'most recent wins' would silently discard a deliberate earlier vote."""
    out = _read(monkeypatch, reactions={A_EMOJI: [_user(KONAN)], C_EMOJI: [_user(KONAN)]})
    assert out["status"] == "ambiguous_choice"
    assert out["choice"] is None
    assert "resolve" in out["detail"]


def test_no_reaction_is_no_choice(monkeypatch):
    out = _read(monkeypatch, reactions={})
    assert out["status"] == "no_choice"
    assert out["choice"] is None


def test_reply_choice_works(monkeypatch):
    out = _read(monkeypatch, replies=[{"content": "pick C", "author": _user(KONAN)}])
    assert out["status"] == "chosen"
    assert out["choice"] == "C"
    assert out["source"] == "reply"


def test_reply_from_stranger_is_refused(monkeypatch):
    out = _read(monkeypatch, replies=[{"content": "A", "author": _user(STRANGER)}])
    assert out["status"] == "no_choice"
    assert out["refused"][0]["source"] == "reply"


def test_reply_naming_an_unknown_option_is_ignored(monkeypatch):
    out = _read(monkeypatch, replies=[{"content": "Z", "author": _user(KONAN)}],
                options=("A", "B"))
    assert out["status"] == "no_choice"


def test_choice_resolves_to_its_own_message(monkeypatch):
    """FALSIFIES: guessing the target instead of using the recorded message id."""
    import urllib.parse
    seen: list[str] = []
    # The emoji is URL-encoded in the path, so compare the QUOTED form. Comparing the
    # raw emoji silently never matches, which is how this stub was wrong on first write.
    quoted_b = urllib.parse.quote(B_EMOJI)

    def fake(method, path, token, body=None):
        seen.append(path)
        if "reactions" in path:
            return [_user(KONAN)] if quoted_b in path else []
        if "messages?" in path:
            return []
        return {"id": MSG}

    monkeypatch.setattr(rc, "_api", fake)
    monkeypatch.setattr(rc, "token", lambda: "t")
    out = rc.read_choice(message_id=MSG, thread_id="123", options=["A", "B"])
    assert out["choice"] == "B"
    assert all(MSG in p for p in seen if "reactions" in p), "must read THIS message's reactions"


# ── posting validation ──────────────────────────────────────────────────

def test_post_rejects_malformed_options():
    for bad in ([], [("A", "x"), ("A", "y")], [("Z", "x")]):
        with pytest.raises(ValueError):
            rc.post_choice(thread_id="0", title="t", options=bad, tok="x")


def test_post_rejects_missing_image():
    with pytest.raises(ValueError):
        rc.post_choice(thread_id="0", title="t", options=[("A", "x")],
                       image_paths={"A": Path("/nonexistent/nope.png")}, tok="x")


def test_emoji_map_is_sound():
    assert len(set(rc.CHOICE_EMOJI.values())) == len(rc.CHOICE_EMOJI)
    assert rc.URGENT_EMOJI not in rc.EMOJI_TO_CHOICE
    assert all(rc.EMOJI_TO_CHOICE[v] == k for k, v in rc.CHOICE_EMOJI.items())

# ── rate limiting ───────────────────────────────────────────────────────

def _http_error(code, body=b"", headers=None):
    import urllib.error
    import io
    return urllib.error.HTTPError(
        url="https://discord.com/api/v10/x", code=code, msg="err",
        hdrs=headers or {}, fp=io.BytesIO(body))


def test_retry_after_reads_json_body():
    """Discord's own number is honoured, not a hardcoded guess."""
    assert rc._retry_after(_http_error(429, b'{"retry_after": 1.25}')) == 1.25


def test_retry_after_reads_header_when_body_is_empty():
    assert rc._retry_after(_http_error(429, b"", {"Retry-After": "3"})) == 3.0


def test_retry_after_is_clamped_and_survives_garbage():
    """A malformed body must not turn a rate limit into a crash or an endless wait."""
    assert rc._retry_after(_http_error(429, b"not json")) == 2.0
    assert rc._retry_after(_http_error(429, b'{"retry_after": 9999}')) == 30.0
    assert rc._retry_after(_http_error(429, b'{"retry_after": -5}')) == 2.0


def test_api_retries_on_429_then_succeeds(monkeypatch):
    """FALSIFIES: without retry the caller reports read_failed and the choice is LOST.

    Measured live: three consecutive `collect` runs hit HTTP 429 on runs 2 and 3.
    """
    import urllib.request
    calls = {"n": 0}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _http_error(429, b'{"retry_after": 0}')
        return FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    assert rc._api("GET", "/x", "tok") == {"ok": True}
    assert calls["n"] == 2, "must retry exactly once here"


def test_api_does_not_retry_a_404(monkeypatch):
    """A 404 means 'nobody reacted yet' - retrying it would be pointless delay."""
    import urllib.request
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise _http_error(404)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    with pytest.raises(Exception):
        rc._api("GET", "/x", "tok")
    assert calls["n"] == 1, "404 must not be retried"


def test_api_gives_up_after_max_attempts(monkeypatch):
    """Bounded retry: an unbounded loop in a 15-minute cron is an outage."""
    import urllib.request
    calls = {"n": 0}

    def fake_urlopen(req, timeout=None):
        calls["n"] += 1
        raise _http_error(429, b'{"retry_after": 0}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(rc.time, "sleep", lambda s: None)
    with pytest.raises(Exception):
        rc._api("GET", "/x", "tok", attempts=3)
    assert calls["n"] == 3, "must stop at the attempt limit"

