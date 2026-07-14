# Conductor UI v3.0 — Full Pipeline Dispatch (2026-06-23)

The worked example of dispatching an entire multi-phase build plan in one session — 37 cards across 4 phases, auto-progressing via dependency graph.

## What happened

1. **Spec audit found v2.0 was wrong.** Browser + filesystem verification revealed the plan claimed mobile components, connector YAMLs, and drag-and-drop existed. None did. v2.0 deprecated, v3.0 written as single source of truth.

2. **All 4 phases dispatched in one session.** Phase A (fixes, 9 cards) → Phase B (shipping claimed, 8 cards) → Phase C (new features, 10 cards) → Phase D (QA gates, 10 cards). User said "dispatch like we planned" — then "keep going, don't wait for me to say next step."

3. **Pipeline auto-progressed.** Workers claimed cards, completed them, dependencies unblocked downstream cards. By session end: 54/54 done (including sub-cards spawned by workers).

## Key learnings

### One-file-per-card isn't absolute

The "one file = one card" rule is for logic/code files. For config/data files that share identical format and no interdependencies, batch them:

**Right:** 12 connector YAMLs → one card "Create 12 connector YAML definitions"
**Wrong:** 12 cards, one per YAML

The `change` field described "CREATE 12 YAML definitions" and max_loc_delta was set to 100 (flagging it as a create-card). The worker auto-decomposed into sub-cards (B3a, B3b, B3c) — which is fine; the idempotency key prefix groups them.

### Workers auto-decompose

When a card body describes creating multiple files, the worker may spawn sub-cards. B3 (12 YAMLs) became B3a/B3b/B3c. C1 (mobile) spawned variants. This means the DB will have MORE cards than were dispatched. Query by idempotency_key prefix to get the full set.

### Crashed worker recovery

Four cards silently failed (A3 Settings, A2d Card wiring, B1d Forge wiring, C2a DnD handlers):
- Status: `blocked` with task_runs in `gave_up` / `crashed` / `stale` state
- Summaries were empty (no error capture)
- Recovery: `UPDATE tasks SET status = 'ready', consecutive_failures = 0` then let workers re-claim

### Duplicate card cleanup

Idempotency key collisions created duplicates (C5 collided with webhook YAML, B4 duplicated trigger wiring). Resolution: `hermes kanban complete <id> --result "Duplicate of <id> — already shipped."`

### Obsolete card closure

B1c "Rewrite InterviewEngine" was blocked on iteration budget. But B1d "Wire forge.tsx" rewrote forge.tsx to use chat-forge-backend.ts directly, bypassing InterviewEngine entirely. B1c closed as obsolete.

The check: when a blocked card's summary mentions work already done, grep the codebase for the component it was supposed to modify. If it's no longer imported, the card is obsolete.

### Continuous dispatch principle

The user said: "I don't want to have to keep coming back to tell you to do the next step."

After dispatching one phase, immediately decompose and dispatch the next. Don't wait for "ok now do Phase B." The dependency graph handles ordering — cards without satisfied deps sit in `todo` until their parents complete. Put everything on the board.

### NEVER fix files manually during acceptance — dispatch a card

When the acceptance sweep found that board card click advanced status instead of opening a drawer, Hephaestus started manually editing `board.tsx` inline. The user stopped this: "Why are you not dispatching kanban cards to handle this? We use the exact same workflow as the rest of everything."

**The rule:** every fix — no matter how small — goes through the kanban. Card → worker → verify → done. Direct edits bypass QA, aren't tracked, and break the pipeline's evidence chain. The one exception: build-breaking import issues that prevent the pipeline from running at all.

**Follow-up pattern:** when a fix card (A7) introduces test failures (2/18 tests expect old behavior), dispatch a chaser card (A8) parented on A7 to update the tests. The dependency graph auto-queues it.

### Card-count creep is normal (and good)

The original dispatch was 37 cards. The final DB had 57. The 20 extra cards came from:
- Worker auto-subdivision (B3 split into B3a/B3b/B3c, C1 spawned sub-cards)
- Acceptance-sweep follow-ups (A7, A8, B5, D11)
- Duplicate cleanup (C5, B4, C2)

This is the system working — workers split cards that are too big, and follow-ups naturally extend the chain. Query by idempotency_key prefix, not by expected count.

### Build fix: Vite + Node.js modules in browser bundle

`ledger_client/index.ts` imported `local_stub.ts` which used `fs`, `path`, `crypto` — Vite tried to bundle Node.js modules into the browser build. Fix:

1. Remove server-only re-exports (`export * as migration from './migration'`)
2. Add `typeof window !== 'undefined'` check in `getDefaultClient()`
3. In browser: return lightweight no-op stub instead of importing LocalStub
4. In Node.js: use opaque import path (`const stubPath = './local_stub'; await import(stubPath)`) to prevent Vite's static analysis from tracing the import

## Idempotency key scheme used

```
conductor-phase-{a|b|c|d}-2026-06-23-NNN
```

Phase A: `conductor-phase-a-2026-06-23-010` through `-018`
Phase B: `conductor-phase-b-2026-06-23-020` through `-027`
Phase C: `conductor-phase-c-2026-06-23-030` through `-043`
Phase D: `conductor-phase-d-2026-06-23-050` through `-059`

The per-phase prefix keeps each phase's keys isolated. The date prefix prevents collisions across days.

## Dispatch command pattern

```bash
# Independent (no parent)
hermes kanban create --assignee marvin --idempotency-key "<prefix>-NNN" --body "<body>" --json "<title>"

# Dependent (parent is task_id from prior dispatch)
hermes kanban create --assignee marvin --idempotency-key "<prefix>-NNN" --parent t_xxxxxxxx --body "<body>" --json "<title>"
```

QA gate cards use `--assignee hephaestus-qa` with verify command `echo 'QA gate — manual browser verification'`.

## Board state queries

```sql
-- Full state by status
SELECT status, COUNT(*) FROM tasks 
WHERE idempotency_key LIKE 'conductor-phase-%' 
GROUP BY status;

-- Blocked cards with run summaries
SELECT t.id, t.title, t.status, tr.status as run_status, tr.summary
FROM tasks t
LEFT JOIN task_runs tr ON tr.task_id = t.id
WHERE t.idempotency_key LIKE 'conductor-phase-%' AND t.status IN ('blocked','todo');

-- Running cards with heartbeats
SELECT id, title, last_heartbeat_at, claim_expires
FROM tasks 
WHERE idempotency_key LIKE 'conductor-phase-%' AND status = 'running';
```
