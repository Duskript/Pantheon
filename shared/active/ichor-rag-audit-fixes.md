# Ichor RAG Audit Fixes — 4 Tasks

**Source:** Pantheon Ichor audit against the article *"Larger Context Windows Don't Fix RAG — So I Built a System That Does"* (EmiTechLogic on TDS, 2026-06-14).
**Knowledge article:** `Codex-God-thoth/distilled/concepts/retrieval-is-not-computation.md`
**Pattern:** Retrieval returns facts. Computation produces answers. Synthesis polishes language. Never confuse the three.

## The principle

Every Ichor retrieval must be **dumb and honest** — return ranked facts with a coverage signal. If a query is going to claim an aggregate, total, average, or ranking, the system must show the work. Anything less is pattern-matching dressed as computation.

The four fixes below close the gap between Ichor's current behavior and that principle. They're ordered by ROI: cheapest fixes first, biggest impact first.

---

## Task 1 — `total_matching` field on every Ichor retrieval

**What:** Every retrieval response carries a `total_matching` field — the count of all candidates that matched the query in the source table, not just the top-N that were returned.

**Why:** Right now a query returning 5 results looks complete even if there are 5,000 candidates. The reader has no way to know they're seeing 0.1% of the matches. This is the article's failure mode at the retrieval layer: silent truncation that looks authoritative.

**Where to change:**
- `athenaeum/tools/ichor_retrieve.py` (the Python tool) — add `SELECT COUNT(*) ...` to each backend
- The MCP `ichor_retrieve` tool — surface the field in the response
- The `ichor_retrieve` events in `cold_events` — log `total_matching` so synthesis layers can see it

**Cost:** ~2 lines per query path (one for the count, one for the return). Total: ~6-10 lines.

**Test:** Query for "conductor" → get 5 results, see `total_matching: 47`. Reader can now say "5 of 47" — honest coverage signal.

**Acceptance:** Every retrieval tool (FTS5, Graph, Events) returns `total_matching`. The field is part of the documented API.

---

## Task 2 — Alias expansion for FTS5 keyword search

**What:** Build an alias table — when a query matches a canonical term (e.g., "conductor"), the search automatically expands to include synonyms (e.g., "orchestration," "dispatch," "workflow engine," "reaction rule"). 

**Why:** FTS5 is keyword-based. It cannot tell that "orchestration" and "conductor" refer to the same concept. This is the article's bug, rebranded: keyword overlap returns partial coverage even when full coverage exists in the dataset. The reader sees 5 results, concludes the topic is small, and misses the other 23 that used different vocabulary.

**Where to change:**
- New table: `ichor.term_aliases` (canonical, alias, weight)
- Seed with Pantheon-domain terms: conductor, dispatcher, handoff, workflow → all expand to each other; god names; project codenames
- Modify `athenaeum/tools/ichor_retrieve.py` FTS5 path to expand query terms before searching

**Cost:** One alias table (~50 lines seed data) + ~30 lines in the query expander.

**Test:** Query for "conductor" → returns rows mentioning "orchestration" and "workflow engine" too. `total_matching` goes from 47 to 142 — the real coverage.

**Acceptance:** Alias expansion is a feature of the FTS5 path. Aliases are editable in one place (the seed file or a small admin command). Coverage goes up measurably on a regression test set.

---

## Task 3 — Subconscious synthesis coverage guard

**What:** The `ichor_subconscious.py` tick reports aggregate across events. Add a guard: synthesis queries must report `coverage_pct` and refuse to write a summary if coverage is below a threshold (e.g., 30%).

**Why:** Thoth's tick reports look authoritative. A 1-hour synthesis across 6 events from god X looks like a complete picture even if god X was active 47 times that hour. The reader sees polished output and assumes it's correct. Same bug as the article.

**Where to change:**
- `athenaeum/scripts/ichor_subconscious.py` — add a coverage check before synthesis
- The `report_length` field already implies coverage; add `coverage_pct` and `events_skipped` explicitly
- If `coverage_pct < 30` → write the report with a `[LOW COVERAGE]` warning banner, not a polished summary

**Cost:** ~30 lines in `ichor_subconscious.py`. One new field in the report schema.

**Test:** Force a tick with only 5 of 100 expected events for a god → report shows `coverage_pct: 5%` and the synthesis section says "insufficient coverage, raw events only."

**Acceptance:** Every subconscious tick report carries `coverage_pct`. Below 30%, the report degrades to raw events + warning, not a polished summary.

---

## Task 4 — L2 finalization blocker (don't summarize provisional entities)

**What:** Any query that summarizes across entities must filter to `provisional = 0` (finalized only). Provisional entities (8,199 currently, 11,251 relationships) are LLM-extracted and not yet validated. Summarizing across them summarizes noise.

**Why:** The L2 extractor has accumulated 8,199 provisional entities that have never been finalized. If Thoth's synthesis touches them — "what entities relate to conductor?" — it can return hallucinated relationships from an unvalidated extraction. Same bug as the article: top-N matches presented as complete picture.

**Where to change:**
- `athenaeum/tools/ichor_graph_query.py` — add `WHERE provisional = 0` to all entity/relationship queries by default; add an opt-in flag `include_provisional=True` for explicit L2-extraction work
- Add a one-line check: "If you query for entities, do not count provisional ones."

**Cost:** 1-line check. ~5 lines total in the tool wrapper.

**Test:** Query for entities related to "conductor" — return 12 finalized entities, not 47 (which includes 35 provisional). `total_matching` shows both, with the provisional count flagged.

**Acceptance:** Default behavior: finalized entities only. `include_provisional=True` is explicit and logged. Synthesis across entities is grounded in validated data.

---

## Optional larger shift (parking lot, not in this batch)

Two architectural changes that would prevent the failure mode systemically, but require more design work:

1. **Graph as primary for entity queries, FTS5 as fallback.** When user asks "what do we know about X," start at `warm_entities`, traverse the graph — don't keyword-search.
2. **Separate retrieval from synthesis in the API.** `ichor_retrieve` returns facts. `ichor_synthesize` is a separate call that requires `coverage_pct > N` as a precondition. Synthesis refuses to run on thin retrieval.

Both align with the article's principle. Both are bigger than the four fixes above. Park for now.

---

## Build order

1. **Task 1** (`total_matching`) — highest leverage, lowest cost. Ship first.
2. **Task 4** (L2 finalization blocker) — 1-line check, immediate correctness win.
3. **Task 2** (alias expansion) — biggest impact on coverage, but needs the alias table.
4. **Task 3** (subconscious guard) — last because it touches cron output and we want the data right before we guard the synthesis.

**Owner:** Marvin (Python) with Thoth review on the test cases.
**Estimated total:** ~100-120 lines of new code, 1 new SQLite table (`term_aliases`), 1 new report field (`coverage_pct`).
