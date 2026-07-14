# hephaestus-watchdog — Dispatcher's perspective

> Why this matters for `plan-execution`: the watchdog closes the loop on the dispatcher give-up pitfall. The pitfall in the main SKILL.md describes a manual recovery. The watchdog automates the recoverable subset.

## What the dispatcher does to a coding task that crashes on spawn

The kanban dispatcher has `effective_limit: 1` (typically 2 attempts). When a worker dies at "pid not alive" immediately after spawn — the classic "Unknown skill" symptom — the kernel writes `spawned → crashed → spawned → crashed → gave_up` to `task_events` and marks the task `blocked`.

For a **coding task** (assignee = marvin/iris/etc), this is *not recoverable* by the watchdog. The missing skill is on the coding profile, and only a human (or the watchdog escalating to one) can fix it. The watchdog's Class B handler **escalates to operator via god-notify** with the hypothesis "missing skill on <assignee>'s profile."

For a **Hephaestus review task** (assignee = hephaestus), the same crash IS recoverable — Hephaestus is the same profile the watchdog is running in, so it can just unblock and let the dispatcher respawn (or the watchdog can recover in-session via the kanban-spawn-recovery skill recipe). The watchdog's Class A handler auto-applies this.

## How the dispatch chain stays healthy

```
plan-execution
    ↓
[50 tasks dispatched in one pass, parent-gated]
    ↓
hephaestus-watchdog (every 4 min)
    │
    ├── Class A: spawn crash on hephaestus Tier-N review
    │           → hermes kanban unblock
    │           → dispatcher respawns
    │           → human (Hephaestus) does the review
    │
    ├── Class B: spawn crash on marvin/iris coding task
    │           → god-notify error ping
    │           → operator: install missing skill + requeue
    │
    ├── Class C: parent still running
    │           → silent, correct gating
    │
    └── Class D: unknown blocker
                → god-notify warning ping
                → operator: investigate

kanban-watcher (every 5 min, parallel)
    ↓
Telegram: new tasks appearing, status transitions
    ↓
Operator: only sees changes that matter
```

## What plan-execution should do differently now

**Nothing.** The whole-graph dispatch pattern (v1.0.5) and the QA gate SOP (v1.0.6) are still correct. The watchdog is a *complement* to the existing infrastructure, not a replacement.

The one change is **post-dispatch verification**: after the chain is in flight, the first 3 minutes of watchdog output confirms the dispatch is healthy. If the watchdog recovers tasks in its first sweep, that's a signal the plan had a phantom-skill issue that the Step 1.5 pre-flight check missed — review the dispatch plan and tighten the pre-flight.

## When the watchdog doesn't fire but you expected it to

- **Watchdog not running** — `ps aux | grep hephaestus-watchdog` should show the cron process every 4 min. If not, check the cron entry in `~/.hermes/profiles/hephaestus/cron/jobs.json` and the lock file at `cron/state/hephaestus-watchdog.pid`.
- **Task not classified as Class A** — the watchdog only auto-recovers **Hephaestus review tasks** with spawn crashes. Coding tasks (Class B) escalate. Tasks blocked for non-crash reasons (Class D) escalate. Check the task's `task_events` to confirm the failure mode matches.
- **State file has the task in `recovered` or `escalated` already** — the watchdog is idempotent and won't re-process. Clear the entry to retry: `python3 -c "import json; d=json.load(open('hephaestus-watchdog.json')); d['recovered'].pop('<tid>', None); d['escalated'].pop('<tid>', None); json.dump(d, open('hephaestus-watchdog.json', 'w'))"`.

## See also

- Main SKILL.md pitfall: "Dispatcher give-up on review tasks"
- `dispatch-monitoring/references/hephaestus-watchdog.md` — full triage trace and recovery recipe
- `kanban-spawn-recovery` SKILL.md — the recipe the watchdog auto-applies
