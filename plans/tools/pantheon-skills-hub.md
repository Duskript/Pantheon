# Pantheon Skills Hub MCP Server — Build Spec v1

> **Status:** Draft
> **Author:** Thoth
> **Builder:** Hephaestus
> **Target:** Hermes Agent MCP Server

## Purpose

A unified MCP server that catalogs, searches, and installs AI agent skills across all sources — local installed skills, Pantheon's curated collection, and upstream skill marketplaces. Enables on-demand discovery and installation without manual git clone operations.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│             Pantheon Skills Hub (MCP Server)          │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐ │
│  │  Search      │  │  Install     │  │  Catalog   │ │
│  │  Engine      │  │  Engine      │  │  Manager   │ │
│  └──────┬───────┘  └──────┬───────┘  └─────┬──────┘ │
│         │                 │                 │        │
│  ┌──────┴─────────────────┴─────────────────┴──────┐ │
│  │              Index / Cache Layer                  │ │
│  │  (SQLite FTS5 for full-text search across skills) │ │
│  └──────────────────────┬───────────────────────────┘ │
│                         │                              │
│  ┌──────────────────────┴───────────────────────────┐ │
│  │              Source Resolver                       │ │
│  │  installed/ → curated/ → upstream/ → catalog/     │ │
│  └──────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

## Skill Source Tiers

### Tier 1: Installed (~/.hermes/skills/)
Skills already on disk. Read-only search target.

### Tier 2: Pantheon Curated (~/pantheon/skills-hub/curated/)
Our vetted collection. Skills we've tested, approved, and potentially customized. These get a `pantheon_rating` and `pantheon_notes` in the index.

### Tier 3: Upstream Tracked (in MONITORED_REPOS)
Repos we track for updates but may not have installed locally. Pre-indexed metadata (name, description, source, version) for searchability.

### Tier 4: Catalog (discoverable but unindexed)
Repos we know about but haven't fetched yet. URLs stored, skills fetched on demand via search.

## MCP Tools

### `skills_search(query: str, tiers: str = "all")`

Search all skill sources for matching skills. Returns ranked results with:
- Skill name, description, source repo, tier
- Relevance score
- Installation status (installed/available/curated)
- Version info

```
SkillsSearchResult[] {
  name: string,
  description: string,
  source: "installed" | "curated" | "upstream" | "catalog",
  repo: string,            // e.g., "obra/superpowers"
  tier: number,            // 1-4
  installed: boolean,
  version?: string,
  pantheon_rating?: "vetted" | "experimental" | "unreviewed",
  path?: string            // filesystem path if installed
}
```

### `skills_install(name: str, source: str, tier: int)`

Install a skill from any source to the installed skills directory.

1. Resolve the skill's source location
2. If from an upstream repo: git clone → copy SKILL.md + references to ~/.hermes/skills/{name}/
3. If from catalog: git clone the whole repo → extract skill → install
4. If already installed: prompt before overwrite
5. Update the search index

### `skills_list(filters: str = "all")`

List skills with optional filtering:
- `installed` — only locally installed
- `curated` — only Pantheon-vetted
- `upstream` — available from tracked repos
- `all` — everything

### `skills_catalog_add(repo_url: str, name: str)`

Register a new upstream repo for cataloging:
1. Clone repo (shallow, no checkout)
2. Scan for SKILL.md files
3. Extract frontmatter (name, description, version)
4. Add to search index
5. Add to MONITORED_REPOS config

### `skills_catalog_refresh()`

Re-scan all registered upstream repos for new/changed skills. Updates the search index.

### `skills_vet(name: str, rating: str = "vetted", notes: str = "")`

Mark an installed skill as Pantheon-curated:
- Copies the skill to ~/pantheon/skills-hub/curated/{name}/
- Assigns rating ("vetted" | "experimental")
- Adds notes for internal documentation

### `skills_status()`

Overview:
- Total skills in index (by tier)
- Recently updated upstream repos
- Skills with available updates
- Curation stats

## Search Index

SQLite FTS5 table for full-text search:

```sql
CREATE VIRTUAL TABLE skills_fts USING fts5(
  name, description, content,
  source, repo, tier,
  tokenize='porter unicode61'
);
```

Index is updated on:
- Startup (full rebuild)
- `skills_install()` (add entry)
- `skills_catalog_add()` (add entries)
- `skills_catalog_refresh()` (rebatch)

## Source Resolver

Maps a skill name + source to a concrete location:

- `installed/writing-plans` → `~/.hermes/skills/superpowers/writing-plans/SKILL.md`
- `upstream/marketingskills/ai-seo` → `~/.hermes/skills/marketingskills/skills/ai-seo/SKILL.md`
- `catalog/obra/superpowers/brainstorming` → `/tmp/pantheon-cache/obra-superpowers/skills/brainstorming/SKILL.md`

## Discovery Protocol (MCP)

```json
{
  "name": "skills-hub",
  "version": "1.0.0",
  "tools": [
    {
      "name": "skills_search",
      "description": "Search for skills across all sources",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": { "type": "string" },
          "tiers": { "type": "string", "enum": ["all", "installed", "upstream", "catalog"] }
        },
        "required": ["query"]
      }
    },
    {
      "name": "skills_install",
      "description": "Install a skill from any source",
      "inputSchema": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "source": { "type": "string" }
        },
        "required": ["name", "source"]
      }
    },
    {
      "name": "skills_list",
      "description": "List installed skills",
      "inputSchema": {
        "type": "object",
        "properties": {
          "filter": { "type": "string", "enum": ["all", "installed", "curated", "upstream"] }
        }
      }
    },
    {
      "name": "skills_catalog_add",
      "description": "Add an upstream repo to the catalog",
      "inputSchema": {
        "type": "object",
        "properties": {
          "repo_url": { "type": "string" },
          "name": { "type": "string" }
        },
        "required": ["repo_url", "name"]
      }
    }
  ]
}
```

## Delivery

- Python MCP server using the `mcp` library
- Compatible with Hermes Agent's existing MCP provider
- Written to `~/pantheon/apps/skills-hub/`
- Registered in Pantheon's MCP config

## Files to Create

```
~/pantheon/apps/skills-hub/
├── server.py              # MCP server entry point
├── indexer.py             # FTS5 index management
├── resolver.py            # Source resolver (tier mapping)
├── installer.py           # Skill installation engine
├── catalog.py             # Upstream repo scanner
├── curated/               # Pantheon-vetted skills (git-tracked)
│   └── INDEX.md
├── state/
│   ├── skills.db          # SQLite FTS5 index
│   └── repos.json         # Registered upstream repos
└── requirements.txt
```

## Integration Points

1. **Hermes MCP config** — register server in `~/.hermes/profiles/thoth/config.yaml` under `mcp_servers`
2. **Upstream monitor** (`upstream-skills-update-check.py`) — write updated versions to the search index
3. **Kairos** — can use `skills_search` in AEO workflow to find relevant skills
4. **Daemon** — can auto-install skill updates detected by the cron

## Future

- Skill dependency resolution (skill X requires skill Y)
- Skill version locking (pin to specific version)
- Community ratings/votes
- Auto-suggest on project context
