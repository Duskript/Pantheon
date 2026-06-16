# Build-Plan-Builder — Skill Spec

**From:** Hermes (PM)
**To:** Konan (operator), Thoth, Hephaestus
**Status:** DRAFT for ratification (test target: Conductor v2 closeout)
**Author:** Hermes, 2026-06-15T17:30Z

---

## Why this skill exists

Today: one growing `BUILD-PLAN.md` ("cluttered desk"). Every PM-loop turn scans the whole file. Memory is the implicit state, and the 2,200-char memory cap is a constant tax.

Goal: **the build plan is the executable spec.** Master + sub-plans, structured (YAML frontmatter + Markdown body), parseable by a runner skill. Memory becomes a cache, not a source of truth.

## Scope (operator-locked 2026-06-15 17:30Z)

- **Builders** (who can scaffold a build plan): Konan (operator), Hermes (PM), Thoth (research input), Hephaestus (engineering input).
- **Consumers** (who reads the plan, doesn't write it): Marvin, Iris, the gods who run dispatches, the `pm-loop-runner` skill.
- **Out of scope:** God-skill authoring skills (`writing-plans`, `test-driven-development`, etc.). Those produce deliverables, not plans.

## Artifacts (file layout)

```
~/pantheon/plans/
├── _index.yaml                       # all projects, by id
├── <project-id>/
│   ├── master.yaml                   # project tree, sub-plan list, current pointer
│   ├── <sub-plan-id>.yaml            # one sub-plan per file
│   ├── briefs/                       # 3 briefs per step, sliced for god dispatch
│   │   └── <sub-plan-id>-step-<n>-<god>-<phase>.yaml
│   └── reviews/                      # final-review outputs
│       └── <sub-plan-id>-final-review.md
└── templates/
    ├── master-template.yaml
    ├── subplan-template.yaml
    ├── brief-template.yaml
    └── review-template.md
```

One project per folder. No mega-master. Each project has its own `master.yaml` + sub-plan YAMLs.

## Master plan structure

```yaml
---
plan_id: conductor-v2
plan_title: "Conductor v2 — Sovereign Workflow Engine"
created: 2026-06-15
last_updated: 2026-06-15T17:30Z
owner: konan
pm: hermes
status: in_progress
current_subplan: phase-4-quarantine-sovereign
total_subplans: 5
gods_involved: [marvin, thoth, hephaestus]
file_dependency_map: |
  /home/kohan/pantheon/conductor/v2/engine.py
    - depends on: SOVEREIGN_OUTBOUND_RE (engine.py:157), _has_operator_approval (engine.py:179)
    - depended on by: workflows/*.yaml (notify-enterprise, sovereign-publish-tallon-correction)
    - touched by: step 4.6 (YAML guardrails, future), step 1.6 (lazy fix)
  /home/kohan/pantheon/conductor/v2/nats.py
    - depends on: enqueue_outbound_nats, _handle_msg
    - depended on by: workflows/*.yaml
  ...
subplans:
  - id: phase-1-handoff
    title: "Phase 1 — Handoff Foundation"
    status: DONE
    completed_at: 2026-06-12
  - id: phase-2-routing
    title: "Phase 2 — Routing + Rules"
    status: DONE
  - id: phase-3-engine
    title: "Phase 3 — Engine + Bridge"
    status: DONE
  - id: phase-4-quarantine-sovereign
    title: "Phase 4 — Quarantine + Sovereign Guards"
    status: in_progress
    current_step: 4.4
  - id: phase-5-e2e
    title: "Phase 5 — E2E Test Suite"
    status: not_started
---

## Cycle goal
[1 paragraph: what this project delivers when all sub-plans are DONE]

## Cross-cutting decisions
- The sovereign-NATS guard is the load-bearing safety pattern. No workflow that publishes to subspace.*.outgoing.* may fire without operator_approval_token.
- Per-profile SKILL.md drift was a real bug class (Step 4.2 root cause). Symlinks prevent it; profile-bootstrap hook (Step 4.4 candidate) prevents the class.
- State files in `state/wf_*.json` are append-only + correctable. Manual truth-write is the audit-trail of last resort.
```

## Sub-plan structure

```yaml
---
plan_id: phase-4-quarantine-sovereign
parent: conductor-v2
status: in_progress
current_step: 4.4
steps_total: 7
steps_done: 3
gods_involved: [marvin, thoth]
created: 2026-06-15
last_updated: 2026-06-15T17:30Z
---

## Sub-plan goal
[1 paragraph: what this phase delivers when all steps are DONE]

## Steps

### Step 4.1 — Quarantine status helper
- **Status:** DONE
- **God:** marvin (build) / thoth (QA)
- **Briefs:** 3 sliced briefs (1 build, 1 QA, 1 final review)
- **Files touched:** `~/pantheon/conductor/scripts/quarantine_status.py`
- **Success criteria:** [1-3 items, testable]
- **Completed at:** 2026-06-15T13:55Z
- **Verification command:** `python3 ~/pantheon/conductor/scripts/quarantine_status.py`
- **Reversibility:** `git diff` + `git checkout`

### Step 4.2 — Fix per-profile SKILL.md drift (thoth-dawn-patrol §5.5)
- **Status:** DONE
- **God:** marvin / thoth QA
- **Files touched:** `~/.hermes/profiles/thoth/skills/thoth/thoth-dawn-patrol/SKILL.md`, `~/home/konan/athenaeum/reports/dawn-patrol/2026-06-15.md`
- **Completed at:** 2026-06-15T15:57Z
- **QA verdict:** SHIP (Thoth session 20260615_104204_4b472f)

### Step 4.3 — Profile-wide symlink audit (95 skills)
- **Status:** DONE
- **God:** marvin / thoth QA
- **Files touched:** 95 per-profile SKILL.md → symlinks, 66 references/ subdirs merged, BUILD-PLAN.md
- **Completed at:** 2026-06-15T16:34Z
- **QA verdict:** SHIP (1 minor finding on NO-CANON report scope, operator-ratified)
- **Artifact:** `~/pantheon/shared/active/conductor-step-4.3-no-canon.txt` (86 entries, 14.3K)

### Step 4.4 — Profile-bootstrap hook (prevent new skills from drifting)
- **Status:** pending → in-progress on dispatch
- **God:** marvin (build) / thoth (QA)
- **Briefs (3, sliced):**
  - 1: detect-new-canonical-skills at gateway start
  - 2: create per-profile symlinks for new skills
  - 3: verify with fresh-gateway-start test
- **Success criteria:**
  1. New canonical SKILL.md → per-profile symlink created at next gateway start
  2. Pre-existing 95 symlinks untouched
  3. Failure mode: log + continue, don't block startup
- **Verification:** Drop a test canonical skill, restart any per-profile gateway, confirm symlink + readlink; pytest -q → still 193/193
- **Out of scope:** Spec Part 1 (YAML guardrails), Spec Part 3 (YAML validator) — those are Step 4.6
- **Reversibility:** `rm` the bootstrap hook script, restart, symlinks remain (they were correct)

### Step 4.5 — Heuristic .archive/ cleanup (6 hephaestus entries)
- **Status:** pending
- **God:** hephaestus (build, hephaestus-owned data) / thoth (QA)
- **Files touched:** 6 hephaestus .archive/ SKILL.md (capture-idea, js-regex-escaping, pantheon-god-bot-setup, pantheon-mcp-server, pantheon-system-migration, pantheon-wsl-networking)
- **Success criteria:** 6 .archive/ entries either removed (if obsolete) or promoted to canonical (if still useful)
- **Verification:** `find ~/.hermes/profiles/hephaestus -name SKILL.md -path "*.archive/*"` returns 0, or 0 non-redundant entries
- **Out of scope:** Per-profile SKILL.md in non-.archive/ paths
- **Reversibility:** git history + the original 6 files are in `athenaeum/Codex-God-hephaestus/.archive/` backups

### Step 4.6 — Spec Part 1+3 (YAML guardrails, workflow validator) — defense-in-depth
- **Status:** pending, deferrable
- **God:** hephaestus
- **Why deferrable:** Engine guard already catches the breach shape via regex. This is defense-in-depth, not blocking.
- **Briefs (3, sliced):**
  - 1: add `operator_approval_required: true` to deploy-feature.yaml:notify-enterprise
  - 2: add workflow YAML validator at load time
  - 3: integration test that bypasses regex still gets blocked
- **Success criteria:** Workflows with sovereign subjects + no operator_approval_required fail to load with a clear error
- **Verification:** Craft a workflow that bypasses the regex (different subject shape) → load → expect hard fail
- **Reversibility:** git revert of deploy-feature.yaml and the validator

### Step 4.final — Phase 4 final review
- **Status:** pending
- **Type:** review (no god dispatch, hermes-only)
- **Trigger:** All 4.1-4.6 DONE
- **Output:** `reviews/phase-4-quarantine-sovereign-final-review.md` with the structured holes/decisions/blockers/impacts/drift report
- **Blocks:** Advancement to phase-5-e2e sub-plan
```

## Per-step brief structure (3 briefs, one per job)

```yaml
---
brief_id: phase-4-step-4.4-marvin-build-1
subplan: phase-4-quarantine-sovereign
step_id: 4.4
brief_number: 1_of_3
to: marvin
type: build
spec_ref: plans/conductor-v2/phase-4-quarantine-sovereign.yaml#step-4.4
created: 2026-06-15T17:30Z
---

# Brief: Step 4.4, Brief 1 of 3 — Detect new canonical skills at gateway start

## Context
[1-2 paragraphs: what came before, why this brief exists]
- Step 4.3 closed the existing 95 drifted skills with symlinks.
- Step 4.4 prevents NEW skills from drifting. This is the "class fix" not the "instance fix."
- This brief covers Brief 1 of 3: detection only. Briefs 2 and 3 are dependency-ordered.

## Task
Write a hook script that, on every per-profile gateway start, scans `~/.hermes/skills/` for SKILL.md files, compares against `~/.hermes/profiles/<god>/skills/` symlinks, and reports any canonical skills that lack a per-profile symlink.

## Success criteria
1. Script exists at `~/pantheon/conductor/scripts/profile-bootstrap-hook.sh` (or similar, propose in brief response)
2. On gateway start, runs as part of the gateway init
3. Logs the list of new canonical skills needing symlinks
4. Exit code 0 even if no new skills (idempotent)
5. Exit code !=0 only if the script itself is broken (not for "no new skills")

## Verification
```bash
# Drop a test canonical SKILL.md
mkdir -p ~/.hermes/skills/test-bootstrap-detect
echo "test" > ~/.hermes/skills/test-bootstrap-detect/SKILL.md

# Restart any per-profile gateway (e.g., thoth-profile)
systemctl --user restart hermes-gateway-thoth.service

# Confirm the hook logged the new skill
journalctl --user -u hermes-gateway-thoth.service | grep "test-bootstrap-detect"

# Clean up
rm -rf ~/.hermes/skills/test-bootstrap-detect
```

## Files touched
- NEW: `~/pantheon/conductor/scripts/profile-bootstrap-hook.sh` (proposed path)
- Possibly: `~/.config/systemd/user/hermes-gateway-*.service` (if hook needs to be in service file)

## Out of scope
- Creating the symlinks (Brief 2)
- Verifying with a fresh-gateway-start test (Brief 3)
- Other gods (Brief 2 is a separate god, Brief 3 is QA)

## Reversibility
`rm` the script and revert any service file changes. Symlinks are unaffected.

## Deadline
30 minutes wall-clock
```

## The wizard (interview mode)

**The wizard IS the file editor.** It scaffolds a live YAML file at the project folder path. You and I edit that file in real time during the interview. The skill reads the file back at each turn to know where we are.

### Wizard states

1. **`awaiting_project_id`** — Operator says "build a plan for X" or pastes a spec. Wizard asks for project_id (kebab-case, becomes folder name).
2. **`awaiting_project_title`** — Wizard asks for the human-readable title.
3. **`awaiting_scope_split`** — Wizard proposes the sub-plan split (using the heuristic: a sub-plan = one observable ship-able outcome). Operator ratifies or overrides.
4. **`awaiting_subplan_goal`** — Per sub-plan, wizard asks for the goal (1 paragraph). Operator provides.
5. **`awaiting_steps`** — Wizard walks each sub-plan, asking for steps. Per step: title, success criteria, verification, out-of-scope, files touched.
6. **`awaiting_review_step`** — For each sub-plan, wizard suggests the `<id>.final` review step with the 5-section output shape.
7. **`awaiting_cross_cutting_decisions`** — Wizard asks for project-level decisions (e.g., "what's the load-bearing pattern?").
8. **`awaiting_file_dependency_map`** — Wizard scaffolds an initial dep map from the sub-plan steps. Operator can edit.
9. **`complete`** — All artifacts written. Master + sub-plans + briefs folder + reviews folder. Runner can take over.

### Wizard heuristic for sub-plan split

> "A sub-plan is a coherent unit of work that delivers one observable outcome. If you can ship it and announce it as a milestone, it's a sub-plan. If it's 'do this one thing and verify,' it's a step."

Concrete examples from this session:
- Conductor v2 has 5 sub-plans: Phase 1 (handoff), Phase 2 (routing), Phase 3 (engine), Phase 4 (quarantine + sovereign), Phase 5 (E2E).
- Step 4.3 is a STEP, not a sub-plan, because it has one deliverable (symlinks) and one verification (readlink spot-check).
- The final-review is a STEP, not a sub-plan.

## The listener (back-and-forth mode)

The listener is **not** a structured mode. It's the same Hermes surface you already have. The difference: when a decision-moment is detected in the active conversation, the skill proposes a step addition to the current sub-plan.

### Decision-moment heuristics (high-confidence only)

- **Scope change**: "let me change scope on X" / "actually do Y instead" / "skip Z for now"
- **Deferral**: "that's a Step N.x candidate" / "defer to follow-up cycle" / "out of scope for this"
- **Operator ratification**: "Yeah let's do that" / "sounds good" / "agreed"
- **Implicit decision**: Operator picks option A over B, or a god proposes an alternative and operator doesn't push back.

The listener's posture: **propose, don't auto-write.** When a decision is detected, the skill surfaces "I think this is a new step / scope change / deferral. Want me to add it to the current sub-plan?" and waits for the operator's call.

### Why not over-structured

You said: "I don't want to overly structure the listener part because I feel we get the most out when it's a back and forth conversation." The listener is **the existing PM-loop** with a new responsibility: surface decision-captures at the right moments. The structure lives in the file (the sub-plan YAML), not in the conversation.

## The 3-brief rule

Per the operator's call: **3 briefs, one per job, never batched.** Today's Step 4.3 brief was ~6K characters doing 5 jobs. The new shape:

- **Brief 1: build deliverable.** What to produce.
- **Brief 2: dependency-ordered follow-on.** (e.g., rsync after symlinks, NO-CANON after symlinks)
- **Brief 3: verification + integration.** (e.g., pytest, fresh-gateway-start, end-to-end test)

If a step genuinely only has 1 job, it's 1 brief. If it has 5 jobs, it's 5 briefs. **The cap is per-job, not per-step.** The cap exists to keep each brief focused enough that a god can read it in one pass and execute without ambiguity.

## The final-review step (sub-plan completion gate)

When a sub-plan's `current_step` reaches `<id>.final`, the runner refuses to advance until a final-review artifact exists at `reviews/<sub-plan-id>-final-review.md`.

### Final-review structure (5 sections)

1. **Holes.** Step statuses are DONE, but the actual deliverable is missing or wrong. (Example: Step 4.3 said "95 symlinks created" but a spot-check shows 3 didn't resolve.)
2. **Decisions.** Implicit scope calls made during execution that weren't in the spec. (Example: Thoth QA noted NO-CANON count was 80 not 86 — that's a decision, not a hole.)
3. **Blockers.** Anything that would prevent the next sub-plan from starting.
4. **Forward impacts.** Dependencies the next sub-plan assumed that aren't real. (Example: Phase 5 E2E assumes the sovereign guard passes test_backbone_e2e.py — confirm.)
5. **Drift.** Live state vs. spec in ways that matter. (Example: BUILD-PLAN.md was updated by Marvin, but the sub-plan YAML was never updated to reflect the same status — both should be in sync.)

The final-review is **run by Hermes, not a god.** It's a meta-step. The output is a structured doc the operator reviews before the runner advances.

## The file dependency map

An **artifact of every sub-plan** — a section in the sub-plan YAML (or a sibling `dependencies.yaml`) listing every file the plan creates/modifies, with what depends on what.

### Why this matters

- Future operator: "I want to upgrade Step 4.4 to do X. What other files reference the 95-symlink pattern?" → answer in 5 seconds, not 30 minutes of `grep`.
- Refactor planning: "If I rewrite `engine.py`, what's the blast radius?" → answer in 1 minute.
- Onboarding: new god gets a visual map of what they can touch vs. what's load-bearing.

### Format

```yaml
file_dependency_map:
  /home/kohan/pantheon/conductor/v2/engine.py:
    depends_on: [SOVEREIGN_OUTBOUND_RE, _has_operator_approval, _consume_operator_approval]
    depended_on_by: [workflows/deploy-feature.yaml, workflows/cross-pantheon-deploy.yaml, workflows/sovereign-publish-tallon-correction.yaml]
    touched_by: [step-1.6, step-4.6, step-4.final]
    load_bearing: true
  /home/kohan/.hermes/skills/thoth/thoth-dawn-patrol/SKILL.md:
    depends_on: [thoth-dawn-patrol canonical]
    depended_on_by: [thoth-profile skill loader, dawn-patrol cron]
    touched_by: [step-4.2]
    load_bearing: false
```

The wizard scaffolds the initial map from the steps' "files touched" lists. The operator edits.

## State machine (for `pm-loop-runner`)

The runner is a separate skill, not this one. The state machine:

1. `awaiting_dispatch` → I draft a brief + send to a god.
2. `awaiting_god` → god is working, I can do parallel work but not start the next step.
3. `awaiting_qa` → god says DONE, Thoth is verifying.
4. `awaiting_operator` → QA says SHIP, I need operator ratification.
5. `awaiting_next_step` → operator ratified, advance to next step, write the brief.
6. `awaiting_final_review` → sub-plan's last step is `<id>.final`, runner blocks until review artifact exists.
7. `awaiting_next_subplan` → review passed, advance to next sub-plan from master.

## Open questions for the operator (don't block on these)

1. **Storage location for plans.** Spec says `~/pantheon/plans/<project-id>/`. Alternative: `~/pantheon/conductor/plans/<project-id>/` (conductor-namespaced) or `~/pantheon-core/plans/` (pantheon-namespaced). My read: `~/pantheon/plans/` is the right place because plans are cross-conductor (olympus, theoforge, ledger, etc., not just conductor).
2. **Versioning of plans.** Do we version the YAML files in git, or treat them as ephemeral? My read: git-versioned, because the plan is the source of truth and version drift is its own bug class.
3. **Migration of BUILD-PLAN.md.** Today the existing `BUILD-PLAN.md` is the de-facto plan. The wizard should offer to migrate it to the new structure as one of the first real projects. My read: yes, do it as part of the conductor-v2 test target.
4. **Indexing.** `_index.yaml` at `~/pantheon/plans/_index.yaml` is the discovery surface. The wizard writes it; the runner reads it. Alternative: scan the folder. My read: explicit index is more reliable, scan is fallback.
5. **Skill name.** `build-plan-builder`? `pm-plan-builder`? `pm-loop-architect`? My read: `build-plan-builder` (the operator said "build plan builder" verbatim).

## Test target: Conductor v2 closeout

The first real run of the wizard. Outcome:
- `~/pantheon/plans/conductor-v2/master.yaml` (project tree)
- `~/pantheon/plans/conductor-v2/phase-1-handoff.yaml` (DONE sub-plan, populated from BUILD-PLAN.md)
- `~/pantheon/plans/conductor-v2/phase-2-routing.yaml` (DONE)
- `~/pantheon/plans/conductor-v2/phase-3-engine.yaml` (DONE)
- `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (current, Steps 4.1-4.3 DONE, 4.4-4.6 + 4.final pending)
- `~/pantheon/plans/conductor-v2/phase-5-e2e.yaml` (stub, "TBD — see BUILD-PLAN.md §Phase 5")
- `~/pantheon/plans/conductor-v2/file_dependency_map.yaml` (initial scaffold)
- 3 briefs per pending step in `briefs/`
- `reviews/phase-4-quarantine-sovereign-final-review.md` (only when phase 4 is DONE)

## Estimated work to ship

1. **Spec doc** (this file) — 30 min ✅
2. **Templates** (master, sub-plan, brief, review) — 20 min
3. **Conductor v2 first real run** (wizard drives the scaffold) — 30-45 min
4. **Iterate on the wizard's heuristics** based on what the first run surfaces — ongoing
5. **Promote spec → skill** at `~/.hermes/skills/pm/build-plan-builder/SKILL.md` — 15 min

Total to first-run: ~1.5 hours. After that, the wizard is real, the artifacts are real, and the runner can be built against them.

## Decision log

- 2026-06-15T17:30Z: Wizard + listener (not just wizard). Listener is the existing PM-loop with a new responsibility, not a structured mode.
- 2026-06-15T17:30Z: 3 briefs per step, one per job, never batched.
- 2026-06-15T17:30Z: Scope = you + me + Thoth + Hephaestus. Marvin, Iris, others consume only.
- 2026-06-15T17:30Z: Sub-plan split heuristic: "ship-able outcome = sub-plan, do-one-thing-verify = step."
- 2026-06-15T17:30Z: Final-review is hermes-only, runs at sub-plan completion, blocks advancement to next sub-plan.
- 2026-06-15T17:30Z: File dependency map is an artifact of every sub-plan, in YAML, editable by operator.
- 2026-06-15T17:30Z: Test target = Conductor v2 closeout, opinionated wizard, operator override.

— Hermes, 2026-06-15T17:30Z
