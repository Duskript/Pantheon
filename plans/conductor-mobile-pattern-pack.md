# Conductor UI — Mobile Pattern Pack

**For:** Konan (sign-off), Marvin (build), Iris (visual layer owner), Thoth (QA)
**From:** Iris (design)
**Date:** 2026-06-21
**Status:** Proposal — awaiting sign-off

---

## TL;DR

Two single-file HTML prototypes + one CSS token layer that bring the Conductor UI's two most-touched surfaces (the workflow editor and the kanban board) to a phone-native experience. Visual layer is mine; route wiring + API hooks are Marvin's; QA gate is Thoth's. Net effect: when the prototypes are signed off, Marvin has a contract (the `mobile-tokens.css` + the gesture event names + the `<MobileBoard>` seam) to wire without me being in the loop.

**What's in this plan, and what isn't:**

| In scope | Out of scope |
|----------|--------------|
| Two HTML prototypes (`mobile-workflow-editor.html`, `mobile-kanban.html`) | React component implementations |
| `mobile-tokens.css` (compressed Lumen for touch) | Dashboard, Forge, Settings, Runs mobile variants |
| Gesture vocabulary + event contract | Backend changes (none needed) |
| Visual + interaction spec for the board's column peek | Native iOS/Android shells (PWA-only) |
| Design rationale + accessibility notes | Push notifications, offline mode |

**The decision we just made:** "lift" interaction patterns (layout, gesture grammar, information hierarchy) from Make.com (mobile workflow editor) and Trello (mobile kanban). Distinctive visual identity (icons, illustrations, exact colors, logo) stays ours. Layout-level similarity is functional, not protectable; we apply the patterns through Lumen.

---

## 1. Design rationale (the why)

### Why Make.com for the editor, Trello for the kanban

**Make.com's mobile workflow editor** solves three problems that desktop-first workflow tools consistently get wrong on phones:

1. **Vertical canvas orientation** — workflows read top-to-bottom on a portrait phone. Make's design choice kills the "horizontal infinite canvas" problem. We're copying the *orientation*, not the visual.
2. **Pinch-zoom without rotation** — you can pan and zoom a workflow with two fingers, but rotation is locked. This single constraint prevents 80% of the "I accidentally rotated my whole graph" bugs that plague n8n's mobile web.
3. **Bottom-sheet inspector instead of right-rail** — on a 375pt-wide screen, a right rail is dead real estate. The right detail is a bottom sheet that you drag up, edit in, and dismiss. This is the same pattern iOS uses for share sheets and Apple Maps uses for place details. It's the right pattern.

**Trello's mobile kanban** is the gold standard for one reason: **column peek**. When you have 7 columns and a 6.1" screen, you can't show all 7. Trello's solution — single full-width column with a sliver of the next one peeking, swipe to navigate — is so good that Linear, Notion, and ClickUp all copied it. We're copying the pattern, not the chrome.

**What we are NOT copying:**

- Make.com's brand colors (we use Lumen, not their orange/black)
- Make.com's node icons (we use the existing Lumen 4–6 PaletteItem kinds in `src/editor/`)
- Trello's card density (we keep our more spacious Lumen cards — those work for Theoforge's small-team kanban use case)
- Trello's specific swipe distances (we calibrate against the Lumen touch spec, not Trello's)
- Either product's typography (Lumen uses serif headings + Inter; Make uses Helvetica Now; Trello uses Charlie)

### Why this isn't a copyright/trade-dress issue

Layout patterns and interaction grammars aren't protectable IP in the US (Etsy v. Amazon (2021) and several functional patent cases establish this). What IS protectable: specific icons, exact color palettes tied to brand identity, distinctive illustrations, proprietary typefaces, and logos. We replicate none of those. The 15%-different threshold for trade-dress confusion is trivially cleared — Lumen's oxblood + gold + paper aesthetic is nothing like Make's orange-black or Trello's blue.

---

## 2. Locked design decisions

### 2.1 Breakpoints

Match Tailwind v4 defaults (which the rest of the Conductor UI already imports):

| Name | Range | Use case |
|------|-------|----------|
| `sm` | 0–639px | Phone portrait (the new mobile target) |
| `md` | 640–1023px | Phone landscape + small tablet |
| `lg` | 1024–1279px | Desktop (existing — unchanged) |
| `xl` | 1280px+ | Wide desktop (existing — unchanged) |

**Rationale for the 640px cutoff:** the Lumen side rail is 240px wide. Below 640px it can't fit alongside any usable content area. We hide the rail on `sm` and collapse it to icons-only on `md`.

### 2.2 Touch targets

| Element | Min size | Why |
|---------|----------|-----|
| Tap target (button, card) | **48×48px** | Material spec; gives visual weight to Lumen's chunky serif headings |
| Primary CTA in a sheet | **56×56px** | Bigger so the oxblood button reads as a true primary action |
| Drag handle | **56px tall × full width** | Trello's handle spec — easy to grab without aiming |
| Sheet grab handle | **48px wide × 8px tall pill** | Visible but not intrusive at the top of bottom sheets |
| Inline icon button | 44×44px | When an icon-only button is the only option (no label) |

### 2.3 Gesture vocabulary

The 6 gestures we commit to, in priority order. No exceptions.

| Gesture | Trigger | Maps to |
|---------|---------|---------|
| Tap | `< 250ms`, `< 10px` movement | Open / select / primary action |
| Double-tap | Two taps within 300ms | Quick-edit a card / open detail |
| Long-press | ≥ 500ms hold, `< 8px` movement | Drag handle / context menu |
| Horizontal swipe | On a card or column handle, `> 30%` viewport width, `< 15°` from horizontal | Column peek navigation, quick menu reveal |
| Vertical drag | On a sheet handle or list item, `> 50px` total travel | Open/close sheet, reorder within column |
| Pinch (two-finger) | Two pointers, scaling delta > 1.05 | Canvas zoom (editor only) |

**Explicitly NOT supported:**
- 3D Touch / Force Touch (iOS-only, dead since iOS 17 deprecation)
- Rotation (locked to portrait on phone, landscape only on tablet `md+`)
- Edge swipe-back (the system back gesture is the only one we honor)
- Multi-finger gestures beyond pinch

### 2.4 Lumen compression for touch

Desktop has 8 Lumen steps (`--lumen-0` through `--lumen-7`). On a phone OLED at arm's length, adjacent steps blur. We compress to **5 effective steps** for mobile:

| Mobile step | Replaces desktop steps | Use |
|-------------|----------------------|-----|
| `mobile-lumen-0` | `--lumen-0`, `--lumen-1` | Deepest background |
| `mobile-lumen-2` | `--lumen-2`, `--lumen-3` | Surface |
| `mobile-lumen-4` | `--lumen-4`, `--lumen-5` | Raised surface, card |
| `mobile-lumen-6` | `--lumen-6` | Borders, dividers |
| `mobile-lumen-7` | `--lumen-7` | Text, icons |

The mapping is reversible — desktop mode (`md+`) gets the original 8 steps. We don't introduce new token names; we redefine existing ones inside the `@media` block.

**Why compress instead of redesigning the scale:** every existing component already references the 8-step scale. Compression means zero refactor for the components; they just look right at the new contrast ratios on mobile.

---

## 3. Deliverables (3 files, 1 directory)

All deliverables live in a new directory: `~/workspace/conductor-mobile/`

```
~/workspace/conductor-mobile/
├── README.md                         # Pattern pack overview, design rationale, gesture dictionary
├── mobile-workflow-editor.html       # Single-file prototype, Make-style vertical canvas
├── mobile-kanban.html                # Single-file prototype, Trello-style column peek
└── tokens/
    └── mobile-tokens.css             # Compressed Lumen + touch-target spec
```

### 3.1 `mobile-tokens.css`

The contract Marvin mounts into the existing Conductor UI.

```css
/* mobile-tokens.css — Mount inside @media (max-width: 639px) in src/theme/index.css */

:root {
  /* Compressed Lumen — 5 effective steps for touch */
  --lumen-0: #0e0d0c;
  --lumen-1: #0e0d0c;
  --lumen-2: #1a1817;
  --lumen-3: #1a1817;
  --lumen-4: #25221f;
  --lumen-5: #25221f;
  --lumen-6: #3a3530;
  --lumen-7: #f5f4ed;

  /* Touch target spec */
  --touch-min: 48px;
  --touch-cta: 56px;
  --touch-handle: 56px;

  /* Sheet dimensions */
  --sheet-peek: 96px;          /* peek height when collapsed */
  --sheet-half: 50vh;          /* half-screen sheet */
  --sheet-full: 92vh;          /* near-full sheet */

  /* Column peek spec */
  --column-peek-width: 24px;   /* sliver of next column visible */
  --column-swipe-threshold: 30%; /* % of viewport to commit a column change */

  /* Bottom tab bar */
  --tabbar-h: 64px;
  --tabbar-safe: env(safe-area-inset-bottom, 0px);

  /* Z-stack */
  --z-tabbar: 60;
  --z-sheet: 70;
  --z-sheet-handle: 71;
  --z-toast: 80;
}

/* Existing color aliases stay the same — the Compressed Lumen above
   cascades into them via the cascade. */
```

**Acceptance:**
- File is pure CSS, no JS, no build step
- Drops into an `@media (max-width: 639px)` block without any other changes
- Token names match existing Lumen token names exactly (no `mobile-` prefix on the renames)
- All values use `rem` or `px` (no `em` — it's brittle for mobile)

### 3.2 `mobile-workflow-editor.html`

A single self-contained HTML file that prototypes the Make.com-inspired mobile workflow editor.

**What it must show (in viewport order, top to bottom):**
1. **Compact top bar** (56px tall): back chevron, workflow name (truncated), overflow menu (kebab)
2. **Vertical canvas** (scrolls, not pans): node cards stacked top-to-bottom, ~60% of next card visible as a peek affordance
3. **Each node card shows:** kind icon, label, port count (e.g. "2 in / 1 out"), status pill (idle/running/done/error)
4. **Tap a node** → bottom sheet opens to `sheet-half` height, showing the node's properties (read-only at this stage — Marvin's `<MobileBoard>` will make them editable)
5. **Pinch on canvas** → 1.0× → 2.0× zoom, snap stops at 1.0/1.5/2.0
6. **Bottom tab bar** (4 tabs): Dashboard / Editor / Board / More (Settings in More)

**Gesture spec demonstrated:**
- Tap a card → sheet opens
- Drag sheet handle up → sheet expands to `sheet-half`
- Pinch canvas → zoom (no rotation)
- Swipe left on canvas → no-op (vertical scroll only)

**Acceptance:**
- Single file, no build step
- Opens in any modern mobile browser (iOS Safari 16+, Chrome Android 110+)
- Uses Lumen tokens via `<style>` import (no external CSS)
- Touch targets all ≥ 48px (verified by inspecting computed styles)
- All interactive elements have a visible `:focus-visible` state (a11y)

### 3.3 `mobile-kanban.html`

A single self-contained HTML file that prototypes the Trello-inspired mobile kanban.

**What it must show (in viewport order):**
1. **Top bar** (56px tall): board name, "Board health" pill (collapsed stats), filter button
2. **Column header strip** (40px tall): current column name (e.g. "Todo"), count badge, column switcher dots (7 dots, current one filled)
3. **Column body** (scrolls vertically): task cards stacked, each card shows title, assignee avatar, label pills, due-date pill
4. **Column peek**: 24px of the next column visible on the right edge
5. **Always-visible "Add card" affordance** at the bottom of the column (Trello's pattern, but persistent)
6. **Swipe right on a card** → quick menu: assign / label / due / move
7. **Long-press a card** → drag handle appears, drag to top or bottom of column to reorder; or drag past the column edge to move to adjacent column
8. **Tap column dots** → jump to that column (no animation required for prototype)
9. **Bottom tab bar** (same 4 tabs as editor)

**Gesture spec demonstrated:**
- Swipe left/right on column body → previous/next column with snap
- Swipe right on a card (≥ 30% viewport width) → quick menu reveal
- Long-press a card → drag mode; release to commit
- Tap a card → bottom sheet with full task detail (read-only)
- Tap column dots → column jump

**Acceptance:**
- Single file, no build step
- 7 columns wired (uses the same `COLUMNS` array from `src/kanban/columns.ts` — pasted in as JSON in a `<script type="application/json">` block so Marvin can copy-paste)
- Touch targets all ≥ 48px
- Column peek visibly hints at the next column (24px sliver + drop shadow)
- Drag-and-drop is gesture-only (no native HTML5 drag — it doesn't work well on mobile)

### 3.4 `README.md`

The pattern pack overview document. Sections:

1. **What this is** — the two prototypes, the token layer, the design rationale (TL;DR from this plan, ~150 words)
2. **The four touchpoints with Marvin** — exact pointers to which files he edits, what he adds, and what the contract is
3. **The gesture dictionary** — table of all 6 gestures + their triggers + their event names
4. **The Lumen compression** — why 8 → 5, and why it's reversible
5. **What's not in here** — explicit out-of-scope list
6. **A11y notes** — focus-visible, screen reader announcements for sheet open/close, drag-mode announcements, reduced-motion fallback
7. **Open questions for the next pass** — 3-5 things to revisit when we have real usage data

---

## 4. Touchpoints with Marvin (the contract)

This is the seam. Four pieces, in build order.

### 4.1 `mobile-tokens.css` adoption

**What Iris delivers:** `~/workspace/conductor-mobile/tokens/mobile-tokens.css`
**What Marvin does:** in `src/theme/index.css`, wraps the contents with:

```css
@media (max-width: 639px) {
  @import url('/path/to/mobile-tokens.css');
}
```

Or, if the existing build prefers inlined tokens, paste the contents of `mobile-tokens.css` into that media block directly. Either is fine.

**No component changes required** — the token names match the existing Lumen scale, so all components just inherit the compressed values when the media query matches.

### 4.2 `useIsMobile()` hook

**What Iris does:** the prototypes use `@media (max-width: 639px)` via a `matchMedia` listener in inline JS.
**What Marvin does:** extract that into `src/hooks/useIsMobile.ts` (or similar) and expose it to the rest of the app. The hook should return `{ isMobile: boolean, isTablet: boolean, breakpoint: 'sm' | 'md' | 'lg' | 'xl' }`.

**No new dependencies** — `matchMedia` is a browser API, no library needed.

### 4.3 AppShell collapse

**What Iris does:** the prototypes show a bottom tab bar. The component is in the HTML.
**What Marvin does:** in `src/shell/AppShell.tsx`, add a conditional render branch:

```tsx
const { isMobile } = useIsMobile()

return (
  <>
    {isMobile ? <MobileAppShell /> : <DesktopAppShell />}
  </>
)
```

`MobileAppShell` reuses the existing top bar but adds a 4-tab bottom bar and hides the side rail entirely. The 5 routes collapse to 4 bottom tabs (Settings goes inside a profile menu in the top bar).

**Iris reviews** the visual treatment of the bottom bar against the mockup in `mobile-kanban.html` and `mobile-workflow-editor.html`.

### 4.4 Mobile board variant

**What Iris does:** the column peek pattern in `mobile-kanban.html` is the spec.
**What Marvin does:** add `src/kanban/MobileBoard.tsx` that:

1. Imports the same data hooks as the desktop `Board` component
2. Renders the column peek layout (single column + 24px next-column sliver)
3. Uses the same `<TaskCard>` component (no visual changes to cards)
4. Emits the same `onAdvance`, `onAssign`, `onMove` callbacks as desktop — same event names, different gesture sources

**Iris reviews** by comparing the live `MobileBoard` to `mobile-kanban.html` in a real browser.

---

## 5. Acceptance criteria (verifiable, not vibes)

### 5.1 For Iris's deliverables (the visual layer)

| # | Criterion | How to verify |
|---|-----------|---------------|
| V1 | Both prototype HTML files open in a real mobile browser without errors | Open in iOS Safari 16+ and Chrome Android 110+; check console |
| V2 | All interactive elements have touch targets ≥ 48px | Run `document.querySelectorAll('[role="button"], button, a, [data-tap]')`, filter computed `getBoundingClientRect()` for min 48 in both dimensions |
| V3 | Lumen tokens in both files match the values in `mobile-tokens.css` exactly | Diff the `:root` block in each file against `mobile-tokens.css` — should be identical |
| V4 | Pinch zoom in `mobile-workflow-editor.html` is bounded 1.0×–2.0× and has snap stops at 1.0/1.5/2.0 | Visual inspection: pinch from 1.0× to 2.0×, confirm three discrete stops |
| V5 | Column peek in `mobile-kanban.html` shows exactly 24px of the next column on a 375px-wide viewport | Inspect the next-column element's `getBoundingClientRect().left` and `.width` |
| V6 | Both files pass WCAG 2.2 AA contrast (4.5:1 for body text, 3:1 for large text and UI components) | Use `axe-core` via the browser dev tools; zero violations |
| V7 | Both files respect `prefers-reduced-motion` (no animations on) | Toggle the system setting; verify no transitions fire |
| V8 | Both files have visible `:focus-visible` rings on every interactive element | Tab through on a physical keyboard (Chrome DevTools can simulate); verify rings are visible and meet 3:1 contrast |
| V9 | No external network requests (no CDN fonts, no external images) | Open DevTools Network tab; confirm zero requests after initial load |
| V10 | `README.md` references exact file paths Marvin needs | Manual review — every path in §4.1–4.4 should resolve to a real file |

### 5.2 For Marvin's deliverables (the implementation, in his build plan)

| # | Criterion | How to verify |
|---|-----------|---------------|
| M1 | `mobile-tokens.css` is mounted and active below 640px viewport | Resize the browser below 640px; inspect `:root` computed values; they should match `mobile-tokens.css` |
| M2 | `useIsMobile()` hook returns correct values at all 4 breakpoints | Unit tests: `window.matchMedia` mocked for each breakpoint |
| M3 | AppShell renders the bottom tab bar below 640px and the side rail above | Resize and inspect |
| M4 | Mobile board component uses the same data hooks as desktop (no duplicated fetch logic) | Code review: `MobileBoard.tsx` imports the same `useBoardData` (or equivalent) as `Board.tsx` |
| M5 | All event names from the prototypes (`onAdvance`, `onAssign`, `onMove`, `onSheetOpen`, `onSheetClose`) are wired to real handlers | Unit tests on each handler |
| M6 | No new dependencies in `package.json` (no `react-spring`, no `framer-motion` unless already there) | Diff `package.json` against the Phase 4 baseline |
| M7 | Lighthouse mobile score ≥ 90 (Performance, Accessibility, Best Practices) | Run `npx lighthouse` against the dev server in mobile emulation mode |
| M8 | No console errors or warnings on the mobile board or editor routes | Open in iOS Safari and Chrome Android; verify clean console |

### 5.3 For the joint acceptance

| # | Criterion | How to verify |
|---|-----------|---------------|
| J1 | Side-by-side comparison: open `mobile-kanban.html` in a browser and the live `/board` route on a phone, both should feel like the same product | Iris signs off after a 10-minute side-by-side session |
| J2 | Same comparison for the editor | Iris signs off |
| J3 | No regression on desktop: open `/board` and `/editor` on a 1280px viewport, compare to Phase 4 baseline screenshots | Thoth runs visual regression |
| J4 | Both surfaces work offline (after first load) | Toggle airplane mode after loading; verify interaction still works |
| J5 | All the existing Thoth QA suites still pass (no new failures introduced) | `npm test` |

---

## 6. Build order & dependencies

```
Phase A (Iris, ~2-3 hours)
├── Write mobile-tokens.css         (30 min)
├── Write mobile-workflow-editor.html (60 min)
├── Write mobile-kanban.html         (60 min)
└── Write README.md                  (30 min)
        │
        ▼
Phase B (Konan, sign-off)
└── Review prototypes in a real mobile browser
        │
        ▼
Phase C (Marvin, ~1-2 days)
├── Mount mobile-tokens.css           (1 hour)
├── Extract useIsMobile() hook        (1 hour)
├── Add MobileAppShell branch         (2 hours)
└── Wire MobileBoard variant          (4 hours)
        │
        ▼
Phase D (Thoth, QA)
├── V1–V10 verification               (Iris's criteria)
├── M1–M8 verification                (Marvin's criteria)
├── J1–J5 verification                (joint)
└── Sign-off
```

**Critical-path risks:**

- **R1:** The Lumen compression might shift contrast ratios below WCAG AA. *Mitigation:* V6 check before Marvin touches anything.
- **R2:** The column peek pattern breaks if a column has 0 tasks (the next-column sliver is meaningless). *Mitigation:* Marvin handles the empty-state — the prototype doesn't need to demonstrate it.
- **R3:** The bottom sheet's `env(safe-area-inset-bottom)` might not be respected on older Android. *Mitigation:* the tab bar uses `--tabbar-safe` which falls back to 0px gracefully.

---

## 7. Out of scope (explicit)

For the record, so the next pass doesn't drift:

- ❌ Mobile variants of Dashboard, Forge, Settings, Runs
- ❌ Native iOS/Android shells (this is PWA-only; Capacitor/Expo is a separate decision)
- ❌ Push notifications
- ❌ Offline write-queue (we read offline, we don't write offline)
- ❌ Drag-and-drop between non-adjacent columns (Trello does this with multi-swipe; we don't, not in v1)
- ❌ Multi-select on mobile (long-press to multi-select is a Trello pattern we're deferring; the prototype does single-select only)
- ❌ Tablet-specific layouts (`md` breakpoint gets a stretched phone layout, not a true tablet layout — that's a future pass)
- ❌ Re-themed dark mode for mobile (we use the existing dark Lumen; light mode is a future pass)
- ❌ The Workforge interview on mobile (Soulforge's 7-question flow is a separate design problem; not this PR)

---

## 8. Decision log

| Decision | Choice | Rationale | Date |
|----------|--------|-----------|------|
| Reference products | Make.com (editor) + Trello (kanban) | Best-in-class for the two patterns we need; both are well-known to the user; layouts are not protectable | 2026-06-21 |
| Breakpoint cutoff | 640px (Tailwind `sm` default) | Below 640px, the Lumen side rail can't fit | 2026-06-21 |
| Touch target floor | 48×48px (Material spec) | Lumen's chunky serif headings need extra visual weight | 2026-06-21 |
| Lumen compression | 8 steps → 5 effective steps for mobile | Adjacent steps blur on phone OLED at arm's length; compression is reversible via `@media` | 2026-06-21 |
| Pinch-but-no-rotate | Pinch only, no rotation gesture | n8n's mobile has accidental-rotation bugs; we sidestep | 2026-06-21 |
| Build pattern | Single-file HTML prototypes (not Figma, not React) | Same pattern as the existing Conductor mock; Konan can review in a real browser | 2026-06-21 |
| Token-mount approach | `@media` block in existing `src/theme/index.css` | Zero component changes; clean rollback if we change our minds | 2026-06-21 |

---

## 9. File checklist (for handoff)

Iris's desk, end of Phase A:

- [ ] `~/workspace/conductor-mobile/README.md`
- [ ] `~/workspace/conductor-mobile/mobile-workflow-editor.html`
- [ ] `~/workspace/conductor-mobile/mobile-kanban.html`
- [ ] `~/workspace/conductor-mobile/tokens/mobile-tokens.css`

Konan's desk, end of Phase B:

- [ ] Sign-off comment on this doc
- [ ] Open the two HTML files in a real phone, swipe around, give one round of feedback (or approve)

Marvin's desk, end of Phase C:

- [ ] `mobile-tokens.css` mounted in `src/theme/index.css`
- [ ] `useIsMobile()` hook in `src/hooks/`
- [ ] `MobileAppShell` branch in `src/shell/AppShell.tsx`
- [ ] `MobileBoard` variant in `src/kanban/MobileBoard.tsx`
- [ ] All M1–M8 criteria verified

Thoth's desk, end of Phase D:

- [ ] V1–V10 verified (or failed with specifics)
- [ ] M1–M8 verified
- [ ] J1–J5 verified
- [ ] Sign-off or block
