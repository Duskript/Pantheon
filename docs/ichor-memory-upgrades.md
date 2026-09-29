# Ichor Memory Upgrades

## Observations vs events

`ichor_events` remains the source event log: raw facts, preferences, decisions, and relationship fragments as they were captured. `ichor_observations` is a deterministic consolidation layer over repeated similar events. An observation carries `proof_count`, exact quote sources, first/last seen timestamps, trend, confidence, and tags. It is safer for recall, but the source events remain inspectable.

## Strict tag modes

Tag filters apply before ranking/truncation.

- `any`: include rows with at least one requested tag, plus untagged rows.
- `all`: include rows with all requested tags, plus untagged rows.
- `any_strict`: include only rows with at least one requested tag.
- `all_strict`: include only rows with all requested tags.

User-scoped retrieval should use strict modes. The system never infers `user:<id>` tags unless a trusted caller supplies them.

## Budget, limit, and max_tokens

`limit` is the maximum returned result count. `budget` controls candidate effort (`low`, `mid`, `high`) before ranking. `max_tokens` caps the final payload using a deterministic estimate while preserving the top result when possible. Retrieval metadata reports `candidate_counts`, `token_budget`, `estimated_tokens_returned`, and `results_dropped_for_token_budget`.

## query_timestamp / as-of recall

`query_timestamp` asks “what was active at this time?” Rows with `valid_until` before the timestamp or `valid_from` after it are excluded. With no `query_timestamp`, recall does not wall-clock-expire facts; it only excludes inactive statuses by default.

## Knowledge pages are projections

Knowledge pages are rebuildable markdown projections from observations. They are not source of truth and can be regenerated. Updates keep version history in `ichor_knowledge_page_versions`; deleting or rebuilding a page does not mutate observations or events.

## Optional reranker

The reranker is disabled by default (`ICHOR_RERANK_ENABLED=false`). Only model-free heuristic reranking is implemented. `local_cross_encoder` is intentionally a passthrough unless a future operator explicitly wires a local model.

## Dry-run maintenance scripts

Run against a temp or staged DB first:

```bash
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_backfill_tags.py --db-path /tmp/ichor.db --dry-run --pantheon-scope
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_temporal_backfill.py --db-path /tmp/ichor.db --dry-run
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_consolidate_observations.py --db-path /tmp/ichor.db --dry-run --limit 100
```

Use `--apply` only after dry-run counts look right for tag and temporal backfills. Observation consolidation applies by omitting `--dry-run`.

## LCM boundary

Ichor stores learned state and returns source identifiers. Exact commands, paths, counts, causal chains, and transcript wording still require LCM exact references. `recall_with_ladder(require_exact=True)` returns `lcm_expand_hint` objects instead of calling LCM internally.
