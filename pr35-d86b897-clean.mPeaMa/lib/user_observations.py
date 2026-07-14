"""
Pantheon User Observations — PostgreSQL Storage Backend.

Stores structured observations extracted from conversations by the 
Ichor Nudge plugin's LLM review. Each observation is atomic, self-contained,
and linked to source messages via evidence references.

Schema dependency: See database/schema.sql for the conclusions table.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pantheon.user_observations")

# ---------------------------------------------------------------------------
# PostgreSQL connection (lazy, single-connection for cron/plugin use)
# ---------------------------------------------------------------------------
_conn = None


def _get_conn():
    """Lazy PostgreSQL connection. Reads PGPASSWORD from ~/.hermes/.env."""
    global _conn
    if _conn is not None and not _conn.closed:
        return _conn

    import psycopg2
    import psycopg2.extras

    # Read password from env file
    env_path = Path.home() / ".hermes" / ".env"
    password = "pantheon"  # default
    if env_path.exists():
        for line in env_path.read_text().split("\n"):
            line = line.strip()
            if line.startswith("PGPASSWORD="):
                password = line.split("=", 1)[1].strip().strip("\"'")
                break

    _conn = psycopg2.connect(
        dbname="pantheon",
        user="pantheon",
        password=password,
        host="127.0.0.1",
    )
    _conn.autocommit = True
    return _conn


# ---------------------------------------------------------------------------
# Observation categories (mirrors the extraction prompt)
# ---------------------------------------------------------------------------
VALID_CATEGORIES = {
    "fact", "preference", "commitment", "project", "relationship",
    "environment", "emotional", "contradiction", "gap",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def store_observations(
    observations: List[Dict[str, Any]],
    subject_id: str,
    observer_id: str = "hermes",
    session_id: str = "",
) -> int:
    """Store extracted observations in PostgreSQL.

    Args:
        observations: List of observation dicts from the LLM extraction.
            Each must have: category, content, confidence.
            Optional: evidence, deadline, prior_belief, current_belief.
        subject_id: Who the observation is ABOUT (canonical user ID).
        observer_id: Which god extracted this (default: hermes).
        session_id: Source session for evidence tracing.

    Returns:
        Number of observations successfully stored.
    """
    if not observations:
        return 0

    conn = _get_conn()
    count = 0
    now = datetime.now(timezone.utc).isoformat()

    with conn.cursor() as cur:
        for obs in observations:
            category = obs.get("category", "fact")
            if category not in VALID_CATEGORIES:
                logger.debug("Skipping observation with invalid category: %s", category)
                continue

            content = (obs.get("content") or "").strip()
            confidence = float(obs.get("confidence", 0.5))

            if not content or confidence < 0.5:
                continue

            evidence_raw = obs.get("evidence", [])
            evidence = json.dumps(evidence_raw) if evidence_raw else "[]"

            deadline = obs.get("deadline")
            prior_belief = obs.get("prior_belief") or obs.get("prior")
            current_belief = obs.get("current_belief") or obs.get("current")

            try:
                cur.execute(
                    """
                    INSERT INTO conclusions 
                        (peer_id, peer_type, observer_id, category, content,
                         evidence, confidence, created_at, session_id,
                         deadline, prior_belief, current_belief)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        subject_id,
                        "user",
                        observer_id,
                        category,
                        content,
                        evidence,
                        confidence,
                        now,
                        session_id or None,
                        deadline,
                        prior_belief,
                        current_belief,
                    ),
                )
                count += 1
            except Exception as exc:
                logger.warning(
                    "Failed to store observation for %s: %s", subject_id, exc
                )

    if count:
        logger.info(
            "Stored %d observations about %s (observer: %s, session: %s)",
            count, subject_id, observer_id, session_id or "(none)",
        )

    return count


def get_existing_observations(
    subject_id: str,
    observer_id: str = "hermes",
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """Retrieve existing observations about a user for deduplication.

    Used by the extraction prompt to avoid re-extracting known facts.

    Args:
        subject_id: Who we're querying about.
        observer_id: Which god's perspective to query.
        limit: Max observations to return.

    Returns:
        List of observation dicts, newest first.
    """
    conn = _get_conn()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT category, content, confidence, created_at
            FROM conclusions
            WHERE peer_id = %s
              AND peer_type = 'user'
              AND observer_id = %s
              AND superseded_by IS NULL
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (subject_id, observer_id, limit),
        )
        rows = cur.fetchall()

    return [
        {
            "category": row[0],
            "content": row[1],
            "confidence": row[2],
            "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
        }
        for row in rows
    ]


def get_representation(
    subject_id: str,
    observer_id: str = "hermes",
) -> Optional[str]:
    """Get the current god-specific representation of a user.

    The representation is a living markdown document that summarizes
    everything this god knows about this user. Generated from conclusions
    and updated periodically.

    Args:
        subject_id: Who the representation is about.
        observer_id: Which god's perspective.

    Returns:
        Markdown string or None if no representation exists.
    """
    conn = _get_conn()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT content FROM representations
            WHERE observer_id = %s
              AND subject_id = %s
              AND subject_type = 'user'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (observer_id, subject_id),
        )
        row = cur.fetchone()

    return row[0] if row else None


def update_representation(
    subject_id: str,
    observer_id: str,
    content: str,
) -> bool:
    """Upsert a god's representation of a user.

    Args:
        subject_id: Who this is about.
        observer_id: Which god holds this view.
        content: Markdown representation text.

    Returns:
        True if stored successfully.
    """
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()

    with conn.cursor() as cur:
        try:
            cur.execute(
                """
                INSERT INTO representations (observer_id, subject_id, subject_type, content, updated_at, version)
                VALUES (%s, %s, 'user', %s, %s, 1)
                ON CONFLICT (observer_id, subject_id)
                DO UPDATE SET content = EXCLUDED.content,
                              updated_at = EXCLUDED.updated_at,
                              version = representations.version + 1
                """,
                (observer_id, subject_id, content, now),
            )
            return True
        except Exception as exc:
            logger.warning("Failed to update representation: %s", exc)
            return False


def resolve_user_alias(platform: str, alias: str) -> Optional[str]:
    """Resolve a platform alias to a canonical user ID.

    Args:
        platform: 'telegram', 'discord', 'webui'
        alias: Platform-specific identifier or display name.

    Returns:
        Canonical user ID (e.g., 'konan') or None.
    """
    conn = _get_conn()

    with conn.cursor() as cur:
        # Try exact platform_id match first
        cur.execute(
            """
            SELECT user_id FROM user_aliases
            WHERE platform = %s AND (alias = %s OR platform_id = %s)
            LIMIT 1
            """,
            (platform, alias, alias),
        )
        row = cur.fetchone()
        if row:
            return row[0]

    return None


# ---------------------------------------------------------------------------
# Standalone: regenerate a user's representation from conclusions
# ---------------------------------------------------------------------------


def regenerate_representation(
    subject_id: str,
    observer_id: str = "hermes",
) -> str:
    """Build a fresh representation from all current conclusions about a user.

    Groups conclusions by category and formats as a markdown summary.
    This can be called by the Tier 2 deep reasoning pass or on demand.

    Args:
        subject_id: User to build representation for.
        observer_id: God whose perspective to use.

    Returns:
        Markdown representation string.
    """
    conn = _get_conn()

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT category, content, confidence, created_at
            FROM conclusions
            WHERE peer_id = %s
              AND peer_type = 'user'
              AND observer_id = %s
              AND superseded_by IS NULL
            ORDER BY
                CASE category
                    WHEN 'fact' THEN 1
                    WHEN 'preference' THEN 2
                    WHEN 'commitment' THEN 3
                    WHEN 'project' THEN 4
                    WHEN 'relationship' THEN 5
                    WHEN 'environment' THEN 6
                    WHEN 'emotional' THEN 7
                    WHEN 'contradiction' THEN 8
                    WHEN 'gap' THEN 9
                END,
                confidence DESC,
                created_at DESC
            """,
            (subject_id, observer_id),
        )
        rows = cur.fetchall()

    if not rows:
        return f"# {subject_id}\n\n_No observations yet._\n"

    # Group by category
    grouped: Dict[str, List] = {}
    for row in rows:
        cat = row[0]
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append({"content": row[1], "confidence": row[2]})

    category_labels = {
        "fact": "## 📋 Facts",
        "preference": "## ⭐ Preferences",
        "commitment": "## 📅 Commitments",
        "project": "## 🏗️ Projects",
        "relationship": "## 🔗 Relationships",
        "environment": "## 💻 Environment",
        "emotional": "## 🫀 Emotional Signals",
        "contradiction": "## ⚠️ Contradictions",
        "gap": "## ❓ Knowledge Gaps",
    }

    lines = [f"# {subject_id} — {observer_id.capitalize()}'s View", ""]
    lines.append(f"_Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}_")
    lines.append("")

    for cat in ["fact", "preference", "commitment", "project", "relationship",
                 "environment", "emotional", "contradiction", "gap"]:
        if cat not in grouped:
            continue
        label = category_labels.get(cat, f"## {cat}")
        lines.append(label)
        lines.append("")
        for obs in grouped[cat]:
            conf_str = "🟢" if obs["confidence"] >= 0.9 else "🟡" if obs["confidence"] >= 0.7 else "🟠"
            lines.append(f"- {conf_str} {obs['content']}")
        lines.append("")

    return "\n".join(lines)
