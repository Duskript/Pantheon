# Conductor YAML Templates

> Common Conductor YAML patterns that the build plan author can reference or adapt. Each template has: the canonical use case, the YAML shape, when to use it, and an example.

---

## Pattern 1: Single-god pipeline

**Use when:** A workflow that runs sequentially through 2-4 gods. Classic "research → architect → implement → review" pipeline.

**YAML shape:**
```yaml
workflow:
  id: <name>
  name: "<display name>"
  version: "1.0.0"

  steps:
    - id: step1
      god: thoth
      skill: <skill>
      input: <input>
      output: <output_name>
      timeout: <duration>
      gates: [<gate_list>]

    - id: step2
      god: hephaestus
      skill: <skill>
      input_from: step1
      output: <output_name>
      timeout: <duration>
      gates: [<gate_list>]

    # ... more sequential steps
```

**Example:** `bug-fix.yaml`, `deploy-feature.yaml`

---

## Pattern 2: Parallel fan-out + fan-in

**Use when:** Multiple agents working on the same task in parallel, then a judge picks the best.

**YAML shape:**
```yaml
steps:
  - id: parallel-impl
    type: parallel
    fail_mode: slow
    max_concurrency: N
    branches:
      - id: <branch1>
        type: cli_tool
        tool: <tool_name>
        input:
          prompt: "..."
          working_dir: "..."
          stream: true
        timeout: <duration>
      - id: <branch2>
        # ... more branches
    output: parallel-outputs

  - id: merge
    type: merge
    inputs: [<branch1>, <branch2>, ...]
    strategy: llm_pick_best
    strategy_config:
      judge_tool: <tool>
      judge_prompt_template: "..."
      timeout: 30m
    output: winning-impl
```

**Example:** `claude-x-codex-feature.yaml` (4 agents in tandem)

---

## Pattern 3: Scheduled (cron-triggered)

**Use when:** A workflow that fires on a schedule, not an event.

**YAML shape:**
```yaml
workflow:
  id: <name>
  schedule: cron("<expr>")  # e.g., "0 6 * * *" for daily at 6 AM

  steps:
    - id: <first_step>
      god: <god>
      # ... etc
```

**Example:** `morning-briefing.yaml`, `forge-overnight-research.yaml`

---

## Pattern 4: Event-triggered (NATS / webhook)

**Use when:** A workflow that fires when an external event arrives.

**YAML shape (uses a reaction rule, not a workflow trigger):**
```yaml
# In conductor/rules/<name>.yaml
rule:
  name: <rule_name>
  event_filter:
    event_type: <type>  # e.g., "nats.message", "webhook", "schedule.cron"
    # ... other filters
  action:
    type: start_workflow
    workflow_id: <workflow_id>
    context:
      # ... event-derived context
```

**Example:** Cross-Pantheon message handlers, webhook triggers.

---

## Pattern 5: Approval-gated (operator checkpoint in the middle)

**Use when:** A workflow that needs operator approval before continuing (e.g., a controversial config change).

**YAML shape (uses the morning-brief approval card pattern):**
```yaml
steps:
  - id: <work_step>
    # ... do the work

  - id: build-approval-card
    type: cli_tool
    tool: python
    input:
      prompt: |
        python -m <module>.build-approval-card \
          --output ~/.hermes/<system>/pending-approval/<date>.md
    output: approval-card-path

  - id: write-approval-card-path
    type: nats_publish
    subject: "subspace.konan.inbox"
    input_from: build-approval-card
    message: |
      approval-needed: ${approval-card-path}
      review_by: <time>
```

**Example:** `forge-overnight-research.yaml` (the controversial changes section)

---

## Pattern 6: Long-running with state (multi-day)

**Use when:** A workflow that spans multiple sessions, accumulates state, and is checked into/out of the kanban.

**YAML shape:** This is harder to express in pure Conductor YAML. The recommendation is:
- Use the kanban for the orchestration
- Each "phase" of the multi-day work is a kanban task
- The Conductor workflow runs INSIDE each kanban task (not the other way around)

**Example:** Not in the catalog yet. Add as needed.

---

## Pattern 7: Ad-hoc operator-triggered (one-off)

**Use when:** The operator wants to run a workflow on demand, not on a schedule or event.

**YAML shape:** Same as Pattern 1, but triggered by `trigger: manual` or a `kanban_create` with the workflow as the body.

**Example:** `bug-fix.yaml` (manual trigger via the kanban)

---

## Anti-patterns (don't do these)

- **Don't mix trigger types** — a workflow should be either scheduled OR event-triggered, not both. If you need both, create two workflows.
- **Don't put long-running state in workflow YAML** — workflows should be deterministic and restartable. State lives in the database (ERPNext, the kanban DB, etc.).
- **Don't have steps that depend on previous-run outputs** — if step 5 needs step 3's output from yesterday's run, that's wrong. Use the kanban to pass state across days, not the workflow.
- **Don't write a workflow for a 1-line change** — use the kanban or a direct session.
