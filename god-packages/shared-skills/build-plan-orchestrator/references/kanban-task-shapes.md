# Kanban Task Shapes

> Canonical kanban task shapes for common workflow patterns. Each shape is the body of a `kanban_create` call.

---

## Shape 1: Ad-hoc single-task work

**Use when:** A one-off task that doesn't fit into a workflow. Research, review, draft a doc.

```python
kanban_create(
    title="<verb>: <object>",
    assignee="<god>",
    body="""
<task description>

## Output

Write your result as `kanban_complete(summary, metadata)`.
""",
    skills=["<skill_1>", "<skill_2>"],
)
```

**Example:** "research: best practices for ERPNext AGPL compliance"

---

## Shape 2: Sequenced pipeline (parent-child chain)

**Use when:** Step 2 needs step 1's output before it can start. This is the kanban version of Conductor's `input_from`.

```python
t1 = kanban_create(
    title="<step 1>",
    assignee="<god1>",
    body="...",
)
t2 = kanban_create(
    title="<step 2>",
    assignee="<god2>",
    body="""
Read the result from task {t1.id}:
{{t1.result.summary}}

## Your task
<step 2 description>
""",
    parents=[t1],
)
```

**Example:** "research → write spec"

---

## Shape 3: Fan-out (parallel)

**Use when:** N tasks all need to run in parallel. No merge — they all just complete independently.

```python
tasks = []
for assignee, body_modifier in [
    ("marvin", "TDD approach"),
    ("hephaestus", "architecture-first approach"),
    ("claude-code-cli", "novel feature approach"),
]:
    t = kanban_create(
        title=f"implement feature X ({assignee}'s take)",
        assignee=assignee,
        body=f"""
Implement feature X using {body_modifier}.

## Output
Write the implementation + tests. Mark complete with file paths.
""",
    )
    tasks.append(t)
```

**Example:** 4-agent coding workflow (one task per agent).

---

## Shape 4: Fan-out + fan-in (parallel + merge)

**Use when:** N parallel tasks, then one merge task that runs after all N complete.

```python
# Fan-out: N parallel tasks
branches = []
for assignee in assignees:
    t = kanban_create(
        title=f"<step> ({assignee})",
        assignee=assignee,
        body="...",
    )
    branches.append(t)

# Fan-in: one task gated on all branches
merge = kanban_create(
    title="merge: pick the best",
    assignee="<merge_owner>",
    body=f"""
Read the results from all N tasks: {[t.id for t in branches]}

## Your task
Compare all N outputs. Pick the best.

## Output
kanban_complete with metadata.best_pick and metadata.rationale.
""",
    parents=branches,  # Gates on ALL branches
)
```

**Example:** 4-agent coding with judge-picks-best.

---

## Shape 5: Approval-gated (block for human)

**Use when:** A task needs operator decision before continuing.

```python
# Phase 1: the work
work = kanban_create(
    title="<the work>",
    assignee="<god>",
    body="...",
)

# Phase 2: the operator decision
decision = kanban_create(
    title="<approve the work>",
    assignee="<god_or_human>",
    body=f"""
Read the result from task {work.id}.

## Your task
If approved, mark complete with metadata.decision=approved.
If rejected, mark complete with metadata.decision=rejected and metadata.feedback=<what to change>.
""",
    parents=[work],
)
```

**Example:** Auto-apply controversial changes (operator reviews before applying).

---

## Shape 6: Long-running (multi-day, with state)

**Use when:** A task that spans multiple days, accumulates state, and is checked into/out of.

```python
kanban_create(
    title="<long-running project>",
    assignee="<god>",
    body="""
<project description>

## State management
- Write intermediate state to: $HERMES_KANBAN_WORKSPACE/state.json
- On each session start, read the state and resume from where you left off
- Heartbeat every 30 min with progress

## Output
kanban_complete when the project is done.
""",
    workspace="dir:/home/konan/<project_dir>",  # Persistent workspace
    max_retries=10,  # Allow many retries across days
)
```

**Example:** A multi-day research project, a 2-week content calendar build.

---

## Shape 7: Recurring (cron-triggered)

**Use when:** The task should fire on a schedule, like a workflow.

```python
# Note: this is the same as a Conductor workflow with a cron trigger.
# Use Conductor if it's a multi-step pipeline.
# Use a recurring kanban task if it's a single-step recurring job.

kanban_create(
    title="<recurring task>",
    assignee="<god>",
    body="...",
    schedule="<cron expression>",  # The kanban supports this
)
```

**Example:** Daily data collection, weekly report generation.

---

## Anti-patterns

- **Don't create a kanban task for a 1-line change** — just do it directly
- **Don't use parents when you actually want fan-out** — parents=[] means "run after all parents complete" (fan-in), not "run in parallel with parents"
- **Don't put a workflow's body in a single kanban task** — that's what Conductor YAML is for. The kanban is for individual tasks within or alongside workflows
- **Don't have a task body that says "do everything"** — be specific about what the worker should do
