---
name: conductor-design-workflow
description: "Use when the user says 'set up a pipeline', 'create a workflow', 'I need a multi-god process', or any request to chain multiple gods into a repeatable sequence. Produces a Conductor workflow YAML and saves it to ~/pantheon/conductor/workflows/."
version: 1.0.0
author: Thoth & Hermes (Pantheon)
license: MIT
metadata:
  hermes:
    tags: [conductor, workflow, design, pipeline, multi-god]
    related_skills: [conductor-design-rule, conductor-design-webhook, conductor-design-report]
---

# Conductor Workflow Designer

## When to Use

Load this skill when the user wants to define a repeatable multi-god process. Keywords: "pipeline," "workflow," "chain," "sequence," "when I do X, do Y then Z."

## Process

### Step 1: Clarify Intent

Ask the user to describe the workflow in plain language. Guide with these questions:

- **What triggers this workflow?** (user command, handoff from a god, cron schedule, external event)
- **What are the steps?** List each god action in order.
- **What context needs to flow between steps?** (artifacts, decisions, summary)
- **Where do RALPH gates go?** Between which steps should we validate before continuing?
- **What happens if a step fails?** Loop back? Escalate? Abort?
- **Is there a notification step at the end?** Hermes summary? NATS publish to Tallon?

### Step 2: Map to YAML Structure

Translate the conversation into a Conductor workflow definition. Template:

```yaml
workflow:
  id: ""                    # kebab-case id, generated from name
  name: ""                  # Human-readable name
  version: "1.0.0"
  description: ""

  triggers:
    - type: command          # command | handoff | schedule | webhook
      pattern: ""            # e.g. "deploy feature *"

  context:
    required: []
    optional: []

  steps:
    - id: step_1
      god: ""                # which god
      skill: ""              # what skill to use (optional)
      action: ""             # what action (optional)
      input: ""              # user_request | from_previous_step | file
      gates: []              # which RALPH gates at this step boundary
      timeout: 30m           # max time before escalation
      output: ""             # label for this step's output

    # More steps as needed...
    # RALPH loops use:
    #   loop:
    #     max_retries: 3
    #     on_fail: back_to_{previous_step_id}
    #     gate: logic_gate
```

### Step 3: Fill From Conversation

Map the user's answers to the template fields. Ask about anything missing — don't guess defaults for routing decisions.

### Step 4: Validate

Before writing the file, check:

- [ ] Every `god` value matches a registered Pantheon god
- [ ] `id` is kebab-case, unique among existing workflows
- [ ] All `input_from` references point to existing step IDs
- [ ] RALPH loop `on_fail` targets exist
- [ ] Required context fields are listed
- [ ] Every step has a `timeout`

### Step 5: Write

Save to `~/pantheon/conductor/workflows/{workflow_id}.yaml`

Then confirm to the user:
- Workflow name and summary
- Number of steps, which gods are involved
- Where gates and RALPH loops are placed
- How to trigger it

### Step 6: Offer Next Steps

Ask if they want to:
- Create a reaction rule to trigger this workflow automatically
- Test the workflow now
- Add it to a higher-level super-skill
