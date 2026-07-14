---
name: convention-enforcer
description: "Use when Hephaestus is about to dispatch a build plan or when a god is about to ship a change. Scans plans and code for convention violations: build paths, naming, ownership, QA gates, time estimates, missing owner comments. Catches drift before it ships."
version: 1.0.0
tags: [conventions, enforcement, validation, gates, hephaestus, thoth]
---

# Convention Enforcer — Catches Drift Before It Ships

> **The skill that scans plans and code against the conventions canon, catches violations, and either auto-fixes or reports.** Hephaestus uses this at dispatch time. Thoth uses this at review time. Catches drift before it ships.

## When to use this skill

Load this skill whenever:

- Hephaestus is about to dispatch a build plan (per `plan-execution`)
- Hephaestus is about to dispatch a one-off task (per `kanban-orchestrator`)
- Thoth is reviewing a plan (per `qa-gate-rubric.md` phase 0 review)
- Thoth is reviewing code (per `qa-gate-rubric.md` phase 1+ review)
- The operator asks "is this plan compliant?"
- A new convention is added (the enforcer needs to know the new rule)

**Don't use this skill for:**

- Writing conventions (that's the convention-doc-shape standard)
- Authoring plans (that's the build-plan-orchestrator's t3)
- Coding (that's Marvin)

## How to use it (the procedure)

### Step 0: Load the conventions canon

Before scanning, load the operator-locked rules:

1. **`Codex-Pantheon/design/operator-rules-cheatsheet.md`** — the 10 rules
2. **`Codex-Pantheon/design/build-path-convention.md`** — the build path rule
3. **`Codex-Pantheon/design/standards/`** — the 10 standards
4. **`Codex-Pantheon/design/standards/qa-gate-rubric.md`** — the per-phase rubric
5. **`Codex-Pantheon/standards/tailscale-serve-link-convention.md`** — the Tailscale Serve link rule
6. **`pantheon/shared/decisions/INDEX.md`** — the most recent operator decisions

The canon is the source of truth. The enforcer doesn't decide what's a violation — the canon does.

### Step 1: Identify the target

The enforcer scans one of:

- **A plan** — `~/pantheon/plans/<project>-build-plan.md`
- **A code file** — `<path-to-file>.ts`, `.py`, etc.
- **A chain of tasks** — `hermes kanban list --parent <id> --json`
- **A god profile** — `~/.hermes/profiles/<name>/SOUL.md`

Pass the target as the input to the skill.

### Step 2: Run the checks

The enforcer runs **12 checks**, organized by the 11 operator-locked rules. Each check is binary: pass or fail.

#### Check 1: Build Path Convention

**Rule:** Build plans live at `~/pantheon/plans/<project>-build-plan.md`. Project code lives at `/home/konan/projects/<project>/`.

**Detection (for plans):**

```bash
# The plan's title block should declare the project root
grep "Project root:" <plan> | grep -E "^\*\*Project root:\*\* \`/home/konan/projects/<project>/\`"
```

**Detection (for code):**

```bash
# Code files should be in /home/konan/projects/<project>/, not in ~/pantheon/
grep "^// owner:" <file>  # the file should be in a project, not in system source
```

**Response on fail:** the path is wrong. Report: "Build path convention violation: <where it is> should be <where it should be>."

#### Check 2: QA Gate Rule

**Rule:** Every code-producing task has a Thoth review follow-on.

**Detection:**

```bash
# For each CREATE/MODIFY code task, check for a review follow-on
sqlite3 ~/.hermes/kanban.db "
SELECT t1.id, t1.title
FROM tasks t1
WHERE (t1.title LIKE 'CREATE%' OR t1.title LIKE 'MODIFY%' OR t1.title LIKE 'Action: CREATE%' OR t1.title LIKE 'Action: MODIFY%')
  AND t1.assignee = 'marvin'
  AND NOT EXISTS (
    SELECT 1 FROM task_links
    WHERE parent_id = t1.id AND assignee = 'thoth'
  );"
```

**Response on fail:** the task is missing its QA review. Report: "QA gate violation: task <id> has no Thoth review. Should the enforcer create one, or should this task be a non-code task?"

#### Check 3: No Time Estimates

**Rule:** No calendar durations in plans, reports, or skill outputs.

**Detection (for plans):**

```bash
# Look for time-estimate patterns
grep -E "(\b[0-9]+ (days?|weeks?|months?|hours?|minutes?)\b|\bby (Friday|Monday|Tuesday|Wednesday|Thursday|Saturday|Sunday|tomorrow|next week|next month)\b|expected to (complete|ship|finish)|should ship in)" <plan>
```

**Detection (for code, comments, reports):**

```bash
grep -E "(\b[0-9]+ (days?|weeks?|months?)\b|by (Friday|tomorrow|next week))" <file>
```

**Response on fail:** the time estimate is present. Report: "Time estimate violation: '<the match>' found at <location>. Replace with scope summary (phases, tasks, builders) per the no-time-estimates rule."

#### Check 4: Hephaestus Role Boundaries

**Rule:** Hephaestus does NOT write production code. Hephaestus does NOT develop plans.

**Detection (in the file-by-file table of a plan):**

```bash
# If Hephaestus is the Owner of a CREATE or MODIFY code file, that's a violation
grep "CREATE\|MODIFY" <plan> | grep "Hephaestus"
```

**Detection (in a kanban task):**

```bash
# If Hephaestus is the assignee of a code-producing task, that's a violation
sqlite3 ~/.hermes/kanban.db "
SELECT id, title, assignee
FROM tasks
WHERE assignee = 'hephaestus'
  AND (title LIKE '%CREATE%' OR title LIKE '%MODIFY%' OR title LIKE '%implement%' OR title LIKE '%scaffold%' OR title LIKE '%code%');"
```

**Response on fail:** the role boundary is violated. Report: "Hephaestus role violation: <where>. Hephaestus is the conductor, not the coder or planner. Re-assign to Marvin (code) or re-author the plan (planner = Konan + Thoth)."

#### Check 5: Sovereignty Guardrail

**Rule:** External events must not auto-execute.

**Detection (in a workflow YAML):**

```bash
# Look for NATS publishes without operator approval
grep -B 2 "nats.publish" <workflow-yaml> | grep -v "operator_approval: required"
```

**Detection (in a Conductor workflow):**

```bash
# Look for handlers that don't check operator approval
grep -A 5 "on_message\|on_event" <workflow-yaml> | grep -v "check_operator_approval"
```

**Response on fail:** the sovereignty guardrail is missing. Report: "Sovereignty violation: <workflow> auto-executes on external event without operator approval. Per the sovereignty rule, add a check_operator_approval step."

#### Check 6: Plan Has 13 Sections

**Rule:** Plans follow the build-plan-shape (13 sections).

**Detection:**

```bash
# Look for the 13 section headers
for section in "Provenance" "Tier routing" "Similar workflows" "Foundation" "Phased implementation" "File-by-file" "Tests + verification" "Decisions applied" "Phase scope" "Pitfalls" "Post-build" "Operator sign-off"; do
  grep -q "^## .*$section" <plan> || echo "MISSING: $section"
done
```

**Response on fail:** sections are missing. Report: "Plan shape violation: missing sections <list>. Per the build-plan-shape standard, the plan needs the 13 sections."

#### Check 7: Tasks Have 9 Fields

**Rule:** Tasks follow the kanban-task-shape (9 fields).

**Detection:**

```bash
# Check that every task has title, body, assignee, skills, parent, priority, metadata, status
sqlite3 ~/.hermes/kanban.db "
SELECT id, title
FROM tasks
WHERE (body IS NULL OR body = '')
   OR (assignee IS NULL OR assignee = '')
   OR (priority IS NULL);"
```

**Response on fail:** tasks are missing fields. Report: "Task shape violation: task <id> is missing <field>. Per the kanban-task-shape standard, all 9 fields are required."

#### Check 8: Reviews Use the Design-Review Shape

**Rule:** Every Thoth or Hephaestus review has the 5-field design-review shape.

**Detection (in a review file or comment):**

```bash
# Check that the review has verdict, findings, risks, recommendations, pass_criteria
grep -E "^verdict: (pass|pass_with_notes|needs_changes|block)$" <review>
grep -E "^findings:" <review>
grep -E "^risks:" <review>
grep -E "^pass_criteria:" <review>
```

**Response on fail:** the review is malformed. Report: "Review shape violation: review <id> is missing <field>. Per the design-review-shape standard, all 5 fields are required."

#### Check 9: Handoffs Use the God-Handoff Shape

**Rule:** Every god-to-god handoff has the 5 fields.

**Detection (in a kanban comment):**

```bash
# Check that the handoff comment has from, to, artifact, context, next_step
grep -E "^  from: " <comment>
grep -E "^  to: " <comment>
grep -E "^  artifact: " <comment>
grep -E "^  context:" <comment>
grep -E "^  next_step: " <comment>
```

**Response on fail:** the handoff is malformed. Report: "Handoff shape violation: comment on task <id> is missing <field>. Per the god-handoff-shape standard, all 5 fields are required."

#### Check 10: Owner Comments in Code

**Rule:** Every code file has a `// owner: <god>` comment at the top.

**Detection:**

```bash
# For each code file in the project, check the first 5 lines
for file in $(find /home/konan/projects/<project> -type f \( -name "*.ts" -o -name "*.tsx" -o -name "*.py" -o -name "*.rs" -o -name "*.go" -o -name "*.sh" \)); do
  head -5 "$file" | grep -q "// owner:" || echo "MISSING: $file"
done
```

**Response on fail:** the file is missing its owner comment. Report: "Owner comment violation: file <path> is missing the `// owner: <god>` comment. Add it to the top 5 lines."

#### Check 11: Convention Existence

**Rule:** The operator-locked rules canon is complete and discoverable.

**Detection:**

```bash
# Check that the 4 canon files exist
test -f ~/athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md || echo "MISSING: operator-rules-cheatsheet.md"
test -f ~/athenaeum/Codex-Pantheon/design/build-path-convention.md || echo "MISSING: build-path-convention.md"
test -d ~/athenaeum/Codex-Pantheon/design/standards/ || echo "MISSING: standards/"
test -f ~/athenaeum/Codex-Pantheon/design/INDEX.md || echo "MISSING: design/INDEX.md"
```

**Response on fail:** the canon is incomplete. Report: "Convention canon violation:   is missing. The enforcer cannot run without the full canon."

#### Check 12: Tailscale Serve Link Convention

**Rule:** Every `localhost` or `127.0.0.1` link given to Konan must be replaced by a Tailscale Serve URL (`https://pantheon-laptop.tail164759.ts.net/[...]`).

**Detection (in a response, comment, or documentation):**

```bash
# Scan for raw localhost links in chat, docs, or build output
grep -E "(http://localhost:[0-9]+|http://127\.0\.0\.1:[0-9]+)"   || echo "PASS: no localhost links found"
```

**Detection (in a kanban task body or comment):**

```bash
sqlite3 ~/.hermes/kanban.db "
SELECT id, title, body
FROM tasks
WHERE (body LIKE '%localhost:%' OR body LIKE '%127.0.0.1:%')
  AND assignee NOT LIKE 'konan';"
```

**Response on fail:** a localhost link was found. Report: "Tailscale link convention violation: raw localhost link found in  . Replace with `https://pantheon-laptop.tail164759.ts.net/` format. See `Codex-Pantheon/standards/tailscale-serve-link-convention.md`."

### Step 3: Aggregate the results

The enforcer produces a structured report:

```yaml
enforcement_report:
  target: <plan or file or chain>
  timestamp: <ISO>
  total_checks: 11
  passed: <count>
  failed: <count>
  violations:
    - check: <check-name>
      severity: high | medium | low
      location: <where the violation is>
      message: <what's wrong>
      fix: <what to do>
```

**Severity:**
- `high` — blocks dispatch. The plan/task is not ready.
- `medium` — sends a warning. The plan can dispatch but the issue should be fixed in a follow-up.
- `low` — informational. The plan can dispatch; the enforcer just notes it.

### Step 4: Report + act

**On any `high` violation:** Hephaestus does NOT dispatch. Reports to the operator, lists the violations, asks for direction.

**On `medium` violations:** Hephaestus dispatches but logs the violations to `pantheon/shared/decisions/` for follow-up. The next task in the chain may fix them.

**On `low` violations:** Hephaestus dispatches and notes them. No follow-up needed unless the violation pattern recurs.

**On no violations:** Hephaestus dispatches and reports "Plan is compliant. Dispatching."

### Step 5: Update the enforcer

When a new convention is added (operator-locked), the enforcer's checks are updated:

1. Add the new check to the `Step 2` list
2. Update the canon load in `Step 0`
3. Update the severity classification
4. Test the new check against a sample plan

The enforcer is **Hephaestus's tool**, not a god. The enforcer doesn't decide conventions; Hephaestus applies the operator-locked ones.

## Worked example

The conductor-ui build v1.1 plan, before dispatch:

- **Check 1 (build path):** PASS — project root is `/home/konan/projects/conductor-ui/`
- **Check 2 (QA gate):** PASS — Thoth review follow-ons are generated at dispatch
- **Check 3 (no time estimates):** PASS — the plan was rewritten to remove all calendar durations
- **Check 4 (Hephaestus role):** PASS — all code production is Marvin's
- **Check 5 (sovereignty):** PASS — no NATS auto-execute in the plan
- **Check 6 (plan has 13 sections):** PASS — the plan follows the build-plan-shape
- **Check 7 (tasks have 9 fields):** not applicable at plan time (tasks are created at dispatch)
- **Check 8 (reviews use design-review shape):** not applicable at plan time (reviews are at review time)
- **Check 9 (handoffs use god-handoff shape):** not applicable at plan time
- **Check 10 (owner comments):** not applicable at plan time
- **Check 11 (convention existence):** PASS — all canon files exist
- **Check 12 (tailscale links):** PASS — no localhost links found in the plan

The enforcer reports: "Plan is compliant. Ready to dispatch."

## Pitfalls

**Don't false-positive.** A check that flags every plan is useless. The checks are specific.

**Don't false-negative.** A check that misses a real violation is worse than no check. Test the checks.

**Don't make the enforcer the source of truth.** The canon is the source. The enforcer applies it.

**Don't auto-fix without reporting.** Auto-fixing can hide the violation. Report first, then ask if the auto-fix is OK.

**Don't run the enforcer on every change.** Run it at gates (plan dispatch, code review, ship). Not on every file save.

## Verification gates

The enforcer is "working" when:

- [ ] All 11 checks are implemented and tested
- [ ] The canon load in Step 0 is correct
- [ ] The severity classification is consistent
- [ ] The report format is parseable
- [ ] False-positive rate is < 5%
- [ ] False-negative rate is < 1%
- [ ] The enforcer runs in < 30 seconds for a typical plan

## See also

- `Codex-Pantheon/design/operator-rules-cheatsheet.md` — the 10 rules the enforcer applies
- `Codex-Pantheon/design/build-path-convention.md` — the build path rule
- `Codex-Pantheon/design/standards/` — the 10 standards
- `Codex-Pantheon/design/standards/build-plan-shape.md` — what a plan looks like
- `Codex-Pantheon/design/standards/kanban-task-shape.md` — what a task looks like
- `Codex-Pantheon/design/standards/design-review-shape.md` — what a review looks like
- `Codex-Pantheon/design/standards/god-handoff-shape.md` — what a handoff looks like
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — the dispatching counterpart
