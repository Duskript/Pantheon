"""Entity-relationship graph layer for Ichor.

Phases:
    ER-P0 (shipped): Schema — 6 new tables, indexes, migration
    ER-P1 (shipped): Backfill extraction (L0 regex + L1 Levenshtein cluster, $0)
    ER-P2 (shipped): Incremental LLM extraction (L2, every 25 turns + finalize)
    ER-P3 (shipped): Multi-hop traversal (3 primitives + adaptive depth + bidirectional)
    ER-P4 (shipped): Dream cycle (dedup + decay + contradiction, cron)

See `lib/ichor/entities/dream.py` for the cycle orchestrator, dedup
merge logic, contradiction detection, and exponential decay.
Re-exported below as: dedup, detect_contradictions, decay,
run_dream_cycle, touch_entity.

Spec: ~/athenaeum/Codex-God-thoth/research/entity-relationship-taxonomies/ichor-entity-model-design.md

This package re-exports the schema/CRUD, extraction, L2, and traversal
helpers from the underlying modules so callers can do
`from lib.ichor.entities import migrate, validate, backfill,
extract_incremental, traverse, graph_query, traverse_between, ...`
as a canonical entry point.
"""

from lib.ichor.entities.extraction import (
    backfill,
    backfill_stats,
    cluster_l1,
    extract_l0,
    link_to_warm,
)
from lib.ichor.entities.l2_llm import (
    build_prompt,
    extract_batch,
    extract_incremental,
    finalize,
    l2_stats,
    parse_extraction,
)
from lib.ichor.entities.schema import (
    DB_PATH,
    SCHEMA_TABLES,
    get_conn,
    migrate,
    rollback,
    status,
    validate,
)
from lib.ichor.entities.dream import (
    decay,
    dedup,
    detect_contradictions,
    run_dream_cycle,
    touch_entity,
)
from lib.ichor.entities.traversal import (
    format_meeting_path,
    format_path,
    graph_query,
    resolve_depth,
    traverse,
    traverse_between,
)

# Public surface: callers can `from lib.ichor.entities import run_dream_cycle`
# and run the daily dedup+contradiction or weekly decay tick.

__all__ = [
    # schema
    "DB_PATH",
    "SCHEMA_TABLES",
    "get_conn",
    "migrate",
    "rollback",
    "status",
    "validate",
    # extraction (ER-P1)
    "extract_l0",
    "cluster_l1",
    "link_to_warm",
    "backfill",
    "backfill_stats",
    # l2_llm (ER-P2)
    "build_prompt",
    "parse_extraction",
    "extract_batch",
    "extract_incremental",
    "finalize",
    "l2_stats",
    # traversal (ER-P3)
    "traverse",
    "graph_query",
    "traverse_between",
    "resolve_depth",
    "format_path",
    "format_meeting_path",
    # ER-P4 dream cycle: dedup, contradiction detection, exponential decay.
    # `run_dream_cycle` is the cron entry point. `touch_entity` updates
    # `last_accessed` so decay knows which edges are still in use.
    "dedup",
    "detect_contradictions",
    "decay",
    "run_dream_cycle",
    "touch_entity",
]
