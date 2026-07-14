# Olympus UI — Open Questions & Gaps

> Living document. Each question must be answered before the dependent build task starts.
> Created: 2026-05-27. Append answers as they are resolved.
> **When all questions are answered, merge back into BUILD_TRACKER.md.**

---

## 1. Dead Code Cleanup

### Q1.1 — SidebarRail.tsx removal
**Context:** AppShell.tsx imports `Sidebar` (singular), not `SidebarRail`. Sidebar.tsx handles both collapsed (48px rail) and expanded (280px drawer) states. SidebarRail.tsx has no imports beyond its own test file.

**Question:** Confirm SidebarRail.tsx + SidebarRail.test.tsx should be deleted before any rail modifications in T1-T3?

**Answer:** ✅ YES — SidebarRail.tsx is the old standalone component. Sidebar.tsx is canonical. Delete SidebarRail.tsx and SidebarRail.test.tsx.

---

## 2. Backend Ownership

### Q2.1 — Who builds the auth backend?
**Context:** T4-T7 are frontend tasks. They need backend endpoints.

**Answer:** ✅ Built by Hephaestus as an **Olympus backend service** — simple, separate from Hermes Agent. Keep basic, improve later.

- Login UX: blank screen, grid of user icons, click → password prompt → backend check → activate profile
- Marked for future improvement: move to Hermes plugin when security tightens
- For now: simple credential check, nothing complicated

---

### Q2.2 — Who builds the feature flag API?
**Context:** T1 needs feature toggles that persist.

**Answer:** ✅ Olympus backend endpoint — same service as auth.
- `GET /api/feature-flags` → `{ "skills": true, "cron": false, ... }`
- `PUT /api/feature-flags` → save changes to JSON file on disk
- Instant toggle — frontend reads flag state on boot and reacts to changes

---

### Q2.3 — Who builds the search API?
**Context:** T3 needs unified search across sessions, athenaeum, tools, gods.

**Answer:** ✅ Client-side aggregation. No new backend endpoint needed.
- `useSearch` hook fires parallel fetches: `/api/sessions`, `/api/athenaeum/search`, `/api/gods`, `/api/mcp/tools`
- Search panel has source toggle pills (● Sessions, ● Athenaeum, ○ Gods, ○ Tools)
- Toggling a source off cancels/ignores that fetch — results update instantly
- Results grouped by source, ranked by relevance

---

### Q2.4 — Who builds the Stream API?
**Context:** T17 needs `/api/stream/entities`, `/api/stream/edges`, `/api/stream/metrics`.

**Answer:** ✅ Olympus backend serves them — consistent pattern with auth, flags, theme.
- Reads data written by Stream B's ingest pipeline
- Single backend for frontend to talk to

---

### Q2.5 — Athenaeum API availability
**Context:** T2 builds the Athenaeum browser. Pantheon MCP exposes athenaeum operations but browser can't call MCP.

**Answer:** ✅ HTTP wrappers needed.
- `GET /api/athenaeum/walk?path=` → index tree
- `GET /api/athenaeum/read?path=` → file content
- `GET /api/athenaeum/search?q=` → semantic search
- For the UI: find existing HTML file tree viewer to integrate, potentially tie into Boon viewer

---

## 3. Architecture Decisions

### Q3.1 — Admin vs Settings split
**Context:** Rail has Admin (shield) and Settings (gear). Both go to same overlay.

**Answer:** ✅ DECIDED

**Settings** (user-facing, gear icon ⚙):
- Profile — display name, avatar, color
- Appearance/Theme — colors, density, logos
- Notifications — preferences, polling interval
- Integrations — n8n OAuth connections
- Language — preferred language
- User Cron — current user's cron jobs only

**Admin** (operator, shield icon 🛡):
- Gods — manage gods + summon/edit/forge toggles
- Users & Roles — add/remove users, assign roles, god permissions
- Feature Flags — on/off for cron, plugins, skills, MCP, kanban, webhooks, terminal, multi-user
- System Cron — all system cron jobs + all user cron jobs
- Health — system status
- Logs — log viewer
- Plugins — installed plugins
- Skills — skills browser
- MCP — connected MCP tools
- Terminal — shell access
- Export — god/profile export

**Nuance:** Cron is split — user-scoped in Settings, system + all-users in Admin.

---

### Q3.2 — Feature toggle catalog
**Context:** T1 builds admin toggle system.

**Answer:** ✅ DECIDED — 11 toggles:
- Cron jobs, Plugins, Skills browser, MCP tools, Kanban board, Webhooks, Terminal
- Summon God, Edit God, Forge God, Multi-user mode
- When OFF: nav item hidden, route blocked, UI inaccessible. Backend still exists.
- May add more toggles later.

---

### Q3.3 — Theme config format
**Context:** T18 makes Olympus themeable.

**Answer:** ✅ Runtime loading from Olympus backend.
- Format: YAML (human-readable, both backend and frontend can parse)
- Location: served at `GET /api/theme`, stored at `~/pantheon/config/olympus-theme.yaml`
- Loading: fetched at app boot, changes apply instantly without rebuild
- Admin UI (Appearance tab in Settings) writes through `PUT /api/theme`
- Terminology map included in same config under `terminology:` block

---

### Q3.4 — Auth token storage
**Context:** T4 needs session persistence.

**Answer:** ✅ localStorage for now. Simple, fine for Tailscale-served local instances.
- `localStorage.setItem('olympus_token', token)` on login
- Sent as `Authorization: Bearer <token>` header on API calls
- Cleared on logout
- Note: migrate to httpOnly cookies when security hardening happens

---

### Q3.5 — Single-user → multi-user migration
**Context:** T7 toggles multi-user mode. Existing data needs a home.

**Answer:** ✅ On multi-user toggle ON, all existing data auto-scoped to the owner. No migration wizard. New users start clean. Sharing is an explicit future feature, not a side effect.

---

### Q3.6 — OAuth redirect URI pattern
| **Context:** N4 builds n8n OAuth flow.

**Question:** 
- What's the callback URL pattern?
- Where are n8n credential types documented?

**Answer:** 

---

## 4. Route & State Planning

### Q4.1 — New route tree
**Context:** New pages needed for onboarding, stream, integrations.

**Answer:** ✅ DECIDED
```
__root.tsx                          (AppShell wrapper, checks onboarding_completed flag)
├── index.lazy.tsx                  / (chat)
├── login.lazy.tsx                  /login
├── settings.lazy.tsx               /settings (tab-based overlay from rail)
├── stream.lazy.tsx                 /stream (Codex-Stream dashboard)
└── onboarding/
    ├── welcome.lazy.tsx            /onboarding/welcome
    ├── runtime-choice.lazy.tsx     /onboarding/runtime-choice
    ├── custom/
    │   ├── inference.lazy.tsx      /onboarding/custom/inference
    │   ├── integrations.lazy.tsx   /onboarding/custom/integrations
    │   ├── voice.lazy.tsx          /onboarding/custom/voice
    │   └── search.lazy.tsx         /onboarding/custom/search
    └── complete.lazy.tsx           /onboarding/complete
```
Settings and Admin remain rail-triggered overlays. Stream and Onboarding are full-page routes.
⚠️ Onboarding backend needs attention for seamless experience — address during T15.

---

### Q4.2 — New Zustand stores
**Context:** New features need state management.

**Answer:** ✅ DECIDED — 6 stores, kept separate:
| Store | Purpose |
|-------|---------|
| `auth-store` (extend) | Add login/logout actions, token management, `isAuthenticated` |
| `onboarding-store` | Wizard step index, draft choices, `completeAndExit()` |
| `feature-flag-store` | Toggle state cache, `isEnabled('skills')`, refresh from API |
| `stream-store` | Entity cache, graph node/edge state, metrics, hotness |
| `user-store` | User list for admin panel, CRUD actions |
| `search-store` | Query state, source toggles, aggregated results cache |

---

## 5. Testing & QA

### Q5.1 — Test file requirement
**Answer:** ✅ Yes. Every new component in `src/components/` must have a matching `*.test.tsx` with at minimum render + key interaction tests.

### Q5.2 — Mobile verification
**Answer:** ✅ Yes. All QA gates include a ≤768px viewport check for new components.

### Q5.3 — Keyboard/a11y verification
**Answer:** ✅ Yes. Basic checks: Tab through interactive elements, Enter to activate, Escape to close modals. Not full WCAG — just making sure things work without a mouse.

---

## 6. Missing Features

### Q6.1 — Session management UI
**Context:** Sessions load and switch but no rename, delete, or pin from UI.

**Answer:** ✅ Mirror the :8787 pattern — always-visible icon overlays on each session row: ☆ pin, ▾ context, ✏ rename, × delete. Icons at 12px, wrapped below timestamp. No hover-only, no right-click.

---

### Q6.2 — Chat export
**Answer:** ✅ Deferred polish. Everything is saved to athenaeum anyway.

---

### Q6.3 — Install/setup documentation
**Answer:** ✅ Not needed for dev repo. Olympus will be built into Pantheon and replace the current Pantheon UI. Install docs will live in the Pantheon repo.

---

## 7. Sequencing Corrections

### Q7.1 — T14 dependency on T1
**Answer:** ✅ Build OAuth components standalone in parallel with T1. Add micro-task T14b: "Wire integrations into Settings tab" that fires when both T1 and T14 are complete.

---

### Q7.2 — Kanban investigation scope
**Answer:** ✅ Kanban works on :8787 and in Hermes Agent's built-in dashboard. The 500 from Olympus is likely a wrong API path or proxy issue. Task: investigate working implementations' API paths → fix URL in Olympus.

---
### Q8.2 — Hermes plugin hooks
**Context:** T8-T10 build Hermes plugins that use `on_pre_write` hook.

**Question:** Does Hermes Agent's plugin system support `on_pre_write` hooks for wiki operations? Is this documented?

**Answer:** ✅ Investigate before Stream B starts. Hephaestus will audit Hermes Agent's current plugin hook system to determine what hooks exist for wiki operations. If `on_pre_write` doesn't exist, we'll build what we need or adapt to the existing hook model.

---

---
## ⚠️ REMINDER

**All questions answered. Merge answers back into BUILD_TRACKER.md now.**
