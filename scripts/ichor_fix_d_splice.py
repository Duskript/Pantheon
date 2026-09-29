#!/usr/bin/env python3
"""Fix D (zero-LLM half) splicer — stop graph hits rendering as hollow nodes.

14,093 of 18,427 entities (76%) have an empty `summary`, and exactly 1 has
>=200 chars.  `_format_context` renders a graph hit's snippet from `summary`, so
every hit on a summary-less entity fell back to a content-free string.

Two halves to Fix D:
  * this file: derive a compact descriptor from the entity's typed neighbourhood
    at READ time.  No LLM, no writes — so a later semantic backfill can still
    tell an empty `summary` apart from a generated one.
  * the LLM backfill proper: deliberately NOT done here.  There is no existing
    entity-summary backfill tool in the repo and it costs API spend on ~14k
    entities, so it needs an explicit go-ahead.

Anchored replacements, assert-verified, `ast.parse`-checked.  Idempotent.
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

TARGET = Path("/home/konan/.hermes/plugins/ichor/provider.py")

EDIT_OLD = """                    other_name = other.get("name") or f"id={other_id}"
                    snippet = (other.get("summary") or "").strip()
                    if not snippet:
                        snippet = (
                            f"{other.get('type', 'entity')} linked to "
                            f"{anchor_name} via '{rel}'"
                        )
"""

EDIT_NEW = """                    other_name = other.get("name") or f"id={other_id}"
                    snippet = (other.get("summary") or "").strip()
                    if not snippet:
                        # Fix D (zero-LLM half): 76% of entities have no summary,
                        # so describe the node from its own typed neighbourhood
                        # rather than emitting a content-free fallback.  Memoised
                        # per call -- at most _T3_MAX_RESULTS lookups.
                        if other_id not in described:
                            described[other_id] = self._neighborhood_descriptor(
                                conn, other_id
                            )
                        snippet = described[other_id]
                    if not snippet:
                        snippet = (
                            f"{other.get('type', 'entity')} linked to "
                            f"{anchor_name} via '{rel}'"
                        )
"""

LOOP_ANCHOR = """                nodes = {n.get("id"): n for n in sub.get("nodes", [])}
                anchor = nodes.get(int(start_id)) or {}
                anchor_name = anchor.get("name") or name
"""

LOOP_NEW = """                nodes = {n.get("id"): n for n in sub.get("nodes", [])}
                anchor = nodes.get(int(start_id)) or {}
                anchor_name = anchor.get("name") or name
                described: Dict[int, str] = {}
"""

NEW_DESCRIPTOR = '''    def _neighborhood_descriptor(self, conn, entity_id: int) -> str:
        """Compact structural one-liner for an entity that has no summary.

        Fix D, zero-LLM half.  14,093 of 18,427 entities carry an empty
        `summary`, so a graph hit on one of them rendered as a content-free
        "<type> linked to <anchor> via '<rel>'".  This reads the entity's
        immediate typed neighbourhood -- its own top relations and the names of
        what sits on the other end -- so the injected context says something
        about the node, not just about the hop.

        Reads only.  It deliberately does NOT write `summary`: a semantic
        backfill needs to be able to distinguish "never summarised" from
        "summarised", and derived text in that column would destroy the signal.

        Returns "" when the entity has no qualifying edges.
        """
        try:
            rows = conn.execute(
                "SELECT r.type_id AS rel, "
                "       CASE WHEN r.source_id = ? THEN r.target_id "
                "            ELSE r.source_id END AS other "
                "FROM relationships r "
                "WHERE (r.source_id = ? OR r.target_id = ?) "
                "  AND r.provisional = 0 "
                "  AND r.confidence >= ? "
                "  AND (r.valid_to IS NULL OR r.valid_to > datetime('now')) "
                "ORDER BY r.confidence DESC, r.weight DESC "
                "LIMIT 40",
                (entity_id, entity_id, entity_id, _T3_MIN_CONFIDENCE),
            ).fetchall()
            if not rows:
                return ""

            other_ids = list({r["other"] for r in rows if r["other"]})
            if not other_ids:
                return ""
            placeholders = ",".join("?" * len(other_ids))
            names = {
                r["id"]: r["name"]
                for r in conn.execute(
                    f"SELECT id, name FROM entities WHERE id IN ({placeholders})",
                    other_ids,
                )
            }

            parts: List[str] = []
            seen_rels: set = set()
            for r in rows:
                rel = r["rel"]
                if rel in seen_rels:
                    continue
                seen_rels.add(rel)
                target = names.get(r["other"])
                if target:
                    parts.append(f"{rel} {target}")
                if len(parts) == 3:
                    break
            if not parts:
                return ""
            return "linked via " + "; ".join(parts)
        except Exception as e:
            logger.debug("neighbourhood descriptor failed for %s: %s", entity_id, e)
            return ""

'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "_neighborhood_descriptor" in src:
        print("ALREADY APPLIED — no change")
        return 0

    backup = TARGET.with_suffix(".py.bak.fixD-20260917")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
    print("backup:", backup)

    for label, old, new in (
        ("described-memo", LOOP_ANCHOR, LOOP_NEW),
        ("snippet-fallback", EDIT_OLD, EDIT_NEW),
    ):
        count = src.count(old)
        if count != 1:
            print(f"FAIL[{label}]: anchor found {count} times (need exactly 1)")
            return 1
        src = src.replace(old, new, 1)
        print(f"OK  [{label}]")

    anchor = "    def _reinforce_edges(self, entries: List[Dict]) -> int:"
    if src.count(anchor) != 1:
        print("FAIL: _reinforce_edges anchor not unique")
        return 1
    src = src.replace(anchor, NEW_DESCRIPTOR + anchor, 1)
    print("OK  [insert _neighborhood_descriptor]")

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
