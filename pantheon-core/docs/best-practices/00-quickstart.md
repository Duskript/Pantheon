---
title: "Quickstart — 5 commands to get started"
last_verified: 2026-09-01
audience: new operators
---

# Quickstart — 5 commands to get started

This page covers the five operator actions needed to start using Pantheon. The examples below match the current repository layout and MCP server implementation, verified 2026-09-01.

## 1. Start Pantheon

```bash
# Recommended: start the installed user service
systemctl --user start pantheon-mcp.service

# Or run the server manually from the repository
cd ~/pantheon/pantheon-core
python3 mcp_server.py --port 8010
```

The HTTP server binds to loopback by default and exposes the Streamable HTTP MCP endpoint at `http://127.0.0.1:8010/mcp`. A bare GET to that endpoint returns a transport hint; MCP clients should use their normal Streamable HTTP negotiation.

The bundled systemd unit sends stdout and stderr to the user journal:

```bash
journalctl --user -u pantheon-mcp.service -n 50 --no-pager
```

A manually backgrounded process (`&`) is not a persistent service. Use systemd when the server must survive logout or reboot.

## 2. Talk to a god

Pantheon MCP exposes knowledge, memory, messaging, and workflow tools; it does not itself provide a general chat router. Use your MCP client or Hermes profile to talk to a god, then let that client select the Pantheon tools it needs.

For example, in a Hermes session:

```
> Talk to Thoth about [your topic]
```

The registered roster is in `~/pantheon/gods/gods.yaml`. It contains each god's display name, role, description, capabilities, and status. The roster is useful for choosing a god, but the MCP server does not automatically route an arbitrary chat message by capability.

## 3. Check a god's inbox

The legacy inter-god messaging tools use file-backed inboxes under `~/pantheon/gods/messages/<god>/`:

```
> Check Thoth's inbox
```

Or via the MCP tool:

```python
messaging_check_inbox(god_name="thoth", mark_read=False)
```

`mark_read` defaults to `False`. Set it to `True` only after reviewing the returned messages; that changes the message files. The tool returns unread notifications, requests, handoffs, and alerts. Do not poll it in a tight loop—check at session start or when a message is expected.

## 4. Record a decision

When you make an operator-locked decision (a durable choice that other operators or gods must follow), create a decision file in `~/pantheon/shared/decisions/` and append its entry to `INDEX.md`:

```text
> Record this decision: [your decision text]
```

For memory retrieval, you can also record the decision as an Ichor event:

```python
ichor_store(
    key="decision:2026-09-01-short-slug",
    content="The decision text, with rationale and reversibility.",
    category="decision",
)
```

Important: `ichor_store(category="decision")` writes an event to Ichor's FTS5-backed memory; it does not create the Markdown decision file or update the decisions index. See [Decision Log](08-decision-log.md) for the two records and their roles.

## 5. Monitor god state

To see ranked recent context across the Pantheon:

```python
ichor_brief(god_name="", limit=20)
```

To scope the brief to one god, pass its roster name, for example `god_name="thoth"`. The brief ranks events using priority, freshness, confidence, and repetition. `ichor_ledger` is the alternative when you want a structured state ledger rather than a ranked event list.

## What you just did

You started the MCP server, selected a god through your client, inspected an inbox, recorded a decision in the durable paths, and queried current state. That covers the common operator loop.

The remaining topics—context management, skills, god creation, workflow operations, and debugging—are covered by the other pages in this guide.

## When to use which

| You want to... | Use this | Page reference |
|---|---|---|
| Ask a question | Talk to a god through your client | [Skills](02-skills.md) |
| Get a god to remember something | `ichor_store` | [MCP Tools](09-mcp-tools.md) |
| Find something you discussed before | `ichor_retrieve` or `session_search` | [MCP Tools](09-mcp-tools.md) |
| Hand off work to another god | `messaging_send` | [MCP Tools](09-mcp-tools.md) |
| Lock in a decision | Decision Markdown + `INDEX.md`, optionally `ichor_store(category="decision")` | [Decision Log](08-decision-log.md) |
| Inspect current state | `ichor_brief` or `ichor_ledger` | [MCP Tools](09-mcp-tools.md) |

## Anti-patterns

- **Don't treat the MCP server as a chat router.** It exposes tools; your client or Hermes profile provides the conversational interface and routing behavior.
- **Don't use `messaging_send` for synchronous questions.** Use the chat interface for Q&A and messaging for asynchronous handoffs or notifications.
- **Don't poll `messaging_check_inbox` in a tight loop.** Inboxes are durable; check at session start or when a notification is expected.
- **Don't confuse Ichor memory with the decision-file audit trail.** Store important decisions in both places when you need searchable recall and a human-readable append-only record.
- **Don't use `ichor_store` for transient state.** Use session context for information that should expire with the conversation.

## See also

- [MCP Tools](09-mcp-tools.md) — the current operator-facing tool surface
- [Decision Log](08-decision-log.md) — how to record decisions well
