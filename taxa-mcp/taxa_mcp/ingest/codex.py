"""Load parsed tax records into the Athenaeum as Codex-Tax-US.

Each section becomes a markdown file in the codex, with YAML frontmatter
for the citation metadata. The full text is in the body. This makes the
data:
    1. Human-readable (open any .md in a text editor)
    2. Indexable (the existing Athenaeum INDEX.md walk can navigate it)
    3. Embeddable (ChromaDB can chunk and embed the markdown bodies)
    4. FTS5-friendly (FTS5 indexes the body text for keyword search)

Layout:
    ~/athenaeum/Codex-Tax-US/
        INDEX.md                          # Master index
        README.md                         # What this codex is
        irc/
            §1.md
            §199A.md
            ...
        cfr/
            §1.1-1.md
            §1.162-1.md
            ...
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .irc import IRCSection
from .cfr import CFRSection


CODEX_NAME = "Codex-Tax-US"


def make_section_filename(section_num: str) -> str:
    """Convert '1.162-1' or '199A' into a filesystem-safe filename.

    Sanitizes: strips any path separators, slashes, colons, and other
    filesystem-unfriendly characters that may leak through from
    malformed USLM identifiers.
    """
    if not section_num:
        return ""
    # Replace anything that's not a safe char with an underscore
    safe = re.sub(r"[^A-Za-z0-9.\-]", "_", section_num)
    # Collapse multiple underscores
    safe = re.sub(r"_+", "_", safe).strip("_")
    if not safe:
        return ""
    return f"§{safe}.md"


def render_irc_markdown(section: IRCSection) -> str:
    """Render an IRC section as a markdown document with YAML frontmatter."""
    frontmatter_lines = [
        "---",
        f"citation: \"{section.citation}\"",
        f"section_num: \"{section.section_num}\"",
        f"heading: \"{section.heading}\"",
        f"source: \"{section.source_url}\"",
        f"release_point: \"{section.release_point}\"",
        f"fetched_at: \"{section.fetched_at}\"",
        f"parent_subtitle: \"{section.parent_subtitle or ''}\"",
        f"parent_chapter: \"{section.parent_chapter or ''}\"",
        "codex: \"Codex-Tax-US\"",
        "---",
        "",
    ]
    frontmatter = "\n".join(frontmatter_lines)

    title = f"# {section.citation}"
    if section.heading:
        title += f": {section.heading}"

    body = f"""{title}

{section.text}

---

**Source:** [{section.citation}]({section.source_url})
**Release point:** {section.release_point} (current as of fetched_at {section.fetched_at})
**Parent structure:** Subtitle {section.parent_subtitle or "?"}, Chapter {section.parent_chapter or "?"}
"""
    return frontmatter + body


def render_cfr_markdown(section: CFRSection) -> str:
    """Render a CFR section as a markdown document with YAML frontmatter."""
    frontmatter_lines = [
        "---",
        f"citation: \"{section.citation}\"",
        f"section_num: \"{section.section_num}\"",
        f"heading: \"{section.heading}\"",
        f"source: \"{section.source_url}\"",
        f"issue_date: \"{section.issue_date}\"",
        f"fetched_at: \"{section.fetched_at}\"",
        f"parent_chapter: \"{section.parent_chapter}\"",
        f"parent_subchapter: \"{section.parent_subchapter or ''}\"",
        f"parent_part: \"{section.parent_part}\"",
        f"parent_subpart: \"{section.parent_subpart or ''}\"",
        "codex: \"Codex-Tax-US\"",
        "---",
        "",
    ]
    frontmatter = "\n".join(frontmatter_lines)

    title = f"# {section.citation}"
    if section.heading:
        title += f": {section.heading}"

    body = f"""{title}

{section.text}

---

**Source:** [{section.citation}]({section.source_url})
**Issue date:** {section.issue_date} (current as of fetched_at {section.fetched_at})
**Parent structure:** Title 26, Chapter {section.parent_chapter}, Subchapter {section.parent_subchapter or "?"}, Part {section.parent_part}, Subpart {section.parent_subpart or "—"}
"""
    return frontmatter + body


def load_codex(
    athenaeum_root: Path,
    irc_jsonl: Path,
    cfr_jsonl: Path,
) -> dict:
    """Load IRC and CFR JSONL into the Codex-Tax-US codex.

    Returns stats: {irc_loaded, cfr_loaded, codex_path}.
    """
    codex_root = athenaeum_root / CODEX_NAME
    irc_dir = codex_root / "irc"
    cfr_dir = codex_root / "cfr"
    irc_dir.mkdir(parents=True, exist_ok=True)
    cfr_dir.mkdir(parents=True, exist_ok=True)

    # Write README
    readme = codex_root / "README.md"
    readme.write_text(
        f"""# {CODEX_NAME}

US tax research corpus: the Internal Revenue Code (Title 26) and the
Treasury Regulations (26 CFR). Built from primary public sources on
{datetime.now(timezone.utc).strftime("%Y-%m-%d")}.

## Sources

- **IRC Title 26** — Office of the Law Revision Counsel, US House of Representatives.
  XML bulk download, current through Public Law 119-100.
  https://uscode.house.gov/download/download.shtml
- **26 CFR (Treasury Regulations)** — Electronic Code of Federal Regulations (eCFR),
  Office of the Federal Register, National Archives. JSON/XML bulk download.
  https://www.ecfr.gov/current/title-26

## Structure

- `irc/§<NUM>.md` — Internal Revenue Code sections (~2,276 files)
- `cfr/§<NUM>.md` — Treasury Regulations sections (~6,154 files)
- `INDEX.md` — Master catalog of all sections with one-line summaries

## Usage

- **Humans** — open any `.md` file in your text editor or Obsidian.
- **AI agents (Taxa MCP)** — call `taxa_research(query)` for natural language
  queries; the FTS5 + vector search will find the right sections.
- **Taxa `taxa_cite(code)`** — exact lookup of a section by number.

## Update cadence

Both sources update within ~24 hours of new public laws and regulations.
For real production use, re-run the ingest pipeline weekly.
"""
    )

    # Load IRC
    irc_loaded = 0
    with open(irc_jsonl) as f:
        for line in f:
            rec = json.loads(line)
            section = IRCSection(**rec)
            fname = make_section_filename(section.section_num)
            if not fname or fname == "§.md":
                # Skip sections without a number (table-of-contents entries)
                continue
            (irc_dir / fname).write_text(render_irc_markdown(section))
            irc_loaded += 1
            if irc_loaded % 500 == 0:
                print(f"  loaded {irc_loaded} IRC sections...", flush=True)

    # Load CFR
    cfr_loaded = 0
    with open(cfr_jsonl) as f:
        for line in f:
            rec = json.loads(line)
            section = CFRSection(**rec)
            fname = make_section_filename(section.section_num)
            (cfr_dir / fname).write_text(render_cfr_markdown(section))
            cfr_loaded += 1
            if cfr_loaded % 1000 == 0:
                print(f"  loaded {cfr_loaded} CFR sections...", flush=True)

    # Write a basic INDEX.md (just the file listing for now; can be enriched later)
    index = codex_root / "INDEX.md"
    irc_files = sorted(irc_dir.glob("§*.md"))
    cfr_files = sorted(cfr_dir.glob("§*.md"))
    index.write_text(
        f"""# {CODEX_NAME} — Master Index

**Last updated:** {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
**IRC sections:** {irc_loaded}
**CFR sections:** {cfr_loaded}
**Total documents:** {irc_loaded + cfr_loaded}

## Directories

| Directory | Count | Range | Description |
|---|---|---|---|
| `irc/` | {irc_loaded} | §1 — §9833 | Internal Revenue Code (Title 26) |
| `cfr/` | {cfr_loaded} | §1.0-1 — §899 | Treasury Regulations (26 CFR) |

## Indexes

- **By citation:** see `by-citation.md` (regenerated on each ingest)
- **By topic:** TBD — needs topic modeling pass over the corpus

## Source citations

Every document contains its source URL in the YAML frontmatter (`source:` field)
and the body footer. For the authoritative legal text, always verify against
the source.
"""
    )

    return {
        "irc_loaded": irc_loaded,
        "cfr_loaded": cfr_loaded,
        "codex_path": str(codex_root),
    }


if __name__ == "__main__":
    import sys

    athenaeum = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "athenaeum"
    irc = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("data/irc_sections.jsonl")
    cfr = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("data/cfr_sections.jsonl")

    print(f"Loading into {athenaeum / CODEX_NAME}...")
    print(f"  IRC: {irc}")
    print(f"  CFR: {cfr}")
    print()
    stats = load_codex(athenaeum, irc, cfr)
    print()
    print(f"Done. {stats['irc_loaded']} IRC + {stats['cfr_loaded']} CFR = "
          f"{stats['irc_loaded'] + stats['cfr_loaded']} sections loaded into "
          f"{stats['codex_path']}")
