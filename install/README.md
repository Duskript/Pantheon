# Pantheon Install Pipeline

The canonical public installer lives here:

```text
install/
├── install-pantheon.sh      # canonical installer used by README one-liner
├── validate-pantheon.sh     # post-install health check
├── README.md                # this file
└── assets/
    ├── hephaestus/          # Hephaestus profile assets shipped by install
    ├── systemd/             # service templates/reference units
    └── env/                 # clean env templates and god metadata
```

`scripts/install-pantheon.sh` is kept as a compatibility copy for older links. Keep both files identical until the old path is fully retired.

## Quick start

```bash
curl -fsSL https://raw.githubusercontent.com/Duskript/Pantheon/main/install/install-pantheon.sh | bash
```

The default path is the smooth first-run path: clone Pantheon, install Hermes, create env files, install core profiles/skills, start the local setup server, and open the Welcome Wizard.

For the heavier all-in install:

```bash
bash ~/pantheon/install/install-pantheon.sh --full
```

## Flags

| Flag | Effect |
|------|--------|
| `--full` | Run optional heavyweight phases: Composio, Ollama, Whisper, user systemd services, cron, Olympus UI build, endpoint smoke tests. |
| `--enterprise` | Skip interactive credential prompts. Assumes `~/.hermes/.env` is pre-populated by an enterprise wrapper. |
| `--skip-composio-prompt` | Skip the Composio prompt. |
| `--non-interactive` | Fail rather than prompt. Useful for CI/automation. |
| `--phase N` | Run only phase N for debugging partial installs. |
| `--no-setup-server` | Do not start the first-run setup server at the end. |

## Default phases

0. Preflight.
1. Install required system packages.
2. Clone or update Pantheon.
3. Install Hermes Agent from bundled source.
7. Create Pantheon `.env`.
8. Install Hermes + Hephaestus core profiles.
9. Install curated Hephaestus skills.
13. Create `god-exports/` runtime staging dir.
16. Print summary.
17. Start `scripts/setup-server.py` on `127.0.0.1:9876` and open `welcome.html`.

## Optional `--full` phases

4. Install/start Composio bridge.
5. Install Ollama and pull `nomic-embed-text`.
6. Install faster-whisper and download the base model.
10. Install/start user systemd services.
11. Install cron jobs.
12. Build/deploy Olympus UI bundles.
14. Smoke test wizard endpoint.
15. Smoke test intake endpoint.

These are intentionally outside the default path so a fresh user can reach the wizard before optional local services create friction.

## Systemd behavior

The installer now checks whether `systemd --user` is available before service phases. If it is not available, the script warns and continues instead of aborting. This makes WSL, containers, macOS, and minimal Linux installs less brittle.

## Source of truth

The executable script is the source of truth for current install behavior. When install behavior changes, update this README and the root README in the same commit.
