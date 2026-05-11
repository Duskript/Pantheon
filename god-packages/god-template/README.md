# Template — A Pantheon God

This is a template package for creating new Pantheon gods.

## Files

| File | Purpose |
|------|---------|
| `god.yaml` | Manifest — name, version, type, model, studios |
| `harness.yaml` | God harness — identity, routing, guardrails, failure behavior |
| `prompts/` | Personality/system prompts (add identity.md here) |
| `plugins/` | Hermes tool plugins (add Python plugins here) |
| `assets/` | Static files and reference data |

## How to Use

1. Copy this directory: `cp -r ~/pantheon/god-packages/god-template/ ~/god-packages/god-{your-god-id}/`
2. Edit `god.yaml` — fill in your god's name, version, type, etc.
3. Edit `harness.yaml` — write the identity, routing, and guardrails
4. Add any prompts, plugins, or assets
5. Install: `pantheon-install ~/god-packages/god-{your-god-id}/`
6. Add to `~/pantheon/gods/gods.yaml` — register the god in the active roster
7. **Add MCP server config** — add this block to the god's Hermes profile config at `~/.hermes/profiles/{god-id}/config.yaml`:

```yaml
mcp_servers:
  pantheon:
    url: "http://127.0.0.1:8010/mcp"
    timeout: 60
```

This gives the god access to `mcp_pantheon_*` tools: athenaeum_search, messaging_send, god_list, system_health, etc. See the MCP Inter-God Bus section in the pantheon-god-architecture skill for full details.

8. **Register heartbeat** (if scheduled/cron-driven) — run:
   ```bash
   cd ~/pantheon && python3 scripts/heartbeat.py register <god-id> \
     --label "God Name — Description" \
     --interval <expected_interval_min>
   ```
   Then add `beat("<god-id>")` at the end of the god's run function.
   This lets The Fates monitor uptime and alert if the god stops running.

## About MCP Tools

Every new god automatically gets these MCP tools once the server config is added:

| Tool | What it does |
|------|-------------|
| `mcp_pantheon_athenaeum_search` | Semantic search across all Codexes |
| `mcp_pantheon_athenaeum_read` | Read any file from the Athenaeum |
| `mcp_pantheon_athenaeum_walk` | Browse the Athenaeum index tree |
| `mcp_pantheon_athenaeum_write` | Write new knowledge to the Athenaeum |
| `mcp_pantheon_athenaeum_list_codexes` | List all Codices |
| `mcp_pantheon_messaging_send` | Send messages to any god's inbox |
| `mcp_pantheon_messaging_check_inbox` | Check your own or another god's inbox |
| `mcp_pantheon_hades_get_report` | Get the latest consolidation report |
| `mcp_pantheon_god_list` | List all registered gods |
| `mcp_pantheon_system_health` | Check Pantheon infrastructure status |
| `mcp_pantheon_skill_list` | List all shared skills in the Pantheon skills hub |
| `mcp_pantheon_skill_info` | Get detailed info about a specific skill |
| `mcp_pantheon_skill_run` | Execute a shared skill by name with arguments |

## Pantheon Skills Hub

The Pantheon has a **shared skills hub** at `/home/konan/athenaeum/skills/`. These are universal, reusable tasks that any god can execute via MCP.

**How it works:**
- Skills live in subdirectories under `athenaeum/skills/`, each with a `skill.yaml` manifest and a Python script
- Any god connected to the MCP server can list, inspect, and run them
- To add a new universal skill: create `<skill-name>/skill.yaml` + `<skill-name>/scripts/<script>.py`

**Available MCP tools for skills:**
- `mcp_pantheon_skill_list` — discover available skills
- `mcp_pantheon_skill_info` — inspect a skill's arguments
- `mcp_pantheon_skill_run` — execute a skill with given args

**Example — capture an idea via MCP:**
```json
mcp_pantheon_skill_run({
  "name": "capture-idea",
  "arguments": "[\"My Idea\", \"Description of the idea\"]"
})

## Monitor Your Inbox

Every god must check their inbox at session start. This is how Hermes, The Fates, and other gods pass you information between sessions.

**Inbox location:** `~/pantheon/gods/messages/{god-id}/`
**MCP tool:** `mcp_pantheon_messaging_check_inbox`

Add this to your session-start routine — read unread messages and mark them read immediately. Without this, you'll miss alerts, directives from Hermes, and inter-god coordination.
