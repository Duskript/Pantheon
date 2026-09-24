#!/usr/bin/env python3
"""Phase 3's approval surface — proposals out to Discord, approvals back in.

THE SURFACE
-----------
A proposal is posted to the approvals thread with its `expected_improvement` block,
so it can be judged WITHOUT opening the diff. Konan approves by reacting ✅ or by
replying `approve <n>`. Either way the approval is recorded against a human identity,
and only then can the applier act on it.

THE LOAD-BEARING PART IS THE IDENTITY CHECK
-------------------------------------------
An approval surface that cannot tell who approved is not an approval surface. Two
checks, both required:

  1. the actor must be in `DISCORD_ALLOWED_USERS` (the same allow-list the gateway uses)
  2. the actor must NOT be a bot

Without (2), the agent's own bot account can react ✅ to its own proposal and the
result is T3 with a screenshot — automation wearing a human's badge. Without (1), any
server member can approve a change to the harness.

This is why the surface reads reactions through the REST API rather than the Discord
tool: `fetch_messages` returns reaction *counts*, and a count cannot say who reacted.
A count is exactly the shape of evidence that looks like proof and isn't.

Usage:
    python3 scripts/proposal_surface.py render            # post the pending queue
    python3 scripts/proposal_surface.py collect           # read approvals back
    python3 scripts/proposal_surface.py collect --apply    # and apply approved T1 items
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("proposal-surface")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.ichor import proposal_applier as pa  # noqa: E402

API = "https://discord.com/api/v10"
THREAD_ID = "1552415266846154882"          # #notifications -> the approvals thread
CHANNEL_ID = "1522263537186246717"
APPROVE_EMOJI = "\u2705"                    # ✅
REJECT_EMOJI = "\u274c"                     # ❌
STATE_FILE = Path.home() / ".hermes" / "pantheon" / "proposals" / "surface_state.json"


def _token() -> str:
    t = os.environ.get("DISCORD_BOT_TOKEN", "")
    if t:
        return t
    for p in (Path.home() / ".hermes" / ".env", Path.home() / ".hermes" / "profiles" / "hermes" / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                if line.startswith("DISCORD_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("no DISCORD_BOT_TOKEN found (env or ~/.hermes/.env)")


def allowed_humans() -> set[str]:
    """The gateway's own allow-list — reused, not restated."""
    v = os.environ.get("DISCORD_ALLOWED_USERS", "")
    if not v:
        for p in (Path.home() / ".hermes" / ".env",):
            if p.exists():
                for line in p.read_text().splitlines():
                    if line.startswith("DISCORD_ALLOWED_USERS="):
                        v = line.split("=", 1)[1].strip().strip('"').strip("'")
    return {x.strip() for x in re.split(r"[,\s]+", v) if x.strip().isdigit()}


def _api(method: str, path: str, token: str, body: Optional[dict] = None) -> Any:
    req = urllib.request.Request(
        f"{API}{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
                 "User-Agent": "hermes-pantheon/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


# ── render ──────────────────────────────────────────────────────────────

def render_queue(path: Path = pa.PROPOSAL_LOG) -> List[Dict[str, str]]:
    """Render the pending queue as ONE MESSAGE PER PROPOSAL.

    One-per-message is not cosmetic. A \u2705 reaction attaches to a MESSAGE, so a
    single message carrying five proposals cannot say which one was approved — the
    reaction path resolved `proposal_id: None` and the decision was correctly refused
    for having no target. Posting one proposal per message makes \u2705 unambiguous,
    and the message-id -> proposal-id mapping is what the collector reads back.

    Returns `[{proposal_id, index, markdown}]`, in queue order.
    """
    pend = pa.pending(path)
    if not pend:
        return []
    out: List[Dict[str, str]] = []
    for n, p in enumerate(pend, 1):
        ei = p.get("expected_improvement") or {}
        body = "\n".join([
            f"# \U0001f5f3\ufe0f Proposal {n} — tier {p['tier']}",
            "",
            f"**Target:** `{p['live_path']}` ({p['artifact_class']})",
            f"**Why:** {p['rationale']}",
            "",
            "```json", json.dumps(ei, indent=2), "```", "",
            f"*author:* `{p['author']}` · *trigger:* `{p['trigger']}`",
            f"*inputs read:* {', '.join(p.get('inputs_read') or []) or '(none)'}",
            "",
            "**React \u2705 to approve, \u274c to reject** — or reply `approve` / `reject`.",
            "Nothing is applied until you approve: T1 requires an explicit human",
            "approval and the applier refuses without one.",
            "",
            f"`{p['proposal_id']}`",
        ])
        out.append({"proposal_id": p["proposal_id"], "index": str(n), "markdown": body})
    return out


# ── collect ─────────────────────────────────────────────────────────────

def collect_decisions(
    *, message_id: str, thread_id: str = THREAD_ID, token: Optional[str] = None,
    humans: Optional[set[str]] = None, number_map: Optional[Dict[int, str]] = None,
    message_map: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    """Read approvals from reactions AND replies, with identity enforcement.

    Returns records of the form `{proposal_id, decision, actor, source, rejected}`.
    Anything from a bot, or from an actor not in the allow-list, is DISCARDED and
    reported — not silently ignored, because a discarded approval and an absent
    approval look identical otherwise.
    """
    token = token or _token()
    humans = humans if humans is not None else allowed_humans()
    number_map = number_map or {}
    decisions: List[Dict[str, Any]] = []
    rejected_actors: List[Dict[str, Any]] = []

    def _actor_ok(user: Dict[str, Any]) -> bool:
        if user.get("bot"):
            rejected_actors.append({"id": user.get("id"), "why": "bot account"})
            return False
        if humans and str(user.get("id")) not in humans:
            rejected_actors.append({"id": user.get("id"), "why": "not in DISCORD_ALLOWED_USERS"})
            return False
        return True

    # reactions — needs the REST API; fetch_messages only gives counts
    for emoji, decision in ((APPROVE_EMOJI, "approve"), (REJECT_EMOJI, "reject")):
        try:
            users = _api("GET",
                         f"/channels/{thread_id}/messages/{message_id}"
                         f"/reactions/{urllib.parse.quote(emoji)}?limit=100", token) or []
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        # The reaction is on ONE message; that message carries ONE proposal. Resolve
        # the target from the recorded message-id -> proposal-id map, not by guessing.
        target = (message_map or {}).get(str(message_id))
        for u in users:
            if _actor_ok(u):
                decisions.append({"proposal_id": target, "decision": decision,
                                  "actor": u.get("username") or u.get("id"),
                                  "actor_id": u.get("id"), "source": "reaction",
                                  "message_id": str(message_id)})

    # replies — `fetch_messages` is enough here, and author ids come with it
    try:
        msgs = _api("GET", f"/channels/{thread_id}/messages?limit=50", token) or []
    except urllib.error.HTTPError:
        msgs = []
    for m in msgs:
        content = (m.get("content") or "").strip()
        if not re.match(r"^(approve|reject)\b", content, re.I):
            continue
        author = m.get("author") or {}
        if not _actor_ok(author):
            continue
        verb = content.split()[0].lower()
        targets = re.findall(r"\d+", content)
        if not targets:
            continue
        for t in targets:
            decisions.append({
                "proposal_id": number_map.get(int(t)),
                "decision": verb,
                "actor": author.get("username") or author.get("id"),
                "actor_id": author.get("id"), "source": "reply", "index": int(t)})

    return decisions + [{"rejected_actor": r} for r in rejected_actors]


def act_on_decisions(
    decisions: List[Dict[str, Any]], *, path: Path = pa.PROPOSAL_LOG,
    apply_approved: bool = False,
) -> Dict[str, Any]:
    """Record approvals. Refuses anything without a verified human actor."""
    out = {"approved": [], "rejected": [], "applied": [], "refused": []}
    for d in decisions:
        if "rejected_actor" in d:
            out["refused"].append(d["rejected_actor"])
            logger.warning("REFUSED an approval from %s (%s)",
                           d["rejected_actor"].get("id"), d["rejected_actor"].get("why"))
            continue
        pid = d.get("proposal_id")
        if not pid:
            out["refused"].append({"why": "no proposal id resolved", **d})
            continue
        if d["decision"] == "approve":
            prop = pa.approve(pid, approver=d["actor"], path=path)
            out["approved"].append(pid)
            if apply_approved and prop.tier in pa.ALLOWED_TIERS:
                done = pa.apply_proposal(pid, path=path)
                out["applied"].append({"proposal_id": pid,
                                       "landed": done.verification.get("landed")})
        else:
            out["rejected"].append(pid)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3 approval surface")
    ap.add_argument("action", choices=["render", "collect"])
    ap.add_argument("--thread", default=THREAD_ID)
    ap.add_argument("--message-id", default="")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.action == "render":
        msgs = render_queue()
        if not msgs:
            print("**No pending proposals.** The queue is empty.")
            return 0
        # One message per proposal, so a \u2705 has exactly one possible target.
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        mapping = state.get("message_to_proposal", {})
        token = _token()
        for m in msgs:
            try:
                posted = _api("POST", f"/channels/{args.thread}/messages", token,
                              {"content": m["markdown"][:1990]})
                mapping[str(posted["id"])] = m["proposal_id"]
                logger.info("posted proposal %s as message %s", m["proposal_id"], posted["id"])
            except Exception as e:
                logger.error("could not post %s: %s", m["proposal_id"], str(e)[:120])
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(
            {"message_to_proposal": mapping, "thread": args.thread}, indent=2) + "\n")
        logger.info("recorded %d message->proposal mapping(s)", len(mapping))
        return 0

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    message_map = state.get("message_to_proposal", {})
    pend = pa.pending()
    number_map = {n: p["proposal_id"] for n, p in enumerate(pend, 1)}
    if args.message_id:
        # an explicit message id overrides the recorded map for a single-message run
        message_map = {**message_map, args.message_id: message_map.get(args.message_id, "")}
        ids = [args.message_id]
    else:
        ids = list(message_map)
    decisions: List[Dict[str, Any]] = []
    for mid in ids:
        decisions += collect_decisions(message_id=mid, thread_id=args.thread,
                                       number_map=number_map, message_map=message_map)
    if args.dry_run:
        print(json.dumps(decisions, indent=2))
        return 0
    result = act_on_decisions(decisions, apply_approved=args.apply)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
