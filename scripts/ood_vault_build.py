#!/usr/bin/env python3
"""Build the OOD label vault for the Phase 2 evaluator.

WHY THIS EXISTS
---------------
The L2 extractor is currently graded on **yield** — entities produced per event.
That metric pays the extractor to hallucinate: an extractor that emits
`LICENSE.txt`, `AL2.0` and `META-INF` as entities scores HIGHER than one that
emits nothing. Measured on the live DB, 15.3% of 23,859 entities (3,650) are
sentence-fragment shaped, and the most recent eight include file paths and
license strings.

To grade on **precision** instead, someone must say which outputs are real. That
judgement is a *label*. This script builds the frozen set of items to be labelled.

WHY "OOD" (out-of-distribution)
-------------------------------
If the labelled set is drawn from the same slice the extractor is currently
chewing through, the labels measure memorisation of that slice rather than
extraction quality. So the vault:
  * spans the WHOLE corpus, not the recent tail;
  * is stratified to contain junk AND good items, so the labels can discriminate
    (a set of 200 good items cannot detect a precision regression);
  * is frozen and content-hashed, so later edits are detectable.

INDEPENDENCE
------------
The labels must come from a source independent of the extractor. The extractor
runs on deepseek-v4.1-flash; the judge is **minimax-m2.5** (MiniMax, a different
family), chosen by measurement — 5/5 on a probe set, see the vault manifest.

THE VAULT IS WRITE-ONLY
-----------------------
Nothing in the proposal path may read it. A proposer that can see the labels can
optimise against them, which converts a held-out set into a training set. Enforced
by `tests/test_ood_vault_isolation.py`, not by convention.

Usage:
    python3 scripts/ood_vault_build.py --n 200
    python3 scripts/ood_vault_build.py --n 200 --out ~/.hermes/ichor/ood-vault
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("ood-vault")

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# The vec0 extension is unavailable to this interpreter, so `PRAGMA table_info` on
# the embedding table raises `no such module: vec0`. Skip those tables BY NAME —
# a crash mid-scan is how a stale result gets printed from a dead script.
_VEC_TABLES = {"event_embeddings", "vec_events", "entity_embeddings"}

DEFAULT_DB = Path.home() / ".hermes" / "ichor.db"
DEFAULT_OUT = Path.home() / ".hermes" / "ichor" / "ood-vault"

# Stratification buckets. The point is that a label set containing ONLY clean
# items cannot detect the failure we are trying to detect.
JUNK_SHAPED = (
    "LENGTH(name) > 45",
    "name LIKE '%/%'",
    "name LIKE '%\\\\%'",
    "name LIKE '%.md'",
    "name LIKE '%.json'",
    "name LIKE '%.py'",
    "name LIKE '%.txt'",
    "name LIKE '% 2x:%'",
    "name LIKE '% 3x:%'",
    "name LIKE '%\"%'",
    "name LIKE '%(%'",
)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _source_text_for_relationship(conn: sqlite3.Connection, rel_id: int, limit: int = 700) -> str:
    """Ground a relationship on its OWN recorded provenance.

    `relationships.source_ref` is populated for ~35,810 rows and holds the text the
    relationship was extracted from. The builder previously used the SOURCE ENTITY's
    name (`_source_text(conn, sn)`), which produced an excerpt of whatever text
    mentions that entity — e.g. for `(Konan) --[related]--> (Ledger)` it returned
    ledger-unrelated text containing "Konan", so the judge correctly reported the
    relation as ungrounded. The excerpt was wrong, not the verdict.
    """
    row = conn.execute("SELECT source_ref FROM relationships WHERE id = ?", (rel_id,)).fetchone()
    if not row or not row[0]:
        return ""
    return str(row[0])[:limit]


def _source_text(conn: sqlite3.Connection, name: str, limit: int = 700) -> str:
    """Grounding excerpt for an item: the events the name actually occurs in.

    NOT via `entity_facts.source_event_ids` — that link exists for only ~581 of
    23,859 entities (and `linked_warm_ids` for 15), so keying on it left 197 of 200
    items ungrounded. `cold_events.raw_text` is populated for 79,419 of 79,530
    events, and an occurrence search over it grounds almost everything.

    The excerpt is centred on the match rather than taken from the head of the
    event, so the judge sees the CONTEXT the extractor was working from.
    """
    if not name or len(name) < 3:
        return ""
    rows = conn.execute(
        "SELECT raw_text FROM cold_events WHERE raw_text LIKE ? "
        "ORDER BY id DESC LIMIT 3",
        (f"%{name}%",),
    ).fetchall()
    if not rows:
        return ""
    parts = []
    for (raw,) in rows:
        if not raw:
            continue
        i = raw.find(name)
        start = max(0, i - 260)
        parts.append(raw[start:start + 420])
    return "\n---\n".join(parts)[:limit]


def _event_ids_for_entity(conn: sqlite3.Connection, entity_id: int) -> list[str]:
    row = conn.execute(
        "SELECT value FROM entity_facts WHERE entity_id = ? AND key = 'source_event_ids' LIMIT 1",
        (entity_id,),
    ).fetchone()
    if not row or not row[0]:
        return []
    try:
        return json.loads(row[0])
    except (ValueError, TypeError):
        return []


def sample_items(conn: sqlite3.Connection, n: int, seed: int = 20260923) -> list[dict]:
    """Stratified sample: half junk-shaped, half clean, spanning the whole corpus."""
    rng = random.Random(seed)
    rel_budget = max(20, n // 5)
    per_bucket = max(1, (n - rel_budget) // 2)

    junk_where = " OR ".join(JUNK_SHAPED)
    buckets = {
        "junk_shaped": f"SELECT id, name, confidence, created_at FROM entities WHERE ({junk_where})",
        "clean": (f"SELECT id, name, confidence, created_at FROM entities "
                  f"WHERE NOT ({junk_where}) AND LENGTH(name) BETWEEN 3 AND 28"),
    }

    items: list[dict] = []
    for bucket, q in buckets.items():
        rows = list(conn.execute(q))
        if not rows:
            continue
        take = min(per_bucket, len(rows))
        for eid, name, conf, created in rng.sample(rows, take):
            items.append({
                "item_id": f"ent:{eid}",
                "kind": "entity",
                "text": name,
                "extractor_confidence": conf,
                "created_at": created,
                "bucket": bucket,
                "source_event_ids": _event_ids_for_entity(conn, eid),
                "source_excerpt": _source_text(conn, name),
            })

    # Relationships too — a label set of entities only cannot see relation noise.
    rels = list(conn.execute("""
        SELECT r.id, s.name, t.name, r.confidence
        FROM relationships r
        JOIN entities s ON s.id = r.source_id
        JOIN entities t ON t.id = r.target_id
    """))
    if rels:
        # Budget OUT of `n` rather than taking the remainder — the remainder was 0
        # because the two entity buckets already filled `n`, so the vault contained
        # 200 entities and ZERO relationships. A label set with no relations cannot
        # see relation-level noise at all.
        take = max(20, n // 5)
        for rid, sn, tn, conf in rng.sample(rels, min(take, len(rels))):
            items.append({
                "item_id": f"rel:{rid}",
                "kind": "relationship",
                "text": f"({sn}) --[related]--> ({tn})",
                "extractor_confidence": conf,
                "created_at": None,
                "bucket": "relationship",
                "source_event_ids": [],
                # Ground on the relationship's OWN provenance, not the source entity's
                # name — the latter cannot mention the object and makes the judge
                # correctly report "not grounded" against the wrong excerpt.
                "source_excerpt": (_source_text_for_relationship(conn, rid)
                                   or _source_text(conn, sn)),
            })

    rng.shuffle(items)
    return items[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the OOD label vault")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--seed", type=int, default=20260923)
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing frozen vault (changes the hash)")
    args = ap.parse_args()

    out = Path(args.out).expanduser()
    manifest_path = out / "manifest.json"
    if manifest_path.exists() and not args.force:
        logger.error("vault already frozen at %s — refusing to overwrite (--force to replace)", out)
        return 2

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    items = sample_items(conn, args.n, args.seed)
    conn.close()

    out.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(i, sort_keys=True) for i in items) + "\n"
    (out / "items.jsonl").write_text(body)
    digest = _sha256_bytes(body.encode())

    grounded = sum(1 for i in items if i["source_excerpt"])
    manifest = {
        "vault": "ood-label-vault",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "n_items": len(items),
        "content_sha256": digest,
        "seed": args.seed,
        "db": str(args.db),
        "buckets": {b: sum(1 for i in items if i["bucket"] == b)
                    for b in sorted({i["bucket"] for i in items})},
        "kinds": {k: sum(1 for i in items if i["kind"] == k)
                  for k in sorted({i["kind"] for i in items})},
        "grounded_items": grounded,
        "judge_model": "minimax-m3",
        "judge_rationale": (
            "MiniMax, a DIFFERENT family from the extractor's deepseek-v4.1-flash, so "
            "the labels are not self-agreement. Chosen by measurement against the "
            "opencode-go quota (flat $10/mo subscription with a limited allowance, so "
            "per-model consumption is the real cost): 12 calls per model on an identical "
            "realistic judge prompt gave minimax-m3 354 tokens/call at 1.4s, versus "
            "minimax-m2.5 804 tokens/call at 11.7s and glm-5.2 532 at 6.8s. M3 is ~2.3x "
            "cheaper in allowance and ~8x faster, and is on opencode-go's official "
            "supported list (m2.5 is not). 36 calls moved the rolling quota 1 point, so "
            "a 200-item run is roughly 5-6% of a rolling window."
        ),
        "write_only": True,
        "notes": [
            "Nothing in the proposal path may read this directory — a proposer that "
            "can see the labels can optimise against them.",
            "Stratified to include junk-shaped AND clean items: a label set of only "
            "clean items cannot detect a precision regression.",
            "source_excerpt is the grounding text from cold_events.raw_text so the "
            "judge checks GROUNDING, not mere plausibility.",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    logger.info("vault frozen: %d items -> %s", len(items), out)
    logger.info("  content sha256 : %s", digest)
    logger.info("  buckets        : %s", manifest["buckets"])
    logger.info("  grounded       : %d/%d carry source text", grounded, len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
