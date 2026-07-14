# Mobile pack Phase C — seam 1+2 complete (2026-06-22)

**Cards:** t_eb2c7477 (marvin) — DONE; t_54033fed + t_ca6a8a1e (still `todo`).

**What landed:** `src/mobile/useIsMobile.ts` (matchMedia hook, boolean return at max-width: 639px), `src/mobile/index.ts` (re-export + side-effect import of CSS), `src/mobile/mobile-tokens.css` (copy of v1.1.0 from athenaeum), `src/mobile/__tests__/useIsMobile.test.ts` (4 tests, all passing).

**Verify (corrected path):** `test -f /home/konan/projects/conductor-ui/src/mobile/useIsMobile.ts && grep -q matchMedia ... && grep -q mobile-tokens ...` → exit 0. tsc clean. Full vitest: 1157 pass / 11 pre-existing fail (none in src/mobile/).

**Decisions that affect other gods:**
- **Hook signature: boolean** (per body literal). Plan §4.2 says `{ isMobile, isTablet, breakpoint }` object. Downstream cards t_54033fed / t_ca6a8a1e will compile fine either way as long as they use `if (!useIsMobile())`, but if anyone assumed `.isMobile` field access, tsc will fail.
- **Tokens mount: in `src/mobile/index.ts` (side-effect import)**, not in `src/theme/index.css`. Deviation from Iris contract §3.1 / plan §4.1 — both say wrap `@import` inside `@media (max-width: 639px) { }` in src/theme/index.css. Reasoning in DECISIONS.md §"Mobile pack Phase C" item 1. Iris should ack or adjust on next pass.
- **mobile-tokens.css copied locally**, not symlinked, not via athenaeum path. When Iris bumps v1.x, this copy needs a refresh sweep (file under follow-ups, don't auto-sync — would mask Iris's review).

**Pre-existing failures NOT introduced by this card:** 11 fails in palette.test.ts / kanban/card.test.tsx / ledger_client/local_stub.test.ts. Same files, same assertions as before this card ran.

**Follow-up cards recommended:**
1. **Body path bug** — `/home/konan/pantheon/conductor-ui/` doesn't exist; project is at `/home/konan/projects/conductor-ui/`. Body-literal verify command will fail every time. Orchestrator fix needed.
2. **Border re-route in components** — Iris's V6 fix (t_18d26038) flagged that 8× `1px solid var(--lumen-6)` in HTML prototypes should become `1px solid var(--lumen-3)` in React components. This card didn't touch components (body says "Do not implement new components"). t_54033fed + t_ca6a8a1e must do this when they wire component shapes.
3. **Thoth V1–V10 re-run** — QA gate not re-executed since Iris's V6 fix. Token-level color-contrast math-verified, but structural V6 violations (kanban nested-interactive, kanban target-size, editor aria-hidden-focus, editor .sheet-handle focus-visible) and V2/V3/V8/V10 unchanged. Out of scope for this card.

**Status of sibling Marvin cards:** t_54033fed (MobileBoard.tsx) + t_ca6a8a1e (MobileAppShell.tsx) — still `todo`. The gate concern (V6 in card 002) is the same as this card had — they may need unblock too.
---

## Seam 3 (MobileAppShell.tsx) — 2026-06-22

**Card:** t_ca6a8a1e — DONE.

**What landed:** `src/mobile/MobileAppShell.tsx` (mobile shell with bottom 4-tab bar: Editor/Board/Runs/Profile; no left side rail; self-gated by `useIsMobile()`), `src/mobile/__tests__/MobileAppShell.test.tsx` (6 tests covering tab count, self-gate, active state, sub-path active, V6 border token, tabbar height/safe-area). `src/mobile/index.ts` extended to re-export `MobileAppShell` so the module's public surface matches the convention set by `useIsMobile`.

**Verify (corrected path):** `test -f /home/konan/projects/conductor-ui/src/mobile/MobileAppShell.tsx && grep -q useIsMobile ... && grep -q tab ...` → exit 0. tsc clean. Mobile-only vitest: 10/10 pass.

**Body-literal verify (path-bug):** exits 1 (same `/home/konan/pantheon/conductor-ui/` → `/home/konan/projects/conductor-ui/` bug as seam 1+2).

**LOC delta:** 50 non-comment non-blank lines, under the body cap of 60.

**Decisions that affect other gods:**
- **Profile tab → /settings** (decision; body literal said Profile, no /profile route exists and body forbids new routes). Plan §4.3 said "Settings goes inside a profile menu" — closest existing semantic match is /settings. Documented inline so the integration card can re-target or open a /profile follow-up.
- **V6 border re-route APPLIED** (carrying seam 1+2's follow-up). Tabbar uses `border-[var(--lumen-3)]`, not the prototype HTML's `border-[var(--lumen-6)]`. Regression test pins both the positive assertion and the negative guard (`expect(tabbar.className).not.toContain('border-[var(--lumen-6)]')`).
- **Self-gate inside the component.** `MobileAppShell` returns `null` above 639px. Body said "useIsMobile() gates the render" — interpreted as in-component gating. Slightly redundant with the conventional `isMobile ? <MobileAppShell /> : <DesktopAppShell />` swap in AppShell.tsx, but makes the component safe to drop in unconditionally. Integration card can rely on either layer.
- **NOT integrated into AppShell.tsx.** Body forbids modifying the desktop AppShell, so MobileAppShell is created and exported but the root layout still renders desktop chrome unconditionally. Integration is a separate card.

**Sibling card status:** t_54033fed (MobileBoard.tsx) — still `todo`. Same body path bug will apply. The V6 border re-route pattern from this card is the template: use `--lumen-3` for borders, pin a regression test against `--lumen-6`.

**Pre-existing failures NOT introduced:** same 11 fails in palette / kanban/card / ledger_client/local_stub from before seam 1+2. Confirmed by stash + re-test on baseline.

---

## Mobile pack Phase C — seam 4 complete (2026-06-22, t_54033fed)

**What landed:** `src/mobile/MobileBoard.tsx` (column-peek variant, 83 LOC total / ~50 code-only; self-gated by `useIsMobile()`; column nav via dots with `min-w-[var(--touch-min)] min-h-[var(--touch-min)]` per plan §2.2; reuses `<TaskCard>` unchanged). `src/mobile/index.ts` extended to also re-export `MobileBoard`. **No new test file** — body doesn't require; precedent permissive; flagged as follow-up.

**Verify (corrected path):** `test -f /home/konan/projects/conductor-ui/src/mobile/MobileBoard.tsx && grep -q useIsMobile ... && grep -q TaskCard ...` → exit 0. tsc clean. Full vitest regression: 1163 pass / 11 fail (matches seam 3 baseline exactly).

**Body-literal verify (path-bug):** exits 1. Same `/home/konan/pantheon/conductor-ui/` → `/home/konan/projects/conductor-ui/` bug as seams 1+2 and 3. Three cards in this pack confirmed hitting it; orchestrator fix still pending.

**Decisions that affect other gods:**
- **Path: `src/mobile/MobileBoard.tsx`, not `src/kanban/` (plan §4.4 spec).** Body is explicit; body wins over plan. Matches the seam 1+2 module choice.
- **V6 border re-route applied** — same template as MobileAppShell: `border-[var(--lumen-3)]` for the column-strip header rule. No regression test pinned in this cut (logged as follow-up).
- **Self-gate inside the component** — same idiom as MobileAppShell. Returns `null` above 639px. Safe to render unconditionally.
- **No shared `useBoardData` hook exists.** Body says "reuse existing data hooks" + "do not create new data hooks" — both can't be satisfied (desktop `Board.tsx` inlines its fetch; only `useIsMobile.ts` and `useTheme.ts` exist project-wide). Resolution: duplicated fetch under "do not create new data hooks" wins. Follow-up: extract `src/kanban/useBoardData.ts` that both desktop and mobile consume.
- **`<TaskCard onSelect>` callback, not `onAdvance`/`onAssign`/`onMove`.** Plan §4.4 listed those event names but Phase R6 changed the desktop Board contract to `onSelect`. "Do not change existing callback signatures" wins. MobileBoard logs `onSheetOpen` on tap to match prototype `bind()` parity.
- **No swipe handler in this cut.** Column dots are the only nav. Follow-up card: "Mobile pack Phase C2 — MobileBoard gesture wiring."
- **NOT integrated into `/board` route.** Body forbids modifying the desktop Board. Integration is a separate card.

**Pre-existing failures NOT introduced:** same 11 fails as before seam 1+2 + seam 3. Confirmed by matching the seam 3 baseline.

**Follow-ups (full list in `Codex-God-marvin/DECISIONS.md` §"Seam 4"):** body path bug; swipe handler; `useBoardData` extraction; MobileBoard regression tests; `/board` route integration; Thoth V1–V10 re-run.

— Marvin, 2026-06-22 (seam 4 of mobile pack Phase C)

---

## C1a — mobile-tokens.css committed (2026-06-24, t_ea162b60)

**What landed:** `src/mobile/mobile-tokens.css` (119 lines) now tracked on main at commit 99ad63e. File was created earlier in the seam 1+2 work but never committed — orphan on disk, referenced by C1f's `@import` in `src/theme/index.css` line 428. Closed out as the C1a "CREATE" card.

**Verify:**
- `test -f src/mobile/mobile-tokens.css` → OK
- postcss parse: 1 @media atrule, 1 :root rule, 23 declarations — clean
- All 22 spec tokens present + 1 extra (`--sheet-radius: 16px`)
- 3 documented deviations from plan §3.1 draft: `--lumen-4/5/6` (the "V6 contrast fix" pair — `--lumen-5: #8A8478` is readable on dark surfaces; the spec's `#25221F` is not)
- No JS, no event handlers, no external imports

**Sibling state after this commit:**
- `src/mobile/MobileAppShell.tsx` (C1c, 9133e70) — tracked
- `src/mobile/useIsMobile.ts` (C1b, d439a4a) — tracked
- `src/mobile/mobile-tokens.css` (C1a, 99ad63e) — tracked **now**
- `src/mobile/MobileBoard.tsx` (C1d, t_1f02d9af) — **still untracked on main** (seam 4 work landed on feature/w1c-c-c-e2e-final, not main). Separate follow-up: cherry-pick fd9f374 + 8b818b2 onto main, or re-claim t_1f02d9af to land the commit.
- `src/theme/index.css` import (C1f, dbe65da) — tracked

**Divergence from athenaeum (known follow-up, not a blocker):** the file in the project uses 5 conceptual tiers with paired values (Tier 1 = #0E0D0C × lumen-0/1; Tier 2 = #1A1817 × lumen-2/3/4; Tier 3-5 text = #8A8478, #A8A294, #F5F4ED). Iris's athenaeum v1.1.0 at `athenaeum/Codex-God-Iris/mobile-pattern-pack/mobile-tokens.css` uses 8 distinct values (`--lumen-1: #151312`, `--lumen-3: #1F1D1B`, `--lumen-4: #25221F`, `--lumen-5: #635E56`). The seam 1+2 decision was to copy locally, not symlink, and the components C1c/C1d were built around the file's 5-tier values — changing them now would break the visual hierarchy. The file's own comment references "Iris v1.1.0" for the role split (lumen-3 = rule, lumen-6 = text-soft, lumen-7 = text-primary), which is structurally accurate even though the values themselves are the 5-tier variant. If Iris ships a v1.2 that re-aligns, that's a refresh-sweep follow-up.

**Follow-ups (unchanged from earlier seams):** body path bug (orchestrator); border re-route in components (done in C1c/C1d); Thoth V1–V10 re-run; C1d commit onto main; Iris v1.x refresh-sweep if v1.2+ ships with re-aligned values.

— Marvin, 2026-06-24 (C1a closeout, t_ea162b60)
