# Hermes Kanban CLI — Verified Surface (2026-06-16)

The kanban orchestrator surface that's actually true on the Hermes CLI as of 2026-06-16. Verified against `hermes kanban <verb> --help` and the source at `pantheon/hermes-agent/hermes_cli/kanban.py` + `kanban_db.py`. Anything in the SKILL.md above this file that contradicts the surface below is **wrong** — the SKILL.md is aspirational intent, this file is the working truth.

## `hermes kanban create <title>`

**Working flags (verified live):**

| Flag | Type | Notes |
|---|---|---|
| `--body BODY` | str | Inline body. **There is no `--body-file`.** For long bodies, use `--body "$(cat /tmp/body.md)"` with proper shell quoting. |
| `--assignee PROFILE` | str | **Profile name. `hermes` is RESERVED** (see "Reserved assignee names" below). Use `thoth`, `iris`, `hephaestus`, `marvin`, `apollo`, `caduceus`, `mercer`, `rheta`, `master-coder`, `cachyos`, `theoforge`. |
| `--parent ID` | str, repeatable | Adds a parent to `task_links`. Gating is enforced at claim time in `claim_task()` (`kanban_db.py:2932`). |
| `--priority N` | **int** | Tiebreaker. **Must be int, not the string `"high"`.** Higher = picked first. |
| `--skill NAME` | str, repeatable | Skill to force-load into the worker. **The flag is `--skill`, not `--skills`.** Repeatable. |
| `--workspace WORKSPACE` | str | `scratch`, `worktree`, `worktree:<path>`, `dir:<path>` |
| `--branch NAME` | str | Branch name for worktree tasks |
| `--tenant TEN` | str | Tenant namespace |
| `--max-runtime DUR` | str | `300`, `90s`, `30m`, `2h`, `1d`. SIGTERMs the worker at the cap, then SIGKILLs, then re-queues. |
| `--idempotency-key KEY` | str | Dedup key. If a non-archived task with this key exists, its id is returned instead of creating a duplicate. |
| `--created-by NAME` | str | Author recorded on the task. Defaults to `user`. |
| `--initial-status STATUS` | enum | `blocked` or `running`. Use `blocked` to park a task that needs human ops (R3 gate) — the dispatcher won't claim it. |
| `--max-retries N` | int | Override the dispatcher's failure limit (default 2). |
| `--goal` / `--goal-max-turns N` | flag/int | Run the worker in a goal loop with a judge until done or the turn budget runs out. |
| `--triage` | flag | Park in triage. A specifier fleshes out the spec and promotes it to `ready`. |
| `--json` | flag | Emit JSON. **Do not pipe to an interpreter** — the security guard rejects `hermes | python`. Read the JSON from the terminal or redirect to a file and read that. |

**Flags that DO NOT exist (and the older aspirational docs that lie about them):**

- `--body-file` — the original `build-plan-orchestrator` v1.0.0 had this. It's wrong. Use `--body "$(cat ...)"`.
- `--skills` (plural form) — error: `unrecognized arguments: --skills`.
- `--parent-ids` — use `--parent` repeatedly.
- `--priority high|medium|low` — must be int.

## Reserved assignee names

The dispatcher refuses to spawn workers for profile names in `_RESERVED_NAMES` (`hermes_cli/profiles.py:286-296`):

- `hermes` — would create `~/.hermes/profiles/hermes/` and collide with the Hermes installation. The `hermes` directory exists at `~/.hermes/profiles/hermes/` (real profile, registered in `god.json` as the god Hermes), but the dispatcher refuses to spawn it.
- `default`, `test`, `tmp`, `root`, `sudo` — also reserved, mostly for sandboxing reasons.

**Verified 2026-06-16 on t_aeb9804a and t_09e134f1** (conductor-ui chain). The chain originally used `--assignee hermes` for t3 (write plan) and t5 (dispatch) because t1's tier-routing said "Hermes (PM lead)" — but Hermes-as-PM is a role concept, not a profile name. Reassigned both to `thoth` via direct SQL and the chain proceeded.

**Diagnostic if a task fails with this:** check the task's `error` field in `task_runs`:

```bash
sqlite3 ~/.hermes/kanban.db "SELECT id, status, error FROM task_runs WHERE task_id='<id>' AND error LIKE '%reserved%';"
```

**Recovery:** reassign via direct SQL, insert an audit `task_events` row, then `hermes kanban reclaim` to release the spawn_failed lock, then `hermes kanban dispatch` to claim again with the new assignee.

**The takeaway:** even if `god.json` lists `hermes` as a registered god, you cannot dispatch a kanban task to it. The dispatcher's profile name is what matters. Map "Hermes as PM" to whichever real profile does the work (thoth for research/planning, marvin/hephaestus for engineering, etc.).

## `hermes kanban edit <task_id>`

**For already-completed tasks only.** Edits recovery fields:

- `--result TEXT` — backfilled task result
- `--summary TEXT` — structured handoff summary (falls back to `--result` if omitted)
- `--metadata JSON` — structured facts for the latest completed run

**CLI gap:** there is **no** command to mutate a task's priority, status, body, or assignee mid-flight. For those, use the SQLite escape hatch below.

## `hermes kanban comment <task_id> <text...>`

Positional text. **NOT** `--body`. The author comes from `--author NAME` (default: `$HERMES_PROFILE` or `user`).

`hermes kanban show <task_id>` also surfaces comments + events + parents + children + runs in JSON.

## `hermes kanban link <parent_id> <child_id>` / `unlink <parent_id> <child_id>`

Adds/removes entries in the `task_links` table. Use this to **re-parent a task** after creation, or to add a parent to a task you forgot to pass `--parent` on. Idempotent.

## Parent-gating (the chain pattern)

When you pass `--parent` on a task, the dispatcher's `claim_task()` (kanban_db.py:2932) checks all parents before transitioning `ready → running`:

```sql
SELECT 1 FROM task_links l
JOIN tasks p ON p.id = l.parent_id
WHERE l.child_id = ? AND p.status NOT IN ('done', 'archived') LIMIT 1
```

If any parent is not done, the claim is rejected, the child is demoted to `todo`, and a `claim_rejected` event is written with `reason: parents_not_done`. This is the **single enforcement point** for the parent-gate invariant — every writer (create, link, unblock, manual SQL) goes through it.

**Implication for chains:** dispatch a 5-task chain as 5 separate `hermes kanban create` calls, each with `--parent` pointing to the prior. The dispatcher auto-fires each task when its parent completes. You do **not** need to wait for one to finish before dispatching the next.

**Operator-pause via blocked status:** to enforce "wait for the operator", dispatch the pause task with `--initial-status blocked`. The dispatcher won't claim it. To proceed, run `hermes kanban unblock <id> <reason>` — the unblock comment is the operator's input to the next task.

**Re-parenting mid-flight:** if a chain's gating is wrong (e.g. you parented t5 to t3 instead of t4 and t5 would fire too early), use `unlink` + `link` to fix. The dispatcher doesn't need a restart — the next claim attempt re-evaluates.

## Priority mutation (SQLite escape hatch)

When the CLI gap bites (e.g. you need to bump a task's priority mid-flight), open the shared kanban.db directly:

```bash
sqlite3 /home/konan/.hermes/kanban.db <<SQL
BEGIN IMMEDIATE;
UPDATE tasks SET priority=10 WHERE id='t_xxx';
INSERT INTO task_events (task_id, kind, payload, created_at)
  VALUES ('t_xxx', 'priority_changed',
          '{"from":7,"to":10,"reason":"<why>","changed_by":"<god>"}',
          strftime('%s','now'));
COMMIT;
SQL
```

The dispatcher sorts by `(priority DESC, created_at ASC)`. Higher priority = picked first when ready. **A priority bump cannot preempt a running worker** — the lock model is cooperative (claim TTL). The bump protects **re-claim** priority for tasks that lose their lock (heartbeat timeout, crash, etc.), not in-flight focus.

**Always** write a `priority_changed` event in the same transaction. The event is the audit trail; the UPDATE alone leaves no record of who changed what and why.

## Skill registration gotcha (the thoth-config-bug)

If a freshly-claimed task crashes immediately with `Error: Unknown skill(s): <name>` and the worker dies before producing a heartbeat:

1. The skill file exists on disk (`ls <skill-dir>/SKILL.md` works)
2. The task was created with `--skill <name>`
3. **But the profile's `external_dirs` in `config.yaml` is a stringified JSON array** (`'["path1", "path2"]'`) instead of a YAML list (`- path1\n- path2`)

The skill loader at `agent/skill_utils.py:get_external_skills_dirs` does:

```python
if isinstance(raw_dirs, str):
    raw_dirs = [raw_dirs]  # treats the whole string as ONE path
```

The literal string `["path1", "path2"]` (with brackets and quotes) is treated as a single path, expanded to a directory that doesn't exist, and the skill is silently dropped from the skill index.

**Fix the config to use YAML list syntax:**

```yaml
skills:
  external_dirs:
    - ~/athenaeum/Codex-God-marvin/skills-adapted
    - ~/pantheon/god-packages/shared-skills
```

**Verification:** `hermes skills list | grep <name>` should show the skill after the config fix. If it doesn't, the path is wrong or the `SKILL.md` is malformed (missing frontmatter, broken YAML, etc.).

**Scope:** the thoth profile and the main `/home/konan/.hermes/config.yaml` had this bug. All other profiles (apollo, iris, hephaestus, marvin, caduceus, mercer, rheta) used the correct YAML list format. Likely a hand-edit at some point that broke just the thoth profile.

## Operator-pause pattern (Path A / Path B / Path C)

The 3 variants in the SKILL.md "Path A vs Path B vs Path C" table map to flag choices:

| Path | Pause mechanism | Verified flag |
|---|---|---|
| A (4 pauses) | Each god completes with `kanban_block` | Worker calls `hermes kanban block <id> <reason>` at end of task |
| B (2 pauses) | t1→t2 and t2→t3 auto-progress; t3 + t4 are paused via blocked status | t3 + t4 dispatched with `--initial-status blocked`; operator runs `hermes kanban unblock <id> <reason>` to fire |
| C (0 pauses) | All auto-progress | All tasks in `ready`; no `blocked`; no operator unblock |

For Path B, the operator-unblock is the only thing that progresses the chain past t3 and t4. The unblock comment travels into the next task's `result.metadata` via the kanban `comments` join.

## Heartbeat / lock-TTL timing

A claimed task heartbeats every ~60s. The default claim TTL is ~900s. If a worker goes silent for the full TTL, the dispatcher reclaims the task and re-spawns a worker. The recovery cost is real — the new worker has to re-derive the task context from `task_runs.summary` of the prior run. For tasks with > 60 iteration budgets, the recovery cost is high; size `--max-runtime` accordingly.

When a task's `status = running` and `last_heartbeat_at` is > 5 minutes old, the worker is either dead or stuck. The dispatcher will reclaim eventually; you can force it with `hermes kanban reclaim <id>` to release the lock immediately.

## What this file does NOT cover

- `hermes kanban` verbs not listed above (list, ls, show, assign, claim, complete, block, unblock, promote, archive, tail, dispatch, daemon, watch, stats, etc.) — see `hermes kanban --help` for the full list. Most of those are read-only or surface operations; the verbs above are the ones that **mutate** state and matter for orchestration.
- Conductor YAML authoring (workflows, rules, webhooks) — that's the `conductor-design-workflow` skill.
- Hermes gate semantics (RALPH, Q1-Q5 questions) — that's the `ichor-harness-engineering` skill.
- The `external_dirs` `~` resolution bug (Bug 2 in `hermes-profile-config-bugs-2026-06-16.md`) — fix in flight as kanban task `t_0d5aa51d`.
