# Template — A Pantheon God

This is a template package for creating new Pantheon gods.

## Files

| File | Purpose |
|------|---------|
| `god.yaml` | Manifest — name, version, type, model, studios |
| `harness.yaml` | God identity + operational protocols (SOUL.md equivalent): identity, domain, shared brain, topic-shift, notifications, guardrails |
| `prompts/persona.md.example` | Example personality file — define the god's voice, speech patterns, character |
| `prompts/identity.md` | (optional) Additional system prompts |
| `plugins/` | Hermes tool plugins (add Python plugins here) |
| `assets/` | Static files and reference data |

The god's identity is split across two files:
- **`harness.yaml`** — *what* the god does: identity, domain, operational protocols (shared brain, topic-shift, notifications, delegation, guardrails)
- **`persona.md`** — *who* the god is: voice, speech patterns, personality traits, catchphrases

## How to Use

1. Copy this directory: `cp -r ~/pantheon/god-packages/god-template/ ~/god-packages/god-{your-god-id}/`
2. Edit `god.yaml` — fill in your god's name, version, type, etc.
3. Edit `harness.yaml` — write the identity, domain, shared brain, topic-shift, notifications, and guardrails
4. Create `prompts/persona.md` — define the god's voice and personality using `persona.md.example` as a starting point
5. Add any extra prompts, plugins, or assets
6. Install: `pantheon-install ~/god-packages/god-{your-god-id}/`
7. Add to `~/pantheon/gods/gods.yaml` — register the god in the active roster
8. Add `mcp_servers` to the god's Hermes profile config at `~/.hermes/profiles/{god-id}/config.yaml`:

```yaml
mcp_servers:
  pantheon:
    url: "http://127.0.0.1:8010/mcp"
    timeout: 60
```

This gives the god access to `mcp_pantheon_*` tools: athenaeum_search, god_list, system_health, etc.

9. **Shared context is automatic** — the harness.yaml already includes the Shared Context protocol. Every new god is born with awareness of `~/pantheon/shared/`. No extra configuration needed.

10. **Notifications are built in** — the harness.yaml includes the Notifications protocol with `god-notify`. Every god can push success/error/info/warning notifications to the user.

11. **Register heartbeat** (if scheduled/cron-driven) — run:
   ```bash
   cd ~/pantheon && python3 scripts/heartbeat.py register <god-id> \
     --label "God Name — Description" \
     --interval <expected_interval_min>
   ```
   Then add `beat("<god-id>")` at the end of the god's run function.

## What the Harness Gives You

The harness.yaml includes ALL of these standard protocols — no need to add them by hand:

| Section | What it does |
|---------|-------------|
| **Identity** | Domain, persona reference, interaction pattern |
| **Filesystem Access** | Allowed paths + hard off-limits |
| **MCP Tools** | Full pantheon tool list for cross-god coordination |
| **Topic-Shift Detection** | Auto-compaction protocol with configurable thresholds |
| **Shared Brain Protocol** | memory.md + journal workflow for persistent memory |
| **Delegation** | (optional) Sub-agent spawning for parallel work |
| **Shared Context** | Cross-god awareness via `~/pantheon/shared/` |
| **Guardrails** | Hard stops + soft boundaries |
| **Failure Behavior** | What to do when things go wrong |

## MCP Tools

Every new god automatically gets these MCP tools once the server config is added:

| Tool | What it does |
|------|-------------|
| `mcp_pantheon_athenaeum_search` | Semantic search across all Codexes |
| `mcp_pantheon_athenaeum_read` | Read any file from the Athenaeum |
| `mcp_pantheon_athenaeum_walk` | Browse the Athenaeum index tree |
| `mcp_pantheon_athenaeum_write` | Write new knowledge to the Athenaeum |
| `mcp_pantheon_athenaeum_list_codexes` | List all Codices |
| `mcp_pantheon_hades_get_report` | Get the latest consolidation report |
| `mcp_pantheon_god_list` | List all registered gods |
| `mcp_pantheon_system_health` | Check Pantheon infrastructure status |
| `mcp_pantheon_skill_list` | List all shared skills in the Pantheon skills hub |
| `mcp_pantheon_skill_info` | Get detailed info about a specific skill |
| `mcp_pantheon_skill_run` | Execute a shared skill by name with arguments |

## Pantheon Skills Hub

The Pantheon has a **shared skills hub** at `~/athenaeum/skills/`. These are universal, reusable tasks that any god can execute via MCP.

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
```

## Note on Inbox Checking

Older gods may have a "check your inbox at session start" step in their Shared Brain Protocol. This pattern is now **obsolete** — notifications are push-based via `god-notify`. New gods created from this template do NOT include inbox checking. If you're updating an existing god, remove the inbox check line from their SOUL.md.
