---
title: "MCP Tools — the operator-facing tool surface"
last_verified: 2026-09-01
---

# MCP Tools — the operator-facing tool surface

As of 2026-09-01, `pantheon-core/mcp_server.py` registers **35 MCP tools** with FastMCP. This page is a human-maintained guide to that current source inventory; tool names and counts can change between releases, so verify the live manifest when upgrading.

## Categories

- [Athenaeum and Ichor](#athenaeum-and-ichor) — 19 tools
- [Messaging](#messaging) — 2 tools
- [Gods and reports](#gods-and-reports) — 2 tools
- [Skills](#skills) — 3 tools
- [System](#system) — 2 tools
- [Conductor](#conductor) — 1 tool
- [Pantheon index and paths](#pantheon-index-and-paths) — 6 tools

## Athenaeum and Ichor

These tools cover file-backed knowledge, FTS5 memory, goals, gates, graph operations, and entity extraction.

| Tool | Purpose |
|---|---|
| `athenaeum_search` | FTS5 keyword search over Athenaeum/Ichor reference data |
| `athenaeum_read` | Read a file by path relative to the Athenaeum root |
| `athenaeum_walk` | Browse the Athenaeum index structure |
| `athenaeum_write` | Write or overwrite a file in the Athenaeum |
| `athenaeum_list_codexes` | List Athenaeum Codexes, optionally with counts |
| `ichor_brief` | Ranked zero-query context brief |
| `ichor_ledger` | Structured current-state ledger for a god |
| `ichor_retrieve` | Fused retrieval across FTS5, vector, graph, and event backends |
| `ichor_store` | Store memory and route it by category |
| `ichor_forget` | Delete an Ichor item by backend-qualified key |
| `ichor_goal` | Add, list, inspect, update, complete, pause, inject, or summarize strategic goals |
| `ichor_health` | Check Ichor memory backends |
| `ichor_gates` | Run state, logic, phase-detection, handoff, or pipeline-health gates |
| `ichor_forge` | Analyze gate interventions and propose harness adjustments |
| `ichor_graph_query` | Run a multi-hop entity/relationship graph query |
| `ichor_l2_stats` | Read L2 entity/relationship extraction statistics |
| `ichor_extract_entities` | Run one incremental L2 extraction pass |
| `ichor_l2_finalize` | Finalize provisional L2 entities and relationships |
| `athenaeum_graph_search` | Search the WARM entity/relationship table |

`athenaeum_search` currently uses SQLite FTS5 and reference tables; it is not a ChromaDB search wrapper. `ichor_retrieve` is the broader fused retrieval surface.

## Messaging

| Tool | Purpose |
|---|---|
| `messaging_send` | Write an asynchronous notification, request, alert, or handoff to a god's inbox |
| `messaging_check_inbox` | Return unread messages for a god; `mark_read=True` mutates the returned message files |

The MCP messaging inbox is file-backed under `~/pantheon/gods/messages/<god>/`. It is not a synchronous Q&A channel and should not be polled in a tight loop.

## Gods and reports

| Tool | Purpose |
|---|---|
| `god_list` | Read the registered god roster from `~/pantheon/gods/gods.yaml` |
| `hades_get_report` | Read the latest or a specified Hades consolidation report |

## Skills

| Tool | Purpose |
|---|---|
| `skill_list` | List executable shared skills in the Pantheon skills hub |
| `skill_info` | Inspect a shared skill's manifest and arguments |
| `skill_run` | Execute a shared skill by name with arguments |

These are distinct from Hermes Markdown skills loaded with `skill_view` or `/<skill-name>`. Inspect an executable skill before running it, especially when it has side effects.

## System

| Tool | Purpose |
|---|---|
| `system_health` | Check Pantheon Ichor vector/event state, Athenaeum filesystem, and embedding service |
| `system_current_model` | Report the configured model/provider for a session or active profile |

## Conductor

| Tool | Purpose |
|---|---|
| `conductor_start_workflow` | Start a Conductor v2 workflow instance and mint a workflow ID |

Conductor's wider lifecycle has additional endpoints outside this MCP server; consult the Conductor documentation for handoff, acknowledgement, and workflow-state operations.

## Pantheon index and paths

| Tool | Purpose |
|---|---|
| `pantheon_path` | Resolve a canonical path for a Pantheon artifact type |
| `pantheon_index_refresh` | Rebuild the Pantheon System Index |
| `pantheon_search` | Full-text search indexed files, tools, skills, cron jobs, gods, and workflows |
| `pantheon_locate` | Locate a known component by name or path |
| `pantheon_list` | List indexed components by category |
| `pantheon_index_status` | Show index location, size, timestamp, and category counts |

Run `pantheon_index_refresh` after adding indexed files, tools, skills, cron jobs, gods, or workflows if the index is expected to reflect the change immediately.

## How to call a tool

### From chat

Ask the active agent for the outcome you need:

```
> What do we know about SQLite FTS5 memory retrieval?
```

The agent can select `ichor_retrieve`, `athenaeum_search`, or a graph/index tool based on the question.

### From a build plan

Reference the tool name in the plan's Tools section. The executor remains responsible for passing the required arguments and handling side effects.

### Programmatically

Use the MCP client library appropriate to your host:

```python
result = mcp_client.call(
    "ichor_store",
    {
        "key": "fact:fts5-memory",
        "content": "The current Athenaeum keyword path uses SQLite FTS5.",
        "category": "fact",
    },
)
```

Always inspect the returned envelope. In particular, `athenaeum_write`, `messaging_send`, `skill_run`, workflow start, and memory mutation tools have side effects.

## Anti-patterns

- **Don't rely on the count in this page as a protocol guarantee.** Discover the live MCP manifest after a release or server change.
- **Don't poll `messaging_check_inbox` in a tight loop.** Check at session start or when a message is expected.
- **Don't `ichor_store` volatile data.** Ichor is for durable memory; use session context for expiring state.
- **Don't confuse `ichor_store(category="decision")` with the Markdown decision log.** It writes an FTS5 event; important decisions also belong in `shared/decisions/INDEX.md`.
- **Don't `ichor_forget` to clean up ordinary noise.** Prefer a correction or superseding event when history matters.
- **Don't use `athenaeum_write` as a path escape hatch.** It is rooted at the Athenaeum; use the canonical Pantheon path and file workflow for shared decisions or plans.
- **Don't run `skill_run` or workflow mutations without checking the arguments and side effects.**

## The most-used tools

For routine memory and coordination, start with:

1. `ichor_retrieve` — find durable knowledge
2. `ichor_store` — record durable knowledge
3. `ichor_brief` — see ranked current context
4. `messaging_send` — send an asynchronous handoff or notification
5. `messaging_check_inbox` — inspect unread messages

Use the remaining tools when the task requires a specific subsystem.

## See also

- [Skills](02-skills.md) — Markdown skills vs executable skills
- [Decision Log](08-decision-log.md) — how durable decisions are recorded
- [Quickstart](00-quickstart.md) — the five operator actions
