# Pantheon Right Panel — Full Design Spec

> Created: 2026-05-10
> Updated: 2026-05-10 (after user clarification)
> Goal: Right panel with dual tabs — Boon (📜) and Workspace (📁)
> Analogy: Workspaces = Claude Projects · Boons = Claude Artifacts

---

## 1. THE VISION (in the user's words)

> *"As I'm working with a god they either independently make a boon — HTML code, lyrics, a Word doc, Excel spreadsheet, whatever — it shows up in the Boon tab opened so it's viewable after it's created."*
> 
> *"The Boon tab should act as a folder for the session where created documents get stored and can be viewed in full in that side panel tab."*
> 
> *"I'm not having to open another window or app to see the contents of the file/boon."*
>
> *"The promote to boon button should take that response from the god/agent, copy it, and create it as a boon."*
>
> *"A boon — text, code, or spreadsheet — should be editable in that same location by the user."*
>
> *"Workspaces should function like projects in Claude. Boons should function like artifacts in Claude."*
>
> *"If I'm working on the Suno player, anything that is made or uploaded while I have that workspace selected should go in that folder."*

---

## 2. CORE CONCEPTS

### Workspace = Project
- A named directory/folder on disk
- Contains all files and boons related to a specific project/task
- Selecting a workspace sets the storage context
- Files uploaded or boons created while a workspace is active → go into that workspace's folder
- Analogy: Claude Projects

### Boon = Artifact
- A document/file created by a god (or promoted from a message)
- Can be: text, HTML, code, lyrics, Word doc, Excel spreadsheet, markdown, etc.
- Appears in the Boon tab automatically upon creation
- Viewable IN FULL within the right panel (no external app needed)
- Editable in-place (text, code, structured content)
- Stored on disk inside the active workspace's folder
- Analogy: Claude Artifacts

---

## 3. RIGHT PANEL — TAB BAR

```
┌──────────────────────────────────────────┐
│ [📜 Boon]  [📁 ▼ Workspace]     [✕ Hide] │
├──────────────────────────────────────────┤
│                                          │
│   <tab content area>                     │
│                                          │
└──────────────────────────────────────────┘
```

### Tab 1: 📜 Boon
- **Clicking the tab** → switches to boon content panel
- Shows a list/search of boons (artifacts) for the current workspace
- Clicking a boon in the list → opens it for full viewing in the panel
- Boons are renderable/viewable in full (HTML renders as HTML, code with syntax highlighting, spreadsheets as tables, text as text)

### Tab 2: 📁 ▼ Workspace (SPLIT BUTTON)
- **Two interaction zones on the same tab button:**

  1. **Tab body** (📁 Workspace label area) — click opens workspace panel content:
     - File tree of the currently selected workspace
     - Ability to browse folders/files in that workspace
     - Like a mini file explorer

  2. **▼ Down arrow** (right side of tab) — click opens a drop-down menu:
     - Lists all available workspaces
     - Clicking a workspace name → switches active workspace
     - Workspace switch updates EVERYTHING:
       - File tree (now points to new workspace folder)
       - Boon list (now shows boons from new workspace)
       - Chat composer workspace chip (syncs)
       - The tab label updates to show new workspace name

---

## 4. BOON TAB — Full Detail

### When a boon is created (by god or promotion):
1. Boon is stored in the active workspace's folder on disk
2. Boon card appears in the boon list
3. Boon opens automatically for viewing (full content visible in panel)
4. If the boon type supports it (text, code, structured data), inline editing is available

### Boon List:
- Shows boon cards with: title, god source icon, timestamp, type badge
- Search/filter at the top
- Pin/unpin for favorites
- **GLOBAL — shows ALL boons across all workspaces**
- Switching workspaces does NOT filter the boon list

### Boon View:
- Full content rendered in the panel preview area
- HTML → rendered as interactive HTML
- Code → syntax-highlighted with Prism
- Spreadsheet → rendered as formatted table
- Text/Markdown → rendered formatted
- Edit button → switches to edit mode (textarea or structured editor)

### Boon Storage:
- Metadata in `~/.hermes/webui/boons/{boon_id}/meta.json`
- Content in `~/.hermes/webui/boons/{boon_id}/content.{format}`
- **NEW:** When a boon is created, ALSO copy/symlink it into `{active_workspace}/boons/{boon_id}/` for filesystem organization
- The boon list in the UI shows ALL boons globally (regardless of workspace)

---

## 5. WORKSPACE TAB — Full Detail

### Tab Interaction:
- **Click tab body (📁 Workspace):** Opens workspace panel showing:
  - Breadcrumb navigation
  - File tree of current workspace
  - File preview on click
  - New file/folder creation
  - Hidden files toggle

- **Click ▼ arrow:** Opens drop-down listing all workspaces:
  - Current workspace highlighted/checked
  - Click any workspace to switch
  - Drop-down closes on selection

### File Tree:
- Standard directory tree (already exists in the original code via boot.js)
- Click files to preview in the panel
- Folder expand/collapse
- Create/delete/rename files and folders

### Workspace Switching:
When user switches workspace (via tab arrow ▼):
1. `POST /api/workspaces/select` or equivalent updates the session
2. File tree reloads for new workspace
3. Composer workspace chip updates
4. Tab label updates to show new workspace name
5. **Boon list is NOT affected** — boons are global across all workspaces

---

## 6. PROMOTE TO BOON — Full Detail

### Button Location:
- 📜 button in message footer actions (assistant messages only)

### On Click:
1. Takes the message content (raw text / code)
2. Determines content type (text, code, HTML, markdown)
3. Creates a new boon entry:
   - Title: First line of message (or "Boon from {god name}")
   - Body: Full message content
   - Source God: The god that sent the message
   - Workspace: Current active workspace
   - Type: auto-detected from content (html, code, text, markdown)
4. Saves boon to central store (`~/.hermes/webui/boons/{id}/`)
5. Also copies boon to the active workspace folder (`{workspace}/boons/{id}/`)
6. Opens the new boon in the Boon tab (auto-switches to Boon tab if on workspace tab)
7. Shows success toast

---

## 7. DATA FLOW

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER ACTIONS                                  │
├──────────────────┬─────────────────────┬─────────────────────────────┤
│ Click ▼ on       │ Click 📁 Workspace  │ Click 📜 on message        │
│ Workspace tab    │ tab body            │ (Promote to Boon)           │
└────────┬─────────┴──────────┬──────────┴──────────────┬──────────────┘
         │                    │                          │
         ▼                    ▼                          ▼
┌─────────────────┐ ┌─────────────────┐ ┌──────────────────────────┐
│ Drop-down menu   │ │ Show file tree  │ │ Create boon from msg     │
│ of workspaces    │ │ for workspace   │ │ Save to workspace/boons/ │
│ Click → switch   │ │ Browse files    │ │ Open in Boon tab         │
│ workspace        │ │ Preview files   │ │                          │
└────────┬─────────┘ └────────┬────────┘ └──────────┬───────────────┘
         │                    │                      │
         ▼                    ▼                      ▼
    ┌─────────────────────────────────────────────────────┐
    │                  SYNC EFFECTS                        │
    │  • File tree reloads for new workspace               │
    │  • Boon list reloads for new workspace               │
    │  • Composer workspace chip updates                   │
    │  • Tab label updates                                 │
    └─────────────────────────────────────────────────────┘
```

---

## 8. WHAT TO STRIP (clean slate)

On rebuild, remove the following from the right panel code:

- ❌ `ws-picker` (the internal picker bar inside workspacePanel)
- ❌ `ws-picker-dropdown` (the internal dropdown inside workspacePanel)
- ❌ `toggleWsPickerDropdown()` function
- ❌ `loadWsPickerList()` function
- ❌ `filterWsPickerList()` function
- ❌ `selectWsPicker()` function
- ❌ `closeWsPickerDropdown()` function

The workspace selector moves from inside the panel → to the tab button itself.

---

## 9. NEW CODE STRUCTURE (proposed)

### HTML changes (`index.html`):
- `#tabWorkspace` → split into tab body + ▼ arrow span
- `#workspacePanel` → simplify: remove ws-picker, keep file tree + preview
- `#boonPanel` → enhance: add boon view area, edit mode, type rendering

### JS changes (`ui.js`):
- Replace `switchRightPanelTab` → handle both tab click and arrow click
- Workspace tab arrow handler → load + show dropdown
- Workspace tab body handler → show file tree
- `promoteMsgToBoon` → save to workspace folder on disk, not just API
- Boon rendering → HTML render, code highlight, table render, edit mode
- Auto-open boons on creation
- Workspace-scoped boon filtering

### Backend changes (`api/`):
- Boon storage → per-workspace folder on disk
- Boon CRUD → scoped to workspace
- Content type detection/rendering hints
- Workspace select endpoint (if not exists)

---

## 10. MOBILE CONSIDERATIONS

- Tab split-button needs to work with touch (▼ arrow must be tappable)
- Drop-down menu must work within the right panel z-index
- File tree works at mobile widths with container queries
- Boon full-view works within the panel (scroll, not page nav)
- Edit mode works on mobile (textarea fills panel width)

---

