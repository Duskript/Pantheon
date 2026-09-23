"""Ichor mistake ledger — instance-attributed records of things that went wrong.

Why this exists
---------------
Pantheon already stores corrections as memory events (`category='correction'`;
2,377 such rows in `warm_entities` at the time of writing) and already detects
contradictions on write. What it could not do was answer three questions:

  1. **Which instance was wrong?** A correction row says "X is actually Y". It
     does not point at the specific output, turn, or message that got it wrong.
  2. **What revealed it?** Nothing linked a claim made in turn N to the turn that
     showed it was false.
  3. **Was it ever learned from?** There was no outcome field, so nothing could
     tell whether a prevention worked — the same gap that leaves the Dojo's
     crystallizations with no recorded outcome.

This module supplies exactly those three things and nothing else. It is the
outcome signal the rest of the self-improvement plan was missing: without a
record of what failed, proposals cannot be ranked, preventions cannot be
verified, and any "improvement" loop is optimizing noise.

Design rules
------------
- **Attribution is mandatory.** A record without an identifiable offending
  instance is rejected at intake. An un-attributed "a mistake happened" note is
  not useful for learning and would poison the recurrence counts.
- **Append-only.** Records are never rewritten in place; state transitions are
  appended as separate events carrying the same `mistake_id`. The current state
  of a mistake is derived by folding its events.
- **Plain JSONL.** No database, so it can be read by anything, diffed, and
  grepped. The ledger lives outside the agent-writable skill tree at
  `~/.hermes/pantheon/mistake-ledger.jsonl` so it is a file of record.

Usage
-----
    from lib.ichor.mistakes import record_mistake, resolve_mistake, open_mistakes

    rec = record_mistake(
        god="hermes",
        claim="I reported the extract step as healthy; it had failed 456 times.",
        category="wrong_fact",
        detected_by="human",
        quote="that one is wrong, check the journal",
        correction="extract was skipping on a missing credential",
        offending_message_id="1552...",
        revealing_message_id="1552...",
    )
    resolve_mistake(rec["mistake_id"], state="learned",
                    prevention="assert effect, not exit code")

CLI
---
    python3 -m lib.ichor.mistakes stats
    python3 -m lib.ichor.mistakes list --state open
    python3 -m lib.ichor.mistakes record --god hermes --claim "..." \\
        --category wrong_fact --detected-by human --quote "..."
    python3 -m lib.ichor.mistakes resolve <mistake_id> --state learned \\
        --prevention "..."
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_HOME = Path.home()
LEDGER_PATH = Path(
    os.environ.get("ICHOR_MISTAKE_LEDGER", str(_HOME / ".hermes" / "pantheon" / "mistake-ledger.jsonl"))
)

#: A record must name one of these. Free-text categories defeat the purpose of
#: counting recurrence, which is the only signal that a prevention is needed.
CATEGORIES = (
    "wrong_fact",        # asserted something false
    "wrong_command",     # ran or recommended a command that did not do the job
    "broken_code",       # shipped code that does not work as claimed
    "bad_plan",          # a plan that could not achieve the stated goal
    "hallucination",     # invented a file, line, number, or API
    "misread_request",   # solved a different problem than the one asked
    "missed_constraint", # ignored something the user had already specified
    "false_success",     # reported success for work that did not happen
    "other",
)

#: Who or what caught it. `human` is the highest-precision signal and the only
#: one that requires a revealing turn.
# `peer` exists because a peer god catching an error is neither human nor
# self nor tool, and it is currently the most common real case. Without it a
# cross-god catch has to be filed as "human", which flattens attribution in
# the one artifact whose purpose is attribution. Pair it with detected_by_god.
DETECTORS = ("human", "self", "tool", "peer")

#: Lifecycle. `open` = recorded, not yet acted on. `learned` = a prevention has
#: been written. `verified` = it has not recurred since. `wontfix` = accepted.
STATES = ("open", "learned", "verified", "wontfix")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(god: str, claim: str, ts: str) -> str:
    """Identifier for ONE OCCURRENCE of a mistake.

    Deliberately per-instance, not content-addressed by claim. An earlier
    revision hashed only the date, so three separate occurrences of the same
    mistake on one day folded into a single record — which silently destroyed
    the recurrence count. Recurrence is the signal that decides whether a
    prevention is warranted, so distinct instances MUST stay distinct.

    `ts` carries microseconds, so identical claims recorded in the same
    microsecond (impossible in practice) would be the only collision.
    """
    digest = hashlib.sha256(f"{god}|{claim}|{ts}".encode("utf-8")).hexdigest()
    return "mis_" + digest[:16]


def _append(entry: Dict[str, Any], path: Optional[Path] = None) -> Dict[str, Any]:
    p = Path(path) if path is not None else LEDGER_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def validate(record: Dict[str, Any]) -> List[str]:
    """Return a list of reasons the record is not acceptable. Empty = valid.

    Kept as a pure function so callers (and tests) can check a prospective
    record without writing it.
    """
    problems: List[str] = []

    if not str(record.get("god") or "").strip():
        problems.append("god is required")

    claim = str(record.get("claim") or "").strip()
    if not claim:
        problems.append("claim is required — what exactly was wrong")
    elif len(claim) < 10:
        problems.append("claim is too short to be actionable (<10 chars)")

    category = str(record.get("category") or "")
    if category not in CATEGORIES:
        problems.append(f"category must be one of {CATEGORIES}, got {category!r}")

    detected_by = str(record.get("detected_by") or "")
    if detected_by not in DETECTORS:
        problems.append(f"detected_by must be one of {DETECTORS}, got {detected_by!r}")

    # A human-caught mistake must name the turn that revealed it, otherwise the
    # record cannot be traced back to the conversation — which is the whole
    # point of instance attribution.
    if detected_by == "human" and not str(record.get("quote") or "").strip():
        problems.append("detected_by='human' requires 'quote' (the correcting turn)")

    # A peer-caught mistake carries the same evidence burden as a human-caught
    # one: name the turn that revealed it. And it must name WHICH peer, or the
    # cross-god attribution this value exists to enable is still lost.
    if detected_by == "peer":
        if not str(record.get("quote") or "").strip():
            problems.append("detected_by='peer' requires 'quote' (the revealing turn)")
        if not str(record.get("detected_by_god") or "").strip():
            problems.append("detected_by='peer' requires 'detected_by_god' (which peer)")

    # And every record must point at the offending instance.
    if not (record.get("offending_message_id") or record.get("claim")):
        problems.append("an offending instance is required (offending_message_id or claim)")

    return problems


def record_mistake(
    god: str,
    claim: str,
    category: str,
    detected_by: str,
    detected_by_god: str = "",
    quote: str = "",
    correction: str = "",
    offending_message_id: str = "",
    revealing_message_id: str = "",
    session_id: str = "",
    artifact: str = "",
    delta_turns: Optional[int] = None,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append a mistake record. Raises ValueError if it fails validation.

    A record without an identifiable offending instance is rejected — see the
    module docstring on why un-attributed mistakes are worse than none.
    """
    ts = _now()
    record = {
        "event": "recorded",
        "mistake_id": _new_id(god, claim, ts),
        "ts": ts,
        "god": god,
        "session_id": session_id,
        "claim": claim.strip(),
        "category": category,
        "detected_by": detected_by,
        "detected_by_god": detected_by_god,
        "quote": quote.strip(),
        "correction": correction.strip(),
        "offending_message_id": offending_message_id,
        "revealing_message_id": revealing_message_id,
        "artifact": artifact,
        "delta_turns": delta_turns,
        "state": "open",
    }
    problems = validate(record)
    if problems:
        raise ValueError("mistake record rejected: " + "; ".join(problems))
    return _append(record, path)


def resolve_mistake(
    mistake_id: str,
    state: str,
    prevention: str = "",
    prevention_skill: str = "",
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Append a state transition for `mistake_id` (append-only; nothing is rewritten)."""
    if state not in STATES:
        raise ValueError(f"state must be one of {STATES}, got {state!r}")
    if state == "learned" and not prevention.strip():
        raise ValueError(
            "state='learned' requires --prevention: claiming a lesson was learned "
            "without naming the prevention is the exact failure this ledger exists to catch"
        )
    entry = {
        "event": "resolved",
        "ts": _now(),
        "mistake_id": mistake_id,
        "state": state,
        "prevention": prevention.strip(),
        "prevention_skill": prevention_skill.strip(),
    }
    return _append(entry, path)


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


def load_mistakes(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Fold the append-only event stream into one current record per mistake."""
    folded: Dict[str, Dict[str, Any]] = {}
    for ev in load_events(path):
        mid = ev.get("mistake_id")
        if not mid:
            continue
        if ev.get("event") == "recorded":
            folded.setdefault(mid, dict(ev))
        elif ev.get("event") == "resolved" and mid in folded:
            folded[mid]["state"] = ev.get("state", folded[mid].get("state"))
            if ev.get("prevention"):
                folded[mid]["prevention"] = ev["prevention"]
            if ev.get("prevention_skill"):
                folded[mid]["prevention_skill"] = ev["prevention_skill"]
            folded[mid]["resolved_ts"] = ev.get("ts")
    return sorted(folded.values(), key=lambda r: r.get("ts", ""))


def open_mistakes(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    return [m for m in load_mistakes(path) if m.get("state") == "open"]


def recurrence(path: Optional[Path] = None) -> Dict[str, int]:
    """Mistake counts per category.

    This is the signal that decides whether a *prevention* is warranted: a
    category that keeps recurring needs a rule; a one-off does not.
    """
    counts: Dict[str, int] = {}
    for m in load_mistakes(path):
        cat = m.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def stats(path: Optional[Path] = None) -> Dict[str, Any]:
    ms = load_mistakes(path)
    by_state: Dict[str, int] = {}
    for m in ms:
        by_state[m.get("state", "open")] = by_state.get(m.get("state", "open"), 0) + 1
    return {
        "total": len(ms),
        "by_state": by_state,
        "by_category": recurrence(path),
        "by_god": _count_by(ms, "god"),
        "by_detector": _count_by(ms, "detected_by"),
        "ledger_path": str(path or LEDGER_PATH),
    }


def _count_by(records: Iterable[Dict[str, Any]], field: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for r in records:
        key = str(r.get(field) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cmd_record(args: argparse.Namespace) -> int:
    try:
        rec = record_mistake(
            god=args.god, claim=args.claim, category=args.category,
            detected_by=args.detected_by, quote=args.quote or "",
            detected_by_god=getattr(args, "detected_by_god", "") or "",
            correction=args.correction or "",
            offending_message_id=args.offending_message_id or "",
            revealing_message_id=args.revealing_message_id or "",
            session_id=args.session_id or "", artifact=args.artifact or "",
            delta_turns=args.delta_turns,
        )
    except ValueError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2
    print(f"recorded {rec['mistake_id']}  [{rec['category']} via {rec['detected_by']}]")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    try:
        resolve_mistake(args.mistake_id, args.state,
                        prevention=args.prevention or "",
                        prevention_skill=args.prevention_skill or "")
    except ValueError as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 2
    print(f"{args.mistake_id} -> {args.state}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    rows = load_mistakes()
    if args.state:
        rows = [r for r in rows if r.get("state") == args.state]
    if not rows:
        print("(no mistakes recorded)")
        return 0
    for r in rows:
        print(f"{r['mistake_id']}  {r.get('state','?'):8} {r.get('category','?'):16} "
              f"{r.get('god','?'):12} {str(r.get('claim',''))[:70]}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    print(json.dumps(stats(), indent=2))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Ichor mistake ledger (append-only JSONL)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_rec = sub.add_parser("record", help="record a mistake")
    p_rec.add_argument("--god", required=True)
    p_rec.add_argument("--claim", required=True, help="what exactly was wrong")
    p_rec.add_argument("--category", required=True, choices=list(CATEGORIES))
    p_rec.add_argument("--detected-by", required=True, choices=list(DETECTORS))
    p_rec.add_argument("--detected-by-god", default="",
                       help="which god detected it (required when --detected-by peer)")
    p_rec.add_argument("--quote", help="the turn that revealed it (required for human)")
    p_rec.add_argument("--correction", help="the correct form, if known")
    p_rec.add_argument("--offending-message-id")
    p_rec.add_argument("--revealing-message-id")
    p_rec.add_argument("--session-id")
    p_rec.add_argument("--artifact", help="file/command this concerns")
    p_rec.add_argument("--delta-turns", type=int)
    p_rec.set_defaults(func=_cmd_record)

    p_res = sub.add_parser("resolve", help="append a state transition")
    p_res.add_argument("mistake_id")
    p_res.add_argument("--state", required=True, choices=list(STATES))
    p_res.add_argument("--prevention", help="required when --state learned")
    p_res.add_argument("--prevention-skill")
    p_res.set_defaults(func=_cmd_resolve)

    p_ls = sub.add_parser("list", help="list mistakes")
    p_ls.add_argument("--state", choices=list(STATES))
    p_ls.set_defaults(func=_cmd_list)

    p_st = sub.add_parser("stats", help="counts by state/category/god/detector")
    p_st.set_defaults(func=_cmd_stats)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
