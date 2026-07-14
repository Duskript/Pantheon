# Conductor Build Brief — Today's Build Session

**Spec:** `~/athenaeum/Codex-Pantheon/specs/conductor-workflow-engine.md` (v1.1.0)
**Goal:** Complete Conductor system — handoff queue, MCP server, workflow engine, abort handling, NATS bridge, and webhook gateway
**Build order:** Each phase is a working checkpoint you can validate before moving on
**Available infrastructure:** nats-server v2.11.1 installed, nats-py v2.14.0 in venv, no NATS server running yet

---

## Phase 1 — Directory Structure (~5 min)

**Why:** Conductor is file-driven. Everything reads from and writes to directories. No DB setup needed.

**What to create:**

```bash
mkdir -p ~/pantheon/conductor/{rules,workflows,state,pending/{thoth,hephaestus,marvin,hermes,iris,caduceus,mercer,rheta}}
mkdir -p ~/pantheon/shared/handoffs
```

That's it. The `pending/` dirs are per-god inboxes. The `state/` dir holds active workflow instances. `handoffs/` holds the handoff files between steps.

**Validation:** `tree ~/pantheon/conductor ~/pantheon/shared/handoffs` shows the structure.

---

## Phase 2 — Handoff JSON Schema (~15 min)

**Why:** This is the data contract. Every god must hand off in the same format. If gods hand off inconsistently, the router can't route.

**What to create:** `~/pantheon/shared/handoffs/schema.json`

This is a reference file — not code, just documentation that tells every god what a valid handoff looks like. The schema is intentionally minimal: gods provide only what they did, Conductor fills in the rest.

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "Conductor Handoff",
  "description": "File written by a god when completing a workflow step. Conductor reads this, routes to the next step.",
  "type": "object",
  "required": ["handoff_id", "workflow_id", "from_god", "to_god", "step", "context"],
  "properties": {
    "handoff_id": {
      "type": "string",
      "pattern": "^hof_\\d{8}_[a-z0-9]{6}$",
      "description": "Unique ID. Format: hof_YYYYMMDD_random6"
    },
    "workflow_id": {
      "type": "string",
      "pattern": "^wf_[a-z0-9_]+$",
      "description": "Workflow instance this belongs to. Format: wf_{name}_{seq}"
    },
    "from_god": { "type": "string", "description": "Who completed the step" },
    "to_god": { "type": "string", "description": "Who should do the next step" },
    "step": { "type": "string", "description": "Step ID that was completed" },
    "context": {
      "type": "object",
      "required": ["decisions", "artifacts", "summary"],
      "properties": {
        "summary": { "type": "string", "description": "One-line summary of what was done" },
        "decisions": { "type": "array", "items": { "type": "string" }, "description": "Decisions made during this step" },
        "artifacts": { "type": "array", "items": { "type": "string" }, "description": "Paths to files produced" },
        "open_questions": { "type": "array", "items": { "type": "string" }, "description": "Open questions for the next god" }
      }
    }
  }
}
```

**Validation:** A sample handoff file in `~/pantheon/shared/handoffs/` that matches the schema:

```json
{
  "handoff_id": "hof_20260613_sample01",
  "workflow_id": "wf_deploy_42",
  "from_god": "thoth",
  "to_god": "hephaestus",
  "step": "research",
  "context": {
    "summary": "Researched MCP ecosystem migration options",
    "decisions": ["Migrate to FastMCP 3.x"],
    "artifacts": ["/athenaeum/research/mcp-report.md"],
    "open_questions": ["Should Hermes coordinate upgrade schedule?"]
  }
}
```

---

## Phase 3 — Ack Schema (~5 min)

**Why:** Same reason as the handoff schema — gods need a standard response contract so Conductor knows what the ack means.

**What to create:** The ack format lives in the handoff schema file (add as a second schema) or as a separate `~/pandemonium/pantheon/shared/ack-schema.json`. Keep it in the same file for simplicity.

Ack response (gods return this when Conductor dispatches work to them):

```json
{
  "ack_id": "ack_20260613_456",
  "handoff_id": "hof_20260613_abc123",
  "status": "accepted",
  "eta": "2026-06-13T15:00:00Z",
  "message": "Heard, pulling context now. ETA ~30min."
}
```

Status values:
- `accepted` — God has the work, will execute. Conductor waits for result.
- `pending` — God is busy, queued it. Conductor checks back later.
- `rejected` — Wrong god. Conductor re-routes or escalates.
- `completed` — Step done. Conductor starts next step.

---

## Phase 4 — Conductor Server (unified, ~3h)

**Why:** This is the brain. Single process that serves MCP tools, optionally runs a NATS subscriber for cross-Pantheon messaging, and optionally runs an HTTP webhook gateway for external services. Without this, the directories are empty boxes.

**What to build:** `~/pantheon/conductor/conductor-server.py`

A single-file Python MCP server using the MCP SDK. Should expose these tools:

### MCP Tools to Expose

| Tool | Called By | Purpose |
|---|---|---|
| `conductor.submit_handoff` | Any god | "I finished my step, here's what I produced" |
| `conductor.check_inbox` | Any god | "What work is waiting for me?" |
| `conductor.ack_handoff` | Any god | "I received the dispatch, status: accepted/pending/rejected" |
| `conductor.get_workflow_state` | Any god, Hermes | "What's the status of workflow X?" |
| `conductor.list_pending` | Hermes | "What's in the queue across all gods?" |
| `conductor.list_rules` | Konan | "What reaction rules are active?" |
| `conductor.list_workflows` | Konan | "What workflow definitions exist?" |
| `conductor.abort_workflow` | Konan | "Cancel workflow X, stamp artifacts" |
| `conductor.cleanup` | Konan | "Delete temp artifacts for aborted workflow X" |

### Internal Logic

When `submit_handoff` is called:

```
1. Validate handoff against schema
2. Write handoff file to ~/pantheon/shared/handoffs/{workflow_id}/{step}.json
3. Load active workflow state from ~/pantheon/conductor/state/{workflow_id}.json
4. Update state: mark current step completed, add context bag
5. Determine next step:
   a. Is there a workflow definition for this? Load ~/pantheon/conductor/workflows/{def_id}.yaml
   b. Find the next step after this one in the YAML
   c. If no workflow definition: find matching reaction rule from ~/pantheon/conductor/rules/*.yaml
6. Write dispatch to target god's pending queue: ~/pantheon/conductor/pending/{to_god}/{handoff_id}.json
7. Return: { status: "dispatched", target_god, target_step, workflow_id }
```

When `check_inbox` is called by a god:

```
1. List files in ~/pantheon/conductor/pending/{god_name}/
2. For each file, read the dispatch request
3. Return array of pending dispatches
```

When `ack_handoff` is called:

```
1. Mark the ack status in the workflow state
2. If "accepted": update status to "in_progress", set ETA
3. If "pending": no action, wait for follow-up
4. If "rejected": update workflow state, look for alternative routing
5. If "completed": trigger next step via submit_handoff logic
```

When `abort_workflow` is called:

```
1. Load workflow state
2. Transition to status: "aborted"
3. For every completed step's artifacts (listed in step output):
   - Append abort footer to each artifact file
4. Write abort manifest to ~/pantheon/conductor/state/{workflow_id}.aborted.json
5. Return: { status: "aborted", artifacts_stamped: [...], manifest_path }
```

### Workflow State JSON Format

Stored at `~/pantheon/conductor/state/{workflow_id}.json`:

```json
{
  "workflow_id": "wf_deploy_42",
  "definition_id": "deploy-feature",
  "status": "in_progress",
  "current_step": "implement",
  "context_bag": {
    "decisions": ["Use FastMCP 3.x"],
    "artifacts": ["/athenaeum/research/mcp-report.md"]
  },
  "step_history": [
    { "step_id": "research", "god": "thoth", "status": "completed" }
  ],
  "created": "2026-06-13T10:00:00Z",
  "completion_target": "2026-06-14T18:00:00Z",
  "abort_on_fail": false
}
```

Status values: `in_progress`, `waiting_for_ack`, `completed`, `aborted`, `failed`

### Sample MCP Implementation Sketch

```python
#!/usr/bin/env python3
"""
Conductor MCP Server — Pantheon Workflow & Reaction Engine
FastMCP-style server that exposes handoff routing, workflow state, and abort handling.
"""

import json, os, re, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = os.path.expanduser("~/pantheon/conductor")
HANDOFFS_DIR = os.path.expanduser("~/pantheon/shared/handoffs")
PENDING_DIR = os.path.join(BASE_DIR, "pending")
STATE_DIR = os.path.join(BASE_DIR, "state")
RULES_DIR = os.path.join(BASE_DIR, "rules")
WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")

from mcp.server import FastMCP
server = FastMCP("Conductor")

@server.tool()
def submit_handoff(handoff: dict) -> dict:
    """Submit a completed step handoff. Conductor routes to the next step."""
    # 1. Validate required fields
    required = ["handoff_id", "workflow_id", "from_god", "step", "context"]
    for field in required:
        if field not in handoff:
            return {"error": f"Missing required field: {field}"}
    
    # 2. Write handoff file
    wf_dir = os.path.join(HANDOFFS_DIR, handoff["workflow_id"])
    os.makedirs(wf_dir, exist_ok=True)
    step_file = os.path.join(wf_dir, f"{handoff['step']}.json")
    with open(step_file, "w") as f:
        json.dump(handoff, f, indent=2)
    
    # 3. Load or create workflow state
    state_file = os.path.join(STATE_DIR, f"{handoff['workflow_id']}.json")
    if os.path.exists(state_file):
        with open(state_file) as f:
            state = json.load(f)
    else:
        # First step — create state
        state = {
            "workflow_id": handoff["workflow_id"],
            "status": "in_progress",
            "current_step": handoff["step"],
            "context_bag": dict(handoff.get("context", {})),
            "step_history": [],
            "created": datetime.now(timezone.utc).isoformat()
        }
    
    # 4. Update step history
    history_entry = {
        "step_id": handoff["step"],
        "god": handoff["from_god"],
        "status": "completed" if handoff.get("state", {}).get("ready_for_next") else "paused",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "summary": handoff.get("context", {}).get("summary", "")
    }
    state["step_history"].append(history_entry)
    
    # 5. Merge context
    if "decisions" in handoff.get("context", {}):
        state["context_bag"]["decisions"] = state["context_bag"].get("decisions", []) + handoff["context"]["decisions"]
    if "artifacts" in handoff.get("context", {}):
        state["context_bag"]["artifacts"] = state["context_bag"].get("artifacts", []) + handoff["context"]["artifacts"]
    
    # 6. Determine next step
    target_god = handoff.get("to_god", None)
    next_step = handoff.get("routing", {}).get("workflow_step", None)
    
    if target_god:
        # Direct routing — write to pending queue
        dispatch = {
            "dispatch_id": f"disp_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "handoff_id": handoff["handoff_id"],
            "workflow_id": handoff["workflow_id"],
            "from_god": handoff["from_god"],
            "to_god": target_god,
            "step": next_step or handoff["step"],
            "context": handoff["context"],
            "dispatched_at": datetime.now(timezone.utc).isoformat()
        }
        
        inbox_dir = os.path.join(PENDING_DIR, target_god)
        os.makedirs(inbox_dir, exist_ok=True)
        dispatch_file = os.path.join(inbox_dir, f"{dispatch['dispatch_id']}.json")
        with open(dispatch_file, "w") as f:
            json.dump(dispatch, f, indent=2)
        
        state["status"] = "waiting_for_ack"
        state["current_step"] = next_step or handoff["step"]
        state["dispatched_to"] = target_god
    else:
        # No routing — workflow is done or paused
        state["status"] = "completed" if not target_god else state["status"]
    
    # 7. Save state
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    
    return {
        "status": "dispatched" if target_god else "recorded",
        "workflow_id": handoff["workflow_id"],
        "target_god": target_god,
        "target_step": next_step,
        "state_status": state["status"]
    }

@server.tool()
def check_inbox(god_name: str) -> dict:
    """Check pending dispatches for a god."""
    inbox_dir = os.path.join(PENDING_DIR, god_name)
    if not os.path.exists(inbox_dir):
        return {"god": god_name, "dispatches": []}
    
    dispatches = []
    for fname in sorted(os.listdir(inbox_dir)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(inbox_dir, fname)
        with open(fpath) as f:
            dispatches.append(json.load(f))
    
    return {
        "god": god_name,
        "dispatches": dispatches,
        "count": len(dispatches)
    }

@server.tool()
def ack_handoff(ack: dict) -> dict:
    """Acknowledge a dispatch. Gods call this when they accept/pending/reject work."""
    required = ["ack_id", "handoff_id", "status"]
    for field in required:
        if field not in ack:
            return {"error": f"Missing required field: {field}"}
    
    valid_statuses = ["accepted", "pending", "rejected", "completed"]
    if ack["status"] not in valid_statuses:
        return {"error": f"Invalid status: {ack['status']}. Must be one of: {valid_statuses}"}
    
    # Find the dispatch file and remove it from pending (ack received)
    # The status tells us what to do next
    if ack["status"] == "completed":
        # God completed the step — this ack IS the step completion
        pass
    
    return {
        "acknowledged": True,
        "handoff_id": ack["handoff_id"],
        "status": ack["status"],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@server.tool()
def get_workflow_state(workflow_id: str) -> dict:
    """Get the current state of a workflow."""
    state_file = os.path.join(STATE_DIR, f"{workflow_id}.json")
    if not os.path.exists(state_file):
        return {"error": f"Workflow {workflow_id} not found"}
    with open(state_file) as f:
        return json.load(f)

@server.tool()
def list_pending() -> dict:
    """List all pending dispatches across all gods."""
    result = {}
    for god_dir in sorted(os.listdir(PENDING_DIR)):
        god_path = os.path.join(PENDING_DIR, god_dir)
        if not os.path.isdir(god_path):
            continue
        dispatches = []
        for fname in sorted(os.listdir(god_path)):
            if not fname.endswith(".json"):
                continue
            with open(os.path.join(god_path, fname)) as f:
                d = json.load(f)
                dispatches.append({
                    "dispatch_id": d.get("dispatch_id"),
                    "workflow_id": d.get("workflow_id"),
                    "from_god": d.get("from_god"),
                    "dispatched_at": d.get("dispatched_at")
                })
        if dispatches:
            result[god_dir] = dispatches
    return result

@server.tool()
def abort_workflow(workflow_id: str, reason: str) -> dict:
    """Abort a workflow. Writes abort manifest + .aborted marker files beside artifacts."""
    state_file = os.path.join(STATE_DIR, f"{workflow_id}.json")
    if not os.path.exists(state_file):
        return {"error": f"Workflow {workflow_id} not found"}
    
    with open(state_file) as f:
        state = json.load(f)
    
    state["status"] = "aborted"
    state["failure_reason"] = reason
    state["aborted_at"] = datetime.now(timezone.utc).isoformat()
    
    # Collect artifacts from completed steps
    artifacts_marked = []
    for entry in state.get("step_history", []):
        if entry.get("status") != "completed":
            continue
        handoff_file = os.path.join(HANDOFFS_DIR, workflow_id, f"{entry['step_id']}.json")
        if os.path.exists(handoff_file):
            try:
                with open(handoff_file) as f:
                    handoff = json.load(f)
                for art in handoff.get("context", {}).get("artifacts", []):
                    art_path = os.path.expanduser(art)
                    # Write zero-byte .aborted marker beside each artifact
                    marker = f"{art_path}.aborted"
                    with open(marker, "w") as mf:
                        mf.write("")  # zero bytes — name tells the story
                    artifacts_marked.append(art)
            except Exception:
                pass
    
    # Write abort manifest
    manifest = {
        "workflow_id": workflow_id,
        "status": "aborted",
        "failed_step": state.get("current_step"),
        "failure_reason": reason,
        "completed_steps": [{"step_id": e["step_id"], "god": e["god"]} for e in state["step_history"] if e["status"] == "completed"],
        "artifacts_marked": artifacts_marked,
        "aborted_at": state["aborted_at"],
        "requires_manual_review": False
    }
    manifest_file = os.path.join(STATE_DIR, f"{workflow_id}.aborted.json")
    with open(manifest_file, "w") as f:
        json.dump(manifest, f, indent=2)
    
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)
    
    return {
        "status": "aborted",
        "workflow_id": workflow_id,
        "artifacts_marked": artifacts_marked,
        "manifest_path": manifest_file
    }

@server.tool()
def cleanup(workflow_id: str) -> dict:
    """Delete temp artifacts for an aborted workflow."""
    manifest_file = os.path.join(STATE_DIR, f"{workflow_id}.aborted.json")
    if not os.path.exists(manifest_file):
        return {"error": f"No abort manifest found for {workflow_id}. Has it been aborted?"}
    
    with open(manifest_file) as f:
        manifest = json.load(f)
    
    # Load workflow definition to find temp_artifacts paths
    state_file = os.path.join(STATE_DIR, f"{workflow_id}.json")
    if not os.path.exists(state_file):
        return {"error": f"Workflow state not found for {workflow_id}"}
    
    with open(state_file) as f:
        state = json.load(f)
    
    # Look for temp_artifacts in the workflow def
    def_id = state.get("definition_id")
    if not def_id:
        return {"status": "no_temp_declared", "deleted": [], "message": "No workflow definition ID found. Nothing to clean."}
    
    def_file = os.path.join(WORKFLOWS_DIR, f"{def_id}.yaml")
    if not os.path.exists(def_file):
        return {"status": "no_temp_declared", "deleted": [], "message": "Workflow definition not found. Temp cleanup requires the definition file."}
    
    # Parse YAML for temp_artifacts
    # (Simple implementation — reads the YAML manually)
    import re
    with open(def_file) as f:
        content = f.read()
    
    temp_patterns = re.findall(r'temp_artifacts:\n(?:\s+- "([^"]+)"\n?)+', content)
    # Simpler: find all temp_artifacts entries
    deleted = []
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("- ") and ("temp" in line or "scratch" in line or "tmp" in line):
            # This is a heuristic — the YAML path should be in quotes
            match = re.search(r'"([^"]+)"', line)
            if match:
                path = match.group(1).replace("{workflow_id}", workflow_id)
                path = os.path.expanduser(path)
                import shutil
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                    deleted.append(path)
                elif os.path.isfile(path):
                    os.remove(path)
                    deleted.append(path)
    
    # Remove .aborted marker files beside each artifact
    for art_path in manifest.get("artifacts_marked", []):
        marker = f"{os.path.expanduser(art_path)}.aborted"
        if os.path.exists(marker):
            try:
                os.remove(marker)
                deleted.append(marker)
            except Exception:
                pass
    
    return {
        "status": "completed",
        "workflow_id": workflow_id,
        "deleted": deleted,
        "markers_removed": len(manifest.get("artifacts_marked", [])),
        "permanent_artifacts_retained": manifest.get("artifacts_marked", [])
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Conductor — Pantheon Workflow Engine")
    parser.add_argument("--nats", action="store_true", help="Enable NATS bridge for cross-Pantheon messaging")
    parser.add_argument("--webhook-port", type=int, default=0, help="Enable webhook gateway on this port (e.g. 8088)")
    args = parser.parse_args()
    
    # Start the MCP server (always runs)
    # In a production setup, you'd start the NATS thread and webhook thread here.
    # For now, MCP is the primary surface. NATS and webhook are separate scripts
    # that can be started alongside.
    server.run()
```

### Dependencies

```
pip install mcp
```

No database. This is file-driven, zero infrastructure. NATS subscriber and webhook gateway are optional threads within this same server (enable with --nats and --webhook-port flags).

### How to Run

```bash
# Start with MCP tools only
python3 conductor-server.py

# Enable NATS bridge for cross-Pantheon messaging
python3 conductor-server.py --nats

# Enable webhook gateway on port 8088
python3 conductor-server.py --webhook-port 8088

# Enable both
python3 conductor-server.py --nats --webhook-port 8088
```

### How to Test (from any god session)

```
User to Thoth/Hephaestus/Marvin:
  Can you check my inbox with the conductor MCP tool?

Or test manually:
```

---

## Phase 5 — Workflow Definition (First Example) (~15 min)

**Why:** Without a workflow, the system just routes handoffs. A workflow gives it structure — gods know what step they're on and what comes next.

**What to create:** `~/pantheon/conductor/workflows/example-research-build.yaml`

```yaml
workflow:
  id: example-research-build
  name: "Research → Build Pipeline"
  version: "1.0.0"
  description: "Simple two-step: Thoth researches, Hephaestus builds"

  steps:
    - id: research
      god: thoth
      skill: deep-research
      gates: [state_gate]
      timeout: 1h
    
    - id: build
      god: hephaestus
      skill: test-driven-development
      input_from: research
      gates: [logic_gate]
      timeout: 2h
    
    - id: review
      god: hermes
      skill: summarize
      input_from: build
      gates: []
```

**Validation:** The conductor-server reads this to determine next steps when a handoff comes in.

---

## Phase 6 — Reaction Rules (First Example) (~10 min)

**Why:** Rules tell Conductor what to do when there's no explicit workflow definition or when an event arrives outside a workflow context.

**What to create:** `~/pantheon/conductor/rules/example-routing.yaml`

```yaml
rules:
  - id: thoth-research-to-hephaestus
    when:
      event_type: handoff.completed
      source: thoth
      target: hephaestus
    then:
      dispatch_workflow: example-research-build
      start_at_step: build
      context: inherit_full

  - id: unmatched-event-quarantine
    when:
      event_type: "*"
      source: "*"
    then:
      handling_mode: approval_required
      # Default catch-all for unknown events
```

---

## Phase 7 — God SKILL.md Updates (distributed work) (~1h)

**Why:** The server is useless if gods don't know to call it. Each god's SKILL.md needs a Conductor section that tells them:

1. At session start → Call `conductor.check_inbox(my_god_name)` to find waiting work
2. When completing a step → Call `conductor.submit_handoff(...)` with the handoff JSON
3. When receiving a dispatch → Call `conductor.ack_handoff(...)` within 5 min
4. Never ask "what did we decide" → the context is in the handoff

**What to update (per god):** `~/.hermes/profiles/{god}/skills/{god}/SKILL.md`

Add a section like this:

```markdown
## Conductor Integration

This god participates in Conductor-managed workflows.

### Protocol
- **Session start:** Call `conductor.check_inbox(god_name)` to see pending dispatches
- **Work received:** Call `conductor.ack_handoff(...)` with status=accepted, provide ETA
- **Work rejected:** Call `conductor.ack_handoff(...)` with status=rejected, provide reason
- **Work complete:** Call `conductor.submit_handoff(...)` with the handoff JSON
- **Context arrives with handoff:** The handoff's `context` block contains all decisions, artifacts, and open questions from previous steps. Read it first. Do not ask the user to repeat information that is already in the context.

### Required Handoff Fields (god provides — Conductor derives the rest)
| Field | Description | Example |
|---|---|---|
| handoff_id | `hof_{date}_{random6}` | hof_20260613_abc123 |
| workflow_id | From the dispatch | wf_deploy_42 |
| from_god | Your name | hephaestus |
| to_god | Next god | marvin |
| step | Step ID | architect |
| context.summary | One-line summary | "Arch spec complete" |
| context.decisions | Decisions made | ["Use FastMCP 3.x"] |
| context.artifacts | Files produced | ["/path/to/arch.md"] |
```

---

### NATS Bridge (optional, enable with --nats flag)

**Why:** Cross-Pantheon messaging with Tallon's instance. Without this, Conductor can only route events locally. With it, Tallon's messages arrive in the same routing system as internal handoffs.

### Starting the NATS Server

```bash
# Create a config
mkdir -p ~/pantheon/nats
cat > ~/pantheon/nats/server.conf << 'EOF'
port: 4222
http_port: 8222
jetstream: true
store_dir: /home/konan/pantheon/nats/data
EOF

# Create a systemd user service
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/nats-server.service << 'EOF'
[Unit]
Description=NATS Server
After=network.target

[Service]
Type=simple
ExecStart=/home/konan/.local/bin/nats-server -c /home/konan/pantheon/nats/server.conf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now nats-server.service
loginctl enable-linger
```

### NATS Bridge Script (conductor-nats-bridge.py)

```python
#!/usr/bin/env python3
"""
Conductor NATS Bridge — subscribes to NATS subjects, translates messages
to Conductor event envelopes, writes to pending queues.
Cross-Pantheon handoffs with Tallon.
"""

import json, os, asyncio
from pathlib import Path

PENDING_DIR = os.path.expanduser("~/pantheon/conductor/pending")
NATS_SERVER = "nats://localhost:4222"

async def handle_incoming(msg):
    try:
        payload = json.loads(msg.data)
        subject = msg.subject
        parts = subject.split(".")
        target_god = parts[3] if len(parts) >= 4 else None
        if not target_god:
            return

        dispatch = {
            "dispatch_id": f"nats_{payload.get('id', 'unknown')}",
            "workflow_id": payload.get("workflow_id", f"cross_{asyncio.get_event_loop().time():.0f}"),
            "from_god": "tallon",
            "to_god": target_god,
            "source": "nats",
            "context": payload.get("context", {}),
            "dispatched_at": datetime.now(timezone.utc).isoformat()
        }
        
        inbox_dir = Path(PENDING_DIR) / target_god
        inbox_dir.mkdir(parents=True, exist_ok=True)
        (inbox_dir / f"{dispatch['dispatch_id']}.json").write_text(json.dumps(dispatch, indent=2))
        
        ack = json.dumps({"status": "accepted", "dispatch_id": dispatch["dispatch_id"]})
        await msg.respond(ack)
    except Exception as e:
        print(f"NATS bridge error: {e}")

async def main():
    import nats
    nc = await nats.connect(NATS_SERVER)
    await nc.subscribe("subspace.*.incoming.*", cb=handle_incoming)
    print(f"NATS Bridge connected to {NATS_SERVER}")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
```

**NATS Subjects for Conductor:**

| Subject | Direction | Purpose |
|---|---|---|
| `subspace.{pantheon}.incoming.{god}` | Inbound | Tallon → Our god |
| `subspace.{pantheon}.outgoing.{target}` | Outbound | Conductor → Tallon |
| `subspace.{pantheon}.workflow.{event}` | Broadcast | Workflow start/completion/failure |
| `subspace.broadcast` | Both | Cross-Pantheon broadcast |

**Validation:** Start the NATS server, start the bridge, send `nats pub "subspace.tallon.incoming.hephaestus" '{"id":"test"}'` and check the hephaestus pending queue.

---

### Webhook Gateway (optional, enable with --webhook-port)

**Why:** External services (GitHub, Stripe, Jira, YouTube, etc.) can't call MCP tools. They send HTTP POST webhooks. This gateway translates those POSTs into Conductor event envelopes and writes them to the pending queue — same pipeline as everything else.

**What to create:** `~/pantheon/conductor/conductor-webhook.py`

```python
#!/usr/bin/env python3
"""
Conductor Webhook Gateway — accepts HTTP webhooks, converts to
Conductor event envelopes, writes to pending queue.
"""

import json, os, uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

PENDING_DIR = os.path.expanduser("~/pantheon/conductor/pending")

class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": "invalid JSON"}')
            return
        
        source = self.path.split("/")[-1]
        event_id = f"wh_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        envelope = {
            "dispatch_id": event_id,
            "source": source,
            "event_type": "webhook",
            "workflow_id": f"webhook_{source}_{datetime.now().strftime('%Y%m%d')}",
            "context": {
                "raw_payload": payload,
                "headers": dict(self.headers),
                "received_at": datetime.now(timezone.utc).isoformat()
            }
        }
        
        webhook_dir = os.path.join(PENDING_DIR, "_webhooks")
        os.makedirs(webhook_dir, exist_ok=True)
        with open(os.path.join(webhook_dir, f"{event_id}.json"), "w") as f:
            json.dump(envelope, f, indent=2)
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "received", "event_id": event_id, "source": source}).encode())
    
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Conductor Webhook Gateway")

def run(port=8088):
    from http.server import HTTPServer
    server = HTTPServer(("", port), WebhookHandler)
    print(f"Webhook gateway on port {port} — POST /webhook/{'{source}'}")
    server.serve_forever()

if __name__ == "__main__":
    import sys; run(int(sys.argv[1]) if len(sys.argv) > 1 else 8088)
```

**Validation:**
```bash
curl -X POST http://localhost:8088/webhook/github \
  -H "Content-Type: application/json" \
  -d '{"action":"opened","pull_request":{"number":42}}'
ls ~/pantheon/conductor/pending/_webhooks/
```

---

## Build Order (for Today)

```
Phase 1: Directory structure              5min  → working directories
Phase 2: Handoff schema                   15min → data contract defined
Phase 3: Ack schema                       5min  → response contract defined
Phase 4: Conductor server (unified)        ~3h   → MCP tools + NATS bridge + webhook gateway in one process
  ├── submit_handoff                       first MCP tool to build
  ├── check_inbox                          second tool
  ├── ack_handoff                          third tool
  ├── get_workflow_state + list_pending    query tools
  ├── abort_workflow + cleanup             abort tools
  ├── accumulation engine                  extends rule matcher
  └── optional: --nats, --webhook-port     feature flags for extras
Phase 5: First workflow definition        15min → example to test with
Phase 6: First reaction rule              10min → example rule
Phase 7: God SKILL.md updates             1h    → gods know how to use it
                 ─────────────────────────
                 ~4.5h total
```

---

## What Each Phase Buys You

| After Phase | You Can |
|---|---|
| 1-3 | Nothing visible yet, but the data contracts are set |
| 4 | Unified server with MCP tools + optional NATS + optional webhook gateway | Full system in one process |
| 5 | Conductor reads your workflow YAML and routes accordingly | Declarative multi-god pipelines |
| 6 | External events and handoff patterns trigger automated routing | Event-driven dispatching |
| 7 | Gods self-check at session start — full automation | Every god participates |

---

## What's Out of Scope

| Not Building | Why |
|---|---|
| Visual workflow editor | That's a TheoForge product — separate from Conductor infrastructure. Conductor is the runtime, editor is the config surface. |
| Accumulation/threshold custom node types | The building blocks are all here, but complex filter/transform logic is outside Conductor's routing scope. That's what the deities themselves handle. |
