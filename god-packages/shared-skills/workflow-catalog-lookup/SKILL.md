---
name: workflow-catalog-lookup
description: "Use when searching the workflow catalog for existing patterns similar to a build request. Returns the top 3-5 matches with similarity scores, locations, and modification guides. This is the second step in the build-plan-orchestrator chain."
version: 0.1.0
tags: [catalog, search, workflow, build-plan]
---

# Workflow Catalog Lookup — Finding Similar Patterns

This skill searches the workflow catalog at `~/athenaeum/Codex-Pantheon/workflows/` for existing patterns similar to a build request. The output is the top 3-5 matches with enough detail for the operator to decide "clone, modify, or scratch."

> **Status:** v0.1 stub. The catalog doesn't exist yet — see §"Bootstrap the catalog" below. This skill will be functional once 10-15 catalog entries are added.

## When to use this skill

Load this skill when:
- The `build-plan-orchestrator` step 2 task asks you to find similar workflows
- Someone asks "have we built something like X before?"
- You're writing a new workflow and want to start from a similar one

## The catalog structure

The catalog lives at `~/athenaeum/Codex-Pantheon/workflows/` (one file per workflow). Each entry is a markdown article with YAML frontmatter:

```markdown
---
workflow_id: morning-briefing
title: "Daily Morning Briefing"
type: conductor_yaml | kanban_task_pattern | direct_session | hybrid
location: ~/pantheon/conductor/workflows/morning-briefing.yaml
trigger: schedule.cron "0 6 * * *" | manual | event.nats.message | ...
duration: ~15m
gods_involved: [thoth, hermes, iris]
tags: [scheduled, daily, research, intel, summary, multi-god]
pattern: pipeline
difficulty: low
created: 2026-06-15
last_used: 2026-06-16
---

# Daily Morning Briefing

**What it does:** Pulls the day's intel, summarizes, formats, delivers to your Telegram.

**Use when:** You want a recurring daily/weekly summary of recent activity.

**Don't use when:** You need the summary to fire on an event (use an event-triggered workflow instead), or you need per-item approval gates (use Forge-autoresearch-style approval card).

**Modifications:** To add a new intel source, add a step after `last30days-research` and update the `input_from` chain.

**Cloning:** `cp ~/pantheon/conductor/workflows/morning-briefing.yaml ~/pantheon/conductor/workflows/<your-name>.yaml` and edit.
```

The skill uses Ichor search (FTS5) to find matches. Frontmatter fields are searchable.

## The lookup procedure

### Step 1: Read the search terms from the upstream task

The `workflow-tier-routing` task provides `catalog_search_terms` in its metadata. Use these as the primary search query.

### Step 2: Search the catalog

```python
# Via Ichor (FTS5)
results = ichor_search(
    query=" ".join(search_terms),  # e.g., "outreach sequence multi-touch approval"
    codexes=["Codex-Pantheon"],
    path_filter="workflows/",
    n_results=10,
)

# Or via filesystem fallback
from pathlib import Path
catalog = Path("~/athenaeum/Codex-Pantheon/workflows/")
for md_file in catalog.rglob("*.md"):
    content = md_file.read_text()
    if any(term.lower() in content.lower() for term in search_terms):
        results.append(md_file)
```

### Step 3: Score and rank

For each match, compute a similarity score:
- **Title match:** +0.3 if any search term is in the title
- **Tag match:** +0.2 for each matching tag
- **Description match:** +0.1 per matching term in the description (cap 0.4)
- **Pattern match:** +0.2 if the pattern matches the routing decision
- **Type match:** +0.1 if the type matches the routing decision

Sort by score. Take top 5.

### Step 4: Read the full match for each top result

For each of the top 5, read the full markdown file to extract:
- workflow_id
- location (path to the YAML or skill)
- description (one line)
- modification_guide (how to adapt for THIS project)

If the modification guide is too generic, write a custom one based on the build request.

### Step 5: Write the output

```python
kanban_complete(
    summary=f"Found {len(matches)} similar workflows. Best match is {best_match}.",
    metadata={
        "matches": [
            {
                "workflow_id": "...",
                "location": "...",
                "similarity_score": 0.85,
                "description": "...",
                "modification_guide": "...",
            },
            ...
        ],
        "best_match": "...",
        "no_match_fallback": "...",  # What to do if the catalog is empty
    },
)
```

### Step 6: Block for operator choice

```
kanban_block(
    reason="I found these similar workflows. Best match is [X]. "
           "Want to (1) clone and modify it, (2) start from scratch, "
           "or (3) extend a different existing one? "
           "Reply with: clone | scratch | extend <workflow_id>"
)
```

## Bootstrap the catalog (do this before the skill is useful)

The catalog doesn't exist yet. To make this skill functional, create 10-15 entries from existing patterns:

1. **Audit existing Conductor workflows** at `~/pantheon/conductor/workflows/`. For each, write a catalog entry. Skip the `bridge-test-*` test files.
2. **Audit existing kanban task patterns** by looking at the task types in the `kanban-task-shapes.md` reference. For each pattern, write a catalog entry.
3. **Add Mercer workflows as they're built.** When the first Mercer outreach sequence is built, add it.
4. **Add Ledger workflows as they're built.** When the Ledger Desk is built, add it.
5. **Add ad-hoc patterns as they emerge.** If you find yourself using the same kanban task shape 3+ times, add it to the catalog.

**Target: 15-20 entries by end of the parallel-work build.** The catalog grows organically as patterns emerge.

## Anti-patterns in cataloging

- **Don't catalog bridge-test-*** — those are test scaffolding, not real workflows
- **Don't catalog one-off workflows** — if it's been used <3 times, it's not a pattern yet
- **Don't write modification guides that are too generic** — be specific about what changes for THIS project
- **Don't list every god involved** — list the primary ones, not the support cast
