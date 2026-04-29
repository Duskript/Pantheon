# Pantheon — ORACLE Migration Reference

> Source: Constitution Section 14
> Read this document when: running the ORACLE vault migration, understanding how ORACLE components map to Pantheon, or working on migrate-oracle-vault.sh.

---

## Purpose

This section documents how the original ORACLE memory compiler system maps onto Pantheon. It exists so nothing gets lost in the transition and builders understand the prior system's intent.

---

## Component Translation

| Original ORACLE | Pantheon Equivalent | Notes |
|---|---|---|
| watcher.py — polls AnythingLLM every 15min | Demeter file watcher | Real-time in Pantheon — no polling gap |
| flush.py — extracts and writes to vault | Sanctuary vault logging | Built into session lifecycle, not a separate process |
| compile.py — converts logs to knowledge articles | Hades nightly consolidation | LLM-driven, not template extraction |
| AnythingLLM RAG | Mnemosyne | Adds Codex scoping and semantic partitioning |
| Obsidian vault | The Athenaeum | Tool-agnostic, same markdown files |
| vault/Sessions/daily/YYYY-MM-DD.md | /Athenaeum/Codex-[X]/sessions/[timestamp].md | Per-Sanctuary, not per-day |
| vault/Knowledge/concepts/ | /Athenaeum/[Codex]/distilled/ | Same purpose, Codex-scoped |
| vault/Knowledge/qa/ | Session logs — queries preserved inline | No separate QA store needed |
| Single vault, two machine watchers | Single Athenaeum, one Demeter instance | Homelab migration handles multi-device in Phase 4 |
| NFS mount from gaming rig to Proxmox | Tailscale access to homelab Athenaeum | Phase 4 |
| Syncthing failsafe | Still valid — carry forward in Phase 4 | Local copy on workstation via Syncthing |

---

## Original Extraction Categories

The original flush.py used these structured extraction categories. They are preserved in Pantheon as Hades consolidation tags — Hades applies these as metadata when distilling session content:

```
DECISIONS       — choices made and why
LESSONS         — things learned
PROBLEMS_SOLVED — issues resolved with solutions
PATTERNS        — recurring approaches or thinking styles
CREATIVE        — creative output and ideas worth preserving
```

These tags appear as frontmatter in distilled notes:

```markdown
---
codex: SKC
type: distilled
tags: [CREATIVE, PATTERNS]
source_sessions: [2026-04-18T14:32:00.md]
distilled: 2026-04-19
---
```

---

## Key Improvements Over ORACLE

- **No polling gap.** Original system could lose up to 15 minutes of content from a crash. Pantheon writes every turn in real time.
- **No session-close dependency.** Original relied on AnythingLLM session close as a secondary flush trigger. Pantheon logging is independent of session state.
- **Codex-scoped knowledge.** Original vault was a single flat knowledge store. Pantheon partitions by domain — IT knowledge never surfaces in a lyric writing session.
- **LLM-driven consolidation.** Original compile.py used structured extraction templates. Hades reasons about consolidation using an LLM — better judgment about what to merge, what to keep separate, what to propose as a new Codex.
- **Self-expanding structure.** Original vault structure was manually defined. Pantheon's Athenaeum grows as Mnemosyne detects new topics and proposes new Codices.

---

## Migration Mapping

If content exists in the original ORACLE vault before Pantheon is built, it should be migrated into the Athenaeum during Phase 1 setup. Run `init-athenaeum.sh` first, then run `migrate-oracle-vault.sh`.

```
vault/Lyrics/           → Athenaeum/Codex-SKC/lyrics/
vault/IT-Notes/         → Athenaeum/Codex-Infrastructure/
vault/Projects/ORACLE/  → Athenaeum/Codex-Pantheon/
vault/Projects/SKC/     → Athenaeum/Codex-SKC/style/
vault/Projects/CantorsTale/ → Athenaeum/Codex-Fiction/
vault/Sessions/         → Athenaeum/Codex-Pantheon/sessions/archive/
vault/Knowledge/        → Athenaeum/[appropriate Codex]/distilled/
vault/STL-Library/      → Athenaeum/Codex-General/
vault/Interests/        → Staging/inbox/
```

**vault/Knowledge/** requires judgment — route each file to the most appropriate Codex's `/distilled/` subfolder based on content. When in doubt, route to `Codex-General/distilled/`.

Migration is a one-time manual operation performed during Phase 1 Athenaeum initialization. Demeter will detect the new files and trigger Mnemosyne embedding automatically after migration completes.
