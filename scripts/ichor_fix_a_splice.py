#!/usr/bin/env python3
"""Fix A splicer — wire provider.py T3 to the real ER graph.

Splices by *def-line anchor* (not raw text match) so the edit survives
whitespace/em-dash differences, then asserts the result parses.
Idempotent: refuses to re-apply if the marker is already present.
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

TARGET = Path("/home/konan/.hermes/plugins/ichor/provider.py")
MARKER = "WIRED 2026-09-17 (Fix A)"

NEW_IMPORTS_OLD = "import os\nimport sys\nimport time\n"
NEW_IMPORTS_NEW = "import os\nimport re\nimport sqlite3\nimport sys\nimport time\n"

NEW_QUERY_GRAPH = '''    def _query_graph(self, entities: List[str], depth: int = 2) -> List[Dict]:
        """T3: typed ER graph walk over the ichor.db entity graph.

        WIRED 2026-09-17 (Fix A).  This was a no-op shim (`return []`) whose
        docstring claimed replacement by a "WARM entity lookup" that was never
        written -- so the relational half of the retriever was structurally
        absent and prefetch() was FTS5-only.

        Each candidate name is anchored on its canonical entity id through
        `entity_resolve.resolve` (which consults `entity_aliases` first), then
        walked with `traversal.graph_query_by_id` -- the Phase-2 bounded,
        index-backed BFS -- rather than `traverse()`, whose recursive CTE joins
        on `source_id = ? OR target_id = ?` and has a documented timeout
        history on dense hubs (konan owns 1,033 live edges).

        Returns one entry per (neighbour, relation) edge in the same dict shape
        `all_results` already carries, so T4 synthesis is unchanged.
        """
        if not entities:
            return []

        try:
            _ensure_pantheon_path()
            from lib.ichor.entities import entity_resolve  # type: ignore[import-untyped]
            from lib.ichor.entities import traversal  # type: ignore[import-untyped]
        except Exception as e:
            logger.debug("T3 graph tier import failed (non-fatal): %s", e)
            return []

        try:
            conn = sqlite3.connect(str(_ICHOR_DB))
            conn.row_factory = sqlite3.Row
        except Exception as e:
            logger.debug("T3 graph tier db open failed (non-fatal): %s", e)
            return []

        results: List[Dict] = []
        seen: set = set()
        try:
            for name in entities[:_T3_MAX_START_ENTITIES]:
                try:
                    start_id = entity_resolve.resolve(name, db_path=str(_ICHOR_DB))
                except Exception as e:
                    logger.debug("T3 resolve(%r) failed: %s", name, e)
                    continue
                if not start_id:
                    continue

                try:
                    sub = traversal.graph_query_by_id(
                        conn,
                        int(start_id),
                        depth=depth,
                        min_confidence=_T3_MIN_CONFIDENCE,
                        max_nodes=_T3_MAX_NODES,
                        max_edges=_T3_MAX_EDGES,
                        fanout=_T3_FANOUT,
                        timeout_ms=_T3_TIMEOUT_MS,
                    )
                except Exception as e:
                    logger.debug("T3 graph_query_by_id(%s) failed: %s", start_id, e)
                    continue

                nodes = {n.get("id"): n for n in sub.get("nodes", [])}
                anchor = nodes.get(int(start_id)) or {}
                anchor_name = anchor.get("name") or name

                for edge in sub.get("edges", []):
                    src, tgt = edge.get("source"), edge.get("target")
                    other_id = tgt if src == int(start_id) else src
                    if other_id is None or other_id == int(start_id):
                        continue
                    other = nodes.get(other_id)
                    if other is None:
                        continue

                    rel = edge.get("type") or "related_to"
                    key = (other_id, rel)
                    if key in seen:
                        continue
                    seen.add(key)

                    other_name = other.get("name") or f"id={other_id}"
                    snippet = (other.get("summary") or "").strip()
                    if not snippet:
                        snippet = (
                            f"{other.get('type', 'entity')} linked to "
                            f"{anchor_name} via '{rel}'"
                        )
                    results.append({
                        "id": f"graph:{other_id}:{rel}",
                        "score": float(edge.get("confidence") or 0.0),
                        "backend": "graph",
                        "type": other.get("type", ""),
                        "title": f"{anchor_name} --{rel}--> {other_name}",
                        "snippet": snippet[:300],
                        "direction": "unknown",
                    })
                    if len(results) >= _T3_MAX_RESULTS:
                        break
                if len(results) >= _T3_MAX_RESULTS:
                    break
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — closing must never mask a result
                pass

        if results:
            logger.debug("T3 graph tier returned %d relational hits", len(results))
        return results
'''

NEW_EXTRACT = '''    def _extract_named_entities(self, text: str) -> List[str]:
        """Capitalised phrases for graph walking, plus a possessive pass.

        Not NER -- a capitalisation + stop-word heuristic.  Two defects fixed
        2026-09-17 (Fix A):

        1. The old sentence-position guard tested `len(candidates) == 0`, which
           is only true before the *first* candidate is appended.  Every
           capitalized token seen while the list was still empty was dropped,
           so for a typical short message the tier returned [] and T3 never
           ran.  Sentence-initial proper nouns are now kept; `_STOP_WORDS`
           does the filtering.
        2. There was no possessive/pronoun pass, so "my brother" or "my
           partner" never anchored on a person.  `_relation_phrase_entities`
           now maps them through the person_roots relationship sections.
        """
        tokens = _WORD_RE.findall(text or "")
        entities: List[str] = []

        # Multi-word capitalised runs first: "Konan Ross Rudolph".
        run: List[str] = []
        for tok in tokens:
            if tok[:1].isupper() and tok.lower() not in _STOP_WORDS:
                run.append(tok)
            else:
                if len(run) >= 2:
                    entities.append(" ".join(run))
                run = []
        if len(run) >= 2:
            entities.append(" ".join(run))

        # Single capitalised tokens, possessive suffix stripped
        # ("Konan's" -> "Konan").
        for tok in tokens:
            if not tok[:1].isupper() or tok.lower() in _STOP_WORDS:
                continue
            entities.append(re.sub(r"(?:'|\\u2019)s$", "", tok))

        entities.extend(self._relation_phrase_entities(text))

        out: List[str] = []
        seen: set = set()
        for cand in sorted(set(entities), key=len, reverse=True):
            cand = cand.strip()
            key = cand.lower()
            if not cand or key in seen:
                continue
            seen.add(key)
            out.append(cand)
        return out[:_T3_MAX_ENTITIES]

    def _relation_phrase_entities(self, text: str) -> List[str]:
        """Resolve possessive relation phrases ("my brother") to people.

        Absence of this pass is why "my brother" / "my partner" never reached
        the graph tier even when the edge existed.  Unknown relations and
        unmatched people are skipped silently -- this is best-effort.
        """
        if not text:
            return []
        relations = {m.group(1).lower() for m in _POSSESSIVE_RE.finditer(text)}
        relations.update(
            m.group(1).lower() for m in _KONAN_POSSESSIVE_RE.finditer(text)
        )
        if not relations:
            return []
        table = _load_relation_phrase_table()
        found: List[str] = []
        for rel in relations:
            found.extend(table.get(rel, ()))
        return found
'''


def splice_methods(lines: list[str], starts: dict[str, int]) -> list[str]:
    """Replace the body of each named method, keeping its own def line."""
    for name, start in sorted(starts.items(), key=lambda kv: -kv[1]):
        end = start + 1
        while end < len(lines):
            stripped = lines[end]
            if stripped.startswith("    def ") or stripped.startswith("    # \u2500"):
                break
            end += 1
        # Trim trailing blank lines back into the file's spacing.
        replace_with = (NEW_QUERY_GRAPH if name == "_query_graph" else NEW_EXTRACT)
        lines[start:end] = replace_with.splitlines(keepends=True)
    return lines


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if MARKER in src:
        print("ALREADY APPLIED — no change")
        return 0

    backup = TARGET.with_suffix(".py.bak.prefixA-20260917")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
    print("backup:", backup)

    if NEW_IMPORTS_OLD not in src:
        print("FAIL: import anchor not found")
        return 1
    src = src.replace(NEW_IMPORTS_OLD, NEW_IMPORTS_NEW, 1)

    lines = src.splitlines(keepends=True)
    targets = {"_query_graph": None, "_extract_named_entities": None}
    for i, line in enumerate(lines):
        for name in targets:
            if line.startswith(f"    def {name}("):
                targets[name] = i
    missing = [k for k, v in targets.items() if v is None]
    if missing:
        print("FAIL: def not found:", missing)
        return 1
    print("def line anchors:", {k: v + 1 for k, v in targets.items()})

    lines = splice_methods(lines, {k: v for k, v in targets.items()})
    out = "".join(lines)

    try:
        ast.parse(out)
    except SyntaxError as e:
        print("FAIL: result does not parse:", e)
        return 1

    TARGET.write_text(out, encoding="utf-8")
    print("WROTE", TARGET, len(out), "bytes")
    print("ast.parse: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
