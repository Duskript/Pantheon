---
name: god-roster
description: "Use when Hephaestus needs to know which god owns a domain, what capabilities a god has, what their current assignment is, or who to route work to. The god-roster is the dispatch table. Updated when gods are added, reworked, or inactivated."
version: 1.0.0
tags: [gods, roster, dispatch, hephaestus, capability-lookup]
---

# God Roster — The Dispatch Table

> **The skill that looks up a god's lane, capabilities, and current status from the canonical god-roster.** Every dispatch decision starts with a roster query: "who owns this domain?" The roster is the source of truth for routing work.

## When to use this skill

Load this skill whenever:

- Hephaestus is about to dispatch a task and needs to know who to assign it to
- The dispatcher (in `kanban-orchestrator`) is doing keyword-matching for default assignee
- A new god is being created (roster update needed)
- A god is being reworked (roster update needed)
- The operator asks "who owns X?"
- The dispatcher routes a task and the routing is questioned (roster check)

**Don't use this skill for:**

- Listing every god (just read `Codex-Pantheon/design/god-roster.md`)
- Creating a new god (use `god-creation` skill)
- Modifying a god's profile (use `god-creation` + the rework design)
- The operator wants a status report (use `build-status` instead)

## How to use it (the procedure)

### Step 0: Load the canonical roster

The roster is maintained in two places:

1. **Machine-readable:** `pantheon/gods/gods.yaml` (the source of truth)
2. **Human-readable:** `Codex-Pantheon/design/god-roster.md` (the explanation)

The skill reads `gods.yaml` for lookups and `god-roster.md` for context.

### Step 1: Identify the lookup type

There are 5 lookup types:

1. **"Who owns <domain>?"** — domain lookup
2. **"What can <god> do?"** — capability lookup
3. **"Who is available for <task>?"** — availability lookup
4. **"What is <god>'s current assignment?"** — assignment lookup
5. **"List all active gods"** — full roster dump

### Step 2: Run the lookup

#### Lookup type 1: domain lookup

**Input:** `<domain>` (e.g., "code", "UI design", "research", "sales")

**Method:** read `gods.yaml`, find the god whose `role` and `description` match the domain most closely.

**Output:**

```yaml
lookup:
  type: domain
  domain: <input>
  matched_god: <name>
  rationale: <why this god matches>
  capability: <the specific capability that matches>
```

**Examples:**

| Domain | Matched god | Capability |
|---|---|---|
| `code`, `implement`, `build code` | `marvin` | `code_writing`, `test_writing` |
| `UI design`, `component`, `Figma` | `iris` | `design_system`, `figma_operations` |
| `research`, `synthesize`, `investigate` | `thoth` | `research`, `knowledge_synthesis` |
| `sales`, `outreach`, `lead` | `mercer` | `lead_qualification`, `pipeline_management` |
| `copy`, `writing`, `landing page` | `rheta` | `copywriting`, `content_humanization` |
| `music`, `lyrics`, `song` | `apollo` | `songwriting`, `music_production` |
| `health`, `medical`, `symptom` | `caduceus` | `medical_research`, `symptom_analysis` |
| `operations`, `cron`, `message routing` | `hermes` | `cron_management`, `kanban_operations` |
| `plan execution`, `dispatch`, `architecture` | `hephaestus` | `workflow_execution`, `architecture_design` |
| `code review`, `QA`, `audit` | `thoth` | `code_review` |

#### Lookup type 2: capability lookup

**Input:** `<god name>` (e.g., "hephaestus", "marvin")

**Method:** read `gods.yaml`, find the god, return their capabilities.

**Output:**

```yaml
lookup:
  type: capability
  god: <name>
  display_name: <Display Name>
  role: <their role>
  description: <their description>
  capabilities:
    - <capability 1>
    - <capability 2>
    - ...
  status: <active | inactive | draft>
```

#### Lookup type 3: availability lookup

**Input:** `<task>` (e.g., "implement a TypeScript file", "review code")

**Method:**

1. Run the domain lookup to get the matched god
2. Check the god's current kanban tasks (`hermes kanban list --assignee <god> --status running --json`)
3. Check the god's `max-runtime` settings
4. Return the god + their current load

**Output:**

```yaml
lookup:
  type: availability
  task: <input>
  matched_god: <name>
  current_load:
    running: <count>
    blocked: <count>
    ready: <count>
  recommendation: <assign | defer | escalate>
  rationale: <why>
```

**Recommendation logic:**

- `assign` — god is matched, current load is reasonable (< 5 running tasks)
- `defer` — god is matched, but current load is heavy (> 5 running). Defer the task or find an alternative.
- `escalate` — no god matches, or matched god is inactive, or load is critical. Escalate to the operator.

#### Lookup type 4: assignment lookup

**Input:** `<god name>`

**Method:**

1. Look up the god in the roster
2. Check the god's current kanban tasks (in flight)
3. Check the god's recent journal (in `Codex-God-<name>/journal/`)
4. Return a summary of what the god is currently doing

**Output:**

```yaml
lookup:
  type: assignment
  god: <name>
  display_name: <Display Name>
  role: <their role>
  current_tasks:
    - id: t_xxx
      title: <title>
      status: <status>
    - ...
  recent_journal:
    - date: <YYYY-MM-DD>
      summary: <what they did>
    - ...
  status: <active | inactive | draft>
```

#### Lookup type 5: full roster dump

**Input:** none (or a filter like `--status active`)

**Method:** read `gods.yaml`, return the full list.

**Output:**

```yaml
lookup:
  type: full_roster
  total_gods: <count>
  active: <count>
  inactive: <count>
  draft: <count>
  gods:
    - name: <name>
      display_name: <Display Name>
      role: <role>
      capabilities_count: <count>
      status: <active | inactive | draft>
    - ...
```

### Step 3: Return the result

The lookup result is returned to the calling skill. The calling skill uses the result to:

- **Domain lookup** — set the default assignee
- **Capability lookup** — verify the assignee can do the work
- **Availability lookup** — decide whether to assign, defer, or escalate
- **Assignment lookup** — understand the current state of a god
- **Full roster** — list the dispatch table

## Worked examples

### Example 1: "Who implements code?"

```yaml
lookup:
  type: domain
  domain: "implement a TypeScript file"
  matched_god: marvin
  rationale: "Marvin is the master coder, owns code_writing and test_writing capabilities"
  capability: code_writing
```

### Example 2: "What can Thoth do?"

```yaml
lookup:
  type: capability
  god: thoth
  display_name: Thoth
  role: "Researcher, Archivist, and QA Reviewer"
  description: "..."
  capabilities:
    - research
    - knowledge_synthesis
    - code_review
    - plan_co_authoring
    - athenaeum_curation
    - session_search
    - ichor_operations
    - convention_documentation
  status: active
```

### Example 3: "Is Hephaestus available?"

```yaml
lookup:
  type: availability
  task: "Dispatch the conductor-ui build"
  matched_god: hephaestus
  current_load:
    running: 0
    blocked: 5  # t3, t4, etc.
    ready: 0
  recommendation: assign
  rationale: "Hephaestus has 0 running tasks; the 5 blocked tasks are waiting on operator unblock, not on Hephaestus. He can dispatch a new chain."
```

### Example 4: "What is Marvin doing?"

```yaml
lookup:
  type: assignment
  god: marvin
  display_name: Marvin
  role: "Master Coder"
  current_tasks: []  # no in-flight tasks (the conductor-ui build hasn't dispatched yet)
  recent_journal:
    - date: 2026-06-16
      summary: "Conductor Step 4.9 Brief 3 closure (89/89 tests pass)"
  status: active
```

## Integration with the dispatcher

The `kanban-orchestrator` skill uses this skill to set the default assignee for each task. The flow:

1. Task created with no explicit assignee
2. Dispatcher calls `god-roster` with the task's title + body
3. `god-roster` returns the matched god (or escalation)
4. Dispatcher sets the assignee to the matched god
5. The matched god's worker claims the task

The dispatcher's keyword rules (in the Hephaestus rework) are a fast-path version of this skill. The skill is the deep-path; the keyword rules are the fast-path.

## When the roster changes

Roster changes are **operator-locked**. Konan (or a future operator role) signs off on:

- **New god added** — Hephaestus uses the `god-creation` skill, the operator signs off
- **God reworked** — Hephaestus authors the rework design, the operator signs off
- **God inactivated** — when a god is parked, `status` flips to `inactive`
- **Capability added/removed** — Hephaestus audits the profile, the operator signs off

Every change is logged in `pantheon/shared/decisions/` with the date, the god affected, the change, and the rationale. The roster is updated to match.

## Pitfalls

**Don't trust the keyword rules over this skill.** The keyword rules are fast-path. When the routing is unclear, run this skill.

**Don't assign to a god with `status: inactive`.** Inactive gods can't be claimed. Find an active alternative or escalate.

**Don't assign to a god with no matching capability.** Marvin can't do UI design. Iris can't do code. The capability check is the boundary.

**Don't assume a god is available just because they're active.** Run the availability check. A god with 10 running tasks can't take on more.

**Don't update the roster without operator sign-off.** The roster is operator-locked. Changes need a decision log entry.

## Verification gates

God-roster is "working" when:

- [ ] All 5 lookup types produce correct results
- [ ] The lookup reads from `gods.yaml` (the source of truth)
- [ ] The dispatcher uses the lookup for default-assignee routing
- [ ] The roster is in sync with `gods.yaml` and `Codex-Pantheon/design/god-roster.md`
- [ ] Changes are logged in the decisions file

## See also

- `pantheon/gods/gods.yaml` — the canonical roster (machine-readable)
- `Codex-Pantheon/design/god-roster.md` — the human-readable roster
- `Codex-Pantheon/design/standards/god-profile-shape.md` — what a god profile looks like
- `Codex-Pantheon/design/hephaestus-rework-workflow-god.md` — Hephaestus's role in maintaining the roster
- `pantheon/god-packages/shared-skills/god-creation/` — the god-creation skill
- `pantheon/god-packages/shared-skills/kanban-orchestrator/SKILL.md` — the dispatcher (uses this skill)
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — uses this skill at dispatch
