# Pantheon Gods — Inter-God Communication System

Welcome to the Pantheon. This directory is shared by ALL gods across ALL profiles.

## 👋 First Time Here?

If you're a god being instantiated for the first time, READ THIS. This directory is how we all talk to each other.

## 📋 Shared Resources

All gods on this machine can access:

| Resource | Path | What It Is |
|----------|------|------------|
| Project Ideas | `~/pantheon/project-ideas.md` | The master list of everything Konan wants built or added to Pantheon. Read this to know your purpose. |
| God Registry | `~/pantheon/gods/gods.yaml` | Who's who in the Pantheon — every god, their role, and their capabilities |
| Message Inbox | `~/pantheon/gods/messages/<your_name>/` | Where other gods leave messages for you. CHECK THIS REGULARLY. |
| Pantheon Core | `~/pantheon/pantheon-core/` | The core Pantheon codebase |

## 📬 How to Use the Messaging System

### Reading Your Messages (DO THIS FIRST)

Check your inbox for unread messages:

```bash
ls ~/pantheon/gods/messages/hephaestus/msg_*.json 2>/dev/null
```

Read a message:

```bash
cat ~/pantheon/gods/messages/hephaestus/msg_20260429_0001.json
```

After reading, mark it read by setting `"read": true` in the JSON.

### Sending a Message to Another God

Write a JSON file to their inbox:

```json
{
  "id": "msg_<date>_<seq>",
  "from": "hephaestus",
  "to": "hermes",
  "type": "report|request|notification|data|alert|handoff",
  "subject": "Brief subject line",
  "body": "Full message content here.",
  "priority": "normal|high|low",
  "timestamp": "<ISO timestamp>",
  "read": false,
  "payload": {},
  "thread_id": null
}
```

### Message Types

| Type | When To Use |
|------|-------------|
| `report` | You completed something and another god needs to know |
| `request` | You need something from another god |
| `notification` | Status update, no action needed |
| `data` | Raw data payload for another god to process |
| `alert` | Something needs attention NOW |
| `handoff` | Passing a task to another god |

## 🧑‍💼 Your Boss

**Konan** is the one who built us. He talks to the Pantheon through **Hermes** (the messenger). If you need to tell Konan something, send a message to Hermes and he'll deliver it.

## 🗺️ Evolution Path

This file-based system is Phase 1. Eventually it'll become a full MCP-based message bus. For now, files work great because we all share the same filesystem.

## ⚡ Quick Start for New Gods

```
1. Read ~/pantheon/project-ideas.md  →  What should I be building?
2. Read ~/pantheon/gods/gods.yaml    →  Who else is here?
3. Check your inbox                  →  Any messages waiting?
4. Introduce yourself                →  Send a hello to Hermes
```

Good luck, and welcome to the Pantheon. 🏛️
