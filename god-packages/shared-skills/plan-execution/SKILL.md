---
name: plan-execution
description: "Use when the user says 'execute this plan', 'run this plan', 'dispatch the build', 'start the work', or any request to take a written, signed-off build plan and turn it into shipped work. This is Hephaestus's core skill — the conductor of the workflow. Reads a plan from ~/pantheon/plans/, dispatches kanban tasks per the file-by-file table, wires parent-child gating, generates QA-gate review follow-ons, monitors the chain, escalates blockers."
version: 1.0.9
tags: [orchestration, plan-execution, build-plan, dispatch, kanban, conductor, hephaestus, qa-gate, ponytail-gate, whole-graph]
---

# Plan Execution — Hephaestus's Core Skill

> **The skill that takes a written, signed-off build plan and turns it into shipped work.** This is Hephaestus's primary job. The plan is the boundary between "Konan + Thoth have decided" and "the work is in flight." Plan-execution is the act of crossing that boundary correctly.

## When to use this skill

Load this skill whenever:

- The user says "execute this plan", "run this plan", "dispatch the build", "start the work"
- A `build-plan-orchestrator` chain reaches t5 (dispatch the build)
- Hephaestus is asked to take a plan and run it
- A build's t1-t4 are done and the operator has signed off (status: APPROVED)

**Don't use this skill for:**

- Writing the plan (that's the build-plan-orchestrator's t3)
- Reviewing the plan (that's the build-plan-orchestrator's t4 sign-off)
- One-off tasks that don't have a plan (use `kanban-orchestrator` directly)
- Reading a plan without executing (just read the file)

## Plan Revision Discipline (binding)

**When a revision document arrives against an existing build plan:**

1. **Mark the current build plan as DEPRECATED.** Add a prominent header at the top: `> **DEPRECATED YYYY-MM-DD:** Superseded by [new plan name].` Do NOT delete it — the deprecated plan is a historical artifact. Do NOT append to it — a plan is never patched in place.

2. **Read both sources:** the revision document AND the deprecated plan. Understand what changed and what stayed.

3. **Compile a new, self-contained build plan** that merges both sources. The new plan is the single source of truth. It must be readable without cross-referencing the deprecated plan or the revision document — all context is inlined.

4. **Double-check the compilation.** Verify that every item mentioned in the revision document appears in the new plan. Verify that every item from the deprecated plan that was NOT revoked by the revision still appears. Nothing dropped silently.

5. **Set status and provenance.** The new plan's provenance section cites both the deprecated plan and the revision document as sources. Status starts at `DRAFT`.

**Rules that govern this discipline:**

- **Single source of truth.** For any planning document or architecture document, exactly ONE canonical version exists. Once it has been set, it is never appended — only superseded by an entirely new version.
- **No silent drops.** When combining sources, you must verify completeness. If the revision removes something, that removal is explicit and documented in the new plan's "Changes from previous version" section.
- **Push approved plans to git.** When a plan reaches `APPROVED` status and the operator signs off, commit it to the assigned git repository for that project. Plans sitting only on local disk are lost knowledge.
- **Plan path convention.** Plans live at `~/pantheon/plans/<project>-build-plan-v<version>.md`. The deprecated plan stays at its original path; the new plan gets the next version number.

**Pitfall — "I'll update the plan later":** Never defer plan updates. The discipline fails when the operator's latest instructions live in chat but the plan on disk is stale. Apply the discipline at the moment the revision arrives, not after the build starts.

## How to use it (the procedure)

### Step 0: Read the plan carefully

Before dispatching anything, read the plan from start to finish.

**Path:** `~/pantheon/plans/<project>-build-plan.md`

**Read for:**

- **Title block** — what project, what version, who authored
- **Provenance** — what informed the plan (operator request, tier-routing, catalog lookup)
- **Tier routing summary** — what tools, what pattern, what specialists
- **Foundation** — what artifact the build starts from
- **Phased plan** — phases, dependencies, deliverables per phase
- **File-by-file table** — every file, action, owner, verification
- **Tests + verification gates** — per-phase "done" check
- **Decisions applied** — every operator-locked decision that constrains the build
- **Pitfalls** — patterns that have failed before
- **Specialists** — who's involved, what each one owns

**Verify:**

- The plan status is `APPROVED` (not `DRAFT` or `IN-FLIGHT`)
- The plan follows the 13-section build-plan-shape standard
- The Q&A decisions are all answered
- The file-by-file owners match the god-roster (per `god-roster.md`)
- The project root follows the build-path convention (per `build-path-convention.md`)
- The verification gates are runnable commands

If the plan is missing any of these, **stop and escalate to the operator**. Don't dispatch an incomplete plan.

### Step 1: Validate the plan against the standards

Before dispatching, run the `convention-enforcer` skill on the plan. Check:

- The path follows `build-path-convention.md` (project root is `~/projects/`, plan is in `~/pantheon/plans/`)
- The plan uses no calendar durations (no "X days", "X weeks")
- The plan uses the 13-section build-plan-shape
- The file-by-file owners are valid gods per `god-roster.md`
- The verification gates are concrete commands (not "works correctly")
- The pitfalls section cites real prior sessions

If validation fails, **stop and report to the operator**. The plan needs revision before dispatch.

### Step 1.5: Pre-dispatch skill validation (PREVENTION, not just workaround)

**Every skill listed in the dispatch plan must exist in the assignee's profile before the task is created.** This is the *prevention* layer for the phantom-skill crash class (the workaround lives in pitfall "Skills referenced in dispatched tasks must exist in the assignee's profile" below — but the right move is to catch the issue at dispatch time, not after the worker crashes).

**Procedure for each task being dispatched:**

```bash
# For each (assignee, skill) pair in the dispatch plan:
ASSIGNEE=marvin
SKILL=pantheon-dev-workflow
if [ ! -d "/home/konan/.hermes/profiles/${ASSIGNEE}/skills"/*/"${SKILL}" ] && \
   [ ! -d "/home/konan/.hermes/profiles/${ASSIGNEE}/skills"/*/*/"${SKILL}" ]; then
  echo "MISSING: ${ASSIGNEE} does not have skill ${SKILL}"
fi
```

Or via Python:

```python
import os
assignee = "marvin"
skill = "pantheon-dev-workflow"
profile_skills_dir = f"/home/konan/.hermes/profiles/{assignee}/skills/"
# Walk the profile's skills dir (handles nested skill categories)
for root, dirs, files in os.walk(profile_skills_dir):
    if os.path.basename(root) == skill:
        print(f"FOUND: {assignee} has {skill}")
        break
else:
    print(f"MISSING: {assignee} does NOT have {skill}")
```

**If any skill is missing from the assignee's profile, three options:**

1. **Install the skill in the assignee's profile** — symlink or `hermes skills install` if the skill is in the shared hub
2. **Replace the skill** with one the assignee has (find a close functional equivalent)
3. **Reassign the task** to a profile that has the skills

**Do NOT create the task with a phantom skill and rely on the worker to handle it.** Marvin tolerated the warning this time; Iris crashed twice. The behavior is profile-dependent, which makes it non-deterministic. **Pre-flight validation is the only deterministic fix.**

**A pre-flight script that wraps `hermes kanban create` is the long-term answer** — the dispatcher should validate before committing the create. Until that's built, run the check manually for every task in the dispatch plan.

**If a skill is intentionally a phantom** (e.g., a future skill that hasn't been built yet, or a skill the operator explicitly wants to gate on), document it in the task body as `Note: this skill is intentionally phantom and will be added in <phase>`. Don't just leave the field blank.

### Step 1.5: Validate that every skill in the dispatch plan exists in the assignee's profile

For every skill that will be loaded into a task (from the plan's per-task spec), verify the skill actually exists in the assignee's `~/.hermes/profiles/<assignee>/skills/` directory. This is the pre-flight for the "phantom skill" pitfall below.

```bash
# For each (skill, assignee) pair in the dispatch plan
for skill in <skill-list>; do
  for assignee in <assignee-list>; do
    if ! ls ~/.hermes/profiles/${assignee}/skills/ 2>/dev/null | grep -qF "$skill"; then
      echo "MISSING: skill '$skill' not in profile '$assignee'"
    fi
  done
done
```

**If any skill is missing in the assignee's profile:**

- **(a)** Install the skill in the assignee's profile (symlink from `~/pantheon/god-packages/shared-skills/<skill>/` into `~/.hermes/profiles/<assignee>/skills/<skill>/`).
- **(b)** Replace the skill in the dispatch plan with a skill the assignee has (check `pantheon-god-roster.md` for the right owner of that skill's domain).
- **(c)** Direct-SQL UPDATE `tasks.skills` to strip the missing name after dispatch (see the "phantom skill" pitfall below for the exact pattern).

Option (a) is the cleanest; option (b) is the right call when the skill doesn't belong in the assignee's profile conceptually; option (c) is the workaround when the task is already dispatched and the worker is about to claim it.

**This step is operator-locked for any build with an automated worker spawn pattern.** Skipping it is the failure mode that produced the 2026-06-16 conductor-ui chain bug: t5 dispatched 6 phase tasks all referencing `build-spec-authoring` and `thoth-qa-gate` which exist in no profile; Iris's worker crashed twice on spawn; Marvin's worker tolerated the warning but the phantom remained. The check is cheap (seconds per task) and catches a class of bug that takes a chain offline for 5+ minutes per failure.

### Step 2: Build the dispatch plan (chain construction)

**Operator-locked rule (2026-06-17): pre-build the WHOLE graph, don't drip-feed.**

The kanban's parent-child gating is designed to be used as a graph, not a queue. When dispatching, create **every** task in the plan (code + tier-1 reviews + tier-2 reviews + phase gates) in a single dispatch pass, with parent IDs wired so the chain self-propels. Do NOT wait for a task to complete before dispatching its successors. Do NOT throttle to "first wave of 5 tasks, watch them, then queue the next 5." Pre-build the entire graph.

Why: the parent-child gate (`task_links` table) is the dispatcher's built-in scheduler. Tasks become `ready` (claimable) automatically when their parents hit `done`. The chain is then self-driving — the monitor catches the state changes, the workers pick up ready tasks, and the graph unwinds without per-batch intervention. Drip-feeding inverts this: Hephaestus becomes the throttler instead of the conductor, and the operator has to ask for status because no notifications flow until the human-visible next batch is queued.

Operator signal: "why are we not building basically every task and dropping them all in the kanban so as the blockers clear they're just there?" — Konan, 2026-06-17. Treat as a standing directive for every multi-task dispatch.

**Practical limits to the whole-graph rule:**

- Respect the **turn budget** pitfall — tasks with >5 files or >3 concerns must be split (a single task will time out at 90 turns regardless of how many siblings it has).
- Respect the **OOM on low-RAM** pitfall — split Phase 0 into files-only + tsc-clean.
- Idempotency keys (`<project>-<phase>-<file>-<action>`) prevent duplicate creation if the dispatch has to be re-run after a partial failure.

**Read the plan's `phased plan` + `file-by-file table`. For each phase, build a chain:**

**The plan is the source of truth, but task bodies are frozen at dispatch time.** The dispatcher creates the task body from the plan once; subsequent plan edits (operator scope shifts, additional decisions) do NOT auto-propagate to in-flight tasks. If the plan changes after dispatch, the dispatched task bodies need a manual `UPDATE tasks SET body=...` in `kanban.db` (see pitfall "Plan edits don't auto-propagate to in-flight tasks" below). Always snapshot the plan at the moment of dispatch and treat dispatched task bodies as the contract for those workers.

**Per-phase structure:**

```
Phase N (Scope)
  ↓
[N tasks per the file-by-file table]
  ↓
[QA-gate review tasks — one per code-producing task]
  ↓
[Phase gate task — runs the verification command, reports to operator]
  ↓
(operator sign-off)
  ↓
Phase N+1 starts
```

**Task shape (per `kanban-task-shape.md`):**

For each file in the file-by-file table:

```yaml
title: "[<project>] <verb> <path>"
body: |
  <context: which build plan section, what decisions>
  <your task: implement the file per the plan's verification>
  <output: the file path, the verification command>
  <skills to load: based on the file's owner>
assignee: <god per the file-by-file Owner column>
skills: [<skills based on the Owner>]
parent: <phase-level parent task>
workspace: dir:/home/konan/projects/<project-name>
priority: 7  # or higher if the operator marked it urgent
created-by: hephaestus
idempotency-key: "<project>-<phase>-<file>-<action>"
max-runtime: <appropriate for the task size>
```

**QA-gate review tasks (per the QA-gate rule, op-locked 2026-06-17):**

For each code-producing task (Action: CREATE or MODIFY for `.ts`, `.tsx`, `.py`, `.rs`, `.go`, `.sh`):

**Tier-1: Hephaestus (in-session, kanban task):**

```yaml
title: "[<project>] tier-1 review <path> against the architecture contract"
body: |
  <context: which file, which plan section, which architecture contract>
  <your task: verify the file (run tests, tsc, lint), engineering-review, send back to Marvin for fixes if needed>
  <output: pass | needs_changes verdict per design-review-shape>
  <skills: code-review, design-review>
assignee: hephaestus
skills: [code-review, design-review-shape]
parent: <the coder task>
priority: 7
created-by: hephaestus
idempotency-key: "<project>-<phase>-<file>-tier1"
```

After the tier-1 task completes, Hephaestus invokes the GPT-5.5 Ponytail gate (isolated one-shot `hermes chat` on `openai-codex/gpt-5.5`) — see `gpt55-ponytail-qa` SKILL.md. The Ponytail gate is a per-build invocation, not a kanban task. Thoth is only invoked on `ESCALATE`, operator request, or release-gate work.

**Phase gate tasks:**

For each phase, after all the work tasks + QA reviews:

```yaml
title: "[<project>] Phase <N> gate — verify and report"
body: |
  <context: which phase, what's expected>
  <your task: run the verification command from the build plan §6, report to operator>
  <output: pass/fail, the verification output, the next-phase owner>
  <skills: phase-boundary-shape>
assignee: hephaestus
skills: [phase-boundary-shape]
parent: <the last task in the phase>
priority: 7
created-by: hephaestus
idempotency-key: "<project>-phase-<N>-gate"
```

### Step 3: Dispatch the chain

For each task in the dispatch plan, run:

```bash
BODY=$(cat /tmp/<task-id>-body.md)
hermes kanban create \
  "<title>" \
  --body "$BODY" \
  --assignee <god> \
  --skill <skill> \
  --parent <parent-id> \
  --workspace dir:/home/konan/projects/<project-name> \
  --priority 7 \
  --created-by hephaestus \
  --idempotency-key "<key>" \
  --max-runtime <duration>
```

**Gotchas (per Hephaestus's command reference):**

- Use `--body "$BODY"` not `--body-file` (doesn't exist)
- Use repeated `--skill` not `--skills` (plural, doesn't exist)
- Use `--priority 7` (int) not `--priority high` (string, rejected)
- The workspace must be `dir:/home/konan/projects/<project-name>` (per the build-path convention)
- The idempotency key prevents duplicate creation (use the format `<project>-<phase>-<file>-<action>`)

**Path B tasks (if any in the plan):** use `--initial-status blocked` to create the task already paused, so the dispatcher won't claim it. The operator unblocks via `hermes kanban unblock <id> <reason>`.

### Step 4: Notify the operator + the next-phase owners

Once the chain is dispatched, notify:

1. **The operator** — "Build <project> dispatched. <N> tasks across <M> phases. <K> QA-gate reviews auto-created. First task: <task-id>. Pings fire as tasks complete."

2. **The first task's owner** — "Task <task-id> is ready to claim. Body: <summary>. Verification: <command>."

3. **Any blockers** — if a task has dependencies, notify the owner of the dependency.

Use the `messaging_send` MCP tool or `hermes kanban notify-subscribe` for the notifications.

### Step 5: Monitor the chain (loop)

The chain is now in flight. Hephaestus monitors until it ships or blocks.

**Per the `dispatch-monitoring` skill:**

- Watch for `running` tasks that exceed their `max-runtime` (the dispatcher auto-claims stale, but Hephaestus verifies)
- Watch for `blocked` tasks (operator unblock needed)
- Watch for `failed` tasks (re-dispatch or escalate)
- Watch for QA reviews returning `block` (escalate to operator)
- Watch for the phase gate passing (report to operator, await sign-off)

The monitoring loop runs until:

- The chain ships (all phases `done`, all QA reviews `pass`)
- The chain blocks (operator decision needed)
- The chain is cancelled (operator says `cancel`)

### Step 6: Report at every phase boundary

At each phase boundary (per `phase-boundary-shape.md`):

1. **Run the verification command** — confirm the gate is technically passed
2. **Report to the operator** — "Phase <N> complete. Gate: pass. Awaiting sign-off."
3. **Wait for sign-off** — explicit `approved`, `change`, `cancel`, or `defer`
4. **On `approved`** — **commit and push the approved work to the project repo BEFORE dispatching the next phase.** See "Commit-after-signoff rule" below. Then notify the next-phase owner, the next phase starts.
5. **On `change`** — send the change request back to the current phase's owner
6. **On `cancel`** — halt the chain, mark tasks `cancelled`, notify all owners
7. **On `defer`** — pause the chain, schedule a re-check

The operator's sign-off is **explicit**. Hephaestus does not assume.

#### Commit-after-signoff rule (operator directive 2026-06-17)

When the operator signs off on a phase (or any unit of approved work), **commit the approved work to the project repo before moving on to the next thing.** Konan's standing directive: "we should start committing after each sign off." This applies to:

- Phase boundaries in a dispatched chain (Step 6 above)
- One-off tasks the operator approves ("good, do X" → commit X before doing Y)
- Recovery work after a crash — the operator says "ok, recover" → commit the recovery before continuing
- The very first sign-off in a brand-new project — this triggers the git init + first-push flow (see `github-pr-workflow` §8 "New project repo: first-commit flow")

**Why this rule exists:** the 2026-06-17 conductor-ui case had ~795 lines of `detail.tsx` plus 23 passing tests living uncommitted on disk because no one had run `git init` and no phase gate had triggered a commit. The work was functionally shipped but had no history, no recovery path, and no remote backup. Commit-after-signoff prevents the "everything green on disk, nothing in git" failure mode.

**Mechanics:**

- Use the project's commit conventions (Conventional Commits) per `github-pr-workflow` §2
- Push to the project's primary remote (usually `origin`, branch `main` for solo projects, branch-per-phase for multi-developer)
- For multi-task phases, the phase gate task body should include the commit command — don't leave it implicit
- For solo project repos, commit straight to `main` (the SOUL.md "no commits to main" rule applies to team repos with PR review, not solo projects)
- For team repos, the commit goes on the phase branch and the PR is opened/merged as part of the signoff handshake

**Verification at the signoff handshake:** `git status` clean, `git log --oneline -1` shows the new commit, `git push` returns ok. If any of these fail, the signoff is not complete — debug the commit before notifying the next-phase owner.

### Step 7: Ship the build

When all phases are done and all QA reviews pass:

1. **Run the final verification** (the plan's overall gate)
2. **Update the build-status doc** — move the build from "active" to "completed"
3. **Log the decision** — write a decision log entry for the ship event
4. **Notify the operator** — "Build <project> shipped. <N> tasks done, <M> QA reviews pass, <K> phases complete. Project at <path>. Next: <follow-up work>"
5. **Trigger the post-build artifacts** — per the plan's §12, queue the catalog entry + wiki ingest

## Worked example

The conductor-ui build v1.1 is the worked example. When the plan is approved and the chain dispatches:

- Phase 0 dispatches 6 tasks: P0a (Iris, mock re-inspection), P0b (Konan+Thoth, Soulforge design), P0c-f (Marvin, scaffold)
- Each Marvin task gets a Thoth review follow-on
- Phase 0 gate task runs `npx tsc --noEmit && npm run test:run` after the work + reviews complete
- Hephaestus reports the gate state to the operator
- On operator `approved`, Phase 1 dispatches

## Pitfalls

**Don't dispatch a DRAFT plan.** DRAFT means the operator hasn't signed off. Dispatching a DRAFT = executing unapproved work. Stop, escalate.

**Don't skip the tier-1 review tasks.** Every code-producing task must have a Hephaestus tier-1 follow-on (per the QA gate SOP, operator-locked 2026-06-17). After tier-1 passes, Hephaestus invokes the GPT-5.5 Ponytail gate in an isolated one-shot chat (see `gpt55-ponytail-qa` SKILL.md). Thoth reviews are escalation-only — don't auto-create Thoth review tasks unless the operator requests them or the work is release-gate scope.

**Don't use the wrong workspace.** The workspace must be `dir:/home/konan/projects/<project-name>`, not `scratch` (the work would be lost) and not `worktree` (that's for git branches, not for project code).

**Don't time-estimate.** No "X days" or "expected timeline" in any report. Use "Pings fire as tasks complete" (per the no-time-estimates rule, operator-locked 2026-06-16).

**Don't auto-execute external events.** If a NATS message or webhook arrives mid-chain, the sovereignty rule applies. Notify the operator, ask `handle now or later?`. Don't auto-execute.

**Don't claim the next phase until the operator signs off.** Phase boundaries are operator gates. Even if the verification command passes, the next phase doesn't start until the operator says `approved`.

**Don't bundle multiple files into one task.** Each file in the file-by-file table gets its own task. Otherwise, the QA review can't follow per-file, and one file's failure blocks the others.

**Don't assume dispatcher references are current after a god-role change.** After any rework that changes which god owns which domain, verify that `build-plan-orchestrator` (the CLI examples' `--assignee` fields), `kanban-orchestrator` (the `references/pantheon-god-roster.md`), and the `god-roster` skill all agree on the assignee mapping. A stale reference in any of these causes tasks to route to the wrong god silently. Run a grep for `--assignee` across all three before dispatching a newly-approved plan. (Discovered 2026-06-16: Hephaestus rework flipped build-plan-orchestrator t1/t2/t3/t5 from `thoth` → `hephaestus`; the CLI examples were caught before any chain dispatched, but the drift window was real.)

**Operator sign-off unblock pattern: `comment` first, then `unblock`.** When a path-B gate is blocked and the operator approves, the CLI sequence is `hermes kanban comment <task> "approved"` THEN `hermes kanban unblock <task> "approved"`. Passing the approval text only as the unblock-command's text-arg is treated as a "silent unblock" by the worker convention — the worker re-spawns and re-blocks with "Silent unblock = approval on next spawn." The comment puts the operator's reply into the worker's input; the unblock advances the cycle. Discovered 2026-06-16: t4 (conductor-ui sign-off) looped twice because unblock-with-text was treated as silent. Fix was comment + unblock in that order. See `kanban-orchestrator` references for the full post-dispatch operations recipe.

**Skills referenced in dispatched tasks must exist in the assignee's profile.** The dispatcher's task creation loads the skills list into `tasks.skills` from the plan's per-task spec, but does not validate the skills exist in the assignee's profile. If a skill name is in the plan but no profile has it installed, the worker's skill loader fails and the worker crashes (typically "Unknown skill(s): X, Y" then "pid not alive" on spawn). **Prevention:** Step 1.5 (validate skills before dispatch). **Recovery:** if the task is already dispatched and the worker is about to claim, the fix is direct SQLite — `UPDATE tasks SET skills='["a","b"]' WHERE id='<task>';` (use a Python wrapper or `json.dumps` to handle quoting). Then `hermes kanban unblock <task> "skill list repaired"`. See `kanban-orchestrator` references / pitfall "hermes kanban edit cannot mutate tasks.skills either" for the full recipe. Discovered 2026-06-16: t5 dispatched 6 conductor-ui phase tasks all referencing `build-spec-authoring` and `thoth-qa-gate` which exist in no profile. Iris's worker crashed twice on spawn; Marvin's worker tolerated the warning but the phantom remained. **Tool gap to fix in a future kanban version: validate `tasks.skills` against the assignee's `~/.hermes/profiles/<name>/skills/` at create time, AND let `hermes kanban edit` accept `--skills` for post-dispatch mutation.**

**QA gate SOP (op-locked 2026-06-17): Marvin/Iris → Hephaestus tier-1 (in-session verify + engineering review) → GPT-5.5 Ponytail QA gate (isolated one-shot `hermes chat` on `openai-codex/gpt-5.5` via the `gpt55-ponytail-qa` skill) → ACCEPT/RETURN/ESCALATE.** Konan's directive: "I am not utilizing my chatgpt subscription enough and this serves a pretty important purpose and it does mean that things should run quicker." So the routine QA gate is now GPT-5.5 Ponytail, not Thoth. Thoth QA is reserved for: (a) Ponytail verdict = `ESCALATE`, (b) operator-requested review, (c) release-gate work (Phase 5+, public releases, schema migrations). Decision lock: `pantheon/shared/decisions/2026-06-17-qa-gate-replaces-thoth-routine.md`. The dispatch pattern is: every code-producing task gets a Hephaestus tier-1 follow-on (parent=the code task, assignee=hephaestus, in-session verify + engineering review). After Hephaestus signs off, Hephaestus runs the GPT-5.5 Ponytail gate in an isolated one-shot chat (see `gpt55-ponytail-qa` SKILL.md for the invocation recipe). Only ESCALATE verdicts route to Thoth. Discovered 2026-06-17: UCE v0.3 was the first chain to ship under the two-tier pattern; conductor-ui v1.2 transitioned to the Ponytail gate mid-flight. Always create the tier-1 review follow-on in the same dispatch pass as the code task; the Ponytail gate is a per-build invocation, not a kanban task.

**Turn budget exhaustion on large tasks — split proactively.** Marvin's worker has a 90-turn iteration budget per kanban task run. Tasks that require building multiple files or complex logic can exhaust this budget before completion, timing out with "Iteration budget exhausted (90/90)." The worker runs for ~20-25 minutes before hitting the wall. **Fix:** Split tasks with >3 files or >1 concern into sub-tasks. A task like "build 8 REST endpoints + auth hardening across 3 files" will reliably time out; split into "build 4 CRUD endpoints" then "build run/validate/events + auth." A task like "wire 12 API endpoints" will time out; split into "wire 5 READ endpoints" then "wire 7 mutation + events endpoints." The split should keep each task's scope to what fits in ~50 turns with margin. Test: if the task body describes >5 distinct files or >3 architectural concerns, split it. Discovered 2026-06-17: Phase 3.1 and 4.0 both timed out twice (4 runs total, ~80 agent-minutes burned) before being split into 3.1a/3.1b and 4.0a/4.0b.

**Parent-child review deadlock — unblock the code task to let the review flow.** The kanban parent-child gating prevents a child task from being claimed while its parent is in a terminal state (blocked, failed). When a Marvin code task completes and blocks itself with "review-required," the review task (which has the code task as its parent) cannot promote because its parent is blocked. This creates a self-deadlocking chain. **Fix:** After confirming the code review passes (tier-1), unblock the code task (`hermes kanban unblock <code-task> "tier-1 pass"`) THEN complete it (`hermes kanban complete <code-task>`). The review task will auto-promote when the parent transitions to done. Alternatively, complete D1 first then let the dispatcher claim D1-Review-T1 — but if D1 is blocked, it must be unblocked before it can be completed. Discovered 2026-06-17: D1 blocked itself on "review-required"; D1-Review-T1 (parent=D1) stayed "todo" because parent was blocked; unblocking D1 then completing it allowed the review to flow.

**OOM on low-RAM systems — split scaffold tasks, avoid compiling in the same process.** On 8GB hosts, TypeScript compilation (`npx tsc --noEmit`) plus `node_modules` can exhaust available memory, killing the worker process with "pid not alive." This produces repeated crashes that burn through retries (Phase 0 crashed 5 times before max-retries exhausted). **Fix:** Split Phase 0 into sub-tasks — "create placeholder files" (no compilation) then "tsc clean" as a separate gated task. Do NOT run `npm install` and `npx tsc --noEmit` in the same task as file creation. Keep individual task memory footprints small. On systems with <16GB RAM, consider adding swap before large TypeScript builds. Discovered 2026-06-17: Phase 0 of conductor-ui v1.1 crashed 5 times (iris ×2, marvin ×3) before being split into 0a (files only) and 0b (tsc clean). The split resolved the OOM pattern.

**Deploy a chain monitor on every dispatch — never make the operator ask for status.** Konan's explicit frustration: "why is it that I have to keep telling you to check this? Is there no way for you to keep an eye on this? And if something goes wrong or changes that you let me know." After dispatching a chain, deploy a background monitor that polls the kanban board and notifies the operator on every task status change. The monitor script lives at `~/pantheon/scripts/chain-monitor.sh` (shell-based, polls `hermes kanban list`, diffs against snapshot, sends `god-notify` on changes). Start it with `bash chain-monitor.sh &` after dispatch. The monitor watches for project prefixes (`[uce-v0.3]`, `[conductor-ui]`) and reports: new tasks appearing, status transitions (todo→running, running→done, →blocked, →failed), tasks disappearing (archived/done). Proactive monitoring is a conductor obligation, not an operator request. Discovered 2026-06-17: Konan asked "where are we at" multiple times because no notifications were flowing; the chain monitor was built mid-session and restarted after a process death. If the operator approves a scope shift, role reassignment, or new decision AFTER the chain has dispatched, the live task bodies in `kanban.db` still reflect the old plan. Workers reading the body will execute the old scope. Required fix: `UPDATE tasks SET body=<new body> WHERE id=<task_id>` in `kanban.db`, ideally while the task is `ready` (not yet claimed). If the task is already `running`, the worker may have already loaded the old body — coordinate via `messaging_send` to the assignee's inbox AND a `kanban comment` on the task. Discovered 2026-06-16: phase 0 of conductor-ui dispatched with P0a in its body; operator scope-shifted P0a into Phase 1 mid-chain; the body had to be UPDATEd via direct SQLite to match the new plan. Mark the live plan with the scope shift (append a "scope shift (operator directive YYYY-MM-DD)" block to the relevant phase) and update the task body in the same move. The plan is the source of truth for *future* tasks; the task body is the source of truth for *current* workers.

**Pre-dispatch inventory check: is the work already done?** Before dispatching a phase, verify the deliverables aren't already in the workspace. The plan describes intent; the workspace has the reality. If the plan says "create docs/conductor-soulforge-interview-design.md" and that file already exists with a signed-off P0b decision, the dispatch should either skip the task or fold it into a verification step. A 30-second `ls <project-root>/docs/` + `ls <project-root>/src/` check before dispatch prevents re-doing work the operator already approved. Discovered 2026-06-16: phase 0 was dispatched with P0a (mock re-inspection) in scope, but P0b's deliverable was already in the repo and signed off. The operator caught the redundancy only when the worker crashed on phantom skills; the inventory check would have caught the redundancy first.

**Always verify the on-disk state before splitting a "crashed" kanban task.** When a task description says a worker crashed mid-build, the dispatcher's instinct is to split the task and re-dispatch. But the workspace has the reality: run `npx tsc --noEmit`, `npx vitest run`, `git status`, and read the file in question BEFORE splitting. The "crash" may have been in wrap-up, not build — the artifact may be functionally complete and green on disk (tsc clean, tests pass, router wired). If so, the right move is *not* to split + re-dispatch, it's to (a) verify the work, (b) commit it (per the commit-after-signoff rule), (c) fold the recovery into a verification + signoff task rather than a rebuild task. The "split t_34f89a26" instinct would have rebuilt work that was already shipped, burning a kanban cycle and a worker's run budget. Discovered 2026-06-17: conductor-ui Phase 3.4 t_34f89a26 was being prepped for split because the description said Marvin "crashed during tests + final verification." On disk: detail.tsx was 795 lines, all 4 sections built, router wired, tsc clean, 23/23 tests passing. The crash was apparently in a prior wrap-up cycle; what survived was the shipped-quality artifact. The right task shape was "verify + commit + signoff," not "split + rebuild."

**Verify upstream handoff claims before planning around them (the "phantom error" class).** Inbox messages and upstream QA reports describe blockers ("X is broken," "Y has N errors," "Z crashed mid-build"). These claims can be stale by the time they reach the next session — the underlying state may have been fixed in a later commit, the error counted may be a test-side bug, or the "crash" may have been a wrap-up loop where the artifact actually shipped. The pattern: (1) take the claim seriously, (2) but do NOT plan work around it without verifying on disk first. A 30-second `npx tsc --noEmit` or `git status` check can prevent spending 90 minutes building a fix for a problem that no longer exists. Discovered 2026-06-17 conductor-ui: (a) Phase 3.4 handoff said "1 unrelated tsc error in src/ledger_client/migration/" — tsc was actually clean, the error had been fixed in a later commit; (b) Phase 4.3 Tier-2 audit claimed "76 tsc errors in src/editor/nodes/*/schema.ts" blocking Phase 4.2 — tsc was actually clean across all 6 schema files. Both phantom-blocker claims would have spawned recovery work; verifying on disk first revealed the work was unblocked. The fix is one extra verification command in the recon step, not a different dispatch shape. **The discipline: "trust the audit, verify the file."** Inbox narratives are useful context but not ground truth. The filesystem is ground truth.

**Don't stop at the first blocker — dispatch everything unblocked in parallel.** When one phase is blocked on a specialist who hasn't launched (or on a dependency that's still in flight), do NOT report the blocker and stop. Immediately scan the dependency graph for EVERY phase whose blockers are all cleared, and dispatch them all to available specialists in a single pass. The operator's explicit directive: "if there is anything we can be doing we should be doing it, don't let one blocker stop things that depend on it from being worked on." Different repos = zero merge conflicts = genuinely parallel. The operator should never have to ask "why isn't X doing their part?" — the answer is always either "X is dispatched and in their inbox" or "X is blocked on Y, and here's everything else I dispatched instead." Discovered 2026-06-18: Phase 4.3 was blocked on Iris (unlaunched), but 4.5 (credentials) and 3.8 (editor↔kanban) were both unblocked and could have been dispatched to Marvin immediately. Hephaestus waited for operator prompting before dispatching them.

**One at a time on multi-thread status answers — never drip-feed options in a single turn.** When the operator asks "what's left" or "what's going on with X," the temptation is to enumerate every open thread, score each by priority, and propose 3-5 next moves. The operator has explicitly rejected this pattern (operator signal: "Nope let's do it one at a time," 2026-06-17). The right shape: (1) state the actual state in a table or short list, (2) propose ONE thread to pull, (3) wait for the operator to confirm before pulling it. Don't preemptively ask "which of these 5?" with full detail on each — the operator picks the thread, then you go deep on it. **The pattern:** status report → recommended next move → wait. If the operator wants a different thread, they say so; you do NOT pre-render all the other threads' details. The cost of "show all 5 options in detail" is cognitive overhead and the impression that you can't prioritize. The cost of "show state + propose one + wait" is one extra round-trip, which the operator values more than the saved pre-render. Discovered 2026-06-17 conductor-ui: when asked "what is going on with 4.2," Hephaestus surfaced 3 sub-decisions, 4 design questions for Iris, 3 next-move options, and 5-page reasoning — the operator cut it short with "Generated CSS / And leave the rest to Iris." The decision the operator actually cared about was 1 of 3. Surface the decision, not the menu.

**Make the design decision you can, route the rest to its owner.** When the operator is asked to weigh in on a multi-part design question, they will often answer only the parts they care about and leave the rest to the named owner. Don't ask for all 3 decisions when the operator will make 1 and route 2. The pattern: identify which sub-decision is the operator's call (typically: principle/architecture/values), surface that one, and proactively route the other sub-decisions to their owners (Iris for visual design, Thoth for research, Marvin for implementation). **The signal:** if you find yourself asking "which of A/B/C do you want?" and any of A/B/C clearly belongs to another named role, surface that in the same response: "A is yours, B is Iris's, C is Marvin's; here's A." Discovered 2026-06-17 conductor-ui Phase 4.2: Hephaestus asked about 4 design decisions for the Lumen theme (source-of-truth surface, editor node styling, status color tokens, WCAG contrast). The operator answered "Generated CSS" (the one design decision) and explicitly said "And leave the rest to Iris." Two of the four questions were never the operator's to answer; they were Iris's. Surface the operator's question, route the rest, save the round-trip.

**Dispatcher give-up on review tasks — recover by doing the review in-session, not by re-dispatching.** The kanban dispatcher has an `effective_limit: 1` (often 2 attempts) on worker spawns. If a Tier-1 (Hephaestus) or Tier-2 (Thoth) review task crashes the worker twice in a row — typically "pid not alive" immediately after spawn, classic Unknown-skill symptom from the assignee's profile missing the listed skills — the kernel writes a `gave_up` event and marks the task `blocked`. **The parent-child gate does not promote the child tier review**, so the whole downstream branch stalls. Re-dispatching with `hermes kanban dispatch` will hit the same give-up because the skill list is the same. **Recovery recipe:**
2. **Decide: re-dispatch with fixed skills, or do the review in-session.** If the assignee's profile is missing a skill, `hermes skills install` first, then re-dispatch. If the assignee is the same profile Hephaestus is already running in, do the review directly — read the file, run the tests, write the verdict.
3. **Unblock** — `hermes kanban unblock <task_id> --reason "<who is recovering and how>"`.
4. **Complete with structured handoff** — `hermes kanban complete <task_id> --result "<verdict with specifics>" --summary "<one-line for downstream>" --metadata '{"key": "value", ...}'`. The metadata goes onto the closing run and is what the tier-2 review reads.
5. **Verify the parent-child gate fired** — `sqlite3 ~/.hermes/kanban.db "SELECT status FROM tasks WHERE id='<child-task-id>'"`. The child should now be `ready` or `running`.

Discovered 2026-06-17: Phase 3.1b Tier-1 review (assigned to hephaestus) crashed at spawn with "pid not alive x2" because the worker's skill loader failed on phantom skills. The dispatcher hit `effective_limit: 1` and gave up. The fix was to do the review in-session (Hephaestus is the same profile), then unblock + complete with structured metadata. Thoth's tier-2 review auto-promoted within seconds of the unblock.

**Long-term fix to file as a github issue against the kanban plugin:** (a) validate `tasks.skills` against the assignee's profile at create time (kills the whole crash class), (b) raise the dispatcher give-up threshold to 3+ for review tasks (Tier-1/Tier-2 are not resource-heavy — failing fast on a transient skill-loader race wastes a recoverable task), (c) make the `blocked` state reclaimable rather than terminal-soon, with an explicit `hermes kanban force-recover` or auto-recover-after-N-minutes.

**Status reports from kanban.db — bypass the API auth.** The dashboard server at `100.68.106.59:9119` requires session-token auth and binds to Tailscale, not localhost. For status checks during monitoring, query the SQLite DB directly. It's faster, doesn't need a token, and survives if the dashboard is down. Schema: `tasks` (id, title, status, assignee, parent_id), `task_links` (parent_id, child_id), `task_events` (kind, payload JSON, created_at), `task_runs` (task_id, status). **Useful queries:**

```bash
# What's running right now
sqlite3 -header -column ~/.hermes/kanban.db \
  "SELECT id, substr(title,1,65), assignee FROM tasks WHERE status='running';"

# Tasks in a specific phase (use LIKE on title prefix)
sqlite3 -header -column ~/.hermes/kanban.db \
  "SELECT status, count(*) FROM tasks WHERE title LIKE '%Phase 3%' GROUP BY status;"

# A task's full event log
sqlite3 -header -column ~/.hermes/kanban.db \
  "SELECT kind, substr(payload,1,150), created_at FROM task_events WHERE task_id='<id>' ORDER BY id DESC LIMIT 10;"

# Parent-child wiring
sqlite3 -header -column ~/.hermes/kanban.db \
  "SELECT child_id, parent_id FROM task_links WHERE child_id='<id>';"
```

For a richer reference (full schema, recovery recipes, give-up payloads), see `references/kanban-recovery.md`.

## Verification gates

Plan-execution is "complete" when:

- [ ] The plan is read in full and validated against the standards
- [ ] The dispatch plan is built (per-phase structure with QA-gate reviews)
- [ ] All tasks are dispatched with verified CLI flags
- [ ] The operator is notified of the dispatch
- [ ] The chain is monitored until ship or block
- [ ] Each phase boundary has operator sign-off
- [ ] The build-status doc is updated
- [ ] The decision log has a ship entry
- [ ] Post-build artifacts are queued

## See also

- `Codex-Pantheon/design/standards/build-plan-shape.md` — what a plan looks like
- `Codex-Pantheon/design/standards/kanban-task-shape.md` — what a task looks like
- `Codex-Pantheon/design/standards/phase-boundary-shape.md` — what a phase boundary looks like
- `Codex-Pantheon/design/standards/god-handoff-shape.md` — the handoff shape
- `Codex-Pantheon/design/standards/qa-gate-rubric.md` — the review rubric
- `Codex-Pantheon/design/operator-rules-cheatsheet.md` — the operator rules
- `Codex-God-Hephaestus/command-reference.md` — the Hermes CLI reference
- `pantheon/god-packages/shared-skills/build-plan-orchestrator/SKILL.md` (v1.0.5) — the chain that produces the plan (Hephaestus is now default assignee for t1/t2/t3/t5 post-rework)
- `pantheon/god-packages/shared-skills/kanban-orchestrator/SKILL.md` — the dispatcher (plan-execution uses it)
- `references/hephaestus-watchdog.md` — the auto-recovery cron that closes the dispatcher-give-up loop
- `dispatch-monitoring/references/hephaestus-watchdog.md` — full triage trace + failure-mode taxonomy

## Changelog

### v1.0.10 (2026-06-19)

- **Post-build router verification pitfall.** After all components ship, verify the router imports real route components — not Phase 0 inline placeholders. The pattern: the file-by-file table says every component was built, tests pass, tsc clean, but the app still shows "Phase 0 scaffold — task board with columns (Phase 3)." The gap is in the router — it was written with inline placeholder JSX in Phase 0 and never updated as real components shipped. Check each route's `component:` in `router.tsx` against the corresponding file in `src/routes/`. Every route should import from its route file, not render inline `<div>Phase 0 scaffold...</div>`. Also verify: the TanStack Router file-based plugin requires a `src/routes/__root.tsx` even when routing is code-defined; without it, HMR restarts fail with "rootRouteNode must not be undefined."
- **Vite proxy pitfall series.** Three proxy misconfigurations block a live frontend: (a) path mismatch — conductor serves at `/api/workflows` but Vite proxies `/api/conductor/workflows` → need `rewrite: (path) => path.replace(/^\/api\/conductor/, '/api')`; (b) allowedHosts — Tailscale Funnel proxies through `pantheon.tail164759.ts.net` but Vite blocks it with 403 unless `allowedHosts` includes the Funnel domain; (c) kanban auth — the Hermes dashboard skips auth for 127.0.0.1 but not Tailscale IP; the Vite proxy must target `http://127.0.0.1:9119` for dev loopback bypass.
- **Backend port reality check.** The build plan assumed conductor on 8770; the deployed service was on 8088. Before wiring proxies, run `lsof -i:<port>` to verify where services actually bind — plan assumptions drift from deployment reality.
- **`hermes kanban` has no `cancel` command.** Use `archive` to remove stale tasks. The CLI surface (2026-06) has `archive` but not `cancel`.

- **Phantom-error pitfall.** New pitfall: verify upstream handoff claims before planning around them. Inbox messages and QA reports can be stale by the time they reach the next session. The discipline is "trust the audit, verify the file" — run the actual command (`npx tsc --noEmit`, `git status`, `ls <path>`) before committing to a recovery task. A 30-second check prevents 90 minutes of work on a non-problem. Discovered 2026-06-17 conductor-ui: two phantom blockers in a single session (the "1 tsc error in migration" from the Phase 3.4 handoff, and the "76 tsc errors in src/editor/nodes/*/schema.ts" from the Phase 4.3 Tier-2 audit). Both were stale; tsc was clean in both cases.
- **One-at-a-time status pitfall.** New pitfall: when the operator asks "what's left" or "what's going on with X," surface the state + ONE recommended next move + wait. Do not drip-feed 3-5 options in detail — the operator will pick one, and the pre-rendered detail on the others is cognitive overhead. Discovered 2026-06-17 conductor-ui: operator signal "Nope let's do it one at a time" after Hephaestus enumerated 5 open threads with pre-rendered plans for each. The right shape is "status table + recommend one + wait." Extra round-trip is cheaper than pre-rendering options the operator didn't pick.
- **Route design decisions to their owners pitfall.** New pitfall: when a multi-part design question lands, identify which sub-decision is the operator's call vs which belongs to another named role (Iris for visual design, Thoth for research, Marvin for implementation). Surface the operator's question; proactively route the rest in the same response. Discovered 2026-06-17 conductor-ui Phase 4.2: Hephaestus asked about 4 design decisions; operator answered 1 ("Generated CSS") and routed the rest ("leave the rest to Iris"). Two of the four were never the operator's question. The "Generated CSS / leave the rest to Iris" pattern is the canonical example.

### v1.0.8 (2026-06-17)

- **Commit-after-signoff rule** (operator directive). Step 4 of the phase-boundary flow now requires committing and pushing the approved work to the project repo BEFORE notifying the next-phase owner. Applies to phase boundaries, one-off approved tasks, recovery work, and the first sign-off in a brand-new project. Captures Konan's standing directive: "we should start committing after each sign off." Discovered against conductor-ui 2026-06-17: ~795 lines of `detail.tsx` plus 23 passing tests lived uncommitted on disk because no phase gate triggered a commit and the project was never `git init`'d. Rule prevents the "everything green on disk, nothing in git" failure mode.
- **Always-verify-before-splitting pitfall.** When a task description claims a worker crashed mid-build, the dispatcher must verify the on-disk state (tsc, tests, file existence, git status) before splitting + re-dispatching. The crash may have been in wrap-up, not build — the artifact may already be shipped-quality. Discovered against conductor-ui Phase 3.4 t_34f89a26: the task was being prepped for split because Marvin "crashed during tests + final verification," but on disk the work was functionally complete (tsc clean, 23/23 tests pass, router wired). Right move was verify + commit, not split + rebuild.

### v1.0.7 (2026-06-17)

- **hephaestus-watchdog integration** — The dispatcher-give-up recovery recipe (v1.0.5) is now automated. The `hephaestus-watchdog` cron (every 4 min, profile-scoped) auto-applies the recipe for Class A failures (spawn crash on Hephaestus Tier-N review). Added a one-paragraph "Auto-recovery note" callout to the give-up pitfall, a `See also` pointer, and a new `references/hephaestus-watchdog.md` documenting the dispatcher's perspective (what the watchdog can/can't recover, when it doesn't fire, how the dispatch chain stays healthy with both `kanban-watcher` and `hephaestus-watchdog` running in parallel). No change to dispatch procedure — the watchdog is a complement, not a replacement.

### v1.0.6 (2026-06-17)

- **QA gate SOP updated (op-locked 2026-06-17).** Routine gate is now GPT-5.5 Ponytail QA (isolated one-shot `hermes chat` on `openai-codex/gpt-5.5` via the `gpt55-ponytail-qa` skill) instead of Thoth. Tier-1 review tasks still go to Hephaestus (in-session verify + engineering review), but tier-2 review follow-on tasks are no longer auto-created — the Ponytail gate is invoked per-build by Hephaestus as the second layer. Thoth reviews are escalation-only: `ESCALATE` verdict, operator request, or release-gate scope. Step 2 task shape updated to `assignee: hephaestus` for tier-1. "Don't skip" pitfall updated. The "Two-tier QA" pitfall replaced with the new flow + invocation path. Konan's quote: "I am not utilizing my chatgpt subscription enough and this serves a pretty important purpose and it does mean that things should run quicker." Decision lock: `pantheon/shared/decisions/2026-06-17-qa-gate-replaces-thoth-routine.md`.

### v1.0.5 (2026-06-17)

- **Whole-graph dispatch pattern** — Operator directive: pre-build the entire graph at once, don't drip-feed. Kanban's parent-child gating IS the scheduler; tasks auto-promote when parents hit `done`. The chain self-propels. Respect the existing turn-budget and OOM-split pitfalls for task granularity, but within those limits, queue EVERYTHING in a single dispatch pass. Discovered 2026-06-17: Konan asked why we were drip-feeding 2 tasks at a time when the kanban could be holding all 50+ tasks with parent-child wiring and they would just unblock as gates cleared.
- **Dispatcher give-up recovery recipe** — New pitfall: when a review task (Tier-1 or Tier-2) crashes the worker twice in a row (typical "pid not alive" from phantom skills), the kernel hits `effective_limit: 1` and marks the task `blocked`. Re-dispatching hits the same wall. Recovery: diagnose via `task_events`, do the review in-session if the assignee is the same profile, then `unblock` + `complete --metadata '{...}'` with structured handoff. The child tier review auto-promotes. Long-term fix noted: dispatcher should validate `tasks.skills` at create time AND raise the give-up threshold for review tasks.
- **Status from kanban.db directly** — New pitfall: bypass the dashboard's auth requirement (binds to Tailscale at 9119, not localhost) by querying `~/.hermes/kanban.db` directly with `sqlite3`. Faster, no token, survives dashboard downtime. Useful queries documented inline; full schema in `references/kanban-recovery.md`.

### v1.0.4 (2026-06-17)

- **Two-tier QA pitfall** — Operator-locked rule: every code task gets Hephaestus tier-1 (iterative) + Thoth tier-2 (final QA). Baked into the QA-gate review task shape in Step 2.
- **Turn budget pitfall** — 90-turn iteration limit requires splitting tasks with >5 files or >3 concerns. Sub-tasks keep scope under ~50 turns. UCE 3.1 and 4.0 both timed out twice (4 runs, ~80 agent-minutes) before splitting.
- **Parent-child review deadlock pitfall** — Code tasks blocked on "review-required" prevent review child tasks from promoting. Fix: unblock code task, then complete it, then review auto-flows.
- **OOM on low-RAM pitfall** — Phase 0 scaffold + tsc in same task kills worker on 8GB. Split: files-only task, then gated tsc-clean task. Conductor-ui Phase 0 crashed 5 times before this fix.
- **Chain monitor pitfall** — Deploy `~/pantheon/scripts/chain-monitor.sh` after every dispatch. Shell-based, diffs kanban state, sends god-notify on changes. Never make the operator ask for status.

### v1.0.3 (2026-06-16)

- **Added Step 1.5: Pre-dispatch skill validation** — the *prevention* layer for the phantom-skill crash class. The pitfall in v1.0.2 documented the workaround (SQLite strip after worker crash); this version adds the procedure that catches the issue *at dispatch time* — verify every skill listed in the dispatch plan exists in the assignee's profile before creating the task. The class signal: Iris's worker crashed twice in a row on Phase 0 of the conductor-ui build because `build-spec-authoring` + `thoth-qa-gate` were in the plan but not in her profile. Marvin's worker tolerated the warning, which made the failure non-deterministic. Pre-flight validation is the only deterministic fix; the long-term answer is a wrapper script that validates before committing the kanban.create call. The pre-flight bash + Python snippets are inline in Step 1.5.
