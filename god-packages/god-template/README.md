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
