# Pantheon — Athenaeum Navigation Protocol

> Load this document when accessing the Athenaeum as a god. This defines how to move through the knowledge store efficiently and what you are and are not permitted to do.

---

## What The Athenaeum Is

The Athenaeum is Pantheon's canonical knowledge store — a filesystem of markdown files organized into domain-specific Codices. It is the source of truth. Every other data layer (Mnemosyne, the distilled layer, Codex partitions) is derived from it.

**The Athenaeum is not:**
- A database to query arbitrarily
- A place for gods to write session content directly (use vault logging via the Sanctuary pipeline)
- Browsable by scanning the filesystem blindly

---

## Index Tree Walking Protocol

Every folder in the Athenaeum has an `INDEX.md`. Always start at the root and walk down. Never open files without first reading the index at that level.

```
Step 1 — Read /Athenaeum/INDEX.md
         Identify which Codex likely contains what you need.

Step 2 — Read /Athenaeum/[Codex]/INDEX.md
         Identify which subfolder branch to follow.

Step 3 — Walk indexes down the tree until reaching file level.
         Read file summaries in the index to identify candidates.

Step 4 — Open only the candidate files.
         Never open files speculatively.

Step 5 — If nothing found after walking the tree:
         Escalate to Mnemosyne for semantic search.
```

---

## When To Use Index Walking vs Mnemosyne

**Use index walking when:**
- You know which Codex the information belongs to
- You are navigating to a known or predictable location
- The query maps cleanly to a folder structure (e.g., "SKC lyrics", "homelab networking notes")
- Speed and token efficiency matter

**Use Mnemosyne semantic search when:**
- Index walking fails to find the content
- The query is fuzzy or cross-domain
- You need to surface related content that may not be obviously categorized
- You are doing a similarity check against the full corpus

Index walking is fast and token-efficient. Mnemosyne is the fallback for queries that don't map cleanly to the folder structure. Both systems complement each other.

---

## How To Read Index Entry Summaries

Each index entry includes a one-line summary. Read the summary before deciding whether to go deeper. If the summary does not match what you need, do not open the file or descend into that subfolder.

```markdown
| File | Summary |
|---|---|
| digital-rain.md | Full lyrics for Digital Rain — metaverse escapism, Billie Eilish meets Deftones |
| ignite.md | Full lyrics for Ignite — dormant coal as emotional resurrection, additive chorus |
```

If the summary is ambiguous, open the file. If the summary clearly does not match, skip it and continue walking.

---

## How To Handle A Missing Index File

A folder without an `INDEX.md` is a navigation failure — the folder is invisible to god navigation by design.

If you encounter a folder without an index:
1. Do not scan the folder directly.
2. Log the missing index to Kronos as a navigation failure.
3. Send a notification to Iris flagging the folder for Demeter to regenerate the index.
4. Fall back to Mnemosyne semantic search to find the content you need.

Do not attempt to reconstruct or create an index yourself — index maintenance is Demeter's responsibility.

---

## What Gods Are Permitted To Do In The Athenaeum

**Permitted:**
- Read any file in any Codex you have scope access to
- Walk index trees at any depth
- Request Mnemosyne to search the Athenaeum semantically
- Read distilled content in any `/distilled/` subfolder
- Read archived content in any `/archive/` subfolder

**Not permitted without escalation:**
- Writing files directly to the Athenaeum (use Sanctuary vault logging or a vault_write workflow node)
- Moving or renaming files
- Creating new folders or Codices
- Modifying index files (Demeter's responsibility)
- Accessing Codices outside your defined `mnemosyne_scope` without explicit scope escalation

---

## What Requires Escalation Before Acting

The following actions require explicit escalation to Zeus before proceeding:

- Writing to a Codex outside your defined scope
- Proposing a new Codex (route through Hera via Mnemosyne)
- Accessing archived content for reinstatement (route through Persephone)
- Any action that would modify the structure of the Athenaeum

Escalate with full context: what you are trying to do, why, and what Codex or path is involved.

---

## The Short Link Standard

All index links use the shortest valid relative path. No decorative text beyond the arrow symbol.

```markdown
✓  [→](Codex-SKC/INDEX.md)
✓  [→](../INDEX.md)

✗  [Click here to view the SKC Codex index](Codex-SKC/INDEX.md)
✗  [Codex-SKC/INDEX.md](Codex-SKC/INDEX.md)
```

Token efficiency is a first-class concern in index design. Keep links minimal.
