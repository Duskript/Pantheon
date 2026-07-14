# Pantheon — Communication Protocol

> Source: Constitution Section 10
> Read this document when: implementing Hermes, Iris, Kronos, Zeus escalation, or any inter-god message passing.

---

## Overview

Every inter-god message follows a standard envelope format. Hermes is the transport layer. No god communicates directly with another god by bypassing Hermes except for `call` actions within an active Sanctuary session where latency matters.

---

## The Message Envelope

Every message passed between gods uses this structure:

```json
{
  "message_id": "uuid-v4",
  "timestamp": "ISO-8601",
  "from": "apollo",
  "to": "mnemosyne",
  "action": "similarity_check",
  "session_id": "sanctuary-session-uuid",
  "workflow_id": "workflow-uuid-or-null",
  "priority": "normal",
  "payload": {
    "content": "the content being passed",
    "context": "additional context if needed",
    "metadata": {}
  },
  "response_expected": true,
  "timeout_seconds": 30
}
```

---

## Message Types

| Type | Description | Response Expected |
|---|---|---|
| request | God asks another god to perform an action | Yes |
| response | Reply to a request | No |
| escalation | God routes up to Zeus for orchestration | Yes |
| notification | One-way informational message — no reply needed | No |
| gate_pause | Workflow engine signals user gate required | Yes — user input |
| gate_resume | User gate resolved — workflow continues | No |
| health_check | Hestia pings a god to confirm it is alive | Yes |
| event | Demeter or file watcher signals a state change | No |

---

## Hermes As Transport

Hermes maintains a lightweight internal message queue. Gods publish messages to Hermes and subscribe to responses. This decouples gods from each other — Apollo does not need to know how to reach Mnemosyne directly. Apollo sends a message to Hermes addressed to Mnemosyne. Hermes delivers it.

```
Apollo → [request to Mnemosyne] → Hermes queue
                                         ↓
                               Hermes delivers to Mnemosyne
                                         ↓
                        Mnemosyne processes and responds
                                         ↓
                          Hermes delivers response to Apollo
```

For `call` actions within an active Sanctuary session where latency is a concern, gods may invoke each other directly via the routing engine without going through the full Hermes queue. This is the exception, not the rule.

---

## Escalation To Zeus

When a god cannot resolve a request within its domain it escalates to Zeus with full context:

```json
{
  "from": "apollo",
  "to": "zeus",
  "action": "escalate",
  "payload": {
    "original_request": "...",
    "reason": "request_outside_domain",
    "suggested_god": "hephaestus",
    "context": "user appears to be asking about infrastructure"
  }
}
```

Zeus evaluates the escalation and either routes to the suggested god, routes elsewhere, or handles directly if it falls under orchestration. Zeus logs every escalation decision to Kronos.

### Hecate Consult Pattern

Hecate uses a specific escalation type when she detects conflicting domain signals and needs Zeus to identify candidate gods. This is not a full escalation — it is a lightweight consult that stays silent to the user.

```json
{
  "from": "hecate",
  "to": "zeus",
  "action": "consult",
  "payload": {
    "original_request": "...",
    "reason": "conflicting_domain_signals",
    "context": "request contains both creative and technical signals"
  }
}
```

Zeus responds with an ordered list of candidate gods and the reasoning behind each:

```json
{
  "from": "zeus",
  "to": "hecate",
  "action": "consult_response",
  "payload": {
    "candidates": [
      { "god": "apollo", "domain": "creative", "reason": "recording space as artistic environment" },
      { "god": "hephaestus", "domain": "technical", "reason": "recording space as infrastructure build" }
    ]
  }
}
```

Hecate then frames the disambiguation in her own voice using the candidates Zeus returned. Zeus is never referenced by name in the UI. The consult is logged to Kronos but not surfaced to the user.

---

## Kronos Logging

Every message that passes through Hermes is logged to Kronos with full envelope contents. This creates a complete audit trail of all inter-god communication. Kronos logs are append-only and stored in `/Athenaeum/Codex-Pantheon/sessions/kronos/`.

Log entries are structured for queryability — timestamp, from, to, action, session_id, and outcome are indexed fields. Full payload is stored but not indexed.

---

## Iris Notifications

When a background god needs to surface information to the user it does not interrupt the active session directly. It sends a notification message to Iris. Iris holds notifications and surfaces them at appropriate moments — between conversation turns, at session end, or immediately if priority is urgent.

```json
{
  "from": "hestia",
  "to": "iris",
  "action": "notify_user",
  "payload": {
    "message": "Mnemosyne re-embedding completed for Codex-SKC",
    "priority": "low",
    "surface_at": "next_turn_end"
  }
}
```

### Priority Levels

| Priority | Behavior |
|---|---|
| urgent | Surfaces immediately, interrupts if necessary |
| normal | Surfaces between turns |
| low | Surfaces at session end or next natural pause |
| silent | Logged to Kronos only, never shown to user |

---

## Hard Rules For This Layer

- Every inter-god message uses the standard envelope. No freeform god-to-god communication.
- Hermes is the default transport. Direct god invocation is permitted only for synchronous `call` actions within an active session.
- All messages are logged to Kronos. No silent inter-god communication.
- Timeouts are always defined. A god waiting for a response that never comes fails gracefully after `timeout_seconds` and logs the failure.
- Iris is the only path to the user from background gods. Background gods never write directly to the active session.
- Escalations always include a reason and suggested routing. Zeus never receives a blank escalation.
- All external web calls route through Prometheus. No god makes external network calls directly.

---

## Prometheus — External Web Gateway

Prometheus is Pantheon's controlled web search gateway. When a god needs external information that isn't in the Athenaeum or Mnemosyne, Prometheus fetches it. He is not a general external API bridge — his sole job is web search.

Cloud model calls are not Prometheus's concern. If a cloud model is configured in Hera, those inference calls flow directly at the inference layer without any approval gate — the decision was already made at config time.

### Default Behavior

Prometheus is **disabled by default**. No god can make external calls until Prometheus is enabled in Hera. Once enabled, access is granted per god — gods without explicit permission cannot route through Prometheus regardless of whether it is enabled globally.

### Approval Modes

Approval mode is set per god in Hera. Three options:

| Mode | Behavior | Default |
|---|---|---|
| Once per session | User approves on the first external call of each session — silent after that | ✓ |
| Every call | User approves each individual external call — maximum control | |
| Always accessible | Prometheus runs silently with no approval gate | |

The approval prompt is surfaced by Iris between turns — it never interrupts a response mid-generation.

### Request Flow

```
God determines external information is needed
        ↓
Checks Mnemosyne first — not found or insufficient
        ↓
God sends web_search request to Prometheus via Hermes
        ↓
Prometheus checks god's permission — no permission → hard reject, logged to Kronos
        ↓
Prometheus checks approval mode for this god
        ↓
If approval required — Iris surfaces prompt, waits for user confirmation
        ↓
User approves → Prometheus executes web search
        ↓
Results returned to requesting god via Hermes
        ↓
God uses results, continues response
        ↓
Results written to Staging/inbox/ for Mnemosyne to classify and absorb
```

### Message Envelope

```json
{
  "from": "apollo",
  "to": "prometheus",
  "action": "web_search",
  "session_id": "sanctuary-session-uuid",
  "priority": "normal",
  "payload": {
    "query": "shoegaze guitar tone techniques 2024",
    "context": "user asking about sonic references for SKC production",
    "max_results": 5
  },
  "response_expected": true,
  "timeout_seconds": 15
}
```

### Results and Staging

Prometheus writes search results to `Staging/inbox/` after every successful call. This means:
- Useful external content gets absorbed into the Athenaeum automatically via Mnemosyne
- The same search is unlikely to require a second external call in the future
- Results are attributed with source URL and retrieval timestamp in the staged file

### Kronos Logging

Every Prometheus call is logged to Kronos regardless of outcome — approved, rejected, failed, or timed out. Log entry includes: requesting god, query, approval mode, user decision (if applicable), result summary, and timestamp.

### Hard Rules — Prometheus

- Prometheus is disabled by default. Explicit enablement in Hera is required.
- Per-god permission is enforced. A god without permission cannot use Prometheus even if it is globally enabled.
- No god makes external network calls directly. All web search routes through Prometheus.
- Cloud model inference calls are not Prometheus's concern — they are handled at the inference layer.
- Every call is logged to Kronos. No silent external calls.
- Results are always staged to Staging/inbox/ after a successful call.
