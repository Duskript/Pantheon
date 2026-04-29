# Pantheon — The Knowledge Layer

> Source: Constitution Section 3
> Read this document when: working on anything touching the Athenaeum, Codices, indexes, Staging, Mnemosyne, or the knowledge pipeline.

---

## The Four Layers

The knowledge layer is Pantheon's memory system. It has four distinct layers, each with a specific role. They are not interchangeable.

**Layer 1 — The Athenaeum**
The canonical human-readable knowledge store. A filesystem of markdown files organized into Codices. This is the source of truth. It is append-and-archive only — nothing is deleted from the Athenaeum, only moved to archive subfolders. If every other layer were destroyed, the entire system could be rebuilt from the Athenaeum alone.

**Layer 2 — The Vector Store (Mnemosyne)**
A machine-readable semantic index of the Athenaeum. Built from and derived from Layer 1. Never the source of truth — always a derived layer. Gods query Mnemosyne when they need to find semantically relevant knowledge. Mnemosyne is rebuilt or updated whenever the Athenaeum changes. If the vector store is corrupted or lost it is rebuilt from the Athenaeum — no data is permanently lost.

**Layer 3 — The Distilled Layer**
Consolidated canonical concepts produced by Hades during nightly consolidation runs. Raw notes that have been merged, deduplicated, and summarized live here. Sits between raw Athenaeum content and vector search as a noise reduction layer. Distilled content is still stored in the Athenaeum under each Codex's `/distilled/` subfolder — it is not a separate system.

**Layer 4 — Codex Partitions**
Scoped views into the vector store. Not separate databases. Each Codex has a corresponding Mnemosyne partition defined by metadata tags applied at embedding time. Studios query their designated partition only. A Lyric Writing Studio session never surfaces infrastructure notes. Partitions are logical, not physical.

---

## The Athenaeum File Structure

```
/Athenaeum/
├── Codex-SKC/
│   ├── lyrics/
│   ├── style/
│   ├── references/
│   ├── distilled/
│   └── archive/
│
├── Codex-Infrastructure/
│   ├── homelab/
│   ├── networking/
│   ├── proxmox/
│   ├── distilled/
│   └── archive/
│
├── Codex-Pantheon/
│   ├── constitution/
│   ├── harnesses/
│   ├── workflows/
│   ├── sessions/
│   ├── distilled/
│   └── archive/
│
├── Codex-Forge/
│   ├── blueprints/
│   ├── sessions/
│   ├── distilled/
│   └── archive/
│
├── Codex-Fiction/
│   ├── cantors-tale/
│   ├── worldbuilding/
│   ├── distilled/
│   └── archive/
│
├── Codex-General/
│   ├── notes/
│   ├── distilled/
│   └── archive/
│
└── Codex-Asclepius/
    ├── research/
    ├── references/
    ├── conditions/
    ├── treatments/
    ├── distilled/
    └── archive/
```

---

## Codex Definitions

| Codex | Domain | Primary God | Studio Access |
|---|---|---|---|
| SKC | Music, lyrics, style, sonic references | Apollo | Lyric Writing, Poetry |
| Infrastructure | Homelab, networking, IT, Proxmox | Hephaestus | Infrastructure Planning |
| Pantheon | System docs, harnesses, workflows, sessions | Athena | All |
| Forge | Blueprints, planning sessions, specs | Hephaestus | Project Scoping, Program Design |
| Fiction | Long form narrative, worldbuilding | Calliope | Long Form Fiction |
| Asclepius | Medical research, health knowledge, treatment references | Caduceus | Medical Research, Health Reference |
| General | Uncategorized notes and personal knowledge | Athena | Knowledge Query |

---

## The Staging Area

The Staging area lives outside the Athenaeum entirely. It is not indexed, not embedded into Mnemosyne, and not part of the canonical knowledge store. It is a drop zone for raw unprocessed content.

```
/Pantheon/
├── Athenaeum/          ← indexed, embedded, canonical
│   ├── INDEX.md
│   └── [Codices...]
│
└── Staging/            ← outside Athenaeum, never indexed directly
    ├── inbox/          ← raw drops — web clippings, documents, notes
    ├── processing/     ← Mnemosyne is actively classifying
    └── rejected/       ← could not be classified, needs manual review
```

**Mnemosyne watches Staging/inbox** and processes new content automatically. Her classification workflow:

```
Content dropped in Staging/inbox
        ↓
Mnemosyne reads and understands content
        ↓
Scans existing Codex index summaries for fit
        ↓
Clear fit — moves to correct Codex subfolder
  Demeter regenerates affected indexes
  Mnemosyne embeds content into correct partition
        ↓
Ambiguous fit — routes to Codex-General
  Flags via Iris for user review
        ↓
No fit — recurring or substantial topic detected
  Proposes new Codex to user via Iris
  User approves via Hera → Codex created automatically
  Content routed and embedded
        ↓
Cannot classify — moves to Staging/rejected
  Iris notifies user for manual decision
```

Content only enters the Athenaeum and Mnemosyne after Mnemosyne has classified it. Staging/inbox is never embedded directly.

---

## The Index System

Every folder in the Athenaeum contains an INDEX.md file. Indexes are the navigation layer — they allow gods and AI assistants to traverse the Athenaeum without scanning the filesystem blindly. An LLM entering the Athenaeum always starts at the root index and walks the tree to its destination.

Indexes are auto-generated and maintained by Demeter. When any file or folder is created, moved, or archived Demeter updates the affected index and all parent indexes up to the root. Indexes are never hand-edited — they are always derived from actual filesystem state.

### Root Index — /Athenaeum/INDEX.md

The master entry point. Lists every Codex with a one-line description and a link to its index. This is the first file any god or AI assistant reads when entering the Athenaeum.

```markdown
# Athenaeum — Master Index
Last updated: [ISO 8601 timestamp]

## Codices

| Codex | Description | Index |
|---|---|---|
| Codex-SKC | Music, lyrics, sonic identity, and style for the SKC project | [→](Codex-SKC/INDEX.md) |
| Codex-Infrastructure | Homelab, networking, IT systems, and Proxmox | [→](Codex-Infrastructure/INDEX.md) |
| Codex-Pantheon | System documentation, harnesses, workflows, and session logs | [→](Codex-Pantheon/INDEX.md) |
| Codex-Forge | Planning sessions, blueprints, and project specs | [→](Codex-Forge/INDEX.md) |
| Codex-Fiction | Long form narrative, worldbuilding, and The Cantor's Tale | [→](Codex-Fiction/INDEX.md) |
| Codex-Asclepius | Medical research, health knowledge, and treatment references | [→](Codex-Asclepius/INDEX.md) |
| Codex-General | Uncategorized notes and personal knowledge | [→](Codex-General/INDEX.md) |

> **Link format:** All index links use the shortest valid relative path. No decorative text beyond the arrow symbol. Token efficiency is a first-class concern in index design.
```

### Codex Index — /Athenaeum/[Codex]/INDEX.md

Lists all subfolders and distilled content within the Codex. Each entry includes a one-line description of what that branch contains.

```markdown
# Codex-SKC — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: [ISO 8601 timestamp]

## Subfolders

| Folder | Description | Index |
|---|---|---|
| lyrics | Finished and draft song lyrics organized by topic and structure | [→](lyrics/INDEX.md) |
| style | SKC sonic identity, genre references, and production descriptors | [→](style/INDEX.md) |
| references | Artist and sonic reference notes | [→](references/INDEX.md) |
| distilled | Consolidated canonical SKC knowledge | [→](distilled/INDEX.md) |
| archive | Archived and superseded content | [→](archive/INDEX.md) |
```

### Subfolder Index — /Athenaeum/[Codex]/[subfolder]/INDEX.md

Lists all sub-subfolders and files within the subfolder. Files include a one-line summary of their content so a god can decide whether to open them without reading them.

```markdown
# Lyrics — Index
Parent: [Codex-SKC](../INDEX.md)
Last updated: [ISO 8601 timestamp]

## Files

| File | Summary |
|---|---|
| digital-rain.md | Full lyrics for Digital Rain — metaverse escapism, Billie Eilish meets Deftones |
| ignite.md | Full lyrics for Ignite — dormant coal as emotional resurrection, additive chorus |
```

### Deep Index — Infinite Depth

The index pattern repeats at every level of nesting regardless of depth. A folder covering rhythm and rhyme within a specific genre follows the same pattern. Every index includes a Parent link. Every folder must have an INDEX.md. A folder without an index is invisible to god navigation.

### Index Maintenance Rules

- Every folder must have an INDEX.md. A folder without an index is invisible to god navigation.
- Demeter regenerates affected indexes automatically on file system changes in live Codices only.
- Each index entry must include a one-line human-readable summary — not just a filename.
- Parent links are always present — every index knows where it came from.
- The Last updated timestamp reflects the most recent change to that folder's contents.
- Archived content remains in the archive index — it is not removed from navigation entirely.
- When a new Codex is created via Hera, Demeter immediately generates the root index entry and the Codex index skeleton.

---

## Demeter — File Watcher and Scheduler

Demeter has two distinct responsibilities: watching the live Athenaeum for changes and triggering index regeneration, and scheduling nightly maintenance jobs for the rest of the underworld cluster.

### File Watcher

Demeter uses inotify to watch live Codex paths for filesystem events. She does not poll — she receives events in real time.

**Watched paths:** All live Codex folders under `~/Pantheon/Athenaeum/`

**Ignored paths:**
- `/archive/` at any depth — Charon owns this, maintains his own ARCHIVE_INDEX.md
- `Staging/` — Mnemosyne owns this

**Triggering events:** file created, file modified, file moved within a live Codex

**Non-triggering events:** anything under `/archive/`, anything under `Staging/`, Charon move operations, The Fates purge operations

### Settle Window

Demeter does not fire on every individual event. She waits for a settle window — a period of inactivity after the last event — before processing the accumulated batch as a single job. This prevents cascading regeneration jobs during normal usage and absorbs small bursts cleanly.

**Default settle window: 5 seconds**

Any file events that arrive within the settle window are batched together. Demeter regenerates all affected indexes and their parent indexes up to root in a single pass after the window closes.

### Migration-Aware Pause and Resume

Bulk operations that touch the Athenaeum — vault migrations, bulk imports, Codex restructures — can signal Demeter to pause watching and queue events rather than firing during the operation. When the operation completes it sends a resume signal and Demeter processes the entire queued batch as one job.

Signal protocol via Hermes:

```json
{ "from": "migrate-oracle-vault", "to": "demeter", "action": "pause_watch" }
{ "from": "migrate-oracle-vault", "to": "demeter", "action": "resume_watch" }
```

Any script or god that performs bulk Athenaeum writes should use this pattern. It is not required for single-file operations.

### Failure Handling

If an index regeneration job fails:

1. Retry once immediately
2. If retry fails — keep the last good index in place, do not write a partial index
3. Send notification to Iris with the affected path and error
4. Log the failure to Kronos

A failed index regeneration never leaves a broken index in place. The last good index remains navigable until the issue is resolved.

### Cron Scheduler

Demeter's scheduler is a separate responsibility from her file watcher. She triggers nightly maintenance jobs on a configurable schedule:

| Job | Default Schedule | Configurable Range |
|---|---|---|
| Hades consolidation | Nightly | Nightly to weekly |
| The Fates TTL evaluation | Nightly | Nightly to weekly |
| Backup | Nightly | Nightly to weekly |

All three jobs run in the same maintenance window by default. Schedule is managed through Hera.

---

## The Archive Structure — The Underworld

Each Codex's `/archive/` folder is divided into three tiers, mirroring the fields of the Greek underworld. Live Codices are always clean — nothing lingers there. Charon executes all physical moves between tiers.

```
/archive/
├── elysium/     ← distilled versions superseded by rollback — valuable, intentionally created
├── asphodel/    ← routine archived source files — replaced by distillation, no special status
└── tartarus/    ← condemned content — not restorable, purged after 3 months
```

### Archive Tier Rules

**Asphodel** — where source files go when Hades distills them. 6-month TTL. After 6 months The Fates auto-condemn to Tartarus unless Hades intervenes.

**Elysium** — where distilled versions go when overruled by a rollback. No automatic TTL. Only moves to Tartarus if Hades explicitly condemns it. Treated as valuable by definition.

**Tartarus** — condemned content. 3-month TTL. After 3 months The Fates purge permanently. This is the only place in Pantheon where true deletion occurs. Nothing is restored from Tartarus.

### The Archive Index

Each `/archive/` folder maintains a versioned `ARCHIVE_INDEX.md` written and maintained by Charon. It tracks what was archived, what replaced it, and when — giving Hades a complete recovery reference without needing to search the vector store.

```markdown
# Archive Index — Codex-SKC
Last updated: 2026-04-19T14:32:00Z

| File | Tier | Replaced By | Archived |
|---|---|---|---|
| ignite-draft-v1.md | asphodel | ignite-distilled.md | 2026-04-19T14:32:00Z |
| ignite-distilled.md | elysium | ignite-draft-v1.md (rollback) | 2026-05-01T09:00:00Z |
```

The archive index is Charon's domain. Hades reads it. No other god writes to it.

### Rollback

Hades can instruct Charon to roll back a distillation:

```
Hades issues rollback instruction
        ↓
Charon moves archived source file from Asphodel back to live Codex path
        ↓
Charon moves superseded distilled version to Elysium
        ↓
Charon updates ARCHIVE_INDEX.md to reflect the swap
        ↓
Charon notifies Mnemosyne — re-embed restored file, remove distilled version vectors
        ↓
Demeter regenerates affected live indexes
```

### Stale Embedding Cleanup

When Charon moves any file out of the live Codex — whether to Asphodel, Elysium, or Tartarus — he notifies Mnemosyne with the list of affected files. Mnemosyne removes those vectors immediately. This prevents stale embeddings from accumulating in active partition queries.

Archived content is not embedded in Mnemosyne at any tier. The archive index is the only navigation layer for the underworld.

---

## The Knowledge Pipeline

```
User works in a Sanctuary session
        ↓
Session auto-logs to designated Codex folder
        ↓
Demeter detects new content (file watcher)
        ↓
Mnemosyne re-embeds changed files with Codex metadata tag
        ↓
Hades runs nightly — consolidates and distills where appropriate
        ↓
Charon moves source files to /archive/asphodel/
        ↓
Charon updates ARCHIVE_INDEX.md
        ↓
Charon notifies Mnemosyne — remove stale vectors
        ↓
Distilled content written back to Codex /distilled/ folder
        ↓
Demeter detects new distilled file
        ↓
Mnemosyne re-embeds distilled content
        ↓
The Fates run nightly (configurable: nightly to weekly)
        ↓
Asphodel entries > 6 months → Tartarus (Charon moves)
Tartarus entries > 3 months → permanent deletion (Charon purges)
```

---

## Hard Rules For This Layer

- The Athenaeum owns the truth. All other layers serve it.
- Never write directly to the vector store — always write to the Athenaeum and let Mnemosyne derive from it.
- Live Codices are always clean. Archived content moves immediately — nothing lingers in a live Codex path.
- Codex partitions are defined by metadata tags at embedding time, not by separate database instances.
- Session logs are append-only markdown files. One file per session, named by timestamp.
- Hades directs distillation. Charon executes all physical file moves. They are not interchangeable.
- Archived content is never embedded in Mnemosyne. The archive index is the only navigation layer for the underworld.
- Nothing is restored from Tartarus. Ever.
- Tartarus is the only place in Pantheon where permanent deletion occurs. All other tiers are recoverable.
- The Fates run no more frequently than nightly and no less frequently than weekly.
- Codex-Inbox is a staging area only. Content dropped here is unprocessed and unsearchable until Mnemosyne classifies and routes it to the appropriate Codex.
