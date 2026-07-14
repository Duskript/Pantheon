# Kanban Recovery — Direct DB Access & Dispatcher Recovery Recipes

A reference for Hephaestus when the dashboard API is unavailable (auth, Tailscale bind, downtime) and for when the dispatcher's give-up threshold trips on review tasks.

## When to use this reference

- The kanban dashboard at `100.68.106.59:9119` returns `{"error": "unauthenticated", "reason": "no_cookie"}` and you need status.
- A kanban task is stuck in `blocked` after a worker spawn failure and the parent-child chain has stalled.
- You're investigating why a task transitioned through `claimed → spawned → crashed → gave_up` and need the raw event payload.
- You want a board snapshot for an operator status report without running a full Python client.

## Why direct DB access?

The kanban plugin is a Python aiohttp service bound to Tailscale (`100.68.106.59:9119`), with session-token auth on every endpoint. The DB is `~/.hermes/kanban.db` (also at `~/.hermes/kanban/kanban.db` for the global board, plus per-profile `kanban.db` for boards scoped to a profile). The DB is the source of truth — the API just projects from it. Direct queries are:

- **Faster** — no network roundtrip
- **Auth-free** — no token needed
- **Resilient** — works even if the dashboard is down or crashed
- **More detailed** — you can see `task_events.payload` JSON that the API doesn't expose

## Full schema (key tables only)

```sql
-- tasks: the board's source of truth
CREATE TABLE tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    body            TEXT,
    assignee        TEXT,           -- 'marvin', 'thoth', 'hephaestus', etc.
    status          TEXT NOT NULL,  -- 'todo' | 'ready' | 'running' | 'done' | 'blocked' | 'failed' | 'archived'
    priority        INTEGER DEFAULT 0,
    created_by      TEXT,
    created_at      INTEGER NOT NULL,    -- epoch seconds
    started_at      INTEGER,
    completed_at    INTEGER,
    workspace_kind  TEXT NOT NULL DEFAULT 'scratch',
    workspace_path  TEXT,
    claim_lock      TEXT,
    claim_expires   INTEGER,
    tenant          TEXT,                 -- god name when set; routing key
    result          TEXT,                 -- set on complete
    idempotency_key TEXT,
    spawn_failures  INTEGER NOT NULL DEFAULT 0,
    worker_pid      INTEGER,
    last_spawn_error TEXT,
    max_runtime_seconds INTEGER,
    last_heartbeat_at INTEGER,
    current_run_id  INTEGER,
    workflow_template_id TEXT,
    skills          TEXT                  -- JSON list (or NULL)
);

-- task_links: parent-child dependency graph
CREATE TABLE task_links (
    parent_id  TEXT NOT NULL,
    child_id   TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id)
);
CREATE INDEX idx_links_child ON task_links(child_id);

-- task_events: full lifecycle log
CREATE TABLE task_events (
    id          INTEGER PRIMARY KEY,
    task_id     TEXT NOT NULL,
    run_id      INTEGER,
    kind        TEXT NOT NULL,   -- 'claimed' | 'spawned' | 'crashed' | 'heartbeat' | 'gave_up' | ...
    payload     TEXT,            -- JSON; e.g. {"pid": 472738, "claimer": "pantheon:308703"}
    created_at  INTEGER NOT NULL
);

-- task_runs: one row per worker spawn attempt
CREATE TABLE task_runs (
    id          INTEGER PRIMARY KEY,
    task_id     TEXT NOT NULL,
    -- worker_pid, started_at, ended_at, exit_status, etc.
);
```

## Status-report queries (paste-ready)

```bash
KANBAN=~/.hermes/kanban.db

# Board summary: count by status
sqlite3 -header -column "$KANBAN" \
  "SELECT status, count(*) FROM tasks GROUP BY status ORDER BY status;"

# What's running right now + who owns it
sqlite3 -header -column "$KANBAN" \
  "SELECT id, substr(title,1,60), assignee, substr(last_heartbeat_at,1,10) AS hb
   FROM tasks WHERE status='running';"

# Blocked tasks (operator attention needed)
sqlite3 -header -column "$KANBAN" \
  "SELECT id, substr(title,1,55), assignee, spawn_failures, last_spawn_error
   FROM tasks WHERE status='blocked';"

# Tasks in a phase (use LIKE on title prefix)
sqlite3 -header -column "$KANBAN" \
  "SELECT status, count(*) FROM tasks
   WHERE title LIKE '%Phase 3.1%' GROUP BY status;"

# All tasks for a project, with parent links visible
sqlite3 -header -column "$KANBAN" \
  "SELECT t.id, t.status, t.assignee, l.parent_id
   FROM tasks t LEFT JOIN task_links l ON t.id = l.child_id
   WHERE t.title LIKE '%[conductor-ui]%'
   ORDER BY t.status, t.created_at;"

# Recent done tasks (for "what shipped" reports)
sqlite3 -header -column "$KANBAN" \
  "SELECT id, substr(title,1,55), assignee, completed_at
   FROM tasks WHERE status='done'
   ORDER BY completed_at DESC LIMIT 15;"
```

## Dispatcher give-up: diagnose, recover, prevent

### Symptom

A review task (Tier-1 by Hephaestus, Tier-2 by Thoth) is in `status='blocked'` and its downstream child (the next tier) is `status='todo'` and not promoting. The chain has stalled on a single review.

### Diagnose

```bash
# Pull the full event log for the blocked task
sqlite3 -header -column ~/.hermes/kanban.db \
  "SELECT kind, substr(payload,1,200), created_at
   FROM task_events
   WHERE task_id='<TASK_ID>'
   ORDER BY id DESC LIMIT 10;"
```

Look for the sequence: `claimed → spawned → crashed → spawned → crashed → gave_up`. The `gave_up` payload contains:

```json
{
  "failures": 2,
  "effective_limit": 1,
  "limit_source": "dispatcher",
  "error": "pid 472738 not alive",
  "trigger_outcome": "crashed",
  "pid": 472738,
  "claimer": "pantheon:308703"
}
```

`effective_limit: 1` is the giveaway. The dispatcher tried 2 spawns (success+fail counted as 1 effective attempt) and bailed.

### Common root causes

1. **Phantom skill in `tasks.skills`** — worker loader crashes on `Unknown skill(s): X, Y` immediately after spawn. Check:
   ```bash
   sqlite3 ~/.hermes/kanban.db "SELECT skills FROM tasks WHERE id='<TASK_ID>';"
   ```
   Then verify each skill exists in `~/.hermes/profiles/<assignee>/skills/`.

2. **Worker profile down** — kanban worker daemon not running for the assignee. Check:
   ```bash
   systemctl --user status kanban-worker-<assignee>
   ```

3. **Workspace path missing** — task's `workspace_path` doesn't exist or isn't writable.

4. **OOM kill** — task body is too large for available RAM. Less common for review tasks (which don't compile), but possible if the workspace has 10K+ files.

### Recovery recipe (in order of preference)

**Option A: do the work in-session (fastest, when assignee == current profile).**

If Hephaestus is the assignee and Hephaestus is the active session: read the file, run the tests, write the verdict, then:

```bash
hermes kanban unblock <TASK_ID> --reason "Tier-N review by <god>. Original dispatcher crashed at spawn. Recovering in-session — verifying <scope> directly."

hermes kanban complete <TASK_ID> \
  --result "PASS — <scope>. VERIFIED: <bullet list>. ARCHITECTURE NOTES: <notes>. VERDICT: <verdict>." \
  --summary "<one-line for downstream tier>" \
  --metadata '{"tests_pass": N, "tsc_errors": 0, "reviewer": "<god>", "recovered_from": "dispatcher spawn crash"}'
```

The structured `--metadata` JSON is what the downstream tier reads. The `--summary` is the handoff text. Both are visible in the child task's comments when it auto-promotes.

**Option B: install the missing skill, then re-dispatch.**

```bash
# Find which skill is missing
MISSING=$(sqlite3 ~/.hermes/kanban.db "SELECT skills FROM tasks WHERE id='<TASK_ID>';" | jq -r '.[]' | while read s; do
  [ -d ~/.hermes/profiles/<assignee>/skills/*/"$s" ] || echo "$s"
done)

# Install from the shared hub
hermes skills install "$MISSING"

# Re-dispatch
hermes kanban dispatch <TASK_ID>
```

**Option C: reassign to a profile that has the skills.**

```bash
hermes kanban reassign <TASK_ID> <other-profile> --reclaim
```

### Verify recovery

```bash
# Child should now be ready/running within seconds
sqlite3 -header -column ~/.hermes/kanban.db \
  "SELECT id, status FROM tasks
   WHERE id IN (SELECT child_id FROM task_links WHERE parent_id='<TASK_ID>');"
```

## Prevention (long-term — file as github issue)

The kanban plugin should:

1. **Validate `tasks.skills` at create time** against the assignee's `~/.hermes/profiles/<name>/skills/`. Refuse to create the task with a phantom skill (or auto-install from the shared hub).
2. **Raise the give-up threshold for review tasks** to 3+ spawns. Review tasks are not resource-heavy; failing fast on a transient skill-loader race wastes a recoverable task.
3. **Make `blocked` reclaimable** — add a `hermes kanban force-recover <id>` command that resets `spawn_failures` and re-queues the task without requiring unblock.
4. **Surface `last_spawn_error` in `hermes kanban show <id>`** so the operator can see the actual failure reason without having to query the DB.

## Don't do this

- **Don't `UPDATE tasks SET status='done'` directly in the DB.** This bypasses the task_runs log, the structured `--result` / `--metadata` payload, and the parent-child gate semantics. Use `hermes kanban complete` so the audit trail stays clean.
- **Don't delete a `blocked` task and recreate it.** Same audit-trail concern, plus you lose the worker's task_events log.
- **Don't `hermes kanban dispatch <id>` on a `blocked` task without first unblocking it.** The dispatcher treats `blocked` as terminal; dispatching throws an error.
