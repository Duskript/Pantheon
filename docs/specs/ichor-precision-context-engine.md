# Ichor Precision Context Engine — Reference Design

## Purpose

The product goal is not to make lossy context compaction better. The goal is to make routine context compaction unnecessary by changing Hermes from an ever-growing live transcript into a bounded, memory-backed context selector.

Current Hermes shape:

```text
append every turn to live messages
→ live prompt grows
→ hit threshold
→ ContextCompressor summarizes/drops old middle
→ keep sending large active context until the next compaction
```

Target Ichor shape:

```text
ingest every turn losslessly into Ichor
→ maintain session frontier and fresh tail
→ classify the current turn
→ select only context needed for this turn
→ expose exact recall/expand tools for anything omitted
→ send a small source-backed prompt
```

This makes Ichor the memory substrate and `IchorContextEngine` the compressor-replacement surface. The `compress()` method still satisfies Hermes' `ContextEngine` interface, but internally it means **memory promotion plus bounded active-context assembly**, not lossy summarization.

## Non-goals

- Do not re-enable the separate Hermes-LCM plugin fleet-wide.
- Do not keep injecting a static context pack forever.
- Do not summarize raw truth into authority; summaries are derived views only.
- Do not rely on large prompt windows as the primary memory strategy.
- Do not mutate live profile/fleet config until default-off benchmarks prove the engine.

## Operating invariants

1. **Raw turns are authoritative.** Every user, assistant, tool-call, and tool-result message is stored losslessly with source metadata and content hashes.
2. **Active prompt is bounded every turn.** The model should receive only the current request, a small fresh tail, active frontier state, and relevant selected memory.
3. **No-op turns stay cheap.** If the current turn does not need stored context, inject nothing beyond the fresh tail and stable system/user rules.
4. **Derived context is source-backed.** Decisions, constraints, files, and summaries point back to exact raw turns or canonical source files.
5. **Exact expansion is available on demand.** Omitted context can be recalled by handle/source id via `ichor_recall`, `ichor_expand`, or `ichor_inspect`.
6. **Fresh user intent wins.** Recent user instructions and current task state outrank older summaries or stale memory.
7. **Fallback preserves safety.** If Ichor selection fails, preserve fresh tail and fall back to default compressor or unchanged messages according to configured mode.

## Per-turn context assembly pipeline

### 0. Inputs

Each turn starts with:

- full in-process message list supplied by Hermes
- current user message
- session id / platform thread id
- tool schemas available to this session
- token budget from model metadata
- Ichor session frontier state

### 1. Lossless turn ingestion

Before selection, persist any new messages since the last frontier:

```text
raw_turns(session_id, seq, role, content_hash, content, source, tool_name, timestamps)
raw_tool_results(session_id, seq, tool_call_id, tool_name, status, content_hash, content)
```

Cost control:

- append-only writes
- content hash dedupe for repeated tool output
- store large tool results by blob reference, not repeatedly inline
- batch writes once per turn, not per selector phase
- avoid LLM extraction on the hot path

### 2. Frontier update

Maintain a compact session frontier:

```text
session_id
last_ingested_seq
active_tail_start_seq
last_selected_context_ids
current_task_id
current_topic_hash
fresh_tail_count
turn_count_since_topic_shift
```

The frontier says what can be omitted from the live prompt because it is safely stored and recallable.

### 3. Cheap current-turn classification

Use deterministic first-pass classifiers before any semantic/vector work:

- command shape: build / compare / summarize / debug / recall / casual
- topic shift vs continuation
- named entities: repo, branch, PR, file path, god, service, endpoint, artifact path
- explicit references: “that”, “this”, “the benchmark”, “PR #138”, “continue”
- safety-sensitive intent: config change, gateway restart, destructive op, credential work

Cost control:

- regex/path/entity extraction first
- only use vector search when lexical/entity confidence is low
- no LLM call for routine classification
- cache classification result by current-message hash

### 4. Candidate memory retrieval

Build a candidate set from multiple cheap lanes, in priority order:

1. **Pinned active state** — current todos, current branch/PR/artifact, latest user directive.
2. **Fresh tail references** — entities mentioned in the last N turns.
3. **Exact lexical matches** — file paths, PR ids, branch names, artifact names, service names.
4. **Ichor facts/events/decisions** — source-backed facts scoped to the current task/god/project.
5. **Vector/semantic recall** — only if lexical/entity lanes do not satisfy coverage.
6. **Raw-turn handles** — include handles for expansion, not full raw text unless required.

Cost control:

- hard cap rows examined per lane
- stop early when coverage is sufficient
- prefer structured indexed rows over raw transcript scans
- negative cache known no-op/casual queries
- per-session hot cache for recently selected context ids

### 5. Relevance scoring and pruning

Score candidates with a cheap weighted model:

```text
score = recency
      + explicit_reference_match
      + entity_overlap
      + active_task_match
      + source_authority
      + user_directive_priority
      - stale_topic_penalty
      - already_in_fresh_tail_penalty
      - large_payload_penalty
```

Then prune by:

- relevance threshold
- token budget
- diversity across categories: decisions, constraints, files, artifacts, risks
- source freshness
- contradiction handling: newer source-backed items outrank older summaries

### 6. Assemble bounded prompt sections

The engine returns a valid OpenAI-format message list containing:

```text
1. system/developer prompt layers already required by Hermes
2. stable user profile / durable preferences
3. current task frontier brief, if any
4. fresh tail: small number of recent raw turns
5. selected Ichor context pack: only relevant source-backed items
6. exact recall handles for omitted-but-available context
7. current user message
```

Recommended initial budgets:

```text
fresh_tail: 4–8 turns, dynamically reduced for tool-heavy sessions
frontier_brief: <= 250 tokens
selected_memory_pack: <= 600–900 tokens
recall_handles: <= 150 tokens
tool-result inline budget: <= 1,000 tokens unless current turn directly needs it
```

### 7. Exact expansion tools

If the model lacks enough detail, it should call tools instead of receiving everything upfront:

```text
ichor_status(session_id)
ichor_recall(query, scope, max_items)
ichor_expand(source_id | raw_turn_range | artifact_id)
ichor_inspect(frontier | selected_context | omitted_context)
```

The prompt should include handles like:

```text
Available expansions:
- raw_turns:session:123:seq:80-94 — PR #138 benchmark build loop
- artifact:/tmp/ichor-compressor-weight-benchmark-ready-reviewfix.../summary.json
- decision:ichor-context-engine-target
```

not the full historical text.

## Low-token strategy

1. **Do not send stored history by default.** Store it, index it, and pass handles.
2. **Use a small fresh tail.** Most turn coherence comes from the last few exchanges, not the full thread.
3. **Summaries are optional views, not mandatory prompt cargo.** If a summary is not relevant to the current turn, omit it.
4. **Prefer facts over prose.** A 40-token source-backed decision beats a 500-token paragraph.
5. **Prefer handles over payloads.** Send `expand_id` unless exact text is immediately necessary.
6. **Elide duplicated tool output.** If a tool result is already stored and not needed verbatim, include only status/hash/path.
7. **No-op suppression.** Casual acknowledgements and broad planning pivots should not pull database context unless entities match.
8. **Budget by category.** No single lane gets to consume the whole context window.

## Low-resource strategy

1. **Hot path is deterministic.** Regex/entity/path extraction and indexed lookup happen before vector or LLM work.
2. **Use SQLite/FTS/entity indexes first.** Chroma/vector search is a fallback, not default per turn.
3. **Batch writes.** One append transaction per turn.
4. **Deduplicate blobs by content hash.** Large repeated tool outputs are stored once.
5. **Cache selected packs.** Reuse when current-message/topic hash and frontier are unchanged.
6. **Bound all loops.** Max rows examined, max source expansions, max wall time.
7. **Degrade gracefully.** If retrieval exceeds budget, return fresh tail + handles, not a huge panic pack.
8. **Async extraction.** Expensive entity/relationship extraction can happen after the response as background enrichment.

## Minimal viable `IchorContextEngine`

```text
class IchorContextEngine(ContextEngine):
    name = "ichor"

    on_session_start:
      load/create frontier

    should_compress:
      return True when live messages exceed active-tail budget OR frontier needs advancement

    compress:
      ingest new raw turns
      classify current turn
      retrieve/prune selected memory
      assemble bounded messages
      save frontier
      return bounded OpenAI-format messages

    get_tool_schemas:
      expose ichor_status / ichor_recall / ichor_expand / ichor_inspect

    handle_tool_call:
      execute exact recall/expand against Ichor source records
```

## Benchmark acceptance for replacement

The replacement benchmark must measure per-turn prompt economy, not only after-threshold compression.

Compare:

```text
A: current Hermes transcript accumulation + default compressor
B: Ichor context-pack sidecar
C: IchorContextEngine selector
D: hybrid fallback
```

Required metrics:

- tokens sent per turn
- cumulative tokens sent over a task
- retained decision/constraint correctness
- source-grounding rate
- missed-context rate
- stale-context injection rate
- no-op injection rate
- latency and rows examined
- DB reads/writes
- LLM/API calls
- fallback behavior

Win condition:

```text
IchorContextEngine sends materially fewer tokens per turn than default transcript accumulation while preserving or improving task correctness and source grounding.
```

## Rollout path

1. Keep PR #138 as the augmentation/benchmark proof.
2. Build `IchorContextEngine` default-off behind explicit config.
3. Run per-turn token economy benchmark on long realistic sessions.
4. Canary only one disposable profile after benchmark win.
5. Promote to broader profiles only after rollback and no-op behavior are proven.
