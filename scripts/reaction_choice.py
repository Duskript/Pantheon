#!/usr/bin/env python3
"""Generic A/B/C reaction-choice gate for content-pipeline decisions.

WHAT THIS IS
------------
One reusable primitive for every "pick one" step in the pipeline: topic selection,
draft angle selection, and image-variant selection. It posts a choice to a Discord
thread, attaches the option reactions, and reads back which option a verified human
chose.

WHY NOT REUSE proposal_surface.py DIRECTLY
------------------------------------------
`proposal_surface.py` is bound to `lib.ichor.proposal_applier` - its queue, its tiers,
its apply step. The pipeline needs the same *discipline* without the harness coupling.
The discipline is what is ported here, deliberately and in full:

  1. **Identity, two checks, both required.** The actor must be in
     `DISCORD_ALLOWED_USERS` (the gateway's own allow-list, reused not restated) AND
     must not be a bot. Without the bot check the agent's own account can pick its own
     option and the pipeline ships whatever it wanted. Without the allow-list any
     server member can steer published content.
  2. **Read reactions over REST, never from counts.** `fetch_messages` returns reaction
     *counts*, and a count cannot say WHO reacted. A count is the shape of evidence
     that looks like proof and isn't.
  3. **Never guess the target.** The option is resolved from the emoji and the recorded
     message id, not by inference.

WHY ONE MESSAGE IS ENOUGH HERE
------------------------------
`proposal_surface.py` posts one proposal per message because a bare ✅ cannot say
*which* of five proposals was approved. Here the emoji itself carries the choice -
🇦 / 🇧 / 🇨 name the option - so a single message holding all the options is
unambiguous. This matters for images: three variants belong in one message so they can
be compared side by side, which one-message-per-variant would destroy.

AMBIGUITY IS REFUSED, NOT RESOLVED
----------------------------------
Two different options chosen means the intent is unknown. This returns
`ambiguous_choice` and lists them rather than picking the newest - "most recent wins"
silently discards a deliberate earlier choice. The operator resolves it with a reply.

Usage
-----
    reaction_choice.py post --thread ID --title "..." --option A:label --option B:label \\
        [--image A:/path/a.png] [--urgent]
    reaction_choice.py read --thread ID --message-id ID [--options A,B,C] [--json]
    reaction_choice.py selftest
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Optional

API = "https://discord.com/api/v10"

# Regional indicator symbols carry the option name in the emoji itself, which is what
# makes a single multi-option message unambiguous.
CHOICE_EMOJI: dict[str, str] = {
    "A": "\U0001f1e6", "B": "\U0001f1e7", "C": "\U0001f1e8",
    "D": "\U0001f1e9", "E": "\U0001f1ea", "F": "\U0001f1eb",
}
URGENT_EMOJI = "\u2757"  # ❗ - a flag, never a choice
EMOJI_TO_CHOICE = {v: k for k, v in CHOICE_EMOJI.items()}

DEFAULT_STATE = Path.home() / ".hermes" / "pantheon" / "content-pipeline" / "choices.json"


# ── identity ────────────────────────────────────────────────────────────

def _read_env_value(key: str) -> str:
    """Read a value from the Hermes env files. Never logged, never returned in output."""
    v = os.environ.get(key, "")
    if v:
        return v
    candidates = [Path.home() / ".hermes" / ".env"]
    candidates += sorted((Path.home() / ".hermes" / "profiles").glob("*/.env"))
    for p in candidates:
        try:
            for line in p.read_text().splitlines():
                if line.startswith(f"{key}="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def token() -> str:
    t = _read_env_value("DISCORD_BOT_TOKEN")
    if not t:
        raise SystemExit("no DISCORD_BOT_TOKEN found (env or ~/.hermes/.env)")
    return t


def allowed_humans() -> set[str]:
    """The gateway's own allow-list - reused, not restated."""
    raw = _read_env_value("DISCORD_ALLOWED_USERS")
    return {x.strip() for x in re.split(r"[,\s]+", raw) if x.strip().isdigit()}


def actor_is_human(user: dict[str, Any], humans: set[str]) -> tuple[bool, str]:
    """Both checks, in the order that fails closed. Returns (ok, reason_if_not).

    An EMPTY allow-list refuses everyone. `if humans and ...` would short-circuit to
    "allowed", which means an unset DISCORD_ALLOWED_USERS silently turns the gate into
    "any server member may choose what gets published". An empty list is not permission;
    it is the absence of any way to verify identity, so it must fail closed.
    """
    if user.get("bot"):
        return False, "bot account"
    if not humans:
        return False, "no allow-list configured (DISCORD_ALLOWED_USERS is empty)"
    if str(user.get("id")) not in humans:
        return False, "not in DISCORD_ALLOWED_USERS"
    return True, ""


# ── transport ───────────────────────────────────────────────────────────

def _retry_after(err: urllib.error.HTTPError) -> float:
    """Seconds Discord asks us to wait. Body first, then header, then a safe default.

    Discord puts `retry_after` in the JSON body for 429s and a `Retry-After` header on
    some responses. Reading the body requires care: it may already be consumed, and a
    malformed value must not turn a rate limit into a crash.
    """
    try:
        raw = err.read()
        if raw:
            payload = json.loads(raw)
            v = payload.get("retry_after")
            if isinstance(v, (int, float)) and v >= 0:
                return min(float(v), 30.0)
    except Exception:  # noqa: BLE001 - a bad body must not mask the 429
        pass
    try:
        v = err.headers.get("Retry-After") if err.headers else None
        if v is not None:
            return min(float(v), 30.0)
    except Exception:  # noqa: BLE001
        pass
    return 2.0


def _api(method: str, path: str, tok: str, body: Optional[dict] = None,
         *, attempts: int = 4) -> Any:
    """Discord REST call with bounded retry on 429 and 5xx.

    Retry is not optional here. Measured: three consecutive `collect` runs hit
    `HTTP 429 Too Many Requests` on runs 2 and 3, and the caller reported `read_failed`
    - so a choice made by the operator would be silently missed by the 15-minute cron
    that was supposed to pick it up. A rate limit is a "come back later", not a "no".
    """
    last: Optional[Exception] = None
    for n in range(attempts):
        req = urllib.request.Request(
            f"{API}{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bot {tok}", "Content-Type": "application/json",
                     "User-Agent": "hermes-content-pipeline/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=45) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            last = e
            if n == attempts - 1:
                raise
            if e.code == 429:
                time.sleep(_retry_after(e))
                continue
            if e.code >= 500:
                time.sleep(min(1.5 * (2 ** n), 10.0))
                continue
            raise
    if last is not None:
        raise last
    raise RuntimeError("unreachable")


def _post_with_images(thread_id: str, content: str, images: list[Path], tok: str) -> dict:
    """Multipart upload so variants appear as real attachments, in order.

    Order is load-bearing: the message body labels the images A/B/C in the same order
    they are attached, so the label and the picture cannot drift apart.
    """
    boundary = f"----hermes{uuid.uuid4().hex}"
    parts: list[bytes] = []

    def field(name: str, value: str) -> None:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n".encode())

    field("payload_json", json.dumps({"content": content[:1990]}))

    for i, img in enumerate(images):
        ctype = mimetypes.guess_type(img.name)[0] or "application/octet-stream"
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"files[{i}]\"; "
            f"filename=\"{img.name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
        parts.append(img.read_bytes())
        parts.append(b"\r\n")

    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        f"{API}/channels/{thread_id}/messages", method="POST", data=body,
        headers={"Authorization": f"Bot {tok}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": "hermes-content-pipeline/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())


# ── post ────────────────────────────────────────────────────────────────

def post_choice(
    *, thread_id: str, title: str, options: list[tuple[str, str]],
    body: str = "", image_paths: Optional[dict[str, Path]] = None,
    allow_urgent: bool = False, tok: Optional[str] = None,
    state_path: Path = DEFAULT_STATE, choice_id: str = "",
) -> dict[str, Any]:
    """Post a choice and attach its reactions. Returns `{message_id, choice_id, options}`.

    `options` is `[("A", "label"), ...]`. `image_paths` maps option letter -> file, and
    only those options appear as attachments (in option order).
    """
    if not options:
        raise ValueError("at least one option is required")
    if len(options) > len(CHOICE_EMOJI):
        raise ValueError(f"at most {len(CHOICE_EMOJI)} options are supported")
    letters = [o[0] for o in options]
    if len(set(letters)) != len(letters):
        raise ValueError(f"duplicate option letters: {letters}")
    unknown = [L for L in letters if L not in CHOICE_EMOJI]
    if unknown:
        raise ValueError(f"unsupported option letter(s) {unknown}; use {sorted(CHOICE_EMOJI)}")

    images: list[Path] = []
    if image_paths:
        for L, _ in options:
            p = image_paths.get(L)
            if p is None:
                continue
            if not Path(p).exists():
                raise ValueError(f"image for option {L} does not exist: {p}")
            images.append(Path(p))

    lines = [f"# {title}"]
    if body:
        lines += ["", body]
    lines += [""]
    for L, label in options:
        lines.append(f"**{L}** - {label}")
    lines += ["", f"React {' '.join(CHOICE_EMOJI[L] for L, _ in options)} to choose."]
    if allow_urgent:
        lines.append(f"React {URGENT_EMOJI} to flag this as urgent.")
    lines.append("Only an allow-listed human's reaction counts; bots are ignored.")

    tok = tok or token()
    posted = _post_with_images(thread_id, "\n".join(lines), images, tok)
    message_id = str(posted["id"])

    # Attach the reactions so the operator only has to click. A failure here is not
    # fatal to the post, but it must be visible: an option with no reaction is
    # unselectable by clicking.
    reactions_added, reactions_failed = [], []
    for L, _ in options:
        try:
            _api("PUT", f"/channels/{thread_id}/messages/{message_id}"
                        f"/reactions/{urllib.parse.quote(CHOICE_EMOJI[L])}/@me", tok)
            reactions_added.append(L)
        except urllib.error.HTTPError as e:
            reactions_failed.append({"option": L, "error": f"HTTP {e.code}"})
    if allow_urgent:
        try:
            _api("PUT", f"/channels/{thread_id}/messages/{message_id}"
                        f"/reactions/{urllib.parse.quote(URGENT_EMOJI)}/@me", tok)
            reactions_added.append("URGENT")
        except urllib.error.HTTPError as e:
            reactions_failed.append({"option": "URGENT", "error": f"HTTP {e.code}"})

    cid = choice_id or uuid.uuid4().hex[:12]
    record = {
        "choice_id": cid, "message_id": message_id, "thread_id": str(thread_id),
        "options": [{"letter": L, "label": label} for L, label in options],
        "images": {L: str(image_paths[L]) for L, _ in options if image_paths and L in image_paths},
        "allow_urgent": allow_urgent,
    }
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    state.setdefault("choices", {})[message_id] = record
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2) + "\n")

    return {"message_id": message_id, "choice_id": cid,
            "options": [L for L, _ in options],
            "reactions_added": reactions_added, "reactions_failed": reactions_failed}


# ── read ────────────────────────────────────────────────────────────────

def read_choice(
    *, message_id: str, thread_id: str, options: Optional[list[str]] = None,
    tok: Optional[str] = None, humans: Optional[set[str]] = None,
    state_path: Path = DEFAULT_STATE,
) -> dict[str, Any]:
    """Read back the chosen option, with identity enforcement.

    Returns `{status, choice, actor, source, refused, urgent}` where status is one of
    `chosen`, `no_choice`, `ambiguous_choice`, `no_allowlist`. `refused` lists reactions from bots or
    non-allow-listed users - reported, never silently dropped, because a discarded
    choice and an absent choice look identical otherwise.
    """
    tok = tok or token()
    humans = allowed_humans() if humans is None else humans
    if not humans:
        # Refuse before any network read: with no allow-list nothing can be verified.
        return {"status": "no_allowlist", "choice": None, "actor": None, "source": None,
                "votes": {}, "refused": [],
                "detail": "DISCORD_ALLOWED_USERS is empty; refusing to read a choice "
                          "that cannot be attributed to a verified human",
                "urgent": False}

    if options is None:
        state = json.loads(state_path.read_text()) if state_path.exists() else {}
        rec = (state.get("choices") or {}).get(str(message_id)) or {}
        options = [o["letter"] for o in rec.get("options", [])]
    options = list(options or [])

    votes: dict[str, list[dict[str, Any]]] = {}
    refused: list[dict[str, Any]] = []

    # Reactions: REST only. fetch_messages gives counts, and a count cannot say who.
    for L in options:
        emoji = CHOICE_EMOJI[L]
        try:
            users = _api("GET", f"/channels/{thread_id}/messages/{message_id}"
                                f"/reactions/{urllib.parse.quote(emoji)}?limit=100", tok) or []
        except urllib.error.HTTPError as e:
            if e.code == 404:  # nobody reacted with this emoji yet
                continue
            raise
        for u in users:
            ok, why = actor_is_human(u, humans)
            if ok:
                votes.setdefault(L, []).append(
                    {"actor": u.get("username") or u.get("id"), "actor_id": u.get("id"),
                     "source": "reaction"})
            else:
                refused.append({"option": L, "actor_id": u.get("id"), "why": why})

    # Replies as an accessible alternative: "A", "pick B", "b".
    try:
        msgs = _api("GET", f"/channels/{thread_id}/messages?limit=50", tok) or []
    except urllib.error.HTTPError:
        msgs = []
    for m in msgs:
        content = (m.get("content") or "").strip()
        mt = re.match(r"^(?:pick\s+|choose\s+)?([A-Fa-f])\b", content)
        if not mt:
            continue
        letter = mt.group(1).upper()
        if letter not in options:
            continue
        author = m.get("author") or {}
        ok, why = actor_is_human(author, humans)
        if not ok:
            refused.append({"option": letter, "actor_id": author.get("id"), "why": why,
                            "source": "reply"})
            continue
        votes.setdefault(letter, []).append(
            {"actor": author.get("username") or author.get("id"),
             "actor_id": author.get("id"), "source": "reply"})

    urgent = False
    try:
        users = _api("GET", f"/channels/{thread_id}/messages/{message_id}"
                            f"/reactions/{urllib.parse.quote(URGENT_EMOJI)}?limit=100", tok) or []
        urgent = any(actor_is_human(u, humans)[0] for u in users)
    except urllib.error.HTTPError:
        pass

    chosen = sorted(votes)
    if len(chosen) == 1:
        L = chosen[0]
        winner = votes[L][-1]
        return {"status": "chosen", "choice": L, "actor": winner["actor"],
                "actor_id": winner["actor_id"], "source": winner["source"],
                "votes": {k: [v["actor"] for v in vs] for k, vs in votes.items()},
                "refused": refused, "urgent": urgent}
    if not chosen:
        return {"status": "no_choice", "choice": None, "actor": None, "source": None,
                "votes": {}, "refused": refused, "urgent": urgent}
    return {"status": "ambiguous_choice", "choice": None, "actor": None, "source": None,
            "votes": {k: [v["actor"] for v in vs] for k, vs in votes.items()},
            "refused": refused, "urgent": urgent,
            "detail": f"multiple options selected: {chosen} - reply with one letter to resolve"}


# ── selftest ────────────────────────────────────────────────────────────

def _selftest() -> int:
    """Prove the identity checks fail closed, without touching Discord.

    Falsification: `test_bot_is_refused` fails if the `user.get("bot")` check is
    removed. `test_stranger_is_refused` fails if the allow-list check is removed.
    """
    humans = {"111", "222"}
    failures: list[str] = []

    def check(name: str, got: Any, want: Any) -> None:
        if got != want:
            failures.append(f"{name}: got {got!r}, want {want!r}")

    check("bot refused", actor_is_human({"id": "111", "bot": True}, humans), (False, "bot account"))
    check("stranger refused",
          actor_is_human({"id": "999", "bot": False}, humans), (False, "not in DISCORD_ALLOWED_USERS"))
    check("allow-listed human allowed", actor_is_human({"id": "111"}, humans), (True, ""))
    check("empty allow-list refuses everyone",
          actor_is_human({"id": "999"}, set()),
          (False, "no allow-list configured (DISCORD_ALLOWED_USERS is empty)"))
    check("empty allow-list refuses even a plausible id",
          actor_is_human({"id": "111"}, set()),
          (False, "no allow-list configured (DISCORD_ALLOWED_USERS is empty)"))
    check("emoji map round-trips", EMOJI_TO_CHOICE[CHOICE_EMOJI["B"]], "B")
    check("emoji are distinct", len(set(CHOICE_EMOJI.values())), len(CHOICE_EMOJI))
    check("urgent is not a choice", URGENT_EMOJI in EMOJI_TO_CHOICE, False)

    # option validation must reject nonsense before any network call
    for bad, why in (
        ([], "empty options"),
        ([("A", "x"), ("A", "y")], "duplicate letters"),
        ([("Z", "x")], "unsupported letter"),
    ):
        try:
            post_choice(thread_id="0", title="t", options=bad, tok="x")
            failures.append(f"{why}: should have raised ValueError")
        except ValueError:
            pass

    if failures:
        print("SELFTEST FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("SELFTEST OK: identity checks fail closed, emoji map is sound, "
          "option validation rejects malformed input.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="A/B/C reaction-choice gate")
    sub = ap.add_subparsers(dest="action", required=True)

    p = sub.add_parser("post")
    p.add_argument("--thread", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--body", default="")
    p.add_argument("--option", action="append", default=[], help="LETTER:label")
    p.add_argument("--image", action="append", default=[], help="LETTER:/path.png")
    p.add_argument("--urgent", action="store_true")
    p.add_argument("--choice-id", default="")

    r = sub.add_parser("read")
    r.add_argument("--thread", required=True)
    r.add_argument("--message-id", required=True)
    r.add_argument("--options", default="", help="comma list, e.g. A,B,C")
    r.add_argument("--json", action="store_true")

    sub.add_parser("selftest")
    args = ap.parse_args()

    if args.action == "selftest":
        return _selftest()

    if args.action == "post":
        opts: list[tuple[str, str]] = []
        for spec in args.option:
            if ":" not in spec:
                raise SystemExit(f"--option needs LETTER:label, got {spec!r}")
            L, label = spec.split(":", 1)
            opts.append((L.strip().upper(), label.strip()))
        imgs: dict[str, Path] = {}
        for spec in args.image:
            if ":" not in spec:
                raise SystemExit(f"--image needs LETTER:/path, got {spec!r}")
            L, path = spec.split(":", 1)
            imgs[L.strip().upper()] = Path(path.strip())
        out = post_choice(thread_id=args.thread, title=args.title, body=args.body,
                          options=opts, image_paths=imgs or None,
                          allow_urgent=args.urgent, choice_id=args.choice_id)
        print(json.dumps(out, indent=2))
        return 0

    opts_list = [x.strip().upper() for x in args.options.split(",") if x.strip()] or None
    out = read_choice(message_id=args.message_id, thread_id=args.thread, options=opts_list)
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"status={out['status']} choice={out['choice']} actor={out['actor']} "
              f"source={out['source']} urgent={out['urgent']}")
        if out.get("detail"):
            print(f"  detail: {out['detail']}")
        for x in out["refused"]:
            print(f"  REFUSED option={x['option']} id={x['actor_id']} why={x['why']}")
    # Exit 0 only when the read was conclusive. `no_choice` is conclusive (nothing was
    # chosen yet); `ambiguous_choice` and `no_allowlist` are not, and callers that ignore
    # exit codes would otherwise treat them as a decision.
    return 0 if out["status"] in ("chosen", "no_choice") else 1


if __name__ == "__main__":
    sys.exit(main())
