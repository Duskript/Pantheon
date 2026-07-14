# Decision — Tier-1 Expanded: Spec-Conformance + Acceptance Gates

- **Date:** 2026-06-21
- **Operator:** Konan
- **God:** Hephaestus
- **Decision:** Tier-1 review now includes two mandatory gates before Ponytail QA:
  1. **Spec-Conformance Gate** — Grep codebase for every function name, type, file path, and UI element from the signed-off spec. Click every route, nav item, and button. Document drift. "Could not load the board" = FAIL.
  2. **Acceptance Gate** — Verify the system demonstrably works end-to-end. Running services, reachable endpoints, built images. "Done" = operator can use it, not files exist.
- **Rationale:** Conductor UI shipped with 6 dead nav items, broken Board, wrong Forge content, and half-built dead pages — despite passing Ponytail QA. Ledger shipped with zero Docker images built and no running Vaultwarden/DocuSeal — despite all code files matching the spec. Neither gate in the existing pipeline catches spec drift or integration gaps. These failures are Hephaestus's responsibility — the conductor who signs off before Ponytail.
- **Evidence:** Conductor UI audit (2026-06-21): 6 dead nav items, Board "Could not load the board", Forge = Soulforge not Workforge. Ledger audit (2026-06-21): zero Docker images, zero running containers, .env.example only.
- **Canonical doc updated:** `~/.hermes/profiles/hephaestus/SOUL.md` — Tier-1 Review Checklist items 8 + 9, Handoff Protocol.
- **Supersedes:** Nothing. This is additive — the existing 7 Tier-1 items remain.
