# Connecting AionUi to Pantheon via MCP

## Overview

AionUi is a desktop/web UI for AI agents. It has native MCP client support,
which means it can connect to the Pantheon MCP server and use all Pantheon
tools (athenaeum_search, messaging, etc.) directly — no bridge code needed.

## Prerequisites

- Pantheon MCP server running on the same network (or localhost)
- Node.js 18+ installed
- AionUi installed

## Installation

On the Ubuntu machine:

```bash
# Install AionUi
git clone https://github.com/iOfficeAI/AionUi.git
cd AionUi
npm install

# Start in WebUI mode (accessible from browser)
npx aion --webui --port 3000
```

## Configuration

Create or edit `~/.aionui/config.yaml` (platform-specific path may vary):

```yaml
mcp_servers:
  pantheon:
    url: "http://127.0.0.1:8010/mcp"  # or Ubuntu server IP:8010
    timeout: 60

# Optionally, configure the UI to show Pantheon tools
default_model: mcp/pantheon
```

Alternatively, add via the AionUi settings UI:
1. Open AionUi in browser at `http://localhost:3000`
2. Go to Settings → MCP Servers
3. Add server: Name=`pantheon`, URL=`http://127.0.0.1:8010/mcp`
4. Save and restart

## What You Get

Once connected, the following tools appear in AionUi:

| Tool | Purpose |
|------|---------|
| `athenaeum_search` | Semantic search across all Codices |
| `athenaeum_read` | Read any file from the Athenaeum |
| `athenaeum_walk` | Browse the Athenaeum index tree |
| `athenaeum_write` | Write new knowledge to the Athenaeum |
| `athenaeum_list_codexes` | List all available Codices |
| `messaging_send` | Send messages to any god |
| `messaging_check_inbox` | Check a god's inbox |
| `hades_get_report` | Get the latest Hades consolidation report |
| `god_list` | List all registered gods |
| `system_health` | Check Pantheon infrastructure status |

## Multi-God Setup (Team Rooms)

1. Create a team room for each god (e.g., "Hephaestus", "Apollo", "Hermes")
2. In each room, the model can call `messaging_send` to communicate with other gods
3. Hades reports and system notifications deliver via messaging — visible in AionUi

## Network Access (Optional)

To access AionUi from outside the Ubuntu machine:

```bash
# Option 1: SSH tunnel
ssh -L 3000:localhost:3000 konan@ubuntu-server

# Option 2: Bind to 0.0.0.0 (with auth configured)
npx aion --webui --port 3000 --host 0.0.0.0
```

## Remote MCP Access (Optional)

To access the Pantheon MCP server from another machine:

```bash
# SSH tunnel for MCP
ssh -L 8010:localhost:8010 konan@ubuntu-server
```

Then configure AionUi on the local machine to use `http://localhost:8010/mcp`.

## Troubleshooting

- **Tools not appearing in AionUi**: Restart both AionUi and the MCP server.
  The server must be running before AionUi starts.
- **Search fails**: Verify the OPENROUTER_API_KEY is available to the MCP server
  (it's loaded from `~/.hermes/profiles/hephaestus/.env` at startup).
- **Connection refused**: Run `systemctl --user status pantheon-mcp` to verify
  the MCP server is running.
