# Ichor + Athenaeum God-Aware Retrieval Build Spec v1

**Created:** 2026-06-21  
**Owner for implementation:** Hephaestus  
**Author:** Hermes  
**Repo:** `/home/konan/pantheon`  
**Status:** Ready for implementation planning / Hephaestus execution

## Goal

Make Ichor + Athenaeum retrieval fast, observable, validated, and god-aware so each god receives the minimum correct context needed for their role and task phase.

The target API shape is:

```python
ichor_context_pack(query, god_name, phase, task_type="", max_items=8)
```

The pack must return role-specific context, source evidence, coverage/observability metadata, and stale/low-confidence warnings.

## North Star

Current memory retrieval mostly answers:

> What matches this query?

The desired system answers:

> What does this god, in this task phase, need to know right now, and how confident are we that the visible context covers the underlying evidence?

## Key Article Principle

The motivating RAG article is about **Error Observability Collapse**: larger context can make wrong/partial retrieval look authoritative. The fixes below must make retrieval failure modes visible.

Important distinction:

- Retrieval failures should return partial context with coverage warnings.
- Computation/aggregation failures should fail loud.
- Low coverage should never silently suppress god awareness.

## Correct Current Paths

Do **not** use stale audit paths like `athenaeum/tools/ichor_retrieve.py` or `athenaeum/tools/ichor_graph_query.py`; they do not exist after consolidation.

Current implementation paths:

```text
/home/konan/pantheon/lib/ichor_hybrid.py
/home/konan/pantheon/lib/ichor_subconscious.py
/home/konan/pantheon/lib/ichor/entities/schema.py
/home/konan/pantheon/lib/ichor/entities/traversal.py
/home/konan/pantheon/lib/ichor/entities/graph_query.py
/home/konan/pantheon/lib/ichor/schema_v2.py
/home/konan/pantheon/pantheon-core/mcp_server.py
/home/konan/.hermes/ichor.db
```

Active vector backend:

```text
sqlite-vec / vec0
DB: /home/konan/.hermes/ichor.db
Table: event_embeddings(event_id INTEGER PRIMARY KEY, embedding float[384])
```

ChromaDB is legacy/unused for active vector retrieval and must not be used as the vector-health signal.

---

# Build Order

## Phase 0 — Baseline Tests and Fixtures

### Objective

Add failing/guardrail tests before changing retrieval behavior.

### Files

Create or modify:

```text
tests/test_ichor_retrieval_observability.py
tests/test_ichor_graph_validated_only.py
tests/test_ichor_graph_traversal_bounded.py
tests/test_ichor_context_pack.py
tests/fixtures/ichor_golden_queries.yaml
```

### Required golden queries

```yaml
- query: "Conductor v2"
  god: "hephaestus"
  phase: "debug"
  must_include:
    - "NATS"
    - "MCP"
    - "endpoint"
    - "systemd"
  must_not_top3:
    - "generic INDEX.md"
    - "unhydrated vector"

- query: "Conductor v2"
  god: "thoth"
  phase: "research"
  must_include:
    - "workflow"
    - "cross-god"
    - "routing"
  must_not_top3:
    - "raw test fixture"
    - "unhydrated vector"

- query: "Pantheon pricing managed retainer dedicated infrastructure"
  god: "rheta"
  phase: "copywriting"
  must_include:
    - "$5k"
    - "managed"
    - "dedicated infrastructure"
  must_not_top3:
    - "no subscriptions"
    - "self-hosted"
```

### Acceptance Criteria

- [ ] Tests can run under `cd /home/konan/pantheon && PYTHONPATH=/home/konan/pantheon pytest ...`.
- [ ] At least one baseline test demonstrates current graph/retrieval weakness before implementation.
- [ ] Golden-query fixture distinguishes Hephaestus and Thoth expectations for the same query.
- [ ] Tests do not require a service restart.

---

## Phase 1 — Validated-Only Graph Results

### Objective

Prevent graph answers from summarizing through provisional/unvalidated L2 entities and relationships by default.

This is the highest correctness win because unvalidated graph relationships are exactly the kind of source that creates authoritative-looking wrong answers.

### Files

Likely touch:

```text
lib/ichor/entities/schema.py
lib/ichor/entities/graph_query.py
lib/ichor/entities/traversal.py
pantheon-core/mcp_server.py
```

Also inspect:

```text
lib/ichor/schema_v2.py
```

### Implementation Notes

There are two entity layers:

| Layer | Table | Validation field |
|---|---|---|
| ER layer | `entities`, `relationships` | `provisional` |
| WARM v2 layer | `warm_entities` | `maturity` |

Default graph behavior must be validated-only:

```sql
entities.provisional = 0
relationships.provisional = 0
```

For warm fallback:

```sql
warm_entities.maturity = 'validated'
```

Add explicit opt-in flag only if needed:

```python
include_provisional: bool = False
```

### Response Metadata

Graph responses should include:

```json
{
  "validation_scope": "validated_only",
  "validated_entities_used": 0,
  "provisional_entities_skipped": 0,
  "validated_relationships_used": 0,
  "provisional_relationships_skipped": 0
}
```

### Acceptance Criteria

- [ ] `ichor_graph_query` excludes provisional ER entities/relationships by default.
- [ ] Warm fallback excludes non-validated warm entities by default.
- [ ] Provisional inclusion requires an explicit option and is labeled in response.
- [ ] Graph response reports skipped provisional counts.
- [ ] Tests cover both validated and provisional rows.

---

## Phase 2 — Bounded Graph Traversal / Timeout Fix

### Objective

Replace the timeout-prone recursive CTE traversal with bounded indexed traversal.

### Current Problem

Current traversal shape includes an `OR` join like:

```sql
r.source_id = t.node_id OR r.target_id = t.node_id
```

SQLite plans this poorly and scans active relationships through `idx_relationships_valid_to` instead of using source/target indexes.

For dense entities like `Conductor v2`, prefix resolution can produce many starts, and depth 2 fanout explodes before final `LIMIT` applies.

### Files

Likely touch:

```text
lib/ichor/entities/traversal.py
lib/ichor/entities/graph_query.py
pantheon-core/mcp_server.py
```

### Implementation Shape

Add ID-based entrypoint:

```python
def graph_query_by_id(
    conn,
    entity_id: int,
    *,
    depth: int = 1,
    min_confidence: float = 0.3,
    max_nodes: int = 100,
    max_edges: int = 200,
    fanout: int = 50,
    timeout_ms: int = 1500,
    include_provisional: bool = False,
) -> dict:
    ...
```

Use Python BFS with indexed SQL:

```sql
SELECT *
FROM relationships
WHERE source_id = ?
  AND valid_to IS NULL
  AND confidence >= ?
ORDER BY confidence DESC, weight DESC
LIMIT ?
```

and:

```sql
SELECT *
FROM relationships
WHERE target_id = ?
  AND valid_to IS NULL
  AND confidence >= ?
ORDER BY confidence DESC, weight DESC
LIMIT ?
```

Do **not** use the `source_id OR target_id` join in the hot path.

### MCP Wrapper Change

Resolve query to a canonical entity ID, then call ID-based graph query.

Avoid this pattern:

```text
query -> resolved name -> graph_query(name) -> internal LIKE expansion to many starts
```

Use:

```text
query -> resolved entity_id -> graph_query_by_id(entity_id)
```

### Acceptance Criteria

- [ ] `ichor_graph_query("Conductor v2", hops=1)` completes without MCP hard timeout.
- [ ] Default graph depth is 1.
- [ ] Depth 2 is bounded by `max_nodes`, `max_edges`, `fanout`, and `timeout_ms`.
- [ ] If timeout is reached, return `partial: true` with partial nodes/edges.
- [ ] Query starts from canonical entity ID, not multiple fuzzy-prefix starts.
- [ ] Tests prove traversal uses source/target-index-friendly queries.

---

## Phase 3 — Retrieval Coverage / `total_matching`

### Objective

Make retrieval coverage observable. Returned result count must be separate from total matching candidates.

Current behavior often reports:

```json
"total": 5
```

But this means returned results, not all matching evidence. That hides low-coverage answers.

### Files

Likely touch:

```text
lib/ichor_hybrid.py
pantheon-core/mcp_server.py
```

Possibly add helper module:

```text
lib/ichor/retrieval_coverage.py
```

### Required Response Shape

Add coverage block:

```json
{
  "returned": 10,
  "total_matching": 142,
  "coverage_pct": 7.04,
  "coverage_confidence": "known",
  "by_backend": {
    "fts5": {"returned": 5, "total_matching": 47, "coverage_pct": 10.64},
    "vector": {"returned": 3, "total_matching": 60, "coverage_pct": 5.0},
    "events": {"returned": 2, "total_matching": 35, "coverage_pct": 5.71}
  }
}
```

If a backend cannot cheaply count:

```json
{"total_matching": null, "coverage_confidence": "unknown"}
```

Do not fabricate counts.

### Backend Counting Notes

Each backend has a different count mechanism:

- FTS5: FTS query count over `memory_fts` / current FTS table.
- Vector: count above/under a configured distance threshold if feasible; otherwise unknown.
- Events: normal SQL count.
- Graph: count traversed/eligible edges/nodes within bound, not global graph count.
- Reference/Athenaeum: count matched docs if query implementation supports it, otherwise unknown.

### Logging

Add coverage to retrieval log JSONL if such logging exists, so Forge/Dojo can tune weights later.

### Acceptance Criteria

- [ ] MCP `ichor_retrieve` returns `returned` and `total_matching` separately.
- [ ] Per-backend coverage appears in response.
- [ ] Unknown coverage is explicit, not silently treated as 100%.
- [ ] Tests prove `total` no longer masquerades as total matching evidence.

---

## Phase 4 — Vector Hydration and Safer Ranking

### Objective

Vector hits must be inspectable before they can win. No unhydrated vector result should rank highly.

### Files

Likely touch:

```text
lib/ichor_hybrid.py
lib/ichor/vector_backend.py
```

Optional new helper:

```text
lib/ichor/retrieval_hydration.py
```

### Implementation Shape

Hydrate vector `event_id`s from cold events in one batch:

```sql
SELECT
  id,
  event_type,
  category,
  name,
  raw_text,
  brief,
  god_name,
  session_id,
  created_at,
  importance,
  confidence,
  trust
FROM cold_events
WHERE id IN (...)
```

Pipeline should be:

```text
collect candidates
hydrate candidates
infer metadata
score/rerank
dedupe
return
```

### Ranking Adjustments

Baseline weights should prefer exact/current evidence over semantic neighbors.

Suggested starting weights:

```python
WEIGHTS = {
    "fts5": 0.40,
    "vector": 0.20,
    "graph": 0.15,
    "events": 0.15,
    "reference": 0.10,
}
```

Add rank modifiers:

| Condition | Effect |
|---|---:|
| exact phrase/title match | boost |
| current decision/correction/hard rule | boost |
| spec/roadmap/distilled doc | boost |
| vector hit with hydrated snippet | allowed |
| vector hit with null snippet | heavy penalty |
| noisy line fragment | penalty |
| stale/superseded | penalty |
| generic `INDEX.md` | penalty unless index query |

### Rank Reasons

Each result should include:

```json
"rank_reasons": ["hydrated_vector", "decision_boost", "exact_phrase_match"]
```

### Acceptance Criteria

- [ ] Vector hits include snippet/source metadata when corresponding cold event exists.
- [ ] Vector hit with null snippet cannot rank #1 unless no better evidence exists.
- [ ] Exact decision/correction outranks vague semantic neighbor.
- [ ] Rank reasons are visible in returned results.

---

## Phase 5 — Subconscious Coverage Banner

### Objective

Make low-coverage per-god subconscious ticks visible without suppressing delivery.

### Files

Likely touch:

```text
lib/ichor_subconscious.py
/home/konan/.hermes/scripts/ichor_subconscious.py  # wrapper/entrypoint if needed
```

### Current Known Fields

Tick already reports per god:

```text
events_found
delivered
report_length
```

Add:

```text
events_expected
coverage_pct
coverage_label
```

### Design Rule

Do **not** refuse/suppress summaries when coverage is low.

Instead add visible banner and degrade gracefully:

```markdown
[LOW COVERAGE]
Only 3 events found for Hephaestus in this window.
Expected baseline: 15.
Coverage: 20%.
Summary degraded to raw-event digest.
```

### Acceptance Criteria

- [ ] Tick report includes `events_found`, `events_expected`, `coverage_pct`, and `coverage_label`.
- [ ] Low coverage adds a banner.
- [ ] Low coverage still delivers a report.
- [ ] Low coverage degrades to raw-event digest / thin synthesis.
- [ ] Tests cover zero events, low events, and normal events.

---

## Phase 6 — Athenaeum Ranking Fix

### Objective

Athenaeum search should return durable content, not generic index/navigation files, unless the user asks for an index.

### Files

Likely touch:

```text
pantheon-core/mcp_server.py
```

Possibly Athenaeum helper modules if search is factored elsewhere.

### Ranking Rules

Penalize:

```text
INDEX.md
navigation-only docs
generic codex listings
```

Unless query contains:

```text
index
codex
inventory
list
overview
```

Boost paths containing:

```text
/distilled/
/specs/
/plans/
/reports/
/sessions/
/shared/active/
/shared/decisions/
```

### Acceptance Criteria

- [ ] Non-index query does not return generic `INDEX.md` in top 3.
- [ ] Query asking for index/codex inventory can return `INDEX.md`.
- [ ] Result includes source path and evidence snippet.
- [ ] Conductor v2 endpoint query prefers spec/report/session/decision content.

---

## Phase 7 — God Metadata and Context Profiles

### Objective

Create the role/domain layer required for god-aware retrieval without rewriting every vector.

### Files

Create:

```text
config/context-profiles/hermes.yaml
config/context-profiles/hephaestus.yaml
config/context-profiles/thoth.yaml
config/context-profiles/iris.yaml
config/context-profiles/marvin.yaml
config/context-profiles/rheta.yaml
lib/ichor/retrieval_metadata.py
lib/ichor/god_context_profiles.py
```

### Metadata Inference

Add deterministic functions. No LLM in hot path.

```python
def infer_domains(result: dict) -> set[str]: ...
def infer_phase_tags(result: dict) -> set[str]: ...
def infer_authority(result: dict) -> float: ...
def infer_noise_score(result: dict) -> float: ...
def infer_source_type(result: dict) -> str: ...
```

### Example Hephaestus Profile

```yaml
god: hephaestus
role: engineering_builder
primary_domains:
  - engineering
  - architecture
  - code
  - deployment
  - testing
  - debugging
interested_in:
  - product
  - business_constraints
  - customer_data
preferred_event_types:
  - decision
  - blocker
  - reference
  - commitment
preferred_sources:
  - Codex-Forge
  - Codex-Pantheon/specs
  - Codex-Pantheon/plans
  - shared/active
  - shared/decisions
deprioritize:
  - marketing_trends
  - broad_research
  - raw_social_signal
always_include_if_relevant:
  - hard_rule
  - correction
  - active_goal
  - customer_data_sovereignty
  - pricing_constraint
```

### Example Thoth Profile

```yaml
god: thoth
role: research_synthesis
primary_domains:
  - research
  - synthesis
  - strategy
  - external_signal
  - monitoring
interested_in:
  - architecture
  - product
  - operations
preferred_event_types:
  - insight
  - reference
  - digest_entry
  - decision
preferred_sources:
  - Codex-Distilled
  - Codex-Agent
  - Codex-Pantheon/research
  - shared/DIGEST.md
  - last30days
deprioritize:
  - low_level_code_fragment
  - raw_test_output
  - implementation_minutiae
always_include_if_relevant:
  - active_goal
  - current_decision
  - blocker
  - correction
```

### Acceptance Criteria

- [ ] Profiles exist for Hermes, Hephaestus, Thoth, Iris, Marvin, Rheta.
- [ ] Missing profile falls back to Hermes/default.
- [ ] Results can be annotated with domains, phase tags, authority, source type, and noise score.
- [ ] No vector rewrite/backfill required for runtime correctness.

---

## Phase 8 — God-Aware Reranking

### Objective

Same query should rank differently for different gods and phases.

### Files

Create:

```text
lib/ichor/god_aware_ranking.py
```

Modify:

```text
lib/ichor_hybrid.py
pantheon-core/mcp_server.py
```

### Function Shape

```python
def rerank_for_god(
    results: list[dict],
    *,
    god_name: str,
    phase: str = "",
    task_type: str = "",
    limit: int = 8,
) -> list[dict]:
    ...
```

### Suggested Score

```python
final_score = (
    base_relevance * 0.35
    + authority * 0.20
    + god_domain_match * 0.20
    + phase_match * 0.15
    + freshness * 0.05
    + graph_proximity * 0.05
    - noise_penalty
    - stale_penalty
)
```

### Design Rule

Use weighted relevance, not hard walls.

Hephaestus should see engineering first, but still see business/customer constraints when they affect implementation. Thoth should see research/synthesis first, but still see operational facts when needed.

### Acceptance Criteria

- [ ] Existing `ichor_retrieve(query, limit)` remains backward-compatible.
- [ ] `god_name="hephaestus"` boosts build/debug/test/deployment context.
- [ ] `god_name="thoth"` boosts research/synthesis/strategy context.
- [ ] Results include `god_score`, `domain_match`, and `rank_reasons`.
- [ ] Golden queries prove different ordering for Hephaestus vs Thoth.

---

## Phase 9 — `ichor_context_pack`

### Objective

Return compact context packs, not raw search piles.

### Files

Create:

```text
lib/ichor/context_pack.py
```

Modify:

```text
pantheon-core/mcp_server.py
```

### Function Shape

```python
def build_context_pack(
    query: str,
    *,
    god_name: str,
    phase: str = "",
    task_type: str = "",
    max_items: int = 8,
    include_graph: bool = True,
) -> dict:
    ...
```

### Output Shape

```json
{
  "query": "...",
  "god": "hephaestus",
  "phase": "build",
  "coverage": {},
  "current_decisions": [],
  "hard_constraints": [],
  "relevant_files": [],
  "risks": [],
  "related_entities": [],
  "recent_changes": [],
  "source_links": [],
  "omitted": {
    "count": 12,
    "reasons": ["low_authority", "noisy", "stale"]
  }
}
```

### MCP Tool

Add MCP wrapper:

```python
ichor_context_pack(query, god_name="", phase="", task_type="", max_items=8)
```

### Acceptance Criteria

- [ ] Hephaestus context pack for `Conductor v2` includes implementation/debug/service context.
- [ ] Thoth context pack for `Conductor v2` includes strategic/synthesis/architecture context.
- [ ] Pack contains coverage metadata.
- [ ] Pack warns on low coverage or unknown coverage.
- [ ] Every claim has source evidence/path/id.
- [ ] No unhydrated vector-only item appears as a primary context item.

---

## Phase 10 — Alias Expansion, After Coverage Data

### Objective

Add synonym/alias expansion only after coverage logs show actual vocabulary-mismatch failures.

### Do Not Do First

Do not seed broad aliases blindly. Aliases can improve recall but damage precision.

Example risk:

```text
conductor -> dispatch
```

`dispatch` appears in many unrelated contexts.

### Future Table

```sql
CREATE TABLE IF NOT EXISTS term_aliases (
  term TEXT NOT NULL,
  alias TEXT NOT NULL,
  domain TEXT DEFAULT '',
  active INTEGER DEFAULT 1,
  reviewed_by TEXT DEFAULT '',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(term, alias, domain)
);
```

### Acceptance Criteria

- [ ] Aliases are versioned/reviewable.
- [ ] Expanded terms appear in rank reasons.
- [ ] Precision regression is tested before enabling broad aliases.
- [ ] Alias additions are based on logged low-coverage/missed-query data.

---

## Phase 11 — QueryRouter / Computation vs Retrieval

### Objective

Implement the article's deeper point: route computation/aggregation queries away from semantic retrieval.

### Defer Until

Do this after Phases 1-9 are landed and stable.

### Files

Future module:

```text
lib/ichor/query_router.py
```

### Route Types

```python
COMPUTATION
RETRIEVAL
GRAPH
DOC_LOOKUP
SYNTHESIS
MIXED
```

### Examples

| Query | Route |
|---|---|
| "What did we decide about pricing?" | RETRIEVAL |
| "How many decisions did Thoth make this week?" | COMPUTATION |
| "Which gods touched Conductor v2?" | GRAPH/COMPUTATION |
| "Summarize recent AI agent ecosystem changes" | RETRIEVAL + SYNTHESIS |
| "List all active blockers" | COMPUTATION over structured events |

### Acceptance Criteria

- [ ] Count/list/sum queries use deterministic SQL/graph computation where possible.
- [ ] Computation failures fail loud.
- [ ] Retrieval failures return partial context with coverage.
- [ ] Mixed routes expose which parts are computed vs retrieved.

---

# Execution Batches

## Batch A — Graph correctness and reliability

1. Phase 0 baseline tests for graph.
2. Phase 1 validated-only graph filter.
3. Phase 2 bounded graph BFS.

Exit gate:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest tests/test_ichor_graph_validated_only.py tests/test_ichor_graph_traversal_bounded.py -q
```

## Batch B — Retrieval observability and quality

1. Phase 3 coverage / `total_matching`.
2. Phase 4 vector hydration + safer ranking.
3. Phase 6 Athenaeum ranking fix.

Exit gate:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest tests/test_ichor_retrieval_observability.py -q
```

## Batch C — Subconscious coverage

1. Phase 5 coverage banner.

Exit gate:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest tests/test_ichor_subconscious* -q
```

If no matching tests exist, create targeted tests for `lib/ichor_subconscious.py`.

## Batch D — God-aware context

1. Phase 7 metadata/profiles.
2. Phase 8 reranker.
3. Phase 9 context pack.

Exit gate:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest tests/test_ichor_context_pack.py tests/test_ichor_retrieval_observability.py -q
```

## Batch E — Later architecture

1. Phase 10 alias expansion after data.
2. Phase 11 QueryRouter.

Do not start Batch E until previous batches are stable.

---

# Hephaestus Implementation Rules

1. Read the current files before editing. Do not trust stale audit paths.
2. Do not restart Hermes gateway or god-profile processes without Konan approval.
3. Do not treat ChromaDB as active vector health.
4. Do not use an LLM in the hot retrieval path.
5. Use deterministic scoring/metadata inference first.
6. Keep vector DB as candidate finder, not final judge.
7. Prefer small testable commits/batches.
8. Surface unknown coverage explicitly; never fake counts.
9. Low coverage should warn/degrade, not suppress delivery.
10. Validated-only graph results are the default.

---

# Definition of Done

This build is complete when:

- [ ] Graph query no longer hard-times out on dense entities like `Conductor v2`.
- [ ] Graph defaults to validated-only entities/relationships.
- [ ] Retrieval response distinguishes returned vs total matching evidence.
- [ ] Vector hits are hydrated before they can rank highly.
- [ ] Athenaeum search demotes generic index docs unless requested.
- [ ] Subconscious reports display low-coverage banners without suppressing delivery.
- [ ] Hephaestus and Thoth receive different context ordering for the same query.
- [ ] `ichor_context_pack` returns compact, sourced, god-aware packs.
- [ ] Golden-query tests prove the behavior.

Primary verification command set:

```bash
cd /home/konan/pantheon
export PYTHONPATH=/home/konan/pantheon
pytest tests/test_ichor_graph_validated_only.py -q
pytest tests/test_ichor_graph_traversal_bounded.py -q
pytest tests/test_ichor_retrieval_observability.py -q
pytest tests/test_ichor_context_pack.py -q
```

If tests are newly created during this work, update this spec or the handoff with the final exact test paths.

---

# Handoff Prompt for Hephaestus

Hephaestus, implement the build spec at:

```text
/home/konan/pantheon/plans/ichor-athenaeum-god-aware-retrieval-build-spec-v1.md
```

Start with Batch A only unless Konan explicitly asks you to continue. The highest-priority fixes are validated-only graph results and bounded graph traversal. Use the actual consolidated paths under `/home/konan/pantheon/lib/` and `/home/konan/pantheon/pantheon-core/mcp_server.py`; ignore stale audit paths under `athenaeum/tools/`. Do not restart running Hermes gateway/god-profile processes without asking Konan.
