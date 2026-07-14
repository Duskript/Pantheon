# Conductor v2 — Wizard's Proposed Split (First Real Run)

**Skill:** `build-plan-builder` (DRAFT spec at `~/pantheon/shared/active/build-plan-builder-skill-spec.md`)
**Project:** Conductor v2 — Sovereign Workflow Engine
**Test target:** the work we've been doing this session + the rest of the conductor v2 project
**Wizard's posture:** opinionated, with operator override

---

## Proposed sub-plan split

I propose **5 sub-plans** matching the existing `BUILD-PLAN.md` phases. Each is a coherent unit of work that ships an observable outcome.

| Sub-plan ID | Title | Status | Current Step | Ships When |
|---|---|---|---|---|
| `phase-1-handoff` | Phase 1 — Handoff Foundation | DONE | — | Engine accepts inter-god handoffs (already shipped 2026-06-12) |
| `phase-2-routing` | Phase 2 — Routing + Rules | DONE | — | Rule engine routes events to workflows (already shipped) |
| `phase-3-engine` | Phase 3 — Engine + Bridge | DONE | — | ConductorEngine + Bridge MCP exposed to other gods (already shipped) |
| `phase-4-quarantine-sovereign` | Phase 4 — Quarantine + Sovereign Guards | in_progress | 4.4 | Quarantine helper live, sovereign-NATS guard live, drift class closed |
| `phase-5-e2e` | Phase 5 — E2E Test Suite | not_started | — | Real E2E test of the full backbone (already has 1 E2E per BUILD-PLAN; this phase is the expanded suite) |

**Heuristic applied:** each phase is a "ship-able outcome" you can announce as a milestone. Steps within each phase are "do one thing + verify."

## Proposed cross-cutting decisions (top of master.yaml)

1. **The sovereign-NATS guard is the load-bearing safety pattern.** No workflow that publishes to `subspace.*.outgoing.*` may fire without `operator_approval_token` in `context_bag`. Engine rejects on missing/invalid/consumed token. (Source: the 2026-06-15 NATS breach + 13:55Z engine fix + 17:06:33Z Tallon correction.)
2. **Per-profile SKILL.md drift was a real bug class.** Symlinks prevent it. Step 4.4 (profile-bootstrap hook) prevents new instances of the class. (Source: Step 4.2 root cause + Step 4.3 symlink fix.)
3. **State files in `state/wf_*.json` are append-only + correctable.** Manual truth-write is the audit-trail of last resort. Reversible via `cp` from `state/backups/`. (Source: 13:17Z truth-write on `wf_8a0b5f28` + `wf_f26885f8`.)
4. **The dispatcher is the unwritten sub-plan.** Step-to-god resolver doesn't validate `active_session.god == step.god`. The sovereign guard catches the symptom (refusals block breach), but the root cause is a separate sub-plan. (Source: 5x misroute pattern in `wf_8a0b5f28` + `wf_f26885f8`. Defer to a future "Conductor v3 — Resolver Correctness" project or a phase-6 addition.)

## Proposed file dependency map (initial scaffold)

Based on what the steps touch:

```yaml
file_dependency_map:
  /home/kohan/pantheon/conductor/v2/engine.py:
    depends_on:
      - SOVEREIGN_OUTBOUND_RE (engine.py:157)
      - _has_operator_approval (engine.py:179)
      - _consume_operator_approval (engine.py:199)
      - _REFUSAL_MARKER_RE (engine.py:122)
    depended_on_by:
      - workflows/deploy-feature.yaml
      - workflows/cross-pantheon-deploy.yaml
      - workflows/sovereign-publish-tallon-correction.yaml (NEW 2026-06-15)
      - workflows/morning-briefing.yaml
    touched_by: [step-1.6, step-4.6-deferrable, step-4.final]
    load_bearing: true
    notes: Engine code is the load-bearing safety surface. v2/engine.py has the post-fix guard. Test count 176→193 in v2 tests.

  /home/kohan/pantheon/conductor/v2/nats.py:
    depends_on: [enqueue_outbound_nats, _handle_msg, _SOVEREIGN_TOKENS_ATTR]
    depended_on_by: [workflows/*.yaml, conductor daemon]
    touched_by: [step-4.final]
    load_bearing: true
    notes: Outbound NATS path. Engine guard prevents the breach; this file is unchanged.

  /home/kohan/pantheon/conductor/scripts/quarantine_status.py:
    depends_on: [Python stdlib]
    depended_on_by: [thoth-dawn-patrol §5.5, conductor cron, daily brief]
    touched_by: [step-4.1]
    load_bearing: false
    notes: Helper. Status: SHIP (376/376 tests in 2026-06-15 morning brief).

  /home/kohan/.hermes/skills/thoth/thoth-dawn-patrol/SKILL.md:
    depends_on: [canonical SKILL.md]
    depended_on_by: [thoth-profile skill loader, dawn-patrol cron, morning brief]
    touched_by: [step-4.2]
    load_bearing: false
    notes: 35,813 B, §5.5 at line 163. Fix in step-4.2 was a one-file cp.

  /home/kohan/.hermes/profiles/*/skills/*/*/SKILL.md:
    depends_on: [~/.hermes/skills/*/*/SKILL.md]
    depended_on_by: [profile-specific skill loaders]
    touched_by: [step-4.3]
    load_bearing: false
    notes: 95 per-profile SKILL.md replaced with symlinks. Per-profile references/ subdirs merged via rsync --ignore-existing (1270→1821 files).

  /home/kohan/pantheon/conductor/state/wf_*.json:
    depends_on: [engine._save_instance, manual truth-write]
    depended_on_by: [operator audit, god inbox, NATS server log]
    touched_by: [step-4.2, step-4.3, all workflows]
    load_bearing: true
    notes: 2 truth-written files (wf_8a0b5f28, wf_f26885f8) at 13:17Z. Reversible via state/backups/.

  /home/kohan/pantheon/conductor/state/backups/:
    depends_on: [manual backup, /tmp/state-bak-*.bak]
    depended_on_by: [operator truth-write reversibility]
    touched_by: [step-4.2, step-4.3, all workflows]
    load_bearing: false
    notes: Pre-truth-write backups. Operator's safety net.

  /home/kohan/pantheon/shared/decisions/<date>.md:
    depends_on: [append-only, manual edits]
    depended_on_by: [Hades distillation, audit trail, operator review]
    touched_by: [every step, every god handoff]
    load_bearing: false
    notes: 2026-06-15.md is 295 lines (13:17Z truth-write + 13:55Z engine-fix + 17:07Z Tallon-correction).

  /home/kohan/pantheon/shared/DIGEST.md:
    depends_on: [decisions log, handoffs inbox]
    depended_on_by: [session-start context injection]
    touched_by: [cron e081330759fc every 2h]
    load_bearing: false
    notes: Auto-generated. 2200 lines.

  /home/kohan/pantheon/conductor/BUILD-PLAN.md:
    depends_on: [manual edits, god updates]
    depended_on_by: [this wizard, runner, operator review]
    touched_by: [step-4.2, step-4.3, future steps]
    load_bearing: false
    notes: LEGACY — being replaced by the per-project master.yaml + sub-plan YAMLs. Will be archived once migration is complete.
```

## Proposed pending briefs (3 per step in current sub-plan)

For `phase-4-quarantine-sovereign`, the pending steps are 4.4, 4.5, 4.6, 4.final. That's **12 briefs** total (3 each × 4 steps). Each brief is ~1.5-2K characters, focused on one job.

### Step 4.4 — Profile-bootstrap hook (3 briefs)
- **Brief 1: build deliverable.** Detect new canonical skills at gateway start.
- **Brief 2: dependency-ordered follow-on.** Create per-profile symlinks for new skills.
- **Brief 3: verification.** Fresh-gateway-start test, pytest, no regression on 95 existing symlinks.

### Step 4.5 — Heuristic .archive/ cleanup (3 briefs)
- **Brief 1: build deliverable.** Audit the 6 hephaestus .archive/ entries.
- **Brief 2: dependency-ordered follow-on.** Remove (if obsolete) or promote to canonical (if still useful).
- **Brief 3: verification.** `find` returns 0 obsolete .archive/ entries.

### Step 4.6 — YAML guardrails + validator (3 briefs, deferrable)
- **Brief 1: build deliverable.** Add `operator_approval_required: true` to deploy-feature.yaml:notify-enterprise.
- **Brief 2: dependency-ordered follow-on.** Add workflow YAML validator at load time.
- **Brief 3: verification.** Craft a workflow that bypasses the regex → load → expect hard fail.

### Step 4.final — Phase 4 final review (1 brief, no god dispatch)
- **Brief 1: hermes-only final review.** Read the sub-plan end-to-end, surface holes/decisions/blockers/impacts/drift, write `reviews/phase-4-quarantine-sovereign-final-review.md`, blocks advancement to phase-5.

**Total pending briefs: 12 + 1 = 13.** Note: briefs are created at dispatch time, not pre-generated. This list is the "queue" for when the runner advances.

## Wizard's open questions for the operator

1. **Project ID:** `conductor-v2` (kebab-case) — confirm.
2. **Storage:** `~/pantheon/plans/conductor-v2/` — confirm.
3. **Master plan scope:** include Phase 5 as a stub, or omit? (My read: include, so the master reflects the whole project.)
4. **Phase 1-3 sub-plans:** auto-populate from BUILD-PLAN.md, or write as one-paragraph stubs? (My read: auto-populate, since the work is shipped and the steps are recorded.)
5. **BUILD-PLAN.md fate:** archive after migration, or keep as legacy? (My read: archive, mark as superseded by master.yaml.)
6. **The "dispatcher resolver" cross-cutting decision:** create a phase-6 stub for the future "Conductor v3 — Resolver Correctness" project, or defer? (My read: defer to a future project, don't pollute this one.)
7. **Skill name:** `build-plan-builder` — confirm. (Operator said "build plan builder" verbatim.)
8. **First-run validation:** run the wizard live with you as the operator, ~30-45 min, you ratify each sub-plan split as we go. (My read: yes, this is the test.)

## After ratification

Once you ratify the split, the wizard writes:
- `~/pantheon/plans/conductor-v2/master.yaml` (the project tree + cross-cutting decisions + dep map stub)
- `~/pantheon/plans/conductor-v2/phase-{1,2,3}-handoff-routing-engine.yaml` (DONE sub-plans, auto-populated)
- `~/pantheon/plans/conductor-v2/phase-4-quarantine-sovereign.yaml` (current, fully populated)
- `~/pantheon/plans/conductor-v2/phase-5-e2e.yaml` (stub)
- `~/pantheon/plans/_index.yaml` (project index)
- `~/pantheon/plans/templates/{master,subplan,brief}-template.yaml` (for next projects)
- `~/pantheon/shared/active/build-plan-builder-skill-spec.md` already written (this doc's sibling)

Then the wizard promotes the spec to a real skill at `~/.hermes/skills/pm/build-plan-builder/SKILL.md` and the runner becomes buildable against the new structure.

## My recommendation

Ratify the 5-sub-plan split, include Phase 5 as a stub, auto-populate 1-3 from BUILD-PLAN.md, archive BUILD-PLAN.md after migration, defer dispatcher to a future project. Then I run the wizard for ~30-45 min and we have a real artifact at the end.

Your call.
