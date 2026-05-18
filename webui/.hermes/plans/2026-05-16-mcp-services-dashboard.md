# MCP Services Dashboard — Implementation Plan

**Goal:** Replace the ACI.dev-backed connector system with a Pantheon-native MCP Services Dashboard. Users browse a curated catalog of free/self-hosted MCP servers from the Web UI and connect them with one click — no terminal, no config.yaml editing, no Janus.

**Upstream source:** [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) — 6,630 commits, the community-standard curated list of MCP servers. Our catalog is a **verified subset** of this list, filtered by auth tier and tested on our stack. We don't maintain our own parallel list — we pull from upstream and add a `verified` badge.

**Key discovery:** Hermes Agent's CLI already has full MCP server management built in — `hermes mcp add/remove/list/test`. The Web UI backend just needs to **call these CLI commands** as subprocesses. No config.yaml parsing, no gateway reload logic, no process health checks — Hermes handles all of that.

**Design Principles:**
- **Leverage Hermes CLI** — don't reimplement what `hermes mcp` already does
- **No aggregator** — each service gets its own subprocess (handled by Hermes)
- **No third-party dependency** — zero reliance on ACI or any external auth broker
- **Auth tiering** — services ranked by ease of setup; 🔴 Cloud Console–dance services get deprioritized or excluded
- **Grandma-grade** — click Connect → either it just works or you paste one key. That's it.

**Auth Tier Definitions:**

| Tier | UX | Example | In Catalog? |
|------|-----|---------|-------------|
| 🟢 **Zero config** | Install, no further input | Filesystem, Fetch, Playwright, Memory, Git, Time, Sequential Thinking, Everything | ✅ Always |
| 🟡 **Paste a key** | Open settings → paste API key/token in UI field → done | Brave Search (API key), GitHub (PAT), Sentry (DSN) | ✅ When documented |
| 🟠 **Built-in OAuth** | Click Connect → browser popup → Allow. Package handles OAuth, may still need initial credential setup | Some Google Workspace MCPs with bundled OAuth client | ⚠️ Case-by-case |
| 🔴 **Cloud Console dance** | Must create project, enable APIs, configure consent screen, generate credentials | Most Google MCP servers, AWS, Azure | ❌ Skip |

---

## Tasks

### Backend — New `api/mcp_services.py`

**Strategy:** Every operation delegates to `hermes mcp` CLI via subprocess. The API is a thin wrapper — parse catalog YAML, shell out to Hermes, return JSON.

#### Task 1: `hermes mcp` Wrapper Functions
**File:** Create `~/pantheon/webui/api/mcp_services.py`

Three thin wrappers:

```python
import subprocess, json, yaml

HERMES = "hermes"  # or full path

def _mcp_add(name, command, args, env_vars=None):
    """Add an MCP server via hermes mcp add."""
    cmd = [HERMES, "mcp", "add", name,
           "--command", command,
           "--args"] + args
    if env_vars:
        for k, v in env_vars.items():
            cmd += ["--env", f"{k}={v}"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return result.returncode == 0, result.stdout, result.stderr

def _mcp_remove(name):
    """Remove an MCP server via hermes mcp remove."""
    result = subprocess.run(
        [HERMES, "mcp", "remove", name],
        capture_output=True, text=True, timeout=15
    )
    return result.returncode == 0, result.stdout, result.stderr

def _mcp_list():
    """List MCP servers via hermes mcp list. Returns parsed table."""
    result = subprocess.run(
        [HERMES, "mcp", "list"],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode != 0:
        return []
    return _parse_mcp_list_table(result.stdout)
```

**Note:** `hermes mcp list` outputs a formatted table (not JSON). The wrapper parses it. If Hermes later adds `--json` output, switch to that.

#### Task 2: MCP Service Catalog
**File:** Create `~/pantheon/data/mcp-catalog.yaml`

A YAML file where each entry maps to `hermes mcp add` CLI args:

```yaml
- id: filesystem
  name: Filesystem
  category: Local
  description: "Read, write, and manage local files with configurable access controls"
  tier: zero-config
  icon: "📁"
  hermes_args:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "~/pantheon"]
  verified_date: 2026-05-16

- id: brave-search
  name: Brave Search
  category: Search & Web
  description: "Privacy-first web search via Brave's Search API"
  tier: paste-key
  auth_fields:
    - key: BRAVE_API_KEY
      label: "Brave Search API Key"
      hint: "Get a free key at brave.com/search/api"
      url: "https://brave.com/search/api"
  icon: "🔍"  # or SVG path
  hermes_args:
    command: npx
    args: ["-y", "@anthropic/mcp-server-brave-search"]
  verified_date: 2026-05-16
```

The `hermes_args` block maps directly to `hermes mcp add <name> --command <command> --args [args...] --env KEY=VAL`.

**Initial catalog** — seeded with these verified entries:

| id | tier | auth |
|----|------|------|
| filesystem | 🟢 zero-config | none |
| playwright | 🟢 zero-config | none |
| fetch | 🟢 zero-config | none |
| git | 🟢 zero-config | none |
| memory | 🟢 zero-config | none |
| time | 🟢 zero-config | none |
| sequential-thinking | 🟢 zero-config | none |
| brave-search | 🟡 paste-key | `BRAVE_API_KEY` |
| github | 🟡 paste-key | `GITHUB_PERSONAL_ACCESS_TOKEN` |
| sentry | 🟡 paste-key | `SENTRY_TOKEN` |
| sqlite | 🟡 paste-key | file path |

#### Task 3: API Endpoints
**File:** `api/mcp_services.py` (same file)

- `GET /api/mcp-services/catalog` — loads catalog YAML, cross-references with `hermes mcp list` output to set `installed: true/false` per service, returns JSON
- `POST /api/mcp-services/install` — body `{"id": "brave-search", "env": {"BRAVE_API_KEY": "..."}}` → calls `_mcp_add()`, returns result
- `POST /api/mcp-services/uninstall` — body `{"id": "brave-search"}` → calls `_mcp_remove()`, returns result
- `GET /api/mcp-services/status` — calls `hermes mcp list`, returns structured status per service

#### Task 4: Route Mounting
**File:** Modify `~/pantheon/webui/api/routes.py`

Same as before — add route mounts in GET and POST dispatch blocks pointing at the new handlers.

**NO changes needed for:**
- ~~Config.yaml reader/writer~~ — `hermes mcp add` handles it
- ~~Gateway reload logic~~ — `hermes mcp add` handles process lifecycle
- ~~Process health checks~~ — `hermes mcp list` shows status
- ~~Connection testing~~ — `hermes mcp test NAME` handles it
### Frontend — Reuse the Connectors Overlay

#### Task 5: Refactor Existing Overlay
**File:** Modify `~/pantheon/webui/static/index.html`

Change the existing connectors overlay to call the new API:

- `loadConnectorsCatalog()` → calls `/api/mcp-services/catalog` instead of `/api/connectors/catalog`
- `connectConnector(id, auth)` → calls `/api/mcp-services/install` with optional env values
- `disconnectConnector(id)` → calls `/api/mcp-services/uninstall`
- Remove the ACI hint banner (`connectorsAciHint`)
- For 🟡 (paste-key) services, show an inline input field in the card or a modal dialog when Connect is clicked
- For 🟢 (zero-config) services, Connect button just installs immediately
- Show a "status badge" on each installed service: green dot = process running, red dot = error, gray = installed but not running

#### Task 6: Auth Input Modal
**File:** Modify `~/pantheon/webui/static/index.html`

For 🟡 paste-key services, clicking "Connect" opens a small modal with:
- Service name + icon
- Brief description of what it does
- Input field for the key (labeled, e.g., "Brave Search API Key")
- Link to where to get the key (e.g., "Get a key at brave.com/search/api")
- Cancel / Connect buttons

Store the key in the `env` field of the install payload. The backend writes it to config.yaml's `env` block for that service.

#### Task 7: Setting Tab Label Update
**File:** Modify `~/pantheon/webui/static/index.html`

Change the settings sidebar label from "Connectors" to **"Services"** to reflect the scope change (no longer just ACI connectors, now full MCP service management).

---

### Catalog Maintenance

#### Task 8: Service Definition File
**File:** `~/pantheon/webui/api/mcp_services/catalog.yaml` or `~/pantheon/data/mcp-catalog.yaml`

Move the catalog from a Python list to a standalone YAML file so it can be:
- Version-controlled separately
- PR'd by the community
- Validated with a schema check
- Loaded dynamically without code changes

Each service entry has:
```yaml
- id: brave-search
  name: Brave Search
  category: Search & Web
  description: "Privacy-first web search via Brave's Search API"
  auth: api_key
  tier: paste-key
  homepage: https://github.com/anthropics/mcp-server-brave-search
  icon: https://cdn.jsdelivr.net/gh/simple-icons/simple-icons/icons/brave.svg
  verified_date: 2026-05-16
  reviewed_by: hermes
  config:
    transport: stdio
    command: npx
    args: ["-y", "@anthropic/mcp-server-brave-search"]
    env_template:
      BRAVE_API_KEY: ""
```

#### Task 9: Add Service Verification Script
**File:** create `~/.hermes/scripts/verify-mcp-service.py`

One-shot script to test an MCP server:
1. Register it in a temporary config
2. Spawn the process
3. Wait for tools/list response
4. Print tool names and exit
5. Clean up

Used when vetting new additions to the catalog. Can be run manually or in CI.

---

## Files Changed / Created

| File | Action |
|------|--------|
| `~/pantheon/webui/api/mcp_services.py` | **Create** — catalog, install/uninstall, status |
| `~/pantheon/webui/api/routes.py` | **Modify** — add route mounts, keep old connector routes for now |
| `~/pantheon/webui/static/index.html` | **Modify** — refactor overlay to call new API, add auth modal, relabel tab |
| `~/pantheon/webui/static/style.css` | **Modify** — minor additions for auth input modal |
| `~/pantheon/webui/api/connectors.py` | **Deprecate** — keep file but mark as legacy. Remove after migration confirmed |
| `~/pantheon/data/mcp-catalog.yaml` | **Create** — standalone catalog definition |
| `~/.hermes/scripts/verify-mcp-service.py` | **Create** — verification script |

## Verification

1. Open Settings → "Services" tab → see category grid with service counts
2. Click a category → see service cards with auth badges
3. Click Connect on a 🟢 zero-config service → installs instantly, green status dot appears
4. Click Connect on a 🟡 paste-key service → modal appears → paste key → installs
5. Click Disconnect → service removed from config.yaml, status dot goes gray
6. Refresh page → installed services show as connected
7. `cat ~/.hermes/config.yaml` → new `mcp_servers` entries present with correct format

## Rollout

1. **Phase 1** — Backend only: create `mcp_services.py` with catalog + install/uninstall + status. Wire routes. Test via curl.
2. **Phase 2** — Frontend: refactor overlay to call new API. Add auth modal. Relabel tab.
3. **Phase 3** — Catalog expansion: run verification script on Tier 2 services, add community-submitted definitions.
4. **Phase 4** — Cleanup: archive `connectors.py` once migration confirmed.
