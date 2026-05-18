# God Management System — Implementation Plan

**Goal:** Full god creation/editing panel with icon upload, metadata editing, and SOUL.md viewer
**Architecture:** Backend API (`routes.py` + `profiles.py`) → Frontend panel (`index.html` + `panels.js`) → Main editor view
**Scaffold reference:** `~/workspace/PANTHEON-UI-DESIGN.md` (Phase A-E patterns)

## Tasks

### Backend

#### Task 1: SOUL.md Read/Write API
**Files:** Modify `~/hermes-webui/api/routes.py`
**Details:** Add `GET /api/gods/{name}/soul` — reads `SOUL.md` from the god's profile dir. Add `PUT /api/gods/{name}/soul` — writes new content. Return 404 if no SOUL.md exists yet.
**Verify:** `curl http://localhost:8787/api/gods/apollo/soul` returns content

#### Task 2: Metadata Update API
**Files:** Modify `~/hermes-webui/api/routes.py`
**Details:** Add `PUT /api/gods/{name}/metadata` — accepts `display_name`, `domain`, `color`, `model`, `provider`. Writes to `god.json`. Uses existing `_write_god_metadata()`.
**Verify:** `curl -X PUT -d '{"display_name":"Test","color":"#ff0000"}' http://localhost:8787/api/gods/apollo/metadata`

#### Task 3: Icon Upload API
**Files:** Modify `~/hermes-webui/api/routes.py`
**Details:** Add `POST /api/gods/{name}/icon` — accepts multipart or base64 image. Saves to `~/.hermes/profiles/{name}/icon.png`. Returns `{"url":"/api/gods/{name}/icon"}`. Add `GET /api/gods/{name}/icon` — serves the file.
**Verify:** Upload via curl, verify icon serves at `/api/gods/apollo/icon`

#### Task 4: Providers Listing API
**Files:** Modify `~/hermes-webui/api/routes.py`
**Details:** Add `GET /api/providers` — reads active config for available providers and their models. Returns structured list.
**Verify:** `curl http://localhost:8787/api/providers` returns JSON with providers array

### Frontend

#### Task 5: God List Sidebar
**Files:** Modify `~/hermes-webui/static/index.html`, `~/hermes-webui/static/panels.js`, `~/hermes-webui/static/style.css`
**Details:** Add `#panelGods` sidebar panel with card grid showing all gods (icon, name, domain). Add "+ New God" button. Mark as hidden from rail (same as memory). Wire into `switchPanel()`.
**Verify:** Navigate to Settings → God Management, see god cards

#### Task 6: God Editor Main View
**Files:** Modify `~/hermes-webui/static/index.html`, `~/hermes-webui/static/panels.js`, `~/hermes-webui/static/style.css`
**Details:** Add `#mainGodEditor` main view with: name input, domain input, provider/model dropdowns, color picker (swatches + hex), icon circle preview + upload button, SOUL.md textarea with save. Wire save button to PUT API calls.
**Verify:** Click a god card → see full editor with data populated

#### Task 7: Wire Settings → God Management
**Files:** Modify `~/hermes-webui/static/panels.js`
**Details:** Change `switchSettingsSection('god-memory')` handler from `switchPanel('memory')` to `switchPanel('gods')`.
**Verify:** Settings → God Management opens the god list panel

#### Task 8: God CRUD JS Logic
**Files:** Modify `~/hermes-webui/static/panels.js`
**Details:** `loadGodList()` fetches `/api/gods` and renders cards. `openGodEditor(name)` switches to main view and loads god data. `saveGodMetadata()` PUTs changes. `deleteGod()` confirms + deletes. `createNewGod()` opens empty editor. `uploadGodIcon()` sends file. `saveGodSoul()` PUTs SOUL.md.
**Verify:** Create new god, edit fields, save, see changes persist

#### Task 9: Styling
**Files:** Modify `~/hermes-webui/static/style.css`
**Details:** Card grid (`.god-list`), editor form layout, icon circle preview, color swatches grid, responsive breakpoints.
**Verify:** Desktop and mobile views look clean
