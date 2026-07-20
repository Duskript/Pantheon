---
title: "Decisions Log — Index"
codex: "Codex-Pantheon"
type: "index"
status: "active"
created: "2026-06-16"
created_by: "Hephaestus rework design (operator-locked)"
authored_by: "Thoth (transcribed)"
related: [
  "Codex-Pantheon/design/INDEX.md",
  "Codex-Pantheon/design/operator-rules-cheatsheet.md",
  "pantheon/shared/decisions/"
]
tags: ["index", "decisions", "log", "operator-locked"]
---

# Decisions Log — Index

> **Every operator-locked decision, with the date, the title, and a one-line summary.** Hephaestus reads this before any chain to know "what has the operator already decided." New decisions get appended at the bottom (per the convention-doc-shape standard).

## How to use this index

1. **Before dispatching a chain** — read the most recent decisions to know what's in force
2. **Before writing a plan** — check if any decision constrains your plan
3. **Before asking the operator** — search the index; if the answer is here, don't ask
4. **After the operator makes a decision** — append to the index

The index is **append-only**. Old decisions are never edited. Reversed decisions get a new entry that points at the original.

## Recent decisions (chronological, newest first)

| Date | Title | One-line summary | File |
|---|---|---|---|
| 2026-07-20 | Content Ops Destination Registry | Content Operations targets are data-driven destinations with cross-post joins, not a fixed `surface` enum. | [2026-07-20-content-ops-destination-registry.md](2026-07-20-content-ops-destination-registry.md) |
| 2026-07-20 | Content Ops React Mobile UI Pivot | Content Operations UI moved from the rejected Appsmith experiment to a custom React/Vite mobile app served by Flask. | [2026-07-20-content-ops-react-mobile-ui-pivot.md](2026-07-20-content-ops-react-mobile-ui-pivot.md) |
| 2026-06-20 | Conductor UI Phase D closure — docs + SDK policy + Phase 4.5 gap | Phase D closed: feature flag verified, 3 docs written, decisions locked; Phase 4.5 (Credentials Store) is NOT actually shipped in the tree. | [2026-06-20-conductor-ui-phase-d-docs.md](2026-06-20-conductor-ui-phase-d-docs.md) |
| 2026-06-16 | Hephaestus Rework — God of Building and Architecture | Hephaestus is no longer the planner. He's the conductor. Konan + Thoth develop plans, Hephaestus executes. | [design/hephaestus-rework-workflow-god.md](../../../athenaeum/Codex-Pantheon/design/hephaestus-rework-workflow-god.md) |
| 2026-06-16 | Hephaestus Rework Execution Complete | All 7 steps of the rework execution order complete. SOUL.md, gods.yaml, 8 skills, dispatcher updates, decision logged. | [2026-06-16-hephaestus-rework-complete.md](2026-06-16-hephaestus-rework-complete.md) |
| 2026-06-16 | Build Path Convention | All builds live under `~/projects/<project-name>/`. Plans live under `~/pantheon/plans/`. | [design/build-path-convention.md](../../../athenaeum/Codex-Pantheon/design/build-path-convention.md) |
| 2026-06-16 | QA Gate Rule | Every code-producing kanban task has a follow-on Thoth `Action: REVIEW` task. Coder is not done until reviewer passes. | (in design/standards/qa-gate-rubric.md) |
| 2026-06-16 | No Time Estimates in Plans | Konan: "stop giving me time estimates, they're always wrong." No calendar durations in plans, reports, or skill outputs. | (in design/operator-rules-cheatsheet.md) |
| 2026-06-16 | Sovereignty Guardrail | External events (Tallon NATS, webhooks, cross-Pantheon) must NEVER auto-execute without explicit operator approval. Notify → ask. | (in design/operator-rules-cheatsheet.md) |
| 2026-06-16 | Step 4.9 Final — Brief 3 closure | Conductor 4.9 Brief 3 closed: 89/89 cli_tool tests pass, QA accepted. | [2026-06-16-step-4.final.md](2026-06-16-step-4.final.md) |
| 2026-06-16 | Step 4.8 — Brief 3 wiring | Wired cli_tools.yaml + load_tools_config into the engine. 6 config tests pass. | [2026-06-16-step-4.8.md](2026-06-16-step-4.8.md) |
| 2026-06-16 | Step 4.7 — Brief 2 closure | Brief 2 shipped: cli_tools.yaml + load_tools_config + tests. | [2026-06-16-step-4.7.md](2026-06-16-step-4.7.md) |
| 2026-06-16 | Step 4.6 — cli_tool runtime | Brief 1 closure: cli_tool.py + 30/30 tests pass. | [2026-06-16-step-4.6.md](2026-06-16-step-4.6.md) |
| 2026-06-16 | Step 4.5 — workflow spec | Workflow spec for cli_tool orchestration engine. | [2026-06-16-step-4.5.md](2026-06-16-step-4.5.md) |
| 2026-06-16 | Catalog Brief 3 closure | Conductor 4.9 Brief 3 closure report. | [2026-06-16-catalog-brief-3.md](2026-06-16-catalog-brief-3.md) |
| 2026-06-16 | Pitfall #26 | The pitfall: external events must never auto-execute. | [2026-06-16-pitfall-26.md](2026-06-16-pitfall-26.md) |
| 2026-06-15 | (session) | (large day, see file) | [2026-06-15.md](2026-06-15.md) |
| 2026-06-14 | (session) | | [2026-06-14.md](2026-06-14.md) |
| 2026-06-12 | (session) | | [2026-06-12.md](2026-06-12.md) |
| 2026-06-11 | D2 cron teardown | Tearing down the D2 cron job (deprecation). | [2026-06-11-d2-cron-teardown.md](2026-06-11-d2-cron-teardown.md) |
| 2026-06-11 | (session) | (large day) | [2026-06-11.md](2026-06-11.md) |
| 2026-06-09 | (session) | | [2026-06-09.md](2026-06-09.md) |
| 2026-06-05 | (session) | | [2026-06-05.md](2026-06-05.md) |
| 2026-06-04 | (session) | | [2026-06-04.md](2026-06-04.md) |
| 2026-06-03 | (session) | | [2026-06-03.md](2026-06-03.md) |
| 2026-06-02 | (session) | | [2026-06-02.md](2026-06-02.md) |
| 2026-06-01 | (session) | | [2026-06-01.md](2026-06-01.md) |

## Topical index (decisions by topic)

### Architecture

- 2026-07-20: [Content Ops Destination Registry](2026-07-20-content-ops-destination-registry.md) — destination registry + cross-post join table replaces fixed surface enum for target routing
- 2026-06-16: [Hephaestus Rework — God of Building and Architecture](hephaestus-rework-workflow-god.md)
- 2026-06-16: [Hephaestus Rework Execution Complete](2026-06-16-hephaestus-rework-complete.md) — all 7 steps executed
- 2026-06-16: [Build Path Convention](build-path-convention.md)
- 2026-06-11: (in [2026-06-11.md](2026-06-11.md))

### Conductor

- 2026-06-16: [Step 4.9 Final](2026-06-16-step-4.final.md)
- 2026-06-16: [Step 4.8](2026-06-16-step-4.8.md)
- 2026-06-16: [Step 4.7](2026-06-16-step-4.7.md)
- 2026-06-16: [Step 4.6](2026-06-16-step-4.6.md)
- 2026-06-16: [Step 4.5](2026-06-16-step-4.5.md)
- 2026-06-16: [Catalog Brief 3 closure](2026-06-16-catalog-brief-3.md)

### Conductor UI

- 2026-06-20: [Phase D closure — SDK policy + credentials + YAML format + Phase 4.5 gap](2026-06-20-conductor-ui-phase-d-docs.md)

### Standards + Conventions

- 2026-06-16: [Build Path Convention](build-path-convention.md)
- 2026-06-16: [Hephaestus Rework — introduces 10 standard shapes](hephaestus-rework-workflow-god.md)
- 2026-06-16: [QA Gate Rule](hephaestus-rework-workflow-god.md) (embedded)
- 2026-06-16: [No Time Estimates](operator-rules-cheatsheet.md) (embedded)

### Operations

- 2026-06-16: [Pitfall #26 — sovereignty guardrail](2026-06-16-pitfall-26.md)
- 2026-06-11: [D2 cron teardown](2026-06-11-d2-cron-teardown.md)

### Build plans

- 2026-07-20: [Content Ops Destination Registry](2026-07-20-content-ops-destination-registry.md)
- 2026-07-20: [Content Ops React Mobile UI Pivot](2026-07-20-content-ops-react-mobile-ui-pivot.md)
- 2026-06-16: [Conductor UI build plan v1.1](../../../pantheon/plans/conductor-ui-build-plan.md)

## How to add a new decision

1. Create a new file `YYYY-MM-DD-<slug>.md` in `pantheon/shared/decisions/`
2. Use the canonical format:

```markdown
# YYYY-MM-DD — <decision title>

**Decision:** <the decision>
**Rationale:** <why>
**Alternatives considered:** <what else was on the table>
**Evidence:** <citations, prior sessions, data>
**Reversibility:** <easy | hard | irreversible>
**Decided by:** <god> on <date>
**Operator sign-off:** <konan | pending>
```

3. Update this index (add a row to the chronological table + topical table if relevant)
4. If the decision affects a convention, update the relevant convention doc
5. If the decision affects a standard, update the relevant standard doc
6. If the decision affects a god, update the god roster

## Reversal protocol

If a decision is reversed:

1. **Do NOT edit the original** — append-only
2. Create a new entry that explicitly says "Reversing the decision from YYYY-MM-DD"
3. The new entry links to the original
4. Update the topical index (the old decision stays, the new reversal is added)
5. Notify the operator

## See also

- [Codex-Pantheon/design/INDEX.md](../../../athenaeum/Codex-Pantheon/design/INDEX.md) — the design index
- [Codex-Pantheon/design/operator-rules-cheatsheet.md](../../../athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md) — the rules cheatsheet
- [pantheon/shared/decisions/](.) — the raw decision files
