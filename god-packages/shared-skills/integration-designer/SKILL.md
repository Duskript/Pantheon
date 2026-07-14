---
name: integration-designer
description: "Use when Hephaestus is designing how a new subsystem connects to existing ones, when a new integration point is being defined, or when the seam between two subsystems needs a contract. Outputs the integration contract, the data flow diagram, and the seam locations."
version: 1.0.0
tags: [architecture, integration, design, seams, hephaestus, subsystems]
---

# Integration Designer — Subsystem Connections

> **The skill that designs how a new subsystem connects to existing ones.** When Marvin's building a new module, Hephaestus uses this skill to design the seams, the data flow, the integration contract. The output is the architecture blueprint that Marvin implements.

## When to use this skill

Load this skill whenever:

- A new subsystem is being added to the system
- A new integration point is being defined (e.g., a new API endpoint, a new NATS subject, a new Conductor action)
- Two existing subsystems need a new contract (e.g., a new method on a Client interface)
- The architecture needs to be reviewed for coupling, cohesion, or seam quality
- A subsystem is being refactored and the seams need to be redrawn
- The operator asks "how does X connect to Y?"

**Don't use this skill for:**

- Implementing the integration (that's Marvin's job)
- Reviewing an existing integration (use `design-review` skill, with this skill's output as the contract)
- Listing existing integrations (just read `Codex-Pantheon/design/integration-map.md`)

## How to use it (the procedure)

### Step 0: Load the context

Before designing, load the relevant canon:

1. **`Codex-Pantheon/design/integration-map.md`** — the topology, what's connected to what
2. **`Codex-Pantheon/design/subsystem-seams.md`** — the existing seams, the contracts
3. **`Codex-Pantheon/design/standards/subsystem-shape.md`** — the 6-component shape
4. **The new subsystem's purpose** — what it's for, who uses it, what it does

The context is the foundation. The design is grounded in the existing system.

### Step 1: Identify the integration points

For the new subsystem, identify every place it touches the existing system:

| Integration type | Question | Example |
|---|---|---|
| **API call** | What HTTP/RPC endpoints does it call? | `GET /api/workflows` |
| **Event publish** | What NATS subjects does it publish to? | `kanban.task.created` |
| **Event subscribe** | What NATS subjects does it subscribe to? | `conductor.workflow.completed` |
| **Database** | What tables/files does it read or write? | `kanban.db.tasks` |
| **MCP** | What MCP tools does it use? | `ichor_store`, `athenaeum_write` |
| **Skill load** | What skills does it require? | `build-plan-orchestrator` |
| **Conductor workflow** | What Conductor YAMLs does it call? | `morning-briefing` |
| **God profile** | What god profiles does it spawn? | `marvin`, `thoth` |
| **Filesystem** | What paths does it read or write? | `/home/konan/projects/<project>/` |

For each integration point, document the **direction** (in/out/bidirectional), the **payload** (what data flows), and the **frequency** (how often).

### Step 2: Design the contract

For each integration point, design the **contract** — the stable interface that the integration point exposes.

**Contract types:**

1. **API contract** — endpoint, method, request shape, response shape, error codes
2. **Event contract** — subject, payload shape, when published, who subscribes
3. **Method contract** — function signature, parameter types, return type, exceptions
4. **Schema contract** — table/file structure, fields, types, indexes
5. **Workflow contract** — workflow name, inputs, outputs, side effects

**Per the subsystem-shape standard:** every new subsystem has an interface module. The interface module is the **canonical contract** for the subsystem.

**Output of Step 2:** a list of contracts, one per integration point.

### Step 3: Define the seam location

The seam is **where the contract is enforced**. There are three seam locations:

1. **Caller-side seam** — the caller validates the contract (the caller has the responsibility)
2. **Callee-side seam** — the callee validates the contract (the callee has the responsibility)
3. **Shared seam** — both sides validate (defensive programming, more code, more safety)

**Per the subsystem-shape standard:** the seam is in the **callee** (the subsystem's interface module). The callee exposes the `Client` interface, and the caller calls `Client.method()` without re-validating.

**Output of Step 3:** for each integration point, the seam location.

### Step 4: Design the data flow

The data flow shows how data moves through the new subsystem and into/out of the existing system.

**Draw the data flow as a text-based diagram:**

```
[Caller] --request--> [New Subsystem Interface (Client)]
                              ↓
                       [LocalStub impl]
                              ↓
                       [Storage / External]
                              ↓
                       [LocalStub impl]
                              ↓
[Caller] <--response-- [New Subsystem Interface (Client)]

[New Subsystem] --event--> [NATS subject]
[Other Subsystem] --event--> [NATS subject]
                              ↓
                       [New Subsystem subscribes]
```

**Per integration point:** who sends, who receives, what data, when, what triggers.

**Output of Step 4:** the data flow diagram.

### Step 5: Identify the failure modes

For each integration point, identify:

- **What can fail?** (network error, validation error, auth error, missing data, etc.)
- **How does the new subsystem handle the failure?** (retry, fallback, halt, notify)
- **Who gets notified?** (the operator, the calling god, the user)
- **Is the failure recoverable?** (yes if the cause is transient; no if the data is corrupted)

**Per the sovereignty rule:** external events that trigger side effects require operator approval. The integration must check operator approval before executing.

**Per the operator-as-mind rule:** the operator decides on the failure handling for high-stakes integrations. The integration designer surfaces the decision, the operator decides.

**Output of Step 5:** a failure modes table.

### Step 6: Write the integration contract document

The output of this skill is a **structured integration contract document**:

```markdown
# Integration Contract: <Subsystem Name>

## Purpose
<what the subsystem is for, why it exists>

## Integration Points

| Point | Direction | Payload | Frequency | Seam | Contract |
|---|---|---|---|---|---|
| <point 1> | in/out/bidir | <data> | <freq> | caller/callee/shared | <contract type> |
| <point 2> | ... | | | | |

## Data Flow Diagram

<text-based diagram>

## Contracts

### <Contract 1>
- Type: API | Event | Method | Schema | Workflow
- Endpoint/Subject/Method/Table/Workflow: <location>
- Request shape: <shape>
- Response shape: <shape>
- Error codes: <list>
- Authentication: <how>

### <Contract 2>
- ...

## Failure Modes

| Mode | Cause | Handling | Notification | Recoverable |
|---|---|---|---|---|
| <mode 1> | <cause> | <handling> | <who> | yes/no |
| ... | | | | |

## Migration Plan
<if the integration replaces or extends an existing one>

## Verification

- [ ] Contracts documented and reviewed
- [ ] Failure modes identified
- [ ] Data flow diagrammed
- [ ] Seam locations decided
- [ ] Migration plan written (if applicable)
- [ ] Operator sign-off (if high-stakes)
```

### Step 7: Update the integration map and subsystem seams

After the contract is written:

1. **Update `Codex-Pantheon/design/integration-map.md`** — add the new subsystem to the topology
2. **Update `Codex-Pantheon/design/subsystem-seams.md`** — add the new subsystem's seam entry
3. **Log a decision** — write to `pantheon/shared/decisions/` for the integration design

## Worked example

### Example: The Ledger client (from the conductor-ui build)

**Subsystem:** Ledger client (the new subsystem for the conductor-ui build)

**Integration points:**

| Point | Direction | Payload | Frequency | Seam | Contract |
|---|---|---|---|---|---|
| `Client.listWorkflows` | in | filter | on demand | callee | Method |
| `Client.createWorkflow` | in | workflow spec | on dispatch | callee | Method |
| `Client.appendAudit` | in | audit event | on every action | callee | Method |
| `kanban.task.created` event | in | task payload | on every task | shared | Event |
| `conductor.workflow.completed` event | in | run payload | on workflow done | shared | Event |

**Data flow:**

```
[Conductor UI] --call--> [ledger_client.Client.method]
                              ↓
                       [LocalStub: JSON file]
                              ↓
                       [JSON file on disk]
                              ↓
[Adapter: LedgerAdapter (REST)] --HTTP--> [real Ledger server (when it ships)]
```

**Failure modes:**

| Mode | Cause | Handling | Notification | Recoverable |
|---|---|---|---|---|
| Network error | Ledger is down | retry with exponential backoff (3 attempts) | Hephaestus + operator | yes |
| Auth error | invalid API key | halt, surface to operator | operator | no (until key is fixed) |
| Validation error | malformed data | reject, log to audit, surface to caller | caller (Marvin) | no (data is wrong) |
| File corruption | disk error | halt, surface to operator, manual recovery | operator | no (until disk is fixed) |
| Sovereignty: external event without approval | NATS message arrives | notify operator, ask handle-now-or-later | operator | n/a |

**Migration plan:** the LocalStub is the v1 impl. The Adapter is a stub (never instantiated). When real Ledger ships, swap the LocalStub for the Adapter. The seam is the `Client` interface.

**Verification:** the adapter-swap test proves the seam holds (swap LocalStub for Adapter, all code paths still work).

## Pitfalls

**Don't design without the context.** Read the integration map, the subsystem seams, the existing patterns. The new integration should fit the system.

**Don't skip the failure modes.** Every integration has failure modes. Document them.

**Don't ignore the sovereignty rule.** External events must check operator approval. This is operator-locked.

**Don't couple without a contract.** Two subsystems that call each other without a contract are tightly coupled. The contract is the seam.

**Don't migrate without a plan.** Replacing or extending an existing integration needs a migration plan.

**Don't forget the verification.** Every integration contract needs verification (tests, adapter-swap, etc.).

## Verification gates

Integration-designer is "working" when:

- [ ] The integration context is loaded (the map, the seams, the standards)
- [ ] All integration points are identified
- [ ] Contracts are written for each point
- [ ] Seam locations are decided
- [ ] Data flow is diagrammed
- [ ] Failure modes are documented
- [ ] The integration contract document is produced
- [ ] The integration map and subsystem seams are updated
- [ ] A decision log entry is written

## See also

- `Codex-Pantheon/design/integration-map.md` — the topology
- `Codex-Pantheon/design/subsystem-seams.md` — the existing seams
- `Codex-Pantheon/design/standards/subsystem-shape.md` — the 6-component shape
- `Codex-Pantheon/design/operator-rules-cheatsheet.md` — the sovereignty rule, the operator-as-mind rule
- `pantheon/god-packages/shared-skills/convention-enforcer/SKILL.md` — validates the output
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — uses this skill when designing a new build
- `pantheon/god-packages/shared-skills/design-review/SKILL.md` — reviews the output
