---
title: "Quickstart — 5 commands to get started"
last_verified: 2026-06-19
audience: new operators
---

# Quickstart — 5 commands to get started

This page covers the 5 commands you actually need to start. There are dozens more, but these are the ones you'll use on day one.

## 1. Start Pantheon

```bash
# Start the MCP server (background, persists across sessions)
systemctl --user start pantheon-mcp

# Or if you're not using systemd
python3 ~/pantheon/pantheon-core/mcp_server.py &
```

You should see the MCP server listening on `http://localhost:8010`. If it doesn't, check `~/.local/share/pantheon/logs/mcp_server.log`.

## 2. Talk to a god

Open any MCP client (Hermes, Claude Code, AionUi) connected to the Pantheon MCP server. Then:

```
> Talk to Thoth about [your topic]
```

The god with the matching capability will respond. If you don't know which god to talk to, say so — Hermes routes by default.

> **Tip:** the god roster is at `gods/gods.yaml`. Each god has a `description` and a list of `capabilities`. Look there first.

## 3. Check a god's inbox

When another god has something to tell you, they leave a message. Check any god's inbox:

```
> Check Thoth's inbox
```

Or via the MCP tool:

```python
messaging_check_inbox(god_name="thoth", mark_read=True)
```

Messages include notifications, requests, handoffs, and alerts. The inbox is *pull-based* — a god won't interrupt you, they wait until you ask.

## 4. Record a decision

When you make an operator-locked decision (a choice that other operators/gods need to follow), record it:

```
> Record this decision: [your decision text]
```

Or via the MCP tool:

```python
ichor_store(
    key="decision:YYYY-MM-DD--NNN--short-slug",
    content="The decision text, with rationale and reversibility.",
    category="decision",
)
```

Decisions are append-only. They live at `~/pantheon/shared/decisions/konan/`. Every operator-locked decision goes there — the cost of recording is 30 seconds, the cost of not recording is re-litigating the same choice in 3 months.

## 5. Monitor god state

To see what's in flight across all gods:

```
> What are the gods working on?
```

Or via the MCP tool:

```python
ichor_brief(god_name="hermes", limit=20)
```

This returns a ranked list of recent events for that god, scored by priority, freshness, and confidence. The brief is the canonical "what should I know right now?" query.

## What you just did

You started the system, talked to a god, checked an inbox, recorded a decision, and surveyed the state. That covers ~80% of what operators do day-to-day.

The remaining 20% — building skills, spawning new gods, configuring cron, debugging stalls — is in the other pages of this best-practices guide.

## When to use which

| You want to... | Use this | Page reference |
|---|---|---|
| Ask a question | Talk to a god | [Skills](02-skills.md) |
| Get a god to remember something | `ichor_store` | [Context Management](01-context-management.md) |
| Find something you discussed before | `ichor_retrieve` or `session_search` | [Context Management](01-context-management.md) |
| Hand off work to another god | `messaging_send` | [MCP Tools](09-mcp-tools.md) |
| Make a god an offer it can't refuse | `messaging_send` with `priority="urgent"` | [MCP Tools](09-mcp-tools.md) |
| Lock in a decision | `ichor_store` with `category="decision"` | [Decision Log](08-decision-log.md) |

## Anti-patterns

- **Don't use `messaging_send` to ask a god a question.** That's what the chat interface is for. `messaging_send` is for *asynchronous handoffs*, not synchronous Q&A.
- **Don't check inboxes more than once per session.** Inboxes are append-only and notifications are durable. Re-checking doesn't add information.
- **Don't skip recording decisions.** "I'll write it down later" is how operator-locked decisions get lost.
- **Don't use `ichor_store` for transient state.** It's for durable knowledge. Use session memory for things that should expire with the conversation.

## See also

- [Context Management](01-context-management.md) — what memory, Ichor, and the Athenaeum actually do
- [MCP Tools](09-mcp-tools.md) — the full operator-facing tool surface
- [Decision Log](08-decision-log.md) — how to record decisions well
