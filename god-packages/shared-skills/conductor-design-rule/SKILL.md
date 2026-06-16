---
name: conductor-design-rule
description: "Use when the user says 'when X happens, do Y', 'set up a rule for', 'react to', or any request to define an event-driven trigger. Produces a Conductor reaction rule YAML and saves it to ~/pantheon/conductor/rules/."
version: 1.0.0
author: Thoth & Hermes (Pantheon)
license: MIT
metadata:
  hermes:
    tags: [conductor, rule, reaction, trigger, event]
    related_skills: [conductor-design-workflow, conductor-design-webhook, conductor-design-report]
---

# Conductor Rule Designer

## When to Use

Load this skill when the user wants to define what happens when a specific event occurs. Keywords: "when X, do Y," "react to," "trigger," "on [event]," "set up a rule for."

## Process

### Step 1: Identify the Event Source

Ask:
- **Where does this event come from?** (internal handoff, NATS message, webhook, cron schedule)
- **What is the specific trigger?** (god completes a step, Tallon sends a message, Stripe payment, GitHub PR, time of day)
- **Is this source internal or external to our Pantheon?**

### Step 2: Determine Handling Mode

If the source is external, walk through the handling modes:

| Mode | When to Use |
|---|---|
| `log_only` | Monitoring, no action needed. Check later on demand. |
| `notify` | FYI only. "Here's what happened." No execution. |
| `notify_and_log` | Routine notification, explicitly marked no-action-needed. |
| `approval_required` | **Default for unknown sources.** Actionable but needs a human nod first. |
| `route_on_approval` | Known message type, predictable routing, but still needs approval before executing. |

If internal, gates are the primary guard — but still confirm whether the user wants auto-execution or a confirmation step.

### Step 3: Define the Action

What should happen when the rule matches?
- Dispatch a workflow → which one?
- Dispatch to a specific god → which god, which skill/action?
- Log only → to which journal?
- Notify → via Hermes, or directly to Konan?

### Step 4: Map to YAML

```yaml
# rules/{name}.yaml
rules:
  - id: ""                   # kebab-case id
    when:
      event_type: ""         # handoff.completed | nats.message | webhook | schedule.cron
      source: ""             # which god, which pantheon, which service
      subject: ""            # NATS subject, webhook path, schedule expression
    then:
      handling_mode: ""      # log_only | notify | notify_and_log | approval_required | route_on_approval
      action: ""             # what to do
      # For approval_required / route_on_approval:
      on_approval:
        dispatch_workflow: ""    # optional
        dispatch_god: ""         # optional
        skill: ""                # optional
        context_policy: forward_all
```

### Step 5: Validate

- [ ] Source type matches the event taxonomy (handoff / nats / webhook / cron)
- [ ] Handling mode is appropriate for the source (external sources never default to auto-execute)
- [ ] Target workflow or god exists
- [ ] `id` is kebab-case, unique among existing rules
- [ ] For cron rules: expression is valid

### Step 6: Write

Save to `~/pantheon/conductor/rules/{rule_id}.yaml`

### Step 7: Confirm

Summarize what was set up:
- Trigger source and event
- Handling mode
- Action on match
- What happens if the source is unknown
