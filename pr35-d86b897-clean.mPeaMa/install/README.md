# Pantheon Install Pipeline

The executable form of the install lives in `install/`:

```
install/
├── install-pantheon.sh     # the script
├── validate-pantheon.sh    # the post-install health check
├── README.md               # this file
└── assets/
    ├── hephaestus/         # Hephaestus profile assets shipped by install
    │   ├── SOUL.md         # 148-line trimmed identity
    │   ├── persona.md      # voice + speech patterns
    │   ├── god.json        # wizard registration metadata
    │   └── skills-manifest.txt   # 9-skill curated list
    ├── systemd/
    │   └── composio-bridge.service  # npm-start service for :8789
    └── env/
        ├── .env.example    # template for ~/pantheon/.env
        └── hermes-god.json # wizard registration for the named hermes profile
```

## Quick start

```bash
# Fresh install on a CachyOS/Debian/macOS box:
curl -fsSL https://raw.githubusercontent.com/Duskript/Pantheon/main/install/install-pantheon.sh | bash

# Or clone the repo and run:
git clone https://github.com/Duskript/Pantheon ~/pantheon
bash ~/pantheon/install/install-pantheon.sh

# Re-run after partial failure (idempotent):
bash ~/pantheon/install/install-pantheon.sh

# Run just one phase (debugging):
bash ~/pantheon/install/install-pantheon.sh --phase 4

# Skip the interactive Composio prompt (use .env values or empty placeholders):
bash ~/pantheon/install/install-pantheon.sh --skip-composio-prompt

# Enterprise mode (assumes ~/.hermes/.env is pre-populated):
bash ~/pantheon/install/install-pantheon.sh --enterprise

# After install, check system health:
bash ~/pantheon/install/validate-pantheon.sh
```

## Flags

| Flag | Effect |
|------|--------|
| `--enterprise` | Skip the interactive Composio/n8n prompts. Assumes `~/.hermes/.env` is pre-populated. Used by the Pantheon-Enterprise install wrapper. |
| `--skip-composio-prompt` | Skip the Composio prompt only. n8n prompt is always skipped (out of scope). |
| `--non-interactive` | Fail rather than prompt. For CI/automation. |
| `--phase N` | Run only phase N (1-16). For debugging partial installs. |

## What the script does (16 phases)

0. Preflight (distro, not-root, $HOME writable)
1. Install system packages (git, curl, python3, node, npm)
2. Clone Pantheon at $PANTHEON_REPO_BRANCH (or pull if exists)
3. Install Hermes Agent via `pip install -e`
4. Install + start Composio bridge on :8789
5. Install Ollama + pull `nomic-embed-text`
6. Install faster-whisper + download `base` model
7. Create Pantheon `.env` from `.env.example`
8. Install core god profiles (Hermes default + Hermes named + Hephaestus)
9. Install Hephaestus's 9 core skills (symlinks)
10. Install + start 3 systemd services (`pantheon-webui`, `pantheon-mcp`, `demeter-watcher`)
11. Install cron jobs via `setup-pantheon-cron.sh`
12. Build Olympus-UI bundles (clone + npm ci + npm run build + deploy)
13. Create `god-exports/` runtime staging dir
14. Smoke test wizard endpoint at `:8787/onboarding/welcome`
15. Smoke test intake endpoint at `:8787/api/onboarding/context-gathering`
16. Final summary

## Phases intentionally NOT included

- **n8n install/start/enable** — n8n is intentionally out of scope (currently broken). See [`docs/N8N_SETUP.md`](../docs/N8N_SETUP.md).
- **Voice provider install** — the wizard's Step 2 ("Local runtime") lets the user pick, and the install is triggered by `install_voice_provider` in the wizard at `webui/api/onboarding.py:1323`. Pre-installing faster-whisper ensures the "base" model is downloaded so the first voice message doesn't trigger a 75MB download mid-onboarding.

## Where the install source of truth lives

The spec doc is `~/athenaeum/Codex-Olympus/INSTALL_PIPELINE.md` (canonical). The script is the executable form. When you change the script, update the spec in the same commit and append to `DECISIONS.md`.

## Composio credentials

The install script prompts for `COMPOSIO_CONSUMER_KEY` and `COMPOSIO_AUTH_TOKEN` unless `--enterprise` or `--skip-composio-prompt`. To get these keys, see [`docs/COMPOSIO_SETUP.md`](../docs/COMPOSIO_SETUP.md).

The bridge refuses to start without these keys (`composio-bridge/server.ts:15` does `process.exit(1)`). The install script will install and start the bridge either way, but the bridge will report `composio:false` in `/health` until you fill in `~/.hermes/.env`.

## Enterprise edition

The Enterprise install lives in a separate private repo (`Duskript/Pantheon-Enterprise`) and wraps this script with pre-populated `~/.hermes/.env`. See the Enterprise repo's README for the install command.

## Containerization

The script is designed to be container-portable:
- All installs use `pacman` / `apt` / `brew` (distro-detected)
- All state lives in `~/.hermes`, `~/pantheon`, `~/athenaeum`, `~/.ollama` — all `$HOME`-relative
- All systemd services are `Type=simple` (works under `podman --userland-container`)
- No `sudo` calls in the script (uses `systemctl --user`)

When you do containerize, the script becomes the container `ENTRYPOINT` and each phase is a separate `RUN` layer. See `INSTALL_PIPELINE.md §2` in the spec for the full design.
