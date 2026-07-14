# Pantheon Core Plugin

Phase B of the Pantheon unified-upgrade plan.

## What it does

- Registers the full Hermes lifecycle hook surface for Pantheon.
- Stays **no-op by default**.
- Supports **comparison mode** logging under:

```text
$HERMES_HOME/hooks/pantheon-core/comparison/
```

## Hooks

| Hook | Default | Enabled behavior |
|------|---------|------------------|
| `pre_llm_call` | `None` | Injects memory context via Ichor |
| `pre_tool_call` | `None` | Blocks via Ichor gate pipeline when `hooks.gates: true` |
| `post_tool_call` | `None` | Records outcomes / episodic traces |
| `on_session_start` | `None` | Counts inbox items and logs continuity state |
| `on_session_finalize` | `None` | Writes a session digest and compaction stub |

## Enablement

Add the plugin to `plugins.enabled` in `~/.hermes/config.yaml`:

```yaml
plugins:
  enabled:
    - pantheon-core
```

Then toggle behavior with the `hooks.*` flags in config.
