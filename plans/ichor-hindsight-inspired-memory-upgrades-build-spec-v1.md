# Ichor Hindsight-Inspired Memory Upgrades Build Spec v1

**Created:** 2026-08-06  
**Owner for implementation:** Hephaestus  
**Author:** Thoth  
**Repo root:** `/home/konan/pantheon`  
**Research source:** `/home/konan/athenaeum/Codex-God-thoth/research/hindsight-ichor-source-dive/report.md`  
**Status:** Ready for implementation planning / Hephaestus execution

---

## Goal

Upgrade Ichor from a mostly fragment-retrieval substrate into a scoped, evidence-grounded, time-aware learned-memory substrate while preserving Ichor's current local-first strengths.

The target is **not** to replace Ichor with Hindsight. The target is to lift the durable Hindsight design patterns that fit Pantheon:

1. evidence-grounded observation consolidation,
2. strict tag/scope filtering,
3. budgeted and time-aware recall controls,
4. standing knowledge pages generated from observations,
5. optional high-budget reranking behind a feature flag,
6. deterministic retrieval ladder that hands off to LCM for exact source expansion.

---

## North Star

Current Ichor mostly answers:

> What stored event fragments match this query?

The upgraded Ichor should answer:

> What scoped, current, evidence-backed belief or source does this god need, and how do we inspect the evidence behind it?

---

## Non-Goals

Do **not** do any of the following in this build:

- Do not vendor or import Hindsight as a dependency.
- Do not restore always-on ChromaDB/pgvector/vector retrieval as the default path.
- Do not add a second autonomous reflect agent inside Ichor.
- Do not make knowledge pages a source of truth. They are rebuildable projections from observations.
- Do not remove the existing `ichor_events` table or break existing `ichor_store`, `ichor_retrieve`, `ichor_forget`, or `ichor_health` callers.
- Do not weaken LCM exact-evidence discipline. Ichor stores learned state; LCM provides exact transcript/source proof.

---

## Current Implementation Anchors

Use these live paths as the implementation substrate:

```text
/home/konan/pantheon/schemas/ichor-events.sql
/home/konan/pantheon/lib/ichor_db.py
/home/konan/pantheon/lib/ichor_hybrid.py
/home/konan/pantheon/lib/ichor_mcp.py
/home/konan/pantheon/lib/ichor_memory_score.py
/home/konan/pantheon/lib/ichor_patterns.py
/home/konan/pantheon/lib/ichor_tier_a.py
/home/konan/pantheon/lib/ichor_daily_maintenance.py
/home/konan/pantheon/lib/ichor/reconcile.py
/home/konan/pantheon/lib/ichor/retrieval_hydration.py
/home/konan/pantheon/lib/ichor/retrieve_fusion.py
/home/konan/pantheon/lib/user_observations.py
/home/konan/pantheon/database/schema.sql
/home/konan/.hermes/ichor.db
/home/konan/.hermes/pantheon/graph.db
```

Existing tests to preserve and extend:

```text
/home/konan/pantheon/tests/test_ichor_foundation.py
/home/konan/pantheon/tests/test_ichor_tier_a.py
/home/konan/pantheon/tests/test_ichor_b2_tiered_retrieval.py
/home/konan/pantheon/tests/test_ichor_b4_advanced_retrieval.py
/home/konan/pantheon/tests/test_ichor_c1_outcome_and_contradiction.py
/home/konan/pantheon/tests/test_ichor_c2_weights_and_benchmarks.py
/home/konan/pantheon/tests/test_ichor_context_pack.py
/home/konan/pantheon/tests/test_ichor_embedding_service.py
/home/konan/pantheon/tests/test_ichor_forge.py
/home/konan/pantheon/tests/test_ichor_graph_traversal_bounded.py
/home/konan/pantheon/tests/test_ichor_graph_validated_only.py
/home/konan/pantheon/tests/test_ichor_mcp.py
/home/konan/pantheon/tests/test_ichor_memory_score.py
/home/konan/pantheon/tests/test_ichor_observability.py
/home/konan/pantheon/tests/test_ichor_retrieval_observability.py
/home/konan/pantheon/tests/test_ichor_temporal_backfill.py
/home/konan/pantheon/tests/test_ichor_v2_phase3_provenance.py
/home/konan/pantheon/tests/test_ichor_vector_hydration.py
```

---

## Desired Final Public API Shape

### Python trait API

Existing callers keep working:

```python
MemoryTrait().retrieve(query="Conductor", limit=10, backends="fts5,events")
```

New callers can opt into richer recall:

```python
MemoryTrait().retrieve(
    query="Konan architecture preference for auth/session scraping",
    limit=10,
    backends="observations,fts5,events,graph",
    budget="mid",
    max_tokens=4096,
    types=["observation", "event", "entity"],
    include_sources=False,
    include_raw=False,
    prefer_observations=True,
    query_timestamp="2026-08-06T00:00:00Z",
    tags=["user:konan", "scope:pantheon"],
    tags_match="any_strict",
    min_scores={"final": 0.0},
)
```

### MCP API

`ichor_retrieve` should accept the new fields while keeping old fields stable:

```json
{
  "query": "...",
  "limit": 10,
  "backends": "observations,fts5,events,graph",
  "budget": "mid",
  "max_tokens": 4096,
  "types": ["observation", "event", "entity"],
  "include_sources": false,
  "include_raw": false,
  "prefer_observations": true,
  "query_timestamp": "2026-08-06T00:00:00Z",
  "tags": ["user:konan"],
  "tags_match": "any_strict",
  "min_scores": {"final": 0.0}
}
```

### Result shape

Every enriched result should be inspectable:

```json
{
  "id": "observation:42",
  "backend": "observations",
  "type": "observation",
  "title": "Konan prefers event-driven over polling",
  "snippet": "Konan prefers event-driven architectures where LLMs fire only when a reply is needed.",
  "score": 0.91,
  "confidence": 0.88,
  "proof_count": 6,
  "trend": "stable",
  "status": "active",
  "first_seen": "2026-06-01T00:00:00Z",
  "last_seen": "2026-08-02T00:00:00Z",
  "source_ids": ["fts5:123", "conclusion:456"],
  "source": "ichor_observations",
  "god_name": "thoth",
  "tags": ["user:konan", "scope:pantheon"],
  "rank_reasons": ["observation", "proof_count:6", "strict_tags"]
}
```

---

## Build Order

## Phase 0 — Baseline, Guardrails, and Spec Fixtures

### Objective

Add failing/guardrail tests and fixtures before changing retrieval behavior.

### Files

Create:

```text
tests/test_ichor_hindsight_upgrades_phase0.py
tests/fixtures/ichor_hindsight_upgrade_events.yaml
```

Modify only if needed:

```text
tests/conftest.py
```

### Fixture contents

Create deterministic events covering all new behavior:

```yaml
- id: repeated_preference_1
  session_id: s1
  event_type: preference
  subject: Konan
  predicate: prefers
  object: event-driven over polling
  confidence: 0.9
  raw_text: "Konan prefers event-driven over polling. LLMs should only fire when a reply is needed."
  god_name: thoth
  tags: ["user:konan", "scope:pantheon", "topic:architecture"]
  created_at: "2026-08-01T00:00:00Z"

- id: repeated_preference_2
  session_id: s2
  event_type: preference
  subject: Konan
  predicate: prefers
  object: event-driven triggers instead of polling loops
  confidence: 0.85
  raw_text: "The preference is event-driven over polling: no babysitting loops."
  god_name: hermes
  tags: ["user:konan", "scope:pantheon", "topic:architecture"]
  created_at: "2026-08-02T00:00:00Z"

- id: other_user_leak_guard
  session_id: s3
  event_type: preference
  subject: OtherUser
  predicate: prefers
  object: polling loops
  confidence: 0.9
  raw_text: "OtherUser prefers polling loops."
  god_name: thoth
  tags: ["user:other", "scope:pantheon"]
  created_at: "2026-08-02T00:00:00Z"

- id: stale_fact
  session_id: s4
  event_type: fact
  subject: Suno cookie
  predicate: status
  object: stale
  confidence: 0.8
  raw_text: "The Suno cookie is stale."
  god_name: hermes
  tags: ["user:konan", "project:suno"]
  created_at: "2026-08-01T00:00:00Z"
  valid_until: "2026-08-01T12:00:00Z"

- id: superseding_fact
  session_id: s5
  event_type: fact
  subject: Suno cookie
  predicate: status
  object: refreshed
  confidence: 0.8
  raw_text: "The Suno cookie was refreshed via in-app login."
  god_name: hermes
  tags: ["user:konan", "project:suno"]
  created_at: "2026-08-02T00:00:00Z"
  valid_from: "2026-08-02T00:00:00Z"
```

### Baseline tests

Tests should initially establish current gaps or new expected behavior behind skipped markers.

Required tests:

```python
def test_existing_ichor_retrieve_old_signature_still_works(temp_ichor_db): ...

def test_hindsight_upgrade_fixture_loads(temp_ichor_db): ...

def test_strict_tags_expected_to_exclude_other_user(temp_ichor_db): ...

def test_observation_expected_to_consolidate_repeated_preference(temp_ichor_db): ...

def test_temporal_query_expected_to_exclude_expired_fact(temp_ichor_db): ...
```

### Acceptance Criteria

- [ ] Test fixture can load into a temp Ichor DB without touching `/home/konan/.hermes/ichor.db`.
- [ ] Old `MemoryTrait().retrieve(query, limit, backends)` still has a passing baseline test.
- [ ] New expected behavior tests are present before implementation.
- [ ] Tests run with:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest tests/test_ichor_hindsight_upgrades_phase0.py -q
```

---

## Phase 1 — Schema Extension: Tags, Temporal Fields, Observations, Knowledge Pages

### Objective

Extend the SQLite schema in a backward-compatible way. No retrieval behavior changes yet except insert/read helpers.

### Files

Modify:

```text
schemas/ichor-events.sql
lib/ichor_db.py
```

Create:

```text
lib/ichor_tags.py
lib/ichor_temporal.py
lib/ichor_observations.py
lib/ichor_knowledge_pages.py
```

Tests:

```text
tests/test_ichor_hindsight_schema.py
```

### Schema additions

Append these tables and columns to `schemas/ichor-events.sql` using `CREATE ... IF NOT EXISTS` plus migration-safe `ALTER TABLE` handling in Python. SQLite cannot do `ADD COLUMN IF NOT EXISTS` consistently across versions, so `IchorDB.connect()` should call a Python migration helper after `executescript()`.

#### Event temporal columns

Add to `ichor_events` if absent:

```sql
ALTER TABLE ichor_events ADD COLUMN occurred_start TEXT;
ALTER TABLE ichor_events ADD COLUMN occurred_end TEXT;
ALTER TABLE ichor_events ADD COLUMN mentioned_at TEXT;
ALTER TABLE ichor_events ADD COLUMN valid_from TEXT;
ALTER TABLE ichor_events ADD COLUMN valid_until TEXT;
ALTER TABLE ichor_events ADD COLUMN status TEXT DEFAULT 'active';
ALTER TABLE ichor_events ADD COLUMN superseded_by INTEGER REFERENCES ichor_events(id);
```

Indexes:

```sql
CREATE INDEX IF NOT EXISTS idx_ichor_events_valid_until ON ichor_events(valid_until);
CREATE INDEX IF NOT EXISTS idx_ichor_events_status ON ichor_events(status);
CREATE INDEX IF NOT EXISTS idx_ichor_events_mentioned_at ON ichor_events(mentioned_at);
CREATE INDEX IF NOT EXISTS idx_ichor_events_occurred_range ON ichor_events(occurred_start, occurred_end);
```

#### Tags

Use a join table, not comma-delimited strings, so strict matching stays queryable:

```sql
CREATE TABLE IF NOT EXISTS ichor_event_tags (
    event_id INTEGER NOT NULL REFERENCES ichor_events(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(event_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_ichor_event_tags_tag ON ichor_event_tags(tag);
CREATE INDEX IF NOT EXISTS idx_ichor_event_tags_event ON ichor_event_tags(event_id);
```

#### Observations

```sql
CREATE TABLE IF NOT EXISTS ichor_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject TEXT NOT NULL,
    predicate TEXT,
    object TEXT,
    content TEXT NOT NULL,
    category TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.8,
    proof_count INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT,
    last_seen TEXT,
    evidence_span_days REAL DEFAULT 0,
    trend TEXT DEFAULT 'new',
    status TEXT DEFAULT 'active',
    superseded_by INTEGER REFERENCES ichor_observations(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(subject, predicate, category, content)
);

CREATE TABLE IF NOT EXISTS ichor_observation_sources (
    observation_id INTEGER NOT NULL REFERENCES ichor_observations(id) ON DELETE CASCADE,
    event_id INTEGER REFERENCES ichor_events(id) ON DELETE SET NULL,
    conclusion_id INTEGER,
    quote TEXT NOT NULL,
    relevance TEXT,
    source_session_id TEXT,
    source_god_name TEXT,
    source_timestamp TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(observation_id, event_id, conclusion_id)
);

CREATE TABLE IF NOT EXISTS ichor_observation_tags (
    observation_id INTEGER NOT NULL REFERENCES ichor_observations(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(observation_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_ichor_observations_subject ON ichor_observations(subject);
CREATE INDEX IF NOT EXISTS idx_ichor_observations_category ON ichor_observations(category);
CREATE INDEX IF NOT EXISTS idx_ichor_observations_status ON ichor_observations(status);
CREATE INDEX IF NOT EXISTS idx_ichor_observations_last_seen ON ichor_observations(last_seen);
CREATE INDEX IF NOT EXISTS idx_ichor_observation_tags_tag ON ichor_observation_tags(tag);
```

#### Observation FTS

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS ichor_observations_fts USING fts5(
    subject, predicate, object, content,
    content='ichor_observations',
    content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS ichor_observations_ai AFTER INSERT ON ichor_observations BEGIN
    INSERT INTO ichor_observations_fts(rowid, subject, predicate, object, content)
    VALUES (new.id, new.subject, new.predicate, new.object, new.content);
END;

CREATE TRIGGER IF NOT EXISTS ichor_observations_ad AFTER DELETE ON ichor_observations BEGIN
    INSERT INTO ichor_observations_fts(ichor_observations_fts, rowid, subject, predicate, object, content)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.content);
END;

CREATE TRIGGER IF NOT EXISTS ichor_observations_au AFTER UPDATE ON ichor_observations BEGIN
    INSERT INTO ichor_observations_fts(ichor_observations_fts, rowid, subject, predicate, object, content)
    VALUES ('delete', old.id, old.subject, old.predicate, old.object, old.content);
    INSERT INTO ichor_observations_fts(rowid, subject, predicate, object, content)
    VALUES (new.id, new.subject, new.predicate, new.object, new.content);
END;
```

#### Knowledge pages

```sql
CREATE TABLE IF NOT EXISTS ichor_knowledge_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    question TEXT NOT NULL,
    scope_tags_json TEXT NOT NULL DEFAULT '[]',
    content_md TEXT NOT NULL,
    source_observation_ids_json TEXT NOT NULL DEFAULT '[]',
    version INTEGER NOT NULL DEFAULT 1,
    refresh_status TEXT NOT NULL DEFAULT 'fresh',
    stale_after TEXT,
    last_refreshed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ichor_knowledge_page_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id INTEGER NOT NULL REFERENCES ichor_knowledge_pages(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    content_md TEXT NOT NULL,
    source_observation_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(page_id, version)
);

CREATE INDEX IF NOT EXISTS idx_ichor_knowledge_pages_key ON ichor_knowledge_pages(key);
CREATE INDEX IF NOT EXISTS idx_ichor_knowledge_pages_refresh ON ichor_knowledge_pages(refresh_status, stale_after);
```

### Python migration helper

Add helper in `lib/ichor_db.py`:

```python
def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
```

Call after schema load:

```python
self._run_schema_migrations(self._conn)
```

### Tag helper contract

`lib/ichor_tags.py` should expose:

```python
TagsMatch = Literal["any", "all", "any_strict", "all_strict"]

NORMAL_TAG_RE = re.compile(r"^[a-z][a-z0-9_-]*:[a-z0-9_.-]+$")

def normalize_tag(tag: str) -> str: ...
def normalize_tags(tags: Iterable[str] | None) -> list[str]: ...
def build_tag_filter_sql(table_alias: str, tag_table: str, id_column: str, tags: list[str], tags_match: TagsMatch) -> tuple[str, list[Any]]: ...
def attach_event_tags(conn: sqlite3.Connection, event_id: int, tags: Iterable[str]) -> None: ...
def attach_observation_tags(conn: sqlite3.Connection, observation_id: int, tags: Iterable[str]) -> None: ...
def infer_event_tags(*, god_name: str | None, session_id: str | None, metadata: dict | None = None) -> list[str]: ...
```

Strict semantics:

| Mode | Semantics |
|---|---|
| `any` | include row when it has at least one requested tag OR has no tags |
| `all` | include row when it has all requested tags OR has no tags |
| `any_strict` | include row only when it has at least one requested tag |
| `all_strict` | include row only when it has all requested tags |

Default policy:

- User-scoped calls should default to `any_strict` when any `user:<id>` tag is present.
- Legacy calls with no tags should preserve existing behavior.
- Untagged global memory is allowed only when no tags are passed or strict mode is not requested.

### Temporal helper contract

`lib/ichor_temporal.py` should expose:

```python
def parse_iso_z(value: str | None) -> datetime | None: ...
def normalize_timestamp(value: str | datetime | None) -> str | None: ...
def is_active_at(row: Mapping[str, Any], query_timestamp: str | datetime | None) -> bool: ...
def temporal_rank_boost(row: Mapping[str, Any], query_timestamp: str | datetime | None) -> tuple[float, list[str]]: ...
def event_best_timestamp(row: Mapping[str, Any]) -> str | None: ...
```

Active rules:

- `status != 'active'` is inactive unless caller explicitly asks for archived/superseded rows.
- `valid_until < query_timestamp` is inactive.
- `valid_from > query_timestamp` is inactive.
- If no `query_timestamp` is supplied, do not apply validity exclusion except `status != 'active'`.
- `mentioned_at` defaults to `created_at` during migration/backfill.

### Acceptance Criteria

- [ ] Existing DBs migrate without data loss.
- [ ] `ichor_events` gains temporal columns if absent.
- [ ] Tag tables exist and enforce uniqueness.
- [ ] Observation and knowledge page tables exist.
- [ ] FTS triggers keep `ichor_observations_fts` in sync.
- [ ] `IchorDB.insert_event(...)` can accept optional `tags`, `occurred_start`, `occurred_end`, `mentioned_at`, `valid_from`, `valid_until`, `status`, `superseded_by` without breaking old callers.
- [ ] Unit tests cover migration idempotency by calling connect twice.

---

## Phase 2 — Write Path: Tags and Temporal Fields on Events

### Objective

Make new schema usable from current event insertion paths before building consolidation.

### Files

Modify:

```text
lib/ichor_db.py
lib/ichor_tier_a.py
plugins/pantheon/ichor_nudge.py
lib/ichor/reconcile.py
lib/ichor_mcp.py
```

Tests:

```text
tests/test_ichor_hindsight_event_write_path.py
```

### Implementation Requirements

#### `IchorDB.insert_event`

Extend signature:

```python
def insert_event(
    self,
    session_id: str,
    event_type: str,
    subject: str,
    predicate: Optional[str] = None,
    object: Optional[str] = None,
    confidence: float = 0.8,
    source: Optional[str] = None,
    raw_text: Optional[str] = None,
    god_name: Optional[str] = None,
    direction: Optional[str] = None,
    peer_god: Optional[str] = None,
    tags: Optional[list[str]] = None,
    occurred_start: Optional[str] = None,
    occurred_end: Optional[str] = None,
    mentioned_at: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    status: str = "active",
    superseded_by: Optional[int] = None,
) -> int:
    ...
```

After insert:

- Normalize `mentioned_at` to `created_at` when absent.
- Infer tags from `god_name` and `session_id` if explicit tags are absent.
- Attach explicit and inferred tags.
- Do not reject legacy rows with no user tag.

#### `ichor_nudge.py`

When storing background-review extracted events:

- Pass `god:<name>` when known.
- Pass `session:<id>` when known.
- If gateway metadata exposes user/channel/project, map to tags.
- Do not invent `user:<id>` when no user id is available.

#### `ichor_tier_a.py`

Tier A extraction should preserve existing behavior. Add only:

- optional tag passthrough,
- `mentioned_at=created_at` default,
- status default.

#### `reconcile.py`

When a contradiction causes deletion/supersession:

- Prefer marking older row `status='superseded'`, `superseded_by=<new_id>` when possible.
- Keep existing delete behavior only where callers/tests require deletion.
- Record correction event with source ids in `raw_text` or structured fields.

### Acceptance Criteria

- [ ] Old event insert tests still pass.
- [ ] New insert path stores tags in `ichor_event_tags`.
- [ ] `mentioned_at` defaults to row creation time.
- [ ] Explicit `valid_until` and `status` are persisted.
- [ ] Reconcile updates status/supersession metadata where safe.
- [ ] No background review path requires an extra LLM call.

---

## Phase 3 — Observation Consolidation MVP

### Objective

Create a deterministic consolidation engine that turns repeated events/conclusions into inspectable observations with exact quote evidence.

### Files

Create:

```text
lib/ichor_observations.py
scripts/ichor_consolidate_observations.py
```

Modify:

```text
lib/ichor_daily_maintenance.py
lib/ichor_hybrid.py
lib/ichor_mcp.py
```

Tests:

```text
tests/test_ichor_observations.py
tests/test_ichor_prefer_observations.py
```

### Observation Model

Implement dataclasses:

```python
@dataclass
class ObservationEvidence:
    event_id: int | None
    conclusion_id: int | None
    quote: str
    relevance: str
    source_session_id: str | None
    source_god_name: str | None
    source_timestamp: str | None

@dataclass
class Observation:
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
    tags: list[str]
    sources: list[ObservationEvidence]
```

### Deterministic clustering rules

Start with events only. Postgres conclusions integration can land after event consolidation is stable.

Candidate grouping key:

```python
normalized_subject = normalize_subject(event.subject)
normalized_predicate = normalize_predicate(event.predicate or event.event_type)
category = event.event_type
```

Cluster when:

- same normalized subject,
- same normalized predicate/category,
- object/raw_text token Jaccard similarity above threshold,
- no obvious contradiction from existing `detect_contradiction()`.

Starter thresholds:

```python
MIN_CLUSTER_SIZE = 2
TEXT_SIMILARITY_THRESHOLD = 0.45
QUOTE_MAX_CHARS = 500
```

Content generation must be deterministic in MVP:

```python
content = f"{subject} {predicate} {canonical_object_or_summary}."
```

Do not call an LLM in Phase 3.

### Confidence scoring

Compute:

```python
base = weighted_mean(event.confidence for event in sources)
proof_boost = min(0.15, 0.03 * (proof_count - 1))
recency_penalty = 0.0 if newest source is active/current else 0.05
confidence = clamp(base + proof_boost - recency_penalty, 0.0, 1.0)
```

Use existing `ichor_memory_score.py` only as an input/reference; do not replace it.

### Trend computation

Mirror Hindsight's shape, algorithmically:

- `new`: all source timestamps are recent relative to evidence span or only one dense cluster exists.
- `stable`: evidence exists across older and newer buckets at similar density.
- `strengthening`: recent evidence density is materially higher than older density.
- `weakening`: recent evidence density is materially lower than older density.
- `stale`: no source evidence after the freshness cutoff.

Do not hard-code wall-clock language into the spec. Implement with named constants in code:

```python
RECENT_WINDOW_DAYS = 30
STALE_AFTER_DAYS = 90
DENSITY_STRENGTHENING_RATIO = 1.5
DENSITY_WEAKENING_RATIO = 0.5
```

### Conflict handling

When a new event contradicts an existing observation:

- Do not mutate the original observation content in place without preserving history.
- Either:
  - mark old observation `status='superseded'` and create a new active observation, or
  - create a second active conflicting observation with `rank_reasons=['conflict']`.
- Record source rows for both sides.
- Retrieval must surface conflict metadata when both are relevant.

### Consolidation entry points

Expose:

```python
class ObservationConsolidator:
    def __init__(self, db_path: str = "~/.hermes/ichor.db"): ...
    def consolidate_events(self, *, limit: int = 1000, tags: list[str] | None = None) -> ConsolidationResult: ...
    def consolidate_subject(self, subject: str, *, category: str | None = None) -> ConsolidationResult: ...
    def get_observation(self, observation_id: int, include_sources: bool = False) -> dict[str, Any]: ...
    def search_observations(self, query: str, limit: int = 10, tags: list[str] | None = None, tags_match: str = "any") -> list[dict[str, Any]]: ...
```

CLI:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_consolidate_observations.py --limit 1000 --dry-run
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_consolidate_observations.py --limit 1000
```

### Acceptance Criteria

- [ ] Repeated preference fixture yields one observation with `proof_count >= 2`.
- [ ] Observation source rows include exact quotes from event `raw_text`.
- [ ] Observation tags are the union/intersection policy chosen in code and documented in tests.
- [ ] Contradictory events do not silently overwrite observations.
- [ ] Dry-run CLI reports candidate clusters without writing.
- [ ] Running consolidation twice is idempotent.
- [ ] Phase 0 old retrieval tests still pass.

---

## Phase 4 — Observation Retrieval and `prefer_observations`

### Objective

Make observations available through Ichor retrieval and suppress duplicate raw events only when requested.

### Files

Modify:

```text
lib/ichor_hybrid.py
lib/ichor_mcp.py
```

Create if cleaner:

```text
lib/ichor/retrieval_observations.py
```

Tests:

```text
tests/test_ichor_observation_retrieval.py
tests/test_ichor_prefer_observations.py
```

### Retrieval backend

Add an observations backend with the same shape as current FTS5/events results:

```python
class ObservationsBackend:
    def search(
        self,
        query: str,
        limit: int = 10,
        tags: list[str] | None = None,
        tags_match: str = "any",
        query_timestamp: str | None = None,
        include_sources: bool = False,
    ) -> list[dict[str, Any]]:
        ...
```

Result ids:

```text
observation:<id>
```

Scores:

```python
base_score = fts_rank_normalized_or_confidence
proof_boost = min(0.15, 0.03 * (proof_count - 1))
temporal_boost, reasons = temporal_rank_boost(row, query_timestamp)
score = clamp(base_score + proof_boost + temporal_boost, 0.0, 1.0)
```

### Fusion changes

Current weights in `ichor_hybrid.py` include:

```python
WEIGHTS = {
    "fts5": 0.40,
    "vector": 0.20,
    "graph": 0.15,
    "events": 0.15,
    "reference": 0.10,
}
```

Do not destabilize current ranking. Add observation weight conservatively and only when backend is requested:

```python
WEIGHTS = {
    "observations": 0.35,
    "fts5": 0.30,
    "events": 0.15,
    "graph": 0.10,
    "vector": 0.05,
    "reference": 0.05,
}
```

If `observations` is not requested, normalize over active backends as current code does.

### `prefer_observations` dedup

When both observations and raw events are in the candidate pool and `prefer_observations=True`:

1. Collect source event ids from returned observations within the pre-truncation candidate window.
2. Drop raw `fts5:<id>` / `events:<id>` rows whose event id appears in those sources.
3. Backfill from lower-ranked candidates to preserve `limit` when possible.
4. Add rank reason to the observation: `supersedes_raw:<count>`.
5. Add retrieval metadata: `prefer_observations_dropped_raw_count`.

Do not drop raw events when:

- caller did not request observations,
- caller set `prefer_observations=False`,
- observation is below the returned candidate window,
- raw event is not actually a source for the observation.

### Acceptance Criteria

- [ ] `ichor_retrieve(..., backends="observations")` returns observation rows.
- [ ] `ichor_retrieve(..., backends="observations,fts5", prefer_observations=True)` drops sourced raw duplicates and backfills.
- [ ] `prefer_observations=False` returns both observation and raw source when both rank.
- [ ] Observation result includes `proof_count`, `trend`, `source_ids`, `tags`, and `rank_reasons`.
- [ ] Existing FTS5-only retrieval ordering remains stable when observations backend is absent.

---

## Phase 5 — Strict Tags/Scopes in Retrieval

### Objective

Apply tag filters before ranking/truncation across events, observations, and compatible backends.

### Files

Modify:

```text
lib/ichor_tags.py
lib/ichor_db.py
lib/ichor_hybrid.py
lib/ichor_mcp.py
lib/ichor/retrieval_hydration.py
```

Tests:

```text
tests/test_ichor_tags_and_scopes.py
```

### Retrieval behavior

For FTS5/events SQL:

- Join `ichor_event_tags` before result truncation.
- Enforce `any/all/any_strict/all_strict` in SQL where possible.
- For no tags, preserve current behavior.

For observations SQL:

- Join `ichor_observation_tags` before result truncation.

For graph/entity backends:

- If graph rows have no tags, mark result with `scope_status='untagged_backend'`.
- When strict tags are requested, either exclude untagged graph results or include only graph rows that can be traced to tagged events/entities.
- This phase may choose to disable graph results under strict tags until source mapping exists. If so, return metadata explaining the exclusion.

### Default policy

- MCP `ichor_retrieve` with tags supplied should default `tags_match` to `any_strict` if not explicitly provided.
- Python API should preserve old behavior when `tags is None`.
- Do not infer `user:konan` globally in code. User tags must come from caller/gateway metadata or a migration tool.

### Migration/backfill script

Create:

```text
scripts/ichor_backfill_tags.py
```

Behavior:

- Infer `god:<god_name>` for rows with `god_name`.
- Infer `session:<session_id>` for rows with `session_id`.
- Optionally infer `scope:pantheon` for existing Pantheon god fleet rows only when `--pantheon-scope` is passed.
- Do not infer user tags without explicit map input.

CLI:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_backfill_tags.py --dry-run
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_backfill_tags.py --apply --pantheon-scope
```

### Acceptance Criteria

- [ ] `any_strict` excludes untagged rows.
- [ ] `any` includes untagged rows.
- [ ] `all_strict` requires every requested tag.
- [ ] Filters apply before ranking/truncation.
- [ ] Backfill script dry-run reports planned tag counts.
- [ ] Backfill script apply is idempotent.
- [ ] Strict retrieval metadata reports excluded untagged backend counts.

---

## Phase 6 — Budgeted and Token-Bounded Recall

### Objective

Separate retrieval effort from final returned result count and payload size.

### Files

Modify:

```text
lib/ichor_hybrid.py
lib/ichor_mcp.py
lib/ichor/retrieval_hydration.py
```

Create:

```text
lib/ichor_budget.py
```

Tests:

```text
tests/test_ichor_budgeted_recall.py
```

### Budget contract

`lib/ichor_budget.py`:

```python
Budget = Literal["low", "mid", "high"]

@dataclass(frozen=True)
class RecallBudget:
    name: str
    candidate_multiplier: int
    graph_depth: int
    hydrate_sources: bool
    default_max_tokens: int

BUDGETS = {
    "low": RecallBudget("low", candidate_multiplier=3, graph_depth=0, hydrate_sources=False, default_max_tokens=2048),
    "mid": RecallBudget("mid", candidate_multiplier=8, graph_depth=1, hydrate_sources=False, default_max_tokens=4096),
    "high": RecallBudget("high", candidate_multiplier=20, graph_depth=2, hydrate_sources=True, default_max_tokens=8192),
}

def resolve_budget(budget: str | None, max_tokens: int | None) -> RecallBudget: ...
```

### Token filtering

Implement a lightweight token estimate. Do not add heavyweight dependencies.

```python
def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)
```

Apply after ranking:

- Add results until `max_tokens` would be exceeded.
- Always include at least the top result if any result exists and `max_tokens > 0`.
- If `include_sources=True`, source quote tokens count against the budget.
- Return metadata: `token_budget`, `estimated_tokens_returned`, `results_dropped_for_token_budget`.

### Candidate fetch

For each backend:

```python
candidate_limit = max(limit, limit * budget.candidate_multiplier)
```

Then final truncate to `limit` after fusion, dedup, and token filtering.

### Acceptance Criteria

- [ ] `budget='low'` fetches fewer candidates than `budget='high'` in observable metadata.
- [ ] `max_tokens` truncates payload without crashing.
- [ ] Old `limit` behavior remains backward-compatible when budget/max_tokens omitted.
- [ ] Metadata exposes candidate counts per backend and token budget decisions.
- [ ] Tests verify that budget changes do not alter old-call result shape unexpectedly.

---

## Phase 7 — Event-Level Temporal Validity and As-Of Recall

### Objective

Make Ichor recall respect explicit validity windows and query-time anchors.

### Files

Modify:

```text
lib/ichor_temporal.py
lib/ichor_db.py
lib/ichor_hybrid.py
lib/ichor/reconcile.py
lib/ichor_mcp.py
```

Create/modify:

```text
scripts/ichor_temporal_backfill.py
tests/test_ichor_hindsight_temporal.py
```

### Behavior

When `query_timestamp` is supplied:

- Exclude events/observations where `valid_until < query_timestamp`.
- Exclude events/observations where `valid_from > query_timestamp`.
- Exclude `status != 'active'` unless caller passes `include_inactive=True`.
- Prefer rows whose `occurred_*` or `mentioned_at` are temporally close to the query when relevance scores tie.

When `query_timestamp` is absent:

- Exclude `status != 'active'` by default.
- Do not apply validity-window exclusion based on current wall-clock time unless explicitly requested.

### Reconcile integration

When `reconcile_memory_event()` detects contradiction:

- Mark older row `status='superseded'` and `valid_until=<new row mentioned_at/created_at>` when safe.
- Set `superseded_by=<new_event_id>`.
- Keep correction event.

### Backfill

`scripts/ichor_temporal_backfill.py` should:

- Set `mentioned_at=created_at` where missing.
- Set `status='active'` where missing.
- Leave `occurred_*`, `valid_*`, `superseded_by` null unless explicit source exists.

### Acceptance Criteria

- [ ] As-of query before a supersession can return old fact.
- [ ] As-of query after a supersession returns new/current fact.
- [ ] No query timestamp preserves old behavior except inactive exclusion.
- [ ] Backfill is idempotent.
- [ ] Temporal metadata appears in results.

---

## Phase 8 — Knowledge Pages / Mental-Model Cache

### Objective

Create cheap, provenance-backed standing answers generated from observations.

### Files

Modify/create:

```text
lib/ichor_knowledge_pages.py
lib/ichor_mcp.py
lib/ichor_daily_maintenance.py
```

Tests:

```text
tests/test_ichor_knowledge_pages.py
```

### API

```python
class KnowledgePageStore:
    def upsert_page(
        self,
        key: str,
        question: str,
        scope_tags: list[str],
        content_md: str,
        source_observation_ids: list[int],
    ) -> dict[str, Any]: ...

    def get_page(self, key: str) -> dict[str, Any] | None: ...

    def search_pages(
        self,
        query: str,
        tags: list[str] | None = None,
        tags_match: str = "any_strict",
        limit: int = 5,
    ) -> list[dict[str, Any]]: ...

    def refresh_page(
        self,
        key: str,
        *,
        dry_run: bool = False,
    ) -> dict[str, Any]: ...
```

### MVP generation rule

Phase 8 may use deterministic markdown generation from observations. LLM refresh can be a later build.

Template:

```markdown
# {question}

## Current Answer

{bullet summary from top observations}

## Evidence

- observation:{id} — proof_count={proof_count}, confidence={confidence}, last_seen={last_seen}

## Staleness

{fresh/stale marker}
```

### MCP tools

Add tools or extend `ichor_retrieve`:

```text
ichor_knowledge_page_get(key)
ichor_knowledge_page_search(query, tags, tags_match, limit)
ichor_knowledge_page_refresh(key, dry_run)
```

If adding separate MCP tools creates too much surface area, use `ichor_retrieve(..., backends="knowledge_pages,observations,fts5")` and reserve direct page tools for internal Python.

### Initial page candidates

Seed no pages automatically in production. Tests should create these fixture pages:

- `user-konan-architecture-preferences`
- `pantheon-active-ichor-blockers`
- `god-thoth-research-protocol`

### Acceptance Criteria

- [ ] Page creation stores version 1 and source observation ids.
- [ ] Updating a page increments version and writes previous content to `ichor_knowledge_page_versions`.
- [ ] Deleting/rebuilding a page does not delete observations.
- [ ] Page search respects strict tags.
- [ ] `ichor_retrieve` can include pages as a backend if implemented.

---

## Phase 9 — Deterministic Retrieval Ladder for Ichor + LCM

### Objective

Expose the intended retrieval order without embedding a new autonomous reflect agent in Ichor.

### Files

Create:

```text
lib/ichor_recall_ladder.py
```

Modify:

```text
lib/ichor_mcp.py
```

Tests:

```text
tests/test_ichor_recall_ladder.py
```

### Ladder

```text
1. knowledge_pages      cheap standing answer / projection
2. observations         consolidated belief with proof count
3. events + graph       raw Ichor evidence and relationships
4. lcm_expand handle    exact source expansion outside Ichor
```

### API

```python
@dataclass
class LadderStep:
    name: str
    attempted: bool
    result_count: int
    enough: bool
    reasons: list[str]

@dataclass
class RecallLadderResult:
    results: list[dict[str, Any]]
    steps: list[LadderStep]
    source_expansion_hints: list[dict[str, Any]]
    warnings: list[str]


def recall_with_ladder(
    query: str,
    *,
    tags: list[str] | None = None,
    tags_match: str = "any_strict",
    budget: str = "mid",
    max_tokens: int = 4096,
    require_exact: bool = False,
) -> RecallLadderResult: ...
```

### LCM boundary

Ichor should return expansion hints, not call LCM internally by default:

```json
{
  "kind": "lcm_expand_hint",
  "reason": "exact evidence requested",
  "source_ids": ["session:20260806_...", "store_id:12345"],
  "note": "Caller should use lcm_expand/include_exact_ref for exact wording."
}
```

This preserves the Hermes-LCM policy: exact commands, paths, counts, operands, and causal chains require source-backed exact evidence.

### Acceptance Criteria

- [ ] Ladder tries pages before observations.
- [ ] Ladder can stop early when page/observation evidence is enough and exact evidence is not required.
- [ ] `require_exact=True` returns LCM expansion hints and does not pretend Ichor proof is exact transcript proof.
- [ ] No autonomous LLM loop is introduced.

---

## Phase 10 — Optional High-Budget Reranker Experiment

### Objective

Add an explicitly disabled-by-default reranking lane for high-budget retrieval and audits.

### Files

Create:

```text
lib/ichor_rerank.py
```

Modify:

```text
lib/ichor_hybrid.py
lib/ichor_mcp.py
lib/ichor_benchmarks.py
```

Tests:

```text
tests/test_ichor_optional_rerank.py
```

### Feature flag

Environment/config gate:

```text
ICHOR_RERANK_ENABLED=false
ICHOR_RERANK_MODE=none        # none | heuristic | local_cross_encoder
ICHOR_RERANK_TIMEOUT_SECONDS=10
ICHOR_RERANK_MAX_CANDIDATES=100
```

Default must be disabled.

### Heuristic reranker MVP

Before any model dependency, implement a model-free reranker:

```python
final_score = (
    0.50 * lexical_or_backend_score
    + 0.20 * confidence
    + 0.15 * proof_count_normalized
    + 0.10 * temporal_score
    + 0.05 * scope_score
)
```

Only after heuristic path is tested should a local cross-encoder be considered.

### Passthrough guard

If reranker unavailable, timed out, or returns flat scores:

- preserve original order,
- record `rerank_status='passthrough'`,
- do not let recency/temporal boosts become the only ordering signal.

### Benchmark gate

Use `ichor_benchmarks.py` or a new benchmark fixture to compare:

- old retrieval,
- observation retrieval without rerank,
- heuristic rerank,
- optional model rerank if implemented.

Do not enable by default unless benchmark output and tests justify it.

### Acceptance Criteria

- [ ] Reranker is disabled by default.
- [ ] High-budget call can opt in with `rerank='heuristic'` when enabled.
- [ ] Timeout/failure returns results, not errors, with passthrough metadata.
- [ ] Retrieval log records rerank status and candidate counts.
- [ ] No model download is required for default test suite.

---

## Phase 11 — Observability, Audit Logs, and Forge Feedback

### Objective

Make the new retrieval behavior measurable and tunable.

### Files

Modify:

```text
lib/ichor_mcp.py
lib/ichor_hybrid.py
lib/ichor_forge.py
lib/ichor_benchmarks.py
```

Tests:

```text
tests/test_ichor_hindsight_observability.py
```

### Retrieval log extension

Existing retrieval log:

```text
~/.hermes/pantheon/retrieval-log.jsonl
```

Add fields:

```json
{
  "query": "...",
  "budget": "mid",
  "max_tokens": 4096,
  "tags": ["user:konan"],
  "tags_match": "any_strict",
  "backends_requested": ["observations", "fts5", "events"],
  "backends_used": ["observations", "fts5"],
  "candidate_counts": {"observations": 12, "fts5": 30},
  "strict_scope_excluded_counts": {"untagged": 5, "tag_mismatch": 3},
  "prefer_observations_dropped_raw_count": 4,
  "token_budget": 4096,
  "estimated_tokens_returned": 1800,
  "temporal_filter_dropped_count": 2,
  "rerank_status": "disabled",
  "top_result_ids": ["observation:42"],
  "warnings": []
}
```

### MCP audit

Existing `ichor_mcp.py` has `recall_log`. Extend without breaking current rows:

- store new metadata as JSON columns where possible,
- truncate safely,
- keep async writer behavior,
- add `_drain_recall_log_writes()` tests.

### Forge feedback

Forge should be able to spot:

- strict scoping hides too much,
- observations are suppressing useful raw evidence,
- reranker passthrough too frequent,
- stale observations ranking high,
- high conflict density for a subject.

Add a simple report function first; do not auto-tune weights in this phase.

### Acceptance Criteria

- [ ] New retrieval metadata appears in JSONL log.
- [ ] MCP recall log still writes asynchronously.
- [ ] Tests drain async writes deterministically.
- [ ] Forge/benchmark command can summarize new fields.

---

## Phase 12 — Backfill and Maintenance Jobs

### Objective

Run safe migrations/backfills and wire consolidation into maintenance without disrupting the god fleet.

### Files

Create/modify:

```text
scripts/ichor_backfill_tags.py
scripts/ichor_temporal_backfill.py
scripts/ichor_consolidate_observations.py
lib/ichor_daily_maintenance.py
```

Tests:

```text
tests/test_ichor_hindsight_backfills.py
```

### Backfill order

1. Schema migration via normal `IchorDB.connect()`.
2. Temporal backfill: `mentioned_at=created_at`, `status='active'`.
3. Tag backfill: `god:<name>`, `session:<id>`, optional `scope:pantheon` only with explicit flag.
4. Observation dry-run.
5. Observation apply.
6. Knowledge page refresh only after observations exist.

### Maintenance integration

`ichor_daily_maintenance.py` should:

- run observation consolidation with bounded limits,
- log counts,
- never block core memory writes,
- skip reranker/model paths,
- expose dry-run mode.

### Safety requirements

- Every backfill script must support `--dry-run`.
- Every write script must print counts before/after.
- Every script must accept `--db-path` for temp test DBs.
- No script should assume `~` means `/home/konan`; use explicit path defaults and document them.

### Acceptance Criteria

- [ ] Backfills run against temp DB in tests.
- [ ] Dry-run performs no writes.
- [ ] Apply is idempotent.
- [ ] Maintenance can run with all new jobs disabled/enabled via flags.

---

## Phase 13 — MCP Surface and Compatibility Freeze

### Objective

Finalize tool parameters, response shape, and backward compatibility.

### Files

Modify:

```text
lib/ichor_mcp.py
pantheon-core/mcp_server.py   # only if it proxies or lists Ichor tools
```

Tests:

```text
tests/test_ichor_mcp.py
tests/test_ichor_hindsight_mcp_contract.py
```

### MCP tool updates

`TOOL_NAMES` currently includes:

```python
TOOL_NAMES = [
    "ichor_store",
    "ichor_retrieve",
    "ichor_health",
    "ichor_stats",
    "ichor_audit",
    "ichor_gate_check",
    "ichor_fold",
    "ichor_expand",
    "ichor_compare",
    "ichor_entity_resolve",
    "ichor_recall_stats",
]
```

Do not remove any existing tool.

Extend `ichor_retrieve`; optionally add:

```text
ichor_observation_get
ichor_knowledge_page_get
ichor_knowledge_page_search
ichor_knowledge_page_refresh
```

If adding tools, update tool list and tests.

### Compatibility requirements

- Old arguments still work.
- Unknown new optional arguments should fail clearly, not silently misbehave.
- Response includes old `results` list at top level.
- New metadata should be additive.

### Acceptance Criteria

- [ ] Existing `test_ichor_mcp.py` passes.
- [ ] MCP schema exposes new optional args.
- [ ] Old minimal `ichor_retrieve(query="x")` call succeeds.
- [ ] New full `ichor_retrieve(...)` call succeeds against fixture DB.

---

## Phase 14 — End-to-End Verification Gates

### Objective

Prove the upgraded Ichor behavior across schema, retrieval, scoping, temporal, observations, pages, and compatibility.

### Required commands

Run targeted tests:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest \
  tests/test_ichor_hindsight_schema.py \
  tests/test_ichor_hindsight_event_write_path.py \
  tests/test_ichor_observations.py \
  tests/test_ichor_prefer_observations.py \
  tests/test_ichor_observation_retrieval.py \
  tests/test_ichor_tags_and_scopes.py \
  tests/test_ichor_budgeted_recall.py \
  tests/test_ichor_hindsight_temporal.py \
  tests/test_ichor_knowledge_pages.py \
  tests/test_ichor_recall_ladder.py \
  tests/test_ichor_optional_rerank.py \
  tests/test_ichor_hindsight_observability.py \
  tests/test_ichor_hindsight_backfills.py \
  tests/test_ichor_hindsight_mcp_contract.py \
  -q
```

Run existing regression slice:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon pytest \
  tests/test_ichor_foundation.py \
  tests/test_ichor_tier_a.py \
  tests/test_ichor_b2_tiered_retrieval.py \
  tests/test_ichor_b4_advanced_retrieval.py \
  tests/test_ichor_c1_outcome_and_contradiction.py \
  tests/test_ichor_mcp.py \
  tests/test_ichor_observability.py \
  tests/test_ichor_retrieval_observability.py \
  -q
```

Run syntax checks for changed Python files:

```bash
cd /home/konan/pantheon
python3 -m py_compile \
  lib/ichor_db.py \
  lib/ichor_hybrid.py \
  lib/ichor_mcp.py \
  lib/ichor_tags.py \
  lib/ichor_temporal.py \
  lib/ichor_observations.py \
  lib/ichor_knowledge_pages.py \
  lib/ichor_budget.py \
  lib/ichor_recall_ladder.py \
  lib/ichor_rerank.py
```

### Manual smoke checks

Against a temp DB or explicitly approved local DB:

```bash
cd /home/konan/pantheon
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_backfill_tags.py --dry-run
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_temporal_backfill.py --dry-run
PYTHONPATH=/home/konan/pantheon python3 scripts/ichor_consolidate_observations.py --dry-run --limit 100
```

### Acceptance Criteria

- [ ] New targeted tests pass.
- [ ] Existing Ichor regression slice passes.
- [ ] Syntax checks pass.
- [ ] Dry-run scripts execute without writing.
- [ ] No service restart is required to run tests.
- [ ] Default retrieval remains cheap and does not require any reranker/model download.

---

## Phase 15 — Documentation and Handoff

### Objective

Document the new behavior so future gods and operators do not misuse the system.

### Files

Create or update:

```text
/home/konan/pantheon/docs/ichor-memory-upgrades.md
/home/konan/pantheon/plans/ichor-hindsight-inspired-memory-upgrades-build-spec-v1.md
/home/konan/athenaeum/Codex-Pantheon/DECISIONS.md   # only if implementation locks a new durable architecture decision
```

### Documentation requirements

Docs must explain:

- observations vs events,
- tags and strict scoping modes,
- budget vs limit vs max_tokens,
- query_timestamp/as-of behavior,
- knowledge pages as projections, not source of truth,
- reranker disabled-by-default policy,
- LCM boundary for exact evidence.

### Acceptance Criteria

- [ ] Docs include examples of old and new `ichor_retrieve` calls.
- [ ] Docs include warning: use LCM exact refs for exact commands/paths/counts/causal chains.
- [ ] Docs include backfill script dry-run examples.
- [ ] If a durable architecture decision is made during implementation, append to `Codex-Pantheon/DECISIONS.md`.

---

## Data Migration / Rollback Plan

### Migration principles

- Additive schema only.
- No destructive migration in this build.
- Existing `ichor_events` remains canonical raw event storage.
- Observations and knowledge pages are rebuildable projections.
- Tags and temporal fields can be backfilled incrementally.

### Rollback switches

Add config/env gates:

```text
ICHOR_OBSERVATIONS_ENABLED=true
ICHOR_STRICT_TAGS_ENABLED=true
ICHOR_KNOWLEDGE_PAGES_ENABLED=true
ICHOR_TEMPORAL_FILTER_ENABLED=true
ICHOR_RERANK_ENABLED=false
```

If a problem appears:

1. Disable affected feature flag.
2. Keep schema in place.
3. Keep old retrieval path active.
4. Re-run regression slice.
5. Inspect retrieval log metadata for failure mode.

### Data rollback

Because new tables are projections:

```sql
DELETE FROM ichor_observation_sources;
DELETE FROM ichor_observation_tags;
DELETE FROM ichor_observations;
DELETE FROM ichor_knowledge_page_versions;
DELETE FROM ichor_knowledge_pages;
```

Do not delete `ichor_events` or tag tables during normal rollback.

---

## Security / Privacy / Isolation Requirements

- Strict user tags must exclude other users and untagged rows.
- Do not infer user identity unless a trusted caller supplies it.
- Metadata is not a substitute for tags; filter on tags.
- Observations must preserve exact quotes but avoid storing secrets when upstream memory defense/poison filters identify them.
- If later memory-defense hooks are added, they must run before observation consolidation.

---

## Performance Requirements

- Default retrieval path remains lightweight.
- Observation consolidation runs out-of-band through maintenance/scripts.
- Reranker/model path is disabled by default.
- `budget='low'` should avoid full source hydration.
- Search should not load full raw content unless `include_sources=True`, `include_raw=True`, or explicit expand/get is requested.

---

## Open Questions for Hephaestus Before Build

These should be resolved during implementation planning, not guessed in code:

1. Should observations consolidate only `ichor_events` first, or should Postgres `conclusions` be included in the first implementation phase?
2. Should `scope:pantheon` be backfilled onto all existing god-fleet memory, or only newly written memory?
3. Should strict tags become the default when any tag is passed, or only when a `user:<id>` tag is present?
4. Should knowledge pages be exposed as separate MCP tools or only as a retrieval backend?
5. Should reconcile mark superseded rows instead of deleting them everywhere, or only on new code paths?
6. Which god/channel supplies trusted `user:<id>` tags for Discord/Telegram calls?

---

## Source Ledger

Primary research report:

```text
/home/konan/athenaeum/Codex-God-thoth/research/hindsight-ichor-source-dive/report.md
```

Key source claims from the report:

- Hindsight recall uses semantic, BM25, graph, and temporal retrieval with RRF and reranking.
- Hindsight observations are evidence-grounded beliefs with exact quotes, proof counts, timestamps, and trend.
- Hindsight strict tags are SQL filters before ranking; strict modes exclude untagged rows.
- Hindsight mental models/knowledge pages are standing answer projections with provenance/versioning.
- Ichor currently has FTS5 events, graph, god-aware ranking, Tier A extraction, background review nudge, conservative reconcile, and progressive hydration.
- Ichor lacks first-class observation consolidation, general tag lattice, event-level temporal validity, budget/max_tokens recall controls, and generic knowledge pages.

Local code anchors:

```text
/home/konan/pantheon/schemas/ichor-events.sql
/home/konan/pantheon/lib/ichor_db.py
/home/konan/pantheon/lib/ichor_hybrid.py
/home/konan/pantheon/lib/ichor_mcp.py
/home/konan/pantheon/lib/ichor_memory_score.py
/home/konan/pantheon/lib/ichor_patterns.py
/home/konan/pantheon/lib/ichor_tier_a.py
/home/konan/pantheon/plugins/pantheon/ichor_nudge.py
/home/konan/pantheon/lib/ichor/reconcile.py
/home/konan/pantheon/lib/ichor/retrieval_hydration.py
/home/konan/pantheon/lib/ichor/retrieve_fusion.py
/home/konan/pantheon/lib/user_observations.py
```

---

## Definition of Done

This build is complete when:

- [ ] Schema is additive and migration-safe.
- [ ] Existing Ichor APIs remain backward-compatible.
- [ ] Events can carry tags and temporal fields.
- [ ] Observation consolidation produces source-backed observations with exact quotes and proof counts.
- [ ] Observation retrieval works through Ichor.
- [ ] `prefer_observations` suppresses only raw rows proven to be sources of returned observations.
- [ ] Strict tags/scopes are enforced before ranking.
- [ ] Budget/max_tokens/query_timestamp controls are available and tested.
- [ ] Knowledge pages exist as rebuildable projections from observations.
- [ ] Retrieval ladder returns LCM expansion hints for exact-evidence needs.
- [ ] Optional reranker is disabled by default and safe when unavailable.
- [ ] Retrieval metadata is logged for Forge/benchmark review.
- [ ] New targeted tests and existing Ichor regression slice pass.
- [ ] Docs explain how to use the upgraded system and when to use LCM exact evidence.

---
## Implementation Status — 2026-08-06
- Implemented files: additive schema/migrations, tag/temporal helpers, observation consolidation and retrieval, budgeted hybrid recall, knowledge pages, recall ladder, disabled-by-default reranker, MCP pass-through/recall metadata, dry-run backfill/consolidation scripts, docs, and Hindsight contract tests.
- Verification: py_compile, new target Hindsight tests, minimal Ichor regression slice, dry-run script smokes, MCP temp-HOME smoke, and git diff hygiene were run during Hermes review.
- Remaining operator note: no live DB backfill applied; run dry-runs against the target DB before any apply/consolidation pass.
