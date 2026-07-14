# 2026-06-21 — Conductor UI: Mobile Pattern Pack approved direction

## Context

Konan asked whether the Conductor UI's mobile surfaces (workflow editor and
kanban board) could be modeled after Make.com's mobile editor and Trello's
mobile kanban, respectively. Iris initially flagged trade-dress concerns
around "lifting" layouts; Konan correctly pushed back: layout patterns and
interaction grammars are functional and not protectable, only distinctive
visual identity (icons, illustrations, exact brand colors, logos) is. The
15%-different rule for trade-dress confusion is trivially cleared by
applying the patterns through Lumen.

## Decision

Author a **Conductor UI Mobile Pattern Pack** — a visual-layer deliverable
from Iris that establishes the contract Marvin needs to wire mobile surfaces
into the existing Conductor UI without Iris being in the loop.

**The pack contains 4 files:**

1. `~/workspace/conductor-mobile/tokens/mobile-tokens.css` — compressed Lumen
   scale (8 steps → 5 effective) for touch; designed to mount inside a
   `@media (max-width: 639px)` block in `src/theme/index.css` with zero
   component changes
2. `~/workspace/conductor-mobile/mobile-workflow-editor.html` — single-file
   prototype of the Make.com-inspired mobile editor (vertical canvas, pinch
   zoom without rotation, bottom-sheet inspector)
3. `~/workspace/conductor-mobile/mobile-kanban.html` — single-file prototype
   of the Trello-inspired mobile kanban (column peek, swipe navigation,
   long-press drag, swipe-right quick menu)
4. `~/workspace/conductor-mobile/README.md` — pattern pack overview, design
   rationale, gesture dictionary, touchpoints with Marvin, a11y notes

**Key locked design decisions:**

- Breakpoint `sm` ends at 640px (Tailwind v4 default; below this the Lumen
  side rail can't fit)
- Touch target floor 48×48px; primary CTAs 56×56px
- Lumen compression 8 steps → 5 effective for mobile, reversible via media
  query (existing components don't need to know which mode is active)
- Pinch-but-no-rotation gesture (sidesteps the n8n accidental-rotation bug)
- Build pattern: single-file HTML prototypes (same as the existing
  Conductor mock), no build step, opens in a real mobile browser

**Out of scope (explicit):** Dashboard / Forge / Settings / Runs mobile
variants; native iOS/Android shells; push notifications; offline write-queue;
tablet-specific layouts; mobile light mode; mobile Workforge interview.

## The contract with Marvin

Four touchpoints, in build order:

1. Mount `mobile-tokens.css` inside a `@media (max-width: 639px)` block
2. Extract a `useIsMobile()` hook from the prototypes' `matchMedia` pattern
3. Add a `MobileAppShell` branch in `AppShell.tsx` (bottom tab bar, no side
   rail) for viewports < 640px
4. Add a `MobileBoard` variant in `src/kanban/` that reuses the same data
   hooks and the same `<TaskCard>` component, but renders the column peek
   layout

No new event names. No new dependencies. Same `onAdvance`/`onAssign`/`onMove`
callbacks as desktop, different gesture sources.

## Why this is the right shape

- **Visual layer is mine, build layer is his.** Boundary is clean: Iris
  designs, Marvin wires. No overlap, no hand-holding.
- **The single-file HTML pattern matches the existing Conductor mock** —
  Konan can review in a real browser, no Figma, no build env.
- **Token names are unchanged** — `mobile-tokens.css` redefines existing
  CSS custom properties inside a media block. Zero component refactor.
- **The compression is reversible** — if we decide mobile needs 8 steps
  later, we change one file.

## Evidence

- The plan: `~/pantheon/plans/conductor-mobile-pattern-pack.md` (24K,
  9 sections, full acceptance criteria, file checklist, decision log)
- Existing mock: `~/workspace/conductor-mock/index.html` (2,013 lines, the
  design north star for the desktop editor)
- Existing AppShell: `~/projects/conductor-ui/src/shell/AppShell.tsx`
  (333 lines, 5-route shell, no mobile variant)
- Existing kanban surface: `~/projects/conductor-ui/src/kanban/board.tsx`
  (374 lines, 7-column board, fixed click-to-advance, no mobile variant)
- Lumen token source of truth: `~/projects/conductor-ui/src/editor/theme/
  tokens.generated.ts` (auto-generated from `src/theme/index.css`)

## Reversibility

**High.** The plan is a *pattern pack* — a set of design artifacts — not
a code change. If the prototypes don't land, Marvin hasn't touched
anything yet. The compression is also reversible: at the cost of one
CSS file, we go back to 8 steps on mobile.

## Status

**DONE — direction approved, plan written.** Awaiting Konan's
prototype review in a real mobile browser, then Marvin's build.
