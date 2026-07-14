# Example Chains — Past Build-Plan-Orchestrator Runs

> Full examples of past `build-plan-orchestrator` runs, showing the chain structure, operator checkpoints, and the final dispatch. Use these as reference when running the skill.

---

## Example 1: The 4-Agent Coding Workflow (Conductor CLI Orchestration)

**Date:** 2026-06-16
**Project:** conductor-parallel-work
**Operator:** Konan

### Trigger

> "We need the conductor to be able to run Marvin, Hephaestus, Claude Code, and Codex CLI in tandem on the same feature. Build a build plan for that."

### Chain

```
[t1] tier-route: 2026-06-16 10:30
  Assigned: thoth
  Result: tools=[conductor_yaml, kanban_task, cli_tool], pattern=fan_out_fan_in,
          complexity=high, specialists=[marvin, iris, hephaestus, thoth]
  → Block: "Recommendation: Conductor YAML with parallel/merge step types +
            kanban tasks for the per-step work. Does that match?"
  → Operator: "yes"

[t2] catalog lookup: 2026-06-16 10:45
  Assigned: thoth
  Result: matches=[
    {workflow_id: "claude-x-codex-feature.yaml", similarity: 0.85},
    {workflow_id: "morning-briefing.yaml", similarity: 0.62},
    {workflow_id: "forge-overnight-research.yaml", similarity: 0.55}
  ], best_match="claude-x-codex-feature.yaml"
  → Block: "Best match is claude-x-codex-feature. Clone, scratch, or extend?"
  → Operator: "clone and modify — extend the 2-agent pattern to 4 agents"

[t3] build plan: 2026-06-16 11:00
  Assigned: hermes
  Output: ~/pantheon/plans/conductor-parallel-build-plan.md (26KB, 510 lines)
  Result: 3 workstreams (A: CLI orchestration, B: Forge autoresearch, C: Conductor GUI),
          5 weeks, 15 open questions, 1 open decision (auto-apply approach)
  → Block: "Plan is at <path>. Read it. Approved?"
  → Operator: "approved, but the Forge autoresearch Q2 needs to use the morning brief,
               not a CLI flag"

[t3 rev]: 2026-06-16 11:15
  Operator: re-run with feedback
  Updated plan adds §4.1 (morning-brief integration for the Forge approval card)
  → Block: "Updated plan. Approved?"
  → Operator: "approved"

[t5] dispatch: 2026-06-16 11:20
  Assigned: hermes
  Result: 12 tasks created (4 in Stream A, 5 in Stream B, 3 in Stream C).
          Marvin has 7, Iris has 3, Thoth has 2.
          First task: T-1234 (A.1: cli_tool step type)
          Expected timeline: 5 weeks
  → No block (fire and forget)
  → Skill reports summary to operator
```

### What the operator saw in their Telegram

```
[Thoth]: Build plan conversion started for "conductor-parallel-work".
         I'm routing it through 5 checkpoints.

[Step 1 done] Recommendation: Conductor YAML + kanban tasks for per-step work.
              Pattern: fan-out + fan-in. Complexity: high.
              Specialists: Marvin, Iris, Thoth, Hephaestus.
              Does that match your intent? (yes/modify/different)

[You]: yes

[Step 2 done] Best match is claude-x-codex-feature.yaml. 
              Clone, scratch, or extend?

[You]: clone and modify

[Step 3 done] Build plan at ~/pantheon/plans/conductor-parallel-build-plan.md
              3 workstreams, 5 weeks, 15 open questions.
              Read it. Approved? (approved/change)

[You]: approved, but Forge Q2 needs the morning brief

[Step 3 rev] Updated. Added §4.1 (morning-brief approval card). Approved?

[You]: approved

[Step 5 done] Dispatched. 12 tasks. Marvin has 7, Iris has 3, Thoth has 2.
              First task T-1234 (A.1: cli_tool) starts now.
              Expected timeline: 5 weeks. 
              You'll get pings as tasks complete.
```

### Outcome

The 12 tasks ran over the next 5 weeks. The 4-agent coding workflow worked end-to-end. The Forge autoresearch runs nightly. The morning brief includes the approval card.

---

## Example 2: Mercer Outreach Sequence (planned, not yet run)

**Date:** 2026-06-16
**Project:** mercer-outreach
**Operator:** Konan (planned)

### Trigger

> "I want to build a Mercer outreach sequence that sends a LinkedIn
>  message, waits 2 days, sends a follow-up email, waits 3 days, then
>  creates a task for a phone call. Stop if the prospect replies."

### Expected chain

```
[t1] tier-route: tools=[conductor_yaml, kanban_task], pattern=approval_gated + scheduled,
                  complexity=medium, specialists=[mercer, thoth]
  → Block: "Recommendation?"
  → Operator: "yes"

[t2] catalog lookup: matches=[morning-briefing.yaml, forge-overnight-research.yaml]
                    best_match="morning-briefing.yaml"
  → Block: "Best match?"
  → Operator: "scratch — different enough"

[t3] build plan: phases=[linkedin_send, wait, followup_email, wait, phone_task_setup, stop_on_reply]
                6 tasks over 2 weeks
  → Block: "Approved?"
  → Operator: "approved, use LinkedIn API v2 not v1"

[t3 rev]: updated to use LinkedIn API v2
  → Operator: "approved"

[t5] dispatch: 6 tasks. Mercer has 4, Thoth has 2.
```

### Notes

- This is the canonical example for "user-in-the-loop skill chain"
- The 6 tasks fan out to kanban; the conductor workflow handles the multi-touch sequence
- The "stop if the prospect replies" is a `condition` step in the Conductor workflow, not a separate task

---

## Pattern: What makes a "good" chain run

The above examples are "good" because:
- The operator saw every checkpoint and made every decision
- The chain adapted to operator feedback (Q2 redesign, LinkedIn API v2)
- The final dispatch was exactly what the operator wanted
- The audit trail (in the kanban) shows the full decision history

## Pattern: What makes a "bad" chain run

A bad chain looks like:
- The operator says "yes" to everything without reading
- The skill skips a step to "save time"
- The dispatch fires before the operator saw the plan
- The metadata is unstructured so downstream tasks can't read it

If you see these patterns, stop the chain and restart from the last good checkpoint.
