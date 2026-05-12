#!/usr/bin/env bash
# =============================================================================
# init-athenaeum.sh — Build the Pantheon Athenaeum and Staging area
# =============================================================================
#
# Usage:
#   ./scripts/init-athenaeum.sh              # create at default location (~/)
#   ./scripts/init-athenaeum.sh /custom/path # create at custom prefix
#
# This script is idempotent — running it again will NOT destroy existing
# content. It only creates directories and INDEX.md files that don't exist.
#
# The Athenaeum lives OUTSIDE the git repo. Never in version control.
# =============================================================================

set -euo pipefail

# --- Configuration -----------------------------------------------------------
PREFIX="${1:-$HOME}"
ATHENAEUM="$PREFIX/athenaeum"
STAGING="$PREFIX/Staging"
NOW="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"

# --- Utility -----------------------------------------------------------------
create_index() {
    local file="$1"
    if [ -f "$file" ]; then
        echo "  EXISTS $file"
    else
        cat > "$file"
        echo "  CREATE $file"
    fi
}

# --- Athenaeum Codex directories ---------------------------------------------
echo "==> Athenaeum: $ATHENAEUM"
mkdir -p "$ATHENAEUM"

for codex in \
    Codex-Forge \
    Codex-Pantheon \
    Codex-Infrastructure \
    Codex-SKC \
    Codex-Fiction \
    Codex-Asclepius \
    Codex-General; do

    # Every Codex has the same subfolder skeleton
    for sub in archive distilled; do
        mkdir -p "$ATHENAEUM/$codex/$sub"
    done
done

# Codex-specific subfolders
mkdir -p "$ATHENAEUM/Codex-Forge/blueprints"
mkdir -p "$ATHENAEUM/Codex-Forge/sessions"

mkdir -p "$ATHENAEUM/Codex-Pantheon/constitution"
mkdir -p "$ATHENAEUM/Codex-Pantheon/harnesses"
mkdir -p "$ATHENAEUM/Codex-Pantheon/workflows"
mkdir -p "$ATHENAEUM/Codex-Pantheon/sessions"

mkdir -p "$ATHENAEUM/Codex-Infrastructure/homelab"
mkdir -p "$ATHENAEUM/Codex-Infrastructure/networking"
mkdir -p "$ATHENAEUM/Codex-Infrastructure/proxmox"

mkdir -p "$ATHENAEUM/Codex-SKC/lyrics"
mkdir -p "$ATHENAEUM/Codex-SKC/style"
mkdir -p "$ATHENAEUM/Codex-SKC/references"

mkdir -p "$ATHENAEUM/Codex-Fiction/cantors-tale"
mkdir -p "$ATHENAEUM/Codex-Fiction/worldbuilding"

mkdir -p "$ATHENAEUM/Codex-Asclepius/research"
mkdir -p "$ATHENAEUM/Codex-Asclepius/references"
mkdir -p "$ATHENAEUM/Codex-Asclepius/conditions"
mkdir -p "$ATHENAEUM/Codex-Asclepius/treatments"

mkdir -p "$ATHENAEUM/Codex-General/notes"

# --- Staging directories -----------------------------------------------------
echo "==> Staging: $STAGING"
mkdir -p "$STAGING/inbox"
mkdir -p "$STAGING/processing"
mkdir -p "$STAGING/rejected"

# --- Root INDEX.md -----------------------------------------------------------
echo "==> INDEX files"
create_index "$ATHENAEUM/INDEX.md" <<ROOT
# Athenaeum — Master Index
Last updated: $NOW

> The canonical knowledge store. Append-and-archive only.
> Navigation protocol: always start at root. Walk indexes down. Never scan blindly.

## Codices

| Codex | Domain | Description |
|---|---|---|
| Codex-Forge | Project Planning | Blueprints, planning sessions, specs, project scoping — [→](Codex-Forge/INDEX.md) |
| Codex-Pantheon | System | Pantheon docs, constitution, harnesses, workflows, session logs — [→](Codex-Pantheon/INDEX.md) |
| Codex-Infrastructure | Infrastructure | Homelab, networking, IT systems, Proxmox — [→](Codex-Infrastructure/INDEX.md) |
| Codex-SKC | Music | Music, lyrics, sonic identity, style for the SKC project — [→](Codex-SKC/INDEX.md) |
| Codex-Fiction | Narrative | Long-form fiction, worldbuilding, The Cantor's Tale — [→](Codex-Fiction/INDEX.md) |
| Codex-Asclepius | Health | Medical research, health knowledge, treatment references — [→](Codex-Asclepius/INDEX.md) |
| Codex-General | General | Uncategorized notes and personal knowledge — [→](Codex-General/INDEX.md) |

## Staging

Raw unprocessed content lives outside the Athenaeum at \`~/Staging/\`. It is not indexed, not embedded, not searchable until Mnemosyne classifies and routes it to the correct Codex.

| Folder | Purpose |
|---|---|
| ~/Staging/inbox | Raw drops — web clippings, documents, notes |
| ~/Staging/processing | Mnemosyne is actively classifying |
| ~/Staging/rejected | Cannot be classified — needs manual review |

## Navigation Rules

1. Start here. Identify which Codex likely contains what you need.
2. Open that Codex's INDEX.md and walk subfolder indexes.
3. Read file summaries in indexes before opening files.
4. If index walking fails, use Mnemosyne semantic search.
5. A folder without an INDEX.md is invisible to navigation — log it for Demeter.
ROOT

# --- Codex INDEX files -------------------------------------------------------
create_index "$ATHENAEUM/Codex-Forge/INDEX.md" <<CODEX
# Codex-Forge — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Blueprints, planning sessions, specs, and project scoping.

## Subfolders

| Folder | Description |
|---|---|
| blueprints | Project blueprints and architectural plans |
| sessions | Planning session logs and meeting notes |
| distilled | Consolidated canonical project knowledge |
| archive | Superseded and archived content |
CODEX

create_index "$ATHENAEUM/Codex-Pantheon/INDEX.md" <<CODEX
# Codex-Pantheon — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Pantheon documentation, constitution, harnesses, workflows, and session logs.

## Subfolders

| Folder | Description |
|---|---|
| constitution | Pantheon constitution and planning documents |
| harnesses | God harness YAML files (tracked in git) |
| workflows | Multi-god workflow JSON definitions |
| sessions | System session logs and vault output |
| distilled | Consolidated canonical system knowledge |
| archive | Superseded and archived content |
CODEX

create_index "$ATHENAEUM/Codex-Infrastructure/INDEX.md" <<CODEX
# Codex-Infrastructure — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Homelab, networking, IT systems, and Proxmox.

## Subfolders

| Folder | Description |
|---|---|
| homelab | Homelab server planning and configuration |
| networking | Network topology, Tailscale, firewall rules |
| proxmox | Proxmox VM and container management |
| distilled | Consolidated canonical infrastructure knowledge |
| archive | Superseded and archived content |
CODEX

create_index "$ATHENAEUM/Codex-SKC/INDEX.md" <<CODEX
# Codex-SKC — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Music, lyrics, sonic identity, and style for the SKC project.

## Subfolders

| Folder | Description |
|---|---|
| lyrics | Finished and draft song lyrics |
| style | SKC sonic identity, genre references, production descriptors |
| references | Artist and sonic reference notes |
| distilled | Consolidated canonical SKC knowledge |
| archive | Superseded and archived content |
CODEX

create_index "$ATHENAEUM/Codex-Fiction/INDEX.md" <<CODEX
# Codex-Fiction — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Long-form fiction, worldbuilding, and The Cantor's Tale.

## Subfolders

| Folder | Description |
|---|---|
| cantors-tale | The Cantor's Tale — drafts, chapters, notes |
| worldbuilding | Setting, lore, and worldbuilding reference |
| distilled | Consolidated canonical narrative knowledge |
| archive | Superseded and archived content |
CODEX

create_index "$ATHENAEUM/Codex-Asclepius/INDEX.md" <<CODEX
# Codex-Asclepius — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Medical research, health knowledge, and treatment references.

## Subfolders

| Folder | Description |
|---|---|
| research | Medical research papers and summaries |
| references | Health reference materials and guides |
| conditions | Medical condition documentation |
| treatments | Treatment protocols and approaches |
| distilled | Consolidated canonical health knowledge |
| archive | Superseded and archived content |
CODEX

create_index "$ATHENAEUM/Codex-General/INDEX.md" <<CODEX
# Codex-General — Index
Parent: [Athenaeum](../INDEX.md)
Last updated: $NOW

Uncategorized notes and personal knowledge.

## Subfolders

| Folder | Description |
|---|---|
| notes | Miscellaneous notes and personal knowledge |
| distilled | Consolidated canonical general knowledge |
| archive | Superseded and archived content |
CODEX

# --- Subfolder INDEX.md stubs -------------------------------------------------
echo "==> Subfolder INDEX stubs"
STUB_FOLDERS="
    Codex-Forge/blueprints
    Codex-Forge/sessions
    Codex-Forge/distilled
    Codex-Forge/archive
    Codex-Pantheon/constitution
    Codex-Pantheon/harnesses
    Codex-Pantheon/workflows
    Codex-Pantheon/sessions
    Codex-Pantheon/distilled
    Codex-Pantheon/archive
    Codex-Infrastructure/homelab
    Codex-Infrastructure/networking
    Codex-Infrastructure/proxmox
    Codex-Infrastructure/distilled
    Codex-Infrastructure/archive
    Codex-SKC/lyrics
    Codex-SKC/style
    Codex-SKC/references
    Codex-SKC/distilled
    Codex-SKC/archive
    Codex-Fiction/cantors-tale
    Codex-Fiction/worldbuilding
    Codex-Fiction/distilled
    Codex-Fiction/archive
    Codex-Asclepius/research
    Codex-Asclepius/references
    Codex-Asclepius/conditions
    Codex-Asclepius/treatments
    Codex-Asclepius/distilled
    Codex-Asclepius/archive
    Codex-General/notes
    Codex-General/distilled
    Codex-General/archive
"

for pair in $STUB_FOLDERS; do
    codex="$(dirname "$ATHENAEUM/$pair")"
    folder="$(basename "$ATHENAEUM/$pair")"
    stub="$ATHENAEUM/$pair/INDEX.md"
    create_index "$stub" <<SUB
# $(echo "$folder" | sed 's/[^-a-zA-Z0-9]/ /g' | sed 's/\b\(.\)/\u\1/g') — Index
Parent: [$(basename "$codex")](../INDEX.md)
Last updated: $NOW

Content in \`$(basename "$codex")/$folder/\` is managed by Demeter and Mnemosyne.
Files are auto-detected and embedded into the vector store on change.
SUB
done

# --- Project Ideas (scaffold blank for new users) -----------------------------
echo "==> Project Ideas"
PROJECT_IDEAS_REAL="$PREFIX/project-ideas.md"
PROJECT_IDEAS_EXAMPLE="$PREFIX/project-ideas.example.md"

if [ -f "$PROJECT_IDEAS_REAL" ]; then
    echo "  EXISTS $PROJECT_IDEAS_REAL"
else
    if [ -f "$PROJECT_IDEAS_EXAMPLE" ]; then
        cp "$PROJECT_IDEAS_EXAMPLE" "$PROJECT_IDEAS_REAL"
        echo "  CREATE $PROJECT_IDEAS_REAL (from example template)"
    else
        echo "  SKIP  no example template found at $PROJECT_IDEAS_EXAMPLE"
    fi
fi

# --- Summary -----------------------------------------------------------------
echo ""
echo "============================================"
echo " Athenaeum initialized at: $ATHENAEUM"
echo " Staging initialized at:   $STAGING"
echo " Project ideas:            $PROJECT_IDEAS_REAL"
echo " INDEX files:              $(find "$ATHENAEUM" -name INDEX.md | wc -l)"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Verify read/write access"
echo "  2. Run initial Mnemosyne embedding pass"
echo "  3. Copy planning docs to Codex-Pantheon/constitution/"
echo "============================================"
