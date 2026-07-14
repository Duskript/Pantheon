---
name: doc-discipline
description: "Use when you are about to commit a non-trivial code change, finish a feature branch, or end a session that touched Olympus/Pantheon source. Enforces the rule: every doc has a single home, every change verifies before declaring done, every decision is recorded. Universal skill for all Pantheon gods that change code (Marvin, Hephaestus)."
version: 1.0.0
author: Pantheon
license: MIT
metadata:
  hermes:
    tags: [pantheon, universal, doc-discipline, source-of-truth, change-discipline]
    related_skills: [auto-compact-topic-shift]
    config:
      doc_discipline:
        canonical_docs_index:
          description: "Path to the master index of canonical docs"
          type: string
          default: "~/athenaeum/Codex-Olympus/OLYMPUS_UI_STATE.md §13 'What to read next'"
        decisions_log:
          description: "Path to the append-only decisions log"
          type: string
          default: "~/athenaeum/Codex-Olympus/DECISIONS.md"
        drift_report:
          description: "Where the 3 AM verification cron writes drift findings"
          type: string
          default: "~/pantheon/shared/DOC_DRIFT.md"
        last_verified_grace_days:
          description: "How many days since 'last verified' before forcing a re-check"
          type: integer
          default: 7
        enabled:
          description: "Master toggle — set false to disable the discipline"
          type: boolean
          default: true
---

# Doc Discipline — Source-of-Truth Enforcement

**Purpose:** Prevent the documentation drift problem. Every doc has exactly one canonical home. Every change to code is paired with verification (or update) of the doc that describes it. Every non-obvious decision is recorded with rationale. Future agents (human or god) never have to re-litigate a decision you already made.

This is a **universal Pantheon skill** for any god that changes code or makes architectural decisions. It is required for Marvin and Hephaestus (the code-changers). It is light-touch (decisions-log only) for supporting gods (Hermes, Thoth, Caduceus, Apollo).

## When to invoke

Invoke this skill **before** any of the following:

- Committing a feature branch with more than one file of changes
- Opening a PR against `Duskript/Pantheon` or any Pantheon repo
- Declaring a session "done" if you changed code
- Pushing commits to a remote
- Switching context from "build" to "ship" on a feature

**Skip** the skill for:

- Single-line typo fixes
- Comment-only changes
- Pure refactors with no behavior change (but still apply Step 2)
- Read-only investigation sessions

## The discipline (5 steps)

### Step 1 — Identify the canonical doc

Every code area has **exactly one** doc that describes it as source of truth. For Olympus-UI, the canonical index is in `OLYMPUS_UI_STATE.md §13 "What to read next"`. For other codex areas, find the equivalent `STATE.md` or `INDEX.md` for that codex.

Rules:
- If a doc is a **pointer** (e.g., a stale tracker that just says "see [canonical path]"), do NOT update it. Update the canonical.
- If two docs claim the same content, **one is wrong**. Mark the loser as superseded, point at the winner, never duplicate content.
- If you don't know which doc is canonical, **stop and ask** (the user, or the canonical-doc index). Don't guess.

### Step 2 — Verify or update the doc

For each canonical doc relevant to your change:

1. Check the "last verified" date in the doc header. If older than `last_verified_grace_days` (default 7), the doc is stale and **must** be re-verified before commit.
2. Cross-check the claims the doc makes against current reality. The state doc, for example, claims specific values for tsc errors, vitest pass count, git divergence, bundle mtimes, service status. Each can be re-verified in <30 seconds.
3. If a claim has drifted, **update the doc in the same commit** as the code change. "I'll update it later" is the failure mode this skill exists to prevent.
4. If the change is too large to update the doc in-line, open a follow-up "doc refresh" commit immediately after, with a clear message naming what drifted.

The 3 AM verification cron (`doc-discipline-verify`, see `~/.hermes/cron/jobs.json`) runs the same checks. If it surfaces drift, the discipline failed — fix it before the next commit.

### Step 3 — Append to the decisions log

For any non-obvious decision you make during this change (chose library X over Y, used pattern P instead of the planning-doc's Q, diverged from a prior approach), append an entry to `~/athenaeum/Codex-Olympus/DECISIONS.md` (or your codex's equivalent). Format:

```markdown
### YYYY-MM-DD — Decision: <one-line summary>

**Decision:** <what you chose>

**Rationale:** <why, 2-5 sentences>

**Alternatives considered:** <what you rejected and why>

**Evidence:** <file paths, commit hashes, benchmark results, etc.>

**Reversibility:** <hard / soft / trivial>
```

The log is **append-only**. Never rewrite history. If a decision is reversed, append a new entry that says "Reversed: see [date of original]." Original stays intact.

### Step 4 — Mark superseded planning docs

If you diverged from a planning doc (e.g., a PHASE_*, BUILD_PLAN, or similar aspirational doc) and the planning doc is now wrong, **mark it superseded** rather than letting it drift silently.

Don't delete the planning doc. Don't rewrite it. Add a single line at the top:

```markdown
> **SUPERSEDED 2026-06-02:** See [canonical doc path] for current state.
> Original plan preserved below for historical reference.
```

This way the historical record stays, but anyone reading the planning doc immediately knows it's not the source of truth.

### Step 5 — Confirm the change is shippable

Before pushing, opening a PR, or declaring done:

- [ ] Canonical doc for the changed area is updated (or was already correct)
- [ ] "Last verified" date on the doc is within grace period (or you re-verified it)
- [ ] Any non-obvious decision has a DECISIONS.md entry
- [ ] Any planning doc you diverged from is marked superseded
- [ ] The commit message references the doc update if there was one (e.g., `fix(soul-forge): add interview mode (docs: OLYMPUS_UI_STATE.md §6)`)

If any checkbox is unchecked, fix it before pushing. **A "I'll fix the doc in a follow-up" is a known failure mode.** The discipline exists to make that impossible.

## Pitfalls (failure modes the discipline prevents)

| Pitfall | Why it happens | How the discipline prevents it |
|---------|----------------|-------------------------------|
| "I'll update the doc later" | Sunk-cost fallacy, "ship now, docs later" mentality | Step 2 makes it part of the same commit |
| "The doc is fine, the code is wrong" | Drifting toward "real world" without updating the map | The doc was the truth. Update the doc, then fix the code to match |
| "Two docs disagree" | Multiple planning docs, unclear authority | Step 1 forces canonical resolution before any change |
| "I'll add a note in chat" | Lossy medium, not searchable | Step 3 forces DECISIONS.md entry, not chat |
| "Re-litigating an old decision" | New agent doesn't know the rationale | Step 3 makes rationale findable |
| "Stale tracker that nobody updates" | Manual update burden grows, doc decays | Step 4 demotes stale docs to pointers (single line) |
| "Compounded drift after a year" | Each drift compounds the next | The 3 AM cron catches drift within 24h, not after a year |

## The 3 AM verification cron

A system-level cron job (not bound to any god profile) runs the verification checks from Step 2 daily at 3:00 AM local time. Output: `~/pantheon/shared/DOC_DRIFT.md`. Silent if no drift. The morning briefing picks up the drift report and surfaces it to whoever needs to act.

You do not run the cron yourself. You trust the cron to tell you when your work has drifted. When the cron surfaces drift, the discipline failed at some point — fix it as part of the next commit, don't defer.

## How to invoke in a session

In your response, before declaring any non-trivial work done, output a brief status block:

```
## Doc Discipline Status
- Canonical doc identified: [path]
- Last verified: [date, or "stale — re-verified in this commit"]
- Decisions logged: [list of new DECISIONS.md entries, or "none"]
- Planning docs marked superseded: [list, or "none"]
- Drift from 3 AM cron: [list, or "clean"]
```

If any of those is "I don't know" or "I didn't check," you have not applied the discipline. Apply it before declaring done.

## Cross-god coordination

- **Marvin and Hephaestus** are bound to the full discipline (Steps 1-5). Their SOUL.md modules enforce this.
- **Hermes, Thoth, Caduceus, Apollo** are bound to Step 3 only (decisions log). They make non-obvious decisions occasionally; they don't write code.
- **All gods** can read the verification cron's drift report and surface it to humans they work with.
- The cron is **system-level** (in `~/.hermes/cron/jobs.json`, no `prompt`, just a `script`). It runs regardless of which god is active.

## Related skills

- `auto-compact-topic-shift` — Compaction hygiene (different concern, complementary).
- `plan` — For multi-step work, plan-then-execute before applying doc discipline.
- `systematic-debugging` — For bug investigations, document findings in the canonical bug doc, not chat.

## Where this lives

- The skill: `~/pantheon/god-packages/shared-skills/doc-discipline/SKILL.md` (this file)
- The verification script: `~/pantheon/scripts/doc-discipline-verify.py`
- The drift report: `~/pantheon/shared/DOC_DRIFT.md` (created on first drift)
- The decisions log: `~/athenaeum/Codex-Olympus/DECISIONS.md` (per codex)
- The cron entry: `~/.hermes/cron/jobs.json` (id: `doc-discipline-verify`)
- The bound SOUL.md modules: `~/.hermes/profiles/marvin/SOUL.md` and `~/.hermes/profiles/hephaestus/SOUL.md`
