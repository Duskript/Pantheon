---
name: dispatch-monitoring
description: "Use when Hephaestus is monitoring a chain in flight — watching for stalled tasks, blocked-too-long, repeated crashes, missed QA reviews, or any chain state that needs operator attention. This is the watchdog. Catches the stalls before they become silent failures."
version: 1.0.1
tags: [orchestration, monitoring, watchdog, dispatch, kanban, hephaestus]
---

# Dispatch Monitoring — The Watchdog

> **The skill that watches in-flight chains and catches problems before they become silent failures.** A chain that's stalled is a chain that's silently failing. Hephaestus's job is to catch the stall, escalate the blocker, and keep the chain moving.

## When to use this skill

Load this skill whenever:

- A chain is in flight (after plan-execution dispatches it)
- Hephaestus's daily check (per the rework design — "watches in-flight chains")
- A task has been `running` for longer than expected
- A task has been `blocked` for longer than expected
- A QA review has returned `block` (escalation needed)
- The operator asks "what's the status of chain X"

**Don't use this skill for:**

- Dispatching a new chain (use `plan-execution`)
- Reviewing code (that's Thoth's job)
- Reading a plan (just read the file)
- Modifying a task (use `hermes kanban` directly with the appropriate command)

## The single most important principle (operator correction 2026-06-16)

**Do NOT wait for the operator to ask "where are we at."** When a chain is in flight, the watchdog surfaces state changes proactively — at the top of every turn, not when asked. Konan explicitly corrected this after the conductor-ui dispatch:

> "I am getting frustrated with having to constantly ask what is happening."

The watchdog reports **routine state changes**, not just escalations. The operator should not have to ask "where are we at?" to know the chain is moving. Surface state as a structured status, not as silence-until-something-breaks.

Concretely, on every state change in a monitored chain:

- **State change** (task starts, completes, blocks, becomes ready) → report it: "[Chain: project] [Task: t_xxx] [Event: state] — [one line of context]."
- **Healthy progress** (file produced, heartbeat active, plan on track) → report it so the operator doesn't wonder
- **Routine completion** (a code task done, QA review fires) → report: "[Chain: project] Task t_xxx done. QA review t_yyy fires. Phase N status: M of K complete."
- **Routine phase progress** (e.g., "3 of 6 phase-0 tasks done") → report at each transition.
- **Escalation** (one of the 5 problem patterns below) → report per the existing response rules AND include the chain's overall status (so the operator sees the state in context of the chain, not just the problem).

**Periodic status digest.** If the chain is in flight and no state change has fired a report in the last 10 minutes, the watchdog emits a "still moving" status: "[Chain: project] Status: M of K tasks done, J QA reviews pass, L blocked. Last event: [most recent] at HH:MM. No action needed." The operator gets a heartbeat even if nothing's wrong.

**Anti-pattern.** Reporting only on escalation. The operator polls. The operator is frustrated. The chain is fine but the operator can't tell because the watchdog is silent. The fix: surface state changes and periodic digests, not just problems.

**What doesn't change.** The 5 problem patterns still detect the same way. The responses still escalate the same way. The "monitor every 5 minutes" cadence still holds. The principle adds a "report routine state" step on top of the existing "report escalations" behavior.

**Where this fits in the procedure.** It's Step 3.5: "Report routine state changes" sits between Step 3 (detect the 5 patterns) and the existing escalation logic. The watchdog does both: surface state AND escalate problems.

**Where to check the chain state:**

- `hermes kanban show <task_id>` for the active task
- `ls <workspace-dir>` for the actual files being produced (this is the truth the kanban status doesn't always show — kanban status can say "running" while the worker is mid-stream producing files; the file count is the real progress signal)
- `hermes kanban show <task_id> | tail -20` for recent heartbeats and events

The lesson: **the workspace files are the ground truth, the kanban status is the heartbeat.** Watch both. The kanban says "running 30 min" — the workspace says "10 source files produced, 1 file from the spec missing" — together they tell you "the worker is on task 4 of 9 and the next deliverable is the ledger_client." That's actionable. Either alone is incomplete.

## The kanban-watcher cron (proactive notification, persistence)

The operator doesn't sit in a chat session watching the chain. The kanban-watcher is a small cron-driven script that polls `hermes kanban list` and pushes notifications on state changes. It runs in the background and outlives any individual session.

**Location:** `~/.hermes/cron/kanban-watcher/`

**Cadence:** every 5 minutes

**Inputs:** all in-flight chains (any task with status `running` or `blocked` or recent transitions)

**Outputs:** Telegram (or other configured channel) via `messaging_send` to the operator's chat

**Detection rules (in priority order):**

1. **Phase boundary** — last task in a phase transitions to `done`; the next phase's owner is notified
2. **Worker crash** — task transitions to `crashed` / `gave_up`; the unblock/reassign action is included
3. **Stall** — task has been `running` for >10 min without a new heartbeat
4. **Phantom-skill crash** — worker logs `Error: Unknown skill(s):`; the SQLite-strip fix is included
5. **QA verdict** — review task transitions to `pass` / `needs_changes` / `block`
6. **Operator gate** — task transitions to `blocked`; the unblock command is included

**Why a cron, not a session-loop:** sessions end. The chain doesn't. The operator wants persistent visibility. The cron survives session boundaries; the chat session doesn't.

**Why a cron, not `hermes kanban watch`:** `watch` is a foreground streaming command (per the CLI help: "Live-stream task_events to the terminal"). It doesn't survive across sessions and doesn't route to Telegram. A cron + notification push is the right shape for the operator's use case.

## How to use it (the procedure)

### Step 0: Identify the chain to monitor

Every chain has a parent task (or a set of parent tasks if it's a complex multi-parent chain). The chain is identified by:

- **Project name** — the kanban task title includes `[<project>]`
- **Root task** — the t5 of the build-plan-orchestrator chain, or the explicit root task for ad-hoc chains
- **Worker profiles** — Marvin, Iris, Thoth, etc. (per the dispatch rules)

To find the chain:

```bash
hermes kanban list --assignee <god> --status running --json | jq '.[] | select(.title | contains("[<project>]"))'
```

Or by root task:

```bash
hermes kanban list --parent <root-task-id> --json
```

### Step 1: Take a snapshot

For the chain, get a structured snapshot:

```bash
hermes kanban stats --board <project>  # if the chain uses a dedicated board
hermes kanban list --json | jq '[.[] | select(.title | contains("[<project>]"))] | {by_status: group_by(.status), by_assignee: group_by(.assignee), oldest: min_by(.created_at)}'
```

**The snapshot includes:**

- Tasks by status (`ready`, `running`, `blocked`, `done`, `failed`, `cancelled`)
- Tasks by assignee (which god has how many tasks)
- Oldest task (which task has been in flight longest)
- Total tasks in the chain
- Tasks completed vs. remaining
- Average time-to-completion (if available)

### Step 2: Detect the 5 problem patterns

The watchdog looks for 5 specific patterns. Each pattern has a detection rule and a response.

#### Pattern 1: Stalled task

**Definition:** a task that has been `running` for longer than its `max-runtime` without completing.

**Detection:**

```bash
# Find tasks running for >2x their max-runtime
hermes kanban list --status running --json | jq '.[] | select(.max_runtime != null) | {id, title, assignee, started_at, max_runtime, age_minutes: ((now - (.started_at | fromdate)) / 60)} | select(.age_minutes > (.max_runtime * 2))'
```

**Response:**

1. **First offense** — notify the assignee: "Task <id> has been running for <N> min, max-runtime is <M> min. Are you still working? Need help?"
2. **Second offense (after 30 min)** — reclaim the task: `hermes kanban reclaim <task-id>`
3. **Third offense** — escalate to the operator: "Task <id> has stalled <N> times. Should we cancel, re-dispatch, or wait?"

#### Pattern 2: Blocked-too-long

**Definition:** a task that has been `blocked` for more than 24 hours without being unblocked.

**Detection:**

```bash
hermes kanban list --status blocked --json | jq '.[] | {id, title, blocked_at, age_hours: ((now - (.blocked_at | fromdate)) / 3600)} | select(.age_hours > 24)'
```

**Response:**

1. **Check the block reason** — was the operator asked a question? Did a dependency fail?
2. **If the operator was asked** — re-ping the operator with the question (don't assume they saw it)
3. **If a dependency failed** — escalate to the dependency's owner
4. **If the block is unclear** — notify the operator: "Task <id> has been blocked for <N> hours. Reason: <reason>. Need a decision."

#### Pattern 3: Repeated crashes

**Definition:** the same task has been re-dispatched (claimed → failed → re-claimed) 3 or more times.

**Detection:**

```bash
sqlite3 ~/.hermes/kanban.db "SELECT task_id, COUNT(*) as crash_count FROM task_events WHERE event_type = 'failed' AND task_id = '<id>' GROUP BY task_id HAVING crash_count >= 3;"
```

**Response:**

1. **Stop the re-dispatch loop** — mark the task as `needs_intervention`
2. **Read the failure logs** — `hermes kanban tail <task-id>` to see what went wrong
3. **Diagnose** — is it a flaky environment, a code bug, a missing dependency, a worker skill issue?
4. **Escalate to the operator** — "Task <id> has crashed <N> times. Diagnosis: <what>. Options: <fix-it, simplify-it, cancel-it>."

#### Pattern 4: Missed QA reviews

**Definition:** a code-producing task is `done` but its Thoth review follow-on is not.

**Detection:**

```bash
# Find code-producing tasks (done) without a review follow-on
sqlite3 ~/.hermes/kanban.db "
SELECT t1.id, t1.title, t1.status
FROM tasks t1
WHERE t1.title LIKE 'CREATE%' OR t1.title LIKE 'MODIFY%'
  AND t1.status = 'done'
  AND NOT EXISTS (
    SELECT 1 FROM task_links
    WHERE parent_id = t1.id AND title LIKE '%review%'
  );"
```

**Response:**

1. **Create the missing review task** — using the same shape as the auto-generated ones
2. **Notify Thoth** — the review is queued
3. **Don't advance the phase** — the phase gate is not passed until the review passes

#### Pattern 5: Phase gate not run

**Definition:** all tasks in a phase are `done` + all QA reviews are `pass`/`pass_with_notes`, but no phase gate task has been run.

**Detection:**

```bash
# Find phases where all work is done but no gate task exists
sqlite3 ~/.hermes/kanban.db "
SELECT phase
FROM tasks
WHERE status NOT IN ('done', 'cancelled')
GROUP BY phase
HAVING COUNT(*) = 0;"
```

**Response:**

1. **Create the missing phase gate task** — per the phase-boundary-shape standard
2. **Run the verification command** — confirm the gate is technically passed
3. **Report to the operator** — "Phase <N> complete. Gate: pass. Awaiting sign-off."

### Step 3: Report to the operator

The watchdog reports to the operator:

1. **On detection of a pattern** — what was detected, what was done
2. **On escalation** — what's the blocker, what are the options
3. **On resolution** — what was fixed, the chain is moving again

The report format:

```
[Chain: <project>] [Pattern: <pattern-name>]
- Detection: <what was detected>
- Action taken: <what Hephaestus did>
- Status: <passing | needs-decision | escalated>
- Next: <what happens next>
```

### Step 4: Update the chain state

When the watchdog takes action, update the chain's state:

- **Stall reclaim** — log the reclaim event
- **Re-dispatch** — log the re-dispatch with a new idempotency key
- **Escalation** — create a `needs_intervention` task, link it to the parent

The state is in the kanban DB; the watchdog doesn't need a separate state file.

### Step 5: Continue monitoring

The watchdog loop runs continuously while a chain is in flight. The loop:

```
for each chain in flight:
  take snapshot
  detect 5 patterns
  for each detected pattern:
    respond per the pattern
  if escalation needed:
    notify operator
  sleep 5 min  # don't hammer the DB
```

When a chain ships or is cancelled, the watchdog stops monitoring it.

## Worked example

The conductor-ui build v1.1 chain (after dispatch):

- **t1, t2 done** — no monitoring needed
- **t3, t4 blocked** — watchdog waits for operator unblock
- **Phase 0 in flight** — watchdog watches for stalls, missed reviews, gate not run
- **Phase 0 complete** — watchdog creates the gate task, runs verification, reports to operator

If Marvin's P0c (scaffold) task stalls:
- **Detection** — running for >2x max-runtime
- **First response** — notify Marvin: "P0c has been running for <N> min, max-runtime is <M> min. Need help?"
- **Second response** — reclaim, re-dispatch with same idempotency key
- **Third response** — escalate to operator

## Pitfalls

**Don't ignore the stalled task.** A stalled task is a silent failure. The watchdog catches it before it becomes a chain block.

**Don't auto-re-dispatch without diagnosing.** Re-dispatching the same broken task 3 times in a row = loop. The watchdog diagnoses, then re-dispatches only if the fix is clear.

**Don't skip the operator notification.** The watchdog's job is to escalate, not to decide. The operator decides.

**Don't monitor chains that are not in flight.** A done chain doesn't need monitoring. A draft plan doesn't need monitoring. Only in-flight chains are monitored.

**Don't monitor too often.** Every 5 minutes is fine. Every 10 seconds hammers the DB. The balance is "catches stalls within 5-10 minutes" vs. "doesn't waste resources."

**Don't report only on escalation.** The "proactive operator updates" principle (above) is the operator-locked default. Watchdog silence is a bug, not a feature. The operator wants to know the chain is moving.

## Verification gates

Dispatch-monitoring is "working" when:

- [ ] Every in-flight chain is monitored at least every 5 minutes
- [ ] All 5 patterns are detected correctly (no false positives, no missed cases)
- [ ] Each pattern's response is followed
- [ ] The operator is notified of escalations
- [ ] **The operator is notified of routine state changes** (the proactive-updates principle, operator-locked 2026-06-16)
- [ ] The chain state is updated after each action
- [ ] False alarm rate is < 5% (we're not paging the operator for nothing)

## See also

- `Codex-Pantheon/design/standards/kanban-task-shape.md` — the task shape
- `Codex-Pantheon/design/standards/phase-boundary-shape.md` — the phase boundary
- `Codex-Pantheon/design/standards/qa-gate-rubric.md` — the review rubric
- `Codex-God-Hephaestus/command-reference.md` — the Hermes CLI reference
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — the dispatching counterpart
- `pantheon/god-packages/shared-skills/kanban-orchestrator/SKILL.md` — the dispatcher

## Changelog

### v1.0.1 (2026-06-16)

- **Added "the single most important principle" section: do NOT wait for the operator to ask "where are we at."** Konan explicitly corrected this after the conductor-ui dispatch: "I am getting frustrated with having to constantly ask what is happening." The new default is: check the chain at the top of every turn while a worker is running; surface state changes AND healthy progress (file produced, heartbeat active, plan on track) so the operator doesn't wonder. The lesson is: **the workspace files are the ground truth, the kanban status is the heartbeat.** Watch both. The kanban says "running 30 min"; the workspace says "10 source files produced, 1 file from the spec missing"; together they tell you "the worker is on task 4 of 9 and the next deliverable is the ledger_client." That's actionable. Either alone is incomplete.
- **Added the kanban-watcher cron pattern.** Operators don't sit in chat sessions watching the kanban. The watcher is a small cron-driven script that polls `hermes kanban list` every 5 min, diffs against the last snapshot, and pushes notifications on state changes. It survives session boundaries. The full pattern (script, crontab, dedup logic, notification priority rules) is in `references/kanban-watcher-cron.md`. The "why a cron, not `hermes kanban watch`" rationale: `watch` is a foreground streaming command (per CLI help: "Live-stream task_events to the terminal"), doesn't survive across sessions, doesn't route to Telegram. The cron + notification push is the right shape.
- **The "stalled task" detection threshold was tightened.** Previous version said "watch for running tasks that exceed their max-runtime." This version adds a separate, lower threshold: a worker with no heartbeat in 10+ min is the first signal of a real stall. Below 10 min, the noise-vs-signal ratio is too high (workers pause for tool calls).
- **Added a "report on healthy progress" pattern.** Previous version was 100% problem-detection ("stalled, blocked, crashed, missed, gate-not-run"). This version adds the 8 surface-on-every-turn patterns: state changes, healthy progress, stalls, worker crashes, QA gate fires, phase boundaries, operator decisions needed, skill-resolution errors. The new piece is #2: don't only surface problems; surface motion.
- `references/kanban-watcher-cron.md` — the proactive notification cron (operator correction 2026-06-16)
