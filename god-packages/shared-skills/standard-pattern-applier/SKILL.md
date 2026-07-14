---
name: standard-pattern-applier
description: "Use when Hephaestus or any god needs to apply a standard to a new instance — a new subsystem follows the subsystem-shape, a new build follows the build-plan-shape, a new god follows the god-profile-shape, a new convention follows the convention-doc-shape. Takes the standard + the new context, produces the conformant artifact."
version: 1.0.0
tags: [standards, patterns, application, conformity, hephaestus]
---

# Standard Pattern Applier — Conformant by Default

> **The skill that takes a standard and a new context, and produces a conformant artifact.** Every standard in `Codex-Pantheon/design/standards/` is a template. This skill applies the template. The output conforms by default.

## When to use this skill

Load this skill whenever:

- A new subsystem is being designed (apply `subsystem-shape`)
- A new build plan is being authored (apply `build-plan-shape`)
- A new god is being created or reworked (apply `god-profile-shape`)
- A new god profile is being created (apply `god-profile-shape`)
- A new convention is being authored (apply `convention-doc-shape`)
- A new kanban task is being created (apply `kanban-task-shape`)
- A new Conductor workflow is being authored (apply `conductor-workflow-shape`)
- A new design review is being produced (apply `design-review-shape`)
- A new god handoff is being produced (apply `god-handoff-shape`)
- A new phase boundary is being defined (apply `phase-boundary-shape`)
- A new Soulforge interview is being designed (apply `soulforge-interview-shape`)

**Don't use this skill for:**

- Reading or interpreting an existing artifact
- Reviewing an artifact for compliance (use `convention-enforcer` instead)

## How to use it (the procedure)

### Step 0: Identify the standard and the context

The skill takes two inputs:

1. **The standard** — which of the 10 standards to apply
2. **The context** — what the new thing is, what it's for, who it's for

**Example inputs:**

```
standard: build-plan-shape
context: "Building the Olympus UI. It's a React + Vite + TypeScript app, similar to conductor-ui. Iris will design, Marvin will build, Thoth will review. Phase 0 is foundation (Vite scaffold + theme tokens), Phase 1 is the Olympus shell (5 routes), Phase 2 is the chat surface (assistant-ui), Phase 3 is the notification surface, Phase 4 is integration with the rest of the Pantheon."
```

### Step 1: Load the standard

Read the relevant standard doc:

- `Codex-Pantheon/design/standards/subsystem-shape.md` for subsystems
- `Codex-Pantheon/design/standards/build-plan-shape.md` for plans
- `Codex-Pantheon/design/standards/god-profile-shape.md` for gods
- ... etc

The standard is the template. Every section, every field, every rule is in the doc.

### Step 2: Apply each section/field systematically

Walk through the standard section by section, applying it to the new context. For each section:

1. **What does the standard say?** (read the section)
2. **What's the analog in the new context?** (find the new equivalent)
3. **Is the new context an exception?** (check the standard's exceptions)
4. **If not an exception, fill in the section** (write the conformant content)

**Example (build-plan-shape, Section 5: Phased plan):**

The standard says the plan needs phases with Ships, Key deliverables, Dependencies, Verification.

For the Olympus UI build:
- **Phase 0 (Foundation)** — Ships: Vite + React + TS scaffold, theme tokens, Apollo UI design integration. Key deliverables: package.json, vite.config.ts, theme/tokens.ts, theme/index.css. Dependencies: none. Verification: `npx tsc --noEmit && npm run test:run`.
- **Phase 1 (Olympus shell)** — Ships: 4-layer shell (per Olympus Native architecture), 5 routes (/, /chat, /notifications, /settings, /gods). Key deliverables: shell/AppShell.tsx, routes/*, state/. Dependencies: Phase 0. Verification: routes render with real data, no console errors.
- ... etc.

The output is the section filled in for the new context.

### Step 3: Validate against the standard

After applying, run the `convention-enforcer` (or do a manual check):

- Are all required sections/fields present?
- Are the sections in the right order?
- Are the field names exact (case-sensitive)?
- Is the file format correct (YAML, Markdown, TypeScript)?

**If validation fails:** go back to Step 2, fix the section, re-validate.

**If validation passes:** proceed to Step 4.

### Step 4: Cross-check with related standards

Most artifacts touch multiple standards. For example, a build plan touches:
- `build-plan-shape` (the 13 sections)
- `kanban-task-shape` (the tasks in the file-by-file table)
- `god-handoff-shape` (the hand-offs in the chain)
- `phase-boundary-shape` (the gates between phases)
- `qa-gate-rubric` (the Thoth reviews)

**For each related standard, check the artifact conforms.**

**Example (build plan + kanban tasks):**

The plan's file-by-file table has 53 rows. Each row will become a kanban task. The task shape requires 9 fields. The applier should generate a task spec for each row that has all 9 fields.

**If cross-checks fail:** fix the artifact to conform to all related standards.

### Step 5: Produce the artifact

The output is the conformant artifact:

- A build plan that follows `build-plan-shape` (13 sections, all fields, no time estimates, paths correct)
- A subsystem that follows `subsystem-shape` (interface, types, LocalStub, tests, adapter, migration, docs)
- A god profile that follows `god-profile-shape` (8 components, all canonical)
- A convention that follows `convention-doc-shape` (7 fields, all populated)
- etc.

The artifact is **ready to ship** — it conforms to the standard by default.

### Step 6: Document any exceptions

If the new context has a legitimate exception to the standard:

1. **Document the exception** in the artifact (a "Deviations from the standard" section)
2. **Justify the exception** (why this case is different)
3. **Log a decision** — write to `pantheon/shared/decisions/` for operator review
4. **Note for the operator** — the exception is operator-visible

**The standard is the default. Exceptions are operator-locked decisions.**

## Worked examples

### Example 1: Apply `subsystem-shape` to the Ichor subsystem

**Standard:** `subsystem-shape.md` (6 components)

**Context:** Ichor is the memory harness. It already exists (in `pantheon/god-packages/`), but the shape wasn't documented. We need to document it.

**Application:**

| Component | Path | Status |
|---|---|---|
| Interface | `ichor/store.py` (or equivalent) | The `store_event`, `retrieve`, `forget` functions |
| Types | `ichor/types.py` | `Event`, `Fact`, `Insight`, etc. |
| LocalStub | the SQLite `ichor.db` | The default impl (this IS the local stub) |
| Tests | `ichor/tests/` | 8+ unit tests + integration tests |
| Adapter | (none — Ichor is the memory, no separate adapter) | N/A |
| Migration | Hades nightly consolidation | The migration framework |
| Day-1 docs | `Codex-God-thoth/memory.md` | Documents the seams |

**Output:** the subsystem-seams.md entry for Ichor is populated correctly.

### Example 2: Apply `build-plan-shape` to a new build

**Standard:** `build-plan-shape.md` (13 sections)

**Context:** "We're building the Olympus UI. It's a React + Vite + TypeScript app..."

**Application:**

For each of the 13 sections, the applier produces a draft. The output is a complete build plan.

### Example 3: Apply `god-profile-shape` to a new god

**Standard:** `god-profile-shape.md` (8 components)

**Context:** "We're creating a new god called `Nero` for net-new functionality."

**Application:**

| Component | Path | Content |
|---|---|---|
| gods.yaml | `pantheon/gods/gods.yaml` | The new `nero:` entry |
| SOUL.md | `~/.hermes/profiles/nero/SOUL.md` | The new god's identity |
| persona.md | `~/.hermes/profiles/nero/persona.md` | The new god's voice |
| skills/ | `~/.hermes/profiles/nero/skills/` | Symlinks to relevant shared skills |
| config.yaml | `~/.hermes/profiles/nero/config.yaml` | The runtime config |
| Codex | `athenaeum/Codex-God-Nero/` | The new god's codex |
| decisions | `pantheon/shared/decisions/nero-creation.md` | The creation decision |
| handoffs | `pantheon/shared/handoffs/nero/` | The handoff log dir |

**Output:** the 8 components are created correctly. The new god is ready.

## Pitfalls

**Don't invent sections/fields.** The standard is the template. Don't add to it, don't skip from it.

**Don't cross-apply without checking related standards.** Most artifacts touch multiple standards.

**Don't auto-fix exceptions.** An exception is an operator-locked decision. Log it, ask the operator, don't assume.

**Don't apply the wrong standard.** Each artifact has exactly one shape (or a small set of related shapes). Applying the wrong one produces a non-conformant artifact.

**Don't apply without the context.** The standard says "what" — the context says "for what." Without both, the output is generic.

## Verification gates

Standard-pattern-applier is "working" when:

- [ ] All 10 standards are applied correctly
- [ ] The output conforms to the standard (validated by `convention-enforcer`)
- [ ] Cross-checks with related standards pass
- [ ] Exceptions are documented and logged
- [ ] The output is ready to ship (no follow-up needed for conformity)

## See also

- `Codex-Pantheon/design/standards/INDEX.md` — the 10 standards
- `Codex-Pantheon/design/standards/subsystem-shape.md`
- `Codex-Pantheon/design/standards/build-plan-shape.md`
- `Codex-Pantheon/design/standards/god-profile-shape.md`
- `Codex-Pantheon/design/standards/kanban-task-shape.md`
- `Codex-Pantheon/design/standards/conductor-workflow-shape.md`
- `Codex-Pantheon/design/standards/design-review-shape.md`
- `Codex-Pantheon/design/standards/god-handoff-shape.md`
- `Codex-Pantheon/design/standards/phase-boundary-shape.md`
- `Codex-Pantheon/design/standards/convention-doc-shape.md`
- `Codex-Pantheon/design/standards/soulforge-interview-shape.md`
- `pantheon/god-packages/shared-skills/convention-enforcer/SKILL.md` — the enforcement counterpart
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — uses this skill at dispatch
