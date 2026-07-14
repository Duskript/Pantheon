#!/usr/bin/env python3
"""
Split the monolithic Artist-Profiles.md and Genre-Lexicon.md 
into individual files per artist / per genre.
"""
import re
import os
import unicodedata

BASE = os.path.expanduser("~/athenaeum/Codex-Apollo/knowledge/reference")
ARTISTS_DIR = os.path.join(BASE, "artists")
GENRES_DIR = os.path.join(BASE, "genres")
ARCHIVE_DIR = os.path.expanduser("~/athenaeum/Codex-Apollo/archive")

def slugify(name):
    """Convert 'FKA twigs' → 'fka-twigs', 'Sigur Rós' → 'sigur-ros', etc."""
    name = name.lower().strip()
    # Normalize unicode (é → e, etc.)
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    # Replace various separators
    name = re.sub(r'[&/]+', '-and-', name)
    name = re.sub(r'[\s_]+', '-', name)
    # Remove anything that isn't alphanumeric or dash
    name = re.sub(r'[^a-z0-9-]', '', name)
    # Collapse multiple dashes
    name = re.sub(r'-+', '-', name)
    # Strip leading/trailing dashes
    name = name.strip('-')
    return name

def split_file(filepath, output_dir, entry_type):
    """
    Split a file of entries separated by '---' into individual files.
    
    The first 4 lines are the file header (title line, blank, description, ---).
    Each subsequent entry: text, then --- separator.
    
    entry_type: 'artist' or 'genre'
    """
    os.makedirs(output_dir, exist_ok=True)
    
    with open(filepath, 'r') as f:
        content = f.read()
    
    # Split on --- lines
    raw_blocks = re.split(r'\n---\n', content)
    
    # First block is the header (title + description) — skip it
    if len(raw_blocks) > 0:
        raw_blocks = raw_blocks[1:]
    
    # Last block might end with --- (trailing) — strip empty
    if raw_blocks and raw_blocks[-1].strip() == '':
        raw_blocks = raw_blocks[:-1]
    
    entries = []
    seen_names = {}
    
    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue
        
        # Extract the first # line to get the name
        name_match = re.match(r'^#\s+(.+?)(?:\n|$)', block)
        if not name_match:
            print(f"  WARNING: Could not extract name from block:\n{block[:100]}...")
            continue
        
        raw_name = name_match.group(1).strip()
        # Remove parenthetical years like "(1978–present)" or "(1967–2016)"
        clean_name = re.sub(r'\s*\(.*?\)\s*$', '', raw_name).strip()
        
        # Handle duplicates by appending a year suffix
        slug = slugify(clean_name)
        if clean_name in seen_names:
            # Try to get a year from the original header
            year_match = re.search(r'\((\d{4})', raw_name)
            year_suffix = year_match.group(1) if year_match else f"{seen_names[clean_name]+1}"
            slug = f"{slug}-{year_suffix}"
            print(f"  DUPLICATE: '{clean_name}' → {slug}")
        
        seen_names[clean_name] = seen_names.get(clean_name, 0) + 1
        
        filename = f"{slug}.md"
        filepath_out = os.path.join(output_dir, filename)
        
        # Write the block as-is (it's the full entry without the header and separators)
        with open(filepath_out, 'w') as f:
            f.write(block + '\n')
        
        entries.append((clean_name, filename))
        print(f"  ✓ {filename}  ({raw_name})")
    
    return entries

print("=" * 60)
print("SPLITTING Artist-Profiles.md → individual files")
print("=" * 60)
artist_entries = split_file(
    os.path.join(BASE, "Artist-Profiles.md"),
    ARTISTS_DIR,
    "artist"
)
print(f"\n  → {len(artist_entries)} artists written to {ARTISTS_DIR}\n")

print("=" * 60)
print("SPLITTING Genre-Lexicon.md → individual files")
print("=" * 60)
genre_entries = split_file(
    os.path.join(BASE, "Genre-Lexicon.md"),
    GENRES_DIR,
    "genre"
)
print(f"\n  → {len(genre_entries)} genres written to {GENRES_DIR}\n")

# ── Write INDEX.md for artists ──
artists_sorted = sorted(artist_entries, key=lambda x: x[0].lower())
artist_index_lines = [
    "# Artists — Index",
    "",
    "Individual artist profile files split from the monolithic Artist-Profiles.md.",
    f"Total: {len(artist_entries)} artists.",
    f"Parent: [reference INDEX.md](../INDEX.md)",
    f"Last updated: auto-generated",
    "",
    "| # | Artist | File |",
    "|---|--------|------|",
]
for i, (name, filename) in enumerate(artists_sorted, 1):
    artist_index_lines.append(f"| {i} | {name} | [{filename}]({filename}) |")

with open(os.path.join(ARTISTS_DIR, "INDEX.md"), 'w') as f:
    f.write('\n'.join(artist_index_lines) + '\n')
print(f"✓ Written INDEX.md for artists ({len(artist_entries)} entries)")

# ── Write INDEX.md for genres ──
genres_sorted = sorted(genre_entries, key=lambda x: x[0].lower())
genre_index_lines = [
    "# Genres — Index",
    "",
    "Individual genre files split from the monolithic Genre-Lexicon.md.",
    f"Total: {len(genre_entries)} genres.",
    f"Parent: [reference INDEX.md](../INDEX.md)",
    f"Last updated: auto-generated",
    "",
    "| # | Genre | File |",
    "|---|-------|------|",
]
for i, (name, filename) in enumerate(genres_sorted, 1):
    genre_index_lines.append(f"| {i} | {name} | [{filename}]({filename}) |")

with open(os.path.join(GENRES_DIR, "INDEX.md"), 'w') as f:
    f.write('\n'.join(genre_index_lines) + '\n')
print(f"✓ Written INDEX.md for genres ({len(genre_entries)} entries)")

# ── Archive originals ──
os.makedirs(ARCHIVE_DIR, exist_ok=True)

for fname in ["Artist-Profiles.md", "Genre-Lexicon.md"]:
    src = os.path.join(BASE, fname)
    dst = os.path.join(ARCHIVE_DIR, fname)
    os.rename(src, dst)
    print(f"✓ Archived {fname} → archive/")

print("\n✅ DONE! All files split and archived.")
print(f"   Artists: {ARTISTS_DIR}/")
print(f"   Genres:  {GENRES_DIR}/")
print(f"   Archive: {ARCHIVE_DIR}/")
