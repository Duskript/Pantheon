# Worked example: Conductor Mobile Pattern Pack dispatch (2026-06-21)

The first end-to-end run of the spec-to-kanban-dispatch recipe. Captures the
exact card shapes, the contract failures, the fixes, and the live state of the
kanban at session end. Use as the reference when the recipe encounters a new
edge case — the bug is probably here.

## Source spec

- `~/pantheon/plans/conductor-mobile-pattern-pack.md` (24K, 9 sections)
- `~/pantheon/shared/decisions/2026-06-21-conductor-mobile-pattern-pack.md` (decision log)

4 deliverable files, 4-phase build order, 23 ACs, 4 contract seams with Marvin,
1 risk gate (V6 WCAG AA must pass before Phase C).

## The 9-card decomposition (final, post-validation)

| # | card_id | task_id (returned) | title | type | assignee | parent |
|---|---|---|---|---|---|---|
| 001 | hep-2026-06-21-001 | t_23ec1e5b | mobile-tokens.css | prototype | iris | — |
| 002 | hep-2026-06-21-002 | t_f969396e | mobile-workflow-editor.html | prototype | iris | 001 |
| 003 | hep-2026-06-21-003 | t_3bef3fb8 | mobile-kanban.html | prototype | iris | 001 |
| 004 | hep-2026-06-21-004 | t_e3c2d346 | README.md | prototype | iris | 002+003 |
| 005 | hep-2026-06-21-005 | t_8c864ee1 | QA-REPORT.md (V1-V10) | qa_gate | iris | 004 |
| 006 | hep-2026-06-21-006 | t_eb2c7477 | useIsMobile() hook | integration | marvin | 005 |
| 007 | hep-2026-06-21-007 | t_ca6a8a1e | MobileAppShell | integration | marvin | 006 |
| 008 | hep-2026-06-21-008 | t_54033fed | MobileBoard | integration | marvin | 006 |
| 009 | hep-2026-06-21-009 | t_11402316 | Final QA (M1-M8 + J1-J5) | final_qa | hephaestus | 007+008 |

## Card shapes (the 15-field contract, sample)

The `useIsMobile` card (006) is a clean example of a modify-style card:

```json
{
  "card_id": "hep-2026-06-21-006",
  "type": "integration",
  "assignee": "marvin",
  "title": "Extract useIsMobile() hook from prototype matchMedia pattern",
  "change": "Create src/hooks/useIsMobile.ts exporting a React hook that subscribes to matchMedia('(max-width: 639px)').",
  "depends_on": ["hep-2026-06-21-005"],
  "conflicts_with": [],
  "parallel_group": "phase-C",
  "input": {
    "files": [
      "~/athenaeum/Codex-God-Iris/mobile-pattern-pack/mobile-workflow-editor.html",
      "~/athenaeum/Codex-God-Iris/mobile-pattern-pack/mobile-kanban.html"
    ],
    "context": "QA gate t_8c864ee1 PASSED."
  },
  "output": {
    "file": "src/hooks/useIsMobile.ts",
    "change": "new file, ~30 LoC",
    "max_loc_delta": 30
  },
  "verify": {
    "command": "npx tsc --noEmit src/hooks/useIsMobile.ts && npx vitest run src/hooks/useIsMobile.test.ts",
    "timeout_seconds": 30
  },
  "out_of_scope": [
    "Mounting mobile-tokens.css (separate card 007 / mobile-app-shell task)",
    "Refactoring existing desktop components",
    "Adding new dependencies"
  ],
  "notify_on_complete": true
}
```

## Contract failures hit and fixes applied

In dispatch order, the validation step rejected cards four times. Each
rejection is captured here with the fix:

### Failure 1: max_loc_delta too high (4 cards)

Cards 001-004 (the prototype files) each had max_loc_delta values of
200-1500 LoC. The contract's hard cap was 100. **All 4 rejected.**

**Fix:** decomposed the prototype phase into 1 file per card. 4 files = 4
cards. Each file is 30-90 LoC. All under the 100 cap. The decomposition is
genuinely better than the original "ship the whole pattern pack" card.

### Failure 2: card_id pattern (suffix with letter)

After fixing the LoC cap, my renumber script produced IDs like
`hep-2026-06-21-001a` (using `a` to mark phase 1). The regex
`^hep-\d{4}-\d{2}-\d{2}-\d{3}$` rejects letters.

**Fix:** renumbered to plain `001...009`. Phase info went into
`parallel_group` and the `change` text, not the ID.

### Failure 3: change field > 200 chars (5 cards)

Cards 002 and 004 had `change` descriptions of 240-300 chars. The contract
caps at 200.

**Fix:** rewrote to fit. The trimmed versions were tighter and more useful
for the worker. A 200-char `change` is a feature, not a bug.

### Failure 4: idempotency-key collision (4 cards)

The first 4 dispatches returned successfully but the kanban DB showed those
4 cards as `done` with `marvin` assignee. They were aliased to the previous
build's `MemoryPromoter` cards, which used the same `hep-2026-06-21-001..004`
keys.

**Fix:** re-dispatched all 9 cards with the prefix
`mobile-pack-2026-06-21-`. The 9 cards now have unique keys.

## Dispatch sequence (the actual bash)

```bash
# 1. Root card
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-001" \
  --json card_001.json
# -> task_id: t_23ec1e5b

# 2. Children of 001
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-002" \
  --parent t_23ec1e5b --json card_002.json
# -> task_id: t_f969396e

hermes kanban create --idempotency-key "mobile-pack-2026-06-21-003" \
  --parent t_23ec1e5b --json card_003.json
# -> task_id: t_3bef3fb8

# 3. Grandchild (depends on 002 AND 003)
#    First call: --parent t_f969396e — only one parent is supported,
#    so we set 004 as child of 002 and the README write is gated on
#    002's completion. 003's file is referenced in input but not
#    structurally a parent. (The dispatcher tracks "must reference
#    file X" through input.files, not as a hard dependency.)
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-004" \
  --parent t_f969396e --json card_004.json
# -> task_id: t_e3c2d346

# 4. QA gate (child of 004)
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-005" \
  --parent t_e3c2d346 --json card_005.json
# -> task_id: t_8c864ee1

# 5. Marvin's hook (child of QA gate)
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-006" \
  --parent t_8c864ee1 --json card_006.json
# -> task_id: t_eb2c7477

# 6. Marvin's MobileAppShell (child of 006)
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-007" \
  --parent t_eb2c7477 --json card_007.json
# -> task_id: t_ca6a8a1e

# 7. Marvin's MobileBoard (sibling of 007, same parent 006)
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-008" \
  --parent t_eb2c7477 --json card_008.json
# -> task_id: t_54033fed

# 8. Final QA (child of 007, references 008 in input.files)
hermes kanban create --idempotency-key "mobile-pack-2026-06-21-009" \
  --parent t_ca6a8a1e --json card_009.json
# -> task_id: t_11402316
```

**Caveat:** the kanban only supports one `--parent` per card. If a card
needs to wait on two parents (like 004 needs 002 AND 003 done), set one
as `--parent` and reference the other in `input.files` with a note that
the worker should verify both are present. The strict-blocking-on-both
case requires a follow-up card chain instead.

## Live state at session end (2026-06-21 20:42 UTC)

```sql
SELECT id, status, assignee FROM tasks
WHERE idempotency_key LIKE 'mobile-pack-2026-06-21-%'
ORDER BY id;
```

| task_id | status | assignee |
|---|---|---|
| t_23ec1e5b | done | iris |
| t_f969396e | done | iris |
| t_3bef3fb8 | done | iris |
| t_e3c2d346 | done | iris |
| t_8c864ee1 | done (FAIL verdict) | iris |
| t_eb2c7477 | **blocked** | marvin |
| t_ca6a8a1e | todo | marvin |
| t_54033fed | todo | marvin |
| t_11402316 | todo | hephaestus |

The QA gate returned `result = "QA report delivered; verdict is FAIL on V2 + V6; do not start Phase C"`. The dispatcher's blocked-summary on t_eb2c7477 reads: *"V6 (WCAG AA) still FAILS per parent t_8c864ee1 QA report — body says do not start; Iris must apply plan §R1 fix (revert 5→8 step Lumen compression) + structural kanban fixes, then re-run V1–V10 gate before Phase C."*

## The QA findings (the gate that fired)

6 PASS / 4 FAIL on the V1-V10 visual criteria:

- **V2 FAIL** — kanban column-switcher dots 8×8 (need 24×24), 2 icon-buttons 46×48 (need 48×48). 9 violations.
- **V3 FAIL** — kanban inlines a 22-variable `:root` block instead of cascading from `mobile-tokens.css`. Token duplication risk.
- **V6 FAIL (GATING)** — 5-step Lumen compression hits 1.3:1 and 1.45:1 contrast ratios. WCAG AA needs 4.5:1. 4 axe violations (color-contrast, aria-hidden-focus, nested-interactive, target-size).
- **V8 FAIL** — editor's `.sheet-handle` missing from focus-visible rule.

Iris's recommended fix path: revert Lumen to 8 steps, fix kanban structural
issues, fix editor a11y gaps, write README, re-run V1-V10 gate. Estimated
15-30 min. **Do not redesign components** — the 5-step compression was a v1
bet that lost; reverting is the cheap move.

## What this example proves

1. **The contract works.** Every rejection was correct — wrong LoC, wrong
   pattern, too-long description, key collision. The system is catching
   real scope problems at creation time, not at review time.
2. **The dependency graph works.** Phase A finished in ~28 min wall-clock
   (001→002+003 parallel → 004 → 005). Phase C correctly blocked on the
   V6 gate. No cards ran out of order.
3. **The QA gate works.** V6 was the real risk. The plan §R1 mitigation
   ("V6 check before Marvin touches anything") fired exactly as designed.
   The fix path is clear and bounded.
4. **The id verification step matters.** I had to add it because of the
   collision. Without it, the dispatcher would have silently unblocked
   Phase C and Marvin would have started building on the broken
   prototypes. The fix is permanent (per-build prefix).

## Open question (for the contract follow-up card)

The 100 LoC cap is right for modify-style cards and wrong for
create-style cards. The right contract change: add `card_scope` field
with `modify | create | replace` values, each with its own cap.
Modify = 30, create = 500, replace = 100. Until that's in the
contract, the recipe manually decomposes by file.
