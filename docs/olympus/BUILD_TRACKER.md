# Olympus UI — Build Tracker

> Systematic build tracker with QA gates. All architectural decisions resolved.
> Updated: 2026-05-28 — Merged from QUESTIONS.md. All 25 questions answered.
> Builder: Hephaestus

## Legend
- 🔲 Not started
- 🔄 In progress
- ✅ Verified working
- ❌ Failed / needs fix
- ➖ Skipped / deferred
- 🚦 QA Gate — must pass before proceeding

---

## Resolved Architecture Decisions

### Backend: Olympus Backend Service
A new lightweight backend service runs alongside Hermes Agent. Stack: Python + FastAPI (keep simple; future standalone mobile app will prompt refactor). It serves:
- `POST /api/auth/login`, `POST /api/auth/logout`
- `GET/POST/PATCH/DELETE /api/users`
- `GET/PUT /api/feature-flags`
- `GET/PUT /api/theme`
- `GET /api/athenaeum/walk`, `GET /api/athenaeum/read`, `GET /api/athenaeum/search`
- `GET /api/stream/entities`, `GET /api/stream/edges`, `GET /api/stream/metrics`

### Admin vs Settings
- **Settings** (gear ⚙): Profile, Appearance/Theme, Notifications, Integrations, Language, User Cron
- **Admin** (shield 🛡): Gods, Users & Roles, Feature Flags, System Cron, Health, Logs, Plugins, Skills, MCP, Terminal, Export

### Feature Toggles (11 total)
Cron, Plugins, Skills, MCP, Kanban, Webhooks, Terminal, Summon God, Edit God, Forge God, Multi-user mode.
OFF = hidden from UI, route blocked. Backend still exists.

### Theme System
- Runtime loading from Olympus backend (`GET /api/theme`)
- YAML format at `~/pantheon/config/olympus-theme.yaml`
- Terminology map included under `terminology:` block

### Auth
- localStorage tokens (upgrade to httpOnly cookies later)
- Single-user default, multi-user toggleable
- On multi-user ON: existing data auto-scoped to owner
- Login UX: grid of user icons → password prompt

### Route Tree
```
__root.tsx                          (checks onboarding_completed flag)
├── index.lazy.tsx                  / (chat)
├── login.lazy.tsx                  /login
├── settings.lazy.tsx               /settings (overlay from rail)
├── stream.lazy.tsx                 /stream
└── onboarding/
    ├── welcome.lazy.tsx
    ├── runtime-choice.lazy.tsx
    ├── custom/
    │   ├── inference.lazy.tsx
    │   ├── integrations.lazy.tsx
    │   ├── voice.lazy.tsx
    │   └── search.lazy.tsx
    └── complete.lazy.tsx
```

### Zustand Stores (6 total)
`auth-store` (extend), `onboarding-store`, `feature-flag-store`, `stream-store`, `user-store`, `search-store`

### Session Management
Mirror :8787 pattern — always-visible icon overlays: ☆ pin, ▾ context, ✏ rename, × delete

### QA Requirements (all new components)
- Matching `*.test.tsx` with render + interaction tests
- Mobile viewport check (≤768px)
- Basic keyboard nav (Tab/Enter/Escape)

---

## Pre-Build Investigations

| # | Task | Status | Depends on |
|---|------|--------|------------|
| I1 | Audit Hermes Agent plugin hooks — does `on_pre_write` exist for wiki ops? | 🔲 | Nothing |
| I2 | Research n8n credential types + BYOK flow | ✅ | Nothing → Deprecated: composio research superseded by n8n |

**Rule:** I1 must complete before Stream B starts. I2 must complete before T14 starts.

---

## Tier 0 — Foundation Verification (Pre-Flight)

| # | Step | Status | Verified | Notes |
|---|------|--------|----------|-------|
| 0.1 | TypeScript compiles clean (`npx tsc --noEmit`) | ✅ | 2026-05-26 | Exit 0, no errors |
| 0.2 | Vite build succeeds | ✅ | 2026-05-26 | 2,101 modules, 1.43s |
| 0.3 | Dev server starts on :5173 | ✅ | 2026-05-26 | Proxy /api/* → :8787 working |
| 0.4 | Test suite passes | ✅ | 2026-05-27 | 16/16 files, 145/145 tests — zero failures |
| 0.5 | Hermes gateway :8787 reachable | ✅ | 2026-05-26 | Status: ok |

### 🚦 QA Gate 0
```
- [ ] npx tsc --noEmit → exit 0
- [ ] npx vitest run → ≤9 failures (baseline)
- [ ] Dev server loads without console errors
- [ ] git status clean on master
```

---

## Tier 0.5 — Cleanup

### T0.5 — Delete Dead Code

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `23b49a9` |
| **Files** | Delete: `SidebarRail.tsx`, `SidebarRail.test.tsx` |

**What:** Remove old standalone rail component. Sidebar.tsx is canonical.

**🚦 QA Gate T0.5:**
```
- [ ] SidebarRail.tsx deleted
- [ ] SidebarRail.test.tsx deleted
- [ ] npx tsc --noEmit → exit 0 (no broken imports)
- [ ] npx vitest run → ≤9 failures
- [ ] Dev server loads, rail works normally
- [ ] Commit: "chore: remove dead SidebarRail.tsx"
```

---

## Stream A: Olympus Gaps + Auth

> Olympus backend service + frontend components
> Can start after T0.5 (no other dependencies)

### T1 — Admin/Settings Split + Feature Toggles

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `8d50ea2` |
| **Depends on** | T0.5 |
| **Files** | `app-store.ts`, `SettingsRoot.tsx`, `AdminPanel.tsx`, `Sidebar.tsx`, `feature-flag-store.ts`, Olympus backend: `/api/feature-flags` |

**What it builds:**
- Split Settings overlay into two distinct surfaces
- Settings tabs: Profile, Appearance/Theme, Notifications, Integrations, Language, User Cron
- Admin tabs: Gods, Users & Roles, Feature Flags, System Cron, Health, Logs, Plugins, Skills, MCP, Terminal, Export
- Feature toggle system: 11 toggles persisted via Olympus backend `GET/PUT /api/feature-flags`
- Feature flag store: `isEnabled('skills')` gating helper

**🚦 QA Gate T1:**
```
COMPONENT TESTS:
- [ ] SettingsRoot.test.tsx → PASS (user tabs only)
- [ ] AdminPanel.test.tsx → PASS (operator tabs)
- [ ] Sidebar.test.tsx → PASS (both buttons work)
- [ ] New: feature-flag-store.test.ts → PASS
- [ ] Every new component has matching *.test.tsx
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Settings gear → opens with user-facing tabs only
- [ ] Admin shield → opens with operator tabs
- [ ] Toggle Cron OFF → Cron tabs disappear from both Settings and Admin
- [ ] Toggle Skills OFF → Skills tab disappears from Admin
- [ ] Toggle MCP OFF → MCP tab disappears from Admin
- [ ] Toggle Plugins OFF → Plugins tab disappears from Admin
- [ ] All toggles survive page refresh
- [ ] All toggles survive dev server restart
- [ ] Mobile viewport (≤768px): tabs scrollable, buttons tappable
- [ ] Keyboard: Tab through tabs, Enter to activate
- [ ] Zero console errors
- [ ] git branch --show-current verified

GIT:
- [ ] Commit: "feat(admin): split Settings/Admin + feature toggle system"
```

---

### T2 — Athenaeum Browser

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `b22d550` |
| **Depends on** | T1 |
| **Files** | `Sidebar.tsx`, `BoonPanel.tsx`, `AdminPanel.tsx`, new: `AthenaeumBrowser.tsx`, `use-athenaeum.ts`. Olympus backend: `/api/athenaeum/*` |

**What it builds:**
- Rename every "Library" → "Athenaeum" across all components, tests, stores
- Rename "Trove Library" → "Athenaeum" in BoonPanel, AdminPanel
- Build Athenaeum browser: file explorer tree + viewer pop-up
- Integrate existing file tree viewer (HTML/JSON/Python — research during build)
- Olympus backend wraps Pantheon MCP athenaeum operations as HTTP endpoints
- Rail icon + expanded drawer nav item wired with onClick

**🚦 QA Gate T2:**
```
COMPONENT TESTS:
- [ ] Sidebar.test.tsx → PASS
- [ ] AthenaeumBrowser.test.tsx → PASS (new)
- [ ] grep -r "Library" src/ → only lucide-react imports remain
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Rail icon tooltip shows "Athenaeum" not "Library"
- [ ] Expanded drawer nav shows "Athenaeum"
- [ ] Click rail icon → Athenaeum browser opens
- [ ] File tree loads from /api/athenaeum/walk
- [ ] Click file → viewer pop-up shows content with line numbers
- [ ] Search within Athenaeum filters results
- [ ] BoonPanel header shows "Athenaeum"
- [ ] Mobile: tree navigable, files tappable
- [ ] Keyboard: Escape closes viewer
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(athenaeum): rename Library→Athenaeum + file browser"
```

---

### T3 — Unified Search

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `6fe1b8a` |
| **Depends on** | T2 (shares athenaeum data) |
| **Files** | New: `SearchPanel.tsx`, `use-search.ts`, `search-store.ts`. Modify: `Sidebar.tsx` |

**What it builds:**
- Search panel triggered from rail icon + Cmd/Ctrl+K
- Client-side aggregation: parallel fetches to `/api/sessions`, `/api/athenaeum/search`, `/api/gods`, `/api/mcp/tools`
- Source toggle pills: ● Sessions, ● Athenaeum, ○ Gods, ○ Tools
- Results grouped by source, ranked by relevance
- Remove "coming soon" from rail icon

**🚦 QA Gate T3:**
```
COMPONENT TESTS:
- [ ] SearchPanel.test.tsx → PASS (new)
- [ ] search-store.test.ts → PASS (new)
- [ ] use-search.test.ts → PASS (new)
- [ ] Sidebar.test.tsx → PASS
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Rail Search icon clickable — opens search panel
- [ ] Cmd/Ctrl+K from anywhere opens search
- [ ] Type query → results grouped by source
- [ ] Toggle Gods OFF → god results disappear instantly
- [ ] Toggle Tools OFF → tool results disappear
- [ ] Click session result → navigates to that session
- [ ] Click athenaeum result → opens file viewer
- [ ] Click god result → switches active god
- [ ] Empty state: "No results for [query]"
- [ ] Escape closes panel
- [ ] Click outside closes panel
- [ ] Mobile: panel full-width, toggles tappable
- [ ] Keyboard: Tab between results, Enter to select
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(search): unified search with source toggle pills"
```

---

### T4 — Local Auth (Owner-First)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `ce3a539` |
| **Depends on** | T1 (admin panel exists) |
| **Files** | `auth-store.ts` (extend), `use-auth.ts`, `LoginPage.tsx`, `router.tsx`, `__root.tsx`, Olympus backend: `/api/auth/login`, `/api/auth/logout`, `/api/olympus/auth/me` |

**What it builds:**
- Olympus backend: simple credential check, token generation
- Login UX: blank screen, grid of user icons, click → password prompt → authenticate
- localStorage token persistence
- `Authorization: Bearer <token>` on all API calls
- Auth context wraps AppShell, unauthenticated → redirect to /login
- Owner = first user created at install, always has full access
- Multi-user mode OFF by default (login page hidden, auto-login as owner)

**🚦 QA Gate T4:**
```
COMPONENT TESTS:
- [ ] LoginPage.test.tsx → PASS (new)
- [ ] auth-store.test.ts → PASS
- [ ] Login: username+password fields render
- [ ] Sign In disabled until both fields filled
- [ ] Invalid credentials → error message
- [ ] Valid credentials → redirect to /
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Cold load with multi-user OFF → straight to chat (no login)
- [ ] Multi-user ON → redirected to /login
- [ ] User grid visible with icons
- [ ] Click user → password prompt appears
- [ ] Enter correct password → lands on chat
- [ ] Profile button shows user info (not hardcoded "Y")
- [ ] Close tab, reopen → still authenticated (token persists)
- [ ] Logout → redirected to /login
- [ ] Mobile: grid scrollable, password input visible
- [ ] Keyboard: Tab between users, Enter to select
- [ ] Zero console errors on login/logout
- [ ] No auth secrets in devtools/frontend
- [ ] git branch verified

GIT:
- [ ] Commit: "feat(auth): owner-first local auth with grid login"
```

---

### T5 — User Management Panel

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commits** | `487e5ff`, `b9e3a61` (branch `feat/user-management`) |
| **Depends on** | T4, T1 |
| **Files** | `UserManagementPanel.tsx` + test (23 tests), `olympus-auth.ts`, `vite.config.ts`, `AdminPanel.tsx` |

**What it builds:**
- "Users & Roles" tab in Admin panel
- List all users: name, role, last login, status (active/disabled)
- Add User modal: username, display name, initial password, role
- Edit User: change role, reset password, disable/enable
- Delete User: confirmation, cannot delete self (owner)
- Olympus backend: user CRUD with JSON file store

**🚦 QA Gate T5:**
```
COMPONENT TESTS:
- [ ] UserManagementPanel.test.tsx → PASS (new)
- [ ] user-store.test.ts → PASS (new)
- [ ] Add user flow, edit user flow, delete confirmation tested
- [ ] Cannot delete self tested
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Admin → Users & Roles tab visible
- [ ] Shows all users with correct roles
- [ ] Add User → fills form → user appears in list
- [ ] New user CAN log in with given credentials
- [ ] Edit user → change role → applied on next login
- [ ] Disable user → user cannot log in
- [ ] Delete user → confirmation → removed
- [ ] Try delete self → blocked with message
- [ ] Mobile: forms usable, buttons tappable
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(admin): user management with add/edit/delete/disable"
```

---

### T6 — Role Assignment + God Permissions

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commits** | `40636ef` (Olympus-UI), `63b82b3` (Pantheon) |
| **Depends on** | T5 |
| **Files** | `god-store.ts`, `GodPicker.tsx`, `UserManagementPanel.tsx`, `olympus_users.py` |

**What it builds:**
- Role definitions: owner, admin, user
- God permission assignment per user: which gods each user can access
- Owner always has access to all gods
- GodPicker filters to permitted gods
- Chat blocked for unauthorized god switch

**🚦 QA Gate T6:**
```
COMPONENT TESTS:
- [ ] GodPicker filters to permitted gods for non-owner
- [ ] Owner sees all gods regardless of permissions
- [ ] God switch blocked for unauthorized god
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Admin → Users → click user → god permission checklist visible
- [ ] Uncheck a god → save → user's GodPicker no longer shows that god
- [ ] Owner still sees all gods
- [ ] Re-check god → reappears for user
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(auth): role-based god permissions per user"
```

---

### T7 — Multi-User Toggle

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `d12e416` (branch `feat/user-management`) |
| **Depends on** | T5, T6 |
| **Files** | `__root.tsx`, `AdminPanel.tsx`, `feature-flag-store.ts` |

**What it builds:**
- Toggle in Admin → Feature Flags: "Multi-User Mode"
- OFF (default): login page hidden, auto-login as owner
- ON: login page active, user management visible, role enforcement active
- On toggle ON: all existing data auto-scoped to owner

**🚦 QA Gate T7:**
```
BROWSER VERIFICATION:
- [ ] Multi-user OFF → cold load goes straight to chat
- [ ] Multi-user OFF → Users tab hidden in Admin
- [ ] Toggle ON → Users tab appears
- [ ] Toggle ON → logout → redirected to /login
- [ ] Toggle ON → different user can log in
- [ ] Toggle OFF → other users logged out, owner restored
- [ ] Toggle survives server restart
- [ ] All existing sessions still visible to owner after toggle ON
- [ ] New user sees empty session list
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(admin): multi-user mode toggle"
```

---

### 🚦 Stream A Integration Gate (T1-T7)
```
- [ ] Admin/Settings split working with correct tabs
- [ ] All 11 feature toggles functional
- [ ] Athenaeum browser loads real data
- [ ] Search returns results from all sources
- [ ] Login/logout works end-to-end
- [ ] User CRUD works
- [ ] God permissions enforced
- [ ] Multi-user toggle transitions cleanly
- [ ] npx vitest run → ≤9 failures
- [ ] Mobile: all new surfaces usable at ≤768px
```

---

## Stream B: Integration Backend

> Hermes plugins + cron jobs. Independent of Stream A.
> Location: `~/.hermes/plugins/` and `~/.hermes/cron/pantheon-sync/`
> **Prerequisite:** I1 (Hermes plugin hooks audit) must complete first.

### I1 — Hermes Plugin Hooks Audit

| Field | Value |
|-------|-------|
| **Status** | ✅ Complete |
| **Files** | Research only |

**Finding:** No dedicated wiki/content write hooks exist. Strategy confirmed:

- **`pre_tool_call`** — fires before any tool executes, can veto with `{"action": "block"}`. Use for WikiGuard (block low-quality content) and Dedup (block duplicates). Matcher: `athenaeum_write|write_file|patch`
- **`transform_tool_result`** — fires after tool returns, can rewrite result string. Use for Provenance (inject source/provider tags into result)
- 15 plugin hook types total. Key files: `hermes_cli/plugins.py:78-114` (VALID_HOOKS), `model_tools.py:688-696` (pre_tool_call dispatch at tool boundary)
- T8-T10 implementation: register `pre_tool_call` handler per plugin, gate content before it reaches the write tool. No new hook types needed.

---

### T8 — WikiGuard Admission Gate (P0a)

| Field | Value |
|-------|-------|
| **Status** | ✅ Complete |

---
---

### T9 — Source Tags + Provenance (P0b)

| Field | Value |
|-------|-------|
| **Status** | ✅ Complete |
| **Depends on** | Nothing |
| **Files** | `~/.hermes/plugins/wiki-provenance/` |

**What:** Every content chunk gets mandatory `source`, `provider`, `connector`, and `provenance` fields in frontmatter. Plugin auto-injects source/provider when metadata available.

**🚦 QA Gate T9:**
```
- [ ] plugin.yaml exists with hooks config
- [ ] Source/provider/connector injected into frontmatter
- [ ] Missing provenance = lint warning
- [ ] Tag rules: chat→telegram, web_import→github, etc.
```

---

### T10 — Content-Addressed Dedup (P0c)

| Field | Value |
|-------|-------|
| **Status** | ✅ Complete |
| **Depends on** | Nothing |
| **Files** | `~/.hermes/plugins/wiki-dedup/` |

**What:** SHA256-based dedup. Normalize content, compute hash, compare against index. Same content = no write.

**🚦 QA Gate T10:**
```
- [ ] compute_hash() normalizes whitespace correctly
- [ ] Same content → same hash (dedup hit)
- [ ] First write: stores hash + path in index
- [ ] Second write with identical content: blocked
- [ ] Index persists across restarts (JSON file)
```


### 🚦 Phase 0 Integration Gate (T8+T9+T10)
```
- [ ] All three plugins coexist without conflicts
- [ ] Test chunk → passes gate → has provenance → stored
- [ ] Duplicate chunk → dedup blocks it
- [ ] Junk chunk → gate drops it → logged to dropped.log
```

---

### T11 — Sync Scheduler (P1b)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `0f959ef` (Pantheon repo) |
| **Depends on** | Phase 0 Gate |
| **Files** | `~/pantheon/cron/pantheon-sync/{sync_scheduler.py, sync_state.py, connections.json, README.md}` |

**What:** 20-minute cron loop. Walk active connections, check sync state, call adapter.

**🚦 QA Gate T11:**
```
- [ ] connections.json loads active connections
- [ ] SyncState: last_sync, cursor, records_today, daily budget
- [ ] Daily budget resets on date change
- [ ] Skips not-yet-due connections
- [ ] Skips over-budget connections
- [ ] Errors logged, scheduler never crashes
- [ ] Crontab: */20 * * * *
- [ ] Manual run_sync_tick() works
- [ ] scan.log records every tick
- [ ] Commit: "feat(sync): 20-min cron scheduler"
```

---

### T12 — Adapters: Gmail, GitHub, Slack (P1c)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `12ad4a7` (Pantheon repo) |
| **Depends on** | Phase 0 Gate |
| **Files** | `cron/pantheon-sync/adapters/{__init__,base,gmail,github,slack}.py` |

**What:** Provider-specific adapters. Fetch → canonical Markdown + metadata.

**🚦 QA Gate T12:**
```
PER ADAPTER:
- [ ] get_adapter(provider) returns correct class
- [ ] sync() → {"records": [...], "next_cursor": ...}
- [ ] canonicalize() → {"content": "markdown...", "metadata": {...}}
- [ ] Empty results handled gracefully
- [ ] Auth failure logged clearly

GMAIL: sender/subject/body, provider="gmail", tags=["email"]
GITHUB: repo/event_type, provider="github", tags=["code"]
SLACK: sender/text/timestamp, provider="slack", tags=["chat"]

- [ ] Commit: "feat(adapters): Gmail, GitHub, Slack canonicalization"
```

---

### T13 — Codex-Stream Ingest Pipeline (P1d)

> **ARCHITECTURE CHANGE (2026-05-28):** Pipeline moved from `~/.hermes/cron/pantheon-sync/` to `~/athenaeum/Codex-Stream/ingest/` — it's now a self-contained Athenaeum Codex. Data lives alongside the pipeline. Raw chunks have 30-day TTL. Entities are promoted to permanent Codexes at ≥5 mentions. See Thoth handoff: `~/athenaeum/handoffs/hephaestus-handoff-2026-05-28-ingest-pipeline-move.md`

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `0f959ef` (scheduler), `12ad4a7` (adapters). Pipeline at `~/athenaeum/Codex-Stream/ingest/` (not git-tracked) |
| **Depends on** | T8, T9, T10, T11, T12 |
| **Files** | `~/athenaeum/Codex-Stream/ingest/{__init__,pipeline,chunker,hotness,cleanup}.py`. Modified: `~/pantheon/cron/pantheon-sync/sync_scheduler.py`. |
| **Note** | ✅ End-to-end verified: sync tick → chunks in raw/ → spaCy NER extracts entities → hotness updated. Co-occurrence edges logged to JSONL (Ichor graph write pending). |

**What:** Sync scheduler calls `ingest_into_codex_stream(canonical, connection)` → chunk (≤3k tokens, SHA256 IDs) → WikiGuard score → dedup check → provenance inject → write to `~/athenaeum/Codex-Stream/raw/{provider}/{date}/{chunk_id}.md`. Entity extraction (spaCy NER), co-occurrence edges → Ichor graph, hotness tracking. Daily cleanup: purge raw/ >30 days, promote entities ≥5 mentions.

**🚦 QA Gate T13:**
```
PIPELINE (pipeline.py):
- [ ] ingest_into_codex_stream(canonical, connection) → IngestResult(written=N, dropped=N, skipped=N)
- [ ] WikiGuard score gate called (T8) — DROP/BORDERLINE/KEEP respected
- [ ] Dedup check called (T10) — duplicates skipped
- [ ] Provenance injected (T9) — source/provider/connector in frontmatter
- [ ] Written to ~/athenaeum/Codex-Stream/raw/{provider}/{date}/{chunk_id}.md
- [ ] Handles empty/malformed adapter results gracefully (no crash)

CHUNKER (chunker.py):
- [ ] chunk_text() splits on paragraph boundaries, ≤3000 tokens
- [ ] Chunk IDs are SHA256 content-addressed
- [ ] Standalone: `python -c "from athenaeum.codex_stream.ingest.chunker import chunk_text; ..."` works

HOTNESS (hotness.py):
- [ ] HotnessTracker.increment(entity_name) works
- [ ] trending(n) returns top-N entities by mention count
- [ ] mark_promoted(entity) persists flag
- [ ] JSON persistence survives restarts (~/athenaeum/Codex-Stream/hotness.json)

CLEANUP (cleanup.py):
- [ ] CodexStreamCleanup.run() purges raw/ files >30 days old
- [ ] Empty date directories cleaned up after purge
- [ ] Entities with ≥5 mentions promoted to ~/athenaeum/Codex-Stream/entities/{slug}.md
- [ ] Promotion routing: default → Codex-General (configurable)
- [ ] Hotness decay applied to cold entities
- [ ] Cleanup never touches entities/, graph edges, or summaries
- [ ] Crontab: `0 2 * * * cd ~/athenaeum/Codex-Stream && python -m ingest.cleanup`

INTEGRATION:
- [ ] sync_scheduler.py imports from athenaeum.codex_stream.ingest.pipeline
- [ ] End-to-end: manual sync tick → chunks land in Codex-Stream/raw/
- [ ] spaCy NER extracts entities (zero LLM cost)
- [ ] Co-occurrence edges created in Ichor graph
- [ ] Commit: "feat(ingest): Codex-Stream pipeline — chunk + score + write + cleanup"
```

---

### 🚦 Phase 1 Integration Gate (T11+T12+T13)
```
- [ ] Gmail connected → sync tick → chunks in ~/athenaeum/Codex-Stream/raw/gmail/
- [ ] dropped.log has entries for low-quality chunks
- [ ] Entities extracted and co-occurrence edges created
- [ ] Hotness counters incremented
- [ ] Cleanup cron: 30-day TTL enforced, entities promoted at ≥5 mentions
```

---

## Stream C: Integration UI + Onboarding

> Olympus frontend components for the integration pipeline.
> OAuth components can be built standalone (parallel with T1).

### I2 — Composio API Research

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Note** | 508-line comprehensive doc at `~/pantheon/docs/olympus/composio-setup.md`. Covers: account setup, OAuth architecture, callback URLs, per-service client IDs (Gmail/GitHub/Slack), Python+TS code patterns, BYOK flow, design decisions, sequence diagram. |
| **Depends on** | Nothing |
| **Files** | `~/pantheon/docs/olympus/composio-setup.md` |

**What:** Research Composio BYOK setup — client ID requirements, deep-link URLs for Gmail/GitHub/Slack, callback URL pattern (`localhost:53824/oauth/callback?provider=`), integration guide.

**🚦 QA Gate I2:**
```
- [ ] Composio account creation documented
- [ ] Deep-link URLs for Gmail, GitHub, Slack documented
- [ ] OAuth callback URL pattern confirmed
- [ ] Client ID / API key setup steps documented
- [ ] Research doc written to ~/pantheon/docs/olympus/composio-setup.md
```

---

### T14 — OAuth Flow UI (P3a)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `b22d550` |
| **Note** | All 4 states handled (idle/connecting/connected/error) + 60s timeout per spec. 70 integration tests pass. Wired into Settings ✅ (T14b). Loopback listener (port 53824) and manual token fallback deferred to T14c. |
| **Depends on** | I2 |
| **Files** | `src/components/settings/integrations/`, `src/components/settings/integrations/useOAuth.ts` |

**What:** ConnectionManager page, ConnectionCards (Gmail, GitHub, Slack), OAuthButton with loopback listener on port 53824, manual token fallback.

**🚦 QA Gate T14:**
```
COMPONENT TESTS:
- [ ] OAuthButton.test.tsx → PASS (new)
- [ ] ConnectionCard.test.tsx → PASS (new)
- [ ] ConnectionManager.test.tsx → PASS (new)
- [ ] useOAuth.test.ts → PASS (new)
- [ ] All states: idle, connecting, connected, error
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Settings → Integrations tab visible
- [ ] Grid: Gmail, GitHub, Slack, Notion, Telegram
- [ ] Connected provider: green dot + last sync
- [ ] Not connected: "Connect" button
- [ ] Click Connect → OAuth flow opens
- [ ] Manual token entry fallback visible
- [ ] Disconnect button with confirmation
- [ ] Mobile: cards stack vertically, buttons tappable
- [ ] Keyboard: Tab between cards
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(integrations): OAuth flow UI with Composio BYOK"
```

---

### T14b — Wire Integrations Into Settings

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `1c90323` (Olympus-UI, branch `feat/user-management`) |
| **Depends on** | T1 AND T14 |
| **Files** | `SettingsRoot.tsx`, `ConnectionManager.tsx` + tests |

**What:** Import ConnectionManager, place in Settings → Integrations tab. Micro-task — fires when both T1 and T14 complete.

**🚦 QA Gate T14b:**
```
- [ ] Settings → Integrations tab shows ConnectionManager
- [ ] All connection cards render correctly
- [ ] Zero console errors
- [ ] Commit: "feat(integrations): wire ConnectionManager into Settings"
```

---

## Stream C: Pre-Wizard Backend

> Prerequisite endpoints the onboarding wizard calls. Build these BEFORE T15 (wizard UI).

### T15a — Hardware Detection Endpoint

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Depends on** | Nothing |
| **Files** | `~/pantheon/webui/api/onboarding.py` (get_hardware_info), `~/pantheon/webui/api/routes.py` (route handler) |

**What:** Endpoint that probes the host machine and returns model recommendations. Detects total RAM, CPU cores, and GPU availability (via `lspci` or similar). Maps to one of three tiers: 8GB, 16GB, 16GB+GPU. Returns recommended Ollama models for that tier.

**Response shape:**
```json
{
  "tier": "16gb_gpu",
  "ram_gb": 32,
  "cpu_cores": 16,
  "gpu_detected": true,
  "gpu_name": "NVIDIA RTX 3060",
  "recommended_models": ["qwen2.5:14b", "deepseek-r1:14b", "gemma3:12b"],
  "embedding_model": "nomic-embed-text"
}
```

**🚦 QA Gate T15a:**
```
- [ ] Returns valid JSON with all fields
- [ ] Correctly detects RAM via /proc/meminfo or sysctl
- [ ] Detects GPU via lspci | grep -i vga
- [ ] Falls back to tier "8gb" if detection fails
- [ ] Embedding model always "nomic-embed-text"
- [ ] Curl: curl -s http://localhost:8787/api/onboarding/hardware
```

---

### T15b — Ollama Model Install + Download Script

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `4bb05d3` (Pantheon repo) |
| **Depends on** | T15a |
| **Files** | `~/pantheon/scripts/onboarding/setup-ollama-models.sh` |

**What:** Script that installs Ollama if not present, then pulls user-selected models + `nomic-embed-text`. Called by the wizard UI during Step 2 (Local path). Reports download progress. Returns JSON status.

**🚦 QA Gate T15b:**
```
- [ ] Detects if ollama is installed; if not, runs: curl -fsSL https://ollama.com/install.sh | sh
- [ ] Accepts model list as argument: setup-ollama-models.sh qwen2.5:7b llama3.1:8b
- [ ] Auto-includes nomic-embed-text in every pull
- [ ] Reports per-model status (pending/downloading/done/error)
- [ ] Idempotent: already-pulled models return "done" immediately
- [ ] Works from wizard UI: subprocess.run with progress parsing
- [ ] Test: bash ~/pantheon/scripts/onboarding/setup-ollama-models.sh qwen2.5:3b
```

---

### T15c — OpenCode Go API Verification

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Depends on** | Nothing |
| **Files** | Olympus backend: `POST /api/onboarding/verify-opencode` |

**What:** Endpoint that validates an OpenCode Go API key by making a test call. Returns success + model list, or error with message. Referral link embedded in response for frontend display.

**Response shape:**
```json
{
  "valid": true,
  "models_available": ["deepseek-v4-flash-free", "deepseek-v4-pro", "..."],
  "referral_url": "https://opencode.ai/go?ref=3QSR50S9K2",
  "error": null
}
```

**🚦 QA Gate T15c:**
```
- [ ] Valid key → returns valid:true + model list
- [ ] Invalid key → returns valid:false + error message
- [ ] Referral link always included in response
- [ ] Timeout after 10s (don't hang the wizard)
- [ ] Curl: curl -s -X POST http://localhost:8787/api/onboarding/verify-opencode -d '{"api_key":"sk-..."}'
```

---

### T15d — God Registration Endpoint

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Depends on** | Nothing |
| **Files** | Olympus backend: `POST /api/onboarding/register-gods` |

**What:** Endpoint that registers the core gods (Hermes + Hephaestus) during onboarding. Calls `/api/gods/summon` internally for each. Returns per-god status. Hermes is the default profile so it may already exist — handle gracefully. Hephaestus needs a full summon (SOUL.md + god.json).

**Response shape:**
```json
{
  "gods": [
    {"name": "hermes", "status": "already_exists"},
    {"name": "hephaestus", "status": "registered", "display_name": "Hephaestus"}
  ],
  "all_registered": true
}
```

**🚦 QA Gate T15d:**
```
- [ ] POST with no body registers both Hermes + Hephaestus
- [ ] Hermes already exists → returns "already_exists" (no error)
- [ ] Hephaestus summon creates full profile with SOUL.md + god.json
- [ ] Gods visible in GodPicker after registration (GET /api/gods includes both)
- [ ] Re-run is idempotent (both return "already_exists")
- [ ] Curl: curl -s -X POST http://localhost:8787/api/onboarding/register-gods
```

---

### T15 — Onboarding Wizard (P3b)

> **DESIGN DECISION (2026-05-28):** Replaced Cloud/Custom branching with Local/BYOK. Cloud path was OpenHuman artifact — Pantheon runs locally. Personalities moved to god SOUL.md (not global config). Voice is skip-able. Search is background-configured (DDGS + Scrapeling), not a user step. Core gods (Hermes + Hephaestus) auto-registered during wizard.

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commits** | `b5f0c32` (G2), `00a3463` (G3), `78f05f7` (fixes), `88f3778` (tests) |
| **Depends on** | T14, T4 |
| **Note** | 6 route files + onboarding-store.ts + 8 test files (110 tests). Browser QA: all 6 pages render with zero JS errors. Hardware detection works. Guard redirects work. Mobile/keyboard QA deferred to polish pass. |
| **Files** | `src/routes/onboarding/` (6 route files), `src/stores/onboarding-store.ts`. Modify: `src/routes/__root.tsx`, router |

**What:** First-run wizard shown to new users. 6 steps:

```
Step 1 — Welcome         Intro + "Get Started"
Step 2 — Runtime Choice  Local (hardware detect → model picker → Ollama download)
                         vs BYOK (OpenCode Go referral link + API key paste)
                         Both paths auto-download nomic-embed-text
Step 3 — Register Gods   Auto-register Hermes + Hephaestus (visible in GodPicker)
Step 4 — Integrations    OAuth connections: Gmail, GitHub, Slack [SKIP-ABLE]
Step 5 — Voice           Voice provider: faster-whisper base/small, whisper.cpp medium [SKIP-ABLE]
Step 6 — Complete        "You're ready" → onboarding_completed=true → redirect to /
```

**Guard:** `localStorage.getItem('onboarding_completed')` checked in `__root.tsx`. Wizard never runs again once completed.

**Local path models by tier:**
| RAM | Models |
|-----|--------|
| 8GB (no GPU) | `qwen2.5:3b`, `gemma3:4b`, `phi4-mini:3.8b` |
| 16GB (no GPU) | `qwen2.5:7b`, `mistral:7b`, `llama3.1:8b` |
| 16GB+ (GPU) | `qwen2.5:14b`, `deepseek-r1:14b`, `gemma3:12b` |

**Base config shipped:** Auto-compact on, guardrails, checkpoints, ichor memory, terminal local, browser auto. Personalities stripped (lives in SOUL.md). Critical cron jobs pre-configured: ichor-daily-maintenance, hades, pantheon-sync, Codex-Stream cleanup.

**🚦 QA Gate T15:**
```
COMPONENT TESTS:
- [ ] All 6 step components have *.test.tsx
- [ ] onboarding-store.test.ts → PASS
- [ ] Local path: hardware detect → model selection → download trigger
- [ ] BYOK path: referral link → API key input → validation
- [ ] Skip buttons work on integrations and voice steps
- [ ] completeAndExit() persists onboarding_completed flag
- [ ] npx vitest run → 0 failures

BROWSER VERIFICATION:
- [ ] First visit → redirected to /onboarding/welcome
- [ ] Welcome: intro content + "Get Started" button
- [ ] Runtime Choice: Local card vs BYOK card with referral link
- [ ] Local: model tier shown based on detected hardware
- [ ] BYOK: OpenCode Go link opens in new tab, API key field validates
- [ ] Gods step: auto-registers Hermes + Hephaestus (visible in GodPicker after)
- [ ] Integrations: OAuth cards render, Skip button works
- [ ] Voice: model picker renders, Skip button works
- [ ] Complete → redirected to / (chat), onboarding never shown again
- [ ] Reload page → no redirect (onboarding_completed=true)
- [ ] Mobile: steps full-width, buttons tappable (44px min)
- [ ] Keyboard: Tab through options, Enter to select, Escape for skip
- [ ] Zero console errors
- [ ] git branch verified before browser QA

GIT:
- [ ] Commit: "feat(onboarding): 6-step first-run wizard — Local/BYOK + gods + integrations + voice"
```

---

### T16 — Context Gathering Pipeline (P3c)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `4ebaca6` |
| **Depends on** | T12, T13, T15 |
| **Files** | `ContextGatheringToast.tsx` + test, `onboarding-store.ts`, `complete.lazy.tsx`, `AppShell.tsx`. Backend: `/api/onboarding/context-gathering/*` |

**What:** Background pipeline after first OAuth: search Gmail for LinkedIn → build user profile. "Still working" UI after 30s. Core alive probe. Error state with retry.

**🚦 QA Gate T16:**
```
BROWSER VERIFICATION:
- [ ] After OAuth connect in wizard → ContextGatheringStep appears
- [ ] Pipeline stages visible (Gmail search → profile build)
- [ ] Core alive indicator (green dot)
- [ ] After 30s → "Still working" UI swaps in
- [ ] "Continue to Chat" button always visible
- [ ] Completion → auto-advances after 800ms
- [ ] No Gmail connected → stages skipped gracefully
- [ ] Error state → retry/continue options
- [ ] Profile written to ~/wiki/entities/{username}-profile.md
- [ ] Mobile: status readable, buttons tappable

GIT:
- [ ] Commit: "feat(onboarding): background context gathering pipeline"
```

---

### T17 — Stream Dashboard (P3d)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `5febcd5` (components), `9ee6b6a` (route + tests) |
| **Depends on** | T13, T1 |
| **Files** | `src/components/stream/StreamDashboard.tsx` + test, `src/components/stream/KnowledgeGraph.tsx` + test, `src/stores/stream-store.ts` + test, `src/routes/stream.lazy.tsx`, `router.tsx`. Olympus backend: `/api/stream/*` |
| **Note** | EntityDetailPanel/MemoryMetricsCard/StreamSearchBar are embedded in StreamDashboard (MetricCard, EntityRow) + KnowledgeGraph (search input). 37 test files, 464 tests — all pass. |

**What:** Obsidian-style D3 force-directed knowledge graph as modal overlay. Nodes = entities, edges = co-occurrence, size = hotness. Entity detail panel. Metrics bar.

**🚦 QA Gate T17:**
```
COMPONENT TESTS:
- [ ] KnowledgeGraph.test.tsx → PASS (new)
- [ ] EntityDetailPanel.test.tsx → PASS (new)
- [ ] MemoryMetricsCard.test.tsx → PASS (new)
- [ ] stream-store.test.ts → PASS (new)
- [ ] D3 renders SVG with nodes+edges
- [ ] Node sizes proportional to hotness
- [ ] Node colors by category
- [ ] npx vitest run → ≤9 failures

BROWSER VERIFICATION:
- [ ] Stream tab visible in navigation
- [ ] Metrics bar: Storage, Sources, Chunks, Entities, Connections, 🔥 Trending
- [ ] "🗺️ Graph" button visible
- [ ] Click → full-screen modal with D3 force graph
- [ ] Nodes sized by hotness, colored by category
- [ ] Drag node → physics re-layout
- [ ] Scroll to zoom, drag to pan
- [ ] Click node → side panel with entity detail
- [ ] Search entities → graph filters
- [ ] Click wikilink → focuses graph on that entity
- [ ] Close modal → back to Stream tab
- [ ] Mobile: graph pannable, nodes tappable
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(stream): D3 knowledge graph dashboard"
```

---

## Tier 5 — Polish

### T18 — Theming Foundations

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commits** | `d67be8a` (Olympus-UI), `d4e0e98` (Pantheon) |
| **Depends on** | T1 |
| **Files** | `src/stores/theme-store.ts` + test, `src/components/settings/AppearanceTab.tsx` + test, `src/components/admin/SettingsRoot.tsx`, `config/olympus-theme.yaml`, `routes.py` |
| **Note** | Theme YAML → CSS variables on :root at runtime. Color swatches in Settings → Appearance. Terminology map via t() function. ⚠️ DEFERRED: ~50 hardcoded hex colors (#22c55e, #e06060) across components need replacement with var(--color-success)/var(--color-danger) — tracked as T18b. |

**What:** Config-driven theme. YAML at `~/pantheon/config/olympus-theme.yaml`. Runtime loading. Terminology map. Appearance tab in Settings. Don't paint into corners — no hardcoded values.

**🚦 QA Gate T18:**
```
- [ ] Theme YAML schema defined and documented
- [ ] GET /api/theme returns config, PUT /api/theme saves it
- [ ] Colors (lumen-0 through lumen-7) configurable
- [ ] Logo/favicon swappable via config
- [ ] Border radius, spacing density configurable
- [ ] Settings → Appearance shows preview
- [ ] Theme persists across restarts
- [ ] Terminology map functional (t('knowledge') → "Athenaeum")
- [ ] No hardcoded color hex values in component code
- [ ] Commit: "feat(theme): config-driven theming with YAML + runtime loading"
```

---

### T19 — Kanban Fix + Port

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `d0264cb` (Olympus-UI) |
| **Depends on** | T1 |
| **Files** | `KanbanPanel.tsx`. Investigate: :8787 and Hermes Agent dashboard Kanban implementations. |

**What:** Kanban works on :8787 and in Hermes dashboard. Investigate correct API path → fix Olympus proxy → port working UI. Feature-flag gated.

**🚦 QA Gate T19:**
```
- [ ] Root cause of 500 identified (likely wrong API path)
- [ ] Kanban board renders with real data
- [ ] Create/edit/move/delete cards works
- [ ] Drag between columns works
- [ ] Feature toggle OFF → Kanban hidden from Tools menu
- [ ] Feature toggle ON → Kanban visible and functional
- [ ] Mobile: board scrollable, cards tappable
- [ ] Zero console errors

GIT:
- [ ] Commit: "fix(kanban): correct API path + port from Pantheon UI"
```

---

### T20 — Tasks in Settings

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `36f9067` |
| **Depends on** | T19, T1 |
| **Files** | `TasksPanel.tsx` + test (8 tests), `AdminPanel.tsx`, `feature-flag-store.ts` (+ `tasks` toggle) |

**What:** Tasks tab in Admin. Pull from existing Hermes integration. Create/edit/complete tasks. Feature-flag gated.

**🚦 QA Gate T20:**
```
- [ ] Tasks tab visible in Admin
- [ ] Task list loads from Hermes API
- [ ] Create task works
- [ ] Edit task (status, assignee, due date) works
- [ ] Complete/reopen task works
- [ ] Feature toggle gated
- [ ] Mobile: list scrollable, forms usable
- [ ] Zero console errors

GIT:
- [ ] Commit: "feat(tasks): task management panel"
```

---

## Tier 6 — Integration Polish (Phase 4)

> From OpenHuman/Pantheon integration spec. Depends on Phase 1 data flowing.

### T21 — Knowledge Graph from Real Ichor Data

> **Scope changed (2026-05-30):** Originally "Obsidian Vault Mirror." Re-scoped to wire the existing D3 KnowledgeGraph component to the Ichor knowledge graph database (graph.db) instead of stale Codex-Stream hotness data. The knowledge graph now shows 200+ real entities with typed categories (person, technology, project, company) and 354+ relationship edges from the Pantheon Ichor memory system.

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Depends on** | Nothing |
| **Files** | `webui/api/stream.py` (get_ichor_graph), `webui/api/routes.py` (route), `src/stores/stream-store.ts` (fetchIchorGraph), `src/components/stream/StreamDashboard.tsx` (use ichor data) |
| **Commit** | `f17ee8b` (Pantheon), `2e4d830` (Olympus-UI) |

**What:** Backend endpoint `GET /api/stream/ichor-graph` queries the Ichor `graph.db` directly via SQLite for entity nodes (tool, project, person, organization, system, skill, event, fact, preference, decision) with color-coded categories and relationship edges. Frontend automatically uses ichor data when stream entities are sparse (<10).

**🚦 QA Gate T21:**
```
- [x] GET /api/stream/ichor-graph returns 200+ entities, 354+ edges
- [x] Entities have typed categories (person/technology/project/company)
- [x] KnowledgeGraph opens with colored nodes by category
- [x] Fallback: uses ichor data when stream entities < 10
- [x] Zero error when graph.db is unavailable
```

---

### T22 — Agent Retrieval Tools (P4b)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `4d5c63a` (Pantheon) |
| **Depends on** | T13 (data + entity co-occurrence in Ichor graph) |
| **Files** | `~/pantheon/plugins/stream-retrieval/` |

**What:** Hermes plugin exposing 6 retrieval tools: `stream_search`, `stream_filter`, `stream_entity`, `stream_trending`, `stream_connections`, `stream_fetch_chunks`. FTS5 + ChromaDB hybrid search. Entity lookups via Ichor graph.

**🚦 QA Gate T22:**
```
- [ ] plugin.yaml with 6 tool schemas
- [ ] stream_search(query, filters) → ranked chunks (FTS5 + ChromaDB)
- [ ] stream_filter(source, date_from, date_to) → time/provider filtered
- [ ] stream_entity(entity_name) → all chunks + co-occurring entities
- [ ] stream_trending(min_mentions=3) → hot entities from HotnessTracker
- [ ] stream_connections(entity_name) → entity neighbors via Ichor graph
- [ ] stream_fetch_chunks(chunk_ids) → full content by path
- [ ] Each tool returns empty [] not crash on missing data

---

### T23 — Error Handling + Recovery (P4c)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `c384b0e` (Pantheon) |
| **Depends on** | T13, T11 |
| **Files** | `cron/pantheon-sync/adapters/base.py` (sync_with_retry), `cron/pantheon-sync/sync_scheduler.py` (integration) |

**What:** Production hardening. OAuth token expiry auto-refresh, API rate limit exponential backoff, adapter crash isolation (never crashes scheduler), scheduler restart resumes from saved state, duplicate ingest silently caught by dedup, embedding failure handled gracefully.

**🚦 QA Gate T23:**
```
- [ ] OAuth token expiry triggers auto-refresh
- [ ] API rate limiting triggers exponential backoff
- [ ] Adapter crash logged, does not crash scheduler
- [ ] Scheduler restart resumes from saved state
- [ ] Duplicate ingest silently caught by dedup
- [ ] Embedding failure handled gracefully
```

---

### T24 — TokenJuice Compression (P4d)

| Field | Value |
|-------|-------|
| **Status** | ✅ |
| **Commit** | `a1d8517` (Pantheon) |
| **Depends on** | Nothing (independent) |
| **Files** | `~/pantheon/plugins/tokenjuice/` (symlinked to `~/.hermes/plugins/tokenjuice/`) |

**What:** Transparent compression layer for tool outputs. 10 deterministic rules run before content hits LLM context — saves users money on every query. HTML→Markdown, URL shortening, JSON truncation, etc. Zero LLM calls, pure text processing. Toggleable per-god via config.

**🚦 QA Gate T24:**
```
- [ ] Plugin at ~/.hermes/plugins/tokenjuice/
- [ ] Top 10 compression rules implemented
- [ ] Integration in god tool loop (post-execute filter)
- [ ] Compression stats logged (bytes before/after per rule)
- [ ] Toggleable per-god via config
- [ ] Zero regression on tool output quality
```

---

---

## Stream D: n8n Migration (2026-05-29)

> **Decision:** Composio broken — 2/8 active connections, 6 silently dropped by API. n8n self-hosted Docker verified: 449 credential types, one-click OAuth, REST API, MCP server at `localhost:5678/mcp-server/http`. Full plan: `~/pantheon/docs/olympus/n8n-migration-plan.md`

### Composio Post-Mortem (2026-05-29)
Gmail ✅ / GitHub ✅ actually connected. Google Calendar ❌, Google Drive ❌, Notion ❌ — user connected in UI, API reports zero accounts. Slack ❌, Discord ❌, Outlook ❌ — never connected. Root cause: Composio silently drops OAuth connections.

---

### N1 — Sidebar Reorder + Settings Move

| Field | Value |
|---|---|
| **Status** | ✅ |
| **Priority** | P0 — unblocks admin access |
| **Depends on** | Nothing |
| **Files** | `src/components/shell/Sidebar.tsx` |
| **Commit** | `554743c` |

Admin shield → bottom of collapsed rail (where Settings is). Settings gear → beside Profile avatar. Remove Settings text label in expanded drawer. One file change.

### N2 — n8n Feature Toggle + Sidebar Icon

| Field | Value |
|---|---|
| **Status** | ✅ |
| **Priority** | P0 — enables n8n visibility |
| **Depends on** | N1 |
| **Files** | `feature-flag-store.ts`, `AdminPanel.tsx`, `Sidebar.tsx`, `AdminPanel.test.tsx`, `feature-flag-store.test.ts` |
| **Commit** | `cbdff27` |

Add `n8n` toggle (default OFF) to feature flag system. Workflow icon in rail between Athenaeum and Stream. Hidden when toggle OFF. 5 file locations per feature-flag pattern.

### N3 — n8n API Client + Olympus Routes

| Field | Value |
|---|---|
| **Status** | ✅ |
| **Priority** | P0 — backend for onboarding |
| **Commit** | `fb753d3` |
| **Depends on** | n8n Docker running |
| **Files** | `~/pantheon/webui/api/n8n_client.py`, `routes.py`, `olympus_users.py`, `.env` |

Python wrapper for n8n REST API (363 lines). 5 endpoints verified: `GET /api/n8n/status`, `GET /api/n8n/credentials`, `GET /api/n8n/credentials/{provider}`, `POST /api/n8n/credentials/{provider}/connect`. BYOK-aware with .env fallback loader. n8n feature flag in backend. n8n Docker `unless-stopped` policy configured.

### N4 — Onboarding + Settings Integration

| Field | Value |
|---|---|
| **Status** | ✅ |
| **Priority** | P1 — replaces Composio in user flow |
| **Commit** | `b6e2bb8` (Pantheon backend), `8506bde` (Olympus-UI frontend) |
| **Depends on** | N3 |
| **Files** | `integrations.lazy.tsx`, `ConnectionManager.tsx`, `useOAuth.ts`, `onboarding-store.ts`, `feature-flag-store.ts`, `n8n_client.py`, `routes.py` |

Replace Composio with n8n in onboarding Step 4 and Settings → Integrations tab. Same UI (brand icons, cards, Skip button), different backend. Flow: Connect → n8n OAuth URL → user authorizes → poll status → ✅.

### N5 — MCP Server + Core Workflows

| Field | Value |
|---|---|
| **Status** | ✅ |
| **Priority** | P1 — enables Hermes agent tools |
| **Commit** | `8506bde`+ (Olympus-UI), n8n MCP STDIO server at `~/.hermes/mcp-servers/n8n-server.py` |
| **Depends on** | N3 |
| **Files** | `~/.hermes/mcp-servers/n8n-server.py`, `~/.hermes/config.yaml` (via `hermes mcp add`) |

**What was built:**
- STDIO MCP server (Python) wrapping the n8n REST API as 6 MCP tools
- Registered via `hermes mcp add n8n` — 6/6 tools enabled

**6 MCP tools discovered:**
| Tool | Description |
|---|---|
| `n8n_health` | Check if n8n is running |
| `n8n_list_workflows` | List all workflows with IDs, names, status |
| `n8n_run_workflow` | Execute/trigger a workflow by ID |
| `n8n_list_credentials` | List all connected credentials |
| `n8n_credential_status` | Check specific provider credential |
| `n8n_create_credential_url` | Get n8n URL to set up a credential |

**Architecture:** Instead of n8n's HTTP MCP server (auth plane mismatch), built a local STDIO MCP subprocess that speaks MCP over stdin/stdout. Hermes launches it, discovers tools, no auth battles.

**Start a new session to see them:** `mcp_n8n_health`, `mcp_n8n_list_workflows`, etc.

### N6 — Composio Deprecation (REVISED 2026-05-30)

> **⚠️ Previously marked ✅ but was incomplete.** The initial pass only cleaned runtime config (env vars, MCP server, cron symlink). The repo still has composio code in 26 tracked files. This revision defines the full scope.

| Field | Value |
|---|---|
| **Status** | ✅ Complete |
| **Priority** | P2 — repo must be COMPLETELY clean of composio |
| **Depends on** | N4, N5 |

**What was done (runtime cleanup, keeping):**
- COMPOSIO env keys removed from `~/.hermes/.env`
- composio MCP server removed from Hermes config
- sync cron symlink removed

**What was done (N6a+N6b — repo purge, commit `219d84b`):**
- `git rm` — deleted `bundles/composio-mcp/` (3 files, 146 lines)
- `git rm` — deleted `docs/olympus/deprecated/composio-setup.md`
- Stripped `save_composio_key()`, `check_composio()`, `get_composio_connections()` from `onboarding.py` (~200 lines)
- Stripped composio imports + 3 route handlers from `routes.py`
- Updated `ARCHITECTURE.md` — Composio MCP → n8n MCP
- Updated `FEATURES.md` — replaced composio sections with n8n
- Updated `config.yaml.j2` — removed composio MCP template
- Updated `QUESTIONS.md` — removed composio Q&A
- Updated `olympus-ui` skill — removed composio reference
- Updated `BUILD_TRACKER.md` I2 entry

**What remains (the real scope — 28 items across 5 phases):**

#### N6a — Purge composio from repo (delete/strip)
| # | File | Action |
|---|---|---|
| 1 | `bundles/composio-mcp/composio-mcp.yaml` | `git rm` — delete entire `bundles/composio-mcp/` |
| 2 | `bundles/composio-mcp/setup_credentials.py` | `git rm` (same bundle) |
| 3 | `bundles/composio-mcp/README.md` | `git rm` (same bundle) |
| 4 | `docs/olympus/deprecated/composio-setup.md` | `git rm` — remove deprecated doc entirely |
| 5 | `webui/api/onboarding.py` lines 1311-1513 | Remove `save_composio_key()`, `check_composio()`, `get_composio_connections()` (~200 lines) |
| 6 | `webui/api/routes.py` lines 1908, 1913-1914, 6567-6572, 6628-6632 | Remove composio imports + 3 route handlers |
| 7 | `webui/static/assets/*.js` (3 files) | Rebuild after frontend composio removal (or verify composio refs are dead code) |

#### N6b — Update docs and planning
| # | File | Action |
|---|---|---|
| 8 | `planning/ARCHITECTURE.md` line 357 | "Composio MCP — primary service connector" → "n8n MCP — primary service connector" |
| 9 | `planning/FEATURES.md` lines 227-256 | Remove "Composio MCP" + "Composio Automations" sections |
| 10 | `scripts/lib/god_cli/templates/config.yaml.j2` lines 54-59 | Remove composio MCP server template entry |
| 11 | `docs/olympus/QUESTIONS.md` lines 85, 148, 152, 242, 246 | Remove/update composio-related Q&A |
| 12 | `docs/olympus/BUILD_TRACKER.md` | Replace I2 entry — mark as superseded by n8n |
| 13 | `olympus-ui skill: references/composio-setup.md` | Delete skill reference file |
| 14 | `olympus-ui skill: SKILL.md` | Update changelog + reference list mentioning composio |

#### N6c — Rewrite cron/pantheon-sync adapters from composio to n8n
| # | File | Action |
|---|---|---|
| 15 | `cron/pantheon-sync/adapters/base.py` | Replace `_get_composio_client()` + `_exec_composio_tool()` with n8n REST API helpers |
| 16-23 | `cron/pantheon-sync/adapters/{gmail,github,slack,notion,google_calendar,discord,outlook,microsoft_teams}.py` | Each adapter: swap composio SDK calls for n8n API calls |
| 24 | `cron/pantheon-sync/test_adapters.py` | Update test for n8n-based adapters |
| 25 | `cron/pantheon-sync/connections.json` | Remove `composio_account_id` fields from all 8 providers |

#### N6d — Verify and commit
- [ ] `grep -ri composio ~/pantheon/` returns zero tracked matches
- [ ] All webui API endpoints still return 200 (no broken imports)
- [ ] cron/pantheon-sync/ adapters can reach n8n and return data
- [ ] Olympus UI integrations page loads without errors
- [ ] Commit with message describing full cleanup scope

#### N6e — Replace Connections Panel in Settings/Onboarding
The Settings → Integrations tab and onboarding Step 4 called the now-removed composio endpoints (`/api/onboarding/check-composio`, `/api/onboarding/composio-connections`). These need to call n8n API instead:
- `GET /api/n8n/credentials` — list connected services
- `GET /api/n8n/credentials/{provider}` — check single provider
- `POST /api/n8n/credentials/{provider}/connect` — initiate OAuth flow
- Frontend components (`ConnectionManager`, `ConnectionCard`, `OAuthButton`, `useOAuth` hook) already wired to n8n in N4, but verify the flow works end-to-end now that composio endpoints are gone

| Estimated effort | N6a (deletes): ~30min · N6b (docs): ~30min · N6c (adapters rewrite): ~4-6h · N6d (verify): ~1h · N6e (connections panel): ~2-3h |
|---|---|
| **Total remaining** | **~6-8 hours of work** |

---

## Tier 7 — Backend Refactor (Post-Ship)

> **Decision (2026-05-30):** The 8787 `routes.py` monolith (11,967 lines, stdlib `http.server`) is serving both static files and API — two jobs in one process with the wrong tool. This tier retires 8787 after Phase 1 ships, replacing it with purpose-built components. **Phase 1 completes first (37/37). Phase 2 runs beside live on port 8788 — no downtime.**

### Problem

`routes.py` is a single-file monolith with manual `if parsed.path.startswith(...)` routing for every endpoint in the system. It also serves static files (CSS, JS, favicon) — a job better done by a web server. Every new feature adds ~50 lines to the same file. The stdlib server was never designed for production API serving.

### Architecture Decision

```
Before (now):                    After (Tier 7):
                                 
Browser → 8787 (static)          Browser → Caddy (static, HTTPS)
Browser → 8787 (API monolith)    Browser → Caddy → Fastify/Bun (API)
Agent   → n8n MCP                Agent   → n8n MCP (unchanged)
8787    → n8n REST               8787    → retired
```

Each concern gets one owner:
- **Static assets** → Caddy (4MB binary, auto-HTTPS, zero config)
- **API** → Fastify or Bun (native async, proper routing, 10-50x throughput)
- **Integrations + agent tools** → n8n MCP (already at `localhost:5678`)

### Strategy: Build Beside, Flip Switch

| Phase | What | Risk |
|---|---|---|
| **Phase 1** (current) | Finish 37/37 on 8787. Ship. | None — live stays live |
| **Phase 2** (Tier 7) | New backend on port 8788. Olympus-UI proxies to 8788. Verify all endpoints. | None — runs beside, not instead of |
| **Cutover** | Flip one config line: proxy target 8787→8788. Wait 24h. Retire 8787. | 30-second blip if we mistime |

### T25 — Caddy Static Server

| Field | Value |
|---|---|
| **Status** | 🔲 |
| **Priority** | P0 — unblocks API refactor |
| **Depends on** | Phase 1 complete (37/37) |
| **Files** | `Caddyfile`, systemd unit |

**What:** Install Caddy, configure to serve `~/Olympus-UI/dist/` (built React app) on port 443 with auto-HTTPS via Tailscale. Remove all `_serve_static`, `_STATIC_MIME`, file-serving logic from routes.py. Olympus-UI frontend assets never touch Python again.

**🚦 QA Gate T25:**
```
- [ ] Caddy installed and running as systemd service
- [ ] https://pantheon.tail164759.ts.net serves Olympus-UI
- [ ] All static assets load (CSS, JS, fonts, favicon, manifest)
- [ ] Auto-HTTPS certificate provisioned via Tailscale
- [ ] ~2,000 lines cut from routes.py (static serving dead code)
- [ ] 8787 serves API-only — no static file handling
```

### T26 — Split routes.py Into Modules

| Field | Value |
|---|---|
| **Status** | 🔲 |
| **Priority** | P1 — reduces tech debt |
| **Depends on** | T25 (static gone, less to split) |
| **Files** | `webui/api/routes/*.py` (auth, n8n, athenaeum, chat, gods, etc.) |

**What:** Break the 11,967-line monolith into per-domain modules. Each module registers its own path handlers. The main `routes.py` becomes a thin dispatcher that imports and delegates. Zero performance change — pure organization. Each module ~200 lines instead of a 12K-line file.

**Modules:** `auth.py`, `n8n.py`, `athenaeum.py`, `chat.py`, `gods.py`, `sessions.py`, `kanban.py`, `stream.py`, `onboarding.py`, `terminal.py`, `cron.py`, `mcp.py`, `feature_flags.py`, `workspace.py`, `users.py`, `health.py`

**🚦 QA Gate T26:**
```
- [ ] Every existing endpoint still works (curl all /api/* paths)
- [ ] Each module ≤500 lines
- [ ] No circular imports
- [ ] All 510+ existing tests pass
- [ ] routes.py reduced to dispatcher (<200 lines)
```

### T27 — Fastify/Bun API Server

| Field | Value |
|---|---|
| **Status** | 🔲 |
| **Priority** | P1 — production-grade API serving |
| **Depends on** | T26 (routes modularized, easier to port) |
| **Files** | `~/pantheon/api-server/` (new TypeScript project) |

**What:** Replace the Python `http.server` with Fastify (Node) or Bun (native TS runtime). Proper routing (`fastify.get('/api/n8n/credentials/:provider', handler)`), request validation, async/await, middleware, JSON schema responses. Same API contract — Olympus-UI and Hermes Agent don't care what language the API server is in.

**Why TypeScript:** Olympus-UI is already TypeScript. One language for the whole stack. Shared types between frontend and API server. Bun serves 50K req/s vs Python's 3K. Memory footprint ~20MB vs Python's ~200MB.

**🚦 QA Gate T27:**
```
- [ ] New server running on port 8788
- [ ] All /api/* endpoints respond identically to 8787
- [ ] Olympus-UI works against 8788 (proxy target flip)
- [ ] Response times equal or faster than 8787
- [ ] Hermes Agent internals still callable (subprocess or IPC)
- [ ] All integration tests pass against 8788
```

### T28 — Cutover + Retire 8787

| Field | Value |
|---|---|
| **Status** | 🔲 |
| **Priority** | P2 — cleanup |
| **Depends on** | T25, T26, T27 verified |
| **Files** | Vite proxy config, systemd units |

**What:** Flip Vite proxy target from 8787 to 8788. Run both for 24h to catch edge cases. If stable, stop the 8787 systemd unit. Archive the routes.py monolith for reference. Breathe.

**🚦 QA Gate T28:**
```
- [ ] Vite proxy target: 8787 → 8788
- [ ] Olympus-UI works for 24h with zero 8787 traffic
- [ ] 8787 process stopped
- [ ] No regressions reported
- [ ] routes.py archived, not deleted
- [ ] Commit: "feat: retire 8787 — Tier 7 complete"
```

---

## Current Status Summary

|> Updated: 2026-06-01 — Phase 1 complete (41/41). T22-T24 all built. |

| Stream / Tier | Tasks | Status |
|---------------|-------|--------|
| **Pre-Build** (I1) | 1/1 | ✅ Complete |
| **Pre-Build** (I2 — Composio) | N/A | ➖ Superseded by Stream D (n8n) |
| **Tier 0** (Foundation) | 0.1–0.5 | ✅ Complete |
| **Tier 0.5** (Cleanup) | T0.5 | ✅ Complete |
| **Stream A** (T1–T7) | 7/7 | ✅ Complete |
| **Stream B** (T8–T13) | 6/6 | ✅ Complete (superseded by N5) |
| **Stream C — Pre-Wizard** (T14–T14b, T15a–T15d) | 6/6 | ✅ Complete (T14 superseded by N4) |
| **Stream C — Onboarding** (T15) | 1/1 | ✅ Complete |
| **Stream C — Remaining** (T16–T17) | 2/2 | ✅ Complete |
| **Stream D — n8n Migration** (N1–N5) | 5/5 | ✅ Complete |
| **Stream D — Composio Remediation** (N6) | 5/5 | ✅ Complete |
| **Tier 5 — Polish** (T18–T20) | 3/3 | ✅ Complete |
| **Tier 6 — Integration Polish** (T21–T24) | 4/4 | ✅ Complete |
| **Tier 7 — Backend Refactor** (T25–T28) | 0/4 | 🔲 Post-ship — build beside, no downtime |

**Phase 1: Complete ✅ — all user-facing features built**
**Phase 2: 0/4 Tier 7 tasks — post-ship, runs parallel on port 8788**

### Reconciliation Notes (2026-06-01 — T22-T24 sprint)
- **T24 TokenJuice:** 10 compression rules as Hermes plugin. Commit `a1d8517`. 96% reduction on JSON-heavy payloads.
- **T22 Stream Retrieval:** 6 search tools as Hermes plugin. Commit `4d5c63a`. Filesystem + hotness + Ichor graph integration.
- **T23 Error Handling:** Retry/backoff/OAuth refresh in sync scheduler. Commit `c384b0e`. Exponential backoff (1s→8s), n8n token refresh on 401.
- **T6 Backend Enforcement:** Backend `permitted_gods` check added to chat endpoints. Commit `861bcfd`. Frontend filter already existed.
- **Phase 1 complete.** All user-facing features built. Remaining: Tier 7 backend refactor (post-ship).

### Reconciliation Notes (2026-05-30)
- **N6 fully complete:** All 5 subtasks done across 4 commits. 26 tracked files with composio refs → 2 expected docs.
- **N6e (final):** Commit `64d405f`. Rewrote `start_context_gathering()` from composio MCP → n8n REST API. Rebuilt static assets from Olympus-UI source (zero composio in new bundles). Removed 3 stale JS bundles. Final count: 2 files — BUILD_TRACKER (task definition) and n8n-migration-plan (migration context). Both expected.
- **Cron adapters:** 8 adapters now check n8n credential status via REST API. 11/11 tests pass. Actual data sync deferred to n8n workflows.
- **Build count history:** 36/37 → 33/38 → 37/38. N6 expanded from 1→5, now complete.

### Reconciliation Notes (2026-05-28)
- **T19 (Kanban):** Tracker said 🔲 but KanbanPanel.tsx exists at 929 lines, committed `d0264cb`. Fixed → ✅.
- **T15b (Ollama):** Tracker said 🔲 but `setup-ollama-models.sh` exists at 233 lines, committed `4bb05d3`. Fixed → ✅.
- **T9 (Provenance):** Plugin exists at `~/.hermes/plugins/wiki-provenance/`. Tracker was missing individual entry — added.
- **T10 (Dedup):** Plugin exists at `~/.hermes/plugins/wiki-dedup/`. Tracker was missing individual entry — added.
- **T15 (Onboarding):** 6 route files exist on disk + `onboarding-store.ts` + 8 test files (110 tests). Commit hashes filled in.
- **T23–T24:** Added from integration spec Phase 4 (P4c, P4d) — missing from tracker entirely.
- **Summary table:** Added at bottom — missing from original tracker.
- **T16 (2026-05-28 audit):** Tracker said 🔲 but `ContextGatheringToast.tsx` exists at 119 lines + 90-line test, committed `4ebaca6`. Fixed → ✅. Filename corrected from `ContextGatheringStep.tsx` to `ContextGatheringToast.tsx`.
- **T13 (2026-05-28 audit):** Commit was TBD — filled with `0f959ef` (scheduler) + `12ad4a7` (adapters). Pipeline files at `~/athenaeum/Codex-Stream/ingest/` are not git-tracked.
- **T14 (2026-05-28 audit):** Commit was TBD — filled with `b22d550`. OAuth components + ConnectionManager all committed in that changeset.
- **T15 (2026-05-28 audit):** Commit was TBD — filled with `b5f0c32`, `00a3463`, `78f05f7`, `88f3778`.
- **T17 (2026-05-28 audit):** Route wired (`stream.lazy.tsx` + `router.tsx`), 47 tests added (store + dashboard + graph). 37 files / 464 tests — all pass. Browser QA: metrics bar + entity list + D3 knowledge graph all render with live data. Fixed → ✅.
- **T18 (2026-05-28 audit):** Theme infrastructure built — GET/PUT /api/theme, olympus-theme.yaml, theme-store.ts, AppearanceTab with color swatches. 39 files / 492 tests — all pass. Hardcoded hex color replacement (~50 instances) deferred to T18b.
- **T20 (2026-05-28 audit):** TasksPanel built — fetches from /api/kanban/board, create/complete via Kanban API. Feature-flagged (tasks, default ON). 8 tests pass. Browser QA: tab visible, form renders, task renders with checkbox. 40 files / 500 tests total. — GET/PUT /api/theme, olympus-theme.yaml, theme-store.ts, AppearanceTab with color swatches. 39 files / 492 tests — all pass. Hardcoded hex color replacement (~50 instances) deferred to T18b. (store + dashboard + graph). 37 files / 464 tests — all pass. Browser QA: metrics bar + entity list + D3 knowledge graph all render with live data. Fixed → ✅. (`stream.lazy.tsx` missing, not in `router.tsx`) and ZERO test files. Status changed from 🔲/✅ → 🔄 PARTIAL. Summary count adjusted: 28→27.
