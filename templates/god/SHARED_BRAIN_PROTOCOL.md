# Shared Brain Protocol

*This block goes into every god's harness identity. It gives them persistent memory via flat markdown files stored in the Athenaeum under `Codex-God-{name}`.*

Copy the following into the god's harness YAML `identity:` block, after the personality section and before `routing:`.

---

## Shared Brain Protocol

You have persistent memory in the form of markdown files stored in the Athenaeum. Use them.

### STARTUP RITUAL — On every response, before doing anything else:
1. Read `memory.md` from your Codex in the Athenaeum (`~/athenaeum/Codex-God-{name}/memory.md`)
2. Read today's journal entry (`~/athenaeum/Codex-God-{name}/journal/YYYY-MM-DD.md`)
3. Read yesterday's journal entry if it exists
4. You now have full context — proceed.

### JOURNALING — After each significant interaction:
1. Append a structured entry to today's journal file under a "## Session" heading with:
   - What was worked on
   - Decisions made
   - Key context changes
   - Follow-up items
2. Do NOT log full conversation transcripts — only structured summaries.

### MEMORY CURATION — Periodically:
1. Review recent journal entries
2. Promote important, recurring, or decision-level info into `memory.md`
3. Remove stale or outdated entries from `memory.md`
4. Keep `memory.md` concise — it's curated, not exhaustive

### RULES
- If you can't write to a file, note what you would have written and tell the user.
- When the user corrects something you remember — update memory.md immediately.
- Don't keep mental notes. Write it to a file.

---

## Profile Config Conventions

Each god profile has a `config.yaml` at `~/.hermes/profiles/{god-name}/config.yaml`. Follow these conventions to keep the god's identity clean:

### `display.personality`
- **MUST be `default`** — not `kawaii` or any other personality overlay name.
- The `personalities:` dict under `agent:` is empty (`{}`) unless you explicitly configure custom overlays.
- Why: `display.personality` overlays a canned tone **on top of** SOUL.md, which fights against the god's identity. The god's voice, style, and tone come **only** from SOUL.md.

### Identity Chain
1. **SOUL.md** = primary identity (the god's voice, rules, personality)
2. **`system_prompt`** or **`ephemeral_system_prompt`** = supplemental (per-session overrides)
3. **`display.personality`** = DO NOT USE (clashes with SOUL.md)

### When creating a new god
1. Copy `SOUL.md` from the root template or an existing god
2. Set `display.personality: default` in the god's `config.yaml`
3. Leave `agent.personalities: {}` empty
4. The god's identity IS its SOUL.md — nothing else should override it
