# Pantheon × Hermes UI — Discovery Summary

> Corrections from Konan incorporated. This is the signed brief.

---

## 1. Corrections Applied

| Original | Correction |
|----------|-----------|
| Quick-Connect via ACI.dev (connectors) | ❌ **Remove entirely** — different direction |
| Self-updater pointing at hermes-webui | 🔧 **Re-point** to Pantheon's GitHub repo |
| "Spaces" label | **"Forge Projects"** for clarity |
| Profiles = god profiles | **Sub-agents/minions** — non-god profiles gods can call on |
| "Boon Drawer" overlay | **"Boons"** — stays as a tab in the Terminal panel |
| artifact tab in terminal | Renamed to **Boons** tab |
| forge.py | Renamed to **soul_forge.py** |

---

## 2. What Stays (Backend — 37 modules, untouched)

All 37 `api/` modules remain as-is with these specific changes:

### Updates needed to backend
- **`api/forge.py`** → rename to **`api/soul_forge.py`**, update imports in `routes.py`
- **`api/updates.py`** → change remote from hermes-webui to Pantheon GitHub repo
- **`api/connectors.py`** + **`api/oauth.py`** → remove/deprecate (Quick-Connect direction is dead)

### Pinning untouched
Everything else in `api/` keeps running — 4,810 tests still pass.

---

## 3. What Goes (Removed from scope)

| Feature | Reason |
|---------|--------|
| Connectors / ACI.dev Quick-Connect | Different direction |
| Boon Drawer standalone overlay | Stays as Boons tab inside Terminal panel |

---

## 4. Naming Map (Revised)

| Hermes UI Internal | Pantheon Display |
|--------------------|-----------------|
| Spaces | **Forge Projects** |
| Artifact (tab) | **Boons** |
| Artifact (concept) | **Boon** |
| Terminal panels tab "Artifacts" | **Boons** tab |
| Terminal panel (entire) | TBD — broader name (houses logs + boons) |
| — (new panel) | **Athenaeum** |
| — (new panel) | **God Management** |
| — (new panel) | **Profiles** (sub-agents/minions) |
| — (new panel) | **Summon** (Pantheon-Summons browser) |
| — (nav rail) | **God Rail** |
| Settings | Settings (add Pantheon sections) |
| MCP Browser | MCP Browser (keep) |

---

## 5. Frontend — 13 Pantheon Panels → Hermes UI Map

| Panel | Display Name | Hermes UI Status | Action |
|-------|-------------|-----------------|--------|
| panelChat | Communion | ✅ ChatView | Keep |
| panelWorkspaces | Forge Projects | ✅ SpacesView | Rename |
| panelAthenaeum | Athenaeum | ❌ **New** | Build codex tree + search |
| panelSkills | Skills | ✅ SkillsView | Minor API tweak |
| panelMemory | Memory | ✅ MemoryView | Minor API tweak |
| panelSettings | Settings | ✅ SettingsModal | Add Pantheon sections |
| panelGods | God Management | ❌ **New** | Build list + create/edit |
| panelProfiles | Sub-agents | ❌ **New** | Build minion profiles |
| panelLogs | Logs | ✅ TerminalView | Rename + merge with boons |
| panelInsights | Insights | ❌ **New** | Usage + cost stats |
| panelTasks | Tasks | ✅ TasksView | Keep |
| panelKanban | Kanban | ❌ Partial | TasksView covers loosely |
| panelTodos | Todos | ✅ SessionTodosPanel | Keep |

---

## 6. New React Components to Build

### Major (10)
1. **God Rail** — left sidebar with circular god icons, status dots, glow colors
2. **God Management Panel** — full CRUD list, status indicators
3. **God Detail Card** — expandable card with god info
4. **Summon View** — browse Pantheon-Summons GitHub repo, import gods
5. **Athenaeum Panel** — codex tree browser + file viewer
6. **Athenaeum Search** — semantic search + graph search
7. **Forge Creation Wizard** — Hephaestus interview to create new gods
8. **Profiles Panel** — sub-agent/minion profile management
9. **Insights View** — usage, cost, TPS metrics
10. **Notification System** — bell + dropdown, god notifications

### Medium (4)
11. **Onboarding Wizard** — port from Pantheon's 5-step flow
12. **Boons Tab** (in Terminal Panel) — rename artifact tab, wire to `/api/boons/*`
13. **Gateway Status** — Telegram/Discord connection indicators
14. **God Profile Chip** — composer shows active god with icon

### Small (4)
15. **System Health** — VPS CPU/RAM/disk (add to existing HealthView)
16. **Rollback UI** — checkpoint browser
17. **Project Ideas** — CRUD with drag-reorder
18. **MCP Services Catalog** — quick-install from marketplace

---

## 7. Simple Renames / Adaptations

| Change | Effort |
|--------|--------|
| SpacesView → Forge Projects | Low — label swap |
| Artifacts tab → Boons tab | Low — label swap |
| Terminal panel → broader name | Low — label + icon swap |
| API endpoint calls (15 diffs) | Low — fetch URL changes |
| Icon packs (4 → 1 Pantheon set) | Medium — consolidate |
| Theme SDK integration | Medium — wire PantheonTheme into React |
| i18n system | Medium — port locale bundles |
| PWA manifest | Low — update name/URL |

---

## 8. Updated Scope Totals

| Category | Count |
|----------|-------|
| Backend modules kept as-is | 34 (after remove connectors + oauth, rename forge) |
| Backend tests | 4,810 (still pass) |
| Hermes UI components keep as-is | ~12 |
| API endpoint re-targets | ~15 |
| New React components (major) | 10 |
| New React components (medium) | 4 |
| New React components (small) | 4 |
| Simple renames | ~5 |

---

*Brief signed. Ready for ARCHITECT phase.*
