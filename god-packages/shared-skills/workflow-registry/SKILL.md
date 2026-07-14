---
name: workflow-registry
description: "Use when Hephaestus needs to query the workflow catalog — find a workflow by ID, find similar workflows, register a new workflow, get the canonical path of a workflow, or check the registry's health. The workflow-registry is the queryable, machine-readable version of the workflow catalog."
version: 1.0.0
tags: [workflow, registry, catalog, query, hephaestus]
---

# Workflow Registry — The Queryable Catalog

> **The skill that provides a queryable, machine-readable interface to the workflow catalog.** The catalog itself is at `Codex-Pantheon/workflows/`. The registry adds queries: find, search, register, get, list. Hephaestus uses this when the build-plan-orchestrator's t2 (catalog lookup) needs depth.

## When to use this skill

Load this skill whenever:

- Hephaestus is doing a t2 catalog lookup (in the build-plan-orchestrator chain)
- A god needs to find a workflow by name, tag, or pattern
- A new workflow is being registered (post-build artifact)
- The catalog needs a query for "what workflows use pattern X?"
- The operator asks "do we have a workflow for X?"
- A workflow's metadata is being updated (e.g., dispatch count, last run)

**Don't use this skill for:**

- Authoring a new workflow (use `conductor-design-workflow`)
- Listing the catalog (just read `Codex-Pantheon/workflows/INDEX.md`)
- Running a workflow (use `hermes conductor run <name>`)

## How to use it (the procedure)

### Step 0: Load the registry

The registry has three parts:

1. **The catalog files** — `Codex-Pantheon/workflows/<name>.md` (the prose)
2. **The YAML metadata** — `Codex-Pantheon/workflows/.registry.yaml` (the queryable metadata)
3. **The INDEX** — `Codex-Pantheon/workflows/INDEX.md` (the human-readable index)

**The `.registry.yaml` is the machine-readable part.** It has one entry per workflow:

```yaml
workflows:
  - id: morning-briefing
    name: "Morning Briefing"
    category: scheduled
    path: "Codex-Pantheon/workflows/morning-briefing.md"
    owning_god: hephaestus
    status: active
    pattern: scheduled
    triggers:
      - cron: "0 7 * * *"
    uses_subsystems:
      - ichor
      - kanban
      - conductor
    tags: [briefing, daily, scheduled]
    dispatch_count: 245
    last_run: 2026-06-16T07:00:00Z
    created: 2026-04-01
    updated: 2026-06-15
    description: "Daily morning briefing at 7am. Aggregates overnight research, kanban status, and Conductor state into a single Telegram message."
```

The skill reads `.registry.yaml` and the catalog files in tandem.

### Step 1: Identify the query type

There are 6 query types:

1. **Find by ID** — "get the workflow with ID X"
2. **Search by keyword** — "find workflows matching keyword Y"
3. **Filter by tag/pattern/owning_god** — "list all workflows owned by hephaestus with tag X"
4. **List all active** — "what workflows are available?"
5. **Register a new workflow** — "add workflow X to the registry"
6. **Update metadata** — "workflow X ran successfully, increment dispatch_count"

### Step 2: Run the query

#### Query type 1: Find by ID

**Input:** `<workflow_id>` (e.g., "morning-briefing")

**Method:** look up the ID in `.registry.yaml`, return the full entry + the path to the catalog file.

**Output:**

```yaml
query:
  type: by_id
  workflow_id: <input>
  found: true
  entry: {<full registry entry>}
  catalog_path: <path>
  catalog_content: <the markdown content>
```

#### Query type 2: Search by keyword

**Input:** `<keyword>` (e.g., "morning", "research", "approval")

**Method:** search both `.registry.yaml` (in `name`, `description`, `tags`) and the catalog files (in the body). Score by relevance.

**Output:**

```yaml
query:
  type: by_keyword
  keyword: <input>
  matches:
    - id: <workflow_id>
      name: <name>
      similarity_score: 0.0-1.0
      matched_in: [<where the match was found>]
      description: <one-line>
      catalog_path: <path>
    - ...
  best_match: <workflow_id>  # if any
```

**Scoring:**

- `name` exact match: 1.0
- `name` substring: 0.8
- `description` substring: 0.5
- `tag` exact match: 0.7
- `tag` substring: 0.5
- Catalog body match: 0.3 (per occurrence, capped at 0.5)

#### Query type 3: Filter by attribute

**Input:** `<filter>` (e.g., `{owning_god: hephaestus, pattern: scheduled, status: active}`)

**Method:** filter `.registry.yaml` by the criteria.

**Output:**

```yaml
query:
  type: by_filter
  filter: <input>
  matches:
    - id: <workflow_id>
      name: <name>
      ...
    - ...
```

**Filter fields:**

- `owning_god` — exact match
- `pattern` — exact match (pipeline, fan_out, fan_in, approval_gated, scheduled, event_triggered, etc.)
- `category` — exact match (scheduled, triggered, manual, etc.)
- `status` — exact match (active, inactive, draft)
- `tag` — substring match
- `uses_subsystem` — exact match (which subsystems the workflow calls)
- `created_after` / `created_before` — date range
- `updated_after` / `updated_before` — date range

#### Query type 4: List all active

**Input:** none (or a status filter)

**Method:** filter `.registry.yaml` for `status: active`.

**Output:**

```yaml
query:
  type: list_active
  total: <count>
  workflows:
    - id: <workflow_id>
      name: <name>
      ...
    - ...
```

#### Query type 5: Register a new workflow

**Input:** the new workflow's metadata + path to the catalog file.

**Method:** validate the new workflow against the standards, append to `.registry.yaml`, append to `INDEX.md`.

**Validation:**

- The catalog file exists at the path
- The catalog file follows the workflow shape (per `conductor-workflow-shape.md`)
- The metadata has all required fields
- The workflow ID is unique
- The owning god is active

**Output:**

```yaml
query:
  type: register
  workflow_id: <id>
  registered: true
  registry_path: "Codex-Pantheon/workflows/.registry.yaml"
  catalog_path: <path>
  validation: pass | fail
  validation_errors: [<list, if any>]
```

#### Query type 6: Update metadata

**Input:** `<workflow_id>` + the fields to update.

**Method:** read `.registry.yaml`, update the entry, write back.

**Output:**

```yaml
query:
  type: update
  workflow_id: <id>
  updated_fields: {<field>: <new value>}
  updated: true
```

**Common updates:**

- `dispatch_count` — incremented after a successful run
- `last_run` — set after a successful run
- `last_result` — set after a successful run (the result metadata)
- `status` — flipped when the workflow is deprecated
- `description` — updated when the workflow's purpose changes

### Step 3: Return the result

The query result is returned to the calling skill. The calling skill uses the result to:

- **Find by ID** — get a workflow's full details
- **Search by keyword** — find candidates for a new use case
- **Filter by attribute** — list workflows by some criteria
- **List all** — get the full catalog
- **Register** — add a new workflow (post-build artifact)
- **Update** — record a run or update metadata

## Worked example

### Example 1: Build-plan t2 catalog lookup

**Context:** the conductor-ui build, t2 needs to find similar workflows.

**Query:**

```yaml
query:
  type: by_keyword
  keyword: "visual workflow editor"
```

**Result:**

```yaml
matches:
  - id: build-plan-conversion
    similarity_score: 0.92
    matched_in: [name, description]
    description: "The 5-step user-in-the-loop chain"
    catalog_path: "Codex-Pantheon/workflows/build-plan-conversion.md"
  - id: fan-out-then-merge
    similarity_score: 0.85
    matched_in: [tags]
    description: "Fan out to N parallel branches, merge the results"
    catalog_path: "Codex-Pantheon/workflows/fan-out-then-merge.md"
  - id: approval-gated
    similarity_score: 0.88
    matched_in: [name, description]
    description: "Phase-gated approval chain"
    catalog_path: "Codex-Pantheon/workflows/approval-gated.md"
best_match: build-plan-conversion
```

The t2 worker uses this result to inform the build plan.

### Example 2: Register a new workflow

**Context:** the conductor-ui build, Phase 4 ships a new workflow for the Soulforge interview.

**Query:**

```yaml
query:
  type: register
  workflow_id: conductor-ui-soulforge-new-node
  catalog_path: "Codex-Pantheon/workflows/conductor-ui-soulforge-new-node.md"
  metadata:
    name: "Conductor UI Soulforge — New Node Interview"
    category: manual
    owning_god: hephaestus
    pattern: approval_gated
    status: active
    triggers:
      - manual: operator
    uses_subsystems:
      - ichor
      - ledger_client
      - soulforge
    tags: [soulforge, conductor-ui, node-authoring, interview]
    description: "Soulforge interview for authoring a new node in the Conductor UI visual editor"
```

**Result:**

```yaml
validation: pass
registered: true
```

## Integration with build-plan-orchestrator

The `build-plan-orchestrator` skill's t2 (catalog lookup) uses this skill for the deep search. The fast-path is the keyword matching in the workflow-catalog-lookup skill (which is currently the same as this). When the fast-path is insufficient, this skill is the deep-path.

## Integration with post-build artifacts

The `build-plan-shape` standard says every plan should produce a post-build artifact (a catalog entry for any new workflow). The plan's §12 lists the artifacts. After a build ships, the dispatcher uses this skill to register the new workflows.

## When the registry changes

Registry changes are **Hephaestus-managed** (not operator-locked, since the registry is a tool). Changes are:

- **Appended** when a new workflow is registered
- **Updated** when a workflow's metadata changes
- **Marked** when a workflow is deprecated (`status: inactive`)

The registry's `.registry.yaml` is **append-friendly** but should be reviewed periodically. Hephaestus's `athenaeum-maintenance` skill includes a registry audit.

## Pitfalls

**Don't trust the registry over the catalog.** The catalog files are the source of truth for what a workflow *is*. The registry is the source of truth for what workflows *exist* and their metadata.

**Don't register without a catalog file.** A registry entry without a catalog file is a phantom. Always create the file first.

**Don't update dispatch_count manually.** It's updated by the workflow runner, not by humans.

**Don't trust the similarity score alone.** The keyword search is approximate. Always read the matched catalog file to confirm.

**Don't filter by deprecated attributes.** If a workflow is `status: inactive`, don't include it in "active workflows" queries.

## Verification gates

Workflow-registry is "working" when:

- [ ] All 6 query types produce correct results
- [ ] The registry stays in sync with the catalog files
- [ ] The INDEX.md is updated when a workflow is registered
- [ ] Dispatch counts and last_run are accurate
- [ ] Inactive workflows are marked correctly

## See also

- `Codex-Pantheon/workflows/INDEX.md` — the catalog index
- `Codex-Pantheon/workflows/.registry.yaml` — the machine-readable metadata
- `Codex-Pantheon/design/standards/conductor-workflow-shape.md` — what a workflow looks like
- `pantheon/god-packages/shared-skills/workflow-catalog-lookup/` — the existing catalog-lookup skill
- `pantheon/god-packages/shared-skills/conductor-design-workflow/` — the workflow design skill
- `pantheon/god-packages/shared-skills/build-plan-orchestrator/SKILL.md` (v1.0.4) — uses this skill at t2
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — registers new workflows at ship time
