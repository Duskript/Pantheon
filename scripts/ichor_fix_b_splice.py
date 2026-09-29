#!/usr/bin/env python3
"""Fix B splicer — stop decay from being a one-way door.

`dream.py` halves a relationship's `weight` every 7 days and archives below 0.1;
`_relationships_to_decay` selects `WHERE weight > 0`; and **nothing anywhere
restores weight**.  Result: 26,952 of 27,096 edges sat at `weight = 0.0` with
provenance `dream_decay_archived` and were permanently unreachable by any
weight-filtered query.  Only 131 edges carried `provenance = 'llm'`, so
re-learning could never outpace decay.

Preferred remedy from the handoff: **reinforce-on-traverse** — bump `weight`
toward 1.0 whenever an edge is actually returned into a turn's context.

Two changes here:
  1. `_query_graph` now carries the edge triple on each result (`"edge"`), so
     reinforcement can target the exact row instead of guessing from an id.
  2. `prefetch` reinforces only the graph entries that survived fusion into the
     injected context -- a walk that was fetched and then dropped is not a
     recall signal.

Anchored replacements, assert-verified, `ast.parse`-checked.  Idempotent.
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

TARGET = Path("/home/konan/.hermes/plugins/ichor/provider.py")

EDITS: list[tuple[str, str, str]] = [
    (
        "t3-constants",
        "# Memo for the T3 alias->id lookup.  Caches misses too: a miss is the\n"
        "# expensive case, not the cheap one.\n"
        "_T3_RESOLVE_CACHE_MAX = 256\n",
        "# Memo for the T3 alias->id lookup.  Caches misses too: a miss is the\n"
        "# expensive case, not the cheap one.\n"
        "_T3_RESOLVE_CACHE_MAX = 256\n"
        "\n"
        "# ── Fix B: reinforcement-on-traverse ──────────────────────────────────\n"
        "# Each surfaced edge moves this fraction of the remaining distance to 1.0.\n"
        "# 0.25 => a zeroed edge reaches ~0.68 after four real recalls, which puts\n"
        "# it back inside the decay window instead of staying a permanent zero.\n"
        "_REINFORCE_ALPHA = 0.25\n"
        "_REINFORCE_MAX_PER_TURN = 12\n",
    ),
    (
        "result-carries-edge",
        "                    results.append({\n"
        "                        \"id\": f\"graph:{other_id}:{rel}\",\n"
        "                        \"score\": float(edge.get(\"confidence\") or 0.0),\n"
        "                        \"backend\": \"graph\",\n"
        "                        \"type\": other.get(\"type\", \"\"),\n"
        "                        \"title\": f\"{anchor_name} --{rel}--> {other_name}\",\n"
        "                        \"snippet\": snippet[:300],\n"
        "                        \"direction\": \"unknown\",\n"
        "                    })\n",
        "                    results.append({\n"
        "                        \"id\": f\"graph:{other_id}:{rel}\",\n"
        "                        \"score\": float(edge.get(\"confidence\") or 0.0),\n"
        "                        \"backend\": \"graph\",\n"
        "                        \"type\": other.get(\"type\", \"\"),\n"
        "                        \"title\": f\"{anchor_name} --{rel}--> {other_name}\",\n"
        "                        \"snippet\": snippet[:300],\n"
        "                        \"direction\": \"unknown\",\n"
        "                        # Fix B: the exact row to reinforce if this hit\n"
        "                        # survives fusion into the injected context.\n"
        "                        \"edge\": {\n"
        "                            \"source\": int(edge.get(\"source\") or 0),\n"
        "                            \"target\": int(edge.get(\"target\") or 0),\n"
        "                            \"type\": rel,\n"
        "                        },\n"
        "                    })\n",
    ),
    (
        "reinforce-on-inject",
        "        # Fuse + cache\n"
        "        fused = self._fuse_results(all_results)\n",
        "        # Fuse + cache\n"
        "        fused = self._fuse_results(all_results)\n"
        "\n"
        "        # Fix B: only the entries that actually reach the injected context\n"
        "        # count as a recall.  _format_context caps at 5, so reinforce that\n"
        "        # same head of the list -- otherwise a fetched-then-dropped walk\n"
        "        # would inflate edges that were never seen.\n"
        "        self._reinforce_edges(fused[:5])\n",
    ),
]

NEW_REINFORCE = '''    def _reinforce_edges(self, entries: List[Dict]) -> int:
        """Fix B: move surfaced edges' `weight` toward 1.0.  Returns rows touched.

        Decay is otherwise a one-way door.  `dream.py` halves `weight` every 7
        days (archive threshold 0.1, so ~23 days to zero), `_relationships_to_decay`
        selects `WHERE weight > 0` -- so a zeroed edge is never revisited -- and
        nothing in the codebase restores weight.  26,952 of 27,096 edges had
        reached 0.0 and become permanently invisible to any weight-filtered query.

        An edge that keeps being recalled should not decay out of existence.
        Reinforcement uses an exponential approach to 1.0
        (`w += (1 - w) * _REINFORCE_ALPHA`) so it is self-limiting and can never
        overshoot.  Provenance is marked `traverse_reinforced` so reinforced
        edges stay countable and auditable against the decay selector.

        Best-effort: a failure here must never break a turn.
        """
        triples = []
        for entry in entries or []:
            if entry.get("backend") != "graph":
                continue
            edge = entry.get("edge") or {}
            src, tgt, rel = edge.get("source"), edge.get("target"), edge.get("type")
            if not src or not tgt or not rel:
                continue
            triples.append((src, tgt, rel))
        if not triples:
            return 0

        touched = 0
        try:
            conn = sqlite3.connect(str(_ICHOR_DB))
            try:
                for src, tgt, rel in triples[:_REINFORCE_MAX_PER_TURN]:
                    cur = conn.execute(
                        "UPDATE relationships "
                        "   SET weight = weight + (1.0 - weight) * ?, "
                        "       provenance = 'traverse_reinforced', "
                        "       updated_at = datetime('now') "
                        " WHERE source_id = ? AND target_id = ? AND type_id = ? "
                        "   AND weight < 1.0",
                        (_REINFORCE_ALPHA, src, tgt, rel),
                    )
                    touched += cur.rowcount
                conn.commit()
            finally:
                conn.close()
            if touched:
                logger.debug("Fix B: reinforced %d edge(s)", touched)
        except Exception as e:
            logger.debug("Fix B reinforcement failed (non-fatal): %s", e)
        return touched

'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "_reinforce_edges" in src:
        print("ALREADY APPLIED — no change")
        return 0

    backup = TARGET.with_suffix(".py.bak.fixB-20260917")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
    print("backup:", backup)

    for label, old, new in EDITS:
        count = src.count(old)
        if count != 1:
            print(f"FAIL[{label}]: anchor found {count} times (need exactly 1)")
            return 1
        src = src.replace(old, new, 1)
        print(f"OK  [{label}]")

    anchor = "    def _resolve_entity_id(self, name: str) -> Optional[int]:"
    if src.count(anchor) != 1:
        print("FAIL: _resolve_entity_id anchor not unique")
        return 1
    src = src.replace(anchor, NEW_REINFORCE + anchor, 1)
    print("OK  [insert _reinforce_edges]")

    try:
        ast.parse(src)
    except SyntaxError as e:
        print("FAIL: result does not parse:", e)
        return 1

    TARGET.write_text(src, encoding="utf-8")
    print("WROTE", TARGET, len(src), "bytes; ast.parse OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
