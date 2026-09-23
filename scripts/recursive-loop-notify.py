#!/usr/bin/env python3
"""Recursive-loop reporting + approval emitter.

One surface, two jobs:
  * report  - append-only record of what the loop observed / measured
  * propose - a candidate upgrade, carrying a mandatory justification block
  * decide  - Konan's approval decision, recorded against the proposal id

Destination and ledger paths come from
``~/.hermes/pantheon/recursive-loop-reporting.json``.

Design rules this script enforces (from the self-improvement-loop contract):
  * A proposal without a filled ``expected_improvement`` block is rejected at
    intake - before anything is posted or written.
  * T2 requires a named human approver; T3 is human-only and this script has no
    apply path at all (the applier is a separate, later phase).
  * Every post is also appended to the JSONL ledger, so the record survives
    Discord retention and thread archival.
  * The egress is only claimed after the API returns a message id; a failure
    exits non-zero and writes nothing to the ledger.

Usage:
  recursive-loop-notify.py report  --title T [--body-file F | --body TEXT]
  recursive-loop-notify.py propose --file proposal.json
  recursive-loop-notify.py decide  --id P --decision approve|reject [--reason R]
  recursive-loop-notify.py status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ACCOUNT_HOME = Path("/home/konan")
REGISTRY = ACCOUNT_HOME / ".hermes" / "pantheon" / "recursive-loop-reporting.json"
ENV_FILE = ACCOUNT_HOME / ".hermes" / ".env"
API = "https://discord.com/api/v10"
CHUNK = 1900
TIERS = ("T1", "T2", "T3")
DECISIONS = ("approve", "reject")


class EmitError(RuntimeError):
    """Raised for every refusal; nothing is posted or written when it fires."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_registry(path: Path = REGISTRY) -> dict:
    if not path.exists():
        raise EmitError(f"registry missing: {path}")
    with path.open() as fh:
        reg = json.load(fh)
    for key in ("channel_id", "thread_id", "ledger"):
        if not reg.get(key):
            raise EmitError(f"registry is missing required key: {key}")
    return reg


def bot_token(env_file: Path = ENV_FILE) -> str:
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if tok:
        return tok
    if not env_file.exists():
        raise EmitError(f"no DISCORD_BOT_TOKEN in env and no env file at {env_file}")
    with env_file.open() as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                if tok:
                    return tok
    raise EmitError(f"DISCORD_BOT_TOKEN not found in {env_file}")


def post_message(thread_id: str, content: str, token: str) -> str:
    """POST one chunk. Returns the message id. Raises on any non-2xx."""
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        f"{API}/channels/{thread_id}/messages",
        data=payload,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "PantheonRecursiveLoop (hermes, 1.0)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:400]
        raise EmitError(f"discord POST failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise EmitError(f"discord POST failed: {exc.reason}") from exc
    if "id" not in body:
        raise EmitError(f"discord POST returned no message id: {str(body)[:200]}")
    return str(body["id"])


def chunk(text: str, size: int = CHUNK) -> list:
    """Split on line boundaries so a justification block never splits mid-field."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        if len(cur) + len(line) > size and cur:
            out.append(cur)
            cur = ""
        cur += line
    if cur:
        out.append(cur)
    return out or [""]


def send(thread_id: str, text: str, token: str) -> list:
    parts = chunk(text)
    ids = []
    for i, part in enumerate(parts, 1):
        label = f" ({i}/{len(parts)})" if len(parts) > 1 else ""
        ids.append(post_message(thread_id, part + label, token))
    return ids


def append_ledger(ledger: Path, record: dict) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def load_ledger(ledger: Path) -> list:
    if not ledger.exists():
        return []
    rows = []
    with ledger.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def proposal_state(rows: list) -> dict:
    """Fold the append-only rows into current state, keyed by proposal id."""
    state = {}
    for row in rows:
        if row.get("event") == "proposal":
            state[row["proposal_id"]] = {
                "tier": row.get("tier"),
                "target": row.get("target"),
                "status": "pending",
                "decision": None,
                "posted_at": row.get("ts"),
            }
        elif row.get("event") == "decision":
            entry = state.setdefault(
                row["proposal_id"], {"status": "pending", "decision": None}
            )
            entry["status"] = row["decision"]
            entry["decision"] = row
    return state


def render_proposal(p: dict) -> str:
    just = p["expected_improvement"]
    lines = [
        f"**PROPOSAL `{p['proposal_id']}` - {p['title']}**",
        f"tier: `{p['tier']}` | target: `{p['target']}` | approver required: `{p.get('approver') or 'n/a'}`",
        "",
        "**Why this change (justification block)**",
        f"- mechanism: {just['mechanism']}",
        f"- metric: {just['metric']}",
        f"- predicted delta: {just['predicted_delta']}",
        f"- blast radius: {just['blast_radius']}",
        f"- reversibility: {just['reversibility']}",
    ]
    if p.get("diff_summary"):
        lines += ["", f"**Diff summary:** {p['diff_summary']}"]
    if p.get("evidence"):
        lines += ["", f"**Evidence:** {p['evidence']}"]
    lines += [
        "",
        f"**Decision needed from @Konan** - reply `approve {p['proposal_id']}` or "
        f"`reject {p['proposal_id']} <reason>`, or react on this message.",
        "_No applier exists yet (Phase 3 is unbuilt). Approval records the decision; it does not write._",
    ]
    return "\n".join(lines)


def validate_proposal(p: dict) -> None:
    for key in ("proposal_id", "title", "tier", "target"):
        if not p.get(key):
            raise EmitError(f"proposal rejected at intake: missing '{key}'")
    if p["tier"] not in TIERS:
        raise EmitError(f"proposal rejected at intake: tier must be one of {TIERS}")
    if p["tier"] == "T3":
        raise EmitError(
            "proposal rejected at intake: T3 is human-only and must never be "
            "automated - this surface has no write path to it by design"
        )
    if p["tier"] == "T2" and not (p.get("approver") or "").strip():
        raise EmitError("proposal rejected at intake: T2 requires a named human approver")
    just = p.get("expected_improvement")
    if not isinstance(just, dict):
        raise EmitError(
            "proposal rejected at intake: expected_improvement block is mandatory"
        )
    reg = load_registry()
    for field in reg["required_justification_fields"]:
        value = just.get(field)
        if not isinstance(value, str) or not value.strip():
            raise EmitError(
                f"proposal rejected at intake: expected_improvement.{field} is empty "
                "(a restatement of the diff is not a mechanism)"
            )


def cmd_report(args) -> int:
    reg = load_registry()
    if args.body_file:
        body = Path(args.body_file).read_text()
    else:
        body = args.body or ""
    if not body.strip():
        raise EmitError("report needs --body or --body-file with content")
    text = f"**LOOP REPORT - {args.title}**\n\n{body}"
    if args.dry_run:
        print(json.dumps({"thread_id": reg["thread_id"], "text": text}, indent=1))
        return 0
    ids = send(reg["thread_id"], text, bot_token())
    append_ledger(
        Path(reg["ledger"]),
        {
            "event": "report",
            "ts": now_iso(),
            "title": args.title,
            "thread_id": reg["thread_id"],
            "message_ids": ids,
        },
    )
    print(f"posted report to thread {reg['thread_id']}: {ids}")
    return 0


def cmd_propose(args) -> int:
    reg = load_registry()
    with Path(args.file).open() as fh:
        p = json.load(fh)
    validate_proposal(p)
    rows = load_ledger(Path(reg["ledger"]))
    if p["proposal_id"] in proposal_state(rows):
        raise EmitError(f"proposal id already used: {p['proposal_id']}")
    text = render_proposal(p)
    if args.dry_run:
        print(json.dumps({"thread_id": reg["thread_id"], "text": text}, indent=1))
        return 0
    ids = send(reg["thread_id"], text, bot_token())
    append_ledger(
        Path(reg["ledger"]),
        {
            "event": "proposal",
            "ts": now_iso(),
            "proposal_id": p["proposal_id"],
            "title": p["title"],
            "tier": p["tier"],
            "target": p["target"],
            "approver": p.get("approver"),
            "expected_improvement": p["expected_improvement"],
            "thread_id": reg["thread_id"],
            "message_ids": ids,
        },
    )
    print(f"posted proposal {p['proposal_id']} to thread {reg['thread_id']}: {ids}")
    return 0


def cmd_decide(args) -> int:
    reg = load_registry()
    if args.decision not in DECISIONS:
        raise EmitError(f"decision must be one of {DECISIONS}")
    ledger = Path(reg["ledger"])
    state = proposal_state(load_ledger(ledger))
    if args.id not in state:
        raise EmitError(f"unknown proposal id: {args.id}")
    if state[args.id]["status"] in DECISIONS:
        raise EmitError(
            f"proposal {args.id} already decided ({state[args.id]['status']}); "
            "the ledger is append-only - raise a new proposal id instead"
        )
    record = {
        "event": "decision",
        "ts": now_iso(),
        "proposal_id": args.id,
        "decision": args.decision,
        "by": args.by,
        "reason": args.reason or "",
    }
    text = (
        f"**DECISION - `{args.id}`: {args.decision.upper()}** by {args.by}"
        + (f"\nreason: {args.reason}" if args.reason else "")
        + "\n_recorded in the append-only loop ledger_"
    )
    if args.dry_run:
        print(json.dumps({"record": record, "text": text}, indent=1))
        return 0
    append_ledger(ledger, record)
    ids = send(reg["thread_id"], text, bot_token())
    append_ledger(
        ledger,
        {"event": "decision_announced", "ts": now_iso(), "proposal_id": args.id,
         "message_ids": ids},
    )
    print(f"recorded {args.decision} for {args.id}")
    return 0


def cmd_status(args) -> int:
    reg = load_registry()
    state = proposal_state(load_ledger(Path(reg["ledger"])))
    print(f"thread     : {reg['thread_name']} ({reg['thread_id']}) in #{reg['channel_name']}")
    print(f"ledger     : {reg['ledger']}")
    print(f"approver   : {reg['approval']['approver']} (mode {reg['approval']['mode']})")
    if not state:
        print("proposals  : none yet")
        return 0
    print(f"proposals  : {len(state)}")
    for pid in sorted(state):
        entry = state[pid]
        print(f"  {pid} [{entry.get('tier')}] {entry['status']} -> {entry.get('target')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Recursive-loop reporting + approval emitter")
    sub = ap.add_subparsers(dest="cmd", required=True)

    rep = sub.add_parser("report", help="post a loop report to the registered thread")
    rep.add_argument("--title", required=True)
    rep.add_argument("--body")
    rep.add_argument("--body-file")
    rep.add_argument("--dry-run", action="store_true")
    rep.set_defaults(func=cmd_report)

    prop = sub.add_parser("propose", help="post a proposal (justification block mandatory)")
    prop.add_argument("--file", required=True)
    prop.add_argument("--dry-run", action="store_true")
    prop.set_defaults(func=cmd_propose)

    dec = sub.add_parser("decide", help="record Konan's decision against a proposal id")
    dec.add_argument("--id", required=True)
    dec.add_argument("--decision", required=True)
    dec.add_argument("--reason")
    dec.add_argument("--by", default="konan")
    dec.add_argument("--dry-run", action="store_true")
    dec.set_defaults(func=cmd_decide)

    st = sub.add_parser("status", help="show the registered surface and open proposals")
    st.set_defaults(func=cmd_status)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except EmitError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
