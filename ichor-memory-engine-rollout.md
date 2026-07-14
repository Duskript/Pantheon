## Addendum A — Thoth Gap Analysis: What the Ichor Plan Missed

> **Source:** Thoth research session (Codex-Pantheon/research/openhuman-memory-system-analysis.md)
> **Cross-Reference:** Current Athenaeum system health audit (2026-05-19)
> **Date:** 2026-05-19
> **Status Update 2026-05-20:** Phases 0-4 all live ✅
>
> - **Phase 4 — The Forge**: `lib/ichor_forge.py`, 28 tests, MCP tool registered. Self-adjusting harness loop — analyzes gate intervention logs, detects over-blocking/missing keywords/recurring patterns, proposes adjustments. Patterned after Hermes Dojo. Idle until intervention data accumulates.
> - **Phase 3 — RALPH 5-gate harness**: `lib/ichor_gates.py`, 70 tests passing, MCP tool registered. **Every god gets gates automatically** via `~/.hermes/plugins/ichor-gates/` plugin (pre/post_tool_call hooks). Agent restart to activate.
> - **Compaction hook**: Tier A extraction fires on every context compression
> - **Subconscious Engine**: Cron job every 15m pushes situation reports to god inboxes
> - **Ichor Brief**: MCP tool + CLI for query-less ranked context recall
> - **Hybrid Scorer**: Fused search across FTS5 + ChromaDB + Graph + Events (4/4 healthy)
> - **Memory Trait Contract**: Unified ichor_retrieve/store/forget/health MCP tools
> - **Graph Query**: Multi-hop NL graph queries with relation inference and entity resolution

---

### Pre-Existing Critical Issues (Blockers)

These are not gaps in the Ichor plan — they are **already-broken systems** that must be fixed before Ichor Phase 2 (Hybrid Scorer) can function:

| Issue | Severity | Impact | Priority |
|-------|----------|--------|----------|
| **Entity graph is dead** — `graph.db` is 0 bytes, extract-entities.py crashes at line 703 | 🔴 CRITICAL | Every `athenaeum_graph_search` returns nothing. The graph signal in the Hybrid Scorer will be silent | **P0 — fix NOW** |
| **61 files not embedded** — Codex-General (442 files) and Codex-Apollo (80 files) have 0 ChromaDB embeddings | 🟡 MAJOR | Entire codices invisible to semantic search | P1 — after graph fix |
| **No safety layer** — Zero secret redaction on any Athenaeum write path | 🟡 MAJOR | API keys, tokens, private keys stored in plaintext in knowledge base | P1 — wrap into Phase 0 |

---

### Gaps from Thoth's OpenHuman Analysis

Features OpenHuman has that our Ichor plan doesn't adequately cover:

#### A. Subconscious Engine — *Quick Win, High Impact*

OpenHuman has a periodic background tick that runs every N minutes:
1. Load due tasks from SQLite
2. Build situation report from memory data (zero-LLM)
3. Single LLM call: evaluate tasks + emit reflections
4. Tasks: `act` (execute), `escalate` (ask user), `noop` (skip)
5. Overlap guard via tick generation counter
6. Can be disabled entirely

**Pantheon equivalent:** A lightweight cron job that scans god memory files for open questions, pending decisions, or stale commitments. Gives each god proactive awareness.

| Aspect | Our Current State | Target |
|--------|------------------|--------|
| Background tick | ❌ Nothing | Cron job, configurable per-god |
| Task evaluation | ❌ None | Single LLM call per tick |
| Reflection generation | ❌ None | Periodic context summaries |
| Overlap guard | ❌ None | Tick generation counter |

**Effort:** 1-2 sessions as standalone feature
**Impact:** High — gods become proactive instead of purely reactive

#### B. Query-Less Recall — *Quick Win*

OpenHuman has a dedicated recall mode with no input query:
```
score = priority(0.45) + graph(0.30) + freshness(0.25)
```
Returns: "what should I know right now?" — highest-priority context surfaced without the user asking for anything specific.

**Pantheon equivalent:** A `ichor_brief` tool that every god can call at session start to get a ranked summary of what's relevant.

| Aspect | Our Current State | Target |
|--------|------------------|--------|
| Query-less mode | ❌ Buried in Phase 2 | Standalone tool, available early |
| Priority scoring | ❌ None | Weighted formula per-god |
| Freshness decay | ❌ None | Time-weighted ranking |

**Effort:** 1 session as standalone tool
**Impact:** Medium-High — every god starts every session with context

#### C. Memory Trait Contract — *Medium Effort*

OpenHuman has a clean backend-agnostic contract:
```rust
store(namespace, key, content, category, session_id)
recall(query, limit, opts) -> Vec<Entry>
get(namespace, key) -> Option<Entry>
list(namespace, category, session_id) -> Vec<Entry>
forget(namespace, key) -> bool
count() -> usize
health_check() -> bool
```

**Pantheon equivalent:** One `ichor_store` / `ichor_retrieve` / `ichor_forget` tool that routes to the correct backend (FTS5, ChromaDB, Graph, Events) automatically. Gods never need to know which backend stores what.

| Aspect | Our Current State | Target |
|--------|------------------|--------|
| Store interface | 3 separate tools | Single `ichor_store` |
| Recall interface | 3 separate tools | Single `ichor_retrieve` |
| Delete interface | ❌ No unified delete | `ichor_forget` |
| Health check | ❌ No unified health | `ichor_health` |
| Backend routing | Manual (god picks the right tool) | Automatic (system routes by content type) |

**Effort:** 3-4 sessions, overlaps with Phase 2
**Impact:** Medium — simpler god tool surface, less cognitive load

#### D. Multi-Hop Graph Query Planning — *Requires Graph to Be Fixed First*

OpenHuman infers relation types from NL keywords:
- "where" → LOCATED_IN
- "works" → WORKS_FOR
- "uses" → USES
- "owns" → OWNS

And walks multi-hop chains: OWNS → TRAVELS_TO, USES → LOCATED_IN.

Plus temporal operators: `before/after/latest/earliest` with anchor entity resolution.

**Pantheon equivalent:** Extend `athenaeum_graph_search` with automatic relation type inference and chain walking. But **blocked until entity extraction is fixed** and graph.db is populated.

| Aspect | Our Current State | Target |
|--------|------------------|--------|
| Relation inference | ❌ None | NL keyword → relation type map |
| Multi-hop chains | ❌ None | Configurable depth chain walking |
| Temporal operators | ❌ None | before/after/latest/earliest |
| Anchor resolution | ❌ None | Entity resolution from partial match |

**Effort:** 2-3 sessions (post-graph-fix)
**Impact:** Medium-High — turns graph from lookup into reasoning tool

---

### Updated Phase Plan (With Addendum Items)

|| Order | Item | Phase | Effort | Depends On | Status |
||-------|------|-------|--------|------------|--------|
|| **0a** | **Deprecate LLM extraction** — Hades skips extract-entities.py | 🔴 Pre-Phase 0 | 0 sessions (done) | — | ✅ |
|| **0b** | **Tier A regex extraction** — zero-LLM event extraction on session close | Phase 1 (was P1, bumped to P0) | 4-5 sessions | 0a | ✅ Built & tested |
|| **0c** | Safety layer (secret redaction) | Phase 0 expanded | 1 session | — | ✅ |
|| **0d** | **Subconscious Engine cron** — periodic proactive awareness tick | New standalone | 1-2 sessions | — | ✅ DONE 🎉 |
|| **0e** | **Query-less recall (ichor_brief)** — ranked context tool, 'what should I know right now?' | Phase 0.5 | 1 session | 0b | ✅ DONE 🎉 |
|| **1** | **Compaction hook** — wire Tier A into Hermes Agent compression | Phase 1 | 1 session | 0b | ✅ DONE 🎉 |
|| **3** | **Hybrid Scorer + Memory Trait Contract** | Phase 2 | 5-7 sessions | 1 | ✅ DONE 🎉 |
|| **4** | **Multi-hop graph query planning** — NL graph queries, entity resolution, relation inference, BFS traversal | Phase 2.5 | 2-3 sessions | 0a, 3 | ✅ DONE 🎉 |
||| **5** | **RALPH 5-gate harness** — `lib/ichor_gates.py` | **Phase 3** | **8-10 sessions → 1 session** 🏆 | 3 | ✅ **DONE 🎉** |
|||| 6 | The Forge | Phase 4 | 5-7 sessions | 5 | ✅ **DONE 🎉** |

---

### Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Entity extraction crash takes long to debug | Medium | High — blocks all graph-dependent features | Start with it. Have fallback path that skips entities if fix takes >1 session |
| Subconscious Engine cron floods gods with noise | Medium | Medium | Overlap guard + rate limiting + per-god opt-out |
| Safety layer misses novel secret patterns | Low | Medium | Tier A-style pattern expansion; periodic pattern audit |
| Memory Trait Contract adds middleware latency | Low | Medium | Profile before/after; cache hot paths |
