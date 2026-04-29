# Pantheon — Workflow Engine and Node Editor

> Source: Constitution Sections 8, 9
> Read this document when: building or modifying the workflow engine, node editor, workflow JSON files, or any multi-god pipeline.

---

## Section 8 — The Workflow Engine

The workflow engine is Pantheon's runtime for executing multi-god task pipelines. Where a Sanctuary is a conversation with one god, a workflow is a defined sequence of gods working together to complete a task — with human-in-the-loop gates at decision points and branching logic based on outputs.

Workflows are the mechanism that makes Pantheon more than a chat interface. They encode repeatable processes so you don't have to manually orchestrate the same sequence of god interactions every time.

### What A Workflow Is

A workflow is a directed graph stored as a JSON file in `/Athenaeum/Codex-Pantheon/workflows/`. Each node in the graph is a god action. Each edge is a connection between actions. Gates are nodes that pause execution and wait for user input before continuing.

Workflows are authored visually in the Node Editor (Section 9) and stored as JSON. The workflow engine reads and executes that JSON. The two systems are separate — the engine can run workflows defined as raw JSON without the editor.

### Workflow JSON Structure

```json
{
  "id": "skc-lyric-review",
  "name": "SKC Lyric Review Pipeline",
  "description": "Draft a section, check corpus for repetition, review, finalize",
  "version": "1.0.0",
  "nodes": [
    {
      "id": "n1",
      "type": "god",
      "god": "apollo",
      "studio": "lyric-writing",
      "action": "draft_section",
      "input_from": "user",
      "output_to": "n2"
    },
    {
      "id": "n2",
      "type": "god",
      "god": "mnemosyne",
      "action": "similarity_check",
      "input_from": "n1",
      "output_to": "n3"
    },
    {
      "id": "n3",
      "type": "gate",
      "label": "Review similarity results",
      "message": "Mnemosyne found similar content. Review before continuing?",
      "options": ["Continue", "Revise", "Abort"],
      "output_to": {
        "Continue": "n4",
        "Revise": "n1",
        "Abort": null
      }
    },
    {
      "id": "n4",
      "type": "god",
      "god": "apollo",
      "studio": "lyric-writing",
      "action": "finalize_section",
      "input_from": "n3",
      "output_to": "n5"
    },
    {
      "id": "n5",
      "type": "vault_write",
      "codex": "Codex-SKC",
      "path": "lyrics/",
      "input_from": "n4",
      "output_to": null
    }
  ]
}
```

### Node Types

| Type | Description |
|---|---|
| god | Invokes a god with a specific action and passes input/output |
| gate | Pauses execution, presents options to user, branches based on choice |
| vault_write | Writes output to the Athenaeum at a specified path |
| vault_read | Reads content from the Athenaeum and injects into next node |
| condition | Evaluates output against a condition and branches without user input |
| transform | Reformats or reshapes data between nodes without invoking a god |
| trigger | External event that starts a workflow — file change, schedule, user action |

### Execution Model

```
Workflow loaded from JSON
        ↓
Starting node identified (type: trigger or first god node)
        ↓
Node executed — output stored in session context
        ↓
Next node determined from output_to mapping
        ↓
If gate node — execution pauses, user presented with options
        ↓
User selects option — execution resumes on mapped branch
        ↓
Continue until output_to is null (workflow end)
        ↓
Workflow result logged to Kronos
        ↓
Vault writes executed if any pending
```

### Context Passing

Each node receives the output of its input node as context. Context accumulates through the workflow — later nodes can reference outputs from any earlier node, not just the immediately preceding one. This allows a finalization node to see both the original draft and the similarity check results simultaneously.

```python
def execute_node(node, workflow_context):
    input_data = resolve_inputs(node, workflow_context)
    result = dispatch_node(node, input_data)
    workflow_context[node.id] = result
    return result
```

### Workflow Storage and Management

Workflows are stored in `/Athenaeum/Codex-Pantheon/workflows/` as JSON files. They are versioned — each save increments the version field. Old versions are archived, not deleted.

Workflows are available from any Sanctuary via a workflow launcher. Zeus can invoke workflows directly when routing determines a multi-step process is required. Users can also trigger workflows manually from the UI.

### Hard Rules — Workflow Engine

- Workflows are JSON files in the Athenaeum. They are not stored in a database.
- Gate nodes always require explicit user action. They cannot be configured to auto-resolve.
- Workflow execution is logged to Kronos in full — every node, every output, every gate decision.
- A workflow that encounters a missing god or unavailable model fails at that node and notifies the user. It does not skip nodes silently.
- Circular node references are detected at load time and rejected.
- Vault write nodes execute only after all preceding nodes have completed successfully.

---

## Section 9 — The Node Editor

The Node Editor is the visual authoring surface for workflows. It allows workflows to be created, edited, and connected graphically without writing JSON directly. The JSON is always the source of truth — the editor reads and writes it.

**The Node Editor is a Phase 3 build target. The workflow engine must be operational before the editor is built.**

### What The Node Editor Is

A canvas-based drag-and-drop interface embedded in the Pantheon UI. Users place nodes on a canvas, connect them with edges, configure each node via a sidebar panel, and save the result as a workflow JSON file in the Athenaeum.

The editor is built as part of the fork. React Flow is the recommended foundation given the frontend stack.

### Canvas Layout

```
Left panel    — Node palette, organized by type
               (Gods, Gates, Vault, Logic, Triggers)

Center canvas — Workflow graph, drag and drop surface
               Nodes connected by directional edges
               Zoom and pan supported

Right panel   — Selected node configuration
               Context-sensitive fields based on node type
               Previews routing options and gate branches
```

### Node Configuration By Type

**God Node** — God selector (from registry), studio selector, action field, input/output labels.

**Gate Node** — Gate message, options list (branch labels), branch mapping to target nodes, appearance (color and icon).

**Vault Write Node** — Codex selector, path field, filename (auto timestamp or custom pattern), format (markdown, plaintext, JSON).

**Condition Node** — Condition expression, true branch, false branch. No user interaction — executes silently.

**Trigger Node** — Trigger type (manual, scheduled, file watch, Demeter event), schedule field (scheduled triggers only), watch path (file watch triggers only).

### Workflow Validation

Before saving, the editor validates:

- All nodes must have at least one incoming or outgoing edge except triggers and terminal nodes
- Gate nodes must have all options mapped to target nodes
- No circular references unless explicitly flagged as intentional loops
- All referenced gods must exist in the registry
- All vault paths must point to valid Codex folders

Validation errors are shown inline on the canvas — the offending node is highlighted and the error described in the right panel. The workflow cannot be saved with validation errors.

### Import and Export

Workflows can be exported as JSON for sharing or backup. Exported files are valid workflow JSON and can be imported directly into any Pantheon instance. This is the mechanism for sharing workflow templates between instances.

### Relationship To The Workflow Engine

The editor and engine are decoupled. The engine executes JSON. The editor produces JSON. A workflow created in the editor runs identically to one written by hand. A workflow engine update never requires an editor update unless the JSON schema changes.

When the JSON schema changes the editor must be updated before the schema version is incremented in production. Old workflow files are migrated by a schema migration script, not by hand.

### Hard Rules — Node Editor

- The Node Editor is Phase 3. Do not begin building it until the workflow engine is operational and tested.
- React Flow or equivalent library is used as the canvas foundation. Do not build a canvas renderer from scratch.
- The editor never modifies workflow JSON directly in the Athenaeum during editing — it works on an in-memory copy and writes only on explicit save.
- Unsaved changes are flagged visually. Navigating away from an unsaved workflow prompts confirmation.
- The raw JSON view is always accessible from the editor via a toggle. Power users can edit JSON directly and see changes reflected on the canvas.
