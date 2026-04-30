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

1. Copy this directory: `cp -r god-template god-{your-god-id}`
2. Edit `god.yaml` — fill in your god's name, version, type, etc.
3. Edit `harness.yaml` — write the identity, routing, and guardrails
4. Add any prompts, plugins, or assets
5. Install: `pantheon-install god-{your-god-id}/`
