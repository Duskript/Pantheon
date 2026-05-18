# Pantheon Companion — Browser Extension

A companion extension for Pantheon that brings your gods to every tab.

## Features

- **🎭 God Picker** — Click the toolbar icon to see all gods, their status, models
- **💬 Chat Side Panel** — Full conversation with any god without leaving your tab
- **📎 Right-Click → Ask Pantheon** — Highlight any text, ask the active god about it
- **📥 Right-Click → Save to Pantheon** — Capture pages, links, and images to the Athenaeum
- **💡 Right-Click → Capture Idea** — Instantly save ideas from any page
- **🏥 Health Monitor** — Quick system health at a glance
- **🔔 Notifications** — Coming soon

## Install (Firefox)

### Temporary (developer mode)
1. Open Firefox and go to `about:debugging#/runtime/this-firefox`
2. Click **Load Temporary Add-on**
3. Select `manifest.json` from this directory
4. The extension loads until you restart Firefox

### Permanent (unsigned)
1. Go to `about:config` and set `xpinstall.signatures.required` to `false`
2. Package: `cd .. && zip -r pantheon-companion.zip pantheon-companion/`
3. Drag the `.xpi` file onto Firefox

## Install (Chrome / Vivaldi / Edge)

1. Open the browser and go to `chrome://extensions`
2. Enable **Developer mode** (toggle in top-right)
3. Click **Load unpacked**
4. Select this directory

## First Run

1. Click the Pantheon icon in your toolbar
2. Enter your Pantheon instance URL (e.g., `https://pantheon.tail164759.ts.net`)
3. Click **Connect**
4. Grant the host permission when prompted
5. You're in! 🎉

## Development

To modify:
- `popup/` — Toolbar dropdown UI
- `sidepanel/` — Chat panel
- `background.js` — Service worker & context menus
- `content.js` — Page content capture
- `config.js` — URL & token storage

The extension uses Manifest V3 with ES modules. No build step needed.
