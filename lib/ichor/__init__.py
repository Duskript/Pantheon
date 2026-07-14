"""Ichor entities — entity-relationship graph memory layer.

Additive module: does not modify any existing Ichor table or file.
Built on top of the 5-tier schema in `lib.ichor.schema_v2` (moved from
`lib.ichor_schema_v2` 2026-06-12 as part of the package refactor).

Public surface (added in later phases):
    ER-P1: extract_from_cold_events(), L0 regex, L1 pattern clustering
    ER-P2: extract_from_turns(), L2 LLM extraction (uses lib.ichor.llm)
    ER-P3: traverse(), graph_query(), traverse_between()
    ER-P4: dream_cycle_dedup(), dream_cycle_decay()

Package contents (after 2026-06-12 refactor):
    lib.ichor.schema_v2      — 5-tier schema (was lib.ichor_schema_v2)
    lib.ichor.llm            — LLM call helper (was lib.ichor_tier_a_plus)
    lib.ichor.entities.*     — entity-relationship graph layer
    lib.ichor.migrations.*   — idempotent schema migrations (v2_temporal, ...)

This package re-exports the schema/CRUD helpers from the underlying
modules so that `from lib.ichor.entities import migrate, validate`
works as the canonical entry point.

Ichor V2 migrations (ichor-v2-build-blueprint.md §2 onwards) are exposed
at the package root for convenient invocation:

    from lib.ichor import run_migration
    run_migration()           # applies the latest pending migration
    run_migration.status()    # inspect current state without applying
"""

# Re-exports
# Each migration is reachable by its full path; v2_temporal was the
# canonical "latest pending" entry point as of P0. The backfill
# migration (v2_temporal_backfill) was added 2026-06-21 as P0b and
# must be invoked explicitly so it doesn't auto-fire and surprise
# callers expecting only the original column-add.
# The l2_scenarios migration (P5d, 2026-06-21) creates the L2 Scenario
# table that the Overnight Forge writes to. Same pattern — explicit
# invocation, no auto-fire.
from lib.ichor.migrations.v2_temporal import run_migration  # noqa: F401
from lib.ichor.migrations.v2_temporal_backfill import (  # noqa: F401
    run_migration as run_backfill,
)
from lib.ichor.migrations.v2_l2_scenarios import (  # noqa: F401
    run_migration as run_l2_scenarios_migration,
)
from lib.ichor.contracts import Claim, ClaimEntity, ClaimStore, Evidence  # noqa: F401
from lib.ichor.vector_backend import EmbeddingProvider, get_embedding  # noqa: F401
