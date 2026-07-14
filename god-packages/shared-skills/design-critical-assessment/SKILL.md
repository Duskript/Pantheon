---
name: design-critical-assessment
description: "Use after a design spec is written, before any implementation begins. Runs a structured assessment of holes, risks, pros/cons, system conflicts, overhead, and a go/no-go verdict. Must be completed before build handoff."
version: 1.0.0
author: Thoth
license: MIT
metadata:
  hermes:
    tags: [design, assessment, risk, pre-flight, go-no-go]
    related_skills: [conductor-design-workflow, conductor-design-rule]
---

# Design Critical Assessment

## When to Use

After a design spec is complete but before any code is written. The purpose is not to block progress — it's to catch problems while they're cheap to fix.

## Process

Walk through each section with the designer. Be honest. If something is a vulnerability, say so.

### Step 1: Holes

What does the design NOT address?

- Are there edge cases the spec doesn't cover?
- Are there message types or event sources the user will eventually want that this design ignores?
- Are there failure modes with no defined behavior? ("What happens when X crashes?")
- Does the design assume something that isn't true yet? (e.g., "assumes NATS is running" when it isn't)

### Step 2: Risks

For each risk, assess:

| Risk | Likelihood (Low/Med/High) | Impact (Low/Med/High) | Mitigation |
|---|---|---|---|

- Single points of failure
- Latency or performance regressions
- Configuration drift over time
- Security boundaries crossed accidentally
- Escalation paths that silently drop
- Scaling ceilings (queue backs up, too many events)

### Step 3: System Conflicts

Does this design overlap with or break existing systems?

| Existing System | Nature of Overlap | Resolution |
|---|---|---|

Check against:
- Pantheon RULES.md (Constitution)
- Existing MCP servers and tools
- Other gods' capabilities and domains
- File paths and conventions in use
- Hermes Agent features (kanban, cron, skills, etc.)
- Ichor / Athenaeum / messaging
- NATS/Subspace (if applicable)

### Step 4: Overhead

What does this cost?

- **Cognitive overhead** — does it make the user's mental model more complex?
- **Runtime overhead** — CPU, RAM, latency, network traffic
- **Maintenance overhead** — how many files to keep in sync? YAML drift?
- **Config overhead** — how much setup before it works?
- **Debugging overhead** — when it breaks, is it easy to find out why?

### Step 5: Pros & Cons

Honest list. Not a sales pitch.

| Pro | Con |
|---|---|

If the cons section is longer than the pros section, that's not automatically a no — but it means the justification needs to be stronger.

### Step 6: Verdict

One of:
- **Go** — build as designed
- **Go with constraints** — build, but address specific items first (list them)
- **Go in phases** — build incrementally, ship Layer 1 before Layer 2
- **No-go** — don't build this. Here's why and what to do instead.

The verdict includes a summary statement addressed to the user: *"Here's what I think we should do and why."*

### Step 7: Record

Write the assessment to the spec as an appendix section, or to the Athenaeum as a companion document. The assessment should be findable when someone asks "why did we build this this way?"
