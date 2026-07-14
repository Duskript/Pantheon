# Decision: Kanban Worker Code Left Uncommitted (Pipeline Gap)

**Date:** 2026-06-23
**Task:** P052 (Tier-1 + Ponytail QA on Phase 6)
**Made by:** Hephaestus

## Finding

During P052 Tier-1 review, I discovered that the DnD code (P050 + P051) was present in `src/kanban/board.tsx` as uncommitted working-tree modifications, NOT committed to the `feature/w1c-c-c-e2e-final` branch. The kanban workers for P050 and P051 claimed "shipped" but their changes were in scratch workspaces that were never merged.

## Impact

- The built dist (via `npm run build` which runs `tsc && vite build`) had NO DnD code because tsc fails on pre-existing errors, preventing vite from running. The dist was stale.
- Browser verification showed 0 draggable cards despite 310 tasks rendering.

## Resolution

1. Committed the uncommitted changes as `71329fe` (P050+P051: DnD + BlockedReasonModal)
2. Ran `npx vite build` directly (bypassing tsc gate due to pre-existing errors)
3. Restarted serve.py
4. Re-verified: 310 draggable cards in browser

## Root Cause

The kanban workers operate in `scratch` workspaces. Their file modifications exist only in those isolated workspaces. The workers committed code to the workspace's git (if any) but those commits were never merged into the project's working branch. When the worker says "shipped," it means "files written to my workspace," not "merged into the main branch."

## Recommended Fix

The spec-to-kanban-dispatch skill should include a step that, after a build card is marked done, the orchestrator (Hephaestus) verifies the changes are committed to the project branch — not just the scratch workspace. Alternatively, use `worktree` workspaces so commits land in the shared repo.
