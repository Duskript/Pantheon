# Apollo — Creative God of Songcraft

Apollo is a conversational god for lyric writing, poetry, song creation, and
Suno music production. He operates within your established creative voice and
accesses the creative corpus via Mnemosyne for consistency with past work.

## Skills

| Skill | Trigger | What It Does |
|-------|---------|--------------|
| **lyric-smith-v35** | "Let's write a song" | Full songwriting workflow — setup, write, refine, and hand off to Suno |
| **suno-formatter-v1** | "Format this for Suno" | Takes a handoff block, produces 4 Suno-ready outputs |
| **stylish-style-maker** | "Make a style for [artist]" | Generates JSON-style const blocks for Suno style prompts |

## Workflow

```
Lyric Smith ──handoff block──► Suno Formatter ──outputs──► Suno
                                      ▲
                               Stylish Style Maker
                              (optional, for style refs)
```

Each phase of the workflow is a separate skill to keep context windows
manageable. Handoff between skills happens via a file at
`~/athenaeum/Codex-Apollo/sessions/last-handoff.md`.

## Knowledge Boundaries

- **Codex-Apollo** — Reference library (methodology, techniques, styles, knowledge)
- **Codex-SKC** — Work product (final lyrics, confirmed styles, completed songs)

## Model

`gemma4:31b-cloud` on Ollama Cloud

## Created

1.0.0 — April 2026
