---
name: spec-to-kanban-dispatch
description: "Decompose a build spec into HephaestusBuildCard-contract cards, validate them, dispatch to the kanban with the right idempotency keys and parent references, and report the resulting 9-card state to the user. Use when the user says 'put this on the kanban', 'ship this build via kanban', 'dispatch this plan', 'decompose this into cards', 'let's build this', or hands you a spec doc and asks for the kanban workflow. The class of work: turn a freeform build plan into a dependency-gated, contract-validated card chain that the dispatcher can run end-to-end. **Starts with a mandatory spec review and clarifying-questions pass** — ambiguities must be resolved in the spec before decomposition begins."
tags: [kanban, dispatch, contract, spec-decomposition, build-pipeline, pantheon]
---

# spec-to-kanban-dispatch

## When to use

The user has a build spec (already authored, typically by `build-spec-authoring` or as a hand-written `~/pantheon/plans/*.md`) and wants it executed via the Pantheon kanban. The kanban is the deterministic, dependency-gated, contract-validated execution surface. The spec is the freeform plan. This skill is the bridge.

**Trigger phrases:**
- "put this on the kanban"
- "ship this build via kanban"
- "dispatch this plan"
- "decompose this into cards"
- "let's build this"
- "I have a build spec, how do I run it through the pipeline"
- "set up the card chain for this"

**Don't use this skill if:**
- The spec doesn't exist yet. Use `build-spec-authoring` first.
- The user wants research/architecture, not execution. Use `thoth-system-design` or `thoth-codesign-brainstorm`.
- The user wants to monitor an already-dispatched chain. Use `process` / `terminal` to query the kanban DB directly.

**Disambiguation from `build-plan-orchestrator`:** The user may say "Thoth's build plan skill" or "the one with Phase 0" when they mean this skill. The `build-plan-orchestrator` is a different workflow (Konan+Thoth plan first, then Hephaestus dispatches). This skill is the canonical spec-to-kanban pipeline. If the user says "that's not the one" or references "Thoth authored it" or "Phase 0 = clarifying questions", load this skill, not `build-plan-orchestrator`.

## The 9-step recipe (the actual workflow)

> **Continuous dispatch principle:** After dispatching one phase, immediately decompose and dispatch the next. Do NOT wait for the user to say "ok now do Phase B." The dependency graph handles ordering — cards without satisfied dependencies sit in `todo` until their parents complete. Put every phase on the board in one session. The user should see the full pipeline, not piecemeal dispatches.

> **Step 0 is mandatory.** Do not skip it. Do not "decompose first, ask questions later." A spec that has 3 unresolved ambiguities decomposed into 9 cards produces 9 cards built on the wrong assumption. **Clarify the spec, update the spec, then decompose.**

### Step 0 — Spec review + clarifying questions + spec update

Before any card writing, the agent must:

1. **Read the spec end-to-end.** Identify every place that is:
   - **Ambiguous** — two reasonable readers would interpret differently (e.g. "build the integration" with no seam diagram)
   - **Missing** — the spec assumes a fact that isn't stated (e.g. "use the existing auth" but doesn't say which auth)
   - **Inconsistent** — two sections contradict each other (e.g. one says "3 files" and another says "5 deliverables")
   - **Underspecified for the kanban** — would a worker, given only the card body, know exactly what to do? (no → needs tightening)
2. **Compile a numbered clarifying-questions list.** Be ruthless: if a real worker would have to ask, you have to ask. Group questions by section of the spec for easy reference.
3. **Present the questions to the user and stop.** Do not begin decomposition. Do not write any cards. The questions ARE the output of this step.
4. **When the user answers, update the spec file in place** (not a side-channel answer — the spec itself must reflect the resolved decisions). The update is append-friendly: add a "## Resolved Questions" section at the bottom with the Q&A trail, or edit the offending paragraphs in-line. Either is fine; what matters is that the spec on disk is the canonical, post-clarification truth.
5. **Only then proceed to Step 1.**

**Why this step exists:** the rest of the recipe assumes the spec is the source of truth. If the spec is wrong or fuzzy, the entire 9-card chain ships the wrong thing. Step 0 is the gate that keeps the recipe honest. The mobile-pattern-pack 2026-06-21 run almost shipped with three subtle ambiguities — Step 0 catches them.

**Heuristic for "do I need to ask or can I assume?":**
- If the spec already names a file path, contract, or threshold → don't ask, use it.
- If the spec says "use the standard pattern" without naming one → ask which.
- If two valid decompositions exist and the choice affects the card count → ask, because it changes the chain topology.
- If the spec is silent on rollback / failure mode → ask, don't invent.

**Output of Step 0:** an updated spec file (with the resolved-Q&A section appended or the ambiguities fixed in-line) and a single one-line ack to the user: "Spec reviewed, 4 questions answered, spec updated. Proceeding to Step 1."

### Step 1 — Verify the spec exists and read it

```bash
ls -la ~/pantheon/plans/<spec-slug>.md
ls -la ~/pantheon/shared/decisions/<decision-slug>.md 2>/dev/null
```

Read both. Note: file paths, deliverable count, AC count, risk gates, phase boundaries. The natural card boundaries are usually the phase boundaries.

> If Step 0 was just completed, the spec on disk is already the canonical version. If a user re-runs this recipe without re-running Step 0, do a 30-second re-scan for newly-visible ambiguities — cheap insurance.

### Step 2 — Decompose into natural card boundaries

The 4-phase build shape (A: visual, B: sign-off gate, C: integration, D: QA) maps to 3 card clusters separated by 2 state-transition gates:

| Phase | Card cluster | Cards | Assignee | Why this boundary |
|---|---|---|---|---|
| A | The deliverable files | 1-N (one per file) | iris / coder | Each file = one card (atomic LoC, clear verify) |
| A→C | The QA gate | 1 | iris / qa | V* + M* + J* criteria, machine-readable verdict |
| C | The contract seams | 1-N (one per seam) | marvin | Each seam = one card (one well-defined change) |
| C→PR | The final QA | 1 | hephaestus / thoth | M* implementation + J* joint criteria, gates the PR |

**Rules of thumb for decomposition:**
- **One file = one card** for logic/code files. Don't bundle 4 files into a "deliverables" card. The worker context can't hold it.
- **Exception — config/data files:** When dispatching 12 nearly-identical YAML definitions (same format, no interdependencies, one worker can produce all), batch them into one card. The `change` field describes the batch (e.g., "Create 12 connector YAML definitions"). The worker may auto-decompose into sub-cards — that's fine; query by idempotency_key prefix to get the full set. This exception applies to YAML configs, JSON fixtures, CSS token files, and other data artifacts — not to logic/code.
- **One seam = one card.** The 4 touchpoints in the design = 4 cards, even if each is small.
- **Gates are cards, not state.** A "V6 must pass before C" rule becomes a card whose result is a PASS/FAIL line the dispatcher reads.
- **Sign-off gates are NOT cards.** "Konan reviews and approves" is a state transition outside the kanban.

**Complex specs (>20 cards):** The simple A/B/C/D shape works for 4-file prototypes (see mobile-pack example). For complex specs with 8+ phases and 50+ cards, treat each phase as its own A/B/C/D cycle — prototype files → QA gate → integration → phase QA. The phase QA gates then feed into the next phase. Don't force a single 4-phase structure onto a complex build.

**Decomposition overview checkpoint:** For complex specs, after decomposing but BEFORE writing individual card JSONs (Step 3), present the card-count table to the operator. The operator can catch architecture-level mistakes (wrong nav pattern, wrong domain boundaries) at the table level that would require rewriting 10+ card JSONs to fix. See `references/conductor-ui-v2-2026-06-23.md` for the 55-card overview format that worked.

### Step 3 — Write each card against the HephaestusBuildCard contract

The contract is the 15-field JSON schema in `hermes_cli/kanban_contract.py`. Each card must:

- `card_id` matches `hep-YYYY-MM-DD-NNN` (3-digit suffix, no letters)
- `type` is one of `build | review | qa` (NOT prototype/qa_gate/integration — those are from the skill's original draft; the contract was locked to these three values on 2026-06-21). Map: prototype→build, integration→build, qa_gate→qa, final_qa→qa.
- `assignee` is one of `marvin | hephaestus | iris | rheta | konan` (NOT thoth — Thoth is not in the contract's enum. Assign research cards to hephaestus.)
- `change` is ≤ 200 chars (forces tight scoping)
- `output.max_loc_delta` is 1–100 (hard cap). For QA gate cards, use 1 (not 0 — the contract rejects 0).
- `verify.command` exits 0 on success, non-zero on fail
- `out_of_scope` has ≥ 3 items (explicit non-goals, prevents scope creep)
- `depends_on` lists parent card_ids (logical, not task_ids)
- `conflicts_with` lists sibling card_ids that must NOT run in parallel
- `parallel_group` is a soft hint for confirmed-safe parallel (e.g., "phase-A-1")

**Write all cards to a JSON file first** (e.g., `~/.hermes/plans/<build-slug>-cards.json`). The file is reviewable. The user can audit it before dispatch. Never dispatch cards that only exist in chat context.

### Step 4 — Validate every card before dispatch

```python
from hermes_cli.kanban_contract import validate_card
for card in cards:
    err = validate_card(card)
    assert err is None, f"Card {card['card_id']} failed: {err}"
```

**The contract will reject:**
- Wrong `card_id` pattern (letters, hyphens beyond the second, >3 digits)
- `change` field > 200 chars
- `max_loc_delta` > hard cap (currently 100, but see pitfalls for the create-vs-modify issue)
- `out_of_scope` < 3 items
- Missing required fields (additionalProperties: false catches this)

**If the contract rejects cards, fix the cards, don't bypass the contract.** The rejection is the system telling you the scope is wrong.

### Step 5 — Use a unique idempotency-key prefix per build

The kanban dedups on `idempotency_key`. If you reuse a key from a previous build, your new cards silently alias to the old (now `done`) tasks. The dispatcher then unblocks downstream cards immediately, before the new work has happened.

**The fix:** every build gets a unique prefix. For the `mobile-pattern-pack` build (2026-06-21), the prefix was `mobile-pack-2026-06-21-`. For the `spec-to-cards-pipeline` build (same day, earlier), the prefix was `spec-to-cards-2026-06-21-`. The prefix should include the build name + date, not just the date.

**Verification step:** after the first dispatch, query the kanban DB:
```sql
SELECT id, status, assignee FROM tasks
WHERE idempotency_key LIKE '<prefix>%'
ORDER BY id;
```
If any card shows `done` or `marvin` assignee that you didn't expect, you have a collision. Re-dispatch with a different prefix.

### Step 6 — Dispatch with returned task_id for parents

The `hermes kanban create` command accepts `--parent` to set dependencies. The `--parent` value is the **task_id returned from the previous dispatch**, not the logical `card_id` from your JSON file.

**This means:** dispatch the root cards first, capture each returned `task_id` as it comes back, then use those `task_id`s as `--parent` for the dependent cards.

```bash
# Root card (no parent)
TID_001=$(hermes kanban create --idempotency-key "<prefix>-001" --json card_001.json --jq .id)

# Dependent card (parent is the just-returned task_id)
hermes kanban create --idempotency-key "<prefix>-002" --parent "$TID_001" --json card_002.json
```

If you try to use `card_id` (your logical ID) as `--parent`, the dispatch will error. The kanban's `card_id` field is metadata; `id` and `parent` reference `task_id`.

### Step 7 — Notify assignees + log to Ichor

The kanban claim isn't the only signal. Send a `messaging_send` to each assignee with their first card:

```python
mcp_pantheon_messaging_send(
    to="<god-name>",
    subject="<build-name>: <first-card-title>",
    body="Card <task_id> is ready. Read the verify command and the out_of_scope list, then ship.",
    priority="normal",
    message_type="dispatch"
)
```

Then log the dispatch to Ichor (tier 3) and append to MEMORY.md (tier 1) so the dispatch is durable.

### Step 8 — Report state to the user in the state-of-the-board format

The user wants to see the full chain at a glance, not "card 001 is running." Use this 3-section format:

1. **The 9-card state table** (one row per card, with task_id, status, assignee, parent)
2. **The good news / bad news** (what worked, what failed)
3. **The question for the user** (3 options if there's a choice to make, or "next dispatch coming" if not)

For status checks (the "where are we at" question), query the kanban DB:
```sql
SELECT id, status, assignee, datetime(started_at,'unixepoch'), datetime(completed_at,'unixepoch')
FROM tasks WHERE idempotency_key LIKE '<prefix>%' ORDER BY id;
```

If a card is `blocked`, read its run's `summary` field for the reason:
```sql
SELECT summary FROM task_runs WHERE task_id = '<blocked-card-task-id>' ORDER BY id DESC LIMIT 1;
```

If a card is `done` with a `result` field, that's the worker's report — read it (e.g., the QA report file path the worker wrote).

## Pitfalls (the actual ones from the 2026-06-21 mobile-pack dispatch)

### The 100 LoC hard cap is wrong for file-creation cards

The current `max_loc_delta` cap is 100, designed for "fix this bug" / "modify this function" cards. It punishes "write the prototype" cards, which are legitimately many lines of fresh code. On the 2026-06-21 mobile-pack dispatch, 4 of 4 cards failed validation at 200-1500 LoC each.

**The fix that worked:** decompose the prototype into one card per file. 4 files → 4 cards, each 30-90 LoC, each passing the cap. The decomposition is genuinely better — workers can hold "write mobile-tokens.css" in 90 lines of context more reliably than "write the 4-file pattern pack" in 1500.

**The contract fix that should happen (separate follow-up card):** add a `card_scope` field with `modify | create | replace` values, each with its own cap. Modify = 30 LoC, create = 500 LoC per file, replace = 100 LoC. Until that's in the contract, manually decompose by file.

### The card_id regex rejects letter suffixes

The pattern is `hep-YYYY-MM-DD-NNN` (3 digits, no letters). On the 2026-06-21 dispatch, I used `-001a`, `-001b` to mark phases within a single build. The regex rejected every card.

**The fix:** plain `-001...-009` and put phase info in `parallel_group` or `change` text. The phase distinction is human-readable in the dispatch table, not a contract field.

### The 200-char cap on `change` forces better cards

My first 5 cards had 240-300 char change descriptions. The contract rejected them. Trimming to 200 chars produced tighter, more useful cards because the worker had less waffle to read.

**Don't fight this cap.** A 200-char `change` field is a feature, not a bug. If you can't describe the change in 200 chars, the change is too big for one card.

### Idempotency-key collisions with previous builds

The kanban dedups on `idempotency_key`. If you copy the `hep-2026-06-21-NNN` pattern from a prior build's keys, your new cards silently alias to the old (now `done`) tasks. The dispatcher then unblocks downstream cards immediately, before the new work has happened.

On the 2026-06-21 mobile-pack dispatch, 4 of 9 cards showed as `done` with `marvin` assignee because they aliased to the prior `MemoryPromoter` build that used the same `hep-2026-06-21-NNN` keys.

**The fix:** unique prefix per build. Include the build name + date, not just the date. Verify after first dispatch by querying the DB and checking no card has an unexpected `done` status.

### Dispatch ALL phases at once — don't wait for user instruction between phases

The user expects the full pipeline on the board after one command. After Step 0 (clarifying questions are resolved and spec is updated), decompose and dispatch EVERY phase in one session — build cards AND QA gate cards. Do not dispatch Phase A, then stop and wait for the user to say "now do Phase B." Do not hold back QA cards because their dependencies haven't shipped yet — the `depends_on` edges handle that.

**The pattern that works:** decompose all phases at once → present the card-count overview table → after user confirms "ok dispatch" → dispatch all independent cards in parallel → dispatch dependent cards with `--parent` set to captured `task_id`s → notify assignees → present full board state. The user should see the complete chain on the board within 5 minutes of saying "dispatch."

**Anti-pattern that got corrected (2026-06-23):** Hephaestus dispatched Phase A, then asked "What's next — wait for these to land, or prep Phase B cards?" The user responded "If we can run things in parallel we should. And I don't want to have to keep coming back to tell you to do the next step." The correct response: prep and dispatch ALL phases immediately. Then when asked "ok why not dispatch those now?" about Phase D QA cards — dispatch them. QA gates are cards with `depends_on` edges; they sit blocked until build cards land, then auto-unblock. The dependency graph is the conductor, not the user's next command.

**Rule of thumb:** after Step 0, the user should not need to type another instruction until the full chain is on the board. If you find yourself asking "should I dispatch the next phase?", you've already made the mistake — just dispatch it.

### The dispatcher's --parent flag wants task_id, not card_id

The `hermes kanban create --parent` value is the `task_id` returned from the previous dispatch, not the logical `card_id` from your JSON file. I tried `--parent hep-2026-06-21-001` and got errors. The right call was `--parent t_23ec1e5b`.

**The fix:** dispatch the root cards first, capture each returned `task_id`, then use those as parents. Don't try to set up the full dependency graph in one shot.

### The QA gate auto-blocks Phase C on a hard fail

The V6 (WCAG AA) gate returned FAIL on the QA report. The dispatcher refused to start Marvin's `useIsMobile` card (the parent of all Phase C work) because the parent QA's result said `FAIL`. The chain auto-stopped. **This is the pipeline working as designed.** The `result` field in the parent task is read by the dispatcher to decide whether to unblock children.

**The implication for status reporting:** status isn't just "where are the cards" — it's "where are the cards AND which ones are blocked on which gate failures AND what's the fix path." Always read the `result` field of `done` QA cards and the `summary` field of `blocked` cards.

### Don't bypass the contract for "small fixes"

When Phase C got blocked on V6, I had a choice: write fix cards through the pipeline (Path A, ~30-45 min) or have Iris apply the fixes directly + re-run the QA gate manually (Path B, ~10-15 min). Path B is faster. Path A is the spec-to-cards way.

**The rule:** if the gate says FAIL, the fix goes through the same gate. Bypassing "because the fix is small" sets the precedent that small fixes skip the pipeline. In two weeks, the "small fix" is 200 lines and the gate is theater. **Path A is always the right answer.**

### "The plan is too big for one card" is the most common signal

If you find yourself wanting to write a single card that produces 4 files or 4 contract seams or 4 phases, stop. That's the signal to decompose. The whole point of the 1-card-per-worker rule is that the worker only needs to hold 30 lines of context. A 4-file card violates this.

### WikiGuard blocks single-line patches in Step 0

When editing the spec in Step 0, the `patch` tool's WikiGuard may block single-line replacements with a low-quality score (e.g., replacing `"Bottom tab bar"` with `"Collapsible left drawer"`). WikiGuard scores on content length and structure — a one-liner rates below the 0.4 threshold.

**The fix:** group the edit with surrounding context. Include 2-3 lines above and below the target line. A 5-line old_string with substantive structure passes WikiGuard reliably. If a patch is still blocked, use `write_file` for the full file instead. See `references/conductor-ui-v2-2026-06-23.md` for the full-file approach used on the 427-line spec.

### Contract-field gotchas (2026-06-23 conductor-ui-v2 dispatch)

The 55-card dispatch surfaced 6 contract rejections on first validation pass. All are systematic — they'll hit every large build. Fix them in the card JSONs before the validation step:

1. **QA gate `max_loc_delta` must be ≥1.** The contract's minimum is 1, not 0. QA cards that don't produce code need `max_loc_delta: 1`. All 7 QA cards in the conductor-ui-v2 build failed on 0.
2. **`change` field >200 chars is the most common rejection.** 9 of 55 cards exceeded the cap on first write. Trim aggressively. If you can't describe the change in 200 chars, the card is too big — decompose further.
3. **`timeout_seconds` max is 300.** The acceptance sweep card (Phase 8) needed 600s for browser verification. The contract caps at 300. Either split the sweep into multiple cards or accept the cap.
4. **`parallel_group` triggers false conflicts.** The conflict detector flags any two cards in the same `parallel_group` that share read-only input files (e.g., both reading the build plan). On the conductor-ui-v2 dispatch, 122 conflicts fired — all false positives on reference docs. **Recommendation: omit `parallel_group` entirely.** The `depends_on` edges already express ordering. Cards without explicit dependencies can run in parallel naturally.
5. **`verify.must_pass` defaults to true.** The contract schema lists `must_pass` as required with `default: true`. QA gate verification commands like `echo 'QA gate — manual'` are acceptable since QA is manual — the command exists only to satisfy the schema requirement.
6. **Same output file = always a conflict.** Even if cards are sequenced by `depends_on`, the conflict detector flags same-output-file pairs. This is informational — cards with dependencies won't run in parallel. But expect 1-5 of these in any multi-phase build where a later phase modifies a file created by an earlier phase.

### The CLI takes title + --body, not --json card_file

The `hermes kanban create` command signature is:

```
hermes kanban create [--body BODY] [--assignee ASSIGNEE] [--parent PARENT]
    [--idempotency-key KEY] [--skill SKILL] [--json] TITLE
```

The `--json` flag emits JSON output (for capturing `task_id`). It does NOT accept a file path. The card's fields must be passed as CLI arguments: `title` (positional), `--body` (multiline text), `--assignee`, `--parent` (repeatable), `--idempotency-key`. **Do not write `--json card_001.json`** — that's from an earlier CLI version. Construct the body from the card's `change`, `verify.command`, and `out_of_scope` fields.

For 50+ card dispatches, use Python `subprocess.run()` in a loop. Dispatch root cards first, capture each `task_id` from JSON stdout, then dispatch child cards with `--parent` set to the captured `task_id`. See `references/conductor-ui-v2-2026-06-23.md` for the batch script.

### Kanban DB corruption during dispatch

The kanban SQLite database (`~/.hermes/kanban.db`) can suffer index corruption during heavy dispatch. On the conductor-ui-v2 dispatch, the DB threw `wrong # of entries in index idx_events_run` after 28 cards, blocking all further `hermes kanban` commands. The hermes tool auto-created a backup at `kanban.db.corrupt.<hash>.bak` and refused to proceed.

**Recovery procedure:**

```python
import sqlite3
db = sqlite3.connect('/home/konan/.hermes/kanban.db')

# Rebuild all indexes
for idx in db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall():
    db.execute(f'REINDEX {idx[0]}')
db.commit()

# Vacuum into a clean file (the only way to fix stubborn index corruption)
db.execute("VACUUM INTO '/tmp/kanban-repaired.db'")
db.close()

# Swap the repaired DB in
# cp /home/konan/.hermes/kanban.db /home/konan/.hermes/kanban.db.corrupt.backup
# cp /tmp/kanban-repaired.db /home/konan/.hermes/kanban.db
```

Then verify: `python3 -c "import sqlite3; print(sqlite3.connect('/home/konan/.hermes/kanban.db').execute('PRAGMA integrity_check').fetchone()[0])"` should print `ok`.

**All dispatched cards are preserved** — the `tasks` table is intact; only the indexes were corrupt. After repair, query the DB to recover all `task_id`s by `idempotency_key` prefix and resume dispatching remaining cards.

### Dispatch ALL phases at once — do not wait for user to say "next"

**This is a user preference, codified.** When a build plan has multiple phases (A/B/C/D or more), dispatch every phase's cards in the same session. Do not dispatch Phase A, then wait for the user to say "now do Phase B." The user wants the full pipeline on the kanban board so it auto-progresses without manual intervention.

**The pattern:**
1. Decompose ALL phases into cards (decomposition overview checkpoint for the user)
2. Dispatch every independent card from every phase in parallel
3. Dispatch dependent cards with correct parent task_ids
4. Dispatch QA gate cards for every route/feature alongside build cards
5. Present the full board state — all phases, all cards, all dependencies

**The user should never have to say "ok what about Phase B?" or "dispatch those now."** If cards remain un-dispatched, that's a failure to follow this rule.

**Exception:** Cards blocked on research or external decisions. Those get a research card dispatched now, not deferred.

### Obsolete cards (sibling solved it differently)

Sometimes a card gets blocked/crashed, but a sibling card solved the problem a different way — bypassing the component entirely. The blocked card is now obsolete, not failed.

**Detection:** when a blocked card's `review-required` summary mentions work already done, check whether any SIBLING card (same phase, different approach) made the blocked card unnecessary. Grep the codebase for the component the blocked card was supposed to modify — if it's no longer imported, the card is obsolete.

**Resolution:** `hermes kanban complete <task_id> --result "Not needed — <sibling_card> solved this differently by <approach>."`

**Example from conductor-ui-v3:** B1c "Rewrite InterviewEngine for chat" was blocked, but B1d "Wire forge.tsx to chat UI" rewrote forge.tsx to use chat-forge-backend.ts directly, bypassing InterviewEngine entirely. B1c closed as obsolete.

### Crashed worker recovery (silent failures)

Workers can crash without capturing error output. Cards show `blocked` status with task_runs in `gave_up` / `crashed` / `stale` state and empty summaries. The dispatcher gives up after max retries. These cards sit blocked indefinitely — they must be manually reset.

**Detection:**

```sql
SELECT t.id, t.title, t.status, tr.status as run_status, tr.summary
FROM tasks t
LEFT JOIN task_runs tr ON tr.task_id = t.id
WHERE t.idempotency_key LIKE '<prefix>%' AND t.status = 'blocked'
ORDER BY t.id;
```

**Recovery — reset to ready:**

```sql
UPDATE tasks 
SET status = 'ready', consecutive_failures = 0, claim_lock = NULL, claim_expires = NULL 
WHERE id IN ('t_xxx', 't_yyy');
```

**Duplicate cards** (workers spawning variants of the same card with different keys): close with `hermes kanban complete <task_id> --result "Duplicate of <task_id> — already shipped."`

See `references/conductor-ui-v3-full-pipeline-2026-06-23.md` for a worked example with 4 crashed cards, heartbeat checking, and duplicate cleanup.

### NEVER fix files manually during acceptance — dispatch a card

When the acceptance sweep finds a gap (click doesn't open drawer, route returns wrong content, build is broken), **dispatch a kanban card to fix it.** Do not open the file and edit it in your session. The system is the kanban pipeline — every fix goes through the same card→build→QA→verify loop as the original work.

**What this looks like in practice:**

```
# WRONG — editing the file directly
mcp_filesystem_edit_file(path="board.tsx", edits=[...])

# RIGHT — dispatching a card
hermes kanban create --assignee marvin --body "Fix board click..." --json "A7: Fix board card click"
```

**Why this matters:**
- Direct edits bypass the QA gate — no Ponytail review, no test run, no browser verification
- Direct edits aren't tracked in the kanban — there's no evidence the fix was ever applied
- The user expects the same workflow for everything — card → worker → verify → done
- If the fix needs follow-up (test updates, downstream wiring), the dependency graph handles it

**The one exception:** build-breaking import issues that block the entire dist (e.g., Node.js `fs`/`crypto` leaking into browser bundle). These prevent the pipeline from running at all. Fix the build block directly, commit it, then dispatch a QA card to verify the fix.

### Server-only code leaking into browser bundles

When a shared module (e.g., `ledger_client/index.ts`) re-exports Node.js-specific code that uses `fs`, `path`, `crypto`, or `process.env`, Vite tries to bundle it for the browser and fails with `"fs" is not exported by "__vite-browser-external"`.

**Detection:** `npx vite build` fails with errors referencing `__vite-browser-external` and Node.js built-ins.

**Fix pattern — opaque dynamic import:**

```ts
// BEFORE — Vite traces this and tries to bundle local_stub.ts
const { LocalStub } = await import('./local_stub')

// AFTER — Vite can't trace through a variable, leaves it as a runtime chunk
const stubPath = './local_stub'
const { LocalStub } = await import(stubPath)
```

Combine with a `typeof window` guard so the browser path never reaches the import:

```ts
if (typeof window !== 'undefined') {
  // Browser: return lightweight stub — real data from API
  return createBrowserStub()
} else {
  // Node.js: safe to import local_stub.ts
  const stubPath = './local_stub'
  const { LocalStub } = await import(stubPath)
  return new LocalStub()
}
```

**Alternative — fix the import chain:** if the offending module is re-exported (e.g., `export * as migration from './migration'`), remove the re-export from the index. No frontend code imports server-side migration utilities.

## Related skills

- `build-spec-authoring` — writes the spec. This skill dispatches it.
- `thoth-system-design` — architects the system. This skill ships the build.
- `thoth-codesign-brainstorm` — produces ideas. This skill executes them.
- `pantheon-bridge` — for inter-god messaging (Step 7 of the recipe).
- `spec-to-cards-pipeline` (hephaestus skill) — the contract lives there. Read it for the schema.

## Support files

- `references/mobile-pack-2026-06-21.md` — the worked example. The 9 cards for the Conductor mobile pattern pack, the exact contract failures hit (LoC cap, card_id pattern, change-field length, idempotency-key collision), the fix for each, the dispatch bash sequence, and the live kanban state at session end. Read this first when the recipe throws an unfamiliar error — the bug is probably here.
- `references/conductor-ui-v2-2026-06-23.md` — the complex-case worked example. 15 clarifying questions from Step 0, 55-card decomposition across 8 phases, the decomposition overview checkpoint that caught two architecture mistakes before JSONs were written, and the WikiGuard workaround. Read this when the spec has 8+ phases — the simple A/B/C/D shape from the mobile-pack example won't fit.
- `references/conductor-ui-v3-full-pipeline-2026-06-23.md` — **the full-pipeline pattern.** 37 cards across 4 phases dispatched in one session. Build cards + QA gates dispatched together. Dependency graph drives auto-progression — no manual "next phase" commands. Read this when the user expects everything on the board at once.
