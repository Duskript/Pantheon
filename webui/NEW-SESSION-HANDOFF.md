# Hermes — New Session Handoff

Paste this at the start of a fresh session. It contains all context needed to rebuild the Pantheon right panel from scratch.

---

## Mission

Rebuild the right panel in the **Pantheon Web UI** (`~/hermes-webui/`) with two tabs — **Boons** (📜) and **Workspace** (📁). Full design spec is at `~/hermes-webui/PANTHEON-RIGHT-PANEL-SPEC.md` — read it first.

**Core analogy:** Workspaces = Claude Projects · Boons = Claude Artifacts

## What's broken / needs replacing

I previously tried to add these features and they DON'T WORK on mobile (the user clicks things and nothing happens):

1. **Workspace tab** in right panel — clicking it does nothing
2. **Promote to Boon** button in message footers — clicking it does nothing
3. **Boon tab** exists but functionality is incomplete

There's also a lot of **dead/wrong code** in `static/ui.js` — workspace picker dropdown functions, clunky event binding, etc. Strip it all and rebuild clean.

## What exists and WORKS (don't touch)

- **Left sidebar Forge panel** (`#panelWorkspaces`) — workspace management, works fine
- **Composer workspace chip** (`#composerWorkspaceGroup`) — shows current workspace in chat input
- **Boon CRUD API** — `/api/boons/create`, `/api/boons/list`, `/api/boons/update`, `/api/boons/delete`, `/api/boons/toggle-pin`, `/api/boons/promote-to-forge` — all functional
- **Workspaces API** — `GET /api/workspaces` returns `{workspaces: [{path, name}], last: "..."}`
- **Server** — runs on `localhost:8787`, serves static files from `static/` with `Cache-Control: no-store`
- **Existing right panel structure** — `<aside class="rightpanel">` with tabs, content panels, preview area
- **File tree system** — boot.js has `loadDir()`, `navigateUp()`, file preview, breadcrumbs — all functional

## Key files

- `~/hermes-webui/static/index.html` — Main HTML (right panel at lines ~1204-1292)
- `~/hermes-webui/static/ui.js` — Frontend JS (my boon/workspace additions from ~7050-7540)
- `~/hermes-webui/static/boot.js` — Core framework (panel mode management, file tree, workspace management)
- `~/hermes-webui/static/style.css` — All styling (right panel at ~1293-1394, mobile at ~1463-1660)
- `~/hermes-webui/api/routes.py` — Backend routes (boon CRUD at ~3596-5560)
- `~/hermes-webui/api/boons.py` — Boon data layer
- `~/hermes-webui/PANTHEON-RIGHT-PANEL-SPEC.md` — **THE SPEC — read it first**

## The user (Konan)

- Uses the app on **mobile** (Android/Chrome or iOS/Safari)
- Interacts via the web UI at `localhost:8787`
- MDT timezone
- Prefers **visible, obvious results** — if it works they should SEE it work
- Frustrated by things that silently do nothing

## Build approach

1. Read `PANTHEON-RIGHT-PANEL-SPEC.md` in full
2. Read the existing code to understand what's already there
3. Strip the broken code first (remove ws-picker, old event bindings, etc.)
4. Implement clean — test each piece on the running server after every change
5. Verify with curl and by checking the rendered HTML/JS from the server

## Urgent constraint

The previous implementation used inline `onclick="switchRightPanelTab(...)"` attributes and it DID NOT WORK on the user's mobile browser even with `Cache-Control: no-store`. Use `addEventListener` and `touchstart` events with programmatic binding — no inline onclick for critical interactions.

---

## Quick-start commands

```bash
cd ~/hermes-webui
# Server is already running on port 8787
# Check server: curl http://localhost:8787/
# Check JS: curl http://localhost:8787/static/ui.js | head -50
# Check API: curl http://localhost:8787/api/boons/list
```
