---
title: "Decision Log — how Pantheon records operator-locked decisions"
last_verified: 2026-09-01
---

# Decision Log — how Pantheon records operator-locked decisions

Decisions preserve why Pantheon is the way it is. This page describes the current human-readable audit trail in `~/pantheon/shared/decisions/` and its optional Ichor-memory companion, verified 2026-09-01.

## What an operator-locked decision is

An operator-locked decision is a choice that:

1. Was made or explicitly approved by the human operator
2. Other operators or gods need to follow
3. Is durable enough to outlive the current conversation
4. Has rationale that should remain discoverable

If the choice is still only a proposal, task, or experiment, keep it in the relevant plan or session context until it is approved.

Examples:

- choosing a repository or build-path convention
- setting a QA or approval gate that other workers must obey
- selecting a primary integration path
- reversing an earlier architecture or operations decision

Not decisions:

- a transient meeting time
- an unapproved suggestion
- a task assignment such as “refactor the auth module”

## Two records, two jobs

Pantheon currently has two complementary ways to preserve a decision:

1. **Decision Markdown** in `~/pantheon/shared/decisions/` — the human-readable, append-only audit trail. Add the decision to `INDEX.md` so operators can find it.
2. **Ichor event** with `category="decision"` — searchable FTS5-backed memory for retrieval and ranked context.

These are not the same write. The current `ichor_store` implementation routes `decision` to the `ichor_events` table; it does not create a Markdown file or maintain `shared/decisions/INDEX.md`. For important decisions, write both records.

## How to record a decision

### Method 1 — Via chat

```
> Record this decision: [decision text]
```

The active agent can draft the Markdown entry, append the index, and optionally call `ichor_store`. Review the resulting file and index entry; chat text alone is not the audit trail.

### Method 2 — Write the Markdown record

Create a file in the shared decisions directory using a date-and-slug filename:

```text
~/pantheon/shared/decisions/YYYY-MM-DD-short-slug.md
```

Then append a row to:

```text
~/pantheon/shared/decisions/INDEX.md
```

The repository contains both daily aggregate logs and more focused decision files. Do not assume a per-user subdirectory or a global numeric sequence; neither is enforced by the current Pantheon code or directory convention.

### Method 3 — Add searchable Ichor memory

```python
ichor_store(
    key="decision:2026-09-01-short-slug",
    content="Decision: ...\nRationale: ...\nReversibility: ...",
    category="decision",
    session_id="optional-source-session-id",
    god_name="optional-source-god",
)
```

Use a stable, descriptive key. The returned backend should be `fts5` for the current implementation. If `contradiction_warning` is returned, review the decision against recent high-importance memory rather than silently ignoring it.

## Recommended decision file shape

There is no runtime-enforced schema, but this compact shape is easy to review:

```markdown
# 2026-09-01 — [Decision title]

**Decision:** [What was decided, precisely.]

**Rationale:** [Why this option was selected.]

**Alternatives considered:**
- [Alternative] — [why not]

**Evidence:** [Plans, tests, source files, or operator instruction.]

**Reversibility:** [How to undo it and what the cost is.]

**Decided by:** [operator]
```

Use YAML frontmatter only when the surrounding codex convention requires it. Do not invent fields such as a global sequence number and present them as system-generated metadata.

## How decisions are looked up

### Search the human-readable index

```bash
# Read the index with your normal file viewer
$PANTHEON_ROOT/shared/decisions/INDEX.md
```

For a normal installation, `PANTHEON_ROOT` is `~/pantheon`. Search the directory by topic with your file-search tool or an MCP client.

### Search Ichor

```python
ichor_retrieve(query="topic or decision phrase", limit=10)
ichor_brief(god_name="", limit=20)
```

Use `pantheon_search` or `pantheon_locate` when you are unsure whether the artifact is a decision file, plan, skill, or another Pantheon component.

## Reversing a decision

The log is append-only:

1. Make a new decision file that explicitly reverses or supersedes the old one.
2. Link the old file in the new entry.
3. Explain why the reversal happened and what changes operationally.
4. Append the new entry to `INDEX.md`.
5. Store a corresponding Ichor decision event if future retrieval needs to distinguish the current choice.

Do not rewrite history to make the old decision disappear. If an index summary becomes stale, append the superseding decision and preserve the prior row unless the repository's index-maintenance convention explicitly says otherwise.

## Anti-patterns

- **Don't record a decision in chat only.** Put durable choices in the shared decision trail.
- **Don't claim `ichor_store` updates the Markdown log.** It currently writes the Ichor event backend only.
- **Don't use a per-user `decisions/konan/` path as if it were canonical.** The current tree uses `shared/decisions/` and `shared/decisions/INDEX.md`.
- **Don't assume a global sequence number or auto-maintained index.** The current convention is date-and-slug files plus an append-only index.
- **Don't reverse a decision by deleting or editing the original.** Add a new superseding record.
- **Don't skip rationale and reversibility.** A bare “we chose X” will not help the next operator.

## See also

- [MCP Tools](09-mcp-tools.md) — memory, retrieval, and Pantheon index tools
