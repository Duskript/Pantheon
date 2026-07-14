---
name: workflow-tier-routing
description: "Use when classifying a build request into the right workflow tools and patterns. This is the 'which layer should this be in?' decision — Conductor YAML, kanban task, direct session, CLI tool, soulforge, or a combination. Returns a structured recommendation that the build-plan-orchestrator can consume."
version: 0.1.0
tags: [routing, classification, build-plan, decision]
---

# Workflow Tier Routing — The Routing Rules

This skill decides **which workflow tool(s) a build request should use**. It's the first step in the `build-plan-orchestrator` chain. The output is a structured recommendation: which tools, which pattern, which catalog search terms, which specialists.

> **Status:** v0.1 stub. The routing rules below are a starting point — they'll be refined as we run the orchestrator on real builds. If you have a build that doesn't fit these rules, document the gap.

## When to use this skill

Load this skill when:
- The `build-plan-orchestrator` step 1 task asks you to tier-route a build request
- Someone asks "what's the right way to build X?" and you need a structured recommendation
- You're writing a new Conductor workflow and want to know if it should be a workflow at all

## The routing decision tree

Work through this in order. The first match wins (mostly).

### Q1: Is this a 1-line change, a config tweak, or a one-off question?

If yes, the answer is **direct session** — don't use the kanban, don't write a Conductor YAML, just do it.

Examples: "add a button to the dashboard", "fix this typo", "what does X do?"

### Q2: Is this a pre-authored, versioned, file-based workflow that will be re-run?

If yes, the answer is **Conductor YAML**.

Indicators:
- The workflow has a clear trigger (schedule, event, manual)
- It runs the same way every time
- The user wants to be able to version it, share it, edit it in the workflow editor
- It's a multi-step pipeline (research → architect → implement → review)

Examples: `morning-briefing.yaml`, `deploy-feature.yaml`, `bug-fix.yaml`, `forge-overnight-research.yaml`

### Q3: Is this a multi-agent workflow that needs fan-out or merge?

If yes, the answer is **Conductor YAML with kanban tasks for the per-branch work**.

Indicators:
- Multiple agents need to work in parallel
- A judge needs to compare outputs and pick the best
- The work needs live observability (the WebSocket pattern)
- It's a one-time or rare workflow (not a daily recurring thing)

Examples: `claude-x-codex-feature.yaml` (4 agents in tandem), one-off research projects

### Q4: Is this an ad-hoc, single-purpose task that doesn't fit a pre-authored workflow?

If yes, the answer is **kanban task**.

Indicators:
- It's a one-off (research this, review that, ship this PR)
- The work doesn't need to be a versioned, file-based artifact
- The operator wants the kanban dashboard to see it
- The work might be blocked by a human decision

Examples: "research the best X library", "review PR #42", "fix this bug in the staging env"

### Q5: Does the work need long-running state across multiple days?

If yes, the answer is **kanban task with `workspace: dir:<path>` and heartbeat**.

Indicators:
- The work spans multiple sessions
- Intermediate state needs to persist
- The task can be paused and resumed
- Progress is slow enough that you want heartbeats

Examples: A 2-week content calendar build, a multi-day research project

### Q6: Does the work need to fire on a recurring schedule?

If yes, the answer is **Conductor YAML with a cron trigger** (preferred) or a recurring kanban task (simpler).

Indicators:
- The work fires at the same time every day/week/month
- The output is the same shape every time
- The user wants it to "just work" without manual intervention

Examples: `morning-briefing.yaml` (daily), `forge-overnight-research.yaml` (nightly)

### Q7: Does the work fire on an external event (NATS message, webhook, file change)?

If yes, the answer is **Conductor YAML with a reaction rule**.

Indicators:
- The trigger is an event, not a time
- The user wants the response to be automatic when the event fires
- The event is structured (not a human typing)

Examples: Cross-Pantheon message handlers, webhook triggers, file watchers

### Q8: Does the work need operator approval before continuing (mid-workflow)?

If yes, the answer is **Conductor YAML with the approval-card pattern** (see `references/conductor-yaml-templates.md`).

Indicators:
- Some steps are safe to auto-apply, others need review
- The operator wants to be in the loop without blocking the work
- The approval should be a daily-touchpoint (morning brief)

Examples: `forge-overnight-research.yaml` (controversial changes)

## The output schema

Whatever the routing decision, the output is structured metadata:

```python
kanban_complete(
    summary="<1-2 sentence recommendation>",
    metadata={
        "tools_to_use": ["conductor_yaml", "kanban_task", ...],
        "pattern": "pipeline" | "fan_out" | "fan_in" | "fan_out_fan_in" | "approval_gated" | "scheduled" | "event_triggered" | "long_running" | "ad_hoc" | "one_shot",
        "catalog_search_terms": ["keyword1", "keyword2", ...],
        "estimated_complexity": "low" | "medium" | "high",
        "complexity_rationale": "...",
        "specialists": ["marvin", "iris", "thoth", ...],
        "rationale": "2-3 sentences explaining the recommendation",
    },
)
```

## Anti-patterns in routing

- **Don't route everything to Conductor.** Conductor is for file-based, versioned, multi-step workflows. Most ad-hoc work is a kanban task.
- **Don't route everything to the kanban.** The kanban is for ad-hoc, runtime-created tasks. Pre-authored pipelines belong in Conductor YAML.
- **Don't route a 1-line change to anything.** Just do it.
- **Don't recommend parallel agents when the work is sequential.** If 4 agents all do the same thing sequentially, it's not a fan-out, it's a queue.
- **Don't recommend approval gates if the work is fully deterministic.** If the steps are well-defined and the outputs are structured, no approval is needed.

## Open questions (to be refined as the catalog grows)

- Q1: Should "fan-out + merge" be a separate pattern from "fan-out"? Or is "fan-out" always followed by a merge?
- Q2: When is a direct session better than a kanban task? (Both can do ad-hoc work, but the kanban gives you audit trail + dashboard visibility)
- Q3: How do we route "this is a research project" vs "this is an implementation project"? Both can be kanban tasks but the specialists differ.

These get answered as we run the orchestrator on real builds and see what the routing rules miss.
