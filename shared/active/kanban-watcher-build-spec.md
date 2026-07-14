---
title: "Kanban Watcher — Spec"
type: "build-spec"
status: "draft — pending operator sign-off, ready to dispatch"
created: "2026-06-17"
created_by: "Thoth (per Konan, 2026-06-17, mid-conductor-ui-chain)"
owner: "Marvin (pure Python, no UI)"
priority: "P1 (operator's standing complaint: 'I am getting frustrated with having to constantly ask what is happening')"
related:
  - "pantheon/god-packages/shared-skills/plan-execution/SKILL.md"
  - "pantheon/god-packages/shared-skills/dispatch-monitoring/SKILL.md"
  - "athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md"
tags: ["kanban-watcher", "cron", "notifications", "infrastructure", "operator-experience", "P1"]
---

# Kanban Watcher — Build Spec

> **The operator's standing complaint (2026-06-16):** "I am getting frustrated with having to constantly ask what is happening." This build is the structural fix — the system tells the operator when state changes, instead of the operator polling the system.

---

## 1. What we're building

A small Python cron job that polls the kanban every 5 minutes, detects state changes, and pushes notifications to the operator's Telegram via the existing `god-notify` channel.

**It is NOT**:
- A real-time event stream (5-min latency is acceptable)
- A replacement for `notify-subscribe` (that's per-task, terminal-event-only; the watcher is broader)
- A god (no LLM, no persona, no inbox — it's a small Python script)
- A web UI (terminal output + Telegram messages)

**It IS**:
- A persistent cron that runs while the Pantheon is up
- A `~/.hermes/cron/kanban-watcher/` directory with a script + state file
- A state-diff engine (what changed since last poll?)
- A notification dispatcher (via `god-notify` or `hermes kanban notify-subscribe` pattern)

---

## 2. Build path

`/home/konan/.hermes/cron/kanban-watcher/` (per the cron convention, alongside other Pantheon cron jobs).

Files:
- `watcher.py` (~120 lines) — the main script
- `state.json` — last-seen snapshot (auto-managed)
- `README.md` — how to install, run, customize
- `tests/test_watcher.py` — unit tests for the diff logic
- A `hermes cron` entry to fire it every 5 min (per the existing cron pattern)

---

## 3. Spec — `watcher.py`

### 3.1 Entry point

```python
def main():
    """Poll kanban, diff against last snapshot, notify on changes."""
    last_state = load_state()  # from state.json
    current_state = fetch_kanban_snapshot()  # `hermes kanban list` parsed
    changes = diff(last_state, current_state)
    for change in changes:
        notify(change)
    save_state(current_state)
```

### 3.2 What counts as a "change"

| Event | Detection | Notification type | Notes |
|---|---|---|---|
| Task started (status: todo/ready → running) | Compare status field | info | "Marvin started Phase 0 (t_27babce6)" |
| Task completed (status: running → done) | Compare status field | info | "Phase 0 complete. QA gate next." |
| Task blocked (status: * → blocked) | Compare status field | warning | "Phase 0 blocked. Operator decision needed." |
| Task crashed (event: crashed) | Compare events list | error | "Marvin crashed on Phase 0. Reassign needed." |
| Task gave_up (event: gave_up) | Compare events list | error | "Worker gave up after 2 crashes. Reassign needed." |
| Heartbeat stale >10 min on running task | Check `last_heartbeat_at` field | warning | "Phase 0: no heartbeat in 12 min. Possible stall." |
| New task created | Compare task IDs | info (silent unless notable) | "New task t_XYZ created by thoth" |
| QA review fired (a "REVIEW" task appears) | Match by title pattern | info | "QA review fired for Phase 0 (t_27babce6)" |
| Operator-needed event (block, give_up) | Aggregate | warning | Aggregated "3 tasks need operator attention" |

**Default silence:** state changes that don't need operator action (e.g., a task running for 5 more min with no change) generate **no** notification. The watcher is *delta-based*, not *state-broadcasting*.

### 3.3 Notification format

**Telegram message format:**
```
🔔 Kanban Watcher

[task_title] ([task_id]) — [event_type]
[one-line context]

[link to hermes kanban show t_XYZ]
```

Example:
```
🔔 Kanban Watcher

✓ Phase 0 complete. QA gate next. (t_27babce6)
Marvin finished the conductor-ui foundation. Thoth review pending.

/home/konan/.hermes $ hermes kanban show t_27babce6
```

Example for a block:
```
⚠️ Kanban Watcher

⏸ Phase 1 blocked. (t_3d485846)
Iris's task loaded `build-spec-authoring` skill which her profile doesn't have.
Reassign to Marvin or strip the skill.

hermes kanban show t_3d485846
```

### 3.4 Notification routing

Default: send to `telegram:1460056890` (Konan's home channel).

Override via env var or config: `KANBAN_WATCHER_TARGET=telegram:OTHER_CHAT_ID`.

Use the existing god-notify MCP tool (`mcp_pantheon_messaging_send`) for delivery, OR shell out to `hermes messaging send`. **The watcher doesn't need to be a god itself** — it just delivers via the same channel.

**If the messaging system is down:** the watcher logs to a local file `~/.hermes/cron/kanban-watcher/output/` (per the cron output convention). The next successful delivery picks up the backlog.

### 3.5 State management

**`state.json` shape:**
```json
{
  "last_poll_at": "2026-06-17T01:30:00Z",
  "tasks": {
    "t_27babce6": {
      "status": "running",
      "assignee": "marvin",
      "title": "[conductor-ui] Phase 0 — Foundation",
      "last_heartbeat": "2026-06-17T01:28:00Z",
      "events_seen": [25, 26, 27, 28, 29, 30]
    }
  }
}
```

**State updates:** on every successful poll. The `events_seen` list is used to detect new events (e.g., `crashed`, `gave_up`).

**State bootstrap:** on first run, save the current state without notifying (no diff to compute).

### 3.6 Polling interval

Default: 300 seconds (5 min). Configurable via env var.

5 min is the right balance:
- Not so frequent that we spam the operator
- Not so rare that we miss state changes that matter
- 5 min of latency on a "task complete" notification is acceptable

### 3.7 Failure modes

- **`hermes kanban list` fails** (gateway down, etc.): log to output file, retry next poll
- **`messaging_send` fails** (Telegram down, etc.): log to output file, retry next poll
- **state.json corrupted**: back it up to `state.json.bak`, start fresh, log a warning
- **two watcher instances running** (e.g., user ran it twice): use a PID file lock to prevent
- **gateway conflict** (the watcher's own messages trigger kanban events): filter out events that originate from the watcher itself

---

## 4. Cron entry

Add to the user's `~/.hermes/cron/jobs.json` (or via `hermes cron` CLI):

```json
{
  "name": "kanban-watcher",
  "schedule": "*/5 * * * *",
  "command": "python3 /home/konan/.hermes/cron/kanban-watcher/watcher.py",
  "profile": "thoth",
  "output_dir": "/home/konan/.hermes/cron/output/kanban-watcher/"
}
```

This is the standard Pantheon cron pattern (per `pantheon-cron-operations` skill).

---

## 5. Verification gates

The watcher is "shipped" when:

- [ ] `watcher.py` runs without error on a clean state (first run, no notifications, just saves state)
- [ ] On second run, no notifications fire (no diff)
- [ ] A forced state change (manually edit state.json to mark a task as `done`, then run) produces a "task complete" notification to Telegram
- [ ] A simulated crash (manually inject a `crashed` event) produces an "error" notification
- [ ] A heartbeat-stale detection (modify `last_heartbeat_at` to be 11 min ago) produces a "warning" notification
- [ ] The cron entry is in `~/.hermes/cron/jobs.json` and fires every 5 min
- [ ] README explains installation, customization, troubleshooting
- [ ] Tests cover: empty state, no diff, single change, multiple changes, crash detection, heartbeat detection
- [ ] The watcher does NOT spam: 5 min of inactivity produces 0 notifications (state hasn't changed)

---

## 6. Constraints (operator-locked)

1. **No time estimates** in any plan or report. (Per operator-rules-cheatsheet.)
2. **No silent failures.** The watcher logs everything to `output/` and never silently drops a notification.
3. **No LLM calls.** The watcher is pure Python — no model, no inference, no personality. It's plumbing.
4. **Default target is the operator's home channel** (`telegram:1460056890`). Configurable, but the default is set.
5. **Sovereignty rule:** the watcher observes and notifies. It does not act on chain state. It does not promote tasks, unblock tasks, or reassign tasks. It's a *messenger*, not an *executor*.

---

## 7. Success criteria

The watcher is "done" when:

- Konan can stop asking "where are we at" and still get notified when state changes
- The watcher's notifications are **actionable** (operator knows what changed and what to do)
- The watcher's notifications are **not noisy** (5 min of silence = no notification, not "5 min of state: still running" spam)
- The watcher persists across sessions (the cron keeps it alive)
- The watcher is reusable for any future chain (not conductor-ui-specific)

---

## 8. References

- `athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md` — operator-locked rules
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — the dispatcher
- `pantheon/god-packages/shared-skills/dispatch-monitoring/SKILL.md` — the existing monitoring pattern (5 problem patterns)
- `hermes kanban watch` — the existing CLI watch (per-session only, not what we want)
- `hermes kanban notify-subscribe` — the existing per-task subscription (terminal events only)
- `mcp_pantheon_messaging_send` — the messaging channel for delivery
- `~/.hermes/cron/jobs.json` — the cron pattern (other Pantheon crons are here)
- `~/.hermes/profiles/thoth/skills/pantheon/pantheon-cron-operations/` — the cron-operations skill (how to register a new cron)

---

## 9. Out of scope

- **Real-time events** (sub-second latency) — too much infrastructure, not the right shape
- **A web UI** — out of scope; the Telegram notifications are the UI
- **A new god** — the watcher is a cron, not a god
- **Replacing `notify-subscribe`** — they coexist; `notify-subscribe` is per-task terminal events, the watcher is the general delta-stream
- **Multi-tenant** — the watcher is single-user (Konan). Multi-tenant is a future concern.

---

## 10. Sign-off

**Operator (Konan) review needed on:**

1. **Polling interval** — 5 min default. **Confirm or change.**
2. **Default target** — `telegram:1460056890`. **Confirm or change.**
3. **Scope of "changes"** — the table in §3.2 lists what triggers a notification. **Add/remove events.**
4. **Notification format** — the Telegram message format in §3.3. **Approve or revise.**
5. **Persistence model** — `state.json` in the cron dir, auto-managed. **Approve or change.**

---

## 11. Post-ship follow-ups

Once the watcher ships:
- Thoth updates the dispatch-monitoring skill to reference the watcher (so future chains get the notifications automatically)
- The conductor-ui chain's notifications (already subscribed via `notify-subscribe`) coexist with the watcher's delta stream
- Hephaestus's build plan for the user-context-engine includes a "kanban-watcher integration test" — verify the watcher fires on the 6 new phase tasks as they spin up

---

**Marvin — when you read this, the next step is to:**
1. Read the existing `pantheon-cron-operations` skill to understand the cron pattern
2. Build `watcher.py` per the spec
3. Add the cron entry
4. Test with simulated state changes
5. Report back with: path to the script, test results, an example notification, the cron schedule

**The watcher is a P1 (the operator's standing complaint). The kanban-watcher + the user-context-engine concept are independent workstreams — both can ship in parallel.**
