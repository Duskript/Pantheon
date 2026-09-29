"""Daily maintenance: decay, prune, report.

Run via cron: 0 3 * * * python3 -m lib.ichor_daily_maintenance --execute
"""

import argparse
import json
import logging
import os
from pathlib import Path

import lib.ichor_memory_score as score

logger = logging.getLogger("ichor_daily_maintenance")

# Resolve real home — $HOME may be profile-scoped in Hermes
_REAL_HOME = Path(os.environ.get("REAL_HOME", os.environ.get("HOME", "/home/konan")))
DB_PATH = _REAL_HOME / ".hermes" / "ichor.db"

# Phase 3D: recall_log retention window (days). Rows older than this are
# pruned on every maintenance run (respecting dry_run).
RECALL_LOG_RETENTION_DAYS = 90


def run(dry_run: bool = True) -> dict:
    """Run daily maintenance cycle.

    Order (per SPEC phases 2D / 3D):
      1. Phase 2D entity-resolution dry-run pre-pass — reports dedup
         candidates/merges so no profile spawns from split entities.
         (Merge application is on-demand via the ichor_entity_resolve MCP
         tool with apply=True — the SPEC's profile_compiler_cron.py hook
         does not exist yet, so the pre-pass lands here.)
      2. Standard decay + maturity + prune (existing behavior).
      3. Phase 3D recall_log 90-day retention prune (dry_run respected).
    """
    conn = score.get_db_connection(str(DB_PATH))
    score.ensure_schema(conn)

    # Phase 2D — entity resolution pre-pass (dry-run only).
    try:
        from lib.ichor.entities import entity_resolve

        er_result = entity_resolve.run(dry_run=True, db_path=DB_PATH)
    except Exception as exc:
        logger.warning("entity_resolve pre-pass failed (non-fatal): %s", exc)
        er_result = {"candidates": 0, "merges": 0, "error": str(exc)}

    decayed = score.apply_decay(conn)
    score.update_maturity(conn)
    prunable = score.prune_execute(conn, dry_run=dry_run)

    # Phase 3D — recall_log retention prune (idempotent; dry_run respected).
    from lib.ichor.schema_v2 import ensure_recall_log

    ensure_recall_log(conn)
    cutoff = f"datetime('now', '-{int(RECALL_LOG_RETENTION_DAYS)} days')"
    if dry_run:
        row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM recall_log WHERE retrieved_at < {cutoff}"
        ).fetchone()
        recall_pruned = int(row["cnt"] or 0) if row else 0
    else:
        cur = conn.execute(
            f"DELETE FROM recall_log WHERE retrieved_at < {cutoff}"
        )
        recall_pruned = int(cur.rowcount or 0)

    # Phase 8 — knowledge-page projection. Pages are rebuildable projections of
    # the observation store (see lib/ichor_knowledge_pages): deterministic, no
    # LLM, and they never write back to observations. Non-fatal by design — a
    # projection failure must not abort decay or prune.
    try:
        from lib.ichor_knowledge_pages import build_pages_from_observations

        pages_result = build_pages_from_observations(DB_PATH, dry_run=dry_run)
    except Exception as exc:
        logger.warning("knowledge-page projection failed (non-fatal): %s", exc)
        pages_result = {"pages_written": 0, "error": str(exc)}

    report = {
        "knowledge_pages": pages_result,
        "events_decayed": decayed,
        "events_pruned": prunable,
        "entity_resolve": er_result,
        "recall_log_pruned": recall_pruned,
        "recall_log_retention_days": RECALL_LOG_RETENTION_DAYS,
        "dry_run": dry_run,
    }
    logger.info(
        "Daily maintenance: %d decayed, %d pruned, %d recall_log pruned, "
        "%s knowledge page(s) projected "
        "(dry_run=%s, entity_resolve candidates=%s merges=%s)",
        decayed,
        prunable,
        recall_pruned,
        pages_result.get("pages_written", 0),
        dry_run,
        er_result.get("candidates", 0),
        er_result.get("merges", 0),
    )
    conn.close()
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually delete, not dry-run")
    parser.add_argument("--pages-only", action="store_true",
                        help="Only rebuild knowledge-page projections (no decay/prune)")
    args = parser.parse_args()

    if args.pages_only:
        from lib.ichor_knowledge_pages import build_pages_from_observations

        result = build_pages_from_observations(DB_PATH, dry_run=not args.execute)
        print(json.dumps(result, indent=2, default=str))
    else:
        run(dry_run=not args.execute)
