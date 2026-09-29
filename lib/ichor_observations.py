"""Ichor observation consolidation — deterministic, evidence-grounded.

Hindsight-inspired memory upgrades (spec:
plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md §Phase 3).

Turns repeated, similar events into consolidated observations with exact
quote evidence. Deterministic by construction: no LLM calls, stable ordering
(event id asc), Jaccard similarity clustering with a fixed threshold, and
idempotent upserts keyed on ``UNIQUE(subject, predicate, category, content)``.

Conflict handling: events that contradict a cluster representative are NEVER
silently merged — they start a separate cluster (surfaced via
``contradictions_skipped``), so no observation content is overwritten.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional

from lib.ichor_tags import attach_observation_tags, build_tag_filter_sql, normalize_tags
from lib.ichor_temporal import days_between, normalize_timestamp, parse_iso_z

# ── Deterministic consolidation constants ────────────────────────────────
MIN_CLUSTER_SIZE = 2
TEXT_SIMILARITY_THRESHOLD = 0.45
QUOTE_MAX_CHARS = 500
RECENT_WINDOW_DAYS = 30
STALE_AFTER_DAYS = 90
DENSITY_STRENGTHENING_RATIO = 1.5
DENSITY_WEAKENING_RATIO = 0.5

_WS = re.compile(r"\s+")
_TOKEN_RE = re.compile(r"[a-z0-9_]+")


@dataclass
class ObservationEvidence:
    """One exact-quote source row backing an observation."""

    event_id: int | None
    conclusion_id: int | None
    quote: str
    relevance: str
    source_session_id: str | None
    source_god_name: str | None
    source_timestamp: str | None


@dataclass
class Observation:
    """Consolidated belief with proof count and evidence span."""

    id: int | None
    subject: str
    predicate: str | None
    object: str | None
    content: str
    category: str
    confidence: float
    proof_count: int
    first_seen: str | None
    last_seen: str | None
    evidence_span_days: float
    trend: Literal["new", "stable", "strengthening", "weakening", "stale"]
    status: Literal["active", "archived", "superseded", "invalidated"]
    tags: List[str] = field(default_factory=list)
    sources: List[ObservationEvidence] = field(default_factory=list)


@dataclass
class ConsolidationResult:
    """Summary of one consolidation pass."""

    events_processed: int = 0
    clusters_found: int = 0
    observations_created: int = 0
    observations_updated: int = 0
    sources_written: int = 0
    tags_attached: int = 0
    contradictions_skipped: int = 0
    dry_run: bool = True
    written: bool = False
    observations: List[Dict[str, Any]] = field(default_factory=list)
    min_event_id_processed: int | None = None
    max_event_id_processed: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "events_processed": self.events_processed,
            "clusters_found": self.clusters_found,
            "observations_created": self.observations_created,
            "observations_updated": self.observations_updated,
            "sources_written": self.sources_written,
            "tags_attached": self.tags_attached,
            "contradictions_skipped": self.contradictions_skipped,
            "dry_run": self.dry_run,
            "written": self.written,
            "observation_count": len(self.observations),
            "min_event_id_processed": self.min_event_id_processed,
            "max_event_id_processed": self.max_event_id_processed,
        }


def _normalize_subject(subject: str | None) -> str:
    return _WS.sub(" ", str(subject or "").strip().lower())


def _normalize_predicate(predicate: str | None, event_type: str | None) -> str:
    return _WS.sub(" ", str(predicate or event_type or "").strip().lower())


def _token_set(*texts: str | None) -> set[str]:
    out: set[str] = set()
    for t in texts:
        if not t:
            continue
        out.update(w for w in _TOKEN_RE.findall(str(t).lower()) if len(w) > 2)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _event_ts(row: Dict[str, Any]) -> str | None:
    for key in ("mentioned_at", "created_at"):
        raw = row.get(key)
        if raw:
            norm = normalize_timestamp(str(raw))
            if norm:
                return norm
    return None


def _quote(raw_text: str | None) -> str:
    return (str(raw_text or "")).strip()[:QUOTE_MAX_CHARS]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _as_int(value: Any) -> int:
    """Coerce a DB row id to int (rows always carry an id; None → 0)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _compute_trend(source_ts: List[str], first_seen: str | None, last_seen: str | None) -> str:
    """Deterministic trend from source timestamps (mirrors Hindsight shape).

    Uses wall-clock ``now`` as the freshness reference; all other logic is
    fixed constants so the label is reproducible for a given data window.
    """
    if not source_ts or last_seen is None:
        return "new"
    now = datetime.now(timezone.utc)
    last = parse_iso_z(last_seen)
    if last is None:
        return "new"
    if (now - last).days > STALE_AFTER_DAYS:
        return "stale"
    recent = [ts for ts in source_ts if _within_days(ts, now, RECENT_WINDOW_DAYS)]
    older = [ts for ts in source_ts if ts not in recent]
    if not older:
        return "stable" if len(recent) >= 3 else "new"
    if not recent:
        return "weakening"
    recent_span = _span_days(recent)
    older_span = _span_days(older)
    density_recent = len(recent) / max(recent_span, 1.0)
    density_older = len(older) / max(older_span, 1.0)
    if density_recent >= DENSITY_STRENGTHENING_RATIO * density_older:
        return "strengthening"
    if density_recent <= DENSITY_WEAKENING_RATIO * density_older:
        return "weakening"
    return "stable"


def _within_days(ts: str | None, reference: datetime, days: int) -> bool:
    parsed = parse_iso_z(ts)
    if parsed is None:
        return False
    from datetime import timedelta

    return reference - parsed <= timedelta(days=days)


def _span_days(timestamps: List[str]) -> float:
    parsed = [parse_iso_z(ts) for ts in timestamps]
    parsed = [p for p in parsed if p is not None]
    if not parsed:
        return 0.0
    return max(0.0, (max(parsed) - min(parsed)).total_seconds() / 86400.0)


class ObservationConsolidator:
    """Deterministic consolidation of repeated events into observations."""

    # ── busy_timeout_ms: propagated so the consolidation WRITES wait ───────
    # Mechanism: `_connect()` builds its own IchorDB per call, so a caller that
    # configured a lock-wait policy on its own connection does not automatically
    # cover this class. Without propagation the count/schema connects wait but
    # the write that actually matters still fails after 5s.
    # Symptom: hindsight consolidation aborted at 2026-09-21 09:51 and 10:07
    # with `sqlite3.OperationalError: database is locked` while a sibling job
    # checkpointed a 12 GiB WAL.
    # Reproduce by hand: hold a write lock and run the consolidation pass —
    #     python3 -c "import sqlite3,time; c=sqlite3.connect('/home/konan/.hermes/ichor.db'); c.execute('BEGIN IMMEDIATE'); time.sleep(30)"
    #     python3 scripts/ichor_consolidate_observations.py --db-path ~/.hermes/ichor.db
    def __init__(
        self,
        db_path: str | Path = "~/.hermes/ichor.db",
        *,
        busy_timeout_ms: int | None = None,
    ) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self.busy_timeout_ms = busy_timeout_ms

    def _connect(self) -> sqlite3.Connection:
        from lib.ichor_db import IchorDB  # local import avoids cycles

        db = IchorDB(db_path=self.db_path, busy_timeout_ms=self.busy_timeout_ms)
        db.connect()
        conn = db._conn
        if conn is None:  # pragma: no cover
            raise sqlite3.OperationalError("ichor db connection unavailable")
        return conn

    # ── Core consolidation ────────────────────────────────────────────────

    def consolidate_events(
        self,
        *,
        limit: int = 1000,
        tags: list[str] | None = None,
        after_id: int | None = None,
        only_unsourced: bool = False,
        dry_run: bool = False,
    ) -> ConsolidationResult | Dict[str, Any]:
        """Consolidate up to ``limit`` active events into observations.

        ``after_id`` lets batch jobs advance through the corpus without
        re-reading the same prefix forever. ``only_unsourced`` skips events that
        already appear in observation source rows. ``dry_run=True`` (default at
        the CLI) reports candidate clusters without writing anything. Apply mode
        is idempotent.
        """
        conn = self._connect()
        normalized = normalize_tags(tags)
        tag_sql, tag_params = build_tag_filter_sql(
            "e", "ichor_event_tags", "id", "event_id", normalized,
            "any_strict" if normalized else "any",  # type: ignore[arg-type]
        )
        where = ["(e.status IS NULL OR e.status = 'active')"]
        params: List[Any] = []
        if after_id is not None:
            where.append("e.id > ?")
            params.append(max(0, int(after_id)))
        if only_unsourced:
            where.append(
                "NOT EXISTS ("
                "SELECT 1 FROM ichor_observation_sources os "
                "WHERE os.event_id = e.id"
                ")"
            )
        if tag_sql:
            where.append(tag_sql)
            params.extend(tag_params)
        sql = (
            "SELECT e.* FROM ichor_events e WHERE " + " AND ".join(where)
            + " ORDER BY e.id ASC LIMIT ?"
        )
        params.append(max(1, int(limit)))
        events = [dict(r) for r in conn.execute(sql, params).fetchall()]
        event_ids = [_as_int(e.get("id")) for e in events]

        tag_lookup = self._fetch_event_tags(conn, event_ids)
        clusters = self._cluster_events(events, tag_lookup)
        result = ConsolidationResult(
            events_processed=len(events),
            clusters_found=len(clusters),
            dry_run=dry_run,
            written=not dry_run,
            min_event_id_processed=min(event_ids) if event_ids else None,
            max_event_id_processed=max(event_ids) if event_ids else None,
        )

        if dry_run:
            result.observations = [c.to_dict() for c in clusters]
            return result

        return self._write_clusters(conn, clusters, result)

    def consolidate_subject(
        self,
        subject: str,
        *,
        category: str | None = None,
        dry_run: bool = False,
    ) -> ConsolidationResult | Dict[str, Any]:
        """Consolidate events whose normalized subject matches ``subject``."""
        conn = self._connect()
        params: List[Any] = [_normalize_subject(subject)]
        sql = (
            "SELECT e.* FROM ichor_events e "
            "WHERE (e.status IS NULL OR e.status = 'active') "
            "AND LOWER(TRIM(e.subject)) = ?"
        )
        if category:
            sql += " AND e.event_type = ?"
            params.append(category)
        sql += " ORDER BY e.id ASC"
        events = [dict(r) for r in conn.execute(sql, params).fetchall()]
        tag_lookup = self._fetch_event_tags(conn, [_as_int(e.get("id")) for e in events])
        clusters = self._cluster_events(events, tag_lookup)
        result = ConsolidationResult(
            events_processed=len(events),
            clusters_found=len(clusters),
            dry_run=dry_run,
            written=not dry_run,
        )
        if dry_run:
            result.observations = [c.to_dict() for c in clusters]
            return result
        return self._write_clusters(conn, clusters, result)

    # ── Clustering ────────────────────────────────────────────────────────

    def _fetch_event_tags(self, conn: sqlite3.Connection, event_ids: List[int]) -> Dict[int, List[str]]:
        if not event_ids:
            return {}
        from lib.ichor_db import IchorDB

        return IchorDB(db_path=self.db_path).fetch_event_tags(event_ids)

    def _cluster_events(
        self,
        events: List[Dict[str, Any]],
        tag_lookup: Dict[int, List[str]],
    ) -> List["_ObservationCluster"]:
        """Group events deterministically by subject/predicate/category +
        token Jaccard similarity, honoring contradiction boundaries."""
        from lib.ichor_hybrid import detect_contradiction  # local import (cycle)

        groups: Dict[tuple[str, str, str], List[Dict[str, Any]]] = {}
        for ev in events:
            key = (
                _normalize_subject(ev.get("subject")),
                _normalize_predicate(ev.get("predicate"), ev.get("event_type")),
                str(ev.get("event_type") or "fact"),
            )
            groups.setdefault(key, []).append(ev)

        clusters: List["_ObservationCluster"] = []
        for group_key, group_events in groups.items():
            # Deterministic order: event id ascending.
            for ev in sorted(group_events, key=lambda e: int(e.get("id") or 0)):
                ev_tokens = _token_set(ev.get("object"), ev.get("raw_text"))
                best_cluster: Optional["_ObservationCluster"] = None
                best_sim = 0.0
                for cluster in clusters:
                    if cluster.key != group_key:
                        continue
                    if _jaccard(ev_tokens, cluster.tokens) < TEXT_SIMILARITY_THRESHOLD:
                        continue
                    if detect_contradiction(cluster.rep_text, _quote(ev.get("raw_text"))):
                        # Contradictory evidence — do NOT merge silently.
                        cluster.contradictions += 1
                        continue
                    if best_cluster is None or cluster.similarity_to(ev_tokens) > best_sim:
                        best_cluster = cluster
                        best_sim = cluster.similarity_to(ev_tokens)
                if best_cluster is not None:
                    best_cluster.add_event(ev, tag_lookup.get(int(ev.get("id") or 0), []))
                else:
                    clusters.append(_ObservationCluster(group_key, ev, tag_lookup.get(int(ev.get("id") or 0), [])))

        # Only clusters with enough independent evidence become observations.
        return [c for c in clusters if len(c.events) >= MIN_CLUSTER_SIZE]

    # ── Write path ────────────────────────────────────────────────────────

    def _write_clusters(
        self,
        conn: sqlite3.Connection,
        clusters: List["_ObservationCluster"],
        result: ConsolidationResult,
    ) -> ConsolidationResult:
        for cluster in clusters:
            obs = cluster.to_observation()
            existing = conn.execute(
                "SELECT id FROM ichor_observations "
                "WHERE subject = ? AND predicate = ? AND category = ? AND content = ?",
                (obs.subject, obs.predicate, obs.category, obs.content),
            ).fetchone()
            if existing is None:
                cur = conn.execute(
                    "INSERT INTO ichor_observations "
                    "(subject, predicate, object, content, category, confidence, proof_count, "
                    " first_seen, last_seen, evidence_span_days, trend, status, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                    (
                        obs.subject, obs.predicate, obs.object, obs.content, obs.category,
                        obs.confidence, obs.proof_count, obs.first_seen, obs.last_seen,
                        obs.evidence_span_days, obs.trend, obs.status,
                    ),
                )
                observation_id = int(cur.lastrowid)
                result.observations_created += 1
            else:
                observation_id = int(existing["id"])
                conn.execute(
                    "UPDATE ichor_observations SET "
                    " object = ?, confidence = ?, proof_count = ?, first_seen = ?, last_seen = ?, "
                    " evidence_span_days = ?, trend = ?, status = 'active', updated_at = datetime('now') "
                    "WHERE id = ?",
                    (
                        obs.object, obs.confidence, obs.proof_count, obs.first_seen,
                        obs.last_seen, obs.evidence_span_days, obs.trend, observation_id,
                    ),
                )
                result.observations_updated += 1

            # Evidence rows (INSERT OR IGNORE keeps history → idempotent).
            for src in obs.sources:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO ichor_observation_sources "
                    "(observation_id, event_id, conclusion_id, quote, relevance, "
                    " source_session_id, source_god_name, source_timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        observation_id, src.event_id, src.conclusion_id, src.quote,
                        src.relevance, src.source_session_id, src.source_god_name,
                        src.source_timestamp,
                    ),
                )
                result.sources_written += cur.rowcount

            if obs.tags:
                attach_observation_tags(conn, observation_id, obs.tags)
                result.tags_attached += len(obs.tags)

            # Commit before fetching through get_observation(): that helper opens
            # a fresh connection, so uncommitted rows on this connection would
            # otherwise appear as an empty dict in the result payload.
            conn.commit()
            result.observations.append(self.get_observation(observation_id, include_sources=True))

        return result

    # ── Read helpers ──────────────────────────────────────────────────────

    def get_observation(
        self,
        observation_id: int,
        include_sources: bool = False,
    ) -> Dict[str, Any]:
        """Fetch one observation with optional source rows and tags."""
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM ichor_observations WHERE id = ?", (int(observation_id),)
        ).fetchone()
        if row is None:
            return {}
        out = dict(row)
        tag_rows = conn.execute(
            "SELECT tag FROM ichor_observation_tags WHERE observation_id = ? ORDER BY tag",
            (int(observation_id),),
        ).fetchall()
        out["tags"] = [str(r["tag"]) for r in tag_rows]
        if include_sources:
            source_rows = conn.execute(
                "SELECT event_id, conclusion_id, quote, relevance, source_session_id, "
                "source_god_name, source_timestamp "
                "FROM ichor_observation_sources WHERE observation_id = ? "
                "ORDER BY source_timestamp, event_id",
                (int(observation_id),),
            ).fetchall()
            out["sources"] = [dict(r) for r in source_rows]
        return out

    def search_observations(
        self,
        query: str,
        limit: int = 10,
        tags: list[str] | None = None,
        tags_match: str = "any",
        query_timestamp: str | None = None,
        include_sources: bool = False,
    ) -> List[Dict[str, Any]]:
        """Search consolidated observations (delegates to the backend)."""
        from lib.ichor.retrieval_observations import ObservationsBackend

        backend = ObservationsBackend(db_path=self.db_path)
        return backend.search(
            query=query,
            limit=limit,
            tags=tags,
            tags_match=tags_match,
            query_timestamp=query_timestamp,
            include_sources=include_sources,
        )


class _ObservationCluster:
    """Internal mutable cluster used only during a consolidation pass."""

    def __init__(self, key: tuple[str, str, str], first_event: Dict[str, Any], tags: List[str]) -> None:
        self.key = key
        self.events: List[Dict[str, Any]] = []
        self.tags_seen: Dict[str, None] = {}
        self.contradictions = 0
        self.tokens: set[str] = set()
        self.rep_text = ""
        self.add_event(first_event, tags)

    def add_event(self, ev: Dict[str, Any], tags: List[str]) -> None:
        self.events.append(ev)
        for t in tags or []:
            self.tags_seen[t] = None
        text = " ".join(
            str(ev.get(k) or "") for k in ("object", "raw_text")
        )
        self.tokens = self.tokens | _token_set(text)
        if not self.rep_text:
            self.rep_text = _quote(ev.get("raw_text"))

    def similarity_to(self, tokens: set[str]) -> float:
        return _jaccard(tokens, self.tokens)

    def to_observation(self) -> Observation:
        ordered = sorted(self.events, key=lambda e: int(e.get("id") or 0))
        confidences = [float(e.get("confidence") or 0.5) for e in ordered]
        total_w = sum(confidences)
        base = sum(c * c for c in confidences) / total_w if total_w else 0.5
        proof_boost = min(0.15, 0.03 * (len(ordered) - 1))
        confidence = _clamp(base + proof_boost)

        first_ev = ordered[0]
        # Canonical object: highest-confidence source (tie → lowest id).
        rep = max(ordered, key=lambda e: (float(e.get("confidence") or 0.0), -int(e.get("id") or 0)))
        canonical_object = rep.get("object") or first_ev.get("object") or ""
        subject = str(first_ev.get("subject") or "")
        predicate = str(first_ev.get("predicate") or first_ev.get("event_type") or "")
        content = f"{subject} {predicate} {canonical_object}.".replace("..", ".").strip()

        timestamps = [_event_ts(e) for e in ordered]
        timestamps = [ts for ts in timestamps if ts]
        first_seen = min(timestamps) if timestamps else None
        last_seen = max(timestamps) if timestamps else None
        span = days_between(first_seen, last_seen)
        trend = _compute_trend(timestamps, first_seen, last_seen)

        sources: List[ObservationEvidence] = []
        for ev in ordered:
            sources.append(
                ObservationEvidence(
                    event_id=int(ev.get("id")),
                    conclusion_id=None,
                    quote=_quote(ev.get("raw_text")),
                    relevance="cluster_match",
                    source_session_id=ev.get("session_id"),
                    source_god_name=ev.get("god_name"),
                    source_timestamp=_event_ts(ev),
                )
            )

        return Observation(
            id=None,
            subject=subject,
            predicate=predicate or None,
            object=canonical_object or None,
            content=content,
            category=str(first_ev.get("event_type") or "fact"),
            confidence=round(confidence, 4),
            proof_count=len(ordered),
            first_seen=first_seen,
            last_seen=last_seen,
            evidence_span_days=span,
            trend=trend,  # type: ignore[arg-type]
            status="active",
            tags=list(self.tags_seen.keys()),
            sources=sources,
        )

    def to_dict(self) -> Dict[str, Any]:
        obs = self.to_observation()
        return {
            "subject": obs.subject,
            "predicate": obs.predicate,
            "object": obs.object,
            "content": obs.content,
            "category": obs.category,
            "confidence": obs.confidence,
            "proof_count": obs.proof_count,
            "first_seen": obs.first_seen,
            "last_seen": obs.last_seen,
            "evidence_span_days": obs.evidence_span_days,
            "trend": obs.trend,
            "tags": obs.tags,
            "source_event_ids": [s.event_id for s in obs.sources],
            "contradictions_skipped": self.contradictions,
        }
