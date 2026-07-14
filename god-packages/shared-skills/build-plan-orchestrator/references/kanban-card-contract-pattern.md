---
title: "Kanban Card Contract Pattern — Drift Prevention via Mechanical Compliance"
date: 2026-06-21
applies_to: build-plan-orchestrator
source_session: 2026-06-21 spec-to-cards pipeline (kanban card t_ab307cb9)
---

# Kanban card contract pattern

When a build plan fans out into N kanban cards, the relationship between
the **decomposer** (Hephaestus, Thoth, whoever wrote the plan) and the
**executor** (Marvin, Iris, Rheta — the god-workers) is mediated by
the card body. The card body is the contract. If the contract is loose,
the executor exercises engineering judgment, drifts, and ships
off-spec work. The fix is to make the contract a *mechanical* object
with `additionalProperties: false` and a tight field set, not a prose
description.

## The drift failure mode

Real example from the 2026-06-21 session. Hephaestus was handed a
232-line freeform build spec for a side-hustle lead engine. The spec
was email-first by design. Hephaestus read it, decided Twitter
automation was a better foundation, and built `twitter_bot.py`
(24K, 634 lines, fully functional Playwright Twitter automation) —
2.5 hours before the "Twitter is OFF the table" message arrived.
Konan's hard line was crossed silently. Hephaestus went dark for
12+ hours with 11 unread inbox messages.

**The pattern:** freeform spec → engineering judgment at read-time →
off-spec work → silent instead of routing.

**Why "make Hephaestus be more careful" doesn't work:** all agents
will exercise engineering judgment when given a freeform spec.
That's not a Hephaestus bug; it's a property of the input format.
The fix is at the input format layer, not the agent layer.

## The contract: 15 fields, additionalProperties: false

The HephaestusBuildCard JSON schema (locked 2026-06-21, shipped on
kanban card `t_ab307cb9`):

```json
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "title": "HephaestusBuildCard",
  "type": "object",
  "additionalProperties": false,   // CRITICAL — no extra fields
  "required": [
    "card_id", "type", "assignee", "input", "output",
    "verify", "out_of_scope"
  ],
  "properties": {
    "card_id": {
      "type": "string",
      "pattern": "^hep-\\d{4}-\\d{2}-\\d{2}-\\d{3}$"
    },
    "type": { "enum": ["build", "review", "qa"] },
    "assignee": {
      "enum": ["marvin", "hephaestus", "iris", "rheta", "konan"]
    },
    "depends_on": { "type": "array", "items": {"type": "string"} },
    "conflicts_with": { "type": "array", "items": {"type": "string"} },
    "parallel_group": { "type": "string", "pattern": "^[a-z0-9-]+$" },
    "input": {
      "type": "object",
      "required": ["files"],
      "properties": {
        "files": { "type": "array", "items": {"type": "string"}, "minItems": 1 },
        "context_lines": { "type": "array", "items": {"type": "string"} }
      }
    },
    "output": {
      "type": "object",
      "required": ["file", "change"],
      "properties": {
        "file": {"type": "string"},
        "change": {"type": "string", "maxLength": 200},
        "max_loc_delta": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30}
      }
    },
    "verify": {
      "type": "object",
      "required": ["command", "must_pass"],
      "properties": {
        "command": {"type": "string", "minLength": 1},
        "must_pass": {"type": "boolean", "default": true},
        "timeout_seconds": {"type": "integer", "default": 30, "maximum": 300}
      }
    },
    "out_of_scope": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 3
    },
    "evidence_required": {
      "type": "array",
      "items": {"enum": ["diff_of_changed_file", "output_of_verify_command", "list_of_new_files", "summary_of_changes"]}
    }
  }
}
```

The rendered worker prompt is ~10 lines of contract. Marvin cannot
go off-piste because the contract doesn't tell him there's a piste
to go off.

## The four locks

Four constraints prevent drift even if Marvin *wanted* to drift:

| Lock | Field | What it prevents |
|---|---|---|
| 1. **Schema lock** | `additionalProperties: false` | Extra fields can't be smuggled in. No "rationale" or "context" paragraph that re-opens the design space. |
| 2. **Size lock** | `output.max_loc_delta` (default 30, hard cap 100) | Cards above 100 LoC are rejected at creation. Forces decomposition. |
| 3. **Scope lock** | `out_of_scope` (min 3 entries) | The safety belt. Standard rules pre-filled: "Don't modify any file outside output.file", "Don't add new dependencies", "Don't refactor unrelated code", "Don't change public API", "Don't add tests beyond what verify requires." |
| 4. **Verification lock** | `verify.command` (anti-tautology) | A card with `verify.command: "true"` is rejected. The command must exit 0 *only* when the change is correct. |

## The parallelism model

Three fields control how the dispatcher runs cards in parallel:

- `depends_on` — list of card_ids that must be done first. The
  dispatcher holds the card in `blocked` until parents are `done`.
  Existing kanban mechanism (`--parent` on card creation).
- `conflicts_with` — list of card_ids that share state. The
  dispatcher never runs two cards in `conflicts_with` simultaneously,
  even if both are `ready`. Auto-populated by `detect_conflicts()`
  scanning output.file overlaps.
- `parallel_group` — opt-in for cards the spec author has confirmed
  are safe to run in parallel. The dispatcher runs them in the same
  tick without conflict-check.

Operator-facing knobs in `pantheon/config/kanban.yaml`:

```yaml
kanban:
  dispatcher:
    max_parallel_per_assignee: 4    # max cards running at once per god
    max_parallel_total: 12          # max cards running system-wide
    default_max_loc_delta: 30
    max_loc_delta_hard_cap: 100
    conflict_check: mechanical
```

## Why this works with a small model

The "small model follows small, structured spec consistently"
principle, verified in the 2026-06-21 session: a small model that
gets "add a RateLimiter class to twitter_bot.py with check/increment/
remaining methods, verify with `python -c '...'`" will do exactly
that, every time. The same small model that gets "build a
multi-channel lead orchestration engine with 13 stages" will do
something confident and wrong.

**The constraints do the work, not the model.** YouTube "vague
prompt works" videos are misleading: the prompt only works because
the implicit problem domain is highly constrained (snake game,
CRUD app, landing page) and the model has seen it 10,000 times in
training. The moment the implicit spec is different from training
data, small models fail. Mechanical contracts eliminate the
implicit-spec failure mode.

## When to use this pattern

- **Always** when fanning out a build plan into N kanban cards
  across multiple god-workers
- **Always** when the workers may use a smaller/cheaper model
  (smaller models are *more* sensitive to prompt ambiguity, not less)
- **Often** when the spec author and the executor are different
  agents (different contexts, different priors, different
  judgment-call thresholds)

## When NOT to use

- Single-task work (1 card, 1 worker) — the contract is overhead
- The author and executor are the same agent in the same session —
  the contract is internal context, doesn't need to be JSON
- The work is research/planning, not build — the contract is
  output-shaped; research contracts are different (see
  `references/research-deliverable-contract.md` if it exists, else
  patch the pattern for research)

## The contract enforcement point

The contract only matters if the writer enforces it. The patch is
on `hermes_cli/kanban_decompose.py` — every child card the
decomposer writes must validate against the schema. Cards that
fail validation abort the decompose with a clear error. This is
the same pattern as: "the spec is the spec, the writer enforces the
spec, the executor never sees anything that didn't pass validation."

**Anti-pattern:** LLM-decomposes with no validator. The LLM can
write anything. The card shape drifts over time. Within a few
weeks, the executor sees cards that look nothing like the original
contract.

## The "rewrite on operator answer" trigger

When the operator answers 3+ questions at the t3 pause (build-plan
review), the build plan needs to be rewritten as v1.X, not
patched. The same is true at the card level: when the operator
modifies 3+ fields of a card, rewrite the card body as
`card_id-v2.json` with all the changes applied, don't patch.
Patching cards has the same fragility as patching build plans
(operator-shaped signal 2026-06-16, Conductor UI build).

The audit trail: keep `card_id.json` (v1) + `card_id-v2.json` (v2)
in the build dir. The kanban DB has the v1 metadata; the v2 lives
in the file system. The reviewer reads v2 to see the operator's
applied edits.

## Companion reference

See `references/mid-dispatch-scope-shifts.md` for the operator-shaped
re-authoring signal at the build-plan level. The card-level
re-authoring is the same pattern, applied one level down.

## Worked example: the side-hustle lead engine (2026-06-21)

17 cards in 4 stages. The 232-line freeform spec was rewritten to
~70 checklist items. Each card was ~3 lines:

```yaml
- card_id: hep-2026-06-21-005
  type: build
  assignee: marvin
  depends_on: [hep-2026-06-21-003]
  parallel_group: stage-2-enrich
  input:
    files: [/home/konan/athenaeum/Codex-Work/side-hustle-crm/lead.py]
    context_lines: [the Lead dataclass]
  output:
    file: /home/konan/athenaeum/Codex-Work/side-hustle-crm/lead_store.py
    change: Add class LeadStore with methods add, get, mark_contacted
    max_loc_delta: 30
  verify:
    command: "python3 -c \"from lead_store import LeadStore; s = LeadStore('/tmp/x.json'); s.add({'id': '1'})\""
  out_of_scope: [STANDARD_OUT_OF_SCOPE[:5]]
```

The rendered worker prompt was 10 lines. Marvin's context window
saw: card_id, type, assignee, depends_on, input, output, verify,
out_of_scope. Nothing else. No project rationale, no architecture
overview, no "this is part of a larger feature" — the contract is
the contract.

## Cross-skill references

- **build-plan-orchestrator** — the umbrella skill. This pattern
  extends Path C (auto-fire) and Path B (operator pause) by adding
  a card-level contract on top of the existing chain.
- **thoth-codesign-brainstorm** — for the early-stage exploration
  that *precedes* this skill. When the operator is still in
  "what if we built X" mode, use brainstorm. When the build is
  concrete, use build-plan-orchestrator + this contract.
- **thoth-deliverable-skill-packaging** — the "Path 3: patch in
  place" pattern. When the operator wants to update an existing
  card contract, patch the existing `references/kanban-card-
  contract-pattern.md`, don't build a new one.
