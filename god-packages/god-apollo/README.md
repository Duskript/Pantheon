# Apollo — Creative God of Songcraft (Add-on)

**Apollo is an add-on god for Pantheon-Core.** He handles lyric writing, poetry,
song creation, and Suno music production within your established creative voice.

## Prerequisites

- Pantheon-Core installed (Athenaeum, Mnemosyne, Pantheon plugin)
- Ollama Cloud signed in (`gemma4:31b-cloud` model)
- Telegram bot token from [@BotFather](https://t.me/botfather)

## Installation

```bash
# From Pantheon-Core root:
cd ~/pantheon
bash scripts/pantheon-install ./god-packages/god-apollo/
```

What this does:
1. Creates `~/.hermes/profiles/apollo/` with config and SOUL.md
2. Installs the Pantheon plugin (Athenaeum access)
3. Registers Apollo in the god roster
4. Installs creative skills (Lyric Smith, Suno Formatter, Stylish Style Maker)

Then set up the Telegram bot:
```bash
# Edit ~/.hermes/profiles/apollo/.env with your Apollo bot token
# Start the gateway:
hermes -p apollo gateway run
```

## Skills

| Skill | Trigger | What It Does |
|-------|---------|--------------|
| **lyric-smith-v35** | "Let's write a song" | Full songwriting workflow — setup, write, refine, hand off to Suno |
| **suno-formatter-v1** | "Format this for Suno" | Takes a handoff block, produces 4 Suno-ready outputs |
| **stylish-style-maker** | "Make a style for [artist]" | Generates JSON-style const blocks for Suno style prompts |

## Workflow

```
Lyric Smith ──handoff block──► Suno Formatter ──outputs──► Suno
                                      ▲
                               Stylish Style Maker
                              (optional, for style refs)
```

Each phase is a separate skill to keep context windows manageable.
Handoff happens via `~/athenaeum/Codex-Apollo/sessions/last-handoff.md`.

## Knowledge Boundaries

- **Codex-Apollo** — Reference library (methodology, techniques, style knowledge)
- **Codex-SKC** — Work product (final lyrics, confirmed styles, completed songs)

## Model

`gemma4:31b-cloud` on Ollama Cloud

## Version

1.0.0 — April 2026
