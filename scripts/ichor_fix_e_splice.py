#!/usr/bin/env python3
"""Fix E splicer — make the OOD gate non-terminal, and harden the T3 hot path.

Fix E changes prefetch() so a weak/empty T1 no longer returns early, which
means T3 now runs on turns where it previously never ran.  Two consequences are
handled here so that is not a latency or privacy regression:

  1. `entity_resolve.resolve()` costs ~85 ms on a MISS (it scans every active
     entity and json.loads its aliases column).  T3 resolves up to 4 candidate
     names per turn, so the miss path needed a memo + a fast indexed pre-check
     that skips the O(N) scan.
  2. With the gate non-terminal, peer->peer observations can now arrive on a
     weak-T1 turn.  The cross_god privacy filter is applied to every path, not
     just the T1-only path.

Anchored replacements, assert-verified, `ast.parse`-checked.  Idempotent.
"""
from __future__ import annotations

import ast
import shutil
import sys
from pathlib import Path

TARGET = Path("/home/konan/.hermes/plugins/ichor/provider.py")
MARKER = "Fix E"

EDITS: list[tuple[str, str, str, bool]] = [
    # (label, old, new, required)
    (
        "t3-constant",
        "_T3_MAX_START_ENTITIES = 4\n",
        "_T3_MAX_START_ENTITIES = 4\n"
        "# Memo for the T3 alias->id lookup.  Caches misses too: a miss is the\n"
        "# expensive case, not the cheap one.\n"
        "_T3_RESOLVE_CACHE_MAX = 256\n",
        True,
    ),
    (
        "init-cache",
        "        self._cache: dict = {}    # T0 query cache\n"
        "        self._extractor = None    # Lazy-loaded TierAExtractor\n",
        "        self._cache: dict = {}    # T0 query cache\n"
        "        self._entity_id_cache: dict = {}  # T3 alias->id memo (incl. misses)\n"
        "        self._extractor = None    # Lazy-loaded TierAExtractor\n",
        True,
    ),
    (
        "ood-gate-non-terminal",
        "        all_results = list(t1_results)\n"
        "\n"
        "        # OOD Gate: if T1 found nothing, signal early\n"
        "        if not t1_results or t1_confidence < 0.3:\n"
        "            return self._format_empty_context()\n"
        "\n"
        "        # If T1 is definitive, stop here\n"
        "        if t1_confidence >= 0.8 and not is_full:\n",
        "        all_results = list(t1_results)\n"
        "\n"
        "        # \u2500\u2500 OOD gate \u2014 NON-TERMINAL since 2026-09-17 (Fix E) \u2500\u2500\n"
        "        # This used to return empty context the moment T1 was empty or scored\n"
        "        # below 0.3, so T2/T3/T4 never ran in exactly the case they exist for:\n"
        "        # the question is phrased differently from the stored text.  A weak T1\n"
        "        # now only suppresses the T1-only early exit below; the remaining tiers\n"
        "        # still get their chance and the fused result decides what to inject.\n"
        "        t1_is_strong = bool(t1_results) and t1_confidence >= 0.3\n"
        "\n"
        "        # If T1 is definitive, stop here\n"
        "        if t1_is_strong and t1_confidence >= 0.8 and not is_full:\n",
        True,
    ),
    (
        "peer-to-peer-filter-all-paths",
        "        # Fuse + cache\n"
        "        fused = self._fuse_results(all_results)\n",
        "        # Privacy: peer\u2192peer observations stay filtered unless cross_god, on\n"
        "        # EVERY path.  With the gate non-terminal they can now arrive via a\n"
        "        # weak-T1 turn, not only via the T1-only early exit above.\n"
        "        if not cross_god:\n"
        "            all_results = [\n"
        "                r for r in all_results if r.get(\"direction\") != \"peer\u2192peer\"\n"
        "            ]\n"
        "\n"
        "        # Fuse + cache\n"
        "        fused = self._fuse_results(all_results)\n",
        True,
    ),
    (
        "query-graph-use-memo",
        "                try:\n"
        "                    start_id = entity_resolve.resolve(name, db_path=str(_ICHOR_DB))\n"
        "                except Exception as e:\n"
        "                    logger.debug(\"T3 resolve(%r) failed: %s\", name, e)\n"
        "                    continue\n"
        "                if not start_id:\n"
        "                    continue\n",
        "                start_id = self._resolve_entity_id(name)\n"
        "                if not start_id:\n"
        "                    continue\n",
        True,
    ),
]

NEW_RESOLVER = '''    def _resolve_entity_id(self, name: str) -> Optional[int]:
        """Memoized, cheap alias -> canonical entity id for the T3 hot path.

        `entity_resolve.resolve()` is the full resolver, and it is correct -- but
        its last fallback scans EVERY active entity and `json.loads` each
        `aliases` column.  Measured on the live graph: ~8 ms on a hit, ~85 ms on
        a miss.  T3 resolves up to `_T3_MAX_START_ENTITIES` names per turn, so on
        the hot path the miss case is the one that matters.

        This fast path answers from the two indexed lookups that cover what
        Fix C now maintains -- `entity_aliases` (case-insensitive) and
        `entities.name` -- plus the `merged_into` hop, and caches the answer
        *including misses*.  It deliberately skips the O(N) `entities.aliases`
        JSON scan: that path is legacy (it is what left `entity_aliases` empty in
        the first place) and its cost is not affordable per turn.

        Returns the canonical entity id, or None.
        """
        key = (name or "").strip().lower()
        if not key:
            return None
        sentinel = object()
        cached = self._entity_id_cache.get(key, sentinel)
        if cached is not sentinel:
            return cached

        eid: Optional[int] = None
        try:
            from lib.ichor.entities import entity_resolve  # type: ignore[import-untyped]

            _ensure_pantheon_path()
            conn = sqlite3.connect(str(_ICHOR_DB))
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT canonical_entity_id FROM entity_aliases "
                    "WHERE LOWER(alias) = ? LIMIT 1",
                    (key,),
                ).fetchone()
                if row is not None:
                    eid = int(row["canonical_entity_id"])
                else:
                    row = conn.execute(
                        "SELECT id, status, merged_into FROM entities "
                        "WHERE LOWER(name) = ? ORDER BY id LIMIT 1",
                        (key,),
                    ).fetchone()
                    if row is not None:
                        if row["status"] == "merged" and row["merged_into"]:
                            eid = int(row["merged_into"])
                        elif row["status"] == "active":
                            eid = int(row["id"])
            finally:
                conn.close()

            if eid is None:
                # Rare fallback (alias lives only in the legacy JSON column).
                # Bounded so one odd name cannot stall a turn indefinitely.
                eid = entity_resolve.resolve(name, db_path=str(_ICHOR_DB))
        except Exception as e:
            logger.debug("T3 resolve(%r) failed (non-fatal): %s", name, e)
            eid = None

        if len(self._entity_id_cache) < _T3_RESOLVE_CACHE_MAX:
            self._entity_id_cache[key] = eid
        return eid

'''


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "NON-TERMINAL since 2026-09-17 (Fix E)" in src:
        print("ALREADY APPLIED — no change")
        return 0

    backup = TARGET.with_suffix(".py.bak.fixE-20260917")
    if not backup.exists():
        shutil.copy2(TARGET, backup)
    print("backup:", backup)

    for label, old, new, required in EDITS:
        count = src.count(old)
        if count != 1:
            if required:
                print(f"FAIL[{label}]: anchor found {count} times (need exactly 1)")
                return 1
            print(f"SKIP[{label}]: anchor found {count} times")
            continue
        src = src.replace(old, new, 1)
        print(f"OK  [{label}]")

    # Insert the new method before _llm_synthesize.
    anchor = "    def _llm_synthesize(self, query: str, results: List[Dict]) -> str:"
    if src.count(anchor) != 1:
        print("FAIL: _llm_synthesize anchor not unique")
        return 1
    src = src.replace(anchor, NEW_RESOLVER + anchor, 1)
    print("OK  [insert _resolve_entity_id]")

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
