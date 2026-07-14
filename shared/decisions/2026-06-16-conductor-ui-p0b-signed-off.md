# 2026-06-16 — Conductor UI Workforge Interview Design (P0b) — Signed Off

## Date
2026-06-16

## Decision

The Conductor UI Workforge interview design (P0b deliverable of the conductor-ui build plan v1.1) is signed off. All 6 open questions in §13 resolved with Konan's recommendations accepted.

## What was decided

1. **7 question groups** for the `new_node` context (Node Identity, Inputs, Outputs, Behavior, Configuration, Error Handling, Review)
2. **Per-type interview templates** — each of the 6 node types (chat, forge, god, webhook, rule, custom) gets its own Configuration subquestions
3. **Free-text behavior + structured subquestions** — the customer writes a free-text "what does this node do" first, then the system asks 2-4 type-specific structured subquestions
4. **6-item hidden backend** (canvas position, workflow binding, persistence path, audit entry, provenance, cross-references) — replaces the soulforge-interview-shape standard's 7-item list with a node-specific list
5. **Skip-interview path = blank node with type-default config + "Get help" safety net** — the "Get help" button opens a chat with the relevant domain specialist (god, internally — never named to the customer)
6. **`new_workflow` = hybrid template picker + Workforge interview + chat fallback** — ships in v2, not v1
7. **Customer-facing language throughout** — "workforge" replaces "Conductor" in UI labels, god names sterilized (role-based labeling), "you" replaces "operator," the plain-language Review summarizes in the customer's voice
8. **"Get help" is the primary chat fallback label** — final customer-facing button text
9. **Role-based labeling principle is product-wide** — god names sterilized in all customer-facing surfaces, role names used instead; Workforge is the first surface to apply it
10. **Plain-language summary tone = "professional, confident, warm, no hype"** — matches the TheoForge product page copy final
11. **Chat fallback authority = advises only** — the customer stays in control; the chat can suggest but not apply changes directly

## Rationale

- **The 7-group structure** matches the soulforge-interview-shape standard's template for `new_node` contexts, with the operator's customer-facing voice in the Review group (plain language first, structured below).
- **Per-type templates** are richer than a single type-aware interview (the alternative), but the maintenance tax is bounded — 6 templates, each 2-6 Configuration subquestions, ~30-50 total subquestions across all types.
- **Free-text + structured subquestions** preserves the customer's voice while making the implementation explicit. Matches the Olympus contract's "conversational first, structured underneath" principle.
- **6-item hidden backend** is node-specific (the soulforge-interview-shape standard's 7-item list is god-oriented; some items don't map to nodes).
- **"Get help" + Hephaestus-as-the-role (not named to the customer)** is the first application of the role-based labeling principle. The principle is product-wide because god names don't fit customer-facing surfaces; Workforge is the first surface to demonstrate the pattern.
- **`new_workflow` in v2** is a scope decision, not a quality decision. The interview design specifies both contexts, but the build plan is for `new_node` first. `new_workflow` benefits from learning from `new_node`.
- **Advises-only chat authority** matches the operator-rules-cheatsheet's sovereignty rule (external events don't auto-execute without explicit approval) and the soulforge-interview-shape standard's "interview first, raw document never" principle. The customer is always the author.

## Alternatives considered

- **(a) Single type-aware interview** instead of per-type templates. Rejected: simpler to maintain but less rich per-type.
- **(b) Pure structured form** instead of free-text + structured subquestions. Rejected: too constrained, doesn't match the "conversational first" principle.
- **(c) Standard 7-item hidden backend** (from the soulforge-interview-shape standard). Rejected: some items (Profile, Personality, Notification) don't map cleanly to nodes; a node-specific 6-item list is more accurate.
- **(d) Direct YAML/JSON editor** as the skip path. Rejected: power users are served by the structured form; raw YAML/JSON is too low-level for the customer-facing product.
- **(e) Chat applies suggestions directly (with customer confirmation)** instead of advises-only. Rejected for v1: too much authority for a first ship. Can be revisited in Phase 4 if advises-only proves cumbersome.

## Evidence

- The Olympus Native Soulforge interview contract (`athenaeum/Codex-Olympus/OLYMPUS_NATIVE_SOUL_FORGE_INTERVIEW_CONTRACT.md`) — the reference architecture for the question group pattern
- The soulforge-interview-shape standard (`athenaeum/Codex-Pantheon/design/standards/soulforge-interview-shape.md`) — the 5-component shape every Soulforge interview follows
- The Conductor UI build plan v1.1 (`pantheon/plans/conductor-ui-build-plan.md`) §9 — the Soulforge integration design
- The Conductor UI build plan v1.1 §7 (Q3, Q4) — the operator's clarifications on the interview's substance
- The operator-rules-cheatsheet (`athenaeum/Codex-Pantheon/design/operator-rules-cheatsheet.md`) — the sovereignty rule that drives the advises-only chat authority
- The TheoForge product page copy final (`pantheon/shared/active/ledger-product-page-copy-final.md`) — the voice + audience reference for customer-facing language

## Reversibility

**Low.** The P0b doc is a design document, not code. Changes to question groups, Configuration subquestions, or the skip-path behavior are doc-only changes — Phase 4 hasn't started yet. The role-based labeling principle is harder to reverse once customer-facing surfaces are shipped with god names; locking it now is the right call.

## Artifacts

- The signed-off P0b doc: `/home/konan/projects/conductor-ui/docs/conductor-soulforge-interview-design.md` (32K)
- The build plan v1.1: `/home/konan/pantheon/plans/conductor-ui-build-plan.md` (49.4K, 583 lines)
- This decision log entry: `/home/konan/pantheon/shared/decisions/2026-06-16-conductor-ui-p0b-signed-off.md`

## Status

**DONE — Konan signed off on 2026-06-16. Ready for conductor-ui chain dispatch.**

The chain (t1 done, t2 done, t3 blocked, t4 blocked, t5 todo) can dispatch with the v1.1 plan + the P0b deliverable. Phase 0's gate is satisfied (P0b's design doc is in). Phases 1, 2, 3 proceed in parallel. Phase 4 ships against this doc.
