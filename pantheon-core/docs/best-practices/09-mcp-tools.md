---
title: "MCP Tools — the operator-facing tool surface"
last_verified: 2026-06-19
---

# MCP Tools — the operator-facing tool surface

The Pantheon MCP server exposes 28 tools that gods (and operators) call directly. This page is a categorized reference, not auto-generated. For the full schema of any tool, call it in your MCP client — the descriptions are part of the tool manifest.

## Categories

- [Memory and Knowledge](#memory-and-knowledge) — 9 tools
- [Messaging](#messaging) — 2 tools
- [God Operations](#god-operations) — 3 tools
- [Skills](#skills) — 3 tools
- [System Health](#system-health) — 3 tools
- [Conductor Workflows](#conductor-workflows) — 1 tool
- [Web and Research](#web-and-research) — 2 tools

## Memory and Knowledge

These tools read and write the Athenaeum and Ichor memory layers.

| Tool | Purpose | When to use |
|---|---|---|
| `athenaeum_walk` | Navigate the Athenaeum index tree | Starting a research task — find the codex for your topic |
| `athenaeum_read` | Read a specific file by path | After `athenaeum_walk` returns a path |
| `athenaeum_list_codexes` | List all codexes | Discovering what knowledge domains exist |
| `athenaeum_search` | FTS5 keyword search across the Athenaeum | Looking for content by keyword (not entity) |
| `athenaeum_graph_search` | Entity/relationship graph search | Looking for content by entity name |
| `athenaeum_write` | Write a file to the Athenaeum | Contributing structured knowledge or session artifacts |
| `ichor_retrieve` | Fused search across all memory backends | The default "find what I know about X" |
| `ichor_store` | Store content with auto-routing by category | Recording a fact, decision, insight, or commitment |
| `ichor_forget` | Delete an item by key | Retracting a stored item (use sparingly) |

**The most-used pair:** `ichor_retrieve` (read) + `ichor_store` (write). Together they cover 80% of memory operations.

## Messaging

| Tool | Purpose | When to use |
|---|---|---|
| `messaging_send` | Send a message to another god's inbox | Asynchronous handoff, notification, request, or alert |
| `messaging_check_inbox` | Check a god's inbox for unread messages | At the start of a session, or when a notification is expected |

**Important:** `messaging_send` is for *asynchronous* handoffs, not for asking a god a question in real time. For synchronous Q&A, use the chat interface.

## God Operations

| Tool | Purpose | When to use |
|---|---|---|
| `god_list` | List all registered gods with capabilities | Discovering who exists and what they can do |
| `ichor_brief` | Get a ranked context brief for a god | The canonical "what should I know right now?" query |
| `ichor_health` | Health check for all Ichor memory backends | Diagnosing memory issues |

## Skills

| Tool | Purpose | When to use |
|---|---|---|
| `skill_list` | List all available skills in the hub | Discovering what skills exist |
| `skill_info` | Get detailed info on a specific skill | Before invoking an unfamiliar skill |
| `skill_run` | Execute a skill by name with arguments | When a skill is a script (not a markdown body) |

For more on skills, see [Skills](02-skills.md) and [Making a Skill](04-making-a-skill.md).

## System Health

| Tool | Purpose | When to use |
|---|---|---|
| `system_health` | Check ChromaDB, Athenaeum, embedding service | First step in any "something is broken" diagnosis |
| `system_current_model` | Get the current model and provider for a session | Verifying a model change took effect |
| `hades_get_report` | Get the most recent Hades nightly consolidation report | Understanding what the nightly maintenance did |

## Conductor Workflows

| Tool | Purpose | When to use |
|---|---|---|
| `conductor_start_workflow` | Start a Conductor workflow instance | Triggering a multi-step workflow |

For more on Conductor, see the [Conductor documentation](https://github.com/Duskript/Pantheon/tree/main/conductor).

## Web and Research

| Tool | Purpose | When to use |
|---|---|---|
| `web_search` | Search the web | Operator-initiated research, not god-initiated |
| `web_extract` | Extract content from a URL | After `web_search` returns a result, or when given a URL directly |

## How to call a tool

### From chat

Just ask. The active god will pick the right tool:

```
> What do we know about ChromaDB?
```

The god will call `ichor_retrieve` (or `athenaeum_search`) and synthesize the result.

### From a build plan

In a build plan's "Tools" section, reference tools by name. The plan executor calls them at the appropriate step.

### Programmatically

```python
import json
import subprocess

# Call a tool via the MCP client of your choice
result = mcp_client.call(
    "ichor_store",
    {
        "key": "fact:chromadb-was-replaced",
        "content": "ChromaDB was replaced by SQLite FTS5 in P4d (2026-05).",
        "category": "fact",
    },
)
```

## Anti-patterns

- **Don't poll `messaging_check_inbox` in a tight loop.** The inbox is durable. Check at session start, or on demand, not on a timer.
- **Don't `ichor_store` volatile data.** Use session memory for things that should expire with the conversation. Ichor is for durable knowledge.
- **Don't use `athenaeum_write` to overwrite someone else's work.** The Athenaeum is a knowledge base, not a wiki to be casually edited. Propose, then write.
- **Don't `ichor_forget` to "clean up."** Forgetting destroys signal. If something is wrong, mark it as superseded, don't delete it.
- **Don't bypass `god_list` to talk directly to a specific god.** Let the routing table do its job. If you go direct, you skip the capability check.

## The five most-used tools

If you're new, these are the tools you'll use 90% of the time:

1. **`ichor_store`** — record things
2. **`ichor_retrieve`** — find things
3. **`ichor_brief`** — what's important right now
4. **`messaging_send`** — hand off to another god
5. **`messaging_check_inbox`** — see what came in

The remaining 23 tools are situational. Learn them as you need them.

## See also

- [Skills](02-skills.md) — skills vs MCP tools
- [Context Management](01-context-management.md) — how the memory tools fit together
- [Quickstart](00-quickstart.md) — the 5 commands to get started
