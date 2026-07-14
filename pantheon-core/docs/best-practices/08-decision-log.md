---
title: "Decision Log — how Pantheon records operator-locked decisions"
last_verified: 2026-06-19
---

# Decision Log — how Pantheon records operator-locked decisions

Decisions are how Pantheon remembers *why* the system is the way it is. Without the decision log, every operator re-litigates every choice. With it, the system compounds.

## What an "operator-locked decision" is

An operator-locked decision is a choice that:

1. Was made by the human operator (Konan), not by a god
2. Other operators and gods need to follow
3. Is durable (won't change in a week)
4. Has a rationale that should outlive the conversation

**If a decision meets all four criteria, it goes in the log. If it meets three, it goes in the log. If it meets two, it depends on reversibility cost.**

Examples of operator-locked decisions:

- "Hephaestus absorbs PM as a sub-domain of plan_authoring." *(Meets 4/4.)*
- "Use ChromaDB for semantic memory, not Pinecone." *(Meets 4/4.)*
- "Conductor UI is themeable; theme lives in `~/pantheon/conductor/theme/`." *(Meets 3/4 — second operator may override.)*
- "We use lowercase-with-hyphens for all file names." *(Meets 4/4 — codified convention.)*

Examples of things that are NOT operator-locked decisions:

- "Tomorrow's standup is at 10am." *(Transient, no rationale to record.)*
- "I think we should try Postgres for the new table." *(Speculative, not yet a decision.)*
- "Marvin should refactor the auth module." *(Task, not decision.)*

## How to record a decision

### Method 1 — Via chat (easiest)

```
> Record this decision: [your decision text]
```

The active god (usually Thoth) will:

1. Draft a structured decision entry
2. Save it to `~/pantheon/shared/decisions/konan/`
3. Notify relevant gods via god-notify
4. Add it to the Ichor memory store (so the next session can recall it)

The decision file follows a standard YAML-frontmatter + markdown shape (see below).

### Method 2 — Via the MCP tool

```python
ichor_store(
    key="decision:2026-06-19--032--short-slug",
    content="The decision text, with rationale and reversibility.",
    category="decision",
)
```

This is for programmatic recording (e.g., from a build plan executor). The chat method is preferred for human-initiated decisions.

## The decision file shape

Every decision is a single markdown file at:

```
~/pantheon/shared/decisions/konan/YYYY-MM-DD--NNN--short-slug.md
```

- `YYYY-MM-DD` — date the decision was made
- `NNN` — sequence number for that day (zero-padded, e.g., `001`, `002`)
- `short-slug` — kebab-case summary of the decision

### Frontmatter

```yaml
---
date: 2026-06-19T16:21:58-06:00
domain: development
priority: 7
source: chat
tags: [assistant, infrastructure]
operator: konan
summary: "One-line summary of the decision."
sequence: 032
---
```

The fields:

- `date` — ISO timestamp
- `domain` — free-form area tag (development, design, operations, etc.)
- `priority` — 1-10 scale; 10 is critical
- `source` — where the decision came from (chat, plan, build, etc.)
- `tags` — searchable labels
- `operator` — who made the decision
- `summary` — one-line summary, shown in INDEX.md
- `sequence` — the global sequence number across all decisions

### Body

The body follows a soft template:

```markdown
# [Decision title]

## Context
What was the situation? What was at stake?

## Decision
What did we decide? Be specific.

## Rationale
Why this and not the alternatives?

## Alternatives considered
What were the other options and why were they rejected?

## Reversibility
How do we undo this if it turns out wrong? What's the cost?

## Cross-references
Links to other decisions, plans, or codex entries this relates to.
```

**You don't have to follow this template strictly.** The most important thing is that a future operator (or future you) can read the file and understand:

1. What was decided
2. Why
3. What to do if it turns out wrong

## How decisions are looked up

### Method 1 — Search by topic

```
> Find the decision about [topic]
```

The active god will search the decisions directory and the Ichor memory store.

### Method 2 — The INDEX

Every decisions directory has an `INDEX.md` that's auto-maintained. It lists the most recent decisions with summaries.

```bash
cat ~/pantheon/shared/decisions/konan/INDEX.md
```

### Method 3 — By sequence number

Decisions have a global sequence number. If someone references "decision 031," you can find it:

```bash
ls ~/pantheon/shared/decisions/konan/2026-06-19--031--*
```

## Reversing a decision

Decisions are append-only. You don't edit or delete a decision. To reverse one:

1. **Make a new decision** that explicitly reverses or supersedes the old one
2. The new decision's `## Reversibility` section explains the reversal
3. Optionally, mark the old file as superseded with a header

Example reversal:

```markdown
# Reverse: Hephaestus absorbs PM as sub-domain of plan_authoring

## Reverses
- `2026-06-19--031--pm-skills-installation-and-hephaestus-absorption.md`

## Why reversed
[reason]

## What changes
[concrete changes to god.json, SOUL.md, etc.]

## Status
[reverted / in-progress / partial]
```

The history of decisions is the *evolution* of the system. Erasing history is how systems lose the ability to learn.

## Anti-patterns

- **Don't record a decision in chat only.** "I'll write it down later" is how decisions get lost. The cost of recording is 30 seconds.
- **Don't record a decision that doesn't meet the operator-locked criteria.** Cluttering the log with tasks and speculations makes the signal-to-noise ratio worse.
- **Don't reverse a decision by editing the file.** Always append a new decision that reverses the old one. The history matters.
- **Don't skip the rationale.** "We decided X" without "because Y" is useless in 3 months.

## See also

- [MCP Tools](09-mcp-tools.md) — `ichor_store` and the decision workflow
- [Context Management](01-context-management.md) — how decisions fit into the broader memory system
- [Common Pitfalls](07-common-pitfalls.md) — what goes wrong with decision discipline
