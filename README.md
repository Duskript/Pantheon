# Pantheon-Core

**Build a personal multi-agent AI system.** Pantheon is an architecture for running domain-specific AI agents ("Gods") on Hermes Agent, sharing a unified knowledge layer (Athenaeum + Mnemosyne).

## What's in the box

### Core (always installs)

| Layer | What | Location |
|-------|------|----------|
| **Hermes Agent** | Multi-platform AI agent framework | Installed separately via `curl -fsSL https://hermes-agent.nousresearch.com/install.sh \| sh` |
| **Athenaeum** | File-based knowledge store (11 Codices) | `~/athenaeum/` — structure only in repo, **content is personal** |
| **Mnemosyne** | ChromaDB vector store, Codex-partitioned | `~/.hermes/pantheon/chroma/` |
| **Pantheon plugin** | Hermes memory provider + Athenaeum tools | `plugins/pantheon/` |
| **God SDK** | `pantheon-install`, `pantheon-export`, `pantheon-uninstall` | `scripts/` |
| **Harnesses** | Base identity YAMLs for each God | `harnesses/` |
| **Registry** | All registered gods + metadata | `pantheon-registry.yaml` |
| **God roster** | Active gods and their profiles | `gods/gods.yaml` |

### Add-on Gods (install separately)

| God | Domain | Package |
|-----|--------|---------|
| **Apollo** | Creative songcraft, lyrics, Suno production | `god-packages/god-apollo/` |
| *(future)* | *Your next god* | *Comes with a template:* `god-packages/god-template/` |

## Architecture

```
┌─────────────────────────────────────────────────┐
│                    Hermes Agent                   │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  You     │  │  Apollo  │  │  Future  │  ...  │
│  │(Hephaestus)│  │(Creative)│  │  God     │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│       │              │              │             │
│  ┌────▼──────────────▼──────────────▼─────┐      │
│  │         Athenaeum (Knowledge)          │      │
│  │  ~/athenaeum/ + ChromaDB + Graph DB    │      │
│  └─────────────────────────────────────────┘      │
└─────────────────────────────────────────────────┘
```

Each god is a separate Hermes profile with:
- Its own Telegram bot token
- Its own config, SOUL.md (personality), and skills
- Shared access to the Athenaeum for knowledge search

## Quick Start

```bash
# 1. Install Hermes Agent
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | sh

# 2. Clone Pantheon-Core
git clone git@github.com:Duskript/Pantheon-Core.git ~/pantheon

# 3. Install a god (starts with you — Hephaestus)
cd ~/pantheon
bash scripts/pantheon-install . --profile hephaestus

# 4. Set up bot tokens (from @BotFather on Telegram)
#    → ~/.hermes/.env for your root Telegram bot
#    → ~/.hermes/profiles/apollo/.env for Apollo's bot

# 5. Start gateway
hermes -p hephaestus gateway run
```

## What's in Git vs What's Personal

**In the repository (public):**
- All code, scripts, harnesses, skill definitions
- Directory structure templates
- Apollo's creative skills (lyrics, styles, formatting workflows)

**Not in the repository (personal, stays local):**
- Everything in `~/athenaeum/` (your Codices with actual content)
- `.env` files (Telegram bot tokens, API keys)
- `state.db` files (session history, conversation state)
- `memories/` (Hermes memory files)
- `chroma/` (vector embeddings indexed from your Athenaeum)
- Session logs and gateway state

The `.gitignore` enforces this — `athenaeum/` and `.env` are excluded.

## Migration

Moving to a new machine? Two scripts handle it:

```bash
# On the OLD machine — pack everything personal
bash ~/pantheon/scripts/migrate-export.sh
# → Creates pantheon-migration-YYYY-MM-DD.tar.zst

# Copy the tarball to the new machine, then:
# On the NEW Ubuntu machine
tar -I zstd -xpf pantheon-migration-*.tar.zst -C /
bash ~/pantheon/scripts/migrate-restore.sh
```

The export script collects:
- `~/athenaeum/` — your personal knowledge store
- `~/.hermes/pantheon/` — ChromaDB and graph DB
- All profile configs, .env files, state, memories
- Plugin code (Pantheon memory provider)

The restore script handles:
- Installing system dependencies (curl, git, python3)
- Setting up Ollama + signing in to cloud
- Installing Hermes Agent
- Cloning Pantheon-Core from GitHub
- Verifying everything extracted correctly

## Adding a New God

```bash
# 1. Export the template
bash scripts/pantheon-export god-template -o god-exports/

# 2. Start from the template and customize
cp -r god-packages/god-template god-packages/my-new-god/
# Edit god.yaml, harness.yaml, add skills

# 3. Install
bash scripts/pantheon-install god-packages/my-new-god/
```

Or use the full [God Forging Guide](planning/GOD-FORGING-GUIDE.md).

## Project Structure

```
~/pantheon/
├── scripts/            # God SDK + migration scripts
├── gods/               # Active god roster + messages
├── harnesses/          # Base identity YAMLs
├── plugins/            # Pantheon plugin source
├── god-packages/       # Installable god packages
│   ├── god-template/   # Template for new gods
│   └── god-apollo/     # Apollo add-on god
├── planning/           # Architecture, roadmap, states
├── claude-import-test/ # Test harness (Claude data import)
├── god-exports/        # Generated export tarballs (gitignored)
└── .gitignore          # Excludes personal data
```

## Version

**Pantheon-Core v1.0.0** — Built April 2026 for Hermes Agent.

See the [roadmap](planning/ROADMAP.md) for what's coming.
