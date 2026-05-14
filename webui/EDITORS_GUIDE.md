# Pantheon Web UI — Editor's Guide

> **Purpose:** One-stop reference for anyone (human or agent) adding features to the Pantheon Web UI.
> Covers project layout, how to add endpoints/settings/themes/icons, responsive rules, data flow,
> and the PR checklist. Keep this document updated as the code changes.

---

## 1. Architecture Overview

The WebUI is a **zero-build-step Python + vanilla JavaScript** application. No bundlers, no frameworks.

```
┌──────────────────────────────────────────────────────────┐
│                    server.py (thin shell)                │
│  ThreadingHTTPServer → do_GET() / do_POST() → routes.py │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│  api/routes.py (all route handlers)                      │
│  ┌──────────┬──────────┬───────────┬──────────┬────────┐ │
│  │config.py │models.py │streaming  │auth.py   │helpers │ │
│  │discovery │sessions  │.py SSE    │password  │.py j() │ │
│  │+settings │+CRUD     │engine     │auth      │bad()   │ │
│  └──────────┴──────────┴───────────┴──────────┴────────┘ │
`──────────────────┬────────────────────────────────────────'`
                   │  serves static/
┌──────────────────▼────────────────────────────────────────┐
│  static/  (all frontend — served as flat files)           │
│  index.html   → entry point, preloads theme from LS       │
│  style.css    → all CSS + responsive breakpoints + themes │
│  boot.js      → mobile nav, voice input, boot IIFE        │
│  ui.js        → DOM helpers, renderMd, global state       │
│  panels.js    → settings, cron, skills, memory panels     │
│  messages.js  → send(), SSE event handlers                │
│  sessions.js  → session CRUD, list rendering              │
│  workspace.js → file tree + preview                       │
│  commands.js  → slash command autocomplete                │
│  theme-sdk.js → PantheonTheme API (theme/icon/custom)     │
└──────────────────────────────────────────────────────────┘
```

### Key Files at a Glance

| File | Role | Approx Lines |
|------|------|-------------|
| `server.py` | HTTP shell, routes to `api/routes.py` | ~81 |
| `api/routes.py` | All GET/POST handlers | ~2250 |
| `api/config.py` | Discovery, state dirs, model detection, reloadable config | ~701 |
| `api/models.py` | Session model, in-memory cache `SESSIONS = {}` | ~137 |
| `api/helpers.py` | `j()`, `t()`, `bad()`, `require()`, `safe_resolve()` | ~71 |
| `api/streaming.py` | SSE engine, `_run_agent_streaming()` | ~660 |
| `api/auth.py` | Optional password auth, signed cookies | ~149 |
| `api/profiles.py` | Profile CRUD, `hermes_cli` wrapper | ~246 |
| `static/style.css` | All CSS + responsive breakpoints + skin variables | ~4550 |
| `static/ui.js` | `S` global state, `renderMd()`, helpers | ~1740 |
| `static/panels.js` | Settings, cron, skills, memory, todos, `switchPanel()` | ~1438 |
| `static/messages.js` | `send()`, SSE handlers, approval polling | ~655 |
| `static/sessions.js` | Session CRUD, list rendering, icons | ~800 |
| `static/boot.js` | Mobile nav, voice input, boot IIFE | ~524 |
| `static/theme-sdk.js` | `PantheonTheme` SDK | ~440 |

### State Directory (runtime data, outside repo)

```
~/.hermes/webui/
├── settings.json         User settings (theme, model, workspace, etc.)
├── sessions/             One JSON file per session: {session_id}.json
├── sessions.json         Gateway session metadata
├── workspaces.json       Registered workspaces
├── last_workspace.txt    Last-used workspace path
├── projects.json         Session project groups
└── _index.json           Session index cache
```

Override with `HERMES_WEBUI_STATE_DIR` env var. The staging instance uses
`~/.hermes/webui-stage/` (set via `HERMES_WEBUI_STATE_DIR`).

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `HERMES_WEBUI_HOST` | Bind address | `127.0.0.1` |
| `HERMES_WEBUI_PORT` | Port | `8787` |
| `HERMES_WEBUI_STATE_DIR` | State directory | `~/.hermes/webui/` |
| `HERMES_WEBUI_DEFAULT_WORKSPACE` | Default workspace path | `~/workspace` |
| `HERMES_WEBUI_DEFAULT_MODEL` | Default model ID | Provider default |
| `HERMES_WEBUI_PASSWORD` | Enable password auth | (disabled) |
| `HERMES_CONFIG_PATH` | config.yaml path | `~/.hermes/config.yaml` |
| `HERMES_HOME` | Base Hermes directory | `~/.hermes` |
| `HERMES_WEBUI_AGENT_DIR` | Agent checkout path | Auto-discovered |

---

## 2. Development Setup

```bash
# Start staging server
cd ~/hermes-webui-stage
HERMES_WEBUI_PORT=8788 HERMES_WEBUI_STATE_DIR=~/.hermes/webui-stage python server.py

# Or use the launcher
./bootstrap.py --port=8788

# Check status
curl localhost:8788/health

# Run tests (isolated port 8788, separate state)
cd ~/hermes-webui-stage
pytest tests/ -x -v

# Restart after code change (stop + start)
kill $(lsof -ti:8788) && HERMES_WEBUI_PORT=8788 python server.py
```

**Staging port:** 8788 (production is 8787). Tests use an isolated state
dir and never touch production data.

### Quick Edit Loop

1. Edit a file (Python in `api/` or JS/CSS in `static/`)
2. Kill the server: `kill $(lsof -ti:8788)`
3. Restart: `HERMES_WEBUI_PORT=8788 python server.py &`
4. Reload browser (hard reload: Cmd/Ctrl+Shift+R to bypass cache)
5. Check browser console for errors

---

## 3. Adding a New API Endpoint

### Step-by-Step

**Step 1: Add the handler in `api/routes.py`**

Find the right section (GET handlers or POST handlers) and add an `if/elif`
branch:

```python
# In do_GET():
if parsed.path == "/api/my-new-feature":
    result = do_my_new_feature()
    return j(handler, result)

# In do_POST():
if parsed.path == "/api/my-new-feature":
    body = read_body(handler)
    result = do_my_new_feature(body)
    return j(handler, result)
```

**Step 2: Implement the business logic**

Either inline in routes.py (for simple cases) or import from a new module:

```python
def do_my_new_feature(params=None):
    # Validate inputs
    # Do work
    # Return dict or list (gets JSON-serialized by j())
    return {"ok": True, "data": [...]}
```

**Step 3: Add UI component**

For a simple fetch + render:

```javascript
// In ui.js or panels.js
async function renderMyNewFeature() {
  const data = await api('/api/my-new-feature');
  const container = document.getElementById('myFeatureContainer');
  container.innerHTML = data.data.map(item => `
    <div class="my-feature-item">${item.name}</div>
  `).join('');
}
```

**Step 4: Add CSS (if needed)**

```css
.my-feature-item {
  padding: var(--space-2);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
}
```

**Step 5: Register the panel or button in `index.html` or panels.js**

For a titlebar button, add in `index.html` within the `.app-titlebar-actions` group.
For a sidebar panel, add a nav entry and register in `switchPanel()`.

### Route Handler Conventions

- Use `j(handler, payload, status=200)` for JSON responses
- Use `t(handler, payload, status=200, content_type)` for text/HTML
- Use `bad(handler, message, status=400)` for errors
- All POST endpoints parse JSON body via `read_body(handler)`
- **Critical ordering rule:** The `/api/upload` check in `do_POST()` MUST appear
  BEFORE `read_body()` — uploads need the raw `rfile` stream

### Complete Template

```python
# In api/routes.py — add to do_GET():
if parsed.path == "/api/widgets":
    try:
        widgets = load_widgets()
        return j(handler, {"ok": True, "widgets": widgets})
    except Exception as e:
        logger.exception("Failed to load widgets")
        return j(handler, {"ok": False, "error": str(e)}, 500)

# In static/ui.js:
async function renderWidgets() {
    const el = document.getElementById('widgetContainer');
    if (!el) return;
    try {
        const data = await api('/api/widgets');
        if (!data.ok) { el.textContent = 'Error: ' + data.error; return; }
        el.innerHTML = data.widgets.map(w =>
            `<div class="widget-item">${escHtml(w.name)}</div>`
        ).join('');
    } catch(e) {
        el.textContent = 'Failed to load widgets';
    }
}
```

---

## 4. Adding a New Settings Option

The settings system has three layers:

```
Defaults (in api/config.py → _SETTINGS_DEFAULTS)
  └── Stored (in settings.json, persists across restarts)
       └── Env overrides (HERMES_WEBUI_* env vars)
```

### Step-by-Step

**Step 1: Add default to `api/config.py`**

Find or create the `_SETTINGS_DEFAULTS` dict near the top of config.py:

```python
_SETTINGS_DEFAULTS = {
    "theme": "dark",
    "skin": "default",
    "font_size": "default",
    "layout_density": "comfortable",
    "icon_pack": "pixel",
    "send_key": "enter",
    "language": "en",
    # ... add your new setting:
    "my_new_setting": "default_value",
}
```

**Step 2: Add to allowed keys (if validated):**

```python
_SETTINGS_ALLOWED_KEYS = set(_SETTINGS_DEFAULTS.keys())
```

If the setting has constrained enum values:

```python
_SETTINGS_ENUM_VALUES = {
    "my_new_setting": {"value_a", "value_b", "value_c"},
}
```

**Step 3: Add UI control in the settings panel**

In `static/panels.js`, find the `renderSettingsPanel()` function and add your
control in the appropriate section:

```javascript
// For a select dropdown:
settingsHtml += `
  <div class="settings-field">
    <label class="settings-label">${t('my_setting_label')}</label>
    <div class="settings-control">
      <select class="settings-select-full" data-setting="my_new_setting">
        <option value="value_a" ${s.my_new_setting === 'value_a' ? 'selected' : ''}>Option A</option>
        <option value="value_b" ${s.my_new_setting === 'value_b' ? 'selected' : ''}>Option B</option>
      </select>
    </div>
  </div>`;
```

**Step 4: Wire up autosave**

Settings are autosaved via `_autosavePreferencesSettings()` in panels.js
(or the Appearance variant). Add your setting's data attribute to the form
so the serialization picks it up.

**Step 5: Add i18n key**

In `static/i18n.js`:

```javascript
// For each locale:
my_setting_label: "My New Setting",
my_setting_value_a: "Option A",
```

### Hydration Flow

1. `boot.js` calls `GET /api/settings` → gets merged defaults + stored values
2. `boot.js` passes to `PantheonTheme.hydrate()` for theme settings
3. `panels.js` reads settings from the same API call to populate controls
4. On save: `POST /api/settings` writes to `settings.json`

---

## 5. Theme System

The PantheonTheme SDK (`static/theme-sdk.js`) provides a clean API for all
visual customization. It works by injecting CSS custom properties onto
`document.documentElement` and managing a `<style>` tag for custom colors.

### CSS Variable Map

The SDK mirrors all CSS custom properties used in `style.css`:

| SDK Key | CSS Variable | Purpose |
|---------|-------------|---------|
| `bg` | `--bg` | Page background |
| `sidebar` | `--sidebar` | Sidebar background |
| `border` | `--border` | Border color |
| `text` | `--text` | Primary text |
| `muted` | `--muted` | Secondary text |
| `accent` | `--accent` | Accent/highlight color |
| `surface` | `--surface` | Card/surface background |
| `error` | `--error` | Error state |
| `success` | `--success` | Success state |
| `warning` | `--warning` | Warning state |
| `info` | `--info` | Info state |

### Adding a New CSS Variable

1. Add the variable to `CSS_VARS` in `theme-sdk.js`
2. Add default values in `BASE_COLORS.light` and `BASE_COLORS.dark`
3. For skin-specific overrides, add to `SKIN_COLORS`
4. Add the `:root` rule in `style.css` with a fallback value
5. Reference it in components: `background: var(--my-var, fallback);`

### Adding a New Theme Skin

1. Add a new skin object to `SKIN_COLORS` in `theme-sdk.js`:
   ```javascript
   mynewskin: {
     light: { accent: '#xxx', accentHover: '#xxx', ... },
     dark:  { accent: '#xxx', accentHover: '#xxx', ... },
   }
   ```
2. Add CSS rules in `style.css`:
   ```css
   :root[data-skin="mynewskin"] { --accent: #xxx; --accent-hover: #xxx; ... }
   :root.dark[data-skin="mynewskin"] { --accent: #xxx; ... }
   ```
3. Add to the valid skins list in `PantheonTheme.setSkin()`
4. Add a picker button in the Appearance panel in `panels.js`

### Custom Theme (User-Defined Colors)

When a user sets custom colors via the Appearance panel, the SDK:

1. Calls `PantheonTheme.setColors({ light: {...}, dark: {...} })`
2. Injects a `<style id="pantheon-custom-theme">` with `:root:not(.dark) { ... }`
   and `:root.dark { ... }` blocks overriding CSS variables
3. Persists the color object in `settings.json` under `custom_theme`
4. On page load, `PantheonTheme.hydrate()` reads and re-applies

### Theme Persistence

Settings are saved to `settings.json` and localStorage. Boot order:

1. `index.html` has an inline `<script>` that reads `hermes-theme` and
   `hermes-skin` from localStorage and applies `.dark` class + `data-skin`
   attribute **before** style.css loads (prevents flash)
2. `boot.js` fetches settings from server, hydrates `PantheonTheme`
3. `PantheonTheme.hydrate()` applies full theme state including custom colors

---

## 6. Icon Packs

### Directory Structure

```
static/icons/
├── pixel/        Default pack (pixel art .png)
│   ├── settings_icon.png
│   ├── forge_icon.png
│   ├── Sun_icon.png
│   ├── Moon_icon.png
│   └── ...
├── modern/       (future pack — SVG or higher-res PNG)
│   └── ...
└── minimal/      (future pack)
    └── ...
```

Each icon pack must include the same set of icon filenames. The SDK rewrites
the base path based on the active pack:

```javascript
// Theme SDK getIconUrl():
return 'static/icons/' + packName + '/' + filename;
```

### Adding a New Icon Pack

1. Create directory: `static/icons/mypack/`
2. Add all required icon files (same filenames as pixel pack)
3. Register in the Appearance panel UI (select option in `panels.js`)
4. The pack is now selectable — `PantheonTheme.setIconPack('mypack')`
5. The `data-icon-pack` attribute on `<html>` updates, and image rendering
   switches from `pixelated` to `auto` for non-pixel packs

### setIconPack() Path Rewriting

```javascript
// Before: static/icons/pixel/forge_icon.png
// After setIconPack('modern'):
// → static/icons/modern/forge_icon.png
```

Nav icons, the logo, and any UI image that uses `PantheonTheme.getIconUrl()`
or the `data-icon-pack` attribute pattern automatically updates.

---

## 7. Responsive Layout Rules

### Breakpoints

| Name | Width Range | Touch Targets | Body Text | Nav Pattern |
|------|------------|---------------|-----------|-------------|
| **Mobile** | < 768px | ≥ 48px | 16px | Hamburger → slide-out drawer |
| **Tablet** | 768–1023px | ≥ 44px | 15px | Hamburger → slide-out drawer |
| **Desktop** | 1024–1399px | ≥ 32px | 14px | Fixed 48px rail (always visible) |
| **Wide** | 1400px+ | ≥ 32px | 14px | Fixed 48px rail, max-width 1800px layout |

### How Panels Morph

| Panel | Mobile | Tablet | Desktop |
|-------|--------|--------|---------|
| **Nav rail** | Hidden (hamburger) | Hidden (hamburger) | Fixed 48px rail |
| **Sidebar** | Slide-out drawer | Slide-out drawer | Fixed 300px (resizable) |
| **Right panel** | Slide-out drawer | Slide-out drawer | Fixed 300px (collapsible) |
| **Composer** | Full-width, 44px min | Full-width, compact | Inline bottom, full labels |
| **Settings** | Single-column, stacked | Two-column grid | Multi-column |

### Responsive CSS Patterns

```css
/* Mobile-first base (no min-width — applies everywhere) */
.sidebar { display: none; }  /* hidden by default */
.rail { display: none; }     /* hidden by default */

/* Tablet override */
@media (min-width: 768px) {
  .sidebar { width: var(--sidebar-width); }
}

/* Desktop override */
@media (min-width: 1024px) {
  .rail { display: flex; }
  .sidebar > .sidebar-nav { display: none; }
  .rightpanel { width: var(--rightpanel-width); position: relative; }
}

/* Wide override */
@media (min-width: 1400px) {
  .layout { max-width: 1800px; margin: 0 auto; }
  .messages-inner { max-width: 1200px; }
}
```

### Mobile Drawer Implementation

```css
.sidebar {
  position: fixed; left: -300px; top: 0; bottom: 0;
  width: 300px; z-index: 200;
  transition: left 0.25s ease;
}
.sidebar.mobile-open {
  left: 0;
}
.mobile-overlay {
  position: fixed; inset: 0; z-index: 199;
  background: rgba(0,0,0,.5);
  display: none;
}
.mobile-overlay.visible { display: block; }
```

### Key Rules

- **Never use hardcoded px values** for layout dimensions that should be responsive
- Use `var(--touch-target-min)` for interactive element sizing
- Use `var(--sidebar-width)` and `var(--rightpanel-width)` for panel sizes
- Mobile "hamburger" is a `<button>` with SVG icon in `index.html#btnHamburger`
- Swipe-to-close on right panel is implemented in `boot.js` via touch event handlers

---

## 8. Data Flow Diagrams

### Message Send Flow

```
User types message + clicks Send
         │
         ▼
boot.js:send() → POST /api/chat/start
         │                   │
         │              routes.py creates stream_id,
         │              spawns _run_agent_streaming() thread
         │              returns {stream_id}
         │
         ▼
boot.js: EventSource → GET /api/chat/stream?stream_id=X
         │
    ┌────┴────────── SSE Events ──────────────────┐
    │ token   → {text: "..."}   → append to msg    │
    │ tool    → {name, preview} → tool card shown   │
    │ approval→ {command, ...}  → approval card     │
    │ done    → {session: ...}  → update UI, close  │
    │ error   → {message: ...}  → show error toast  │
    └───────────────────────────────────────────────┘
         │
         ▼
_Run_agent_streaming thread:
  1. Sets env vars (TERMINAL_CWD, HERMES_EXEC_ASK)
  2. Creates AIAgent with stream callbacks
  3. agent.run_conversation(user_message, history)
  4. on_token: queue.put(token event)
  5. on_tool: queue.put(tool event)
  6. On completion: save session, queue.put(done)
```

### Settings Change Flow

```
User changes setting in Settings panel
         │
         ▼
panels.js: _autosavePreferencesSettings()
         │  debounced 350ms
         ▼
fetch(POST /api/settings, { body: JSON.stringify(changes) })
         │
         ▼
routes.py: handle POST /api/settings
         │  validates keys, writes to settings.json
         ▼
Returns {ok: true, settings: {...merged...}}
         │
         ▼
Frontend: PantheonTheme.hydrate(response.settings) [for theme settings]
          localStorage.setItem() [for fast first paint on next load]
```

### Theme Switch Flow

```
User selects skin "ares" in Appearance panel
         │
         ▼
panels.js: PantheonTheme.setSkin('ares')
         │
         ▼
theme-sdk.js: _apply()
         1. root.classList.toggle('dark', ...)
         2. root.dataset.skin = 'ares'
         3. root.dataset.fontSize = ...
         4. If custom colors: inject/remove <style id="pantheon-custom-theme">
         5. localStorage.setItem('hermes-skin', 'ares')
         6. localStorage.setItem('hermes-theme', ...)
         7. Fire onChange callbacks
         │
         ▼
Next page load: index.html inline <script> reads localStorage,
applies dark class + data-skin BEFORE CSS paints → no flash
```

### God Invoke / Sleep Flow

```
Titlebar God button clicked
         │
         ▼
panels.js: toggleGod() → POST /api/god/{name}/wake
         │
         ▼
routes.py: god_runtime.wake_god(name)
          ↓ starts god subprocess if not running
         │
         ▼
Returns {ok: true, state: "awake", pid: 12345}
         │
         ▼
Health panel: polls GET /api/health/gods
         │
         ▼
Returns per-god state:
  - "active"     → currently processing (🟢 green)
  - "sleeping"   → alive but idle (🟡 yellow)
  - "dead"       → crashed/stopped (🔴 red)
  - "ready"      → started once, alive (⚪ white)
  - "uninitialized" → never started (⚫ gray)
```

---

## 9. Pull Request Checklist

Before submitting any change, verify:

### Code Quality
- [ ] No `ps aux` calls in new code (use `/proc` or API instead)
- [ ] No hardcoded colors — use CSS variables (`var(--accent)`, `var(--text)`, etc.)
- [ ] All new UI strings have i18n keys (add to `static/i18n.js`)
- [ ] Mobile layout tested (resize browser to <768px)
- [ ] Theme preview correct in light + dark mode
- [ ] API endpoint has proper error handling (try/except, returns `{ok, error}`)
- [ ] No `// TODO` without an issue number
- [ ] settings.json merge order correct: defaults → stored → env overrides
- [ ] No `print()` statements left in production code (use `logger`)

### Backend
- [ ] New API endpoint registered in `do_GET()` or `do_POST()` in `routes.py`
- [ ] Endpoint returns JSON via `j()` helper (not raw `json.dumps()`)
- [ ] Endpoint doesn't block the server (no `time.sleep()` in handler)
- [ ] If file operation: uses `safe_resolve()` to prevent path traversal
- [ ] If database/state: uses `threading.Lock()` for thread safety
- [ ] Tests added in `tests/` directory

### Frontend
- [ ] New panel registered in `switchPanel()` function in `panels.js`
- [ ] Nav button added to both `.rail` (desktop) and `.sidebar-nav` (mobile)
- [ ] Touch targets meet minimum size for breakpoint (48px mobile, 44px tablet, 32px desktop)
- [ ] CSS respects `var(--touch-target-min)`
- [ ] Modal/dropdown has close-on-Escape handler
- [ ] Console shows no errors or warnings
- [ ] Network tab shows no 404/500 responses
- [ ] Works with and without password auth enabled

### Documentation
- [ ] README.md or ARCHITECTURE.md updated if adding a major feature
- [ ] EDITORS_GUIDE.md updated if adding new patterns or conventions
- [ ] CHANGELOG.md entry added for user-facing changes
- [ ] New CSS variables documented in the SDK and style.css comments

---

## 10. Template Files

### New Panel Template

```javascript
// === In static/panels.js ===

let _myPanelState = null;

function renderMyPanel() {
    const container = document.getElementById('panel-my-feature');
    if (!container) return;
    container.innerHTML = `
        <div class="panel-header">
            <h2>${t('my_panel_title')}</h2>
            <button class="icon-btn" onclick="refreshMyPanel()" data-tooltip="${t('refresh')}">
                <svg>...</svg>
            </button>
        </div>
        <div class="panel-content" id="myPanelContent">
            <p class="loading-placeholder">${t('loading')}...</p>
        </div>`;
    refreshMyPanel();
}

async function refreshMyPanel() {
    const content = document.getElementById('myPanelContent');
    try {
        const data = await api('/api/my-feature');
        content.innerHTML = data.items.map(item =>
            `<div class="my-item">${escHtml(item.name)}</div>`
        ).join('');
    } catch (e) {
        content.innerHTML = `<p class="error-state">${t('error_loading')}</p>`;
    }
}

// Register in switchPanel():
function switchPanel(name) {
    // ... existing code ...
    if (name === 'myfeature') {
        renderMyPanel();
    }
}

// Add nav entry (in index.html):
// Desktop rail:  <button class="rail-btn" onclick="switchPanel('myfeature')" ...>
// Mobile nav:    <button class="nav-tab" onclick="mobileSwitchPanel('myfeature')" ...>
```

### New API Endpoint Template

```python
# === In api/routes.py, in do_GET() ===

if parsed.path == "/api/my-feature":
    try:
        items = _get_my_feature_items()
        return j(handler, {"ok": True, "items": items})
    except Exception as e:
        logger.exception("my-feature endpoint failed")
        return j(handler, {"ok": False, "error": str(e)}, 500)

# The handler function:
def _get_my_feature_items():
    """Return list of feature items from state."""
    path = config.STATE_DIR / "myfeature.json"
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data.get("items", [])
```

### New Settings Option Template

```python
# === In api/config.py ===

# Add to _SETTINGS_DEFAULTS:
_SETTINGS_DEFAULTS = {
    # ... existing ...
    "my_option": "default_value",
}
_SETTINGS_ALLOWED_KEYS = set(_SETTINGS_DEFAULTS.keys())
_SETTINGS_ENUM_VALUES = {
    "my_option": {"value_a", "value_b"},
}
```

```javascript
// === In static/panels.js, inside renderSettingsPanel() ===

settingsHtml += `
  <div class="settings-field">
    <label class="settings-label">${t('my_option_label')}</label>
    <div class="settings-control">
      <select class="settings-select-full"
              data-setting="my_option"
              onchange="_autosavePreferencesSettings()">
        <option value="value_a" ${s.my_option === 'value_a' ? 'selected' : ''}>
          ${t('my_option_a')}
        </option>
        <option value="value_b" ${s.my_option === 'value_b' ? 'selected' : ''}>
          ${t('my_option_b')}
        </option>
      </select>
    </div>
  </div>`;
```

---

## 11. Module Index (Quick Reference)

### API Modules

| Module | Exports / Responsibilities |
|--------|--------------------------|
| `api/config.py` | `REPO_ROOT`, `STATE_DIR`, `SETTINGS_FILE`, `_SETTINGS_DEFAULTS`, model lists, `get_config()`, `reload_config()`, environment discovery |
| `api/routes.py` | `do_GET()`, `do_POST()`, all route handlers, SSE heartbeat, cron, ideas, health, god runtime |
| `api/models.py` | `Session` class, `SESSIONS` cache, `new_session()`, `all_sessions()`, `get_session()` |
| `api/helpers.py` | `j()`, `t()`, `bad()`, `require()`, `read_body()`, `safe_resolve()` |
| `api/streaming.py` | `_run_agent_streaming()`, `STREAMS` registry, SSE event types |
| `api/auth.py` | `check_auth()`, `get_password_hash()`, `make_token()`, `verify_token()` |
| `api/profiles.py` | `list_profiles()`, `get_active_hermes_home()`, `switch_profile()` |
| `api/god_runtime.py` | God process management, health polling, state transitions |

### Static Modules

| Module | Key Functions / Responsibilities |
|--------|-------------------------------|
| `static/ui.js` | `S` global state, `renderMd()`, `api()`, `showToast()`, `escHtml()`, `setStatus()` |
| `static/panels.js` | `switchPanel()`, all panel renderers, settings save/load, cron, skills, ideas, health |
| `static/messages.js` | `send()`, SSE handler, approval polling, `renderMessages()` |
| `static/sessions.js` | Session list rendering, search, CRUD actions, SVG icons |
| `static/workspace.js` | File tree, preview, git status, `loadDir()`, `openFile()` |
| `static/boot.js` | Boot IIFE, mobile nav, voice input, keyboard shortcuts |
| `static/commands.js` | Slash command parser, autocomplete dropdown |
| `static/theme-sdk.js` | `PantheonTheme` SDK (setColors, setIconPack, setMode, hydrate, reset) |

---

> **Maintenance reminder:** Update this guide whenever you add a new pattern,
> change the settings system, or modify the theme SDK API. Stale documentation
> is worse than no documentation.
