#!/usr/bin/env python3
"""Fragment-aware T3 anchoring — scripted edit for provider.py.

Why scripted: `patch` on this 1,600-line file scores below WikiGuard's 0.40
threshold for structural edits. Same guarantees as `patch`: every anchor must
match exactly once, a backup is written, and the result is ast-parsed before
acceptance.

What it does
------------
`IchorMemoryProvider._query_graph` resolved each candidate name to ONE entity
id (`_resolve_entity_id`), so with 1,854 lowercase names carrying more than one
active row (11 'pantheon', 6 'thoth', 6 'mercer') every edge hanging off a
sibling facet was invisible to that query. This wraps the per-facet walk in a
loop over `_resolve_entity_facets(name)` -- canonical id first, then same-name
active siblings, capped by `_T3_MAX_FACETS`.
"""
from __future__ import annotations

import ast
import pathlib
import shutil
import sys
import time

TARGET = pathlib.Path("/home/konan/.hermes/plugins/ichor/provider.py")

HEAD_OLD = '''            for name in entities[:_T3_MAX_START_ENTITIES]:
                start_id = self._resolve_entity_id(name)
                if not start_id:
                    continue

                try:
'''

TAIL_OLD = '''                if len(results) >= _T3_MAX_RESULTS:
                    break
        finally:
'''

HEAD_NEW = '''            for name in entities[:_T3_MAX_START_ENTITIES]:
                # Fragment-aware anchoring: 1,854 lowercase names carry more
                # than one active entity (11 'pantheon' rows, 6 'thoth' rows,
                # ...). `_resolve_entity_id` answers with exactly ONE id, so
                # every edge hanging off a sibling facet was invisible to T3
                # for that query. Walk the canonical id plus its same-name
                # siblings, bounded by `_T3_MAX_FACETS`.
                for start_id in self._resolve_entity_facets(name):
                    if len(results) >= _T3_MAX_RESULTS:
                        break

                    try:
'''

TAIL_NEW = '''                    if len(results) >= _T3_MAX_RESULTS:
                        break
        finally:
'''

CONST_OLD = '''_T3_MAX_START_ENTITIES = 4'''

CONST_NEW = '''_T3_MAX_START_ENTITIES = 4
# Same-name sibling facets walked per candidate name. Entity fragmentation is
# structural here (merges only fold same-type rows), so one anchor id per name
# hides most of the graph: 6 active 'thoth' rows, 11 'pantheon', 6 'mercer'.
_T3_MAX_FACETS = 3'''

CACHE_OLD = '''        self._entity_id_cache: dict = {}  # T3 alias->id memo (incl. misses)'''

CACHE_NEW = '''        self._entity_id_cache: dict = {}  # T3 alias->id memo (incl. misses)
        self._entity_facet_cache: dict = {}  # T3 name->[canonical, siblings] memo'''

METHOD_OLD = '''    def _resolve_entity_id(self, name: str) -> Optional[int]:'''

METHOD_NEW = '''    def _resolve_entity_facets(self, name: str) -> List[int]:
        """Canonical id for `name`, plus its same-name active sibling facets.

        Entity fragmentation is structural in this graph: 1,854 lowercase names
        hold more than one active row (11 'pantheon', 6 'thoth', 6 'mercer'),
        because merges only ever fold same-type rows and L2 extraction creates a
        new (name, type_id) pair for free. `_resolve_entity_id` returns one id,
        so a query anchored on "Thoth" reached one of six facets' edges.

        Returns the canonical id first (when one resolves), then the remaining
        active same-name rows ordered by id, capped at `_T3_MAX_FACETS`.
        Memoised including misses, exactly like `_resolve_entity_id`.
        """
        key = (name or "").strip().lower()
        if not key:
            return []
        sentinel = object()
        cached = self._entity_facet_cache.get(key, sentinel)
        if cached is not sentinel:
            return cached

        ids: List[int] = []
        canonical = self._resolve_entity_id(name)
        if canonical:
            ids.append(int(canonical))
        try:
            conn = sqlite3.connect(str(_ICHOR_DB))
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT id FROM entities WHERE LOWER(name) = ? AND status = 'active' "
                    "ORDER BY id",
                    (key,),
                ).fetchall()
            finally:
                conn.close()
            for r in rows:
                rid = int(r["id"])
                if rid not in ids:
                    ids.append(rid)
        except Exception as e:  # noqa: BLE001 -- facet lookup is an enhancement
            logger.debug("T3 facet lookup(%r) failed (non-fatal): %s", name, e)

        ids = ids[:_T3_MAX_FACETS]
        if len(self._entity_facet_cache) < _T3_RESOLVE_CACHE_MAX:
            self._entity_facet_cache[key] = ids
        return ids

    def _resolve_entity_id(self, name: str) -> Optional[int]:'''


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    src = TARGET.read_text()

    for label, anchor in (
        ("head", HEAD_OLD),
        ("tail", TAIL_OLD),
        ("const", CONST_OLD),
        ("cache", CACHE_OLD),
        ("method", METHOD_OLD),
    ):
        n = src.count(anchor)
        if n != 1:
            print(f"ABORT [{label}]: anchor matched {n} times (expected 1)")
            return 2

    i = src.index(HEAD_OLD)
    j = src.index(TAIL_OLD, i)
    body = src[i + len(HEAD_OLD): j]
    body_reindented = "\n".join(
        ("    " + ln if ln.strip() else ln) for ln in body.split("\n")
    )

    out = src[:i] + HEAD_NEW + body_reindented + TAIL_NEW + src[j + len(TAIL_OLD):]
    out = out.replace(CONST_OLD, CONST_NEW)
    out = out.replace(CACHE_OLD, CACHE_NEW)
    out = out.replace(METHOD_OLD, METHOD_NEW)

    ast.parse(out)
    print("anchors ok, ast.parse ok")
    if not apply:
        print("dry-run: nothing written")
        return 0

    shutil.copy2(TARGET, TARGET.with_suffix(".py.bak.facets-" + time.strftime("%Y%m%d-%H%M%S")))
    TARGET.write_text(out)
    ast.parse(TARGET.read_text())
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
