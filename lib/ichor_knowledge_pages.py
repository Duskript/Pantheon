"""Ichor knowledge pages — standing answer projections from observations.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 8).

Knowledge pages are REBUILDABLE PROJECTIONS, never a source of truth:
- content is generated deterministically from observations (no LLM),
- every page records the observation ids it was built from,
- updates write the previous version to ``ichor_knowledge_page_versions``,
- deleting/rebuilding a page never touches observations.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from lib.ichor_tags import normalize_tags

_STALE_AFTER_DAYS = 30
_TOKEN_RE = re.compile(r"[a-z0-9_]+")

# ── MVP generation rule (Phase 8) ───────────────────────────────────────
#
# Standing answers are PROJECTIONS of the observation store: deterministic
# markdown, no LLM, and every page records the observation ids it was built
# from, so a page can be rebuilt or deleted without ever touching the source.
#
# Two design points, both learned from the 2026-09-20 audit ("a wired reader on
# a permanently empty table is indistinguishable from a correct one"):
#
# 1. Scope tags are EMPTY, deliberately. `KnowledgePageStore._tags_match` treats
#    a tagged page as out-of-scope for an untagged request: "any" mode falls
#    through to `not page_set`, and the ladder's default call is exactly
#    `search_pages(query, tags=[], tags_match="any")`. Tagging a global standing
#    answer therefore makes it UNREADABLE through the only reader that exists --
#    the same silent no-op, moved from the writer into the tag filter.
# 2. Only categories a human would ask about are projected. `health_check` and
#    `digest_entry` are machine telemetry (674 + 24 rows of "status ok"), which
#    would dominate a "what do we know" page with noise.
STANDING_QUESTIONS: Dict[str, str] = {
    "blocker": "What is currently blocked?",
    "commitment": "What commitments are outstanding?",
    "follow_up": "What follow-ups are open?",
    "decision": "What decisions have been made?",
    "insight": "What insights have been recorded?",
    "fact": "What facts do we know?",
    "reference": "What reference material do we have?",
    "correction": "What corrections have been made?",
    "preference": "What preferences are on record?",
}
EXCLUDED_CATEGORIES = frozenset({"health_check", "digest_entry"})
MIN_OBSERVATIONS_PER_PAGE = 3
MAX_OBSERVATIONS_PER_PAGE = 20
# Projection quality gate. The observation store's `content` column is
# template-rendered from raw turns, and raw turns contain JSON, file paths, code
# fences and half-quotes. A page that is nothing but that noise is worse than no
# page at all, because it lands in the HIGHEST-priority retrieval lane. So a
# candidate must look like a sentence: long enough to carry meaning, short
# enough not to be a transcript dump, no structural/code characters, and no
# URLs. Measured 2026-09-21: this keeps 270/23,605 blocker rows -- the gate is
# doing real work, not rubber-stamping.
MIN_OBSERVATION_CHARS = 20
MAX_OBSERVATION_CHARS = 200
MIN_OBSERVATION_WORDS = 4
MIN_OBSERVATION_CONFIDENCE = 0.9
MIN_OBSERVATION_PROOF = 3
_OBSERVATION_NOISE_RE = re.compile(r"[\\{}\[\]|<>#`]|https?://")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class KnowledgePageStore:
    """CRUD + deterministic refresh for knowledge page projections."""

    def __init__(self, db_path: str | Path = "~/.hermes/ichor.db") -> None:
        self.db_path = str(Path(db_path).expanduser())

    def _connect(self) -> sqlite3.Connection:
        from lib.ichor_db import IchorDB  # local import avoids cycles

        db = IchorDB(db_path=self.db_path)
        db.connect()
        conn = db._conn
        if conn is None:  # pragma: no cover
            raise sqlite3.OperationalError("ichor db connection unavailable")
        return conn

    # ── CRUD ──────────────────────────────────────────────────────────────

    def upsert_page(
        self,
        key: str,
        question: str,
        scope_tags: List[str],
        content_md: str,
        source_observation_ids: List[int],
    ) -> Dict[str, Any]:
        """Create or update a knowledge page.

        Versioning: an update with identical content is a no-op; otherwise
        the previous content is archived to ``ichor_knowledge_page_versions``
        and ``version`` increments.
        """
        conn = self._connect()
        key = str(key).strip()
        question = str(question or key)
        tags_json = json.dumps(normalize_tags(scope_tags), sort_keys=True)
        sources_json = json.dumps([int(i) for i in source_observation_ids], sort_keys=True)
        now = _now_iso()

        existing = conn.execute(
            "SELECT * FROM ichor_knowledge_pages WHERE key = ?", (key,)
        ).fetchone()
        if existing is not None:
            if (
                str(existing["content_md"]) == content_md
                and str(existing["question"]) == question
                and str(existing["scope_tags_json"]) == tags_json
                and str(existing["source_observation_ids_json"]) == sources_json
            ):
                return self.get_page(key) or {}
            version = int(existing["version"]) + 1
            conn.execute(
                "INSERT INTO ichor_knowledge_page_versions "
                "(page_id, version, content_md, source_observation_ids_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    int(existing["id"]), int(existing["version"]),
                    str(existing["content_md"]), str(existing["source_observation_ids_json"]),
                    now,
                ),
            )
            conn.execute(
                "UPDATE ichor_knowledge_pages SET question = ?, scope_tags_json = ?, "
                " content_md = ?, source_observation_ids_json = ?, version = ?, "
                " refresh_status = 'fresh', last_refreshed_at = ?, updated_at = ? "
                "WHERE key = ?",
                (question, tags_json, content_md, sources_json, version, now, now, key),
            )
        else:
            cur = conn.execute(
                "INSERT INTO ichor_knowledge_pages "
                "(key, question, scope_tags_json, content_md, source_observation_ids_json, "
                " version, refresh_status, last_refreshed_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 1, 'fresh', ?, ?)",
                (key, question, tags_json, content_md, sources_json, now, now),
            )
            version = 1
        conn.commit()
        page = self.get_page(key) or {}
        page["version"] = version
        return page

    def get_page(self, key: str) -> Dict[str, Any] | None:
        """Fetch one page by key (parsed JSON columns, no sources list)."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM ichor_knowledge_pages WHERE key = ?", (str(key),)
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["scope_tags"] = json.loads(out.get("scope_tags_json") or "[]")
        out["source_observation_ids"] = json.loads(out.get("source_observation_ids_json") or "[]")
        return out

    def search_pages(
        self,
        query: str,
        tags: List[str] | None = None,
        tags_match: str = "any_strict",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search pages by token overlap on question/content.

        Tag scoping is applied in Python (page counts are small). Strict
        modes exclude pages whose scope tags do not satisfy the match mode;
        non-strict modes include untagged/out-of-scope pages.
        """
        conn = self._connect()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM ichor_knowledge_pages ORDER BY updated_at DESC LIMIT 500"
        ).fetchall()]
        normalized = normalize_tags(tags)
        query_tokens = set(_TOKEN_RE.findall((query or "").lower()))

        scored: List[Dict[str, Any]] = []
        for row in rows:
            page = dict(row)
            page["scope_tags"] = json.loads(page.get("scope_tags_json") or "[]")
            page["source_observation_ids"] = json.loads(
                page.get("source_observation_ids_json") or "[]"
            )
            if normalized and not self._tags_match(page["scope_tags"], normalized, tags_match):
                continue
            if not query_tokens:
                score = 1.0
            else:
                haystack = " ".join([
                    str(page.get("question") or ""),
                    str(page.get("content_md") or ""),
                ]).lower()
                hay_tokens = set(_TOKEN_RE.findall(haystack))
                overlap = len(query_tokens & hay_tokens)
                score = overlap / len(query_tokens) if query_tokens else 0.0
            if score > 0:
                page["score"] = round(score, 4)
                scored.append(page)

        scored.sort(key=lambda p: (p["score"], str(p.get("updated_at") or "")), reverse=True)
        return scored[: max(1, int(limit))]

    @staticmethod
    def _tags_match(
        page_tags: List[str],
        requested: List[str],
        tags_match: str,
    ) -> bool:
        page_set = set(page_tags)
        if tags_match == "all_strict":
            return all(t in page_set for t in requested)
        if tags_match == "any_strict":
            return any(t in page_set for t in requested)
        if tags_match == "all":
            return all(t in page_set for t in requested) or not page_set
        return any(t in page_set for t in requested) or not page_set

    # ── Refresh ───────────────────────────────────────────────────────────

    def refresh_page(
        self,
        key: str,
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Regenerate a page's markdown from its source observations.

        Deterministic template (no LLM). ``dry_run=True`` reports the would-be
        content without writing. Returns the page dict (or an error dict).
        """
        page = self.get_page(key)
        if page is None:
            return {"error": f"knowledge page {key!r} not found", "refreshed": False}
        source_ids = [int(i) for i in page.get("source_observation_ids") or []]

        from lib.ichor_observations import ObservationConsolidator

        consolidator = ObservationConsolidator(db_path=self.db_path)
        observations: List[Dict[str, Any]] = []
        missing: List[int] = []
        for oid in source_ids:
            obs = consolidator.get_observation(oid, include_sources=True)
            if obs:
                observations.append(obs)
            else:
                missing.append(oid)

        content_md = render_page_markdown(
            str(page.get("question") or key), observations
        )
        changed = content_md != str(page.get("content_md") or "")
        result = {
            "key": key,
            "refreshed": True,
            "dry_run": dry_run,
            "changed": changed,
            "observations_found": len(observations),
            "observations_missing": missing,
            "content_md": content_md if dry_run else None,
        }
        if not dry_run:
            if changed:
                self.upsert_page(
                    key,
                    str(page.get("question") or key),
                    list(page.get("scope_tags") or []),
                    content_md,
                    source_ids,
                )
            else:
                now = _now_iso()
                conn = self._connect()
                conn.execute(
                    "UPDATE ichor_knowledge_pages SET refresh_status = 'fresh', "
                    " last_refreshed_at = ? WHERE key = ?",
                    (now, key),
                )
                conn.commit()
            result["content_md"] = content_md
            result["page"] = self.get_page(key)
        return result


# ── Deterministic markdown generation ────────────────────────────────────


def render_page_markdown(
    question: str,
    observations: List[Dict[str, Any]],
) -> str:
    """Render the spec template from observation dicts (deterministic)."""
    lines: List[str] = [f"# {question}", ""]
    lines.append("## Current Answer")
    lines.append("")
    if not observations:
        lines.append("_No consolidated observations yet._")
    else:
        for obs in observations:
            content = str(obs.get("content") or "").strip()
            lines.append(f"- {content}")
    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    if not observations:
        lines.append("_No evidence rows._")
    else:
        for obs in observations:
            oid = obs.get("id")
            lines.append(
                f"- observation:{oid} — proof_count={obs.get('proof_count')}, "
                f"confidence={obs.get('confidence')}, last_seen={obs.get('last_seen')}"
            )
    lines.append("")
    lines.append("## Staleness")
    lines.append("")
    stale = _page_is_stale(observations)
    lines.append("stale" if stale else "fresh")
    return "\n".join(lines)


def _page_is_stale(observations: List[Dict[str, Any]]) -> bool:
    """A page is stale when none of its observations were seen recently."""
    if not observations:
        return True
    from lib.ichor_temporal import parse_iso_z

    from datetime import timedelta

    now = datetime.now(timezone.utc)
    for obs in observations:
        last = parse_iso_z(obs.get("last_seen"))
        if last is not None and (now - last) <= timedelta(days=_STALE_AFTER_DAYS):
            return False
    return True


# ── Projection builder ───────────────────────────────────────────────────


def _observation_is_page_worthy(observation: Dict[str, Any]) -> bool:
    """Would this observation read as a sentence on a standing-answer page?

    Deliberately conservative: the page is a projection, so anything that fails
    this test is still reachable through the observations lane with its full
    provenance. Dropping it here costs nothing and keeps the projection clean.
    """
    text = str(observation.get("content") or "").strip()
    if not (MIN_OBSERVATION_CHARS <= len(text) <= MAX_OBSERVATION_CHARS):
        return False
    if _OBSERVATION_NOISE_RE.search(text):
        return False
    if not text[:1].isalpha():
        return False
    return len(text.split()) >= MIN_OBSERVATION_WORDS


def build_pages_from_observations(
    db_path: str | Path = "~/.hermes/ichor.db",
    *,
    dry_run: bool = False,
    min_observations: int = MIN_OBSERVATIONS_PER_PAGE,
    max_per_page: int = MAX_OBSERVATIONS_PER_PAGE,
) -> Dict[str, Any]:
    """Project consolidated observations into standing-answer pages.

    One page per observation category, keyed ``category:<category>``, rendered by
    :func:`render_page_markdown` (deterministic, no LLM) from the category's
    strongest observations -- ordered by ``proof_count`` then recency, because
    proof count is what consolidation already measured.

    Idempotent: :meth:`KnowledgePageStore.upsert_page` is a no-op when nothing
    changed, so this is safe to run nightly. Never touches observations.

    Returns a report of pages written (with versions) and categories skipped.
    """
    path = str(Path(db_path).expanduser())
    store = KnowledgePageStore(db_path=path)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        categories = [
            str(row["category"])
            for row in conn.execute(
                "SELECT category, COUNT(*) AS n FROM ichor_observations "
                "WHERE status = 'active' AND category IS NOT NULL "
                "GROUP BY category ORDER BY n DESC"
            )
            if str(row["category"]) not in EXCLUDED_CATEGORIES
        ]
        built: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []
        for category in categories:
            # Recency FIRST, then proof count. Ordering by proof_count alone
            # surfaced June/July rows whose counts had accumulated, so a
            # "currently blocked" page answered with two-month-old noise.
            # `_observation_is_page_worthy` then drops template/JSON rubble.
            candidates = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM ichor_observations "
                    "WHERE status = 'active' AND category = ? "
                    "AND confidence >= ? AND proof_count >= ? "
                    "ORDER BY last_seen DESC, proof_count DESC",
                    (
                        category,
                        MIN_OBSERVATION_CONFIDENCE,
                        MIN_OBSERVATION_PROOF,
                    ),
                )
            ]
            rows = [r for r in candidates if _observation_is_page_worthy(r)][:max_per_page]
            if len(rows) < min_observations:
                skipped.append({
                    "category": category,
                    "observations": len(rows),
                    "reason": "below min_observations after the quality gate",
                })
                continue

            question = STANDING_QUESTIONS.get(
                category, f"What do we know about {category}?"
            )
            content_md = render_page_markdown(question, rows)
            observation_ids = [int(row["id"]) for row in rows]
            record: Dict[str, Any] = {
                "category": category,
                "key": f"category:{category}",
                "question": question,
                "observations": len(observation_ids),
            }
            if dry_run:
                record["content_md"] = content_md
            else:
                page = store.upsert_page(
                    key=record["key"],
                    question=question,
                    scope_tags=[],
                    content_md=content_md,
                    source_observation_ids=observation_ids,
                )
                record["version"] = page.get("version")
            built.append(record)
    finally:
        conn.close()

    return {
        "db_path": path,
        "dry_run": dry_run,
        "pages": built,
        "skipped": skipped,
        "pages_written": len(built),
    }
