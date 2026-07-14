# External Workflow Patterns — Reference from archon, n8n, Zapier

> Notes on workflow patterns borrowed from other systems. Use as reference when designing new Pantheon workflows or expanding the catalog.

---

## From Archon (github.com/coleam00/archon)

Archon is a YAML workflow engine for AI agents, conceptually similar to Conductor. Patterns we can borrow:

### Multi-agent inline nodes (archon's `agents:` block)

**Archon pattern:** A single node can specify multiple `agents:` that all run in parallel on the same task. Their outputs are aggregated.

```yaml
- id: multi
  prompt: "..."
  agents:
    first-agent:
      description: "..."
      prompt: "..."
    second-agent:
      description: "..."
      prompt: "..."
```

**Pantheon equivalent:** Conductor's `parallel` step type with multiple branches. Each branch is its own step (can be `cli_tool` for direct invocation or `god_dispatch` for session-based).

**What we learned:** Archon treats multi-agent as a property of a single node. We treat it as a separate step type. The trade-off: Archon's approach is more compact YAML; ours is more explicit and observable in the workflow editor.

**Catalog implication:** When the catalog has "4-agent coding workflow," the entry should note "archon would do this as one node with 4 agents; we do it as 4 branches in a parallel step."

### DAG with explicit `depends_on:`

**Archon pattern:** Each node has `depends_on: [other_node_ids]`. The engine runs nodes whose dependencies are satisfied.

**Pantheon equivalent:** Conductor's `input_from:` and the kanban's `parents=[...]`.

**What we learned:** Same pattern, different name. Our `input_from:` is more explicit (one upstream) but `parents=[a, b, c]` for fan-in is cleaner than archon's `depends_on: [a, b, c]` (which has the same effect).

### Per-node model and timeout

**Archon pattern:** Each node has `model:` and `timeout:`. Different agents in the same workflow can use different models.

**Pantheon equivalent:** Conductor's per-step `tool:` and `timeout:` (for `cli_tool` steps). For god dispatches, the model is part of the god's profile config, not the step config.

**What we learned:** For mixed-model workflows (e.g., Claude Code for code, Codex for boilerplate, Hermes for summary), per-step model selection is essential. Our current `cli_tool` design supports this via the `tool:` field.

### `when:` conditions

**Archon pattern:** Each node can have `when: <condition>` that gates whether it runs.

**Pantheon equivalent:** Conductor's `if_else` step type (control flow).

**What we learned:** Conditional execution is a first-class concept. Our `if_else` is more explicit but more verbose. Could be simplified in v2.

---

## From n8n (n8n.io)

n8n is a node-based workflow automation tool with thousands of community templates. Patterns worth borrowing:

### Trigger nodes (vs. workflows)

**n8n pattern:** A "trigger" node (e.g., webhook, schedule, email received) starts a workflow. The workflow is a sequence of actions that follow the trigger.

**Pantheon equivalent:** Conductor's reaction rules (event_type: nats.message, webhook, schedule.cron) + workflow YAML.

**What we learned:** Our reaction rule + workflow split is more explicit than n8n's trigger-in-the-workflow. The advantage: our triggers are reusable across workflows (one rule can fire multiple workflows). The disadvantage: more files to manage.

### Expression syntax for data passing

**n8n pattern:** `{{ $json.field }}` or `{{ $node["step_name"].json.field }}` for data passing between nodes.

**Pantheon equivalent:** Conductor's `input_from: step_name` (which exposes the step's output) + template variables in messages (e.g., `"Composite: ${baseline-snapshot.composite} → ${best-experiment.composite}"`).

**What we learned:** Our template syntax is more limited. n8n lets you do complex transformations inline. We rely on the LLM or a dedicated step for transformations. v2 could add a templating layer.

### Error handling per node

**n8n pattern:** Each node has retry settings, continue-on-fail, error trigger workflow.

**Pantheon equivalent:** Conductor's `on_error.retry` and `on_final_failure: escalate_hermes`.

**What we learned:** Per-node error handling is critical. Our implementation is on the right track. Could add "continue-on-fail" semantics for fan-out (one branch fails, others continue) — partially supported via `fail_mode: slow` and `fail_mode: ignore`.

---

## From Zapier (zapier.com)

Zapier is the consumer-facing workflow tool. Patterns:

### "Zaps" vs. "workflows" naming

**Zapier pattern:** A "Zap" is a single trigger + action sequence. "Workflows" are multi-step Zaps.

**Pantheon equivalent:** Conductor "workflows" (multi-step) + kanban "tasks" (single-step).

**What we learned:** Naming is hard. We have "workflows" in Conductor and "tasks" in the kanban. Zapier has "Zaps" and "workflows." The semantic split is similar: trigger+action vs. multi-step pipeline.

### "Paths" for branching

**Zapier pattern:** A "Path" is a conditional branch (if A, do X; if B, do Y).

**Pantheon equivalent:** Conductor's `if_else` step type.

**What we learned:** Same as archon's `when:` — conditional execution is a must-have. Our `if_else` is more explicit.

---

## What this tells us about the catalog

The catalog entries should reference which external pattern the workflow is based on. Example:

```markdown
---
workflow_id: claude-x-codex-feature
title: "Feature Implementation — 4 Agents in Tandem"
type: conductor_yaml
pattern: fan_out_fan_in
related_patterns:
  - archon: "multi-agent inline nodes"
  - n8n: "fan-out with merge"
---

# 4-Agent Coding Workflow

**External references:** 
- Archon's `agents:` block (we do it more explicitly with `parallel` step type)
- n8n's "fan-out with merge" pattern

**Why we don't just use archon:** Archon is a separate runtime. Conductor is the Pantheon-native workflow engine. Replicating the pattern is more work than just running archon, but the integration with our existing kanban, Ichor, and god infrastructure is worth it.
```

---

## Patterns we're NOT borrowing (and why)

- **Zapier's app integration library** (6,000+ apps) — Composio already gives us this for the apps we need
- **n8n's visual node editor** — we're building our own (Iris's mock). Borrowing the visual is fine; borrowing the runtime isn't.
- **Archon's per-step model override** — we have this via `tool:` in `cli_tool` steps. Same effect, different mechanism.

---

## Open questions

- Q1: Should the catalog entries include a "see also" link to the external pattern? (Pro: discoverability. Con: maintenance burden.)
- Q2: Should we expose archon workflows as a Conductor-compatible import format? (Pro: reuse community patterns. Con: archon YAML != Conductor YAML, conversion is non-trivial.)
- Q3: When n8n has a great pattern for X but Conductor doesn't, do we (a) add X to Conductor, (b) document the gap, or (c) ignore it?
