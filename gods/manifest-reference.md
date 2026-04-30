# Pantheon God SDK — Manifest Schema Reference
# Version: 1.0.0
# Maintainer: Hephaestus

## Overview

Every god in the Pantheon is defined by a `god.yaml` manifest file. This
document describes every field, its purpose, and whether it's required.

The god package structure:
```
god-{id}/
├── god.yaml          # Manifest (required)
├── harness.yaml      # Harness YAML (required)
├── prompts/          # Personality/system prompts (optional)
│   └── identity.md
├── plugins/          # Hermes tool plugins (optional)
├── assets/           # Static files, reference data (optional)
└── README.md         # Description (optional)
```

---

## Schema Fields

### Required

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | integer | Must be `1`. Reserved for future schema changes. |
| `id` | string | Unique identifier. Used for directory name (`god-{id}`), routing path, and registry key. Lowercase, hyphens only, no spaces. Example: `god-apollo`, `god-hestia` |
| `name` | string | Display name — capitalized, human-readable. Example: `Apollo`, `Hestia` |
| `version` | string | Semantic version string. Must follow semver (`X.Y.Z`). Tracks installation history. |
| `type` | string | One of: `conversational`, `service`, `subsystem`. Determines how the god operates. |
| `description` | string | One-line summary of what the god does. Displayed in `pantheon-list-gods`. |

### Optional — Conversational Gods

| Field | Type | Description |
|-------|------|-------------|
| `model` | string | LLM model to use (e.g. `gemma4`, `claude-sonnet-4`). Required for `type: conversational`. |
| `sanctuary` | string | Thematic domain name. Displayed in god listings. Example: `"The Kitchen"`, `"The Library"` |
| `studios` | list[string] | Specializations this god offers. Displayed in listings. Example: `["lyric-writing", "poetry"]` |

### Optional — All Types

| Field | Type | Description |
|-------|------|-------------|
| `author` | string | Creator name. Helps with provenance when sharing gods. |
| `private` | boolean | If `true`, this god is excluded from any future public listings. Default: `false`. |
| `athenaeum_codex` | boolean | If `true`, a Codex directory is auto-created at `~/athenaeum/Codex-{Name}/`. Default: `false`. |
| `dependencies` | list[string] | IDs of other gods this god depends on. Reserved for future dependency resolution. Example: `["pantheon-core", "hermes"]` |
| `tags` | list[string] | Categorization tags for search/discovery. Example: `["music", "creative", "suno"]` |

---

## Example: Conversational God

```yaml
schema_version: 1
id: god-apollo
name: Apollo
version: 1.0.0
type: conversational
author: Konan
private: true
description: Lyric-writing and poetry god for Suno music creation
model: gemma4
sanctuary: The Muses' Summit
studios:
  - lyric-writing
  - poetry
athenaeum_codex: true
tags:
  - music
  - creative
  - s uno
```

## Example: Service God

```yaml
schema_version: 1
id: hecate
name: Hecate
version: 1.0.0
type: service
author: Pantheon Core
description: Intent classifier — routes user requests to the correct god
model: gemma4
```

## Example: Subsystem God

```yaml
schema_version: 1
id: demeter
name: Demeter
version: 1.0.0
type: subsystem
author: Pantheon Core
description: Ingestion pipeline — file watching, content classification, ingestion
```

---

## Version History

Each install/upgrade leaves a trail. The registry (`pantheon-registry.yaml`)
tracks the current version. For full history, Hades distills install events
from vault logs into the Athenaeum.

| Action | Registry Change | Hermes Notified | Graph Updated |
|--------|----------------|-----------------|---------------|
| Install | Entry added with version | Yes | Yes (node created) |
| Uninstall | Entry removed | Yes | Yes (node + edges removed) |
| Upgrade | Version field updated | Yes | Yes (version property updated) |
