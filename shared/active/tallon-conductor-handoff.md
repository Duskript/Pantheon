# Cross-Pantheon Handoff — Conductor Integration for Tallon

**From:** Konan (via Thoth)
**Date:** 2026-06-14
**Purpose:** What Tallon needs to set up Conductor on his Pantheon instance and establish cross-instance messaging

---

## What Conductor Is

A lightweight MCP server that routes work between gods. File-driven, no database. Single Python process. It:

- Receives handoffs from gods when they complete a step
- Matches against reaction rules (YAML) to determine next step
- Dispatches work to target god's pending queue
- Tracks workflow state across multi-god chains
- Handles abort (manifest + marker files, no content stamping)
- Optionally connects via NATS for cross-Pantheon messaging

---

## What Tallon Needs to Build

### 1. The Conductor Spec

All architecture, schemas, and rationale are in one document:

**`~/athenaeum/Codex-Pantheon/specs/conductor-workflow-engine.md` (v2.0.0)**

Key sections to read:
- **Section 2** — Architecture overview
- **Section 3** — Component specs (event envelope, handoff protocol, ack protocol, reaction rules, context store)
- **Section 6** — Implementation layers (what to build and in what order)
- **Section 8** — Guardrails (external event handling modes)
- **Section 3.3** — Handoff JSON schema (simplified: gods provide summary, decisions, artifacts; Conductor derives rest)

### 2. Files to Create on His System

```
~/pantheon/conductor/
├── conductor-server.py       # Unified MCP server
├── rules/                    # Reaction rule YAML files
├── workflows/                # Workflow definition YAML files
├── state/                    # Active workflow state JSON
└── pending/{god}/            # Per-god inboxes

~/pantheon/shared/handoffs/   # Step handoff files
~/pantheon/nats/              # NATS server config (optional)
```

### 3. The Event Envelope (NATS Messages)

Every message between pantheons uses this format:

```json
{
  "id": "evt_20260614_abc123",
  "type": "handoff.completed",
  "source": "tallon",
  "target": "hephaestus",
  "timestamp": "2026-06-14T14:30:00Z",
  "workflow_id": "wf_cross_42",
  "step_id": "research",
  "context": {
    "summary": "Researched X, found Y",
    "decisions": ["Decision A"],
    "artifacts": ["/path/to/report.md"]
  }
}
```

### 4. NATS Subjects

| Subject | Direction | Purpose |
|---|---|---|
| `subspace.{pantheon_id}.incoming.{god}` | Inbound | Messages TO a specific god |
| `subspace.{pantheon_id}.outgoing.{target}` | Outbound | Messages FROM this pantheon |
| `subspace.{pantheon_id}.workflow.{event}` | Broadcast | Workflow lifecycle events |
| `subspace.broadcast` | Both | Cross-Pantheon broadcast |

Tallon's pantheon_id = `tallon`
Konan's pantheon_id = `konan` (or `theoforgesolutions`)

### 5. Cross-Pantheon NATS Connection (Two Options)

**Option A — Shared NATS Server (Recommended)**

We run a NATS server at a network-accessible address. Tallon's Conductor NATS bridge connects to it as a client:

```python
# In Tallon's conductor-server.py (or NATS bridge):
nc = await nats.connect("nats://{konan-server}:4222")
await nc.subscribe(f"subspace.tallon.incoming.*", cb=handle_incoming)
# To send: await nc.publish("subspace.konan.incoming.hephaestus", payload)
```

Requires: NATS URL (we provide), credentials (nkey or user/pass), and agreed pantheon_id

**Option B — NATS Leaf Node**

Each side runs their own NATS server. Tallon's server connects to ours as a leaf node:

```conf
# Tallon's nats-server.conf — leaf node remote pointing to our server
leafnodes {
  remotes: [
    {
      url: "nats://{konan-server}:7422"
      credentials: "/path/to/leaf.creds"
    }
  ]
}
```

Subjects route between servers automatically. More complex to set up but each side keeps their NATS local.

### 6. Handoff Schema (same as ours)

```json
{
  "handoff_id": "hof_20260614_abc123",
  "workflow_id": "wf_cross_42",
  "from_god": "thoth",
  "to_god": "hephaestus",
  "step": "research",
  "context": {
    "summary": "One-line summary of what was done",
    "decisions": ["Decision made during this step"],
    "artifacts": ["/path/to/file.md"]
  }
}
```

Gods provide only summary, decisions, artifacts. Conductor fills in workflow position, gates_passed, routing from state.

### 7. Ack Protocol

```json
{
  "ack_id": "ack_20260614_456",
  "handoff_id": "hof_20260614_abc123",
  "status": "accepted",
  "eta": "2026-06-14T15:00:00Z",
  "message": "Heard, pulling context now."
}
```

Single timeout from step config (no 3-tier ladder). No ack within timeout = escalate to Hermes.

---

## What We Need From Tallon

| Item | Purpose |
|---|---|
| His pantheon_id | For subject routing (e.g., "tallon") |
| His NATS connectivity preference | Shared server vs leaf node vs none for now |
| Whether his gods follow the same SKILL.md conventions | For cross-pantheon handoffs to work bi-directionally |

---

## Suggested Build Order (for Tallon)

1. Read the spec — understand the architecture
2. Build Conductor server (Phase 1-4 from build brief) — gets local routing working
3. Define workflows and reaction rules — his gods can hand off to each other
4. Wire NATS bridge — connects to Konan's instance for cross-pantheon handoffs
5. Test with a cross-pantheon workflow — Thoth→Tallon's Marvin or vice versa
