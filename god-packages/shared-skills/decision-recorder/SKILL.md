---
name: decision-recorder
description: "Use when an operator-locked decision is made, when a god's architectural decision needs to be logged, when a convention is locked, or when a build ships. Records the decision in the canonical format, updates the decisions index, and notifies the relevant gods. The decision log is append-only."
version: 1.0.0
tags: [decisions, log, audit, recording, operator-locked, append-only]
---

# Decision Recorder — The Append-Only Log

> **The skill that records every operator-locked decision, architectural choice, and convention lock in the canonical format.** The decision log is the source of truth for "what has been decided." Every god reads it before any chain. Reversals are new entries, never edits.

## When to use this skill

Load this skill whenever:

- The operator makes a decision (lock a convention, approve a plan, sign off a phase)
- A god makes an architectural decision (design a subsystem, choose a pattern)
- A build ships (the ship event is a decision)
- A convention is locked (the convention doc + a decision entry)
- A reversal happens (a new entry that points at the original)
- The operator asks "what did we decide about X?"

**Don't use this skill for:**

- Reading past decisions (just read `pantheon/shared/decisions/INDEX.md`)
- Writing the convention itself (use the convention-doc-shape standard)
- Authoring a plan (use the build-plan-orchestrator)

## How to use it (the procedure)

### Step 0: Determine the decision type

There are 5 decision types:

1. **Operator-locked** — the operator made the decision
2. **Architectural** — a god made the decision (with operator sign-off)
3. **Convention** — a new convention is locked
4. **Build event** — a build is dispatched, completed, or shipped
5. **Reversal** — a previous decision is reversed

Each type has a slightly different record format.

### Step 1: Gather the decision context

Before recording, gather:

- **What was decided?** (the decision itself, 1-3 sentences)
- **Why?** (the rationale, 1-2 paragraphs)
- **What else was considered?** (alternatives, with their pros/cons)
- **What's the evidence?** (citations, prior sessions, data, links)
- **How reversible is it?** (easy, hard, irreversible)
- **Who decided?** (the god, with the date)
- **Who signed off?** (the operator, if applicable)
- **What's affected?** (which canon docs, which chains, which gods)

If any of these are missing, ask before recording. A decision without rationale is not a decision.

### Step 2: Write the decision file

**Path:** `pantheon/shared/decisions/YYYY-MM-DD-<slug>.md`

**Format (per the convention-doc-shape standard's amendment protocol):**

```markdown
# YYYY-MM-DD — <decision title>

**Decision:** <the decision, 1-3 sentences>

**Rationale:** <why, 1-2 paragraphs, concrete, dated>

**Alternatives considered:**
- <alternative 1>: <pros> / <cons>
- <alternative 2>: <pros> / <cons>
- <alternative 3>: <pros> / <cons>

**Evidence:**
- <citation 1> (e.g., "2026-06-16 session with Konan, ~30 min")
- <citation 2>
- <link to prior decision, if any>

**Reversibility:** <easy | hard | irreversible>

**Decided by:** <god name> on <YYYY-MM-DD>

**Operator sign-off:** <konan | pending | not-required>

**Affected:**
- <canon doc 1>
- <canon doc 2>
- <chain 1>
- <god 1>
```

**For reversals, add:**

```markdown
**Reverses:** <the original decision (file path, date)>
**Reason for reversal:** <why we're reversing>
```

### Step 3: Update the decisions index

Append to `pantheon/shared/decisions/INDEX.md`:

1. **Chronological table** — add a row to the "Recent decisions" table
2. **Topical table** — if the decision is on a known topic (Architecture, Conductor, Standards, Operations, Build plans), add a row to the topical table

**Index format:**

```markdown
| Date | Title | One-line summary | File |
|---|---|---|---|
| YYYY-MM-DD | <title> | <one-line summary> | [YYYY-MM-DD-<slug>.md](YYYY-MM-DD-<slug>.md) |
```

### Step 4: Update the affected canon

If the decision changes a canon doc (a convention, a standard, a god profile, etc.):

1. **Update the canon doc** — apply the change, cite the decision
2. **Add a `supersedes:` entry** if the change replaces an older rule
3. **Add a `Last updated:` timestamp** in the frontmatter

If the decision affects an in-flight chain:

1. **Update the chain's status** — note the decision in the relevant task's comments
2. **Notify the chain's owner** — the decision may require a re-dispatch or revision

### Step 5: Notify the operator (primary) + relevant gods (only if operator directs)

**Operator-first rule (Konan, 2026-06-16):** Report decisions directly to the operator. Do NOT auto-notify a chain of gods — the operator routes to other gods if needed. The sovereignty guardrail (Rule #1) extends to decision notifications: the operator decides who needs to know.

| Decision type | Primary notify | Secondary (only if operator explicitly asks) |
|---|---|---|
| Operator-locked (new convention) | Operator | All gods (if operator says "tell everyone") |
| Architectural (subsystem design) | Operator | The god who'll implement (if operator says "send to Marvin") |
| Build event (ship) | Operator | All gods (if operator says "broadcast the ship") |
| Convention (locked) | Operator | All gods who use the convention (if operator says "notify them") |
| Reversal | Operator | The god who made the original decision (if operator says "let them know") |

**The pattern:** Write the decision, update the index, update the canon — then tell the operator what you did and what changed. Stop there. If other gods need to know, the operator will say so.

Use the `messaging_send` MCP tool or direct chat for operator notification. Do not use `hermes kanban notify-subscribe` unless the operator explicitly requested kanban-based notifications.

### Step 6: Verify the record

Before declaring the decision recorded:

- [ ] The decision file is at `pantheon/shared/decisions/YYYY-MM-DD-<slug>.md`
- [ ] The file has all 8 required fields (decision, rationale, alternatives, evidence, reversibility, decided by, operator sign-off, affected)
- [ ] The file follows the canonical format
- [ ] The decisions index is updated
- [ ] The affected canon docs are updated
- [ ] The relevant gods are notified

## Worked examples

### Example 1: Operator locks a new convention

**Decision:** "All builds live under `~/projects/<project-name>/`. Plans live under `~/pantheon/plans/`."

**Process:**

1. **Gather context** — operator's directive, the prior session where it was decided, the Hephaestus rework
2. **Write the file:** `2026-06-16-build-path-convention.md`
3. **Update the index** — add to chronological and topical
4. **Update affected canon** — `hephaestus-rework-workflow-god.md` cites the convention
5. **Notify** — all gods (the convention applies to every build)

**Output:**

```markdown
# 2026-06-16 — Build Path Convention

**Decision:** All god-initiated code/build projects live under `/home/konan/projects/<project-name>/`, in their own subfolder. The build plan document lives at `~/pantheon/plans/<project>-build-plan.md` (system source).

**Rationale:** Before 2026-06-16, build plans were drafted with implicit `~/pantheon/<project>/` paths. The `pantheon/` directory is the *system source* — it holds the runtime, the gods, the shared skills, the conductor config. Builds (artifacts of god work, designed to be shippable products) were getting tangled with system source. The operator directive: builds go under `~/projects/`, each in their own subfolder.

**Alternatives considered:**
- Build under `~/pantheon/builds/<project>/`: rejected — `pantheon/` is system source, not build output
- Build under `~/Desktop/<project>/`: rejected — not version-controlled, not part of the Pantheon infrastructure
- Continue with `~/pantheon/<project>/`: rejected — operator directive

**Evidence:**
- Operator directive 2026-06-16
- 9 path references in the conductor-ui build plan v1.1, patched 2026-06-16

**Reversibility:** easy — paths are file system, can be moved

**Decided by:** Konan on 2026-06-16

**Operator sign-off:** konan

**Affected:**
- pantheon/plans/conductor-ui-build-plan.md (patched)
- pantheon/god-packages/shared-skills/build-plan-orchestrator/SKILL.md (v1.0.4)
- athenaeum/Codex-Pantheon/design/build-path-convention.md (new doc)
```

### Example 2: Architectural decision (Hephaestus rework)

**Decision:** Hephaestus is reworked from "God of the Forge" to "God of Building and Architecture."

**Process:**

1. **Gather context** — the rework design, the operator's directive, the standards library
2. **Write the file:** `2026-06-16-hephaestus-rework.md`
3. **Update the index** — chronological + topical (Architecture)
4. **Update affected canon** — `gods.yaml` (Hephaestus entry), `god-roster.md` (lane description), the rework doc itself
5. **Notify** — the operator directly: "Hephaestus rework complete. 7 steps executed, 8 skills installed, dispatcher updated. Decision logged at `2026-06-16-hephaestus-rework-complete.md`. Conductor-ui chain ready when you unblock t3." (Do NOT auto-notify Thoth or other gods — the operator routes if needed.)

**Output:** the rework decision file with all 8 fields, plus the rework doc itself.

### Example 3: Build event (conductor-ui ships)

**Decision:** The conductor-ui build v1.1 ships Phase 5.

**Process:**

1. **Gather context** — the build plan, the phase gate, the QA reviews
2. **Write the file:** `2026-XX-XX-conductor-ui-ship.md` (when it actually ships)
3. **Update the index** — chronological + topical (Build plans)
4. **Update affected canon** — `build-status.md` (move from active to completed)
5. **Notify** — all gods (the build is live, the new subsystem is available)

**Output:** the ship event file.

## Integration with other skills

- **`plan-execution`** — when a build ships, plan-execution calls decision-recorder
- **`build-plan-orchestrator`** — when t4 sign-off happens, the orchestrator calls decision-recorder
- **`convention-enforcer`** — when a convention is locked, the enforcer updates its checks and decision-recorder logs the lock
- **`integration-designer`** — when an integration contract is written, decision-recorder logs the design decision

## When the decision log changes

The decision log is **append-only**. Old decisions are never edited (reversals are new entries). The log is in `pantheon/shared/decisions/` and the index is `pantheon/shared/decisions/INDEX.md`.

**Append rules:**

- New decision → new file + index update
- Reversal → new file that points at the original + index update
- Read past decision → read the file, don't edit
- Aggregate decision → write a new file that references the originals

## Pitfalls

**Don't over-notify — report to the operator, not a god chain (Konan, 2026-06-16).** The operator explicitly corrected this: "you don't need to report back to Thoth just report to me." The default pattern is: write the decision → update canon → tell the operator what changed. Do NOT auto-notify Thoth, Marvin, Iris, or any other god unless the operator explicitly says "send this to X." The sovereignty guardrail applies to notifications too — the operator is the decision-maker about who needs to know. Over-notifying creates noise (inbox clutter for gods who aren't involved) and violates the principle that the operator owns the routing.

**Don't record without rationale.** A decision without rationale is just an assertion. The log is for traceability, not assertions.

**Don't edit past decisions.** Append-only. Reversals are new entries.

**Don't forget the operator sign-off.** Operator-locked decisions need the operator's explicit sign-off. The skill records it.

**Don't skip the alternatives.** The alternatives show what was considered. The log is for understanding, not just recording.

**Don't forget the affected canon.** The decision may require updates to multiple docs. The skill's "affected" list is the reminder.

**Don't double-record.** If the decision is already in the log (e.g., the operator repeats a known decision), don't add a new entry. Just reference the existing one.

## Verification gates

Decision-recorder is "working" when:

- [ ] All 5 decision types are recorded correctly
- [ ] The canonical format is followed
- [ ] The decisions index is updated
- [ ] The affected canon is updated
- [ ] The relevant gods are notified
- [ ] The log is append-only (no edits to past decisions)

## See also

- `pantheon/shared/decisions/INDEX.md` — the decisions log index
- `Codex-Pantheon/design/standards/convention-doc-shape.md` — the convention doc shape (and the amendment protocol)
- `Codex-Pantheon/design/operator-rules-cheatsheet.md` — the operator-locked rules
- `Codex-Pantheon/design/hephaestus-rework-workflow-god.md` — the rework, an example of a decision being recorded
- `pantheon/god-packages/shared-skills/plan-execution/SKILL.md` — uses this skill at ship time
- `pantheon/god-packages/shared-skills/convention-enforcer/SKILL.md` — uses this skill when a convention is locked
- `references/pantheon-dashboard-routing-demo.md` — end-to-end keyword-to-god routing demo (Pantheon Health Dashboard, 2026-06-16)
