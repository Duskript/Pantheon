# Janus — Self-Hosted MCP Connector Hub

**Status:** Architecture draft  
**God:** Janus (Roman god of doorways, passages, transitions)  
**Principle:** Zero cloud, zero OAuth broker, entirely self-hosted.

---

## Concept

Janus is a standalone MCP server that **aggregates and manages** multiple child MCP servers under one namespace with encrypted auth storage. You add a service → paste your API key (or complete an OAuth flow) → Janus spawns that service's MCP server → your agent gets the tools.

Designed as a standalone Python package (`pip install janus-mcp`) that works with any MCP-compatible client (Hermes, Claude Code, Codex Copilot, etc.), with optional deeper integration into Pantheon's WebUI.

---

## Community Registry ([janus-registry](https://github.com/Duskript/janus-registry))

Services are NOT hardcoded into Janus. Instead, they live in a **community git repository** — one YAML file per service, PR-driven, forkable, zero hosting cost.

```
github.com/Duskript/janus-registry/
├── INDEX.md                    # "45 services available across 8 categories"
├── services/
│   ├── github.yaml             # Each file is one service definition
│   ├── gmail.yaml
│   ├── brave-search.yaml
│   ├── notion.yaml
│   ├── postgres.yaml
│   └── ...
└── CONTRIBUTING.md             # How to add a new service (it's just YAML)
```

### Service definition format (one `.yaml` per service)

```yaml
# services/github.yaml
name: GitHub
package: "@modelcontextprotocol/server-github"
runner: npx
args: []
auth:
  type: pat                          # pat | apikey | oauth | none
  env_var: GITHUB_PERSONAL_ACCESS_TOKEN
  setup_url: "https://github.com/settings/tokens"
  setup_hint: "Create a classic PAT with repo and user scopes."
category: "Dev Tools"
icon: "github"
description: "Source code hosting, issues, PRs, repos"
```

To add a new service: fork, create `servicename.yaml`, PR. No code. No build step.

### How Janus consumes the registry

```bash
janus search                      # Fetches INDEX.md, shows all available
janus search database             # Filters to matching services
janus info github                 # Shows full definition + auth instructions
janus install github              # Downloads github.yaml → ~/.config/janus/services.d/
janus install github --connect    # Download + prompt for token + start serving
janus update                      # Pulls latest INDEX.md from registry
```

Services are cached locally in `~/.config/janus/services.d/` so Janus works offline after install. The `update` command refreshes the local cache against the registry HEAD.

---

## Architecture

```
 MCP client                    LOCAL MACHINE
┌─────────────┐    stdio     ┌──────────────────────────────────────┐
│  Hermes (or │◄───────────►│         Janus Aggregator              │
│  anything)  │              │                                      │
└─────────────┘              │  ┌────────────────────────────────┐  │
                             │  │  Service Registry              │  │
                             │  │  - Built-in catalog (20+ svcs) │  │
                             │  │  - Custom services/ .yaml      │  │
                             │  └────────────┬───────────────────┘  │
                             │               │                      │
                             │  ┌────────────▼───────────────────┐  │
                             │  │  Service Manager               │  │
                             │  │  - Spawns child MCP subprocess │  │
                             │  │  - Proxies list_tools/call_tool│  │
                             │  │  - Health check + restart      │  │
                             │  └────────────┬───────────────────┘  │
                             │               │                      │
                             │  ┌────────────▼───────────────────┐  │
                             │  │  Auth Vault                    │  │
                             │  │  - Fernet-encrypted token store │  │
                             │  │  - Key derived from master pass │  │
                             │  │  - File: ~/.config/janus/vault │  │
                             │  └────────────────────────────────┘  │
                             │                                      │
                             │  Subprocesses:                       │
                             │  ├── npx @mcp/server-github          │
                             │  ├── npx @mcp/server-brave-search    │
                             │  ├── uvx mcp-server-gmail            │
                             │  └── ...                             │
                             └──────────────────────────────────────┘
```

**Key insight:** Janus is an MCP server that talks to other MCP servers. It presents a single stdio connection to the client but internally routes to `N` child servers. This is the same pattern as ACI but fully local — the broker is a Python process on your own machine.

---

## Tool Naming Convention

All child tools are namespaced so the client sees unique names:

```
janus_{service_key}_{child_tool_name}
```

Examples:
- `janus_github_list_issues`
- `janus_github_get_pull_request`
- `janus_gmail_send_email`
- `janus_brave_search_web`
- `janus_notion_query_database`

The `list_tools()` response includes a human-readable description per tool so the LLM knows what's available.

---

## Service Definition Format

Services are defined in YAML — either built into Janus or dropped into a `services.d/` directory.

### Built-in Catalog (Python dicts)

```python
SERVICES = {
    "github": {
        "name": "GitHub",
        "package": "@modelcontextprotocol/server-github",
        "runner": "npx",
        "args": [],
        "auth": {
            "type": "pat",           # pat | apikey | oauth | none
            "env_var": "GITHUB_PERSONAL_ACCESS_TOKEN",
            "setup_url": "https://github.com/settings/tokens",
            "scopes": ["repo", "read:user"],
            "setup_hint": "Create a classic PAT with repo and user scopes."
        },
        "category": "Dev Tools",
        "icon": "github",
        "desc": "Source code hosting, issues, PRs, repos"
    },
    "gmail": {
        "name": "Gmail",
        "package": "@modelcontextprotocol/server-gmail",
        "runner": "npx",
        "args": [],
        "auth": {
            "type": "oauth",
            "oauth_config": {
                "client_id_env": "GMAIL_CLIENT_ID",
                "client_secret_env": "GMAIL_CLIENT_SECRET",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly",
                           "https://www.googleapis.com/auth/gmail.send"],
                "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_url": "https://oauth2.googleapis.com/token",
            },
            "setup_url": "https://console.cloud.google.com/apis/credentials",
            "setup_hint": "Create OAuth 2.0 credentials, download client ID + secret."
        },
        "category": "Communication",
        "icon": "mail",
        "desc": "Read, send, and manage Gmail messages"
    },
}
```

### Custom Service Files (`~/.config/janus/services.d/*.yaml`)

Users can add unsupported services by dropping in a YAML file:

```yaml
# ~/.config/janus/services.d/my-custom.yaml
key: my-custom
name: My Custom API
package: some-mcp-server-package
runner: npx
args: ["-y", "some-mcp-server-package", "--flag", "value"]
auth:
  type: apikey
  env_var: MY_CUSTOM_API_KEY
  setup_url: "https://example.com/api-keys"
  setup_hint: "Generate an API key from the dashboard."
```

Janus watches this directory for changes (or loads on restart).

---

## Auth Vault

Secrets need to live somewhere. We can't use plaintext env vars because:
1. Some services need OAuth refresh tokens — too complex for env vars
2. Users shouldn't edit config files to paste API keys
3. A service catalog grows past the point where env vars are ergonomic

### Vault Architecture

```
~/.config/janus/
├── vault                    # Fernet-encrypted blob (binary)
├── vault.key                # Master key file (0600) — OR —
├── services.d/              # Custom service definitions
│   └── my-custom.yaml
└── connections.yaml         # Which services are enabled + their vault keys
```

### Encryption

```
master_password (user-supplied or env var JANUS_MASTER_KEY)
    │  (or generate from system keyring: keyctl, secret-service, etc.)
    ▼
Fernet key (32-byte base64-urlsafe)
    │
    ▼
Fernet.encrypt(json.dumps(vault_dict))
    │
    ▼
~/.config/janus/vault  (binary blob)
```

### Vault Contents

```json
{
  "github": "ghp_xxxxxxxxxxxxxxxxxxxx",
  "brave_search": "BSAxxxxxxxxxxxxx",
  "gmail_client_id": "12345.apps.googleusercontent.com",
  "gmail_client_secret": "GOCSPX-xxxxx",
  "gmail_refresh_token": "1//0xxxxx"
}
```

### Key Derivation Priority

1. `JANUS_MASTER_KEY` env var (for headless/systemd setups)
2. System keyring via `keyring` Python package
3. Auto-generated key stored at `~/.config/janus/vault.key` (first-run convenience)
4. Prompt via CLI

---

## MCP Proxy Protocol

When a client connects to Janus:

### `list_tools()`

```python
{
    "tools": [
        {
            "name": "janus_github_list_issues",
            "description": "List issues in a GitHub repository",
            "inputSchema": {...}  # from child server
        },
        {
            "name": "janus_brave_search_web",
            "description": "Search the web using Brave Search",
            "inputSchema": {...}
        },
    ]
}
```

### `call_tool(name, arguments)`

1. Parse `janus_{service_key}_{tool_name}` → extract `service_key`, `tool_name`
2. Look up child server connection for `service_key`
3. Forward `call_tool(tool_name, arguments)` to child server via stdio
4. Return response

### Disconnected Service Handling

If a child server is down, Janus returns a structured error:

```json
{
    "error": true,
    "message": "Service 'github' is not connected. Run: janus connect github"
}
```

---

## CLI Interface

```
Usage: janus [command] [options]

Commands:
  list                List all known services and their status
  ls                  Alias for list
  add <service>       Configure and authenticate a service
  connect <service>   Alias for add
  remove <service>    Disconnect and remove auth for a service
  rm                  Alias for remove
  
  serve               Start the MCP aggregator server (stdio mode)
  start [--port N]    Start as HTTP SSE server on port (default 8011)
  
  catalog             Show the full catalog of available services
  info <service>      Show details for a specific service
  
  vault init          Initialize/rekey the encrypted vault
  vault update <key> <value>  Update a vault entry (CLI)
```

### Usage Examples

```bash
# First time — init vault
janus vault init

# Add a service
janus add github
# -> Paste your GitHub PAT: ****
# -> Service 'github' configured and connected.

# Start the MCP server
janus serve  # writes tools to stdout, reads calls from stdin

# Use with any MCP client:
# hermes config.yaml:
#   mcp_servers:
#     janus:
#       command: janus
#       args: ["serve"]
#       env:
#         JANUS_MASTER_KEY: "your-key-here"
```

---

## WebUI Integration (Pantheon)

The existing **Connectors** panel in the Pantheon WebUI becomes the front door for Janus. The already-built `connectors.py` ACI-backend gets replaced by a Janus backend:

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/janus/catalog` | GET | List all available services from Janus registry |
| `/api/janus/status` | GET | Which services are connected/disconnected |
| `/api/janus/connect` | POST | Connect a service (store token) |
| `/api/janus/disconnect` | POST | Disconnect + clear stored token |
| `/api/janus/logs` | GET | Recent log tail for a service subprocess |
| `/api/janus/restart` | POST | Restart a specific service subprocess |

The WebUI would:
1. Show the service catalog grouped by category
2. Connected vs available count per category
3. "Connect" button → prompts for API key / PAT / OAuth flow
4. Connected services show green badge, tool count
5. Disconnect button to remove

### OAuth Flow (Phase 2)

For OAuth services (Gmail, Google Calendar, Slack), the WebUI needs a callback handler. Janus starts a mini HTTP server on a random port for the callback. The flow:

1. User clicks "Connect Gmail" in WebUI
2. Janus starts local OAuth callback server → returns redirect URL
3. User is redirected to Google OAuth consent screen
4. Google redirects to Janus's local callback server
5. Janus exchanges code for tokens, stores in vault, redirects user back to Pantheon
6. WebUI shows "Connected ✓"

For headless/systemd setups, the OAuth flow can be done once via CLI (`janus add gmail --oauth`) which opens the browser.

---

## Module Structure

```
janus-hub/
├── pyproject.toml
├── janus/
│   ├── __init__.py          # Package metadata, version
│   ├── __main__.py          # python -m janus entry point
│   ├── cli.py               # CLI interface (click or argparse)
│   ├── server.py            # MCP server (aggregator)
│   ├── service_manager.py   # Spawn/monitor child MCP servers
│   ├── proxy.py             # Tool proxying logic (list + call)
│   ├── registry.py          # Service catalog (built-in + custom)
│   ├── vault.py             # Encrypted token storage
│   └── oauth.py             # OAuth callback server (phase 2)
├── janus-hooks/
│   └── pantheon/            # Pantheon WebUI integration (optional)
│       └── connector.py     # JanusConnector class for routes.py
└── tests/
    ├── test_proxy.py
    ├── test_vault.py
    └── test_service_manager.py
```

---

## MVP vs Phase 2

### MVP (could ship this week)

| Feature | Detail |
|---------|--------|
| `janus serve` | Stdio MCP server that spawns child servers, proxies tools |
| Built-in catalog | 6-8 services: github, brave-search, puppeteer, notion, linear, filesystem |
| Vault (file-based) | Encrypted token store with `JANUS_MASTER_KEY` env var |
| `janus add/remove/list` | CLI for managing connections |
| Custom services | `services.d/*.yaml` support |
| Hermes integration | Just add to `mcp_servers` in config.yaml |
| Auth types | `pat`, `apikey`, `none` |

### Phase 2

| Feature | Detail |
|--------|---------|
| OAuth flow | Google, Slack, Notion, etc. with local callback server |
| WebUI integration | Replace ACI backend in Pantheon Connectors panel |
| Service health monitoring | Auto-restart crashed child servers, circuit breaker |
| System keyring | `keyring` Python package for master key |
| HTTP/SSE transport | Janus as HTTP MCP server for remote clients |
| Service auto-discovery | Scan for installed MCP servers on PATH |

---

## Integration Points

### With Hermes Agent

Just one entry in `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  janus:
    command: janus
    args: ["serve"]
    env:
      JANUS_MASTER_KEY: "your-generated-key"
```

All `janus_*` tools appear alongside Hermes's native tools. No ETL, no bridges, no webhooks.

### With Pantheon WebUI

Replace the ACI-backed `api/connectors.py` with a Janus-facing equivalent. The existing Connectors panel HTML/CSS/JS already works — just swap the backend:

- `handle_get_catalog()` → reads from Janus's registry + vault
- `handle_post_connect()` → runs `janus add <service>` in a subprocess
- `handle_post_disconnect()` → runs `janus remove <service>`

### With Any Other MCP Client

Janus is just an MCP server. Any client that speaks MCP stdio can use it:

- Claude Desktop: `"mcpServers": {"janus": {"command": "janus", "args": ["serve"]}}`
- Codex CLI: supported via config
- OpenCode: supported via config
- Cursor: supported via config

---

## Design Decisions

### Why a subprocess manager instead of Python imports?

Each MCP server has its own dependencies, version conflicts, and runtime
requirements. Running them as subprocesses with `npx`/`uvx`/`pipx` means:
- No dependency conflicts with Janus itself
- Each server gets its own environment
- Servers can be in any language (Node, Python, Go, Rust)
- Killed servers don't take down the whole hub

### Why not just use Hermes's native MCP client directly?

Hermes already supports multiple `mcp_servers` in config.yaml. The gap that
Janus fills:

1. **Auth management** — You'd need to paste API keys into config.yaml
   in plaintext and manage them manually. Janus provides encrypted storage.
2. **Service discovery** — No catalog, no "what's available?" experience.
3. **Ease of use** — `janus add gmail` vs. "find the MCP server, install it,
   configure OAuth, add to config.yaml, restart."
4. **Portability** — Janus works with any MCP client, not just Hermes.
