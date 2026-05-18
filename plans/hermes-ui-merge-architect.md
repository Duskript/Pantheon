# Pantheon × Hermes UI — Architecture Plan

> ARCHITECT phase deliverable. Based on signed DISCOVERY brief.
> Date: 2026-05-17

---

## ADR-1: Branch Strategy

**Decision:** Fork Pantheon WebUI repo → branch `feat/hermes-ui-retheme` from `main`.

```
GitHub: Duskript/Pantheon
  main              → current production (unchanged)
  feat/hermes-ui-retheme → the merge branch (this project)
```

**Rationale:**
- Pantheon WebUI repo (`Duskript/Pantheon`) already has the full contrib/CI/release pipeline and 4,810 tests
- Working directory `~/pantheon/webui/` is a subdirectory of the repo root `~/pantheon/`
- The branch never touches `main` until we're ready, so the live server on port `:8787` is unaffected during development
- Hermes UI (pyrate-llama/hermes-ui) becomes an upstream we can pull from for updates

**File placement:**
```
~/pantheon/                          ← repo root (Pantheon.git)
├── webui/                           ← our working directory
│   ├── server.py                    ← KEEP (Pantheon's thin shell)
│   ├── api/                         ← KEEP all 37 modules
│   │   ├── soul_forge.py            ← RENAMED from forge.py
│   │   ├── boons.py                 ← KEEP
│   │   └── ...
│   ├── hermes-ui.html               ← NEW from pyrate-llama (adapted)
│   ├── static/                      ← REPLACED by hermes-ui.html
│   │   └── (old vanilla JS → removed)
│   ├── tests/                       ← KEEP (4,810 tests still pass)
│   ├── assets/                      ← NEW from hermes-ui (avatars, wordmark)
│   └── Dockerfile, docker-compose.yml, etc. ← KEEP
├── shared/
├── data/
└── plans/
    └── hermes-ui-merge-*.md         ← planning docs
```

**What hermes-ui files to bring in:**
- `hermes-ui.html` — the React app (will be heavily adapted)
- `serve_lite.py` — reference only (we keep Pantheon's backend)
- `assets/` — avatars, wordmark
- `CLAUDE.md` — for agent context (merge with Pantheon's)
- `LICENSE` — review for compatibility

**What NOT to bring:**
- `serve.py` — deprecated shim
- `serve_lite.py` — not used (Pantheon backend serves instead)
- `screenshots/` — dev artifacts
- `filler-bg.png` — 4MB, not needed with Pantheon's own design

---

## ADR-2: Server Architecture

**Decision:** Pantheon's existing `server.py` + `api/routes.py` serves the hermes-ui.html frontend. No dual-server mode.

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│   Browser    │────▶│  server.py       │────▶│  Hermes Agent    │
│  React 18    │     │  port 8787       │     │  port 8642       │
│  hermes-ui   │◀────│  (Pantheon API)  │◀────│  (WebAPI)        │
│  single-file │     │                  │     │                  │
└──────────────┘     └─────────────────┘     └──────────────────┘
                          │
                          ├── api/routes.py (all endpoints)
                          ├── api/boons.py
                          ├── api/god_runtime.py
                          └── ...35 more modules
```

**Rationale:**
- Pantheon's backend has ALL endpoints already — 120+ across 37 modules
- hermes-ui.html is a frontend-only React app — it just makes fetch() calls to whatever backend serves it
- `server.py` already serves static files and proxies to Hermes Agent
- Zero new infrastructure, zero new ports, zero new processes
- All 4,810 tests still pass because the backend code doesn't change

**The ONLY code change on the backend:**
1. `api/forge.py` → `api/soul_forge.py` + update import in `routes.py`
2. `api/updates.py` — change remote to Pantheon GitHub
3. Remove/deprecate `api/connectors.py` + `api/oauth.py` routes from `routes.py`

---

## ADR-3: Frontend Architecture

**Decision:** Single-file React 18 app (adapted `hermes-ui.html`), all new Pantheon components added as functions in the same file. No build step, no bundler.

**Rationale:**
- hermes-ui is already 618KB single-file — the pattern works
- Babel standalone compiles JSX in the browser — zero build infra
- Adding new React components is trivial (just append functions)
- Avoids a multi-file/src/build-tool migration that would block everything
- If the file grows past ~800KB, we can split into multiple HTML files loaded via `<script>` tags later

**Component architecture within hermes-ui.html:**

```
App (root component)
│
├── Navigation/Sidebar
│   ├── GodRail                     ← NEW: sidebar gods with status dots
│   ├── NavItems                    ← EXISTING
│   └── ThemeMenu                   ← EXISTING (extend themes)
│
├── Main Content Area
│   ├── ChatView                    ← EXISTING (rename "Communion")
│   ├── DashboardView               ← EXISTING (add god statuses)
│   ├── ForgeProjectsView           ← RENAMED from SpacesView
│   ├── FilesView                   ← EXISTING (rename "Forge Files")
│   ├── AthenaeumView               ← NEW: codex tree + file viewer
│   ├── AthenaeumSearchView         ← NEW: semantic search
│   ├── GodManagementView           ← NEW: god CRUD list
│   ├── GodDetailCard               ← NEW: expanded god modal
│   ├── ForgeWizardView             ← NEW: Hephaestus interview
│   ├── SummonView                  ← NEW: GitHub browser
│   ├── ProfilesView                ← NEW: sub-agent/minion profiles
│   ├── MemoryView                  ← EXISTING
│   ├── SkillsView                  ← EXISTING
│   ├── InsightsView                ← NEW: usage stats
│   └── DelegationChatView          ← EXISTING
│
├── Panels / Modals
│   ├── TerminalPanel               ← EXISTING
│   │   ├── Logs tab                ← Errors / Web UI / All (keep)
│   │   └── Boons tab               ← RENAMED from Artifacts tab
│   ├── SettingsModal               ← EXISTING (add Pantheon sections)
│   ├── MCPBrowserModal             ← EXISTING (add catalog)
│   ├── HealthView                  ← EXISTING (add VPS metrics)
│   ├── NotificationsBell           ← NEW: bell + dropdown
│   ├── SearchModal                 ← EXISTING (add athenaeum search)
│   ├── ShortcutsModal              ← EXISTING
│   └── GatewayStatusView           ← NEW: connection indicators
│
├── Composer
│   ├── GodProfileChip              ← NEW: active god with icon/name
│   ├── PromoteToBoonButton         ← NEW: 📜 button on messages
│   └── Composer                    ← EXISTING
│
└── Other
    ├── OnboardingWizard            ← NEW: 5-step flow
    ├── GodGlowStyles               ← NEW: CSS per-god glow
    ├── ThemeMenu                   ← EXISTING (extend)
    └── PantheonThemeIntegration    ← NEW: wire PantheonTheme SDK
```

---

## ADR-4: API Integration Map

**Decision:** All hermes-ui frontend `fetch()` calls get rerouted to Pantheon backend endpoints. Most match already.

### Exact match (no change needed):
```
/health               → /health               ✅
/api/chat/start       → /api/chat/start       ✅
/api/chat/stream      → /api/chat/stream      ✅
/api/chat/cancel      → /api/chat/cancel      ✅
/api/chat/steer       → /api/chat/steer       ✅
/api/skills            → /api/skills            ✅
/api/skills/content    → /api/skills/content    ✅
/api/skills/save       → /api/skills/save       ✅
/api/skills/delete     → /api/skills/delete     ✅
/api/memory            → /api/memory            ✅
/api/providers         → /api/providers         ✅
/api/providers/delete  → /api/providers/delete  ✅
/api/auth/login        → /api/auth/login        ✅
/api/auth/logout       → /api/auth/logout       ✅
/api/auth/status       → /api/auth/status       ✅
/api/upload            → /api/upload            ✅
/api/models            → /api/models            ✅
/api/files/create      → /api/file/create       ✅ (minor rename)
/api/files/delete      → /api/file/delete       ✅
/api/files/mkdir       → /api/file/create-dir   ✅
/api/files/rename      → /api/file/rename       ✅
```

### Simple endpoint rename:
```
Hermes UI call                         → Pantheon endpoint
──────────────────────────────────────────────────────────────
fetch('/cron/list')                    → fetch('/api/crons')
fetch('/browse?path=X&workspace=Y')    → fetch('/api/list?path=X')
fetch('/readfile?path=X&workspace=Y')  → fetch('/api/file?path=X')
fetch('/writefile')                    → fetch('/api/file/save')
fetch('/api/workspaces/browse?path=X') → fetch('/api/list?path=X')
fetch('/api/ui-conversations')         → fetch('/api/sessions')
fetch('/api/version')                  → fetch('/api/git-info')
fetch('/api/localfile?path=X')         → fetch('/api/file/raw?path=X')
fetch('/api/logs/recent?...')          → fetch('/api/logs?...')
fetch('/server/restart')               → fetch('/api/admin/reload')
```
### Needs adaptation (no direct Pantheon equivalent):

```
/api/tools/web-extract     → ADAPT: replace with /api/mcp/tools or remove health check
/api/convert/rtf-to-txt    → ADAPT: macOS utility — strip from Pantheon build
/skills/dates              → ADAPT: either build endpoint or remove column
/memory/status             → ADAPT: use /api/memory instead
/api/chat/stream/status    → ADAPT: verify Pantheon equivalent
/api/delegation/info       → ADAPT: add if missing from Pantheon
/api/image                 → ADAPT: add image gen if wanted
/server/restart            → ADAPT: use /api/admin/reload
/server/full-restart       → ADAPT: use /api/admin/reload
/server/pull-full-restart  → ADAPT: use /api/admin/reload
```

**Implementation strategy:** Create a `fetchWithPantheon(url, options)` wrapper that maps URLs, or just do a find-and-replace pass on the 20+ changed paths in `hermes-ui.html`.

---

## ADR-5: File Rename Plan (soul_forge.py)

**Decision:** Rename `api/forge.py` → `api/soul_forge.py`. Update 2 import lines in `routes.py`.

```python
# In routes.py, change:
from api.forge import forge_start, forge_chat, forge_accept
# → 
from api.soul_forge import forge_start, forge_chat, forge_accept
```

**Also update** any `api/boons.py` import that references forge (there's a `promote_to_forge`):
```python
from api.boons import promote_to_forge  # no change needed, it's in boons.py
```

**No frontend changes needed** — the frontend calls `/api/gods/:name/forge` which routes.py handles, not the module name.

---

## ADR-6: Build Order

**Decision:** 5 phases, prioritized for fastest working output.

### Phase 1: Foundation (Day 1)
**Goal: Merged app serving on port :8787**

| Step | Action | Files |
|------|--------|-------|
| 1.1 | Branch from main: `feat/hermes-ui-retheme` | git |
| 1.2 | Bring in `hermes-ui.html` + assets | Copy files |
| 1.3 | Reroute API calls (ADR-4 changes) | `hermes-ui.html` |
| 1.4 | Rename Spaces→Forge Projects label | `hermes-ui.html` |
| 1.5 | Rename Artifacts tab→Boons tab | `hermes-ui.html` |
| 1.6 | Rename terminal panel→broader name (tbd) | `hermes-ui.html` |
| 1.7 | Rename forge.py→soul_forge.py, update import | `api/soul_forge.py`, `routes.py` |
| 1.8 | Remove connectors routes from routes.py | `routes.py` |
| 1.9 | Update self-updater to Pantheon GitHub | `api/updates.py` |
| 1.10 | Smoke test: load app, send message | browser |

### Phase 2: God Core (Days 2-3)
**Goal: Gods visible and manageable**

| Step | Action |
|------|--------|
| 2.1 | Build GodRail component (sidebar circles) |
| 2.2 | Build GodManagementView (list + CRUD) |
| 2.3 | Build GodDetailCard (expandable modal) |
| 2.4 | Build GodProfileChip (composer) |
| 2.5 | Add GodGlow CSS |
| 2.6 | Wire `/api/gods` endpoints |
| 2.7 | Build ForgeWizard (Hephaestus interview) |
| 2.8 | Build SummonView (GitHub browser) |

### Phase 3: Knowledge (Days 3-4)
**Goal: Athenaeum browsing and search**

| Step | Action |
|------|--------|
| 3.1 | Build AthenaeumView (codex tree) |
| 3.2 | Build AthenaeumSearchView (semantic + graph) |
| 3.3 | Add Clip-to-Athenaeum button on messages |
| 3.4 | Wire `/api/athenaeum/*` endpoints |

### Phase 4: Boons (Day 4)
**Goal: Content creation and viewing**

| Step | Action |
|------|--------|
| 4.1 | Enhance Boons tab in TerminalPanel |
| 4.2 | Wire to `/api/boons/*` endpoints |
| 4.3 | Add Promote-to-Boon button on messages |
| 4.4 | Boon rendering: HTML iframe, code highlight, CSV table |

### Phase 5: Polish (Day 5)
**Goal: Everything else**

| Step | Action |
|------|--------|
| 5.1 | Build NotificationsBell + dropdown |
| 5.2 | Build InsightsView (usage stats) |
| 5.3 | Build GatewayStatusView |
| 5.4 | Build ProfilesView (sub-agents) |
| 5.5 | Add VPS metrics to HealthView |
| 5.6 | Build OnboardingWizard (simplified) |
| 5.7 | Wire PantheonTheme SDK |
| 5.8 | Update PWA manifest |
| 5.9 | Smoke test all panels |
| 5.10 | Run test suite (4,810 tests should pass) |

---

## ADR-7: Deprecated Backend Code

**Decision:** Remove connectors module + routes. Keep oauth.py — it's used by streaming.py and routes.py for provider auth (OpenAI Codex, Anthropic env lock, onboarding flows), NOT just connectors.

| Module | Action | Why |
|--------|--------|-----|
| `api/connectors.py` | Remove routes + module | ACI.dev Quick-Connect — dead direction per Konan |
| `api/oauth.py` | **KEEP** | Core provider auth infra, imported by streaming.py + routes.py |

**Routes to remove from `routes.py`:**
```
/api/connectors/catalog     → remove
/api/connectors/connect     → remove
/api/connectors/disconnect  → remove
```

**Keep the routes commented out** with a reference to this ADR in case the pattern is ever needed again.

---

## ADR-8: Pantheon Self-Updater

**Decision:** Point the self-updater at `Duskript/Pantheon` instead of the hermes-webui repo.

**Change in `api/updates.py`:**
- Change the remote URL detection from hermes-webui's origin to Pantheon's origin
- The `_check_repo()` function auto-detects by reading `git remote get-url origin` — so if the branch's origin is already Pantheon, it may work without changes
- Verify that `_get_repo_url()` returns `https://github.com/Duskript/Pantheon` for the "What's new?" link

---

## Summary: File Change Log

| File | Action |
|------|--------|
| `webui/hermes-ui.html` | ADD from pyrate-llama + adapt API calls + add Pantheon components |
| `webui/assets/` | ADD from hermes-ui |
| `webui/api/soul_forge.py` | RENAME from forge.py |
| `webui/api/routes.py` | PATCH: update forge import, remove connectors routes |
| `webui/api/updates.py` | PATCH: Pantheon GitHub origin |
| `webui/api/connectors.py` | DEPRECATE (keep file, remove routes) |
| `webui/api/oauth.py` | DEPRECATE if only used by connectors |
| `webui/static/` | REMOVE (replaced by hermes-ui.html) |
| `webui/server.py` | KEEP as-is |
| `webui/tests/` | KEEP as-is |

---

*End of ARCHITECT phase. Ready for BUILD phase authorization.*
