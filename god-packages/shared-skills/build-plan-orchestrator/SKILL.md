---
name: build-plan-orchestrator
description: "Use when the user says 'convert this to a build plan', 'make a build plan for X', 'plan the build for Y', 'set up a build for Z', or any request to convert a concept, spec, or rough idea into a phased, dispatchable build plan. This is the user-in-the-loop skill chain that walks through 4-5 checkpoints before dispatching the work to specialists."
version: 1.0.7
tags: [orchestration, build-plan, kanban, user-in-loop, checkpoints, multi-step, path-a, path-b, path-c]
---

# Build Plan Orchestrator — User-in-the-Loop Chain

This is the **entry-point skill** for "convert this to a build plan." It creates a kanban task chain that walks through 4-5 operator checkpoints before dispatching the build to specialists. **You stay in the loop at every step.** Nothing auto-progresses past a decision you haven't made.

> **CLI Surface — READ FIRST (verified 2026-06-16)**
>
> All `hermes kanban ...` commands in this skill use the **verified CLI surface** at `references/hermes-kanban-cli-verified.md`. The flags in this skill body are correct; if you find a discrepancy, the reference is canonical. The most common errors a god makes when running this skill:
>
> - Using `--body-file <path>` — does **not** exist. Use `--body "$(cat /tmp/body.md)"` with proper shell quoting.
> - Using `--skills name1,name2` (plural, comma-joined) — does **not** exist. Use `--skill name1 --skill name2` (singular, repeated).
> - Using `--priority high|medium|low` (string) — rejected. Must be `--priority 7` (int).
> - Forgetting that `hermes kanban edit` only works on **already-completed** tasks. To bump priority, mutate body, or change status mid-flight, you need the SQLite escape hatch documented in the reference.
>
> The Python `hermes_tools.kanban_create(...)` calls in older versions of this skill do not exist. The CLI is the real surface.

## Path A vs Path B vs Path C — operator-pause variants

The 5-step chain has three modes depending on how many operator pauses you want:

| Path | Operator pauses | When to use | Pause mechanism (verified flags) |
|---|---|---|---|
| **A** (canonical, original v1.0.0) | 4 pauses (after t1, t2, t3, t4) | Novel builds, high-stakes decisions, or builds where the operator genuinely needs to choose between architecture options | Each task's worker calls `hermes kanban block <id> <reason>` at end of execution |
| **B** (default from v1.0.1) | **2 pauses** (after t3 + after t4) | Builds where tier-routing + catalog lookup decisions are constrained, but the operator still wants to read the plan before dispatch. The Conductor UI build uses this. | t1, t2, t5 dispatched normally; **t3 and t4 dispatched with `--initial-status blocked`** so the dispatcher won't claim them. Operator runs `hermes kanban unblock <id> <reason>` to fire. |
| **C** (auto-fire) | 0 pauses | Trusted gods, low-stakes builds, "I just want it done" | All tasks in `ready`; no `blocked`; no operator unblock |

**Path B is the new default for v1.0.1+.** Use Path A only when the operator explicitly asks for the full 4-checkpoint ceremonial version. Use Path C only when the operator has explicitly said "just run it."

**Hephaestus is the default assignee for steps 1, 2, 3, 5 (operator-locked 2026-06-16, now active post-rework).** Hephaestus is "God of Building and Architecture" — he executes the plan, dispatches the work, monitors the chain. Step 4 (final sign-off) stays `thoth` (it's a gate, not an execution decision). The chain structure is unchanged from v1.0.3; only the assignees have flipped. See `Codex-Pantheon/design/hephaestus-rework-workflow-god.md` for the full rework design.

**Path B mechanics in detail:**

- Dispatch all 5 tasks with `hermes kanban create` — the first 3 (t1, t2, t5) in normal `ready` status, t3 and t4 with `--initial-status blocked`.
- Wire parent-gating: t2's `--parent` = t1, t3's `--parent` = t2, t4's `--parent` = t3, t5's `--parent` = t4.
- The dispatcher auto-fires t2 when t1 completes (no operator pause). Same for t2→t3.
- t3 stays `blocked` after creation. The operator (or a watcher) runs `hermes kanban unblock t3 <reason>` to make it claimable.
- t4 same — the operator unblocks after approving the plan.
- t5 auto-fires when t4 completes.

The unblock comment is the operator's input to the next task. It travels via the kanban `comments` join into the worker's context.

## The 5-step chain

| Step | Skill invoked | Operator checkpoint (Path B) | What you're asked |
|---|---|---|---|
| 1. Tier-route the request | `workflow-tier-routing` | none — auto-progresses to t2 | (no operator question; god answers inline) |
| 2. Find similar workflows | `workflow-catalog-lookup` | none — auto-progresses to t3 | (no operator question; god answers inline) |
| 3. Write the build plan | `pantheon-dev-workflow` (Step 4) | **yes** — `blocked` until operator unblocks | "Read the plan at <path>. Approved? Change X? Cancel?" |
| 4. Final sign-off | (gate task) | **yes** — `blocked` until operator unblocks | "Approve to dispatch? Cancel? Modify?" |
| 5. Dispatch | `kanban-orchestrator` | none — auto-fires after t4 done | n/a |

> **v1.0.1 design choice:** Step 4 is a separate task gated on t3 instead of inline. Cost: +1 task, +1 minute. Benefit: greppable `approved_to_dispatch` event in kanban history. For high-stakes builds, this is the default. For low-stakes trusted builds (Path C), skip t4 entirely.

**Each step runs to completion, then either auto-progresses (t1, t2, t5) or waits for operator unblock (t3, t4 in Path B).**

## When to use this skill

Load this skill whenever the user says:
- "Convert this to a build plan"
- "Make a build plan for X"
- "Plan the build for Y"
- "Set up a build for Z"
- "I want to build X, plan it out"
- "What's the right way to build Y?"
- "Walk me through planning Z"
- "Build plan from this spec"
- "Plan a project from this concept"

**Don't use this skill for:**
- One-off questions ("what should I use for X?") — answer directly or use `thoth-codesign-brainstorm`
- Code changes that don't need a multi-step plan — use `plan-to-build` or direct work
- Existing workflows that just need to run — that's the kanban dispatch, not build planning

## How to use it (the procedure)

### Step 0: Read the user's request carefully

Before you create any tasks, understand:
- What's the project name? (use kebab-case, e.g., `mercer-outreach`, `conductor-ui`, `claude-x-codex-feature`)
- What's the rough scope? (1-2 sentences from the user)
- Are there constraints? (deadline, must-use-tech, must-avoid-tech, existing code to modify)
- Where should the build plan live? (default: `~/pantheon/plans/<project-name>-build-plan.md`)

If any of these are unclear, ask 1-2 clarifying questions **before** creating the task chain. Cheap to ask; expensive to spawn the wrong fleet.

### Step 1: Create the tier-route task

**CLI command (verified flags):**
```bash
BODY=$(cat /tmp/build-plan-t1-body.md)
hermes kanban create \
  "[<project_name>] tier-route the build request" \
  --assignee hephaestus \
  --body "$BODY" \
  --skill workflow-tier-routing \
  --skill pantheon-dev-workflow \
  --priority 7 \
  --created-by <caller-god> \
  --workspace scratch \
  --idempotency-key "build-plan-<project_name>-t1"
```

> **Common errors to avoid:** `--body-file` does not exist (use `--body "$BODY"`). `--skills` (plural) does not exist (use repeated `--skill`). `--priority high` is rejected (use `--priority 7`).

The body file content is:

```markdown
<build_request>
{user_request}
</build_request>

## Your task

Apply the `workflow-tier-routing` skill to this build request.

Determine:
1. **Which workflow tools** to use (conductor_yaml, kanban_task, direct_session, cli_tool, soulforge, etc.)
2. **What pattern** this is (pipeline, fan_out, fan_in, approval_gated, scheduled, event_triggered, etc.)
3. **Catalog search terms** for finding similar existing workflows (3-5 keywords)
4. **Estimated complexity** (low | medium | high) and rationale
5. **Which specialists** should be involved (Marvin, Iris, Thoth, etc.)

## Output

Write a structured summary as your task `result`:

```bash
hermes kanban complete <t1_id> \
  --result "<1-2 sentence recommendation>" \
  --metadata '{"tools_to_use": [...], "pattern": "...", "catalog_search_terms": [...], "estimated_complexity": "low|medium|high", "complexity_rationale": "...", "specialists": [...], "rationale": "2-3 sentences"}'
```

## When done — Path B: DO NOT block. Just complete the task and t2 will auto-fire.

```bash
hermes kanban complete <t1_id> --result "..." --metadata '{...}'
```

## Skills to load

- `workflow-tier-routing` (the routing rules)
- `pantheon-dev-workflow` (Step 2: Planning, for context on what makes a good routing decision)
```

### Step 2: Create the catalog lookup task (gated on t1)

**CLI command (verified flags):**
```bash
BODY=$(cat /tmp/build-plan-t2-body.md)
hermes kanban create \
  "[<project_name>] find similar workflows" \
  --assignee hephaestus \
  --body "$BODY" \
  --skill workflow-catalog-lookup \
  --parent <t1_id> \
  --priority 7 \
  --created-by <caller-god> \
  --workspace scratch \
  --idempotency-key "build-plan-<project_name>-t2"
```

The body file content is:

```markdown
Read the tier-routing result from task {t1_id}:
<result>
{ t_xxx.result.metadata }
</result>

## Your task

Apply the `workflow-catalog-lookup` skill.

Use the catalog_search_terms from the tier-routing result to find 3-5 similar workflows in the catalog at `~/athenaeum/Codex-Pantheon/workflows/`.

For each match, return:
- workflow_id
- location (path to the YAML or skill)
- similarity_score (0-1)
- one-line description
- modification_guide (how to adapt it for THIS project)

## Output

```bash
hermes kanban complete <t2_id> \
  --result "Found N similar workflows. Best match is X." \
  --metadata '{"matches": [{"workflow_id": "...", "location": "...", "similarity_score": 0.85, "description": "...", "modification_guide": "..."}, ...], "best_match": "..."}'
```

## When done — Path B: DO NOT block. Complete the task and t3 will auto-fire (after operator unblocks t3 from `--initial-status blocked`).

```bash
hermes kanban complete <t2_id> --result "..." --metadata '{...}'
```

## Skills to load

- `workflow-catalog-lookup`
- The catalog at `~/athenaeum/Codex-Pantheon/workflows/`
```

### Step 3: Create the build plan authoring task (gated on t2, paused)

**CLI command (verified flags, with `--initial-status blocked` for Path B operator pause):**
```bash
BODY=$(cat /tmp/build-plan-t3-body.md)
hermes kanban create \
  "[<project_name>] write the build plan" \
  --assignee hephaestus \
  --body "$BODY" \
  --skill pantheon-dev-workflow \
  --skill build-spec-authoring \
  --skill plan \
  --parent <t2_id> \
  --priority 7 \
  --created-by <caller-god> \
  --workspace scratch \
  --initial-status blocked \
  --max-runtime 90m \
  --idempotency-key "build-plan-<project_name>-t3"
```

The body file content is:

```markdown
Read the tier-routing result: { t_xxx.result.metadata }
Read the catalog lookup result: { t_yyy.result.metadata }

## Your task

Apply the `pantheon-dev-workflow` skill (Step 4: Build Plan).
Apply the `build-spec-authoring` skill for the file-by-file spec.

Write the phased build plan to:
`~/pantheon/plans/{project_name}-build-plan.md`

## Required sections

1. **Tier routing summary** — from t1 (which tools, which pattern, why)
2. **Similar workflows considered** — from t2 (which match, what to clone/modify)
3. **Operator's choice** — clone | scratch | extend (only relevant if t2 was Path A; Path B skips this)
4. **Phased implementation plan** — phases, what each phase ships, dependencies between phases
5. **File-by-file changes** — exact paths, what changes, who does it
6. **Tests + verification gates** — per phase, what's the "done" check
7. **Open questions** — anything needing operator decision before phase 1
8. **Timeline estimate** — rough weeks/days per phase, dependencies

## Output

```bash
hermes kanban complete <t3_id> \
  --result "Build plan written to <path>. N phases, M tasks, ~X weeks." \
  --metadata '{"build_plan_path": "~/pantheon/plans/<project>-build-plan.md", "phases": N, "estimated_tasks": M, "estimated_weeks": X, "open_questions": [...]}'
```

## When done — Path B: BLOCK after writing the plan. This is the operator pause.

```bash
hermes kanban block <t3_id> "Build plan is at ~/pantheon/plans/<project>-build-plan.md. Read it. Reply 'approved' to dispatch, or tell me what to change. (Approved | Change: <what>)"
```

> **Note:** In Path B, the task is created with `--initial-status blocked` so the dispatcher won't claim it. The operator (or a watcher) unblocks via `hermes kanban unblock t3 '<reason>'` AFTER the plan is written. The flow is: operator unblocks → dispatcher claims → god runs → god writes plan → god calls `kanban block` with the read-the-plan prompt. Or: the operator unblocks before the plan is written, in which case the god runs and writes the plan inside the run.

## Skills to load

- `pantheon-dev-workflow` (full)
- `build-spec-authoring`
- `plan` (for the structure)
```

### Step 4: Final sign-off (separate task, Path B default)

**CLI command (verified flags, paused):**
```bash
BODY=$(cat /tmp/build-plan-t4-body.md)
hermes kanban create \
  "[<project_name>] final sign-off — approve to dispatch?" \
  --assignee thoth \
  --body "$BODY" \
  --parent <t3_id> \
  --priority 7 \
  --created-by <caller-god> \
  --workspace scratch \
  --initial-status blocked \
  --max-runtime 5m \
  --idempotency-key "build-plan-<project_name>-t4"
```

The body file content is:

```markdown
Read the build plan: ~/pantheon/plans/{project_name}-build-plan.md
Read t3's unblock comment (operator's first review): { t_xxx.unblock_comment }

## Your task

Confirm the operator's intent before t5 fires.

The operator already saw the plan (t3's unblock comment). Now we ask explicitly: "is this plan final, and is the answer to dispatch yes?"

The t4 task is a 1-minute gate. It blocks, waits for `approved` / `cancel` / `modify <what>`, then unblocks t5.

## Path B: BLOCK immediately on claim.

```bash
hermes kanban block <t4_id> "Plan is at <path>. Reply: approved | cancel | modify <what>. (1 minute timeout.)"
```

After the operator unblocks with `approved` (or any reasonable synonym: "yes", "ship it", "go", "👍"), complete the task:

```bash
hermes kanban complete <t4_id> --result "Operator approved dispatch at <timestamp>. Comment: <unblock_comment>"
```

## Skills to load

- (none — this is a one-message gate)
```

### Step 5: Create the dispatch task (gated on t4 sign-off, auto-fires)

**CLI command (verified flags):**
```bash
BODY=$(cat /tmp/build-plan-t5-body.md)
hermes kanban create \
  "[<project_name>] dispatch the build" \
  --assignee hephaestus \
  --body "$BODY" \
  --skill kanban-orchestrator \
  --parent <t4_id> \
  --priority 8 \
  --created-by <caller-god> \
  --workspace scratch \
  --idempotency-key "build-plan-<project_name>-t5"
```

The body file content is:

```markdown
Read the build plan: ~/pantheon/plans/{project_name}-build-plan.md
Read t3's first review: { t_xxx.unblock_comment }
Read t4's final sign-off: { t_yyy.unblock_comment }

## Your task

Apply the `kanban-orchestrator` skill.

Create kanban tasks for each phase of the build per the build plan:
- One task per phase
- Wire up parent/child relationships (phase N's tasks have phase N-1's task as parent)
- Assign to the right specialists (Marvin, Iris, Thoth, etc.) per the build plan
- Set workspace kinds per the build plan (scratch, dir:, worktree)
- Set skills to load per the build plan

## Output

```bash
hermes kanban complete <t5_id> \
  --result "Dispatched N tasks across M specialists. Expected timeline: ~X weeks. Pings fire as tasks complete." \
  --metadata '{"tasks_created": N, "specialists": {"marvin": N1, "iris": N2, ...}, "phases": M, "build_plan_path": "~/pantheon/plans/<project>-build-plan.md", "first_task_id": "T-..."}'
```

This task does NOT block. It dispatches and reports.

## Skills to load

- `kanban-orchestrator`
- The build plan at the path above
```

### After all 5 tasks complete

Report to the user with a summary:
- Build plan path
- Number of tasks created
- Which specialists are involved
- Expected timeline
- Link to the kanban dashboard to follow along
- Reminder: "Pings will fire as tasks complete. You can intervene at any time by commenting on a task."

## The skill-chain contract

Each step in the chain:
1. **Runs to completion** — the skill does its full work, doesn't half-finish
2. **Writes structured metadata** — downstream tasks can read it without re-deriving
3. **Auto-progresses (Path B: t1, t2, t5) or pauses for operator (Path B: t3, t4)** — chain is gated by `parents=[]` AND `--initial-status blocked` for pause tasks
4. **Doesn't proceed past pause without unblock** — `hermes kanban unblock <id> <reason>` is the only way to advance past t3 and t4

**The operator's unblock comment carries context to the next step.** That's how the chain adapts to operator decisions:
- "Yes, that matches" → next step runs as designed
- "Modify: skip the soulforge step" → next step reads the comment and adjusts
- "Different approach entirely" → operator can re-run from step 1 by creating a new chain with a new request

## Pitfalls

**Don't run all 5 steps in one agent turn.** Each step is a separate kanban task, dispatched to its own session. The user sees checkpoints, not a single black-box execution.

**Don't skip the unblock at t3 and t4 (Path B).** Those two are the operator checkpoints. Skipping t3's unblock means dispatching a build plan the operator never read. Skipping t4's unblock means dispatching without an explicit "approved to dispatch" signal.

**It's fine to skip the operator pause at t1→t2 and t2→t3 (Path B).** When the operator has constrained the architecture, the tier-route and catalog-lookup decisions are mechanical, not architectural. The god completing t1 calls `kanban_complete` (not `kanban_block`) and t2 fires automatically. Same for t2 → t3. This is Path B by design.

**Don't use `--body-file` or `--skills` (plural) — they don't exist.** The verified CLI surface is at `references/hermes-kanban-cli-verified.md`. Common-typo flags will be rejected with `unrecognized arguments`.

**Don't use `--priority high|medium|low` — must be int.** The dispatcher sorts by `(priority DESC, created_at ASC)`. Higher int = picked first when ready. Typical scale: 5 = low, 7 = normal, 9-10 = high.

**Don't assume the worker will run if `--initial-status blocked` is set and no one unblocks.** The dispatcher won't claim blocked tasks. The chain stalls silently. Always either (a) tell the operator to expect the unblock, or (b) have a watcher god unblock on their behalf.

**Don't add steps without operator buy-in.** The 5 steps are the default. If you think the operator would benefit from an extra checkpoint (e.g., "design review before build plan"), add it — but tell them you're adding it and why.

**When the operator answers questions + requests changes during a Path B pause, prefer rewriting the plan to v1.X over 50 scattered patches (operator-shaped signal 2026-06-16, Conductor UI build; same pattern in the Hephaestus rework doc 2026-06-16).** A t3 plan can have 100+ references that need updating (file paths, owner columns, decisions tables, time-estimate cleanup, role swaps, QA gate additions, framing corrections). Patching them one-by-one with the patch tool is fragile (each call has to pass the WikiGuard heuristic, and the failure mode is "patch rejected as low-quality, retry with more context"). The cleaner move: write the plan to v1.1 (or v1.X) with all the operator's answers + changes applied in one pass, then `write_file` the whole thing. This is a `t3`-side technique — when t3 unblocks with operator answers, the t3 worker should treat it as a re-authoring pass, not a series of edits. The signal: if the operator's unblock comment contains 3+ distinct changes (e.g., "swap Hephaestus for Marvin + add QA gate + remove time estimates + mock is at local path" or "you're conflating planner with executor; he builds, not plans"), rewrite the plan. The audit trail is preserved in the version number + a "v1.X changes summary" section at the bottom. **Two real instances of this pattern have now happened (the conductor-ui plan v1.0 → v1.1 and the hephaestus-rework-workflow-god.md → v1.1) — it's a class signal, not a one-off.**

**Don't dispatch without a final read.** The operator should have at least seen the build plan path and the dispatch summary before the kanban tasks fan out. The "approved" unblock is the gate.

**Don't make the operator unblock with the right words.** Accept any reasonable unblock: "yes", "approved", "looks good", "ship it", "👍" — all mean the same thing. Don't make them type "approved" exactly. The skill interprets the unblock, not just the literal text.

**After a one-liner sign-off, execute the FULL plan — do not re-ask, do not re-summarize, do not surface the plan again (operator directive, 2026-06-22).** Konan's sign-off pattern: when a plan is presented with 3-4 numbered recommended defaults and the operator replies with a one-liner like "yeah do the recommended" / "approved" / "ship it" / "go" / "👍", the contract is to proceed with ALL of the recommended defaults. The plan file at `~/pantheon/plans/*.md` is the durable record — it was already presented, the operator already read it (or chose not to), and the sign-off is the green light. Re-prompting with "which option do you want?" after a one-liner sign-off is the failure mode. The right move: dispatch, then report what was dispatched. **Corollary:** if the sign-off includes a *specific* exception ("yeah do the recommended, except use Postgres not SQLite"), honor the exception and proceed with the rest. The exception is the operator's only input; everything else is "yes." This applies to ALL plan-shaped outputs (build plans, configuration choices, recommendation lists, default selections) — the operator's one-liner after a plan is the contract, not a conversational pause.

**`hermes kanban unblock <id> "<text>"` does NOT deliver the text to the worker — it is treated as a silent unblock (operator trap, Conductor UI build 2026-06-16).** The worker prompt explicitly says "silent unblock = approval on next spawn." Passing "approved" as the unblock command's text argument does NOT make the worker see "approved" — the worker re-spawns and re-blocks with the same prompt. The text-arg is treated as a comment-attachment, not a worker-reply. The correct pattern to deliver an answer to a blocked worker is:

1. `hermes kanban comment <task_id> "approved"` — adds the answer as a comment the worker reads
2. `hermes kanban unblock <task_id>` — the unblock itself (no text needed; or with the same text for the audit trail)

This bit me twice in one chain (Conductor UI build t4 runs #22, #23, #24). Each `unblock` with text-arg re-spawned the worker. The fix is: **always `comment` first, then `unblock` (no text)**. The worker reads the comment on next claim. Any agent running a Path B chain should use this pattern when relaying operator sign-offs to blocked workers.

**`hermes kanban edit` cannot change a task's `skills` list — use SQLite directly (tool gap, Conductor UI build 2026-06-16).** If a dispatched task loads skills the assignee's profile doesn't have installed (e.g., t5 loaded `build-spec-authoring` + `thoth-qa-gate` for Iris's Phase 0 task, but Iris's profile doesn't have them — the worker crashed with "Unknown skill(s):" on spawn), the fix is direct SQLite intervention:

```python
import sqlite3
conn = sqlite3.connect('/home/konan/.hermes/kanban.db')
conn.execute("UPDATE tasks SET skills=? WHERE id=?",
            ('["pantheon-dev-workflow", "olympus-ui"]', 't_xxx'))
conn.commit()
```

The `assign` subcommand changes the assignee; the `edit` subcommand only takes `--result/--summary/--metadata`; neither has a `--skills` flag. **Future tool fix:** `hermes kanban edit` should accept `--skills` (or a dedicated `hermes kanban skills <id> --add/--remove` subcommand). Until then, SQLite is the only path. The failure mode looks like the worker's first spawned run dies immediately with `Error: Unknown skill(s): <name>` and `gave_up` after the failure_limit — distinct from a profile-level crash and recoverable by stripping the missing skills + reassigning to a profile that has them. See pitfall "Skill name collisions break workers silently" for the related diagnostic pattern.

**Don't create the chain if the project is too small.** If the build request is "add a button to the dashboard," that's a 1-line change. Don't create a 5-step chain for that. Use the `plan-to-build` skill or just do it.

**Don't write time estimates into plans or reports (operator directive, 2026-06-16).** Konan has corrected this explicitly: "stop giving me time estimates, they're always wrong, you keep ballooning your time estimates telling me it's going to take weeks when it takes you know maybe a day." This means:
- No "X days", "X weeks", "~X minutes", "~X hours" in build plan timelines, t3 reports, t5 dispatch summaries, or final skill reports.
- No "expected to complete by Friday" or "should ship in 2-3 weeks" anywhere.
- In t3's "Build plan written to <path>" report, replace the "estimated_weeks" field with operational state: "N phases, M tasks, P specialists. Pings fire as tasks complete."
- In t5's "Dispatched N tasks..." report, replace the "expected timeline" with: "Pings fire as tasks complete. You can intervene at any time by commenting on a task."
- The only legitimate time reference is a critical-path dependency ("Phase 2 cannot start until Phase 1's verification gate passes"), not a calendar duration.
- If the operator asks "how long will this take?", the right answer is "I'll know when the phases are done — I'll report per phase" or "the chain has X operator checkpoints, you'll have to make X decisions."

**Every code-producing kanban task must have a Thoth QA follow-on (operator-locked 2026-06-16).** Konan's rule: "we need to make sure there are QA checks — Thoth on all code produced — before sign off and going to the next task." This means:
- Any kanban task created by Step 5's dispatch (or by `kanban-orchestrator` generally) that has `Action: CREATE` or `Action: MODIFY` for `.ts`, `.tsx`, `.js`, `.jsx`, `.py`, `.rs`, `.go`, `.sh`, or any other code file MUST have a follow-on `Action: REVIEW` task assigned to `thoth` as a child task.
- The reviewer task is automatically created at dispatch time with the same parent chain as the coder task. The reviewer task is the one that "completes" the build step — the coder task is not done until the reviewer signs off.
- The reviewer task loads the `code-review` skill (or equivalent) and produces a structured review: `pass | pass_with_notes | needs_changes | block`. `block` halts the chain until operator decision.
- For Phase 0 (foundation, scaffold) tasks, the reviewer is **lighter** — verify the scaffold matches the spec, no broken imports, types pass. Don't over-review trivial scaffolding.
- For Phase 4+ (soulforge, ledger, integration), the reviewer is **deeper** — verify behavior matches contract, edge cases handled, docs updated.
- The dispatch metadata in t5 must include a `qa_tasks_created: N` field alongside `tasks_created: N`.
- See `Codex-Pantheon/design/qa-gate-design.md` (TBD) for the full review rubric per phase.

**All build plans produced by this chain must use `/home/konan/projects/<project-name>/` as the project root for the *built artifact* (operator-locked 2026-06-16).** See [Build Path Convention] in `Codex-Pantheon/design/build-path-convention.md`. The convention exists because `~/pantheon/` is system source, not build output. **Important distinction:**

- **Build plan document** (the markdown plan) lives at `~/pantheon/plans/<project>-build-plan.md` — this IS system infrastructure (it's the operator-facing plan, lives in the same place as all other plans).
- **Project code** (the actual deliverable) lives at `/home/konan/projects/<project-name>/` — this is the build output.
- **Reference link in the plan**: the plan's title block must declare the project root as `/home/konan/projects/<project-name>/` (the *build*, not the *plan*).

The t3 task body (Step 3 above) must distinguish these two paths. If a build plan arrives at t3 with `~/pantheon/<project>/` paths in its file-by-file table, the t3 worker must rewrite those to `~/projects/<project>/` before declaring the plan complete — the operator should not have to hand-patch this. **However, the plan document's own path (`~/pantheon/plans/...`) stays as-is — that's system source, not build output.**

**Skill name collisions break workers silently.** If a task crashes immediately with `Error: Unknown skill(s): <name>` even though the file exists, check BOTH the skill directory AND the `references/` directories of OTHER skills for files with the same name. Reference docs that share a name with a real skill will be rejected by the loader. See `references/skill-name-collision-failure-mode.md` for the full failure mode + recovery.

**Mid-flight priority bumps need SQLite, not the CLI.** `hermes kanban edit` only works on completed tasks. To bump priority on a running task, use the SQLite escape hatch in `references/hermes-kanban-cli-verified.md` (and write a `priority_changed` event in the same transaction for the audit trail).

## Examples

### Example 1: Mercer outreach sequence (the canonical use case, Path A)

```
You: "I want to build a Mercer outreach sequence that sends a LinkedIn
     message, waits 2 days, sends a follow-up email, waits 3 days, then
     creates a task for a phone call. Stop if the prospect replies."

[Skill creates the 5-task chain with project_name="mercer-outreach" using Path A]

[t1] tier-route: 
  "Recommendation: Conductor YAML for the sequence with `wait` steps +
   kanban task for the phone call (because it needs human judgment).
   Pattern: approval_gated + scheduled. 
   Complexity: medium. Specialists: Mercer, Thoth."
  → Block: "Does that match your intent?"
  
[You]: "yes"

[t2] catalog lookup:
  "Best match: morning-briefing.yaml (similar: scheduled + approval gate).
   Also: forge-overnight-research.yaml (similar: approval card pattern)."
  → Block: "Clone morning-briefing, scratch, or extend another?"

[You]: "scratch — this is different enough from morning-briefing"

[t3] write build plan:
  "Build plan at ~/pantheon/plans/mercer-outreach-build-plan.md. 
   4 phases over 2 weeks. 6 tasks. 1 open question about the LinkedIn API."
  → Block: "Read it. Approved?"

[You]: "approved, but use the LinkedIn API v2 not v1"

[t5] dispatch:
  "Dispatched. 6 tasks. Mercer has 4, Thoth has 2. 
   First task T-1234 starts now. 
   Pings as tasks complete."

[Skill reports to you with the summary]
```

### Example 2: Conductor UI build (Path B — the recommended default)

```
You: "Convert this to a build plan: Conductor UI. Iris has built a mock,
     we want to convert it to a full project using the framework. Wire all
     the conductor and kanban features in. Visual workflow editor with
     Soulforge interview process for new nodes."

[Skill creates the 5-task chain with project_name="conductor-ui" using Path B]

[Skill dispatches all 5 tasks immediately with `--parent` chain linking.
 t3 and t4 use `--initial-status blocked` to wait for operator.]

[t1] tier-route (auto-fires):
  7-dim recommendation in 90s. Hybrid T2+T1, fan-out-with-gates pattern,
  Soulforge as both UI surface and workflow tool, Ledger-shaped from day 1.

[t2] catalog lookup (auto-fires after t1):
  5 matches. Best fit: build-plan-conversion (0.92). Plus fan-out-then-merge
  for parallel surfaces, approval-gated for phases, bug-fix adapted as
  runtime pattern.

[Chain pauses at t3. Watcher god (Thoth) messages operator:
 "t2 done. Unblock t3 to write the plan?"]

[You]: hermes kanban unblock t_aeb9804a 'looks good, write the plan'

[t3] write build plan (fires after unblock):
  "Plan at ~/pantheon/plans/conductor-ui-build-plan.md. 5 phases, ~6 weeks.
   Phases: research-and-spec → design-system → backend-foundation →
   frontend-conversion → soulforge-subsystem → integration-and-tests → ship.
   1 open question: which CLI tool for parallel branches."
  → Block: "Read it. Approved?"

[You]: "approved"

[Chain pauses at t4. Watcher messages: "t3 done. Unblock t4 to dispatch?"]

[You]: hermes kanban unblock t_9b067dde 'ship it'

[t4] sign-off (fires after unblock):
  Records the approval event. Auto-completes.

[t5] dispatch (auto-fires after t4):
  "Dispatched 6 tasks across 5 specialists. Iris has 3, Marvin has 1,
   Hephaestus has 1, Thoth has 1, Caduceus has 1. First task T-xxxx
   starts now."

[Skill reports to operator with summary]
```

## Reference index

- `references/hermes-kanban-cli-verified.md` — **canonical** CLI surface (flags, parent-gating, priority mutation, external_dirs bug). If the SKILL.md body contradicts this file, the reference wins.
- `references/kanban-task-shapes.md` — canonical kanban task shapes per workflow type
- `references/conductor-yaml-templates.md` — common Conductor YAML patterns the build plan can reference
- `references/example-chains.md` — full examples of past build-plan-orchestrator runs
- `references/skill-name-collision-failure-mode.md` — what to do when a worker crashes with `Error: Unknown skill(s):` because a reference doc shadows a real skill
- `references/test-board-routing.md` — routing test work to `test_board_xyz` instead of the default board (avoids polluting production)
- `references/external-workflow-patterns.md` — patterns from outside the catalog that informed this design
- `references/mid-dispatch-scope-shifts.md` — the 4 patterns for adjusting scope after t5 has dispatched (fold planning artifact into build phase, strip skills + reassign, defer already-shipped work, drop redundant tasks). Conductor UI 2026-06-16 case study.

## Related skills

- **`workflow-tier-routing`** — the routing rules used in step 1
- **`workflow-catalog-lookup`** — the catalog search used in step 2
- **`pantheon-dev-workflow`** — the build-plan authoring skill used in step 3
- **`build-spec-authoring`** — the file-by-file spec skill used in step 3
- **`kanban-orchestrator`** — the dispatch logic used in step 5
- **`plan`** — the planning structure used in step 3
- **`thoth-codesign-brainstorm`** — for early-stage exploration BEFORE this skill (use when the user doesn't have a concrete build request yet)

## Changelog

### v1.0.7 (2026-06-22)

- **New pitfall entry: "After a one-liner sign-off, execute the FULL plan — do not re-ask."** Codifies Konan's sign-off pattern: when a plan is presented with 3-4 numbered recommended defaults and the operator replies with a one-liner like "yeah do the recommended" / "approved" / "ship it" / "go" / "👍", the contract is to proceed with ALL of the recommended defaults. The plan file is the durable record; the sign-off is the green light. Re-prompting with "which option do you want?" is the failure mode. Includes the corollary: a specific exception in the sign-off is honored, everything else defaults to "yes." Generalizes beyond build plans to all plan-shaped outputs (configuration choices, recommendation lists, default selections).

### v1.0.6 (2026-06-16)

- **Two new pitfall entries** capturing real failures from the Conductor UI build dispatch (2026-06-16):
  1. **`hermes kanban unblock <id> "<text>"` does NOT deliver text to the worker** — it's treated as a silent unblock. The worker re-spawns and re-blocks with the same prompt. The correct pattern is `comment <id> "answer"` first, then `unblock` (no text). This bit me twice in one chain (t4 runs #22, #23, #24). The pitfall is a class signal — any Path B chain will hit it.
  2. **`hermes kanban edit` cannot change a task's `skills` list** — the only way to fix a task that loaded skills the assignee's profile doesn't have is direct SQLite UPDATE on `tasks.skills`. The `assign` subcommand changes the assignee; the `edit` subcommand only takes `--result/--summary/--metadata`. Future tool fix: `hermes kanban edit --skills` (or a dedicated `skills` subcommand). Until then, SQLite is the only path.
- **New reference doc:** `references/mid-dispatch-scope-shifts.md` — the 4 patterns (fold / strip-reassign / defer / drop) for adjusting scope after t5 has dispatched. Conductor UI 2026-06-16 case studies for all 4.

### v1.0.5 (2026-06-16)

- **Hephaestus rework is now ACTIVE.** Removed the "future note" qualifier from v1.0.4. Hephaestus (God of Building and Architecture) is now the active default assignee for steps 1, 2, 3, 5. Step 4 (final sign-off gate) stays `thoth`.
- **Updated CLI examples** for t1 (tier-route), t2 (catalog-lookup), t3 (write-plan), and t5 (dispatch) from `--assignee thoth` to `--assignee hephaestus`.
- **Updated kanban-orchestrator pantheon-god-roster reference** — Hephaestus entry now reflects the new role (Building + Architecture, chain dispatch, convention enforcement, architecture design, design review). Review routing rules updated: code review → `thoth` (QA gate), architecture review → `hephaestus`.

- **Clarified the build-path convention** to distinguish the *plan document path* (`~/pantheon/plans/...` — stays as-is, this is system source) from the *project code path* (`/home/konan/projects/<project>/` — the build output). Previous version conflated the two. See pitfall entry below "All build plans produced by this chain must use..." for the corrected wording.
- **Added the QA-gate requirement** (Thoth reviews all code before sign-off). All kanban tasks produced by Step 5's dispatch that involve `Action: CREATE` or `Action: MODIFY` for code files must include a follow-on `Action: REVIEW` task assigned to `thoth` as a child of the coder task. The reviewer task blocks until the coder task completes; the coder task is not considered done until the reviewer task passes. See pitfall entry "Every code-producing kanban task must have a Thoth QA follow-on".
- **Added the "Hephaestus post-rework as primary orchestrator" future-note** under Path A/B/C. When Hephaestus is reworked to own the three-layer orchestration system (planned for 2026-06-16), the default assignee for steps 1, 2, 3, 5 in this chain will flip from `thoth` to `hephaestus`. Step 4 (final sign-off, a gate) stays `thoth` because it's an operator-in-the-loop artifact, not an orchestration decision. For now (pre-rework), the chain runs with `thoth` as the default assignee on all 5 steps.
- **Added the "agent should raise concerns inline" philosophy note** to the operator-pause design. The 5-step kanban chain is one valid shape, but the *agent* (Hephaestus post-rework, or Thoth pre-rework) is the primary orchestration point. Many concerns — paths, tech choices, naming, ownership, QA gates — can be raised by the agent in real-time conversation rather than surfaced as a 5-step chain. Use this skill for **build plans that need the full ceremony** (multi-week builds, multi-specialist coordination, high-stakes decisions). Use direct agent conversation + kanban dispatch for **simple builds** (single-coder, short scope, low-stakes). Don't over-formalize small things.

### v1.0.3 (2026-06-16)

- **Fixed CLI flag errors in all 5 step examples.** Replaced `--body-file <path>` with `--body "$BODY"` (the verified pattern) and `--skills name1,name2` (plural, comma-joined) with repeated `--skill name1 --skill name2` (singular, repeated). These flags did not exist on the CLI and were rejected with `unrecognized arguments`.
- **Added "CLI Surface — READ FIRST" warning at the top** with the most common errors a god makes when running this skill (body-file, skills plural, priority string, edit-on-running-task gap).
- **Added `--initial-status blocked` to the Path B mechanics.** The previous version relied on workers calling `kanban_block` after claiming; this version documents the cleaner pattern of creating pause tasks already blocked and having the operator (or watcher) unblock.
- **Updated Step 3 body template** to use `{ t_xxx.result.metadata }` syntax consistently (was inconsistent across steps).
- **Removed the duplicate "### Step 4: Final sign-off" header** that was left over from the v1.0.0 → v1.0.1 transition.
- **Added 3 new pitfall entries:** skill name collisions, mid-flight priority bumps, blocked-status stalls.
- **Added 2 new examples to the reference index:** `skill-name-collision-failure-mode.md` and `external-workflow-patterns.md`.
- **Added the "Conductor UI build" Path B example** as Example 2 — this is the run that motivated the v1.0.3 corrections.

### v1.0.2 (2026-06-16)

- **Added Path A / Path B / Path C operator-pause variants** to the top of the skill. Path B (2 pauses: t3 + t4) is the new default. Path A (4 pauses, original v1.0.0 design) is opt-in for ceremonial builds. Path C (0 pauses, auto-fire) is opt-in for trusted/low-stakes builds.
- **Updated pitfall "Don't skip the block"** to clarify that skipping the block at t1→t2 and t2→t3 is fine in Path B (the operator has constrained those decisions). Skipping the block at t3 or t4 is still forbidden.
- **Updated Examples section** to add a Path B example (the `conductor-ui` build that motivated this version).
- **Updated the related-skills index** to add the new references subfolder.

### v1.0.1 (2026-06-16)

- **Replaced non-existent Python `hermes_tools.kanban_create` API** in all step bodies with the real Hermes CLI surface: `hermes kanban create/complete/block ...`. The skill is now translatable against the actual CLI.
- **Added the API Surface Note at the top** documenting the translation pattern (Python pseudo-code blocks are intent specs, not runnable code).
- **Made t4 (final sign-off) the default** as a separate task gated on t3, with a 1-minute timeout. Inline sign-off is still noted as an option for future v1 returns.
