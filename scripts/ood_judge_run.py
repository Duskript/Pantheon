#!/usr/bin/env python3
"""Run the independent judge over the OOD vault and emit the disagreement set.

JUDGE: minimax-m3 (MiniMax — a different family from the extractor's
deepseek-v4.1-flash, so the verdicts are not self-agreement). Chosen by measuring
consumption against the opencode-go allowance: 354 tokens/call at 1.4s versus
minimax-m2.5's 804 at 11.7s and glm-5.2's 532 at 6.8s.

WHAT IT DOES
------------
1. Reads the frozen vault (read-only).
2. Asks the judge, in batches, for a REAL|NOISE verdict per item, WITH the source
   excerpt where one exists — so it checks grounding, not mere plausibility.
3. Compares each verdict against the extractor's own self-reported `confidence`.
4. Emits the DISAGREEMENT SET: items where the judge and the extractor differ.
   Those are what a human reviews. Reviewing all 200 would be wasteful; the
   contested items are where a gameable metric hides.

THE EXTRACTOR'S CONFIDENCE IS WEAK, AND THAT IS THE POINT
--------------------------------------------------------
`confidence` is produced by the same LLM call that produced the extraction
(`l2_llm.py`: `float(e.get("confidence", 0.7))`, defaulting to 0.7 when absent).
It is self-assessment, not evidence. Its job here is only to define "contested" —
it cannot be the label.

Usage:
    python3 scripts/ood_judge_run.py                 # judge the vault, write results
    python3 scripts/ood_judge_run.py --limit 24      # a cheap partial run
"""
from __future__ import annotations

import argparse
import json
import re
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("ood-judge")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib.ichor.llm import resolve_provider_credentials  # noqa: E402

DEFAULT_VAULT = Path.home() / ".hermes" / "ichor" / "ood-vault"
JUDGE_MODEL = "minimax-m3"
BATCH = 8

# The extractor's self-reported confidence, above which a NOISE verdict from the
# judge counts as a real disagreement rather than noise-in-the-noise.
CONFIDENT = 0.7


def _judge_call(prompt: str, model: str, key: str, base: str, timeout: int = 180) -> tuple[str, dict]:
    payload = json.dumps({
        "model": model, "temperature": 0, "max_tokens": 2500,
        "messages": [{"role": "user", "content": prompt}],
    })
    r = subprocess.run(
        ["curl", "-sS", "-X", "POST", f"{base.rstrip('/')}/chat/completions",
         "-H", f"Authorization: Bearer {key}",
         "-H", "Content-Type: application/json",
         # opencode-go rejects requests without this: HTTP 400 MissingSessionID.
         "-H", "x-opencode-session: hermes-ood-judge",
         "-d", payload],
        capture_output=True, text=True, timeout=timeout,
    )
    try:
        d = json.loads(r.stdout)
    except Exception:
        return "", {"error": f"unparseable: {r.stdout[:120]}{r.stderr[:120]}"}
    if "error" in d:
        return "", {"error": str(d["error"].get("type"))}
    msg = (d.get("choices") or [{}])[0].get("message") or {}
    return (msg.get("content") or "").strip(), d.get("usage", {})


def _build_prompt(batch: list[dict]) -> str:
    lines = [
        "You are quality-labelling extracted knowledge-graph items for an audit.",
        "",
        "For EACH numbered item decide whether it is:",
        "  REAL  - a genuine named concept worth storing in a knowledge graph",
        "  NOISE - a file path, license string, log line, sentence fragment cut off",
        "          mid-word, or anything that is not a real named concept",
        "",
        "Where a SOURCE excerpt is given, use it: an item is only REAL if the source",
        "actually supports it as a concept. An item with no source and no clear",
        "concept identity is NOISE.",
        "",
        "Answer with EXACTLY one line per item, no preamble:",
        "<n>. REAL|NOISE - <max 8 words why>",
        "",
    ]
    for i, it in enumerate(batch):
        lines.append(f"--- item {i} ---")
        lines.append(f"kind: {it['kind']}")
        lines.append(f"text: {it['text']!r}")
        if it.get("source_excerpt"):
            lines.append(f"SOURCE: {it['source_excerpt'][:600]!r}")
        else:
            lines.append("SOURCE: (none available)")
        lines.append("")
    return "\n".join(lines)


def _strip_reasoning(txt: str) -> str:
    """Drop a leading ` thinking...</think>` block before parsing.

    minimax-m3 (and other reasoning models) emit their scratchpad first, in a
    DIFFERENT format — verdict at the END of each sentence ("0. \"x\" - This is a
    file path. NOISE.") — and only then the answer in the requested format. Parsing
    the raw text matches the scratchpad first and yields garbage: it turned 14 of 16
    correct verdicts into UNPARSED. Stripping the block first is the fix.
    """
    # The delimiters are LITERAL `<think>` / `</think>` tags — verified by reading
    # the codepoints of a live response (0x3C 't' 'h' 'i' 'n' 'k' 0x3E). An earlier
    # guess of `<!--?think-->` matched nothing and silently parsed 0 of 8 items.
    m = re.search(r"(?is)</think\s*>", txt)
    if m:
        return txt[m.end():].strip()
    # `<think>` with no closer means the answer was truncated — no verdicts exist.
    if re.search(r"(?is)<think\s*>", txt):
        return ""
    return txt.strip()


def _parse(txt: str, n: int) -> dict[int, tuple[str, str]]:
    out: dict[int, tuple[str, str]] = {}
    txt = _strip_reasoning(txt)
    for line in txt.splitlines():
        line = line.strip().lstrip("*# ").strip()
        # Match the index by REGEX on the line's prefix, and track whether THIS line
        # matched. The earlier version broke out of the index loop on `i in out`,
        # which is true for any index set by an EARLIER line — so every line after
        # the first broke at i=0 and only one verdict ever parsed.
        m = re.match(r"^(\d{1,3})\s*[.):]\s*(.+)$", line)
        if not m:
            continue
        idx = int(m.group(1))
        if not (0 <= idx < n):
            continue
        rest = m.group(2).strip()
        up = rest.upper()
        if up.startswith("REAL"):
            out[idx] = ("REAL", rest[4:].strip(" -:"))
        elif up.startswith("NOISE"):
            out[idx] = ("NOISE", rest[5:].strip(" -:"))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Run the independent judge over the OOD vault")
    ap.add_argument("--vault", default=str(DEFAULT_VAULT))
    ap.add_argument("--model", default=JUDGE_MODEL)
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N items")
    args = ap.parse_args()

    vault = Path(args.vault).expanduser()
    items = [json.loads(l) for l in (vault / "items.jsonl").read_text().splitlines()]
    if args.limit:
        items = items[:args.limit]
    logger.info("judging %d items with %s", len(items), args.model)

    key, base = resolve_provider_credentials("opencode-go")
    if not key:
        logger.error("no credential for opencode-go")
        return 2

    results: list[dict] = []
    tok_in = tok_out = calls = 0
    t_start = time.time()

    for s in range(0, len(items), BATCH):
        batch = items[s:s + BATCH]
        txt, usage = _judge_call(_build_prompt(batch), args.model, key, base)
        calls += 1
        tok_in += usage.get("prompt_tokens") or 0
        tok_out += usage.get("completion_tokens") or 0
        if usage.get("error"):
            logger.warning("batch %d failed: %s", s // BATCH, usage["error"])
        verdicts = _parse(txt, len(batch))
        for i, it in enumerate(batch):
            v, why = verdicts.get(i, ("UNPARSED", ""))
            conf = it.get("extractor_confidence")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            results.append({**it, "judge_verdict": v, "judge_reason": why,
                            "extractor_confidence_f": conf_f})
        logger.info("  %d/%d judged", min(s + BATCH, len(items)), len(items))

    elapsed = time.time() - t_start

    # ── the disagreement set: judge says NOISE but the extractor was confident,
    #    or judge says REAL but the extractor was not. Those are the contested
    #    items a human should review.
    contested = [
        r for r in results
        if (r["judge_verdict"] == "NOISE" and (r["extractor_confidence_f"] or 0) >= CONFIDENT)
        or (r["judge_verdict"] == "REAL" and (r["extractor_confidence_f"] or 1) < CONFIDENT)
    ]
    unparsed = [r for r in results if r["judge_verdict"] == "UNPARSED"]

    (vault / "judge_results.jsonl").write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in results) + "\n")
    summary = {
        "judged_at": datetime.now(timezone.utc).isoformat(),
        "judge_model": args.model,
        "n_judged": len(results),
        "calls": calls,
        "tokens_in": tok_in, "tokens_out": tok_out,
        "seconds": round(elapsed, 1),
        "verdicts": {v: sum(1 for r in results if r["judge_verdict"] == v)
                     for v in sorted({r["judge_verdict"] for r in results})},
        "contested": len(contested),
        "unparsed": len(unparsed),
        "contested_ids": [r["item_id"] for r in contested],
    }
    (vault / "judge_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    logger.info("done in %.0fs | %d calls | tokens %d/%d", elapsed, calls, tok_in, tok_out)
    logger.info("  verdicts  : %s", summary["verdicts"])
    logger.info("  contested : %d of %d  (these are what a human reviews)",
                len(contested), len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
