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
    lib.ichor.schema_v2   — 5-tier schema (was lib.ichor_schema_v2)
    lib.ichor.llm         — LLM call helper (was lib.ichor_tier_a_plus)
    lib.ichor.entities.*  — entity-relationship graph layer

This package re-exports the schema/CRUD helpers from the underlying
modules so that `from lib.ichor.entities import migrate, validate`
works as the canonical entry point.
"""
