# Active Goal: Pantheon Rebrand of Hermes UI

Set: 2026-05-18
Branch: feat/hermes-ui-retheme

## The Goal

Complete Pantheon rebrand of hermes-ui on feat/hermes-ui-retheme — this becomes the new Pantheon frontend. Full feature integration of all 23 Pantheon API modules, 31 exclusive routes, and 10+ missing panels into the React shell.

## Standing Instructions

**PRELOAD every session:** react-best-practices skill. Apply §5 (re-render), §1 (waterfalls), §6 (rendering) rules to all React work. Audit with hook counts before/after each phase.

**DELEGATE panel builds:** Claude Code (claude -p --allowedTools) for targeted React component work and refactors. Codex CLI (codex exec --full-auto) for batch/parallel panel construction. Hermes orchestrates, verifies every delegation with git diff + test run.

## Phases

### Phase 1 — Foundation
- Commit existing Phase 2 backend changes
- Fix API path mismatches (sessions→/api/sessions, skills CRUD, files)
- Wire artifact panel → /api/boons with promote-from-message
- Apply react-best-practices audit fixes (inline components, useEffect cleanup, content-visibility)

### Phase 2 — Pantheon Shell
- Add God Rail (left sidebar god circles)
- Rebrand all naming: Spaces→Forge Projects, Artifact→Boon, Hermes→Pantheon
- Re-theme with DESIGN.md color tokens + Pantheon wordmarks
- Add God Profile Chip to composer

### Phase 3 — Core Panels
- God Management (list/status/start/stop)
- Athenaeum (codex tree + semantic search)
- Forge wizard (god creation via Hephaestus)
- Summon drawer (GitHub browser + install)

### Phase 4 — Polish
- Onboarding wizard
- Sub-agent profiles
- Notification bell
- Boons drawer enhancements (edit in-place, pin, export)
- PWA share target

## Hard Rules

- Dev on :8788 only, never touch production :8787 without explicit "ship it"
- All 4,810 backend tests stay green
- Babel-standalone React 18 only — no Next.js/RSC/SSR
- Commit per phase, clean history
- Verify every delegation independently — never trust agent self-reports
